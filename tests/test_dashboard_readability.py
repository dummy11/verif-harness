"""Collapsed node content must preserve actions and controlled document reads."""

from pathlib import Path
import shutil
import subprocess
import unittest


class DashboardReadabilityTest(unittest.TestCase):
    def test_node_content_disclosure_and_document_preflight(self):
        if not shutil.which('node') or subprocess.run(
            ['node', '-e', "require('jsdom')"], capture_output=True,
        ).returncode:
            self.skipTest('Node.js and jsdom are required for this DOM test')
        script = Path(__file__).with_name('dashboard_node_readability_dom.cjs')
        result = subprocess.run(['node', str(script)], text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('document preflight PASS', result.stdout)
