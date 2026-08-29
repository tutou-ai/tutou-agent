#!/usr/bin/env python3
"""Publish explicitly invoked, sanitized events to Tutou Live."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_URL = "https://agent.tutou.ai/api/live/events"
DEFAULT_TIMEOUT = 5.0
DEFAULT_RETRIES = 2
MAX_RESPONSE_BYTES = 2048

FIELD_LIMITS = {
    "id": 80,
    "timestamp": 40,
    "goal_id": 128,
    "workstream": 128,
    "agent_id": 128,
    "model": 128,
    "host": 128,
    "stage": 64,
    "status": 64,
    "action": 512,
    "output_excerpt": 1000,
    "test_result": 512,
    "git_sha": 64,
}


_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?"
    r"-----END [^-\r\n]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_AUTH_RE = re.compile(
    r"(?i)\b(authorization\s*[:=]\s*)(?:bearer|basic)\s+[^\s,;]+"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|API_KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL)"
    r"[A-Z0-9_]*\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;&#]+)"
)
_URL_USERINFO_RE = re.compile(r"(?i)(https?://)[^/@\s]+@")
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:access_token|api_key|key|password|secret|token)=)[^&#\s]*"
)
_ENV_PATH_RE = re.compile(r"(?i)(?:[\w./\\-]*\.env(?:\.[\w-]+)?)")
_TOKEN_SHAPE_RE = re.compile(
    r"(?i)\b(?:sk-(?:proj-)?|gh[pousr]_|xox[baprs]-)[A-Z0-9_-]{12,}\b"
)


def sanitize_text(value: Any, limit: int) -> str:
    """Redact common credentials and return one bounded line."""
    text = " ".join(str(value).split())
    text = _PRIVATE_KEY_RE.sub("[redacted]", text)
    text = _AUTH_RE.sub(r"\1[redacted]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(r"\1[redacted]", text)
    text = _URL_USERINFO_RE.sub(r"\1redacted@", text)
    text = _QUERY_SECRET_RE.sub(r"\1[redacted]", text)
    text = _ENV_PATH_RE.sub("[redacted]", text)
    text = _TOKEN_SHAPE_RE.sub("[redacted]", text)
    return text[:limit]


def sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return an allowlisted, string-only, bounded event projection."""
    sanitized: dict[str, Any] = {}
    for key, limit in FIELD_LIMITS.items():
        value = event.get(key)
        if value is None:
            continue
        sanitized[key] = sanitize_text(value, limit)
    raw_links = event.get("links")
    if isinstance(raw_links, (list, tuple)):
        links: list[str] = []
        for raw_link in raw_links[:8]:
            link = sanitize_text(raw_link, 500)
            parsed = urlsplit(link)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                links.append(link)
        if links:
            sanitized["links"] = links
    return sanitized


class LivePublishError(RuntimeError):
    """A safe-to-display publishing failure without response or token data."""


@dataclass(frozen=True)
class PublishResult:
    ok: bool
    status_code: int | None
    attempts: int
    error: str | None = None


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if parsed.scheme == "https" and parsed.hostname:
        return
    if parsed.scheme == "http" and parsed.hostname:
        try:
            is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            is_loopback = parsed.hostname.lower() == "localhost"
        if is_loopback:
            return
    raise LivePublishError("live event endpoint must use HTTPS unless it is loopback")


class _AuthorizationStrippingRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            _validate_endpoint(redirected.full_url)
            redirected.remove_header("Authorization")
        return redirected


_REDIRECT_SAFE_OPENER = build_opener(_AuthorizationStrippingRedirectHandler())


def publish_event(
    event: dict[str, Any],
    *,
    url: str | None = None,
    token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> PublishResult:
    """POST one sanitized event; credentials come from the environment."""
    endpoint = url or os.environ.get("TUTOU_LIVE_URL") or DEFAULT_URL
    _validate_endpoint(endpoint)
    credential = token if token is not None else os.environ.get("TUTOU_LIVE_TOKEN")
    if not credential:
        raise LivePublishError("TUTOU_LIVE_TOKEN is required")

    prepared = dict(event)
    prepared.setdefault("id", f"evt_{uuid.uuid4().hex}")
    prepared.setdefault("timestamp", _utc_timestamp())
    sanitized = sanitize_event(prepared)
    for key, value in sanitized.items():
        if isinstance(value, str):
            sanitized[key] = value.replace(credential, "[redacted]")
        elif isinstance(value, list):
            sanitized[key] = [item.replace(credential, "[redacted]") for item in value]
    body = json.dumps(
        sanitized, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "tutou-live-publisher/1",
        },
        method="POST",
    )
    attempts_allowed = min(max(int(retries), 0), 5) + 1
    bounded_timeout = min(max(float(timeout), 0.1), 30.0)
    for attempt in range(1, attempts_allowed + 1):
        try:
            with _REDIRECT_SAFE_OPENER.open(request, timeout=bounded_timeout) as response:
                response.read(MAX_RESPONSE_BYTES)
                status = int(response.status)
            return PublishResult(
                ok=200 <= status < 300,
                status_code=status,
                attempts=attempt,
                error=None if 200 <= status < 300 else f"HTTP {status}",
            )
        except HTTPError as exc:
            exc.read(MAX_RESPONSE_BYTES)
            status = int(exc.code)
            transient = status in {408, 425, 429} or 500 <= status < 600
            if not transient or attempt == attempts_allowed:
                return PublishResult(
                    ok=False,
                    status_code=status,
                    attempts=attempt,
                    error=f"HTTP {status}",
                )
        except (TimeoutError, URLError, OSError):
            if attempt == attempts_allowed:
                return PublishResult(
                    ok=False,
                    status_code=None,
                    attempts=attempt,
                    error="network error",
                )
        time.sleep(0.1 * (2 ** (attempt - 1)))

    raise AssertionError("unreachable")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish one sanitized status event to Tutou Live.",
        allow_abbrev=False,
    )
    for name in (
        "goal-id",
        "workstream",
        "agent-id",
        "model",
        "host",
        "stage",
        "status",
        "action",
        "output-excerpt",
        "test-result",
        "git-sha",
    ):
        parser.add_argument(f"--{name}")
    parser.add_argument("--link", action="append", default=[])
    parser.add_argument("--stdin", action="store_true", help="Read an event object as JSON from stdin.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    event: dict[str, Any] = {}
    if args.stdin:
        try:
            loaded = json.load(sys.stdin)
            if not isinstance(loaded, dict):
                raise ValueError
            event.update(loaded)
        except (OSError, ValueError, json.JSONDecodeError):
            print('{"ok":false,"error":"invalid stdin JSON"}', file=sys.stderr)
            return 2
    for name in FIELD_LIMITS:
        if name in {"id", "timestamp"}:
            continue
        value = getattr(args, name, None)
        if value is not None:
            event[name] = value
    if args.link:
        event["links"] = args.link
    if not event.get("stage") or not event.get("status"):
        print('{"ok":false,"error":"stage and status are required"}', file=sys.stderr)
        return 2
    try:
        result = publish_event(event, timeout=args.timeout, retries=args.retries)
    except LivePublishError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    output: dict[str, Any] = {
        "ok": result.ok,
        "status_code": result.status_code,
        "attempts": result.attempts,
    }
    if result.error:
        output["error"] = result.error
    print(json.dumps(output, separators=(",", ":")))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
