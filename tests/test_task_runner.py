from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import task_runner as RUNNER  # noqa: E402


def write_project(root: Path, tasks: str) -> tuple[Path, Path]:
    feature = root / "specs/001-test"
    feature.mkdir(parents=True)
    tasks_path = feature / "tasks.md"
    tasks_path.write_text(tasks, encoding="utf-8")
    specify = root / ".specify"
    specify.mkdir()
    (specify / "feature.json").write_text(
        json.dumps({"feature_directory": "specs/001-test"}), encoding="utf-8"
    )
    run_dir = specify / "workflows/runs/abc12345"
    run_dir.mkdir(parents=True)
    return tasks_path, run_dir


def task_text(*, checked: bool = False, blocker: str = "") -> str:
    marker = "x" if checked else " "
    return f"""# Tasks

## Blockers

{blocker}

## Work

- [{marker}] T001 [VF-001] First task
  - mode: `interface`
  - outputs: `out/one.txt`; evidence: `evidence/one.json`
  - validate: `test -f out/one.txt; true`; needs: `none`; interaction: `none`

- [ ] T002 [P] [VF-002] Second task
  - mode: `package`
  - outputs: `out/two.txt`; evidence: `evidence/two.json`
  - validate: `test -f out/two.txt`; needs: `T001`; interaction: `none`
"""


class TaskRunnerTest(unittest.TestCase):
    def test_agent_prompt_requires_shell_safe_rtl_discovery(self) -> None:
        prompt = RUNNER._prompt(
            "abc12345",
            {
                "task_id": "T001",
                "description": "Initialize Stage 0",
                "trace": "VF-001",
                "mode": "init",
                "outputs": [".harness-config.json"],
                "evidence": [".harness/review/stage0_review_packet.md"],
                "validate": "test -f .harness-config.json",
            },
            "$verif-harness",
        )

        self.assertIn("rg/rg --files", prompt)
        self.assertIn("反引号", prompt)
        self.assertIn("必须放在单引号", prompt)
        self.assertIn("禁止用分号拼接", prompt)

    def test_compact_parser_keeps_only_execution_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.md"
            path.write_text(task_text(), encoding="utf-8")
            tasks, blockers = RUNNER.parse_tasks(path)

        self.assertEqual([task.task_id for task in tasks], ["T001", "T002"])
        self.assertEqual(tasks[1].trace, "VF-002")
        self.assertEqual(tasks[1].needs, ("T001",))
        self.assertEqual(tasks[0].validate, "test -f out/one.txt; true")
        self.assertEqual(blockers, [])

    def test_parser_rejects_prose_as_validation_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.md"
            source = task_text().replace(
                "`test -f out/one.txt; true`",
                "`summarize_validation_result 输出无未解决关键项`",
                1,
            )
            path.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(RUNNER.TaskRunnerError, "not available"):
                RUNNER.parse_tasks(path)

    def test_parser_rejects_mutating_validation_options(self) -> None:
        for option in ("--fix", "--write", "--update", "--in-place"):
            with self.subTest(option=option), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "tasks.md"
                source = task_text().replace(
                    "`test -f out/one.txt; true`",
                    f"`python3 scripts/check.py {option}`",
                    1,
                )
                path.write_text(source, encoding="utf-8")
                with self.assertRaisesRegex(RUNNER.TaskRunnerError, "must be check-only"):
                    RUNNER.parse_tasks(path)

    def test_doctor_validation_must_preserve_direct_exit_code(self) -> None:
        for command in ("true", "$verif-harness doctor | tee doctor.log", "$verif-harness doctor; true"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "tasks.md"
                source = task_text().replace("mode: `interface`", "mode: `doctor`", 1)
                source = source.replace("`test -f out/one.txt; true`", f"`{command}`", 1)
                path.write_text(source, encoding="utf-8")
                with self.assertRaisesRegex(
                    RUNNER.TaskRunnerError,
                    "doctor validation must (invoke doctor directly|preserve its direct exit code)",
                ):
                    RUNNER.parse_tasks(path)

    def test_review_rejects_owned_paths_inside_configured_rtl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            write_project(project, task_text().replace("out/one.txt", "rtl/generated.txt"))
            (project / ".harness-config.json").write_text(
                json.dumps({"rtl": {"root": "rtl/"}}), encoding="utf-8"
            )
            with self.assertRaisesRegex(RUNNER.TaskRunnerError, "read-only DUT RTL"):
                RUNNER.validate_document(project)

    def test_parser_rejects_semicolon_separated_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.md"
            source = task_text().replace(
                "outputs: `out/one.txt`",
                "outputs: `out/one.txt`; `out/extra.txt`",
                1,
            )
            path.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(RUNNER.TaskRunnerError, "use commas"):
                RUNNER.parse_tasks(path)

    def test_parser_accepts_comma_separated_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.md"
            source = task_text().replace(
                "outputs: `out/one.txt`",
                "outputs: `out/one.txt`, `out/extra.txt`",
                1,
            )
            path.write_text(source, encoding="utf-8")
            tasks, _ = RUNNER.parse_tasks(path)
            self.assertEqual(tasks[0].outputs, ("out/one.txt", "out/extra.txt"))

    def test_open_blocker_prevents_task_review_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            write_project(project, task_text(blocker="- B001 [OPEN] Need simulator authority"))
            with self.assertRaisesRegex(RUNNER.TaskRunnerError, "B001"):
                RUNNER.validate_document(project)

    def test_prechecked_task_without_run_state_is_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            _, run_dir = write_project(project, task_text(checked=True))
            with self.assertRaisesRegex(RUNNER.TaskRunnerError, "pre-checked"):
                RUNNER.initialize_state(project, run_dir, "abc12345", "codex")

    def test_runner_completes_each_task_once_and_marks_checkboxes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            tasks_path, run_dir = write_project(project, task_text())

            def build(_runtime: str, prompt: str) -> list[str]:
                task_id = "one" if "T001" in prompt else "two"
                code = (
                    "from pathlib import Path;"
                    f"Path('out').mkdir(exist_ok=True);Path('out/{task_id}.txt').write_text('ok');"
                    f"Path('evidence').mkdir(exist_ok=True);Path('evidence/{task_id}.json').write_text('{{}}')"
                )
                return [sys.executable, "-c", code]

            state = RUNNER.run_tasks(
                project, run_dir, "abc12345", "codex", "$verif-harness", build
            )

            self.assertEqual(state["status"], "DONE")
            self.assertEqual([task["attempts"] for task in state["tasks"]], [1, 1])
            source = tasks_path.read_text(encoding="utf-8")
            self.assertIn("- [x] T001", source)
            self.assertIn("- [x] T002", source)

    def test_block_and_resume_retries_only_the_current_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            tasks_path, run_dir = write_project(project, task_text())

            def block(_runtime: str, prompt: str) -> list[str]:
                if "T001" in prompt:
                    code = (
                        "from pathlib import Path;"
                        "Path('out').mkdir(exist_ok=True);Path('out/one.txt').write_text('ok');"
                        "Path('evidence').mkdir(exist_ok=True);Path('evidence/one.json').write_text('{}')"
                    )
                    return [sys.executable, "-c", code]
                command = [
                    sys.executable,
                    str(ROOT / "scripts/verif_harness.py"),
                    "block",
                    "abc12345",
                    "T002",
                    "--project-root",
                    str(project),
                    "--kind",
                    "human",
                    "--question",
                    "请选择 reviewed profile",
                ]
                code = f"import subprocess,time;subprocess.run({command!r},check=True);time.sleep(30)"
                return [sys.executable, "-c", code]

            started = time.monotonic()
            blocked = RUNNER.run_tasks(
                project, run_dir, "abc12345", "codex", "$verif-harness", block
            )
            self.assertLess(time.monotonic() - started, 5)
            self.assertEqual(blocked["status"], "BLOCKED")
            self.assertEqual(blocked["current_task_id"], "T002")
            self.assertEqual(blocked["tasks"][0]["attempts"], 1)
            with self.assertRaisesRegex(RUNNER.TaskRunnerError, "requires --answer"):
                RUNNER.run_tasks(
                    project, run_dir, "abc12345", "codex", "$verif-harness", block
                )

            def finish(_runtime: str, _prompt: str) -> list[str]:
                code = (
                    "from pathlib import Path;"
                    "Path('out').mkdir(exist_ok=True);Path('out/two.txt').write_text('ok');"
                    "Path('evidence').mkdir(exist_ok=True);Path('evidence/two.json').write_text('{}')"
                )
                return [sys.executable, "-c", code]

            done = RUNNER.run_tasks(
                project,
                run_dir,
                "abc12345",
                "codex",
                "$verif-harness",
                finish,
                answer="使用已评审的 profile-a",
            )
            self.assertEqual(done["status"], "DONE")
            self.assertEqual(done["tasks"][0]["attempts"], 1)
            self.assertEqual(done["tasks"][1]["attempts"], 2)
            self.assertIn("- [x] T002", tasks_path.read_text(encoding="utf-8"))

    def test_execution_blocker_reconciles_before_agent_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            tasks_path, run_dir = write_project(project, task_text())
            state = RUNNER.initialize_state(project, run_dir, "abc12345", "codex")
            state["status"] = "BLOCKED"
            state["current_task_id"] = "T001"
            state["tasks"][0]["status"] = "BLOCKED"
            state["tasks"][0]["attempts"] = 1
            state["tasks"][0]["blocker"] = {
                "kind": "execution",
                "question": "doctor command was unavailable",
            }
            RUNNER.atomic_write_json(RUNNER.state_path(run_dir), state)
            (project / "out").mkdir()
            (project / "evidence").mkdir()
            (project / "out/one.txt").write_text("ok", encoding="utf-8")
            (project / "evidence/one.json").write_text("{}", encoding="utf-8")
            prompts: list[str] = []

            def finish_second(_runtime: str, prompt: str) -> list[str]:
                prompts.append(prompt)
                code = (
                    "from pathlib import Path;"
                    "Path('out/two.txt').write_text('ok');"
                    "Path('evidence/two.json').write_text('{}')"
                )
                return [sys.executable, "-c", code]

            done = RUNNER.run_tasks(
                project, run_dir, "abc12345", "codex", "$verif-harness", finish_second
            )

            self.assertEqual(done["status"], "DONE")
            self.assertEqual(len(prompts), 1)
            self.assertNotIn("T001", prompts[0])
            self.assertIn("T002", prompts[0])
            self.assertEqual(done["tasks"][0]["attempts"], 1)
            self.assertIn("- [x] T001", tasks_path.read_text(encoding="utf-8"))

    def test_contract_drift_after_authorization_requires_new_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            tasks_path, run_dir = write_project(project, task_text())
            RUNNER.initialize_state(project, run_dir, "abc12345", "codex")
            tasks_path.write_text(
                tasks_path.read_text(encoding="utf-8").replace("mode: `interface`", "mode: `env`"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RUNNER.TaskRunnerError, "changed after authorization"):
                RUNNER.run_tasks(
                    project,
                    run_dir,
                    "abc12345",
                    "codex",
                    "$verif-harness",
                    lambda _runtime, _prompt: [],
                )

    def test_analyze_cannot_change_tasks_after_task_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            tasks_path, run_dir = write_project(project, task_text())
            RUNNER.record_reviewed_contract(project, run_dir, "abc12345")
            tasks_path.write_text(
                tasks_path.read_text(encoding="utf-8").replace("mode: `interface`", "mode: `env`"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RUNNER.TaskRunnerError, "changed after review-tasks"):
                RUNNER.require_reviewed_contract(project, run_dir, "abc12345")

    def test_agent_cannot_change_task_contract_while_running(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            _, run_dir = write_project(project, task_text())

            def drift(_runtime: str, _prompt: str) -> list[str]:
                code = (
                    "from pathlib import Path;"
                    "p=Path('specs/001-test/tasks.md');"
                    "p.write_text(p.read_text().replace('mode: `interface`','mode: `env`'));"
                    "Path('out').mkdir(exist_ok=True);Path('out/one.txt').write_text('ok');"
                    "Path('evidence').mkdir(exist_ok=True);Path('evidence/one.json').write_text('{}')"
                )
                return [sys.executable, "-c", code]

            state = RUNNER.run_tasks(
                project, run_dir, "abc12345", "codex", "$verif-harness", drift
            )
            self.assertEqual(state["status"], "BLOCKED")
            self.assertEqual(state["tasks"][0]["blocker"]["kind"], "specification")

    def test_reviewed_revision_rebinds_and_reconciles_blocked_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            tasks_path, run_dir = write_project(project, task_text())
            state = RUNNER.initialize_state(project, run_dir, "abc12345", "codex")
            state["status"] = "BLOCKED"
            state["current_task_id"] = "T001"
            state["tasks"][0]["status"] = "BLOCKED"
            state["tasks"][0]["attempts"] = 1
            state["tasks"][0]["blocker"] = {
                "kind": "execution",
                "question": "legacy validation exited 127",
            }
            RUNNER.atomic_write_json(RUNNER.state_path(run_dir), state)
            tasks_path.write_text(
                tasks_path.read_text(encoding="utf-8").replace(
                    "test -f out/one.txt; true", "test -f out/one.txt", 1
                ),
                encoding="utf-8",
            )
            (project / "out").mkdir()
            (project / "evidence").mkdir()
            (project / "out/one.txt").write_text("ok", encoding="utf-8")
            (project / "evidence/one.json").write_text("{}", encoding="utf-8")

            result = RUNNER.approve_revised_contract(
                project, run_dir, "abc12345", "修正 legacy 自然语言 validation"
            )

            revised = result["task_execution"]
            self.assertEqual(revised["status"], "READY")
            self.assertEqual(revised["tasks"][0]["status"], "DONE")
            self.assertEqual(revised["tasks"][1]["status"], "READY")
            self.assertIn("- [x] T001", tasks_path.read_text(encoding="utf-8"))
            audit = json.loads(
                (run_dir / RUNNER.TASK_REVISIONS_FILE).read_text(encoding="utf-8")
            )
            self.assertTrue(audit[0]["blocked_task_reconciled"])
            review = json.loads(
                (run_dir / RUNNER.TASK_REVIEW_FILE).read_text(encoding="utf-8")
            )
            self.assertEqual(review["review_kind"], "task-contract-revision")

    def test_pre_execution_revision_rebinds_without_creating_task_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            tasks_path, run_dir = write_project(project, task_text())
            original = RUNNER.record_reviewed_contract(
                project, run_dir, "abc12345"
            )
            tasks_path.write_text(
                tasks_path.read_text(encoding="utf-8").replace(
                    "test -f out/two.txt", "test -s out/two.txt", 1
                ),
                encoding="utf-8",
            )

            result = RUNNER.approve_pre_execution_revision(
                project, run_dir, "abc12345", "analyze 后修正 T002 validation"
            )

            self.assertIsNone(RUNNER.read_state(run_dir))
            revision = result["revision"]
            self.assertEqual(revision["review_kind"], "pre-execution-task-contract-revision")
            self.assertEqual(
                revision["old_task_contract_sha256"],
                original["task_contract_sha256"],
            )
            self.assertNotEqual(
                revision["new_task_contract_sha256"],
                original["task_contract_sha256"],
            )
            RUNNER.require_reviewed_contract(project, run_dir, "abc12345")

    def test_contract_revision_refuses_to_rewrite_completed_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            tasks_path, run_dir = write_project(project, task_text())
            state = RUNNER.initialize_state(project, run_dir, "abc12345", "codex")
            state["status"] = "BLOCKED"
            state["current_task_id"] = "T002"
            state["tasks"][0]["status"] = "DONE"
            state["tasks"][1]["status"] = "BLOCKED"
            RUNNER.atomic_write_json(RUNNER.state_path(run_dir), state)
            tasks_path.write_text(
                tasks_path.read_text(encoding="utf-8").replace(
                    "test -f out/two.txt", "test -s out/two.txt", 1
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RUNNER.TaskRunnerError, "after tasks are DONE"):
                RUNNER.approve_revised_contract(
                    project, run_dir, "abc12345", "attempt unsafe rewrite"
                )

    def test_validation_timeout_terminates_the_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "out").mkdir()
            (project / "evidence").mkdir()
            (project / "out/value").write_text("ok", encoding="utf-8")
            (project / "evidence/value").write_text("ok", encoding="utf-8")
            task = {
                "outputs": ["out/value"],
                "evidence": ["evidence/value"],
                "validate": "sleep 30",
            }
            started = time.monotonic()
            reason = RUNNER._validate(
                project, task, project / "validation.log", timeout_seconds=0.1
            )
            self.assertLess(time.monotonic() - started, 5)
            self.assertIn("exceeded", reason or "")

    def test_interrupted_task_reconciles_postconditions_before_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            tasks_path, run_dir = write_project(project, task_text())
            state = RUNNER.initialize_state(project, run_dir, "abc12345", "codex")
            state["status"] = "RUNNING"
            state["current_task_id"] = "T001"
            state["tasks"][0]["status"] = "RUNNING"
            RUNNER.atomic_write_json(RUNNER.state_path(run_dir), state)
            (project / "out").mkdir()
            (project / "evidence").mkdir()
            (project / "out/one.txt").write_text("ok", encoding="utf-8")
            (project / "evidence/one.json").write_text("{}", encoding="utf-8")

            recovered = RUNNER.recover_running_task(project, run_dir, "abc12345")

            self.assertIsNotNone(recovered)
            assert recovered is not None
            self.assertEqual(recovered["status"], "READY")
            self.assertEqual(recovered["tasks"][0]["status"], "DONE")
            self.assertIn("- [x] T001", tasks_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
