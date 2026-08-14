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
    skill_text = skill.read_text(encoding="utf-8")
    modes = [
        "init", "add-interface", "add-shared-pkg", "add-uvc-skeleton",
        "add-harness-layer", "add-env-layer", "finalize-filelist-and-make",
        "doctor", "add-regression-runner", "add-simulator-profile",
        "add-testcase", "add-coverage-skeleton", "add-assertion-skeleton",
        "add-refmodel-bridge", "complete-uvc", "complete-scoreboard",
        "add-ci-hook", "add-performance-gate", "regression-triage",
        "coverage-closure", "assertion-closure", "audit-traceability",
        "change-control", "stage-gate-review", "signoff-audit",
        "freeze-baseline", "oss-readiness", "xverif", "patterns",
    ]
    for mode in modes:
        if f"`{mode}" not in skill_text:
            failures.append(f"bundled skill lacks mode: {mode}")
    for mode in (
        "add-simulator-profile", "complete-uvc", "complete-scoreboard",
        "regression-triage", "coverage-closure", "assertion-closure",
        "change-control", "freeze-baseline", "xverif",
    ):
        if not (ROOT / "skills/verif-harness" / mode / "INSTRUCTIONS.md").is_file():
            failures.append(f"mode lacks instructions: {mode}")
    skill_docs = [
        "skills/verif-harness/README.md",
        "skills/verif-harness/docs/user_guide.md",
        "skills/verif-harness/docs/architecture.md",
        "skills/verif-harness/docs/troubleshooting.md",
    ]
    for relative in skill_docs:
        if not (ROOT / relative).is_file():
            failures.append(f"missing skill documentation: {relative}")
        elif relative.startswith("skills/verif-harness/docs/"):
            content = (ROOT / relative).read_text(encoding="utf-8")
            if not any("\u4e00" <= character <= "\u9fff" for character in content):
                failures.append(f"skill documentation is not Chinese: {relative}")
    guide = ROOT / "skills/verif-harness/docs/user_guide.md"
    if guide.is_file():
        guide_text = guide.read_text(encoding="utf-8")
        for mode in modes:
            if f"`{mode}" not in guide_text:
                failures.append(f"skill user guide lacks mode: {mode}")
        for label in ("**用途**", "**适用场景**", "**输入**", "**用法**", "**输出**"):
            if guide_text.count(label) < len(modes):
                failures.append(f"skill user guide lacks per-mode field: {label}")
    for failure in failures:
        print(f"ERROR: {failure}")
    if failures:
        return 1
    print(f"Structure check PASS: {len(entries)} simple_fifo sources, {len(modes)} skill modes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
