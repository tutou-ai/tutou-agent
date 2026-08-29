#!/usr/bin/env python3
"""Tail delegation logs and publish status-only Tutou Live summaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import live_event

_LINE_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\s+([A-Za-z]+)\s*\|\s?(.*)$")
_STATUS_RE = re.compile(r"(?:^|\s)status=([A-Za-z_-]+)")
_ALLOWED_STATUSES = {
    "running",
    "completed",
    "failed",
    "error",
    "cancelled",
    "interrupted",
    "blocked",
}


def _public_id(value: str, prefix: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def summarize_lines(
    transcript: Path,
    lines: Iterable[str],
    *,
    goal_id: str | None = None,
    workstream_id: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any] | None:
    """Summarize lifecycle structure without forwarding any line content."""
    delegation_id = _public_id(transcript.parent.name, "delegation")
    task_id = _public_id(transcript.stem, "task")
    status: str | None = None
    tool_runs = 0
    tool_errors = 0
    for line in lines:
        match = _LINE_RE.match(line)
        if not match:
            continue
        role, content = match.groups()
        role = role.lower()
        if role == "start":
            status = "running"
        elif role == "tool":
            tool_runs += 1
            status = status or "running"
        elif role == "result":
            if re.search(r"\bERROR\b", content):
                tool_errors += 1
            status = status or "running"
        elif role == "final":
            status_match = _STATUS_RE.search(content)
            if status_match:
                candidate = status_match.group(1).lower()
                status = candidate if candidate in _ALLOWED_STATUSES else "failed"
    if status is None:
        return None
    public_status = "failed" if status in {"error", "interrupted"} else status
    action = (
        f"Delegation {delegation_id}/{task_id} {public_status}; "
        f"tools={tool_runs}; tool_errors={tool_errors}"
    )
    event: dict[str, Any] = {
        "stage": "delegation",
        "status": public_status,
        "action": action,
    }
    for key, value in (
        ("goal_id", goal_id),
        ("workstream", workstream_id),
        ("agent_id", agent_id),
    ):
        if value:
            event[key] = value
    return event


@dataclass(frozen=True)
class PollResult:
    scanned: int
    published: int
    failed: int


def _load_state(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "files": {}}
    if not isinstance(loaded, dict) or not isinstance(loaded.get("files"), dict):
        return {"version": 1, "files": {}}
    return loaded


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    payload = json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_complete_lines(
    path: Path, offset: int, limit: int = 65_536
) -> tuple[list[str], int]:
    with path.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read(limit + 1)
        first_newline = chunk.find(b"\n")
        oversized = first_newline >= limit or (
            first_newline < 0 and len(chunk) > limit
        )
        if oversized:
            if first_newline >= 0:
                next_line_offset = offset + first_newline + 1
            else:
                while True:
                    continuation = handle.read(limit)
                    if not continuation:
                        return [], handle.tell()
                    newline = continuation.find(b"\n")
                    if newline >= 0:
                        next_line_offset = handle.tell() - len(continuation) + newline + 1
                        break
            handle.seek(next_line_offset)
            chunk = handle.read(limit)
            newline = chunk.rfind(b"\n")
            if newline < 0:
                return [], next_line_offset
            complete = chunk[: newline + 1]
            return (
                complete.decode("utf-8", "replace").splitlines(keepends=True),
                next_line_offset + len(complete),
            )

        bounded_chunk = chunk[:limit]
        newline = bounded_chunk.rfind(b"\n")
        if newline < 0:
            return [], offset
        complete = bounded_chunk[: newline + 1]
        return (
            complete.decode("utf-8", "replace").splitlines(keepends=True),
            offset + len(complete),
        )


def poll_once(
    *,
    root: Path,
    state_path: Path,
    publisher: Callable[..., live_event.PublishResult] = live_event.publish_event,
    goal_id: str | None = None,
    workstream_id: str | None = None,
    agent_id: str | None = None,
    timeout: float = live_event.DEFAULT_TIMEOUT,
    retries: int = live_event.DEFAULT_RETRIES,
) -> PollResult:
    """Publish at most one structural summary per changed transcript."""
    state = _load_state(state_path)
    files = state["files"]
    scanned = published = failed = 0
    if not root.is_dir():
        return PollResult(scanned=0, published=0, failed=0)
    for path in sorted(root.glob("*/task-*.log"))[:1000]:
        if path.is_symlink() or not path.is_file():
            continue
        scanned += 1
        stat_result = path.stat()
        key = str(path.resolve())
        cursor = files.get(key) if isinstance(files.get(key), dict) else {}
        same_file = (
            cursor.get("device") == stat_result.st_dev
            and cursor.get("inode") == stat_result.st_ino
            and int(cursor.get("offset", 0)) <= stat_result.st_size
        )
        offset = int(cursor.get("offset", 0)) if same_file else 0
        lines, new_offset = _read_complete_lines(path, offset)
        if new_offset == offset:
            continue
        event = summarize_lines(
            path,
            lines,
            goal_id=goal_id,
            workstream_id=workstream_id,
            agent_id=agent_id,
        )
        if event is not None:
            result = publisher(event, timeout=timeout, retries=retries)
            if not result.ok:
                failed += 1
                continue
            published += 1
        files[key] = {
            "device": stat_result.st_dev,
            "inode": stat_result.st_ino,
            "offset": new_offset,
        }
    _save_state(state_path, state)
    return PollResult(scanned=scanned, published=published, failed=failed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish status-only summaries from Hermes delegation transcripts."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / ".hermes" / "cache" / "delegation" / "live",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=Path.home() / ".cache" / "tutou-agent" / "live-delegate-cursors.json",
    )
    parser.add_argument("--goal-id")
    parser.add_argument("--workstream")
    parser.add_argument("--agent-id")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    interval = min(max(float(args.interval), 0.25), 60.0)
    while True:
        result = poll_once(
            root=args.root,
            state_path=args.state,
            goal_id=args.goal_id,
            workstream_id=args.workstream,
            agent_id=args.agent_id,
        )
        print(json.dumps(result.__dict__, separators=(",", ":")), flush=True)
        if args.once:
            return 1 if result.failed else 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
