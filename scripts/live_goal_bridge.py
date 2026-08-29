#!/usr/bin/env python3
"""Publish sanitized standing-goal progress to Tutou Live."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from typing import Any

import live_event


def _public_session_id(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8", "surrogatepass")).hexdigest()[:12]
    return f"session-{digest}"


def project_goal(
    session_id: str,
    state: Any,
    *,
    host: str | None = None,
    git_sha: str | None = None,
) -> dict[str, str]:
    """Project goal counters without exposing goal, subgoal, gate, or judge text."""
    status = str(getattr(state, "status", "missing") or "missing")
    turns_used = int(getattr(state, "turns_used", 0) or 0)
    max_turns = int(getattr(state, "max_turns", 0) or 0)
    subgoals = list(getattr(state, "subgoals", ()) or ())
    gates = list(getattr(state, "gates", ()) or ())
    passing = sum(getattr(gate, "last_exit_code", None) == 0 for gate in gates)
    event = {
        "goal_id": _public_session_id(session_id),
        "stage": "goal",
        "status": status,
        "action": (
            f"Goal {status}; turns={turns_used}/{max_turns}; "
            f"subgoals={len(subgoals)}; gates={len(gates)}; passing_gates={passing}"
        ),
    }
    if host:
        event["host"] = host
    if git_sha:
        event["git_sha"] = git_sha
    return event


def load_goal_state(session_id: str) -> Any:
    from hermes_cli.goals import GoalManager

    return GoalManager(session_id).state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish status-only standing-goal progress to Tutou Live."
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--host", default="local")
    parser.add_argument("--git-sha")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    interval = min(max(float(args.interval), 0.5), 300.0)
    previous: str | None = None
    while True:
        state = load_goal_state(args.session_id)
        event = project_goal(
            args.session_id,
            state,
            host=args.host,
            git_sha=args.git_sha,
        )
        fingerprint = json.dumps(event, sort_keys=True, separators=(",", ":"))
        if fingerprint != previous:
            result = live_event.publish_event(event)
            print(
                json.dumps(
                    {
                        "ok": result.ok,
                        "status_code": result.status_code,
                        "attempts": result.attempts,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
            if not result.ok and args.once:
                return 1
            previous = fingerprint if result.ok else previous
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
