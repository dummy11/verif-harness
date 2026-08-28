from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verif_harness_cli", ROOT / "scripts/verif_harness.py")
CLI = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CLI)


class CliAliasTest(unittest.TestCase):
    def test_status_wait_is_bounded(self) -> None:
        self.assertEqual(CLI.bounded_wait_seconds("30"), 30)
        for value in ("0", "51", "not-a-number"):
            with self.assertRaises(CLI.argparse.ArgumentTypeError):
                CLI.bounded_wait_seconds(value)

    def test_doctor_is_a_native_read_only_wrapper_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/verif_harness.py"),
                    "doctor",
                    "--project-root",
                    directory,
                    "--json",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["next_mode"], "init")
            self.assertEqual(payload["findings"][0]["code"], "CONFIG_ABSENT")

    def test_public_short_aliases_map_to_spec_kit_commands(self) -> None:
        self.assertEqual(CLI.COMMAND_ALIASES["probe"], ("spec-kit", "probe"))
        self.assertEqual(CLI.COMMAND_ALIASES["bootstrap"], ("spec-kit", "bootstrap"))
        self.assertEqual(CLI.COMMAND_ALIASES["stage"], ("spec-kit", "stage"))
        self.assertEqual(CLI.COMMAND_ALIASES["workflow-status"], ("spec-kit", "status"))
        self.assertEqual(CLI.COMMAND_ALIASES["workflow-resume"], ("spec-kit", "resume"))
        self.assertEqual(CLI.COMMAND_ALIASES["workflow-recover"], ("spec-kit", "recover"))
        self.assertEqual(CLI.COMMAND_ALIASES["status"], ("spec-kit", "status"))
        self.assertEqual(CLI.COMMAND_ALIASES["resume"], ("spec-kit", "resume"))
        self.assertEqual(CLI.COMMAND_ALIASES["block"], ("spec-kit", "block"))
        self.assertEqual(
            CLI.COMMAND_ALIASES["revise-tasks"], ("spec-kit", "revise-tasks")
        )
        self.assertEqual(CLI.COMMAND_ALIASES["recover"], ("spec-kit", "recover"))
        self.assertEqual(CLI.COMMAND_ALIASES["docs"], ("spec-kit", "docs-zh"))
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

    def test_short_resume_alias_preserves_run_and_verdict(self) -> None:
        raw = ["resume", "abc12345", "--verdict", "approve"]
        alias = CLI.COMMAND_ALIASES[raw[0]]
        self.assertEqual(
            [*alias, *raw[1:]],
            ["spec-kit", "resume", "abc12345", "--verdict", "approve"],
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

    def test_status_for_live_running_worker_forbids_resume(self) -> None:
        guidance = CLI.workflow_action_guidance(
            "abc12345", {"status": "running"}, None, worker_active=True
        )
        self.assertFalse(guidance["resume_allowed"])
        self.assertEqual(guidance["action_required"], "wait-for-worker")
        self.assertEqual(guidance["next_action"], "status abc12345")

    def test_status_for_paused_gate_allows_one_verdict(self) -> None:
        guidance = CLI.workflow_action_guidance(
            "abc12345",
            {"status": "paused", "gate": {"step_id": "review-spec"}},
            None,
            worker_active=False,
        )
        self.assertTrue(guidance["resume_allowed"])
        self.assertEqual(guidance["action_required"], "review-gate")
        self.assertEqual(
            guidance["next_action"],
            "resume abc12345 --verdict approve|reject",
        )

    def test_status_for_execution_blocker_retries_without_fake_answer(self) -> None:
        task_state = {
            "status": "BLOCKED",
            "current_task_id": "T001",
            "tasks": [
                {
                    "task_id": "T001",
                    "status": "BLOCKED",
                    "blocker": {"kind": "execution", "question": "validation failed"},
                }
            ],
        }
        guidance = CLI.workflow_action_guidance(
            "abc12345", {"status": "paused"}, task_state, worker_active=False
        )
        self.assertEqual(guidance["action_required"], "retry-task")
        self.assertEqual(guidance["next_action"], "resume abc12345")

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

    def test_agent_launcher_defaults_stage_and_resume_to_detached(self) -> None:
        arguments = mock.Mock(detach=False, foreground=False)
        with mock.patch.dict(os.environ, {CLI.AGENT_LAUNCH_ENV: "1"}):
            self.assertTrue(CLI.should_detach(arguments))
        arguments.foreground = True
        with mock.patch.dict(os.environ, {CLI.AGENT_LAUNCH_ENV: "1"}):
            self.assertFalse(CLI.should_detach(arguments))

    def test_detached_worker_records_run_log_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            run_id, run_dir = CLI.reserve_workflow_run(project)
            process = mock.Mock(pid=43210)
            with (
                mock.patch.object(CLI, "active_workflow_processes", return_value=[]),
                mock.patch.object(CLI.subprocess, "Popen", return_value=process) as popen,
            ):
                output = io.StringIO()
                with redirect_stdout(output):
                    result = CLI.launch_detached_workflow(
                        project,
                        run_id,
                        "stage",
                        ["spec-kit", "stage", "--stage", "0", "--foreground"],
                    )

            self.assertEqual(result, 0)
            metadata = json.loads(
                (run_dir / CLI.WORKER_METADATA).read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["pid"], 43210)
            self.assertEqual(metadata["run_id"], run_id)
            self.assertTrue((run_dir / CLI.WORKER_LOG).is_file())
            self.assertEqual(
                popen.call_args.kwargs["env"]["SPECKIT_WORKFLOW_RUN_ID"], run_id
            )
            self.assertEqual(popen.call_args.kwargs["env"][CLI.AGENT_LAUNCH_ENV], "0")
            self.assertEqual(json.loads(output.getvalue())["next"], f"status {run_id}")

    def test_confirmed_stale_recovery_preserves_step_and_makes_run_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            run_id = "abc12345"
            run_dir = CLI.workflow_run_dir(project, run_id)
            run_dir.mkdir(parents=True)
            state_path = run_dir / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "workflow_id": "verif-stage-lifecycle",
                        "status": "running",
                        "current_step_index": 12,
                        "current_step_id": "analyze",
                        "step_results": {"review-tasks": {"status": "success"}},
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            old = time.time() - CLI.STALE_RUN_MIN_AGE_SECONDS - 5
            os.utime(state_path, (old, old))
            with mock.patch.object(CLI, "active_workflow_processes", return_value=[]):
                evidence = CLI.recover_stale_workflow(
                    project, run_id, confirmed=True
                )

            recovered = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(recovered["status"], "failed")
            self.assertEqual(recovered["current_step_index"], 12)
            self.assertEqual(recovered["current_step_id"], "analyze")
            self.assertEqual(evidence["current_step_id"], "analyze")
            self.assertTrue((run_dir / "verif-harness-recovery.json").is_file())

    def test_stale_recovery_refuses_a_live_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            run_id = "abc12345"
            run_dir = CLI.workflow_run_dir(project, run_id)
            run_dir.mkdir(parents=True)
            state_path = run_dir / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "workflow_id": "verif-stage-lifecycle",
                        "status": "running",
                    }
                ),
                encoding="utf-8",
            )
            old = time.time() - CLI.STALE_RUN_MIN_AGE_SECONDS - 5
            os.utime(state_path, (old, old))
            with (
                mock.patch.object(CLI, "active_workflow_processes", return_value=[123]),
                self.assertRaisesRegex(CLI.RuntimeSelectionError, "active"),
            ):
                CLI.recover_stale_workflow(project, run_id, confirmed=True)


if __name__ == "__main__":
    unittest.main()
