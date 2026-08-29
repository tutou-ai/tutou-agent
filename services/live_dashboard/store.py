"""SQLite-backed storage for live dashboard events."""

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from types import TracebackType
from typing import Any, Self

from .redaction import redact
from .schema import LiveEvent


class EventStore:
    """Persist a public event projection in a WAL-mode SQLite database."""

    def __init__(self, database: str | Path, *, retention: int = 1_000) -> None:
        if retention < 1:
            raise ValueError("retention must be positive")
        self.database = Path(database)
        self.retention = retention
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.database.touch(mode=0o600, exist_ok=True)
        self.database.chmod(0o600)
        self._lock = Lock()
        self._connection = sqlite3.connect(
            self.database,
            check_same_thread=False,
            timeout=5,
        )
        self._connection.row_factory = sqlite3.Row
        mode = self._connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            self._connection.close()
            raise sqlite3.OperationalError("live event store requires SQLite WAL mode")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL
            )
            """
        )
        self._connection.commit()
        self._chmod_private_files()

    def _chmod_private_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(f"{self.database}{suffix}").chmod(0o600)
            except FileNotFoundError:
                pass

    def append(self, payload: LiveEvent | Mapping[str, Any]) -> LiveEvent:
        """Validate, redact, and persist one live event."""

        event = payload if isinstance(payload, LiveEvent) else LiveEvent.model_validate(payload)
        public_payload = redact(event.model_dump(mode="json"))
        stored_event = LiveEvent.model_validate(public_payload)
        encoded = json.dumps(public_payload, separators=(",", ":"), sort_keys=True)
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO live_events(event_id, payload) VALUES (?, ?)",
                (stored_event.id, encoded),
            )
            self._connection.execute(
                "DELETE FROM live_events WHERE sequence NOT IN ("
                "SELECT sequence FROM live_events ORDER BY sequence DESC LIMIT ?"
                ")",
                (self.retention,),
            )
        self._chmod_private_files()
        return stored_event

    def history(self, *, limit: int | None = None) -> list[LiveEvent]:
        """Return persisted events in insertion order."""

        query = "SELECT payload FROM live_events ORDER BY sequence ASC"
        parameters: tuple[int, ...] = ()
        if limit is not None:
            query = (
                "SELECT payload FROM ("
                "SELECT sequence, payload FROM live_events ORDER BY sequence DESC LIMIT ?"
                ") ORDER BY sequence ASC"
            )
            parameters = (limit,)
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return [LiveEvent.model_validate_json(row["payload"]) for row in rows]

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        with self._lock:
            self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
