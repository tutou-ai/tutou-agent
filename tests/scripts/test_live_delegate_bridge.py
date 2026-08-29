"""Tests for the cursor-based, status-only delegation bridge."""

from __future__ import annotations

import json
import re
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import live_delegate_bridge as bridge  # noqa: E402
import live_event  # noqa: E402


def test_summarize_lines_emits_status_only_and_never_raw_content(tmp_path: Path) -> None:
    secret = "sk-proj-" + "S" * 24
    transcript = tmp_path / "deleg_safe" / "task-0.log"
    lines = [
        f"12:00:00 user     | kickoff: private prompt {secret}\n",
        f"12:00:01 tool     | -> terminal(--password {secret})\n",
        f"12:00:02 result   | terminal ERROR 0.1s: raw output {secret}\n",
        f"12:00:03 assistant| private response {secret}\n",
        f"12:00:04 final    | status=completed summary: private {secret}\n",
    ]

    event = bridge.summarize_lines(
        transcript,
        lines,
        goal_id="goal-public",
        workstream_id="card-public",
        agent_id="agent-public",
    )

    assert {key: value for key, value in event.items() if key != "action"} == {
        "goal_id": "goal-public",
        "workstream": "card-public",
        "agent_id": "agent-public",
        "stage": "delegation",
        "status": "completed",
    }
    assert re.fullmatch(
        r"Delegation delegation-[0-9a-f]{12}/task-[0-9a-f]{12} completed; "
        r"tools=1; tool_errors=1",
        event["action"],
    )
    rendered = json.dumps(live_event.sanitize_event(event))
    assert secret not in rendered
    assert "private prompt" not in rendered
    assert "password" not in rendered
    assert "raw output" not in rendered
    assert "private response" not in rendered


def test_summarize_lines_hashes_path_derived_identifiers(tmp_path: Path) -> None:
    transcript = tmp_path / "delegation-private-customer" / "task-secret-ticket.log"

    event = bridge.summarize_lines(
        transcript,
        ["12:00:00 start | private kickoff\n"],
    )

    assert event is not None
    assert "delegation-private-customer" not in event["action"]
    assert "task-secret-ticket" not in event["action"]
    assert re.fullmatch(
        r"Delegation delegation-[0-9a-f]{12}/task-[0-9a-f]{12} running; "
        r"tools=0; tool_errors=0",
        event["action"],
    )
    assert bridge.summarize_lines(
        transcript,
        ["12:00:00 start | private kickoff\n"],
    ) == event


def test_poll_once_persists_cursor_and_waits_for_complete_appended_lines(
    tmp_path: Path,
) -> None:
    root = tmp_path / "live"
    log = root / "deleg_cursor" / "task-2.log"
    log.parent.mkdir(parents=True)
    complete = (
        "=== header ===\n"
        "12:00:00 user     | private prompt\n"
        "12:00:01 start    | private kickoff\n"
    )
    partial = "12:00:02 final    | status=comp"
    log.write_text(complete + partial, encoding="utf-8")
    state_path = tmp_path / "cursor.json"
    published: list[dict[str, object]] = []

    def publisher(event, **_kwargs):
        published.append(event)
        return live_event.PublishResult(True, 202, 1)

    first = bridge.poll_once(root=root, state_path=state_path, publisher=publisher)

    assert first == bridge.PollResult(scanned=1, published=1, failed=0)
    assert published[0]["status"] == "running"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    cursor = next(iter(state["files"].values()))
    assert cursor["offset"] == len(complete.encode("utf-8"))
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600

    with log.open("a", encoding="utf-8") as handle:
        handle.write("leted summary: private response\n")
    second = bridge.poll_once(root=root, state_path=state_path, publisher=publisher)

    assert second == bridge.PollResult(scanned=1, published=1, failed=0)
    assert [event["status"] for event in published] == ["running", "completed"]
    assert "private" not in json.dumps(published)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    cursor = next(iter(state["files"].values()))
    assert cursor["offset"] == log.stat().st_size


def test_poll_once_discards_oversized_line_and_advances_to_following_event(
    tmp_path: Path,
) -> None:
    root = tmp_path / "live"
    log = root / "deleg_large" / "task-3.log"
    log.parent.mkdir(parents=True)
    log.write_bytes(
        b"x" * 65_537 + b"\n12:00:00 start | private kickoff\n"
    )
    state_path = tmp_path / "cursor.json"
    published: list[dict[str, object]] = []

    def publisher(event, **_kwargs):
        published.append(event)
        return live_event.PublishResult(True, 202, 1)

    result = bridge.poll_once(
        root=root,
        state_path=state_path,
        publisher=publisher,
    )

    assert result == bridge.PollResult(scanned=1, published=1, failed=0)
    assert [event["status"] for event in published] == ["running"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    cursor = next(iter(state["files"].values()))
    assert cursor["offset"] == log.stat().st_size


def test_poll_once_does_not_advance_cursor_when_publish_fails(tmp_path: Path) -> None:
    root = tmp_path / "live"
    log = root / "deleg_retry" / "task-0.log"
    log.parent.mkdir(parents=True)
    log.write_text("12:00:00 start | private kickoff\n", encoding="utf-8")
    state_path = tmp_path / "cursor.json"

    result = bridge.poll_once(
        root=root,
        state_path=state_path,
        publisher=lambda *_args, **_kwargs: live_event.PublishResult(
            False, 503, 1, "HTTP 503"
        ),
    )

    assert result == bridge.PollResult(scanned=1, published=0, failed=1)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["files"] == {}


def test_bridge_cli_has_safe_watch_controls_and_no_token_argument() -> None:
    parser = bridge.build_parser()
    help_text = parser.format_help()

    assert "--once" in help_text
    assert "--interval" in help_text
    assert "--root" in help_text
    assert "--state" in help_text
    assert "--token" not in help_text.lower()
