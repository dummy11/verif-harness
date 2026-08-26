from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verif_harness_cli", ROOT / "scripts/verif_harness.py"
)
assert SPEC is not None and SPEC.loader is not None
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)
DOCTOR = ROOT / "skills/verif-harness/doctor/scripts/doctor.py"


class RuntimeConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_state(self, runtime: str) -> None:
        state = self.root / ".specify/integration.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(
            json.dumps(
                {
                    "integration_state_schema": 1,
                    "integration": runtime,
                    "default_integration": runtime,
                    "installed_integrations": [runtime],
                }
            ),
            encoding="utf-8",
        )

    def test_explicit_runtime_wins(self) -> None:
        (self.root / ".kimi-code").mkdir()
        resolved = CLI.resolve_runtime(self.root, "codex")
        self.assertEqual(resolved["runtime"], "codex")
        self.assertEqual(resolved["source"], "command-line")

    def test_recorded_runtime_is_authoritative(self) -> None:
        self.write_state("kimi")
        (self.root / ".agents").mkdir()
        payload = CLI.runtime_payload(self.root)
        self.assertEqual(payload["runtime"], "kimi")
        self.assertEqual(payload["skill_dir"], ".kimi-code/skills")
        self.assertFalse(payload["skill_present"])
        self.assertEqual(payload["invocation"], "/skill:verif-harness")

    def test_unique_project_marker_is_detected(self) -> None:
        (self.root / ".agents").mkdir()
        resolved = CLI.resolve_runtime(self.root)
        self.assertEqual(resolved["runtime"], "codex")
        self.assertEqual(resolved["source"], "project-markers")

    def test_ambiguous_markers_require_explicit_choice(self) -> None:
        (self.root / ".agents").mkdir()
        (self.root / ".kimi-code").mkdir()
        with self.assertRaisesRegex(CLI.RuntimeSelectionError, "multiple"):
            CLI.resolve_runtime(self.root)

    def test_no_marker_requires_explicit_choice(self) -> None:
        with self.assertRaisesRegex(CLI.RuntimeSelectionError, "no Agent runtime"):
            CLI.resolve_runtime(self.root)

    def test_unsupported_recorded_runtime_fails_closed(self) -> None:
        self.write_state("claude")
        with self.assertRaisesRegex(CLI.RuntimeSelectionError, "must be one of"):
            CLI.resolve_runtime(self.root)

    def test_kimi_bootstrap_dispatches_selected_integration(self) -> None:
        calls: list[list[str]] = []

        def fake_spec_kit(arguments: list[str], project_root: Path) -> int:
            calls.append(arguments)
            if arguments[0] == "init":
                self.write_state("kimi")
            return 0

        arguments = [
            "verif_harness.py", "spec-kit", "bootstrap",
            "--project-root", str(self.root), "--integration", "kimi",
            "--ignore-agent-tools",
        ]
        with mock.patch.object(CLI, "run_spec_kit", side_effect=fake_spec_kit):
            with mock.patch.object(sys, "argv", arguments):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(CLI.main(), 0)
        self.assertIn("kimi", calls[0])
        self.assertIn("--ignore-agent-tools", calls[0])
        self.assertEqual(calls[1][:3], ["preset", "add", "--dev"])
        self.assertEqual(
            calls[2], ["preset", "add", "constitution-sync", "--priority", "6"]
        )

    def test_bootstrap_inherits_workspace_and_unique_runtime_marker(self) -> None:
        calls: list[tuple[list[str], Path]] = []
        (self.root / ".kimi-code").mkdir()

        def fake_spec_kit(arguments: list[str], project_root: Path) -> int:
            calls.append((arguments, project_root))
            if arguments[0] == "init":
                self.write_state("kimi")
            return 0

        previous = Path.cwd()
        try:
            os.chdir(self.root)
            arguments = ["verif_harness.py", "bootstrap", "--ignore-agent-tools"]
            with mock.patch.object(CLI, "run_spec_kit", side_effect=fake_spec_kit):
                with mock.patch.object(sys, "argv", arguments):
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(CLI.main(), 0)
        finally:
            os.chdir(previous)

        self.assertEqual(calls[0][1], self.root.resolve())
        self.assertIn("kimi", calls[0][0])
        self.assertIn("--ignore-agent-tools", calls[0][0])

    def test_runtime_switch_revalidates_recorded_state(self) -> None:
        self.write_state("codex")

        def fake_spec_kit(arguments: list[str], project_root: Path) -> int:
            self.assertEqual(arguments[:3], ["integration", "switch", "kimi"])
            self.write_state("kimi")
            return 0

        arguments = [
            "verif_harness.py", "runtime", "switch",
            "--project-root", str(self.root), "--to", "kimi",
        ]
        with mock.patch.object(CLI, "run_spec_kit", side_effect=fake_spec_kit):
            with mock.patch.object(sys, "argv", arguments):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(CLI.main(), 0)
        self.assertEqual(CLI.read_runtime_state(self.root)["runtime"], "kimi")

    def test_doctor_reports_supported_runtime(self) -> None:
        self.write_state("kimi")
        config = {
            "project_name": "demo",
            "rtl": {"root": "rtl", "top_module": "dut", "top_file": "rtl/dut.sv"},
            "verif": {"root": "sim", "docs_root": "sim/docs"},
        }
        (self.root / ".harness-config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, str(DOCTOR), "--project-root", str(self.root), "--json"],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        payload = json.loads(result.stdout)
        findings = {item["code"]: item["message"] for item in payload["findings"]}
        self.assertEqual(findings["RUNTIME_ACTIVE"], "Active Agent runtime: kimi.")


if __name__ == "__main__":
    unittest.main()
