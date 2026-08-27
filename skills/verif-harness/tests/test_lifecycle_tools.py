#!/usr/bin/env python3
"""Tests for verif-harness lifecycle scripts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
DOCTOR = SKILL / "doctor" / "scripts" / "doctor.py"
AUDIT = SKILL / "audit-traceability" / "scripts" / "audit_traceability.py"
GATE = SKILL / "stage-gate-review" / "scripts" / "build_stage_gate.py"


def base_config() -> dict:
    return {
        "project_name": "demo",
        "rtl": {"root": "rtl", "top_module": "dut", "top_file": "rtl/dut.sv"},
        "verif": {
            "root": "sim",
            "docs_root": "sim/docs",
            "verification_subdir": "verification",
            "governance_subdir": "governance",
        },
        "reference_model": {"enabled": False, "spec_path": None},
    }


class LifecycleToolsTest(unittest.TestCase):
    def test_doctor_without_config_recommends_init(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [sys.executable, str(DOCTOR), "--project-root", temp, "--json"],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(payload["next_mode"], "init")
            self.assertEqual(payload["findings"][0]["code"], "CONFIG_ABSENT")

    def test_traceability_flags_duplicate_and_unknown_manifest_tests(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".harness-config.json").write_text(json.dumps(base_config()), encoding="utf-8")
            test_root = root / "sim/testbench/test"
            test_root.mkdir(parents=True)
            (test_root / "demo_test.svh").write_text(
                "class demo_test extends uvm_test; endclass\n", encoding="utf-8"
            )
            docs = root / "sim/docs/verification"
            docs.mkdir(parents=True)
            (docs / "testcase_list.md").write_text("T.DEMO.001 demo_test\n", encoding="utf-8")
            for name in ("feature_matrix.md", "coverage_plan.md", "assertion_plan.md"):
                (docs / name).write_text("- None\n", encoding="utf-8")
            cases = root / "sim/docs/caselist/default_regression.caselist"
            cases.parent.mkdir(parents=True)
            cases.write_text("demo_test\ndemo_test\nmissing_test\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(AUDIT), "--project-root", str(root), "--json"],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            payload = json.loads(result.stdout)
            codes = {item["code"] for item in payload["findings"]}
            self.assertEqual(result.returncode, 1)
            self.assertIn("MANIFEST_DUPLICATE", codes)
            self.assertIn("MANIFEST_UNKNOWN_TEST", codes)

    def test_gate_generator_leaves_decisions_unchecked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".harness-config.json").write_text(json.dumps(base_config()), encoding="utf-8")
            docs = root / "sim/docs"
            verification = docs / "verification"
            governance = docs / "governance"
            verification.mkdir(parents=True)
            governance.mkdir(parents=True)
            feature = root / "specs/002-stage2-demo"
            feature.mkdir(parents=True)
            (feature / "spec.md").write_text(
                "# Stage 2 demo specification\n", encoding="utf-8"
            )
            (feature / "plan.md").write_text(
                "## 开放问题\n\n- OQ1: evidence missing.\n", encoding="utf-8"
            )
            specify = root / ".specify"
            specify.mkdir()
            (specify / "feature.json").write_text(
                json.dumps({"feature_directory": "specs/002-stage2-demo"}),
                encoding="utf-8",
            )
            (docs / "roadmap.md").write_text(
                "## Stage 2 — Demo\n\n### Exit Criteria\n\n- Demo regression passes.\n\n"
                "## 暂定决策 (Provisional)\n\n- **P1**: demo\n  - 目标复审: Stage 2 gate\n",
                encoding="utf-8",
            )
            for path in [
                docs / "harness_style_methodology.md",
                governance / "verification_workflow.md",
                *[verification / name for name in (
                    "verification_plan.md", "tb_architecture.md", "coverage_plan.md",
                    "assertion_plan.md", "testcase_list.md", "feature_matrix.md",
                )],
            ]:
                path.write_text("## 开放问题\n\n- None\n", encoding="utf-8")
            (docs / "change_requests.md").write_text("## CR-001 · demo\n", encoding="utf-8")
            out = docs / "stage2_gate_re_review.md"
            result = subprocess.run(
                [sys.executable, str(GATE), "--project-root", str(root),
                 "--completed-stage", "2", "--out", str(out)],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            text = out.read_text(encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("- [ ] Demo regression passes.", text)
            self.assertIn("PROV-01", text)
            self.assertIn("OQ1", text)
            self.assertIn("CR-001", text)
            self.assertIn(
                "Authoritative Stage plan**: `specs/002-stage2-demo/plan.md`",
                text,
            )
            self.assertNotIn("- [x]", text.lower())

    def test_gate_generator_accepts_legacy_plan_without_spec_kit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".harness-config.json").write_text(
                json.dumps(base_config()), encoding="utf-8"
            )
            docs = root / "sim/docs"
            verification = docs / "verification"
            governance = docs / "governance"
            verification.mkdir(parents=True)
            governance.mkdir(parents=True)
            (docs / "plan.md").write_text(
                "## 开放问题\n\n- OQ1: legacy evidence missing.\n",
                encoding="utf-8",
            )
            (docs / "roadmap.md").write_text(
                "## Stage 2 — Legacy\n\n### Exit Criteria\n\n- Legacy exit.\n",
                encoding="utf-8",
            )
            for path in [
                docs / "harness_style_methodology.md",
                governance / "verification_workflow.md",
                *[verification / name for name in (
                    "verification_plan.md", "tb_architecture.md", "coverage_plan.md",
                    "assertion_plan.md", "testcase_list.md", "feature_matrix.md",
                )],
            ]:
                path.write_text("## 开放问题\n\n- None\n", encoding="utf-8")
            out = docs / "stage2_gate_re_review.md"
            result = subprocess.run(
                [sys.executable, str(GATE), "--project-root", str(root),
                 "--completed-stage", "2", "--out", str(out)],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            text = out.read_text(encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Authoritative Stage plan**: `sim/docs/plan.md`", text)
            self.assertIn("legacy evidence missing", text)

    def test_gate_generator_does_not_fallback_in_spec_kit_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".harness-config.json").write_text(
                json.dumps(base_config()), encoding="utf-8"
            )
            legacy = root / "sim/docs/plan.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("# Legacy derived plan\n", encoding="utf-8")
            (root / ".specify").mkdir()
            result = subprocess.run(
                [sys.executable, str(GATE), "--project-root", str(root),
                 "--completed-stage", "2", "--out", "sim/docs/gate.md"],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(".specify/feature.json", result.stderr)
            self.assertFalse((root / "sim/docs/gate.md").exists())

    def test_doctor_reports_legacy_derived_plan_as_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".harness-config.json").write_text(
                json.dumps(base_config()), encoding="utf-8"
            )
            legacy = root / "sim/docs/plan.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("# Legacy derived plan\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(DOCTOR), "--project-root", str(root), "--json"],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            payload = json.loads(result.stdout)
            codes = {item["code"] for item in payload["findings"]}
            self.assertIn("LEGACY_DERIVED_PLAN", codes)


if __name__ == "__main__":
    unittest.main()
