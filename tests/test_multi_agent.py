from __future__ import annotations

import datetime as dt
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from verif_harness.cli import main
from verif_harness.store import HarnessError, ProjectStore, Validity


class MultiAgentControlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "rtl").mkdir()
        (self.root / "rtl/dut.sv").write_text(
            "module dut; endmodule\n", encoding="utf-8",
        )
        self.store = ProjectStore(self.root)
        self.store.bootstrap(
            project_name="multi-agent-test", runtime="codex", rtl_roots=["rtl"],
            verif_root="verification", dut_top="dut", dut_top_file="rtl/dut.sv",
        )
        self.plan = self.store.design_workstream("VCHK", None, [], [], [])
        self.store.review_workstream("VCHK", "approve", "test-user", "approved")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def candidate(self, index: int = 0) -> dict:
        candidates = self.store.agent_work_candidates()["actions"]
        self.assertGreater(len(candidates), index)
        return candidates[index]

    def claim(self, index: int = 0, agent_id: str = "checker-1", **kwargs) -> dict:
        action = self.candidate(index)
        return self.store.claim_agent_work(
            action["id"], agent_id, "TestEngineer", "inspect-checking-path",
            write_scope=kwargs.pop("write_scope", []), **kwargs,
        )

    def test_claim_creates_visible_subagent_activity_without_changing_validity(self) -> None:
        assignment = self.claim(write_scope=["verification/checker"])

        self.assertEqual(assignment["status"], "ACTIVE")
        self.assertEqual(assignment["activity"]["status"], "RUNNING")
        self.assertEqual(assignment["runtime"], "codex")
        self.assertEqual(assignment["parent_agent_id"], "project-agent")
        self.assertEqual(assignment["write_scope"], ["verification/checker"])

        snapshot = self.store.dashboard_snapshot()
        collaboration = snapshot["agent_collaboration"]
        self.assertEqual(collaboration["interaction_owner"], "project-agent")
        self.assertEqual(len(collaboration["active_subagents"]), 1)
        self.assertEqual(collaboration["active_subagents"][0]["id"], "checker-1")
        self.assertEqual(snapshot["project_agent"]["active_subagent_count"], 1)

        finished = self.store.finish_agent_work(
            assignment["id"], "checker-1", "COMPLETED", "只读检查完成",
        )
        self.assertEqual(finished["status"], "COMPLETED")
        self.assertEqual(finished["activity"]["status"], "COMPLETED")
        node = self.store.model(assignment["node_id"])["nodes"][0]
        self.assertEqual(node["status"], "UNKNOWN")

    def test_same_node_and_overlapping_write_scope_cannot_be_claimed_twice(self) -> None:
        first_action = self.candidate(0)
        self.store.claim_agent_work(
            first_action["id"], "worker-1", "TestEngineer", "first",
            write_scope=["verification/shared"],
        )
        with self.assertRaisesRegex(HarnessError, "已被另一个 active"):
            self.store.claim_agent_work(
                first_action["id"], "worker-2", "Reviewer", "duplicate-node",
            )

        second_action = self.candidate(0)
        with self.assertRaisesRegex(HarnessError, "write scope.*冲突"):
            self.store.claim_agent_work(
                second_action["id"], "worker-2", "Reviewer", "overlap",
                write_scope=["verification/SHARED/review"],
            )

    def test_waiting_for_parent_is_internal_and_child_cannot_question_human(self) -> None:
        assignment = self.claim()
        waiting = self.store.heartbeat_agent_work(
            assignment["id"], "checker-1", "WAITING_FOR_PARENT",
            "需要 Main Agent 判断是否沿用现有 reference model",
        )
        self.assertEqual(waiting["activity"]["status"], "WAITING_FOR_PARENT")

        snapshot = self.store.dashboard_snapshot()
        self.assertFalse(snapshot["waiting_for_human"])
        self.assertEqual(snapshot["project_agent"]["waiting_subagent_count"], 1)
        self.assertEqual(snapshot["project_agent"]["status"], "RUNNING")

        with self.assertRaisesRegex(HarnessError, "subagent 的工作记录不能直接绑定"):
            self.store.ask_agent_question(
                assignment["node_id"], "是否采用现有模型？",
                [
                    {"id": "yes", "label": "采用", "description": "使用现有模型"},
                    {"id": "no", "label": "不采用", "description": "另行实现"},
                ],
                asked_by="Project Main Agent", activity_id=assignment["activity_id"],
            )

        with self.assertRaisesRegex(HarnessError, "只有 Project Main Agent"):
            self.store.ask_agent_question(
                "project", "是否绕过 Main Agent？",
                [
                    {"id": "yes", "label": "是", "description": "不允许"},
                    {"id": "no", "label": "否", "description": "返回 Main"},
                ],
                asked_by="checker-1",
            )

        for status in ("WAITING_FOR_HUMAN", "COMPLETED"):
            with self.subTest(status=status):
                with self.assertRaisesRegex(HarnessError, "只能通过 agent-work"):
                    self.store.update_activity(
                        assignment["activity_id"], status, "绕过 assignment 状态机",
                    )
        unchanged = self.store.agent_assignment(assignment["id"])
        self.assertEqual(unchanged["status"], "ACTIVE")
        self.assertEqual(unchanged["activity"]["status"], "WAITING_FOR_PARENT")

        main_question = self.store.ask_agent_question(
            "project", "是否允许 Main Agent 沿用现有模型？",
            [
                {"id": "yes", "label": "允许", "description": "继续复核"},
                {"id": "no", "label": "不允许", "description": "重新规划"},
            ],
            asked_by="Project Main Agent",
        )
        self.assertEqual(main_question["status"], "OPEN")
        self.assertEqual(
            self.store.dashboard_snapshot()["waiting_for_human"][0]["question_id"],
            main_question["id"],
        )

    def test_write_scope_rejects_control_plane_and_runtime_metadata(self) -> None:
        manifest_path = self.root / ".verif-harness/project.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["verif_root"] = "."
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        action = self.candidate()
        for protected in (
            ".verif-harness", ".git", ".Git", ".deps", ".codex", ".CODEX",
            ".kimi-code", ".agents", ".harness-config.json", "AGENTS.md", "agents.md",
        ):
            with self.subTest(protected=protected):
                with self.assertRaisesRegex(HarnessError, "控制状态"):
                    self.store.claim_agent_work(
                        action["id"], "worker-1", "TestEngineer", "unsafe-write",
                        write_scope=[protected],
                    )

    def test_expired_assignment_is_recoverable_and_not_a_verification_failure(self) -> None:
        assignment = self.claim()
        expired = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).isoformat()
        with sqlite3.connect(self.store.database) as connection:
            connection.execute(
                "UPDATE agent_assignments SET lease_expires_at=? WHERE id=?",
                (expired, assignment["id"]),
            )

        observed = self.store.agent_assignment(assignment["id"])
        self.assertEqual(observed["status"], "EXPIRED")
        self.assertEqual(observed["activity"]["status"], "CANCELLED")
        node = self.store.model(assignment["node_id"])["nodes"][0]
        self.assertEqual(node["status"], "UNKNOWN")

        replacement = self.store.claim_agent_work(
            assignment["action_id"], "checker-2", "Reviewer", "take-over",
        )
        self.assertEqual(replacement["status"], "ACTIVE")

    def test_replan_supersedes_old_assignment_and_finish_is_idempotent(self) -> None:
        assignment = self.claim()
        self.store.design_workstream("VCHK", None, [], [], [])

        superseded = self.store.finish_agent_work(
            assignment["id"], "checker-1", "COMPLETED", "旧 revision 工作完成",
        )
        self.assertEqual(superseded["status"], "SUPERSEDED")
        self.assertEqual(superseded["activity"]["status"], "CANCELLED")

        self.store.review_workstream("VCHK", "approve", "test-user", "approved again")
        current = self.claim(agent_id="checker-2")
        first = self.store.finish_agent_work(
            current["id"], "checker-2", "COMPLETED", "当前 revision 工作完成",
        )
        second = self.store.finish_agent_work(
            current["id"], "checker-2", "COMPLETED", "重复上报",
        )
        self.assertEqual(first["status"], "COMPLETED")
        self.assertEqual(second["status"], "COMPLETED")

    def test_changed_closure_action_supersedes_old_assignment(self) -> None:
        self.store.design_workstream(
            "VCHK", None, ["custom checking node"], [], [],
            evidence_claims=["scoreboard"],
        )
        self.store.review_workstream("VCHK", "approve", "test-user", "approved again")
        action = next(
            item for item in self.store.agent_work_candidates()["actions"]
            if item["workstream"] == "VCHK" and item["kind"] == "SATISFY_DESIRED_STATE"
        )
        assignment = self.store.claim_agent_work(
            action["id"], "checker-1", "TestEngineer", "inspect-document-contract",
        )
        self.store.set_status(assignment["node_id"], Validity.INVALID)

        superseded = self.store.agent_assignment(assignment["id"])
        self.assertEqual(superseded["status"], "SUPERSEDED")
        self.assertEqual(superseded["activity"]["status"], "CANCELLED")
        replacement = next(
            item for item in self.store.agent_work_candidates()["actions"]
            if item["target"] == assignment["node_id"]
        )
        self.assertEqual(replacement["kind"], "REPAIR_OR_REPLAN")

    def test_completed_child_is_not_reported_as_latest_main_activity(self) -> None:
        main = self.store.create_activity(
            "project", "coordinate-verification", "Project Main Agent", "协调任务",
        )
        self.store.update_activity(main["id"], "COMPLETED", "协调完成")
        assignment = self.claim()
        self.store.finish_agent_work(
            assignment["id"], "checker-1", "COMPLETED", "child 完成",
        )

        snapshot = self.store.dashboard_snapshot()
        self.assertEqual(snapshot["project_agent"]["latest_activity"]["id"], main["id"])
        self.assertIn(
            assignment["activity_id"],
            snapshot["agent_collaboration"]["assignment_activity_ids"],
        )

    def test_agent_work_cli_and_subagent_alias(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([
                "agent-work", "candidates", "--limit", "1",
                "--project-root", str(self.root),
            ])
        self.assertEqual(code, 0)
        action = json.loads(output.getvalue())["actions"][0]

        output = io.StringIO()
        with redirect_stdout(output):
            code = main([
                "subagent", "claim", action["id"], "--agent", "cli-worker",
                "--role", "TestEngineer", "--operation", "cli-contract-test",
                "--write-scope", "verification/cli",
                "--project-root", str(self.root),
            ])
        self.assertEqual(code, 0)
        assignment = json.loads(output.getvalue())
        self.assertEqual(assignment["agent_id"], "cli-worker")
        self.assertEqual(assignment["activity"]["operation"], "cli-contract-test")


if __name__ == "__main__":
    unittest.main()
