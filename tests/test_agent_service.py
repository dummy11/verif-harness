"""Restart-safe VDOC continuation using isolated projects and a fake CLI."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest import mock

from tests import test_dashboard as fixtures
from verif_harness import agent_service as service
from verif_harness.store import HarnessError, now


class AgentServiceTest(unittest.TestCase):
    def setUp(self):
        self.fixture = f = fixtures.DashboardTest()
        f.setUp()
        f.design_minimal_vdoc()
        self.store = f.store
        self.node = next(item for item in self.store.workstream("VDOC")["desired_state"]
                         if item.get("role") == "document-writing-plan")

    def tearDown(self):
        self.fixture.tearDown()

    def feedback(self):
        state = self.store.node_plan_review_state(self.node["id"])
        self.fixture.post("/api/reviews/node-plan-section", {
            "node": self.node["id"], "section": state["sections"][0]["section"],
            "definition_digest": state["definition_digest"], "verdict": "modify",
            "reviewer": "fixture-owner", "reason": "明确接口检查内容",
        }, self.fixture.server.write_token)
        state = self.store.node_plan_review_state(self.node["id"])
        return self.fixture.post("/api/reviews/node-feedback-submit", {
            "node": self.node["id"], "definition_digest": state["definition_digest"],
        }, self.fixture.server.write_token)["result"]

    def tasks(self):
        return [item for item in service.candidates(self.store)
                if item["action"]["kind"] == "APPLY_REVIEW_FEEDBACK"]

    def record(self, task, status="FAILED"):
        with self.store.connect() as connection:
            connection.execute("INSERT INTO agent_service_runs "
                               "(id,task_key,revision,action_json,status,created_at) VALUES(?,?,?,?,?,?)",
                               (task["key"], task["key"], task["revision"], json.dumps(task), status, now()))

    def wait_until(self, predicate):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(.05)
        self.fail("Timed out waiting for isolated service")

    def fake_runtime(self):
        manifest = self.store.state / "project.json"
        data = json.loads(manifest.read_text())
        data["runtime"] = "codex"
        manifest.write_text(json.dumps(data))
        binary = self.fixture.root / "bin"
        binary.mkdir()
        executable = binary / "codex"
        executable.write_text(f"#!{sys.executable}\n" + '''
import sys
if '--help' in sys.argv:
    print('--sandbox')
    raise SystemExit(0)
print('fake runtime: no verification change')
''')
        executable.chmod(0o755)
        return mock.patch.dict(os.environ, {"PATH": str(binary) + os.pathsep + os.environ["PATH"]})

    def test_http_submission_is_recovered_without_old_await(self):
        batch = self.feedback()
        task = self.tasks()[0]
        self.assertIn(batch["batch_id"], task["action"]["batch_ids"])
        # Reopening ProjectStore (the equivalent of a new CLI) loses no inbox work.
        reopened = type(self.store)(self.fixture.root)
        self.assertIn(task, service.candidates(reopened))
        self.record(task)
        self.assertFalse(self.tasks())
        service.retry(self.store)
        self.assertEqual(self.tasks()[0]["key"], task["key"])

    def test_answers_create_new_input_and_open_questions_block(self):
        self.feedback()
        previous = self.tasks()[0]
        self.record(previous, "COMPLETED")
        question = self.store.ask_agent_question(self.node["id"], "选择检查范围", [
            {"id": "a", "label": "接口", "description": "接口检查"},
            {"id": "b", "label": "复位", "description": "复位检查"},
        ])
        self.assertFalse(self.tasks())
        self.fixture.post("/api/agent-questions/answer", {
            "id": question["id"], "option": "a", "reviewer": "fixture-owner",
        }, self.fixture.server.write_token)
        current = self.tasks()[0]
        self.assertNotEqual(previous["key"], current["key"])
        self.assertEqual(current["answers"][0]["answer_option"], "a")

    def test_new_batch_is_not_suppressed_by_old_attempt(self):
        batch = self.feedback()
        task = self.tasks()[0]
        self.record(task)
        self.store.complete_review_feedback(batch["batch_id"], "Project Main Agent", "测试夹具处理结果")
        self.feedback()
        self.assertNotEqual(self.tasks()[0]["key"], task["key"])

    def test_process_lock_fences_service_and_interactive(self):
        with service.project_lock(self.store):
            with self.assertRaises(HarnessError):
                with service.project_lock(self.store):
                    self.fail("duplicate owner")
            with self.assertRaises(HarnessError):
                service.interactive(self.store, "codex", None)

    def test_inherited_lock_survives_parent_handle_close(self):
        with service.project_lock(self.store) as fd:
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], pass_fds=(fd,))
        try:
            with self.assertRaises(HarnessError):
                with service.project_lock(self.store):
                    self.fail("orphan runtime was not fenced")
        finally:
            child.terminate()
            child.wait(timeout=5)
        with service.project_lock(self.store):
            pass

    def test_revision_change_prevents_old_launch(self):
        self.feedback()
        task = self.tasks()[0]
        self.store.restart_vdoc_workflow("fixture-owner", "重新形成当前方案", confirm=True)
        with service.project_lock(self.store) as fd, mock.patch.object(service.subprocess, "Popen") as launch:
            service.execute_task(self.store, "codex", task, fd)
        launch.assert_not_called()

    def test_service_heartbeat_does_not_recompute_closure(self):
        before = service.change_token(self.store)
        service.heartbeat(self.store, "WAITING", "等待审批")
        self.assertEqual(service.change_token(self.store), before)
        self.feedback()
        self.assertNotEqual(service.change_token(self.store), before)

    def test_runtime_mismatch_and_kimi_prompt_mode(self):
        with self.assertRaisesRegex(HarnessError, "登记不一致"):
            service.validate_runtime(self.store, "codex")
        with mock.patch.object(service.shutil, "which", return_value="/fake/kimi"), mock.patch.dict(service._KIMI_PRINT, {"/fake/kimi": False}):
            self.assertEqual(service.runtime_command("kimi", "task"), ["/fake/kimi", "--prompt", "task"])
        with mock.patch.object(service.shutil, "which", return_value="/fake/legacy"), mock.patch.object(service, "cli_help", return_value="--print --prompt"):
            self.assertEqual(service.runtime_command("kimi", "task"), ["/fake/legacy", "--print", "--prompt", "task"])
        with mock.patch.object(service.shutil, "which", return_value="/fake/modern"), mock.patch.object(service, "cli_help", return_value="--prompt --agent-file"):
            command = service.runtime_command("kimi", "task")
            self.assertIn("--agent-file", command)
            self.assertTrue(Path(command[2]).is_file())
            self.assertIn("managed `agent-service`", Path(command[2]).read_text())
        prompt = service.prompt_for(self.store, {"revision": 1, "action": {}})
        self.assertIn("--no-wait", prompt)
        self.assertIn("不得批准", prompt)

    def test_successful_dispatch_does_not_approve_plan(self):
        batch = self.feedback()
        task = self.tasks()[0]
        script = (
            "import sys; from pathlib import Path; "
            f"sys.path.insert(0, {str(fixtures.ROOT)!r}); "
            "from verif_harness.store import ProjectStore; "
            f"ProjectStore(Path({str(self.fixture.root)!r})).complete_review_feedback("
            f"{batch['batch_id']!r}, 'Project Main Agent', '测试已处理审批意见')"
        )
        with service.project_lock(self.store) as fd, mock.patch.object(service, "runtime_command", return_value=[sys.executable, "-c", script]):
            service.execute_task(self.store, "codex", task, fd)
        run = self.store.agent_service_status()["latest_run"]
        self.assertEqual(run["status"], "COMPLETED")
        self.assertFalse(self.tasks())
        self.assertNotEqual(self.store.node_plan_review_state(self.node["id"])["status"], "APPROVED")
        self.assertEqual(self.store.activity(run["activity_id"])["status"], "COMPLETED")

    def test_detached_start_reuse_stop_and_no_progress_not_retried(self):
        self.feedback()
        with self.fake_runtime():
            state = service.start(self.store, "codex")
            try:
                self.assertTrue(state["online"])
                self.assertEqual(service.start(self.store, "codex")["pid"], state["pid"])
                self.wait_until(lambda: self.store.agent_service_status()["latest_run"]
                                and self.store.agent_service_status()["latest_run"]["status"] == "FAILED")
                with self.store.read_connect() as connection:
                    count = connection.execute("SELECT count(*) FROM agent_service_runs").fetchone()[0]
                time.sleep(3.2)
                with self.store.read_connect() as connection:
                    self.assertEqual(connection.execute("SELECT count(*) FROM agent_service_runs").fetchone()[0], count)
                with self.fixture.get("/api/snapshot") as response:
                    snapshot = json.loads(response.read())
                self.assertTrue(snapshot["project_agent"]["service"]["online"])
                self.assertIn("尚未推进", snapshot["project_agent"]["service"]["latest_run"]["summary"])
            finally:
                service.stop(self.store)
                self.wait_until(lambda: self.store.agent_service_status()["status"] == "STOPPED")
                os.waitpid(state["pid"], 0)
            # No previous in-memory await and no automatic replay after restart.
            state = service.start(self.store, "codex")
            try:
                self.assertFalse(self.tasks())
            finally:
                service.stop(self.store)
                self.wait_until(lambda: self.store.agent_service_status()["status"] == "STOPPED")
                os.waitpid(state["pid"], 0)

    def test_lost_service_is_not_displayed_as_running(self):
        activity = self.store.create_activity(self.node["id"], "处理验证文档待办", "project-agent")
        with self.store.connect() as connection:
            connection.execute("INSERT INTO agent_service VALUES(1,'codex',?,1,'RUNNING',?,0,'处理中')",
                               (service.OWNER, time.time() - 60))
            connection.execute("INSERT INTO agent_service_runs "
                               "(id,task_key,revision,action_json,status,activity_id,created_at) "
                               "VALUES('lost','lost',1,'{}','RUNNING',?,?)", (activity["id"], now()))
        snapshot = self.store.dashboard_snapshot()
        self.assertFalse(snapshot["project_agent"]["service"]["online"])
        self.assertEqual(snapshot["project_agent"]["service"]["status"], "DISCONNECTED")
        observed = next(item for item in snapshot["activities"] if item["id"] == activity["id"])
        self.assertEqual(observed["status"], "DISCONNECTED")
        self.assertEqual(self.store.activity(activity["id"])["status"], "RUNNING")


if __name__ == "__main__":
    unittest.main()
