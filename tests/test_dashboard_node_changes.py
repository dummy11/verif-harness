from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DashboardNodeChangesTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Dashboard comparison checks require Node.js')
    def test_current_node_comparison_marks_changed_content(self) -> None:
        result = subprocess.run(
            ['node', str(ROOT / 'tests/dashboard_node_changes_unit.cjs'),
             str(ROOT / 'verif_harness/dashboard.html')],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('node changes PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
