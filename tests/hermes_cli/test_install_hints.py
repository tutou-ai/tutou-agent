"""Install guidance must never pull the upstream Hermes distribution."""

import pytest


@pytest.mark.parametrize("extra", ["vercel", "otlp", "messaging"])
def test_optional_extra_hint_uses_tutou_checkout(extra: str) -> None:
    from hermes_cli.install_hints import optional_extra_install_hint

    hint = optional_extra_install_hint(extra)

    assert hint == f"run from the Tutou Agent checkout: uv sync --extra {extra}"
    assert "hermes-agent" not in hint
    assert "pip install" not in hint
