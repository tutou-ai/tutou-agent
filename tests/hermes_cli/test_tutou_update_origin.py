"""Tutou updates must never replace the fork with upstream Hermes."""


def test_tutou_is_the_official_self_update_repository() -> None:
    from hermes_cli import update_cmd

    assert update_cmd.OFFICIAL_REPO_URL == "https://github.com/tutou-ai/tutou-agent.git"
    assert update_cmd.OFFICIAL_REPO_URLS == {
        "https://github.com/tutou-ai/tutou-agent.git",
        "git@github.com:tutou-ai/tutou-agent.git",
        "https://github.com/tutou-ai/tutou-agent",
        "git@github.com:tutou-ai/tutou-agent",
    }


def test_zip_fallback_uses_tutou_repository_and_archive_root() -> None:
    from hermes_cli import update_cmd

    zip_url = getattr(update_cmd, "_official_zip_url")
    zip_root = getattr(update_cmd, "_official_zip_root")

    assert zip_url("main") == (
        "https://github.com/tutou-ai/tutou-agent/archive/refs/heads/main.zip"
    )
    assert zip_root("main") == "tutou-agent-main"
