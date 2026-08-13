#!/usr/bin/env python3
"""Unit tests for generic verif-harness regression tools."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
COLLECT = HERE / "collect_results.py"
RUNNER = HERE / "run_regression.py"


class CollectorTest(unittest.TestCase):
    def run_collect(self, log_text: str, require_golden: bool = False) -> tuple[int, str, str]:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "cases.txt").write_text("demo_test\n", encoding="utf-8")
            run = root / "runs" / "demo_test"
            run.mkdir(parents=True)
            (run / "run.log").write_text(log_text, encoding="utf-8")
            command = [sys.executable, str(COLLECT), "--runs-dir", str(root / "runs"),
                       "--caselist", str(root / "cases.txt"), "--result-prefix", "DEMO"]
            if require_golden:
                command.append("--require-golden")
            result = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return result.returncode, (root / "runs" / "report.md").read_text(encoding="utf-8"), (root / "runs" / "failed.caselist").read_text(encoding="utf-8")

    def test_live_pass(self) -> None:
        rc, report, failed = self.run_collect("DEMO demo_test : PASSED\n  (UVM_ERROR=0  UVM_FATAL=0)\n")
        self.assertEqual(rc, 0)
        self.assertIn("PASS-LIVE", report)
        self.assertEqual(failed, "")

    def test_missing_banner_is_crash(self) -> None:
        rc, report, failed = self.run_collect("simulation stopped\n")
        self.assertEqual(rc, 1)
        self.assertIn("CRASH", report)
        self.assertEqual(failed, "demo_test\n")

    def test_required_golden_rejects_false_green(self) -> None:
        rc, report, _ = self.run_collect("DEMO demo_test : PASSED\n", require_golden=True)
        self.assertEqual(rc, 1)
        self.assertIn("NO-COMPARE", report)

    def test_required_golden_pass(self) -> None:
        log = ("ntb_random_seed = 42\nSUMMARY: cfg_events=1 supported_seen=1 "
               "mismatch_lanes=0 residual_beats=0\nDEMO demo_test : PASSED\n")
        rc, report, failed = self.run_collect(log, require_golden=True)
        self.assertEqual(rc, 0)
        self.assertIn("| demo_test | PASS | 42 |", report)
        self.assertEqual(failed, "")


class RunnerTest(unittest.TestCase):
    def test_runner_uses_one_seed_and_isolated_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cases = root / "cases.txt"
            cases.write_text("first_test\nsecond_test\n", encoding="utf-8")
            fake = root / "fake.py"
            fake.write_text(
                "import pathlib,sys\n"
                "pathlib.Path('seen.txt').write_text(sys.argv[1] + ':' + sys.argv[2])\n"
                "print('DEMO ' + sys.argv[1] + ' : PASSED')\n",
                encoding="utf-8",
            )
            result = subprocess.run([
                sys.executable, str(RUNNER), "--caselist", str(cases),
                "--runs-dir", str(root / "runs"), "--seed", "42", "--jobs", "2",
                "--", sys.executable, str(fake), "{test}", "{seed}",
            ], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "runs" / "batch_seed.txt").read_text(), "42\n")
            self.assertEqual((root / "runs" / "first_test" / "seen.txt").read_text(), "first_test:42")
            self.assertEqual((root / "runs" / "second_test" / "seen.txt").read_text(), "second_test:42")

if __name__ == "__main__":
    unittest.main()
