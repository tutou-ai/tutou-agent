#!/usr/bin/env python3
"""Inventory legacy identity references in an immutable Git commit tree."""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_IDENTITY_PATTERN = re.compile(r"hermes", re.IGNORECASE)
_URL_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s<>'\"`]+")
_URL_TRAILING_PUNCTUATION = ".,;:!?)]}"


def _git(repository: Path, *args: str, text: bool = False) -> bytes | str:
    return subprocess.run(
        ["git", "-C", os.fspath(repository), *args],
        check=True,
        capture_output=True,
        text=text,
    ).stdout


def _tree_entries(repository: Path, source_sha: str) -> list[tuple[str, str]]:
    raw = _git(repository, "ls-tree", "-r", "-z", source_sha)
    assert isinstance(raw, bytes)
    entries: list[tuple[str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, encoded_path = record.split(b"\t", 1)
        _mode, object_type, object_sha = metadata.decode("ascii").split()
        if object_type == "blob":
            entries.append((os.fsdecode(encoded_path), object_sha))
    return entries


def _blob_stream(repository: Path, entries: list[tuple[str, str]]) -> Iterator[tuple[str, bytes]]:
    process = subprocess.Popen(
        ["git", "-C", os.fspath(repository), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    cache: dict[str, bytes] = {}
    try:
        for relative_path, object_sha in entries:
            data = cache.get(object_sha)
            if data is None:
                process.stdin.write(object_sha.encode("ascii") + b"\n")
                process.stdin.flush()
                header = process.stdout.readline().decode("ascii").strip().split()
                if len(header) != 3 or header[1] != "blob":
                    raise RuntimeError(f"could not read Git blob {object_sha}")
                size = int(header[2])
                data = process.stdout.read(size)
                if process.stdout.read(1) != b"\n":
                    raise RuntimeError(f"invalid Git batch framing for {object_sha}")
                cache[object_sha] = data
            yield relative_path, data
    finally:
        process.stdin.close()
        process.terminate()
        process.wait(timeout=5)


def scan_repository(
    root: str | os.PathLike[str], *, source: str = "HEAD"
) -> dict[str, Any]:
    """Return stable identity records from the exact Git commit named by source."""
    repository = Path(root).resolve()
    source_sha = str(_git(repository, "rev-parse", f"{source}^{{commit}}", text=True)).strip()
    entries = _tree_entries(repository, source_sha)
    records: list[dict[str, Any]] = []
    for relative_path, data in _blob_stream(repository, entries):
        scope = relative_path.split("/", 1)[0]
        component_offset = 0
        for component in relative_path.split("/"):
            if "hermes" in component.lower():
                records.append(
                    {
                        "path": relative_path,
                        "line": 0,
                        "column": component_offset + 1,
                        "token": component,
                        "kind": "path",
                        "scope": scope,
                    }
                )
            component_offset += len(component) + 1
        if b"\0" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in _IDENTITY_PATTERN.finditer(line):
                records.append(
                    {
                        "path": relative_path,
                        "line": line_number,
                        "column": match.start() + 1,
                        "token": match.group(),
                        "kind": "identity",
                        "scope": scope,
                    }
                )
            for match in _URL_PATTERN.finditer(line):
                url = match.group().rstrip(_URL_TRAILING_PUNCTUATION)
                if "hermes" not in url.lower() and "nousresearch" not in url.lower():
                    continue
                records.append(
                    {
                        "path": relative_path,
                        "line": line_number,
                        "column": match.start() + 1,
                        "token": url,
                        "kind": "url",
                        "scope": scope,
                    }
                )
    records.sort(
        key=lambda record: (
            record["path"],
            record["line"],
            record["column"],
            record["kind"],
            record["token"],
        )
    )
    counts = collections.Counter(record["kind"] for record in records)
    return {
        "source_sha": source_sha,
        "summary": {
            "identity": counts["identity"],
            "path": counts["path"],
            "url": counts["url"],
            "total": len(records),
        },
        "records": records,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source", default="HEAD")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    inventory = scan_repository(args.root, source=args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(inventory["summary"], separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
