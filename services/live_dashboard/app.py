"""FastAPI application for authenticated live dashboard events."""

import asyncio
import json
import os
import secrets
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError

from .schema import LiveEvent
from .store import EventStore

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8791
DEFAULT_RETENTION = 1_000
DEFAULT_MAX_REQUEST_BYTES = 64 * 1024


class LiveEventBroker:
    """One-process, bounded fan-out for authenticated SSE subscribers."""

    def __init__(
        self,
        *,
        queue_size: int = 100,
        max_subscribers: int = 100,
        heartbeat_seconds: float = 15.0,
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be positive")
        if max_subscribers < 1:
            raise ValueError("max_subscribers must be positive")
        self.queue_size = queue_size
        self.max_subscribers = max_subscribers
        self.heartbeat_seconds = max(float(heartbeat_seconds), 0.01)
        self._subscribers: set[asyncio.Queue[LiveEvent]] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @staticmethod
    def _frame(event_name: str, payload: object) -> str:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return f"event: {event_name}\ndata: {data}\n\n"

    async def publish(self, event: LiveEvent) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    def register(self) -> asyncio.Queue[LiveEvent]:
        """Register a subscriber synchronously so no events can race history loading."""

        if len(self._subscribers) >= self.max_subscribers:
            raise RuntimeError("subscriber limit reached")
        queue: asyncio.Queue[LiveEvent] = asyncio.Queue(maxsize=self.queue_size)
        self._subscribers.add(queue)
        return queue

    def unregister(self, queue: asyncio.Queue[LiveEvent]) -> None:
        self._subscribers.discard(queue)

    def subscribe(
        self,
        history: Iterable[LiveEvent],
        *,
        queue: asyncio.Queue[LiveEvent] | None = None,
    ) -> AsyncIterator[str]:
        registered_queue = self.register() if queue is None else queue
        return self._stream(registered_queue, history)

    async def _stream(
        self,
        queue: asyncio.Queue[LiveEvent],
        history: Iterable[LiveEvent],
    ) -> AsyncIterator[str]:
        try:
            history_events = list(history)
            snapshot_ids = {event.id for event in history_events}
            queued_events: list[LiveEvent] = []
            while True:
                try:
                    event = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if event.id not in snapshot_ids:
                    queued_events.append(event)

            snapshot = {
                "events": [event.model_dump(mode="json") for event in history_events]
            }
            yield self._frame("snapshot", snapshot)
            for event in queued_events:
                yield self._frame("event", event.model_dump(mode="json"))
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=self.heartbeat_seconds
                    )
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield self._frame("event", event.model_dump(mode="json"))
        finally:
            self.unregister(queue)


def create_app(
    *,
    database: str | Path | None = None,
    token: str | None = None,
    retention: int = DEFAULT_RETENTION,
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    static_directory: str | Path | None = None,
) -> FastAPI:
    """Create an isolated live dashboard application."""

    database_path = (
        Path(database)
        if database is not None
        else Path(os.getenv("TUTOU_LIVE_DB", "live-events.db"))
    )
    static_path = (
        Path(static_directory)
        if static_directory is not None
        else Path(__file__).with_name("static")
    )
    expected_token = token if token is not None else os.getenv("TUTOU_LIVE_TOKEN")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.store = await asyncio.to_thread(
            EventStore,
            database_path,
            retention=retention,
        )
        application.state.broker = LiveEventBroker()
        try:
            yield
        finally:
            await asyncio.to_thread(application.state.store.close)

    application = FastAPI(title="Tutou Live Dashboard", lifespan=lifespan)

    def require_bearer(authorization: str | None = Header(default=None)) -> None:
        if expected_token is None or not expected_token.strip():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TUTOU_LIVE_TOKEN is not configured",
            )
        scheme, _, supplied_token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(
            supplied_token,
            expected_token,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def live_asset(name: str, media_type: str) -> FileResponse:
        path = static_path / name
        if not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(path, media_type=media_type)

    @application.get("/live", include_in_schema=False)
    @application.get("/live/", include_in_schema=False)
    async def live_index() -> FileResponse:
        return live_asset("index.html", "text/html")

    @application.get("/live/app.js", include_in_schema=False)
    async def live_javascript() -> FileResponse:
        return live_asset("app.js", "application/javascript")

    @application.get("/live/style.css", include_in_schema=False)
    async def live_stylesheet() -> FileResponse:
        return live_asset("style.css", "text/css")

    @application.get("/api/live/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/live/history", dependencies=[Depends(require_bearer)])
    async def history() -> list[LiveEvent]:
        return await asyncio.to_thread(application.state.store.history)

    @application.get("/api/live/stream", dependencies=[Depends(require_bearer)])
    async def stream() -> StreamingResponse:
        broker: LiveEventBroker = application.state.broker
        try:
            queue = broker.register()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Live stream subscriber limit reached",
            ) from exc
        try:
            initial = await asyncio.to_thread(application.state.store.history)
        except BaseException:
            broker.unregister(queue)
            raise
        return StreamingResponse(
            broker.subscribe(initial, queue=queue),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "X-Accel-Buffering": "no",
            },
        )

    @application.post(
        "/api/live/events",
        dependencies=[Depends(require_bearer)],
        status_code=status.HTTP_201_CREATED,
    )
    async def post_event(request: Request) -> LiveEvent:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid Content-Length header",
                ) from exc
            if declared_size > max_request_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="Event request body is too large",
                )

        chunks: list[bytes] = []
        actual_size = 0
        async for chunk in request.stream():
            actual_size += len(chunk)
            if actual_size > max_request_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="Event request body is too large",
                )
            chunks.append(chunk)
        try:
            payload = json.loads(b"".join(chunks))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Event request body must be valid JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Event request body must be a JSON object",
            )
        try:
            event = await asyncio.to_thread(application.state.store.append, payload)
            await application.state.broker.publish(event)
            return event
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=exc.errors(include_url=False),
            ) from exc

    return application


app = create_app()


def main() -> None:
    """Run the development service on the collision-safe default port."""

    import uvicorn

    uvicorn.run(
        "services.live_dashboard.app:app",
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
    )


if __name__ == "__main__":
    main()
