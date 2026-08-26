from __future__ import annotations

import json
import importlib.util
import os
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
        launcher = self.project / ".deps/xverif/tools/xverif-mcp"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        launcher.chmod(0o755)
        (self.project / ".deps/xverif/xverif_mcp/src/xverif_mcp").mkdir(parents=True)
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
        self.assertEqual(profile["registration"], "project-managed")
        self.assertEqual(profile["registration_path"], ".codex/config.toml")
        self.assertNotIn("command", profile)
        self.assertNotIn("token", json.dumps(profile).lower())
        project_launcher = self.project / ".harness/mcp/xverif-mcp"
        self.assertTrue(os.access(project_launcher, os.X_OK))
        codex = (self.project / ".codex/config.toml").read_text(encoding="utf-8")
        self.assertIn("[mcp_servers.xverif]", codex)
        self.assertIn('command = ".harness/mcp/xverif-mcp"', codex)

    def test_configure_is_idempotent_and_can_switch_runtime(self) -> None:
        first = self.run_adapter("configure", "--runtime", "kimi")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_adapter("configure", "--runtime", "kimi")
        self.assertEqual(second.returncode, 0, second.stderr)
        switched = self.run_adapter("configure", "--runtime", "codex")
        self.assertEqual(switched.returncode, 0, switched.stderr)
        profile = json.loads(
            (self.project / ".harness/mcp/xverif.json").read_text(encoding="utf-8")
        )
        self.assertEqual(profile["runtime"], "codex")

    def test_configure_registers_kimi_project_mcp(self) -> None:
        result = self.run_adapter("configure", "--runtime", "kimi")
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(
            (self.project / ".kimi-code/mcp.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            value["mcpServers"]["xverif"]["command"],
            ".harness/mcp/xverif-mcp",
        )

    def test_configure_migrates_legacy_host_managed_profile(self) -> None:
        profile = {
            "schema_version": 1,
            "server_id": "xverif",
            "runtime": "codex",
            "transport": "stdio",
            "backend": "direct",
            "source": "managed-xverif-checkout",
            "source_commit": self.commit,
            "required_tools": [
                "xbit", "xentry", "xloc", "xsva", "xcov", "xdebug", "xwaveform",
            ],
            "environment_keys": [
                "XVERIF_HOME", "XVERIF_MCP_BACKEND", "VERDI_HOME",
                "LD_LIBRARY_PATH", "PATH", "XVERIF_MCP_STARTUP_TIMEOUT_SEC",
                "XVERIF_MCP_REQUEST_TIMEOUT_SEC", "XDEBUG_SESSION_START_TIMEOUT_SEC",
                "XDEBUG_SESSION_IDLE_TIMEOUT_SEC",
            ],
            "registration": "host-managed",
        }
        target = self.project / ".harness/mcp/xverif.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(profile), encoding="utf-8")
        result = self.run_adapter("configure", "--runtime", "codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        migrated = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(migrated["registration"], "project-managed")
        self.assertEqual(migrated["launcher"], ".harness/mcp/xverif-mcp")

    def test_configure_refuses_conflicting_runtime_registration(self) -> None:
        config = self.project / ".codex/config.toml"
        config.parent.mkdir()
        config.write_text(
            '[mcp_servers.xverif]\ncommand = "unmanaged"\n', encoding="utf-8"
        )
        result = self.run_adapter("configure", "--runtime", "codex")
        self.assertEqual(result.returncode, 1)
        self.assertIn("conflicts with setup", result.stderr)

    def test_status_reports_runtime_registration_boundary(self) -> None:
        self.assertEqual(self.run_adapter("configure", "--runtime", "kimi").returncode, 0)
        result = self.run_adapter("status", "--python", str(self.no_mcp_python))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["state"], "MCP_SDK_MISSING")
        self.assertEqual(payload["runtime_registration"], "project-managed")

    def test_probe_is_fail_closed_until_agent_calls_ping(self) -> None:
        result = self.run_adapter("probe")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["state"], "RUNTIME_PROBE_REQUIRED")
        self.assertEqual(payload["tool"], "xverif_ping")

    def test_separate_project_uses_package_dependency_root(self) -> None:
        spec = importlib.util.spec_from_file_location("xverif_mcp_under_test", ADAPTER)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        separate = Path(self.temporary.name) / "separate-project"
        separate.mkdir()
        self.assertEqual(module.dependency_root(separate), ROOT)

    def test_launcher_resolves_managed_runtime_without_embedded_paths(self) -> None:
        spec = importlib.util.spec_from_file_location("xverif_mcp_launcher_test", ADAPTER)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        content = module.launcher_content("direct")
        self.assertIn('.deps/runtime/venv/bin/python', content)
        self.assertIn('.agents/skills/verif-harness', content)
        self.assertNotIn(str(self.project), content)


if __name__ == "__main__":
    unittest.main()
