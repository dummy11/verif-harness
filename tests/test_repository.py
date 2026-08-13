from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryTest(unittest.TestCase):
    def test_structure_checker(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_structure.py")],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_example_config_contract(self) -> None:
        config = json.loads((ROOT / "examples/simple_fifo/config/example.json").read_text())
        self.assertEqual(config["top"], "simple_fifo_tb_top")
        self.assertEqual(config["expected_marker"], "SIMPLE_FIFO_SMOKE PASS")


if __name__ == "__main__":
    unittest.main()
