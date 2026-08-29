"""Runtime version reporting must survive the distribution rename."""


def test_codex_app_server_reports_canonical_tutou_version():
    from hermes_cli import __version__
    import agent.transports.codex_app_server_session as session_mod

    assert getattr(session_mod, "_get_hermes_version")() == __version__


def test_qqbot_reports_canonical_tutou_version():
    from hermes_cli import __version__
    from gateway.platforms.qqbot.utils import _get_hermes_version

    assert _get_hermes_version() == __version__
