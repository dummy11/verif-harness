#!/usr/bin/env python3
"""Validate the public repository structure and simple FIFO filelist."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DIRS = [
    "docs", "examples/simple_fifo", "scripts", "templates/dut", "tests",
    "skills/verif-harness", ".github/workflows", ".github/ISSUE_TEMPLATE",
]


def main() -> int:
    failures: list[str] = []
    for name in REQUIRED_DIRS:
        if not (ROOT / name).is_dir():
            failures.append(f"missing directory: {name}")
    config_path = ROOT / "examples/simple_fifo/config/example.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    filelist_path = ROOT / config["filelist"]
    entries = [line.split("#", 1)[0].strip() for line in filelist_path.read_text().splitlines()]
    entries = [entry for entry in entries if entry]
    if len(entries) != len(set(entries)):
        failures.append("simple_fifo filelist contains duplicates")
    for entry in entries:
        if Path(entry).is_absolute():
            failures.append(f"absolute filelist entry: {entry}")
        if not (ROOT / entry).is_file():
            failures.append(f"missing filelist entry: {entry}")
    expected_entries = [
        "examples/simple_fifo/interfaces/simple_fifo_if.sv",
        "examples/simple_fifo/rtl/simple_fifo.sv",
        "examples/simple_fifo/sva/simple_fifo_checker.sv",
        "examples/simple_fifo/bind/simple_fifo_bind.sv",
        "examples/simple_fifo/tb/harness/simple_fifo_harness.sv",
        "examples/simple_fifo/tb/simple_fifo_tb_top.sv",
    ]
    if entries != expected_entries:
        failures.append(f"unexpected compile order: {entries}")
    skill = ROOT / "skills/verif-harness/SKILL.md"
    if "oss-readiness" not in skill.read_text(encoding="utf-8"):
        failures.append("bundled skill lacks oss-readiness mode")
    for failure in failures:
        print(f"ERROR: {failure}")
    if failures:
        return 1
    print(f"Structure check PASS: {len(entries)} simple_fifo sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
