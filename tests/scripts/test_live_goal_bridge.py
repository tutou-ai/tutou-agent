"""Tests for goal progress projection into Tutou Live."""

from __future__ import annotations

import re
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import live_goal_bridge as bridge  # noqa: E402
import live_event  # noqa: E402


def test_goal_projection_contains_counts_but_not_private_goal_text() -> None:
    private = "private goal content sk-proj-" + "S" * 24
    state = SimpleNamespace(
        status="active",
        turns_used=7,
        max_turns=500,
        subgoals=[private, "another private criterion"],
        gates=[SimpleNamespace(last_exit_code=0), SimpleNamespace(last_exit_code=1)],
        goal=private,
        last_reason=private,
    )

    event = bridge.project_goal("session-public", state, host="pc", git_sha="abc123")

    assert {key: value for key, value in event.items() if key != "goal_id"} == {
        "stage": "goal",
        "status": "active",
        "action": "Goal active; turns=7/500; subgoals=2; gates=2; passing_gates=1",
        "host": "pc",
        "git_sha": "abc123",
    }
    assert re.fullmatch(r"session-[0-9a-f]{12}", event["goal_id"])
    rendered = str(live_event.sanitize_event(event))
    assert private not in rendered
    assert "another private criterion" not in rendered


def test_goal_projection_hashes_session_identifier() -> None:
    session_id = "private-session-for-customer"
    state = SimpleNamespace(status="active")

    event = bridge.project_goal(session_id, state)

    assert session_id not in str(event)
    assert re.fullmatch(r"session-[0-9a-f]{12}", event["goal_id"])
    assert bridge.project_goal(session_id, state)["goal_id"] == event["goal_id"]


def test_goal_bridge_uses_generic_default_host_label(monkeypatch) -> None:
    private_hostname = "alice-private-workstation"
    monkeypatch.setattr(socket, "gethostname", lambda: private_hostname)

    args = bridge.build_parser().parse_args(["--session-id", "private-session"])

    assert args.host == "local"
    assert private_hostname not in str(vars(args))


def test_goal_bridge_cli_exposes_once_watch_without_token_argument() -> None:
    help_text = bridge.build_parser().format_help()

    assert "--session-id" in help_text
    assert "--once" in help_text
    assert "--interval" in help_text
    assert "--token" not in help_text.lower()
