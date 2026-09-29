"""One current, digest-bound acceptance action across CLI and Dashboard."""

import json
import subprocess
import sys
import unittest
import urllib.error
from unittest import mock

from tests import test_dashboard as fixtures


class DeliveryPendingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = f = fixtures.DashboardTest()
        f.setUp()
        f.design_minimal_vdoc()
        plan = next(n for w in f.store.dashboard_snapshot()["workstreams"]
                    if w["workstream"] == "VDOC" for n in w["nodes"] if n["plan_review"])
        f.store.complete_node_plan_review(
            plan["id"], plan["plan_review"]["definition_digest"], "fixture-owner",
        )
        self.document = f.store.documents("verification_plan.md")[0]
        self.path = f.root / self.document["path"]
        self.path.write_text("# 验证计划\n\n检查当前 DUT 的接口。\n", encoding="utf-8")
        f.store.sync_documents([self.document["id"]])
        plan = f.register_minimal_vdoc_delivery()
        self.node = next(n for n in plan["desired_state"] if n["role"] == "document-deliverable")

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def cli(self, *args: str) -> dict:
        result = subprocess.run(
            [sys.executable, str(fixtures.CLI), *args,
             "--project-root", str(self.fixture.root)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def snapshot(self) -> tuple[dict, dict]:
        with self.fixture.get("/api/snapshot") as response:
            snapshot = json.loads(response.read())
        workstream = next(w for w in snapshot["workstreams"] if w["workstream"] == "VDOC")
        self.assertEqual(self.cli("status", "VDOC")["closure"], workstream["closure"])
        return snapshot, workstream

    def node_actions(self) -> list[dict]:
        return [a for a in self.fixture.store.evaluate_closure("VDOC", persist=False)["actions"]
                if a["target"] == self.node["id"]]

    def submit(self) -> dict:
        f = self.fixture
        state = f.store.document_delivery_review_state(self.node["id"])
        return f.post("/api/reviews/document-delivery", {
            "node": self.node["id"], "definition_digest": state["definition_digest"],
            "document_digest": state["document_digest"], "verdict": "approve",
            "reviewer": "fixture-owner", "notes": "已核对测试正文",
        }, f.server.write_token)

    def test_cli_dashboard_and_agent_share_current_acceptance_action(self) -> None:
        f = self.fixture
        f.store.review_workstream("VCHK", "approve", "fixture-owner", "隔离本测试的负责人待办")
        findings = f.store.model()["findings"]
        self.assertTrue(findings)
        persisted = self.cli("closure", "evaluate", "--workstream", "VDOC")
        snapshot, workstream = self.snapshot()
        self.assertEqual(persisted, workstream["closure"])
        pending = [a for a in workstream["waiting_for_human"] if a["source"] == "closure"]
        self.assertEqual([a["target"] for a in pending], [self.node["id"]])
        self.assertEqual(pending[0]["target_role"], "document-deliverable")
        action = self.node_actions()[0]
        self.assertEqual(action["kind"], "HUMAN_REVIEW")
        self.assertEqual(action["document_digest"], f.store.documents(self.document["id"])[0]["digest"])
        self.assertEqual(snapshot["project_agent"]["status"], "WAITING_FOR_HUMAN")
        self.assertIn("文档正文验收", snapshot["project_agent"]["message"])
        self.assertEqual(workstream["progress"]["satisfied"], 1)
        self.assertEqual(workstream["progress"]["required"], 2)
        self.assertEqual(f.store.model()["findings"], findings)

        self.submit()
        snapshot, workstream = self.snapshot()
        self.assertFalse(workstream["waiting_for_human"])
        self.assertEqual(self.node_actions()[0]["kind"], "CHECK_DOCUMENT_REVIEW")
        delivery = next(n for n in workstream["nodes"] if n["id"] == self.node["id"])
        self.assertEqual(delivery["delivery_review"]["status"], "AGENT_CHECKING")
        self.assertEqual(snapshot["project_agent"]["pending_agent_review_check_count"], 1)
        self.assertEqual(snapshot["project_agent"]["status"], "PENDING")
        self.assertIn("等待 Main Agent 检查", snapshot["project_agent"]["message"])
        self.assertIn("尚无可确认的当前执行记录", snapshot["project_agent"]["message"])
        f.complete_vdoc_internal_work()
        self.cli("agent-review-check", "complete", delivery["delivery_review"]["current_review"]["id"],
                 "--summary", "已检查测试正文、审批和依赖影响")
        _, workstream = self.snapshot()
        delivery = next(n for n in workstream["nodes"] if n["id"] == self.node["id"])
        self.assertEqual(delivery["delivery_review"]["status"], "APPROVED")
        self.assertFalse(self.node_actions())

    def test_old_check_does_not_hide_new_body_and_unavailable_body_is_not_offered(self) -> None:
        self.submit()
        old = self.fixture.store.document_delivery_review_state(self.node["id"])["current_review"]
        self.path.write_text("# 验证计划\n\n新的接口检查内容。\n", encoding="utf-8")
        self.assertNotIn("HUMAN_REVIEW", [a["kind"] for a in self.node_actions()])
        self.fixture.store.sync_documents([self.document["id"]])
        snapshot, workstream = self.snapshot()
        self.assertEqual(self.node_actions()[0]["kind"], "HUMAN_REVIEW")
        self.assertEqual(snapshot["project_agent"]["pending_agent_review_check_count"], 0)
        self.assertEqual(snapshot["project_agent"]["status"], "WAITING_FOR_HUMAN")
        state = self.fixture.store.document_delivery_review_state(self.node["id"])
        self.assertIn(old["id"], [r["id"] for r in state["reviews"]])
        self.path.unlink()
        self.assertNotIn("HUMAN_REVIEW", [a["kind"] for a in self.node_actions()])

    def test_dependency_and_question_blockers_do_not_duplicate_acceptance(self) -> None:
        f = self.fixture
        question = f.store.ask_agent_question(
            self.node["id"], "请确认测试范围",
            [{"id": "yes", "label": "确认范围"}, {"id": "no", "label": "需要修改"}],
        )
        _, workstream = self.snapshot()
        self.assertNotIn("HUMAN_REVIEW", [a["kind"] for a in self.node_actions()])
        self.assertEqual([a["question_id"] for a in workstream["waiting_for_human"]], [question["id"]])
        # A blocked prerequisite must not be bypassed by the ready document.
        with f.store.connect() as connection:
            connection.execute("UPDATE nodes SET status='STALE' WHERE id IN "
                               "(SELECT target FROM edges WHERE source=? AND relation='DEPENDS_ON')",
                               (self.node["id"],))
        self.assertEqual(self.node_actions()[0]["kind"], "WAIT_FOR_DEPENDENCY")

    def test_whole_body_approval_optional_reason_and_later_opinions(self) -> None:
        f = self.fixture
        state = f.store.document_delivery_review_state(self.node["id"])
        payload = {
            "node": self.node["id"], "definition_digest": state["definition_digest"],
            "document_digest": state["document_digest"], "verdict": "approve",
            "reviewer": "fixture-owner", "notes": "", "include_snapshot": False,
        }
        for invalid in ({"reviewer": ""}, {"definition_digest": "stale"},
                        {"document_digest": "stale"}, {"verdict": "modify"}):
            with self.subTest(invalid=invalid), self.assertRaises(urllib.error.HTTPError) as error:
                f.post("/api/reviews/document-delivery", {**payload, **invalid}, f.server.write_token)
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as error:
            f.post("/api/reviews/document-delivery", payload, "invalid-token")
        self.assertEqual(error.exception.code, 403)
        with mock.patch.object(fixtures.ProjectStore, "dashboard_snapshot", side_effect=AssertionError("save must not wait for snapshot")):
            approved = f.post("/api/reviews/document-delivery", payload, f.server.write_token)
        self.assertNotIn("snapshot", approved)
        self.assertEqual(approved["result"]["notes"], "")
        self.assertEqual(approved["result"]["delivery_review"]["status"], "AGENT_CHECKING")
        with self.assertRaises(urllib.error.HTTPError):
            f.post("/api/reviews/document-delivery", payload, f.server.write_token)
        changed = f.post("/api/reviews/document-delivery", {
            **payload, "verdict": "modify", "notes": "补充接口复位条件",
            "change_items": [{"operation": "add", "target": "接口说明", "instruction": "补充接口复位条件"}],
        }, f.server.write_token)["result"]
        review = changed["delivery_review"]
        self.assertEqual(review["current_review"]["verdict"], "MODIFY")
        self.assertEqual(len(review["reviews"]), 2)
        self.assertEqual(review["status"], "CHANGES_REQUESTED")
        self.assertEqual(review["feedback"]["draft_count"], 1)
        self.assertEqual(f.store.model(self.node["id"])["nodes"][0]["status"], "REVIEW_REQUIRED")
        with self.assertRaises(urllib.error.HTTPError) as error:
            f.post("/api/reviews/document-delivery", payload, f.server.write_token)
        self.assertEqual(error.exception.code, 400)
        batch = f.post("/api/reviews/node-feedback-submit", {
            "node": self.node["id"],
            "definition_digest": state["definition_digest"],
            "document_digest": state["document_digest"],
        }, f.server.write_token)["result"]
        self.assertEqual(batch["count"], 1)
        self.assertEqual(
            f.store.document_delivery_review_state(self.node["id"])["status"],
            "AGENT_CHECKING",
        )
        f.store.complete_review_feedback(
            batch["batch_id"], "Project Main Agent", "已补充接口复位条件",
        )
        self.assertEqual(
            f.store.document_delivery_review_state(self.node["id"])["status"],
            "PENDING",
        )
        f.store.complete_review_agent_check(approved["result"]["review_id"], "Project Main Agent", "历史检查仅供审计")
        self.assertIsNone(f.store.document_delivery_review_state(self.node["id"])["agent_check"])
        approved_again = f.post(
            "/api/reviews/document-delivery", payload, f.server.write_token,
        )["result"]
        self.assertEqual(approved_again["delivery_review"]["status"], "AGENT_CHECKING")

    def test_missing_body_cannot_be_approved(self) -> None:
        self.path.unlink()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.submit()
        self.assertEqual(error.exception.code, 400)
        self.assertIn("正文缺失", error.exception.read().decode())


if __name__ == "__main__":
    unittest.main()
