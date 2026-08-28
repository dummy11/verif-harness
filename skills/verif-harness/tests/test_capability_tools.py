#!/usr/bin/env python3
"""Tests for lower-level verif-harness capability contracts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
ADD_TEST = SKILL / "add-testcase" / "scripts" / "add_testcase.py"
COVERAGE = SKILL / "add-coverage-skeleton" / "scripts" / "generate_coverage.py"
ASSERTIONS = SKILL / "add-assertion-skeleton" / "scripts" / "generate_assertions.py"
BRIDGE = SKILL / "add-refmodel-bridge" / "scripts" / "generate_bridge.py"
CI = SKILL / "add-ci-hook" / "scripts" / "generate_ci.py"
SIGNOFF = SKILL / "signoff-audit" / "scripts" / "audit_signoff.py"
PERFORMANCE = SKILL / "add-performance-gate" / "scripts" / "evaluate_performance.py"


def run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *(str(arg) for arg in args)], check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def config() -> dict:
    return {
        "project_name": "demo",
        "rtl": {"root": "rtl", "top_module": "dut", "top_file": "rtl/dut.sv"},
        "verif": {
            "root": "sim", "docs_root": "sim/docs",
            "verification_subdir": "verification", "governance_subdir": "governance",
        },
        "reference_model": {"enabled": False, "spec_path": None},
    }


class Stage2PlusToolsTest(unittest.TestCase):
    def test_add_testcase_registers_candidate_but_not_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".harness-config.json").write_text(json.dumps(config()), encoding="utf-8")
            test_dir = root / "sim/testbench/test"
            env_dir = root / "sim/testbench/env"
            test_dir.mkdir(parents=True)
            env_dir.mkdir(parents=True)
            (test_dir / "demo_test_pkg.sv").write_text("package demo_test_pkg;\nendpackage\n", encoding="utf-8")
            (env_dir / "demo_env_pkg.sv").write_text("package demo_env_pkg;\nendpackage\n", encoding="utf-8")
            default = root / "sim/docs/caselist/default_regression.caselist"
            default.parent.mkdir(parents=True)
            default.write_text("smoke_test\n", encoding="utf-8")
            candidate = root / "sim/docs/caselist/candidate.caselist"
            result = run(
                ADD_TEST, "--project-root", root, "--test-name", "feature_test",
                "--base-test", "demo_base_test", "--base-vseq", "demo_base_vseq",
                "--candidate-caselist", candidate,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((test_dir / "feature_test.svh").is_file())
            self.assertTrue((env_dir / "vseq/feature_vseq.svh").is_file())
            self.assertEqual(candidate.read_text(encoding="utf-8"), "feature_test\n")
            self.assertEqual(default.read_text(encoding="utf-8"), "smoke_test\n")
            self.assertIn('`include "feature_test.svh"', (test_dir / "demo_test_pkg.sv").read_text())
            self.assertIn('`include "vseq/feature_vseq.svh"', (env_dir / "demo_env_pkg.sv").read_text())

    def test_coverage_assertion_and_ci_examples_render(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            coverage_out = root / "demo_cov.svh"
            result = run(COVERAGE, "--spec", SKILL / "add-coverage-skeleton/coverage-spec.example.json",
                         "--out", coverage_out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("covergroup cg_demo", coverage_out.read_text(encoding="utf-8"))

            checker_out, bind_out = root / "checker.sv", root / "bind.sv"
            result = run(ASSERTIONS, "--spec", SKILL / "add-assertion-skeleton/assertion-spec.example.json",
                         "--checker-out", checker_out, "--bind-out", bind_out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("a_valid_known: assert property", checker_out.read_text(encoding="utf-8"))
            self.assertIn("bind demo_dut", bind_out.read_text(encoding="utf-8"))

            ci_out = root / "verification.gitlab-ci.yml"
            result = run(CI, "--spec", SKILL / "add-ci-hook/ci-spec.example.json", "--out", ci_out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("rtl_smoke:", ci_out.read_text(encoding="utf-8"))

    def test_assertion_preflight_avoids_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checker_out, bind_out = root / "checker.sv", root / "bind.sv"
            bind_out.write_text("human content\n", encoding="utf-8")
            result = run(ASSERTIONS, "--spec", SKILL / "add-assertion-skeleton/assertion-spec.example.json",
                         "--checker-out", checker_out, "--bind-out", bind_out)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(checker_out.exists())
            self.assertEqual(bind_out.read_text(encoding="utf-8"), "human content\n")

    def test_refmodel_syscan_and_dpi_backends_render(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            syscan_out = root / "bridge.sv"
            result = run(BRIDGE, "--spec", SKILL / "add-refmodel-bridge/bridge-spec.example.json",
                         "--out", syscan_out)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = syscan_out.read_text(encoding="utf-8")
            self.assertIn("demo_systemc_shell u_golden", text)
            self.assertIn("assign out_valid = 1'b0;", text)

            dpi_spec = root / "dpi.json"
            dpi_spec.write_text(json.dumps({
                "backend": "dpi-c", "guard": "USE_DPI", "package_name": "golden_dpi_pkg",
                "functions": [{"name": "golden_init", "signature": "function int golden_init();",
                               "plan_ref": "reference_model_spec.md § init"}],
            }), encoding="utf-8")
            dpi_out = root / "golden_dpi_pkg.sv"
            result = run(BRIDGE, "--spec", dpi_spec, "--out", dpi_out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('import "DPI-C" function int golden_init();', dpi_out.read_text(encoding="utf-8"))

    def test_signoff_audit_reports_recorded_approval_without_granting_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".harness-config.json").write_text(json.dumps(config()), encoding="utf-8")
            docs = root / "sim/docs"
            docs.mkdir(parents=True)
            (docs / "final_signoff.md").write_text(
                "# Final sign-off\n\n"
                "- **Status**: Approved\n- **Reviewer**: Human\n"
                "- **Decision date**: 2026-08-13\n\n"
                "Regression, functional coverage, assertion, CI, Open Question, and "
                "Change Request evidence reviewed. Artifact evidence boundary recorded.\n",
                encoding="utf-8",
            )
            manifest = docs / "caselist/default_regression.caselist"
            manifest.parent.mkdir()
            manifest.write_text("smoke_test\nfeature_test\n", encoding="utf-8")
            result = run(SIGNOFF, "--project-root", root, "--json")
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["summary"]["state"], "APPROVED_RECORDED")

    def test_performance_contract_passes_and_fails_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            contract = SKILL / "add-performance-gate/performance-contract.example.json"
            good = root / "good.log"
            good.write_text(
                "PERF_RECORD|schema=1|case=a|job=1|domain=INT|input_handshakes=4|"
                "expected_input_beats=4|input_valid_cycles=4|input_bubbles=0\n"
                "PERF_RECORD|schema=1|case=b|job=2|domain=FP|input_handshakes=8|"
                "expected_input_beats=8|input_valid_cycles=8|input_bubbles=0\n",
                encoding="utf-8",
            )
            result = run(PERFORMANCE, "--contract", contract, "--log", good, "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["summary"]["state"], "PASS")

            bad = root / "bad.log"
            bad.write_text(
                "PERF_RECORD|schema=1|case=a|job=1|domain=INT|input_handshakes=3|"
                "expected_input_beats=4|input_valid_cycles=4|input_bubbles=1\n",
                encoding="utf-8",
            )
            result = run(PERFORMANCE, "--contract", contract, "--log", bad, "--json")
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            checks = {failure["check"] for failure in payload["failures"]}
            self.assertIn("input_count", checks)
            self.assertIn("completeness:domain", checks)


if __name__ == "__main__":
    unittest.main()
