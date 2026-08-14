#!/usr/bin/env python3
"""Check UTF-8 text files for final newlines and trailing whitespace."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = {".md", ".py", ".sh", ".sv", ".svh", ".f", ".yml", ".yaml", ".json", ".toml", ".tmpl"}
SKIP = {".git", ".deps", "build", "dist", "site", "__pycache__", ".venv"}


def main() -> int:
    failures: list[str] = []
    checked = 0
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if not path.is_file() or any(part in SKIP for part in relative.parts):
            continue
        if path.suffix not in SUFFIXES and path.name not in {"LICENSE", "Makefile"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"not UTF-8: {relative}")
            continue
        checked += 1
        if text and not text.endswith("\n"):
            failures.append(f"missing final newline: {relative}")
        for line_no, line in enumerate(text.splitlines(), 1):
            if line.rstrip() != line:
                failures.append(f"trailing whitespace: {relative}:{line_no}")
    for failure in failures:
        print(f"ERROR: {failure}")
    if failures:
        return 1
    print(f"Text format PASS: {checked} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
