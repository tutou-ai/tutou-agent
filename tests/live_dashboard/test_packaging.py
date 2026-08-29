from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def test_live_dashboard_package_and_static_assets_ship_in_wheels() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    includes = data["tool"]["setuptools"]["packages"]["find"]["include"]
    package_data = data["tool"]["setuptools"]["package-data"]

    assert "services" in includes
    assert "services.*" in includes
    assert package_data["services.live_dashboard"] == ["static/*"]
