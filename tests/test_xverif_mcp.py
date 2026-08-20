from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "skills/verif-harness/xverif/scripts/xverif_mcp.py"


class XverifMcpProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        (self.project / "deps").mkdir(parents=True)
        (self.project / "scripts").mkdir()
        self.commit = "a" * 40
        (self.project / "deps/xverif.lock.json").write_text(
            json.dumps({"commit": self.commit}), encoding="utf-8"
        )
        setup = self.project / "scripts/setup_xverif.py"
        setup.write_text(
            "import json; print(json.dumps({'state': 'READY', 'blockers': []}))\n",
            encoding="utf-8",
        )
        self.no_mcp_python = self.project / "no-mcp-python"
        self.no_mcp_python.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        self.no_mcp_python.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_adapter(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ADAPTER), *arguments, "--project-root", str(self.project)],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def test_configure_writes_non_secret_profile(self) -> None:
        result = self.run_adapter("configure", "--runtime", "codex", "--backend", "direct")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["state"], "CONFIGURED")
        profile = json.loads(
            (self.project / ".harness/mcp/xverif.json").read_text(encoding="utf-8")
        )
        self.assertEqual(profile["source_commit"], self.commit)
        self.assertEqual(profile["registration"], "host-managed")
        self.assertNotIn("command", profile)
        self.assertNotIn("token", json.dumps(profile).lower())

    def test_configure_refuses_overwrite(self) -> None:
        first = self.run_adapter("configure", "--runtime", "kimi")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_adapter("configure", "--runtime", "codex")
        self.assertEqual(second.returncode, 1)
        self.assertIn("refusing to overwrite", second.stderr)

    def test_status_reports_runtime_registration_boundary(self) -> None:
        self.assertEqual(self.run_adapter("configure", "--runtime", "kimi").returncode, 0)
        result = self.run_adapter("status", "--python", str(self.no_mcp_python))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["state"], "MCP_SDK_MISSING")
        self.assertEqual(payload["runtime_registration"], "host-managed")

    def test_probe_is_fail_closed_until_agent_calls_ping(self) -> None:
        result = self.run_adapter("probe")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["state"], "RUNTIME_PROBE_REQUIRED")
        self.assertEqual(payload["tool"], "xverif_ping")


if __name__ == "__main__":
    unittest.main()
