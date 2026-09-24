#!/usr/bin/env python3
"""Validate the v1 public repository structure and dependency boundaries."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verif_harness.document_authoring import (  # noqa: E402
    DocumentAuthoringError, load_authoring_profiles, load_common_rules,
)

CORE_MODES = ("bootstrap", "vplan", "vmodel", "vcheck", "vclosure", "vreason")
BUNDLED_SKILLS = ("verif-harness", "verification-doc-authoring")
CAPABILITY_MODES = (
    "doctor", "xverif", "wavepeek", "add-interface", "add-shared-pkg",
    "add-uvc-skeleton", "add-harness-layer", "add-env-layer",
    "finalize-filelist-and-make", "add-regression-runner",
    "add-simulator-profile", "add-testcase", "add-coverage-skeleton",
    "add-assertion-skeleton", "add-refmodel-bridge", "complete-uvc",
    "complete-scoreboard", "add-ci-hook", "add-performance-gate",
    "regression-triage", "coverage-closure", "assertion-closure",
    "audit-traceability", "change-control", "signoff-audit",
    "freeze-baseline", "oss-readiness",
)


def valid_commit(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(character in "0123456789abcdef" for character in value)


def main() -> int:
    failures: list[str] = []
    required_dirs = (
        "deps", "docs", "examples/simple_fifo", "scripts", "templates/dut",
        "tests", "verif_harness", "skills/verif-harness",
        "skills/verification-doc-authoring",
        "skills/verification-doc-authoring/core",
        "skills/verification-doc-authoring/profiles",
        "skills/verification-doc-authoring/references", ".github/workflows",
    )
    required_files = (
        "verif_harness/__init__.py", "verif_harness/cli.py", "verif_harness/store.py",
        "verif_harness/dashboard.py", "verif_harness/dashboard.html", "verif_harness/evidence_policy.py",
        "scripts/verif_harness.py", "skills/verif-harness/scripts/verif-harness",
        "deps/runtime.lock.json", "deps/runtime-requirements.lock",
        "deps/xverif.lock.json", "deps/wavepeek.lock.json",
        "skills/verif-harness/docs/user_guide.md",
        "verif_harness/document_authoring.py",
        "skills/verification-doc-authoring/SKILL.md",
        "skills/verification-doc-authoring/agents/openai.yaml",
        "skills/verification-doc-authoring/core/common-rules.json",
        "skills/verification-doc-authoring/references/authoring-contract.schema.json",
        "skills/verification-doc-authoring/references/checklist.md",
    )
    for relative in required_dirs:
        if not (ROOT / relative).is_dir():
            failures.append(f"missing directory: {relative}")
    for relative in required_files:
        if not (ROOT / relative).is_file():
            failures.append(f"missing file: {relative}")

    xverif_path = ROOT / "deps/xverif.lock.json"
    if xverif_path.is_file():
        lock = json.loads(xverif_path.read_text(encoding="utf-8"))
        if lock.get("repository") != "https://github.com/BLANK2077/xverif.git":
            failures.append("xverif lock repository differs from review")
        if not valid_commit(lock.get("commit")) or lock.get("license") != "MIT":
            failures.append("xverif commit or license differs from review")

    wavepeek_path = ROOT / "deps/wavepeek.lock.json"
    if wavepeek_path.is_file():
        lock = json.loads(wavepeek_path.read_text(encoding="utf-8"))
        if lock.get("repository") != "https://github.com/kleverhq/wavepeek.git":
            failures.append("WavePeek lock repository differs from review")
        if not valid_commit(lock.get("commit")) or lock.get("license") != "Apache-2.0":
            failures.append("WavePeek commit or license differs from review")
        if lock.get("cargo_features") != []:
            failures.append("WavePeek public default must keep optional features disabled")

    runtime_path = ROOT / "deps/runtime.lock.json"
    if runtime_path.is_file():
        lock = json.loads(runtime_path.read_text(encoding="utf-8"))
        requirements = ROOT / lock.get("python_packages", {}).get("requirements", "missing")
        if not requirements.is_file():
            failures.append("managed Python requirements lock is missing")
        elif hashlib.sha256(requirements.read_bytes()).hexdigest() != lock["python_packages"].get("requirements_sha256"):
            failures.append("managed Python requirements hash differs from runtime lock")

    config_path = ROOT / "examples/simple_fifo/config/example.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        filelist = ROOT / config["filelist"]
        entries = [line.split("#", 1)[0].strip() for line in filelist.read_text(encoding="utf-8").splitlines()]
        entries = [entry for entry in entries if entry]
        if len(entries) != len(set(entries)):
            failures.append("simple_fifo filelist contains duplicates")
        for entry in entries:
            if Path(entry).is_absolute() or not (ROOT / entry).is_file():
                failures.append(f"invalid simple_fifo filelist entry: {entry}")
    else:
        entries = []

    skill_text = (ROOT / "skills/verif-harness/SKILL.md").read_text(encoding="utf-8")
    for mode in (*CORE_MODES, *CAPABILITY_MODES):
        if f"`{mode}" not in skill_text:
            failures.append(f"bundled skill lacks mode: {mode}")
    for mode in CORE_MODES:
        if not (ROOT / "skills/verif-harness" / mode / "INSTRUCTIONS.md").is_file():
            failures.append(f"core mode lacks instructions: {mode}")

    expected_profiles = {
        "verification-workflow": "verification_workflow.md",
        "verification-plan": "verification_plan.md",
        "feature-matrix": "feature_matrix.md",
        "tb-architecture": "tb_architecture.md",
        "reference-model": "reference_model_spec.md",
        "coverage-plan": "coverage_plan.md",
        "assertion-plan": "assertion_plan.md",
        "testcase-list": "testcase_list.md",
    }
    try:
        profiles = load_authoring_profiles()
        load_common_rules()
    except DocumentAuthoringError as exc:
        failures.append(f"verification-doc-authoring registry invalid: {exc}")
    else:
        if {key: item["filename"] for key, item in profiles.items()} != expected_profiles:
            failures.append("verification-doc-authoring profiles differ from the eight VDOC documents")

    for failure in failures:
        print(f"ERROR: {failure}")
    if failures:
        return 1
    print(
        f"Structure check PASS: skills={len(BUNDLED_SKILLS)}, "
        f"v1 core={len(CORE_MODES)}, capabilities={len(CAPABILITY_MODES)}, "
        f"example_sources={len(entries)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
