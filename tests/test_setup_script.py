from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts/setup.sh"
DISPATCHER = ROOT / "scripts/setup"


class SetupScriptTest(unittest.TestCase):
    def run_setup(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SETUP), *args], check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def test_help_exposes_runtime_and_no_agent(self) -> None:
        result = self.run_setup("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--project-root PATH", result.stderr)
        self.assertIn("--runtime codex|kimi", result.stderr)
        self.assertIn("--no-agent", result.stderr)

    def test_shell_neutral_dispatcher_detects_shell_family(self) -> None:
        source = DISPATCHER.read_text(encoding="utf-8")
        self.assertIn("csh|tcsh", source)
        self.assertIn('exec csh "$script_dir/setup.csh"', source)
        self.assertIn('exec bash "$script_dir/setup.sh"', source)

    def test_csh_entrypoint_delegates_without_csh_parsing_bash(self) -> None:
        source = (ROOT / "scripts/setup.csh").read_text(encoding="utf-8")
        self.assertIn("#!/bin/csh -f", source)
        self.assertIn('exec "$bash_path" "$script_dir/setup.sh"', source)

    def test_missing_project_root_fails_before_installation(self) -> None:
        result = self.run_setup("--project-root", "/path/that/does/not/exist")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("project root does not exist", result.stderr)

    def test_invalid_runtime_fails_before_installation(self) -> None:
        result = self.run_setup("--runtime", "unknown", "--no-agent")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime must be codex or kimi", result.stderr)

    def test_legacy_optional_flags_are_removed(self) -> None:
        result = self.run_setup("--with-xverif", "--no-agent")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage:", result.stderr)

    def test_script_installs_all_managed_surfaces_and_launches_selected_cli(self) -> None:
        source = SETUP.read_text(encoding="utf-8")
        self.assertIn('setup_xverif.py" --project-root', source)
        self.assertIn('setup_wavepeek.py" --project-root', source)
        self.assertIn('setup_spec_kit.py" --project-root', source)
        self.assertIn('--project-root "$package_root"', source)
        self.assertIn('pip install --disable-pip-version-check "mcp[cli]"', source)
        self.assertIn('exec "$agent_cli"', source)
        self.assertIn('agent_args+=(--yolo)', source)
        self.assertIn('.codex/config.toml', source)
        self.assertIn('.kimi-code/local.toml', source)
        self.assertIn('Refusing to fall back to global Codex settings.', source)
        self.assertIn('~/.kimi-code/config.toml', source)
        self.assertIn('.agents/skills', source)
        self.assertIn('.kimi-code/skills', source)
        self.assertIn('cd "$project_root"', source)


if __name__ == "__main__":
    unittest.main()
