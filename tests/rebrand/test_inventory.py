"""Tests for the deterministic legacy-identity inventory scanner."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _tracked_repo(tmp_path: Path, files: dict[str, str | bytes]) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git("init", "--quiet", cwd=root)
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    _git("add", "--", ".", cwd=root)
    _git(
        "-c",
        "user.name=Inventory Test",
        "-c",
        "user.email=inventory@example.test",
        "commit",
        "--quiet",
        "-m",
        "fixture",
        cwd=root,
    )
    return root


def test_scan_repository_finds_identity_tokens_case_insensitively(tmp_path: Path) -> None:
    root = _tracked_repo(
        tmp_path,
        {"notes.txt": "Hermes hermes HERMES HeRmEs\nHermes\n"},
    )

    from scripts.rebrand.inventory import scan_repository

    inventory = scan_repository(root)

    assert inventory["records"] == [
        {
            "path": "notes.txt",
            "line": 1,
            "column": 1,
            "token": "Hermes",
            "kind": "identity",
            "scope": "notes.txt",
        },
        {
            "path": "notes.txt",
            "line": 1,
            "column": 8,
            "token": "hermes",
            "kind": "identity",
            "scope": "notes.txt",
        },
        {
            "path": "notes.txt",
            "line": 1,
            "column": 15,
            "token": "HERMES",
            "kind": "identity",
            "scope": "notes.txt",
        },
        {
            "path": "notes.txt",
            "line": 1,
            "column": 22,
            "token": "HeRmEs",
            "kind": "identity",
            "scope": "notes.txt",
        },
        {
            "path": "notes.txt",
            "line": 2,
            "column": 1,
            "token": "Hermes",
            "kind": "identity",
            "scope": "notes.txt",
        },
    ]


def test_scan_repository_finds_legacy_urls_without_line_contents(tmp_path: Path) -> None:
    first_line = (
        "See https://hermes-agent.nousresearch.com/docs and "
        "https://example.com/plain."
    )
    second_line = "Mirror https://github.com/NousResearch/Hermes-Agent)."
    third_line = "Open hermes://settings/profile now."
    root = _tracked_repo(
        tmp_path,
        {"docs/links.md": "\n".join((first_line, second_line, third_line))},
    )

    from scripts.rebrand.inventory import scan_repository

    records = [
        record
        for record in scan_repository(root)["records"]
        if record["kind"] == "url"
    ]

    assert records == [
        {
            "path": "docs/links.md",
            "line": 1,
            "column": first_line.index("https://") + 1,
            "token": "https://hermes-agent.nousresearch.com/docs",
            "kind": "url",
            "scope": "docs",
        },
        {
            "path": "docs/links.md",
            "line": 2,
            "column": second_line.index("https://") + 1,
            "token": "https://github.com/NousResearch/Hermes-Agent",
            "kind": "url",
            "scope": "docs",
        },
        {
            "path": "docs/links.md",
            "line": 3,
            "column": third_line.index("hermes://") + 1,
            "token": "hermes://settings/profile",
            "kind": "url",
            "scope": "docs",
        },
    ]


def test_scan_repository_finds_hermes_in_tracked_path_components(tmp_path: Path) -> None:
    legacy_path = "src/hermes_tools/Hermes-file.txt"
    root = _tracked_repo(
        tmp_path,
        {
            "HERMES.md": "plain text",
            legacy_path: "plain text",
            "src/plain.txt": "plain text",
        },
    )
    (root / "untracked-hermes.txt").write_text("Hermes", encoding="utf-8")

    from scripts.rebrand.inventory import scan_repository

    records = [
        record
        for record in scan_repository(root)["records"]
        if record["kind"] == "path"
    ]

    assert records == [
        {
            "path": "HERMES.md",
            "line": 0,
            "column": 1,
            "token": "HERMES.md",
            "kind": "path",
            "scope": "HERMES.md",
        },
        {
            "path": legacy_path,
            "line": 0,
            "column": legacy_path.index("hermes_tools") + 1,
            "token": "hermes_tools",
            "kind": "path",
            "scope": "src",
        },
        {
            "path": legacy_path,
            "line": 0,
            "column": legacy_path.index("Hermes-file.txt") + 1,
            "token": "Hermes-file.txt",
            "kind": "path",
            "scope": "src",
        },
    ]


def test_scan_repository_skips_nul_and_non_utf8_file_contents(tmp_path: Path) -> None:
    root = _tracked_repo(
        tmp_path,
        {
            "assets/nul.bin": b"prefix Hermes\0suffix hermes",
            "assets/non-utf8.bin": b"prefix HERMES\xffsuffix",
            "src/text.txt": "Hermes",
        },
    )

    from scripts.rebrand.inventory import scan_repository

    records = scan_repository(root)["records"]

    assert records == [
        {
            "path": "src/text.txt",
            "line": 1,
            "column": 1,
            "token": "Hermes",
            "kind": "identity",
            "scope": "src",
        }
    ]


def test_inventory_cli_writes_stable_summary(tmp_path: Path) -> None:
    root = _tracked_repo(
        tmp_path,
        {
            "hermes.txt": "Hermes https://hermes-agent.nousresearch.com/docs\n",
            "plain.txt": "nothing",
        },
    )
    output = tmp_path / "inventory.json"

    from scripts.rebrand.inventory import main

    assert main(["--root", str(root), "--output", str(output)]) == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["summary"] == {
        "identity": 2,
        "path": 1,
        "url": 1,
        "total": 4,
    }
    assert len(data["source_sha"]) == 40
    assert all(character in "0123456789abcdef" for character in data["source_sha"])
    assert data["records"] == sorted(
        data["records"],
        key=lambda row: (
            row["path"], row["line"], row["column"], row["kind"], row["token"]
        ),
    )
