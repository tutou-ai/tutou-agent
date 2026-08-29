"""Fail-closed handling for legacy hermes-agent installations."""

from pathlib import Path
from types import SimpleNamespace

import pytest


def test_legacy_probe_runs_in_resolved_target_interpreter(monkeypatch, tmp_path):
    import hermes_cli.main as main_mod

    target_python = tmp_path / "target-venv" / "bin" / "python"
    target_python.parent.mkdir(parents=True)
    target_python.touch()
    captured = {}

    monkeypatch.setattr(
        main_mod,
        "_resolve_install_target_python",
        lambda prefix, env: target_python,
    )

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=42, stderr="", stdout="")

    monkeypatch.setattr(main_mod.subprocess, "run", fake_run)

    probe = getattr(main_mod, "_target_has_legacy_distribution")
    assert probe(["uv", "pip"], {"VIRTUAL_ENV": str(target_python.parent.parent)}) is True
    assert captured["argv"][0] == str(target_python)
    assert Path(captured["kwargs"]["cwd"]).resolve() != main_mod.PROJECT_ROOT.resolve()
    assert "PYTHONPATH" not in captured["kwargs"]["env"]


def test_legacy_target_is_rejected_before_install(monkeypatch):
    import hermes_cli.main as main_mod

    install_ran: list[bool] = []
    monkeypatch.setattr(main_mod, "_is_windows", lambda: False)
    monkeypatch.setattr(
        main_mod,
        "_target_has_legacy_distribution",
        lambda prefix, env: True,
        raising=False,
    )
    monkeypatch.setattr(
        main_mod,
        "_run_quarantined_install",
        lambda *args, **kwargs: install_ran.append(True),
    )

    with pytest.raises(RuntimeError, match="legacy hermes-agent"):
        main_mod._install_python_dependencies_with_optional_fallback(["uv", "pip"])

    assert install_ran == []


def test_clean_target_preserves_normal_update_flow(monkeypatch):
    import hermes_cli.main as main_mod

    events: list[str] = []
    monkeypatch.setattr(main_mod, "_is_windows", lambda: False)
    monkeypatch.setattr(
        main_mod,
        "_target_has_legacy_distribution",
        lambda prefix, env: False,
        raising=False,
    )
    monkeypatch.setattr(
        main_mod,
        "_run_quarantined_install",
        lambda *args, **kwargs: events.append("install"),
    )
    monkeypatch.setattr(
        main_mod,
        "_verify_console_scripts_installed",
        lambda *args, **kwargs: events.append("verify"),
    )

    main_mod._install_python_dependencies_with_optional_fallback(["uv", "pip"])

    assert events == ["install", "verify"]
