from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DashboardNodeOrderTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Dashboard ordering checks require Node.js")
    def test_verification_order_and_snapshot_filters(self) -> None:
        result = subprocess.run(
            [
                "node",
                str(ROOT / "tests/dashboard_node_order_unit.cjs"),
                str(ROOT / "verif_harness/dashboard.html"),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("snapshot filters PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
