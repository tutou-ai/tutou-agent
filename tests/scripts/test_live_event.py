"""Tests for the explicit, sanitized live-event publisher CLI."""

from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import live_event  # noqa: E402


class _Recorder(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []
    statuses: list[int] = [202]

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).requests.append(
            {"path": self.path, "headers": dict(self.headers), "body": body}
        )
        status = type(self).statuses.pop(0)
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b'authentication_token_should_not_be_printed')

    def log_message(self, _format: str, *args: object) -> None:
        pass


@contextmanager
def _recording_server(*statuses: int) -> Iterator[tuple[str, type[_Recorder]]]:
    handler = type("Recorder", (_Recorder,), {"requests": [], "statuses": list(statuses)})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/api/live/events", handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class _RedirectRecorder(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []

    def _record_request(self, body: bytes) -> None:
        type(self).requests.append(
            {"path": self.path, "headers": dict(self.headers), "body": body}
        )

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("Content-Length", "0"))
        self._record_request(self.rfile.read(length))
        self.send_response(302)
        self.send_header("Location", "/redirected")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._record_request(b"")
        self.send_response(202)
        self.end_headers()

    def log_message(self, _format: str, *args: object) -> None:
        pass


@contextmanager
def _redirecting_server() -> Iterator[tuple[str, type[_RedirectRecorder]]]:
    handler = type("RedirectRecorder", (_RedirectRecorder,), {"requests": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/api/live/events", handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_sanitize_event_keeps_only_bounded_public_fields() -> None:
    event = live_event.sanitize_event(
        {
            "stage": "test",
            "status": "passed",
            "action": "x" * 700,
            "prompt": "private user request",
            "tool_args": {"password": "do-not-send"},
        }
    )

    assert event["stage"] == "test"
    assert event["status"] == "passed"
    assert len(event["action"]) <= live_event.FIELD_LIMITS["action"]
    assert "prompt" not in event
    assert "tool_args" not in event


def test_sanitize_event_redacts_secret_bearing_text() -> None:
    secret = "sk-proj-" + "A" * 24
    private_key = "-----BEGIN PRIVATE KEY----- hidden -----END PRIVATE KEY-----"
    event = live_event.sanitize_event(
        {
            "action": (
                f"Authorization: Bearer {secret} "
                f"API_TOKEN={secret} "
                f"https://alice:{secret}@example.test/run?token={secret} "
                f"{private_key} .env"
            )
        }
    )

    rendered = event["action"]
    assert secret not in rendered
    assert "alice:" not in rendered
    assert "PRIVATE KEY" not in rendered
    assert ".env" not in rendered
    assert "[redacted]" in rendered


def test_sanitize_event_accepts_only_safe_http_links() -> None:
    event = live_event.sanitize_event(
        {
            "links": [
                "https://ci.example.test/job/7",
                "https://alice:pw@example.test/run?token=hidden&view=1",
                "file:///home/user/.env",
                "javascript:alert(1)",
            ]
        }
    )

    assert event["links"] == [
        "https://ci.example.test/job/7",
        "https://redacted@example.test/run?token=[redacted]&view=1",
    ]


def test_publish_event_rejects_plain_http_for_non_loopback_hosts(monkeypatch) -> None:
    monkeypatch.setenv("TUTOU_LIVE_TOKEN", "test-token")

    with pytest.raises(live_event.LivePublishError, match="HTTPS"):
        live_event.publish_event(
            {"stage": "test", "status": "running"},
            url="http://192.0.2.1/api/live/events",
            retries=0,
        )


def test_publish_event_does_not_forward_authorization_on_redirect(monkeypatch) -> None:
    token = "test-token"
    monkeypatch.setenv("TUTOU_LIVE_TOKEN", token)

    with _redirecting_server() as (url, handler):
        result = live_event.publish_event(
            {"stage": "test", "status": "running"},
            url=url,
            retries=0,
        )

    assert result.ok is True
    assert [request["path"] for request in handler.requests] == [
        "/api/live/events",
        "/redirected",
    ]
    first_headers = handler.requests[0]["headers"]
    redirected_headers = handler.requests[1]["headers"]
    assert isinstance(first_headers, dict)
    assert isinstance(redirected_headers, dict)
    assert first_headers["Authorization"] == f"Bearer {token}"
    assert "Authorization" not in redirected_headers


def test_publish_event_posts_sanitized_json_with_env_token(monkeypatch) -> None:
    token = "live-token-" + "Z" * 20
    with _recording_server(202) as (url, handler):
        monkeypatch.setenv("TUTOU_LIVE_URL", url)
        monkeypatch.setenv("TUTOU_LIVE_TOKEN", token)

        result = live_event.publish_event(
            {"stage": "test", "status": "passed", "prompt": token},
            timeout=1,
            retries=0,
        )

    assert result.ok is True
    assert result.status_code == 202
    assert result.attempts == 1
    assert len(handler.requests) == 1
    request = handler.requests[0]
    assert request["path"] == "/api/live/events"
    headers = request["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == f"Bearer {token}"
    assert headers["Content-Type"] == "application/json"
    body = json.loads(request["body"])
    assert body["stage"] == "test"
    assert body["status"] == "passed"
    assert body["id"]
    assert body["timestamp"].endswith("Z")
    assert "prompt" not in body
    assert token not in json.dumps(body)


def test_publish_event_retries_transient_http_errors(monkeypatch) -> None:
    pauses: list[float] = []
    with _recording_server(503, 429, 202) as (url, handler):
        monkeypatch.setenv("TUTOU_LIVE_TOKEN", "test-token")
        monkeypatch.setattr(live_event.time, "sleep", pauses.append)

        result = live_event.publish_event(
            {"stage": "deploy", "status": "running"},
            url=url,
            timeout=1,
            retries=2,
        )

    assert result.ok is True
    assert result.status_code == 202
    assert result.attempts == 3
    assert len(handler.requests) == 3
    assert pauses == [0.1, 0.2]


def test_publish_event_never_copies_ingest_token_into_body(monkeypatch) -> None:
    token = "live-token-" + "Q" * 20
    with _recording_server(202) as (url, handler):
        monkeypatch.setenv("TUTOU_LIVE_TOKEN", token)

        result = live_event.publish_event(
            {"stage": "test", "status": "running", "action": f"using {token}"},
            url=url,
            retries=0,
        )

    assert result.ok is True
    assert token not in handler.requests[0]["body"].decode("utf-8")


def test_publish_event_does_not_retry_client_error_or_return_response_body(
    monkeypatch,
) -> None:
    pauses: list[float] = []
    with _recording_server(400, 202) as (url, handler):
        monkeypatch.setenv("TUTOU_LIVE_TOKEN", "test-token")
        monkeypatch.setattr(live_event.time, "sleep", pauses.append)

        result = live_event.publish_event(
            {"stage": "test", "status": "failed"}, url=url, retries=3
        )

    assert result == live_event.PublishResult(
        ok=False, status_code=400, attempts=1, error="HTTP 400"
    )
    assert len(handler.requests) == 1
    assert pauses == []
    assert "authentication_token" not in (result.error or "")


def test_cli_uses_env_token_and_prints_only_bounded_result(monkeypatch, capsys) -> None:
    token = "live-token-" + "W" * 20
    with _recording_server(202) as (url, _handler):
        monkeypatch.setenv("TUTOU_LIVE_URL", url)
        monkeypatch.setenv("TUTOU_LIVE_TOKEN", token)

        return_code = live_event.main(
            [
                "--stage",
                "test",
                "--status",
                "passed",
                "--action",
                "owned tests passed",
                "--timeout",
                "1",
                "--retries",
                "0",
            ]
        )

    output = capsys.readouterr()
    assert return_code == 0
    assert len(output.out) <= 256
    assert json.loads(output.out) == {
        "ok": True,
        "status_code": 202,
        "attempts": 1,
    }
    assert token not in output.out + output.err
    assert "--token" not in live_event.build_parser().format_help().lower()


def test_cli_accepts_only_canonical_workstream_option(monkeypatch, capsys) -> None:
    with _recording_server(202) as (url, handler):
        monkeypatch.setenv("TUTOU_LIVE_URL", url)
        monkeypatch.setenv("TUTOU_LIVE_TOKEN", "test-token")

        return_code = live_event.main(
            [
                "--stage",
                "test",
                "--status",
                "passed",
                "--workstream",
                "live-core",
                "--retries",
                "0",
            ]
        )

    assert return_code == 0
    assert json.loads(handler.requests[0]["body"])["workstream"] == "live-core"
    help_text = live_event.build_parser().format_help()
    assert "--workstream " in help_text
    assert "--workstream-id" not in help_text
    assert "--card-id" not in help_text
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_publisher_uses_backend_canonical_field_names() -> None:
    event = live_event.sanitize_event(
        {
            "id": "evt-fixed",
            "workstream": "live-core",
            "stage": "test",
            "status": "passed",
            "workstream_id": "must-not-survive",
            "card_id": "must-not-survive",
        }
    )

    assert event["id"] == "evt-fixed"
    assert event["workstream"] == "live-core"
    assert "event_id" not in event
    assert "workstream_id" not in event
    assert "card_id" not in event
