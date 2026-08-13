#!/usr/bin/env python3
"""Tests for the verif-harness completion and freeze tools."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
PROFILE = SKILL / "add-simulator-profile/scripts/generate_profile.py"
UVC = SKILL / "complete-uvc/scripts/generate_uvc.py"
SCOREBOARD = SKILL / "complete-scoreboard/scripts/generate_scoreboard.py"
TRIAGE = SKILL / "regression-triage/scripts/triage_regression.py"
COVERAGE = SKILL / "coverage-closure/scripts/audit_coverage_closure.py"
ASSERTIONS = SKILL / "assertion-closure/scripts/audit_assertion_closure.py"
CHANGES = SKILL / "change-control/scripts/audit_change_control.py"
FREEZE = SKILL / "freeze-baseline/scripts/build_freeze_manifest.py"


def run(*args: object, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = "/private/tmp/verif-harness-test-pycache"
    return subprocess.run(
        [sys.executable, *(str(arg) for arg in args)], cwd=cwd, env=env,
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


class FreezeToolsTest(unittest.TestCase):
    def test_simulator_profile_generates_normalized_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile, make = root / "profile.json", root / "profile.mk"
            result = run(
                PROFILE, "--spec", SKILL / "add-simulator-profile/simulator-profile.example.json",
                "--profile-out", profile, "--make-out", make,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(profile.read_text())["status"], "configured")
            self.assertIn("SIM_COMPILE := verilator", make.read_text())

    def test_simulator_profile_rejects_secret_material(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = json.loads((SKILL / "add-simulator-profile/simulator-profile.example.json").read_text())
            spec["compile_tokens"].append("27000@" + "host.example.invalid")
            source = root / "profile.json"
            source.write_text(json.dumps(spec))
            result = run(
                PROFILE, "--spec", source, "--profile-out", root / "out.json",
                "--make-out", root / "out.mk",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "out.json").exists())

    def test_uvc_and_scoreboard_generate_concrete_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver, monitor = root / "driver.svh", root / "monitor.svh"
            result = run(
                UVC, "--spec", SKILL / "complete-uvc/uvc-contract.example.json",
                "--driver-out", driver, "--monitor-out", monitor,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ready timeout", driver.read_text())
            self.assertIn("ap.write(tr)", monitor.read_text())
            scoreboard = root / "scoreboard.svh"
            result = run(
                SCOREBOARD, "--spec", SKILL / "complete-scoreboard/scoreboard-contract.example.json",
                "--out", scoreboard,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            text = scoreboard.read_text()
            self.assertIn("expected_fifo.get", text)
            self.assertIn("NO_COMPARE", text)
            self.assertIn("RESIDUAL", text)

    def test_uvc_preflight_prevents_partial_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver, monitor = root / "driver.svh", root / "monitor.svh"
            monitor.write_text("human content\n")
            result = run(
                UVC, "--spec", SKILL / "complete-uvc/uvc-contract.example.json",
                "--driver-out", driver, "--monitor-out", monitor,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(driver.exists())
            self.assertEqual(monitor.read_text(), "human content\n")

    def test_regression_triage_requires_matching_rule_and_same_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "fail.log").write_text("UVM_ERROR scoreboard compare mismatch at item 42\n")
            (root / "rerun.log").write_text("UVM_ERROR scoreboard compare mismatch at item 42\n")
            report = {
                "seed": "7", "results": [
                    {"test": "demo_test", "verdict": "FAIL", "seed": 7, "log": "fail.log"},
                ],
            }
            rerun = {
                "seed": "7", "results": [
                    {"test": "demo_test", "verdict": "FAIL", "seed": 7, "log": "rerun.log"},
                ],
            }
            (root / "report.json").write_text(json.dumps(report))
            (root / "rerun.json").write_text(json.dumps(rerun))
            result = run(
                TRIAGE, "--report", root / "report.json", "--rerun-report", root / "rerun.json",
                "--rules", SKILL / "regression-triage/triage-rules.example.json", "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["summary"]["state"], "READY_FOR_HUMAN_TRIAGE")
            self.assertEqual(payload["findings"][0]["candidate_classification"], "FUNCTIONAL")

            rerun["results"][0]["seed"] = 8
            (root / "rerun.json").write_text(json.dumps(rerun))
            result = run(
                TRIAGE, "--report", root / "report.json", "--rerun-report", root / "rerun.json",
                "--rules", SKILL / "regression-triage/triage-rules.example.json", "--json",
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["summary"]["state"], "BLOCKED")

    def test_coverage_and_assertion_examples_are_ready_not_approved(self) -> None:
        result = run(
            COVERAGE, "--evidence", SKILL / "coverage-closure/coverage-evidence.example.json", "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["state"], "READY_FOR_HUMAN_FREEZE_REVIEW")
        self.assertNotIn("APPROVED", payload["summary"]["state"])
        result = run(
            ASSERTIONS, "--evidence", SKILL / "assertion-closure/assertion-evidence.example.json", "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["summary"]["state"], "READY_FOR_HUMAN_FREEZE_REVIEW")

    def test_coverage_uncovered_item_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "coverage.json"
            evidence = json.loads((SKILL / "coverage-closure/coverage-evidence.example.json").read_text())
            evidence["plan_items"][0]["status"] = "uncovered"
            evidence["reported"] = {"covered": 0, "excluded": 1, "uncovered": 1, "closure_percent": 50.0}
            path.write_text(json.dumps(evidence))
            result = run(COVERAGE, "--evidence", path, "--json")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["summary"]["state"], "BLOCKED")

    def test_change_control_records_existing_decisions_only(self) -> None:
        result = run(
            CHANGES, "--contract", SKILL / "change-control/change-control.example.json", "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["state"], "READY_FOR_HUMAN_REVIEW")
        self.assertIn("grants no approval", payload["notice"])

    def test_freeze_manifest_hashes_clean_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "rtl").mkdir()
            (root / "rtl/dut.sv").write_text("module dut; endmodule\n")
            (root / "plan.md").write_text("# Plan\n")
            (root / "coverage.json").write_text(json.dumps({"summary": {"state": "READY"}}))
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
            contract = {
                "schema_version": 1,
                "freeze_name": "fixture-freeze",
                "baseline_ref": "HEAD",
                "rtl_root": "rtl",
                "require_rtl_unchanged": True,
                "required_evidence": ["coverage.json"],
                "state_checks": [{"path": "coverage.json", "key_path": ["summary", "state"], "allowed": ["READY"]}],
                "include_files": ["plan.md", "rtl/dut.sv"],
                "tool_versions": {"simulator": "fixture 1.0"},
            }
            contract_path, output = base / "contract.json", base / "manifest.json"
            contract_path.write_text(json.dumps(contract))
            result = run(FREEZE, "--project-root", root, "--contract", contract_path, "--out", output)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text())
            self.assertEqual(payload["summary"]["state"], "READY_FOR_HUMAN_FREEZE_REVIEW")
            self.assertEqual(len(payload["files"]), 3)
            self.assertTrue(payload["git"]["worktree_clean"])

            (root / "untracked.txt").write_text("dirty\n")
            second_output = base / "dirty-manifest.json"
            result = run(FREEZE, "--project-root", root, "--contract", contract_path, "--out", second_output)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(second_output.exists())


if __name__ == "__main__":
    unittest.main()
