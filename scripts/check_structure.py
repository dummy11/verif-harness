#!/usr/bin/env python3
"""Validate the public repository structure and simple FIFO filelist."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DIRS = [
    "deps", "docs", "examples/simple_fifo", "scripts", "templates/dut", "tests",
    "skills/verif-harness", "integrations/spec-kit", ".github/workflows",
    ".github/ISSUE_TEMPLATE",
]


def main() -> int:
    failures: list[str] = []
    for name in REQUIRED_DIRS:
        if not (ROOT / name).is_dir():
            failures.append(f"missing directory: {name}")
    for name in (
        "THIRD_PARTY_NOTICES.md", "deps/xverif.lock.json",
        "deps/xverif.lock.schema.json", "scripts/setup_xverif.py",
        "scripts/check_xverif.py", "deps/wavepeek.lock.json",
        "deps/wavepeek.lock.schema.json", "scripts/setup_wavepeek.py",
        "scripts/check_wavepeek.py", "deps/spec-kit.lock.json",
        "deps/spec-kit.lock.schema.json", "scripts/setup_spec_kit.py",
        "scripts/check_spec_kit.py",
        "scripts/configure_spec_kit_chinese_docs.py",
        "deps/runtime.lock.json", "deps/runtime.lock.schema.json",
        "deps/runtime-requirements.in", "deps/runtime-requirements.lock",
        "scripts/setup_managed.sh", "scripts/setup_managed_runtime.py",
        "scripts/managed-python", "scripts/runtime-versions",
        "scripts/check_runtime_versions.py",
        "skills/verif-harness/scripts/verif-harness",
        "skills/verif-harness/xverif/scripts/xverif_mcp.py",
    ):
        if not (ROOT / name).is_file():
            failures.append(f"missing managed-dependency file: {name}")
    lock_path = ROOT / "deps/xverif.lock.json"
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        if lock.get("repository") != "https://github.com/BLANK2077/xverif.git":
            failures.append("xverif lock repository is not the reviewed upstream")
        commit = lock.get("commit", "")
        if not isinstance(commit, str) or len(commit) != 40 or any(
            character not in "0123456789abcdef" for character in commit
        ):
            failures.append("xverif lock commit is not a full lowercase object ID")
        if lock.get("license") != "MIT":
            failures.append("xverif lock license is not MIT")
        if lock.get("schema_version") != 2:
            failures.append("xverif lock must use schema version 2 for MCP support")
        if lock.get("tools") != [
            "xbit", "xentry", "xloc", "xsva", "xcov", "xdebug", "xwaveform",
        ]:
            failures.append("xverif lock tools do not match the reviewed wrapper set")
        mcp = lock.get("mcp", {})
        if mcp.get("launcher") != "tools/xverif-mcp":
            failures.append("xverif lock must pin the reviewed MCP launcher")
        if mcp.get("package") != "xverif_mcp":
            failures.append("xverif lock must pin the reviewed MCP package")
    wavepeek_lock_path = ROOT / "deps/wavepeek.lock.json"
    if wavepeek_lock_path.is_file():
        lock = json.loads(wavepeek_lock_path.read_text(encoding="utf-8"))
        if lock.get("repository") != "https://github.com/kleverhq/wavepeek.git":
            failures.append("WavePeek lock repository is not the reviewed upstream")
        if lock.get("commit") != "8779507b06f6b77be49f0d934ea9339140a8df2a":
            failures.append("WavePeek lock commit is not the reviewed object ID")
        if lock.get("version") != "2.2.3" or lock.get("license") != "Apache-2.0":
            failures.append("WavePeek lock version or license differs from review")
        if lock.get("ref") != "refs/tags/v2.2.3":
            failures.append("WavePeek lock tag differs from the reviewed release")
        if lock.get("cargo_features") != []:
            failures.append("WavePeek default lock must not enable FSDB or other features")
        private_glibc = lock.get("private_glibc", {})
        if lock.get("schema_version") != 2:
            failures.append("WavePeek lock must use schema version 2 for private glibc")
        if private_glibc.get("version") != "2.34":
            failures.append("WavePeek private glibc must remain pinned to 2.34")
        if private_glibc.get("license") != "LGPL-2.1-or-later":
            failures.append("WavePeek private glibc license identity differs from review")
        if private_glibc.get("source_sha256") != (
            "44d26a1fe20b8853a48f470ead01e4279e869ac149b195dda4e44a195d981ab2"
        ):
            failures.append("WavePeek private glibc source hash differs from review")
        if private_glibc.get("license_file_sha256") != (
            "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551"
        ):
            failures.append("WavePeek private glibc license hash differs from review")
        if private_glibc.get("licenses_file_sha256") != (
            "b33d0bd9f685b46853548814893a6135e74430d12f6d94ab3eba42fc591f83bc"
        ):
            failures.append("WavePeek private glibc LICENSES hash differs from review")
    spec_kit_lock_path = ROOT / "deps/spec-kit.lock.json"
    if spec_kit_lock_path.is_file():
        lock = json.loads(spec_kit_lock_path.read_text(encoding="utf-8"))
        if lock.get("schema_version") != 2 or "integration" in lock:
            failures.append("Spec Kit lock must separate dependency identity from runtime")
        if lock.get("repository") != "https://github.com/github/spec-kit.git":
            failures.append("Spec Kit lock repository is not the reviewed upstream")
        if lock.get("commit") != "d1f50fcbe684a4222059c4ba7f2d7eabcca87402":
            failures.append("Spec Kit lock commit is not the reviewed object ID")
        if lock.get("version") != "0.16.4" or lock.get("license") != "MIT":
            failures.append("Spec Kit lock version or license differs from review")
        if lock.get("ref") != "refs/tags/v0.16.4":
            failures.append("Spec Kit lock tag differs from the reviewed release")
        if lock.get("python_requires") != ">=3.11":
            failures.append("Spec Kit lock must require Python 3.11 or newer")
    runtime_lock_path = ROOT / "deps/runtime.lock.json"
    if runtime_lock_path.is_file():
        lock = json.loads(runtime_lock_path.read_text(encoding="utf-8"))
        if lock.get("schema_version") != 1 or lock.get("name") != "verif-harness-managed-runtime":
            failures.append("managed runtime lock identity or schema differs from review")
        python = lock.get("python", {})
        if python.get("version") != "3.12.11" or python.get("release") != "20251007":
            failures.append("managed CPython version or distribution release differs from review")
        assets = python.get("assets", {})
        expected_platforms = {
            "aarch64-apple-darwin", "x86_64-apple-darwin",
            "aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu",
        }
        if set(assets) != expected_platforms:
            failures.append("managed CPython assets do not cover the reviewed platforms")
        expected_versions = {
            "bash": ">=3.2", "git": ">=2.25",
            "private_glibc_binutils": ">=2.25",
            "private_glibc_bison": ">=2.7",
            "private_glibc_gawk": ">=3.1.2",
            "private_glibc_gcc": ">=6.2",
            "private_glibc_make": ">=4.0",
            "private_glibc_python": ">=3.4",
            "private_glibc_sed": ">=3.02",
            "private_glibc_texinfo": ">=4.7",
            "verilator": "5.x",
        }
        if lock.get("host_contract", {}).get("version_requirements") != expected_versions:
            failures.append("managed host version requirements differ from review")
        requirements = ROOT / lock.get("python_packages", {}).get("requirements", "missing")
        if requirements.is_file():
            observed = hashlib.sha256(requirements.read_bytes()).hexdigest()
            if observed != lock.get("python_packages", {}).get("requirements_sha256"):
                failures.append("managed Python requirements hash differs from runtime lock")
        else:
            failures.append("managed Python requirements lock is missing")
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
        "freeze-baseline", "oss-readiness", "spec-kit", "xverif", "wavepeek",
        "patterns",
    ]
    for mode in modes:
        if f"`{mode}" not in skill_text:
            failures.append(f"bundled skill lacks mode: {mode}")
    for mode in (
        "add-simulator-profile", "complete-uvc", "complete-scoreboard",
        "regression-triage", "coverage-closure", "assertion-closure",
        "change-control", "freeze-baseline", "spec-kit", "xverif", "wavepeek",
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
