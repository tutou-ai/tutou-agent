import os
import sqlite3
import stat

import pytest

from services.live_dashboard.redaction import REDACTED
from services.live_dashboard.store import EventStore


@pytest.mark.parametrize("retention", [0, -1])
def test_store_rejects_nonpositive_retention(tmp_path, retention):
    database = tmp_path / "events.db"

    with pytest.raises(ValueError, match="retention must be positive"):
        EventStore(database, retention=retention)

    assert not database.exists()


def test_store_keeps_database_and_wal_sidecars_private(tmp_path):
    database = tmp_path / "events.db"
    database.touch(mode=0o666)
    database.chmod(0o666)
    original_umask = os.umask(0)
    try:
        with EventStore(database) as store:
            store.append({"status": "running"})
            sqlite_files = [
                database,
                database.with_name(f"{database.name}-wal"),
                database.with_name(f"{database.name}-shm"),
            ]

            assert all(path.is_file() for path in sqlite_files)
            assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in sqlite_files)
    finally:
        os.umask(original_umask)


def test_store_uses_wal_and_persists_only_a_redacted_public_projection(tmp_path):
    database = tmp_path / "events.db"
    raw_secret = "do-not-persist-this-secret"

    with EventStore(database, retention=10) as store:
        created = store.append(
            {
                "goal_id": "goal-1",
                "status": "running",
                "action": f"https://example.test/run?token={raw_secret}",
                "prompt": f"raw prompt {raw_secret}",
                "message": {"content": raw_secret},
                "tool_payload": {"api_key": raw_secret},
            }
        )
        events = store.history()
        with sqlite3.connect(database) as connection:
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert journal_mode.lower() == "wal"
    assert [event.id for event in events] == [created.id]
    assert events[0].goal_id == "goal-1"
    assert REDACTED in (events[0].action or "")
    persisted = database.read_bytes()
    assert raw_secret.encode() not in persisted
    assert b"raw prompt" not in persisted
    assert b"tool_payload" not in persisted


def test_store_retains_only_the_newest_bounded_events(tmp_path):
    database = tmp_path / "events.db"

    with EventStore(database, retention=3) as store:
        for number in range(5):
            store.append({"status": f"event-{number}"})
        events = store.history()

    assert [event.status for event in events] == ["event-2", "event-3", "event-4"]
