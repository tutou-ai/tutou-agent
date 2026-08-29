"""Tutou-safe dependency installation guidance."""


def optional_extra_install_hint(extra: str) -> str:
    """Return the canonical source-checkout command for an optional extra."""
    return f"run from the Tutou Agent checkout: uv sync --extra {extra}"
