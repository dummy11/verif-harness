#!/usr/bin/env python3
"""Unit tests for generic verif-harness regression tools."""

from __future__ import annotations

import subprocess
import json
import concurrent.futures
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from run_regression import claim_output_directory, replay_runs


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
    def run_round(self, root, directory, *options):
        return subprocess.run([
            sys.executable, str(RUNNER), "--caselist", str(root / "cases.txt"),
            "--runs-dir", str(root / directory), *options, "--", sys.executable,
            str(root / "fake.py"), "{test}", "{seed}", "{iteration}",
        ], check=False, capture_output=True, text=True)

    def prepare_fake(self, root):
        (root / "cases.txt").write_text("demo_test\n", encoding="utf-8")
        (root / "fake.py").write_text(
            "import json,pathlib,sys\n"
            "assert pathlib.Path('../../run_manifest.json').exists() or pathlib.Path('../run_manifest.json').exists()\n"
            "print('ntb_random_seed = ' + sys.argv[2])\n"
            "print('DEMO ' + sys.argv[1] + ' : ' + ('FAILED' if sys.argv[3]=='1' else 'PASSED'))\n",
            encoding="utf-8",
        )

    def test_random_repeat_is_materialized_before_launch_and_replayed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.prepare_fake(root)
            result = self.run_round(root, "first", "--seed-mode", "random", "--repeat", "3")
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "first" / "run_manifest.json").read_text())
            self.assertEqual(len(manifest["runs"]), 3)
            self.assertEqual(len({row["seed"] for row in manifest["runs"]}), 3)
            collected = subprocess.run([
                sys.executable, str(COLLECT), "--runs-dir", str(root / "first"),
                "--caselist", str(root / "cases.txt"), "--result-prefix", "DEMO",
            ], capture_output=True, text=True)
            self.assertEqual(collected.returncode, 1, collected.stderr)
            failed = json.loads((root / "first" / "failed-runs.json").read_text())
            self.assertEqual(len(failed["runs"]), 1)
            self.assertEqual(failed["runs"][0]["iteration"], 1)
            replay = self.run_round(root, "second", "--replay-manifest", str(root / "first" / "failed-runs.json"))
            self.assertEqual(replay.returncode, 0, replay.stderr)
            replayed = json.loads((root / "second" / "run_manifest.json").read_text())
            self.assertEqual(replayed["run_kind"], "failure-rerun")
            self.assertEqual(replayed["runs"][0]["seed"], failed["runs"][0]["seed"])
            self.assertEqual(len(json.loads((root / "first" / "run_manifest.json").read_text())["runs"]), 3)

    def test_fixed_repeat_reuses_seed_and_refuses_history_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.prepare_fake(root)
            result = self.run_round(root, "runs", "--seed", "42", "--repeat", "3")
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "runs" / "run_manifest.json").read_text())
            self.assertEqual([row["seed"] for row in manifest["runs"]], [42, 42, 42])
            refused = self.run_round(root, "runs", "--seed", "43")
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual((root / "runs" / "batch_seed.txt").read_text(), "42\n")

    def test_conflicting_modes_and_repeat_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.prepare_fake(root)
            for options in (("--repeat", "0"), ("--seed-mode", "random", "--seed", "42")):
                result = self.run_round(root, "runs", *options)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / "runs" / "run_manifest.json").exists())

    def test_collector_rejects_pass_banner_with_command_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.prepare_fake(root)
            (root / "fake.py").write_text("import sys\nprint('DEMO ' + sys.argv[1] + ' : PASSED')\nsys.exit(3)\n")
            result = self.run_round(root, "runs", "--seed", "42")
            self.assertEqual(result.returncode, 0)
            collected = subprocess.run([
                sys.executable, str(COLLECT), "--runs-dir", str(root / "runs"),
                "--caselist", str(root / "cases.txt"), "--result-prefix", "DEMO",
            ], capture_output=True, text=True)
            self.assertEqual(collected.returncode, 1, collected.stderr)
            report = json.loads((root / "runs" / "report.json").read_text())
            self.assertEqual(report["results"][0]["returncode"], 3)
            self.assertEqual(report["results"][0]["verdict"], "FAIL")
            self.assertEqual(len(json.loads((root / "runs" / "failed-runs.json").read_text())["runs"]), 1)

    def test_replay_rejects_seed_mode_conflicts(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest_path = Path(temp) / "manifest.json"
            for mode, seeds in (("fixed", [17, 29]), ("random", [17, 17])):
                for run_kind in ("planned", "failure-rerun"):
                    manifest_path.write_text(json.dumps({
                        "schema": "PortableRegressionRunManifest/1", "seed_mode": mode,
                        "repeat": 2, "run_kind": run_kind,
                        "runs": [{"test": "demo_test", "seed": seed, "iteration": index}
                                 for index, seed in enumerate(seeds)],
                    }))
                    with self.assertRaises(ValueError):
                        replay_runs(manifest_path, ["demo_test"])

    def test_parallel_launches_cannot_claim_same_empty_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "runs"
            output.mkdir()
            barrier = threading.Barrier(2)

            def claim():
                barrier.wait()
                try:
                    claim_output_directory(output)
                    return True
                except ValueError:
                    return False

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: claim(), range(2)))
            self.assertEqual(sorted(results), [False, True])
            self.assertTrue((output / ".run-claim").is_dir())
            with self.assertRaises(ValueError):
                claim_output_directory(output)

    def test_empty_failure_rerun_is_successful_noop(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.prepare_fake(root)
            (root / "cases.txt").write_text("")
            manifest_path = root / "failed-runs.json"
            manifest_path.write_text(json.dumps({
                "schema": "PortableRegressionRunManifest/1", "seed_mode": "random",
                "repeat": 3, "run_kind": "failure-rerun", "runs": [],
            }))
            result = self.run_round(root, "rerun", "--replay-manifest", str(manifest_path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((root / "rerun" / "batch.json").read_text())["results"], [])
            collected = subprocess.run([
                sys.executable, str(COLLECT), "--runs-dir", str(root / "rerun"),
                "--caselist", str(root / "cases.txt"), "--result-prefix", "DEMO",
            ], capture_output=True, text=True)
            self.assertEqual(collected.returncode, 0, collected.stderr)

    def test_collector_rejects_timeout_or_missing_command_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.prepare_fake(root)
            result = self.run_round(root, "runs", "--seed", "42")
            self.assertEqual(result.returncode, 0, result.stderr)
            batch_path = root / "runs" / "batch.json"
            batch = json.loads(batch_path.read_text())
            batch["results"][0]["timed_out"] = True
            batch_path.write_text(json.dumps(batch))
            for verdict in ("FAIL", "CRASH"):
                collected = subprocess.run([
                    sys.executable, str(COLLECT), "--runs-dir", str(root / "runs"),
                    "--caselist", str(root / "cases.txt"), "--result-prefix", "DEMO",
                ], capture_output=True, text=True)
                self.assertEqual(collected.returncode, 1, collected.stderr)
                report = json.loads((root / "runs" / "report.json").read_text())
                self.assertEqual(report["results"][0]["verdict"], verdict)
                if verdict == "FAIL":
                    batch_path.unlink()

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
