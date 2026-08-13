from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills/verif-harness/oss-readiness/scripts/audit_oss_readiness.py"
SPEC = importlib.util.spec_from_file_location("oss_audit", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class OssReadinessTest(unittest.TestCase):
    def test_detects_generic_sensitive_patterns(self) -> None:
        findings = MODULE.scan_text(
            "path=/" + "home/demo/private/file\nserver=27000" + "@license.example.test\n",
            "sample.txt", [],
        )
        codes = {finding.code for finding in findings}
        self.assertIn("ABSOLUTE_USER_PATH", codes)
        self.assertIn("LICENSE_SERVER", codes)

    def test_detects_case_insensitive_denylist_term(self) -> None:
        findings = MODULE.scan_text("Legacy_Project is present\n", "sample.txt", ["legacy_project"])
        self.assertEqual(findings[0].code, "DENYLIST_TERM")

    def test_excludes_denylist_definition_from_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            denylist = root / ".github/public-release-denylist.txt"
            denylist.parent.mkdir(parents=True)
            denylist.write_text("private_project\n", encoding="utf-8")
            findings = MODULE.scan_worktree(root, MODULE.deny_terms(root))
            self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
