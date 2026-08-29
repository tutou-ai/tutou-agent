"""Tutou executable aliases must retain Hermes process identity checks."""

import pytest

from hermes_state import _looks_like_hermes


@pytest.mark.parametrize(
    "command",
    [
        "tutou serve --host 127.0.0.1",
        "tutou gateway run",
        "tutou chat -q hello",
        "/opt/tutou/bin/tutou-agent --help",
        "/opt/tutou/bin/tutou-acp",
    ],
)
def test_tutou_commands_are_recognized_as_state_db_holders(command: str) -> None:
    assert _looks_like_hermes(command) is True


def test_unrelated_tutou_prefixed_script_is_not_a_state_db_holder() -> None:
    assert _looks_like_hermes("python /tmp/tutou-notes.py") is False
    assert _looks_like_hermes("python /tmp/tutou-agent-backup.py") is False
    assert _looks_like_hermes(
        "/home/tutou/bin/python /tmp/unrelated.py serve --host 127.0.0.1"
    ) is False
