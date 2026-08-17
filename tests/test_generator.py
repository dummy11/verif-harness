from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts/verif_harness.py"


class GeneratorTest(unittest.TestCase):
    def test_generates_six_additive_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [sys.executable, str(GENERATOR), "init", "demo_dut", "--output", temp],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            root = Path(temp)
            expected = [
                root / "interfaces/demo_dut_if.sv",
                root / "tb/harness/demo_dut_tb_harness.sv",
                root / "tb/demo_dut_tb_top.sv",
                root / "sva/demo_dut_checker.sv",
                root / "bind/demo_dut_bind.sv",
                root / "filelists/demo_dut.f",
            ]
            self.assertTrue(all(path.is_file() for path in expected))
            self.assertNotIn("<DUT>", "".join(path.read_text() for path in expected))

    def test_refuses_overwrite_without_partial_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            existing = root / "bind/demo_dut_bind.sv"
            existing.parent.mkdir(parents=True)
            existing.write_text("human content\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(GENERATOR), "init", "demo_dut", "--output", temp],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(existing.read_text(), "human content\n")
            self.assertFalse((root / "interfaces/demo_dut_if.sv").exists())

    def test_rejects_unsafe_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [sys.executable, str(GENERATOR), "init", "../private", "--output", temp],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_exposes_bounded_spec_kit_operations(self) -> None:
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "spec-kit", "--help"],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for operation in ("probe", "bootstrap", "stage", "status", "resume"):
            self.assertIn(operation, result.stdout)


if __name__ == "__main__":
    unittest.main()
