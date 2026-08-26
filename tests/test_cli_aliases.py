from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verif_harness_cli", ROOT / "scripts/verif_harness.py")
CLI = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CLI)


class CliAliasTest(unittest.TestCase):
    def test_public_short_aliases_map_to_spec_kit_commands(self) -> None:
        self.assertEqual(CLI.COMMAND_ALIASES["probe"], ("spec-kit", "probe"))
        self.assertEqual(CLI.COMMAND_ALIASES["bootstrap"], ("spec-kit", "bootstrap"))
        self.assertEqual(CLI.COMMAND_ALIASES["stage"], ("spec-kit", "stage"))
        self.assertEqual(CLI.COMMAND_ALIASES["workflow-status"], ("spec-kit", "status"))
        self.assertEqual(CLI.COMMAND_ALIASES["workflow-resume"], ("spec-kit", "resume"))
        self.assertEqual(CLI.COMMAND_ALIASES["evidence"], ("xverif",))
        self.assertEqual(CLI.COMMAND_ALIASES["waveform"], ("wavepeek",))

    def test_alias_rewrite_supports_setup_inherited_defaults(self) -> None:
        raw = ["bootstrap"]
        alias = CLI.COMMAND_ALIASES[raw[0]]
        self.assertEqual([*alias, *raw[1:]], ["spec-kit", "bootstrap"])

    def test_alias_rewrite_preserves_explicit_cross_project_overrides(self) -> None:
        raw = ["bootstrap", "--project-root", "/tmp/project", "--integration", "codex"]
        alias = CLI.COMMAND_ALIASES[raw[0]]
        self.assertEqual(
            [*alias, *raw[1:]],
            [
                "spec-kit", "bootstrap", "--project-root", "/tmp/project",
                "--integration", "codex",
            ],
        )

    def test_each_review_gate_has_an_independent_verdict_binding(self) -> None:
        for step_id, input_name in CLI.GATE_VERDICT_INPUTS.items():
            payload = {
                "run_id": "abc12345",
                "status": "paused",
                "gate": {"step_id": step_id},
            }
            self.assertEqual(
                CLI.resume_verdict_input(payload, "approve", {input_name}),
                f"{input_name}=approve",
            )

    def test_resume_rejects_legacy_gate_without_safe_binding(self) -> None:
        payload = {
            "run_id": "abc12345",
            "status": "paused",
            "gate": {"step_id": "review-spec"},
        }
        with self.assertRaisesRegex(CLI.RuntimeSelectionError, "predate"):
            CLI.resume_verdict_input(payload, "approve", set())

    def test_run_input_lookup_rejects_path_traversal(self) -> None:
        with self.assertRaisesRegex(CLI.RuntimeSelectionError, "invalid workflow run ID"):
            CLI.spec_kit_run_inputs("../escape", Path("/tmp/project"))

    def test_noninteractive_spec_kit_run_disconnects_stdin(self) -> None:
        completed = mock.Mock(returncode=0)
        with (
            mock.patch.object(CLI, "spec_kit_command", return_value=["specify"]),
            mock.patch.object(CLI.subprocess, "run", return_value=completed) as run,
        ):
            result = CLI.run_spec_kit(
                ["workflow", "run", "workflow.yml"], Path("/tmp/project"),
                noninteractive=True,
            )

        self.assertEqual(result, 0)
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
