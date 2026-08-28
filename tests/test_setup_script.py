from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
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
        self.assertIn("--workspace-root PATH", result.stderr)
        self.assertIn("--runtime codex|kimi", result.stderr)
        self.assertIn("--isolation managed", result.stderr)
        self.assertIn("--no-agent", result.stderr)

    def test_shell_neutral_dispatcher_detects_shell_family(self) -> None:
        source = DISPATCHER.read_text(encoding="utf-8")
        self.assertIn("csh|tcsh", source)
        self.assertIn('exec csh "$script_dir/setup.csh"', source)
        self.assertIn('exec bash "$script_dir/setup.sh"', source)

    def test_csh_entrypoint_delegates_without_csh_parsing_bash(self) -> None:
        source = (ROOT / "scripts/setup.csh").read_text(encoding="utf-8")
        self.assertIn("#!/bin/csh", source)
        self.assertIn("where -p", source)
        self.assertIn('exec "$bash_path" "$script_dir/setup.sh"', source)
        self.assertNotIn("python3", source)
        self.assertNotRegex(source, r"(?m)^\s*echo .*>&2")

    @unittest.skipUnless(shutil.which("csh"), "csh is not installed")
    def test_csh_error_does_not_create_a_file_named_2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entrypoint = root / "setup.csh"
            shutil.copy2(ROOT / "scripts/setup.csh", entrypoint)
            result = subprocess.run(
                [shutil.which("csh"), "-f", str(entrypoint)],
                cwd=root,
                env=os.environ,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Bash setup implementation is missing", result.stderr)
            self.assertFalse((root / "2").exists())

    @unittest.skipUnless(shutil.which("csh"), "csh is not installed")
    def test_csh_does_not_require_a_host_python(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entrypoint = root / "setup.csh"
            shutil.copy2(ROOT / "scripts/setup.csh", entrypoint)
            setup = root / "setup.sh"
            setup.write_text(
                '#!/bin/sh\nprintf "%s\\n" managed-bootstrap\n',
                encoding="utf-8",
            )
            setup.chmod(0o755)
            environment = os.environ.copy()
            environment.pop("VERIF_HARNESS_PYTHON", None)
            result = subprocess.run(
                [shutil.which("csh"), "-f", str(entrypoint)],
                cwd=root,
                env=environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "managed-bootstrap")
            self.assertFalse((root / "2").exists())

    def test_setup_uses_managed_python(self) -> None:
        source = SETUP.read_text(encoding="utf-8")
        self.assertIn('setup_managed.sh" --project-root', source)
        self.assertIn('export VERIF_HARNESS_PYTHON="$python_cmd"', source)
        self.assertIn('export PYTHON="$python_cmd"', source)
        self.assertNotIn('VERIF_HARNESS_PYTHON:-python3', source)
        self.assertNotIn('"$python_cmd" -m pip install', source)
        self.assertNotIn('python3 "$package_root/scripts/setup_xverif.py"', source)

    def test_setup_does_not_require_make_for_the_default_path(self) -> None:
        source = SETUP.read_text(encoding="utf-8")
        self.assertNotIn("make --version", source)

    def test_missing_workspace_root_fails_before_installation(self) -> None:
        result = self.run_setup("--workspace-root", "/path/that/does/not/exist")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("workspace root does not exist", result.stderr)

    def test_invalid_runtime_fails_before_installation(self) -> None:
        result = self.run_setup("--runtime", "unknown", "--no-agent")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime must be codex or kimi", result.stderr)

    def test_unimplemented_isolation_fails_before_installation(self) -> None:
        result = self.run_setup("--isolation", "apptainer", "--no-agent")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("isolation backend is not implemented", result.stderr)

    def test_legacy_optional_flags_are_removed(self) -> None:
        result = self.run_setup("--with-xverif", "--no-agent")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage:", result.stderr)

    def test_script_installs_all_managed_surfaces_and_launches_selected_cli(self) -> None:
        source = SETUP.read_text(encoding="utf-8")
        self.assertIn('setup_xverif.py" --project-root', source)
        self.assertIn('setup_wavepeek.py" --project-root', source)
        self.assertIn('--project-root "$package_root"', source)
        self.assertIn("-c 'import mcp'", source)
        self.assertIn("from mcp.server.fastmcp import FastMCP", source)
        self.assertIn("import xverif_mcp.server", source)
        self.assertIn("check_runtime_versions.py", source)
        self.assertIn("--require-agent", source)
        self.assertIn('exec "$agent_cli"', source)
        self.assertIn('agent_args+=(--yolo)', source)
        self.assertIn('.codex/config.toml', source)
        self.assertIn('.kimi-code/local.toml', source)
        self.assertIn('configure_response_language.py', source)
        self.assertIn('--project-root "$workspace_root" --runtime "$runtime"', source)
        self.assertIn('xverif mcp configure', source)
        self.assertIn('xverif mcp status', source)
        self.assertIn('--project-root "$workspace_root" --runtime "$runtime"', source)
        self.assertIn('Refusing to fall back to global Codex settings.', source)
        self.assertIn('~/.kimi-code/config.toml', source)
        self.assertIn('.agents/skills', source)
        self.assertIn('.kimi-code/skills', source)
        self.assertIn('cd "$workspace_root"', source)
        self.assertIn('Starting $runtime CLI here: $(pwd)', source)
        self.assertIn("codex_startup_inventory_prompt=", source)
        self.assertIn("configured, connection pending", source)
        self.assertIn('agent_args+=("$codex_startup_inventory_prompt")', source)
        self.assertIn("Kimi starts directly without a blocking inventory turn", source)
        self.assertIn("use /skills and /mcp for the live inventory", source)
        self.assertNotIn("kimi_inventory_args", source)
        self.assertNotIn('"$agent_cli" --prompt', source)
        self.assertIn('exec "$agent_cli" "${agent_args[@]}"', source)
        self.assertIn('workspace disappeared before Agent launch', source)


if __name__ == "__main__":
    unittest.main()
