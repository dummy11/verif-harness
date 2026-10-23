"""Unchanged VDOC operations must not reopen accepted downstream code nodes."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest
import urllib.error

from tests import test_code_workflow as fixtures
from verif_harness import code_workflow as code, vdoc_artifacts
from verif_harness.store import HarnessError, ProjectStore


class ApprovalStabilityTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CodeWorkflowTest()
        self.fixture.setUp()
        self.store = self.fixture.store
        self.doc = self.fixture.fixture
        self.http = self.doc.fixture
        self.fixture.implement()
        self.fixture.validate()
        self.fixture.approve(self.fixture.delivery)

    def tearDown(self):
        self.fixture.tearDown()

    def assert_accepted(self):
        # Fresh Store and HTTP projections must both retain the original approvals.
        store = ProjectStore(self.store.root)
        for node in (self.fixture.plan_node, self.fixture.delivery):
            self.assertTrue(store.node_plan_review_state(node["id"])["completed"])
        self.assertTrue(store.evaluate_closure("VDOC")["ready"])
        self.assertTrue(store.evaluate_closure("VENV")["ready"])
        with self.http.get("api/snapshot") as response:
            snapshot = json.loads(response.read())
        targets = {self.doc.plan["id"], self.doc.delivery["id"],
                   self.fixture.plan_node["id"], self.fixture.delivery["id"]}
        self.assertFalse(any(row.get("target") in targets
                             for row in snapshot["waiting_for_human"]))

    def test_repeated_document_operations_keep_nodes_reviews_and_versions(self):
        original = self.store.workstream("VDOC")
        doc_versions = self.store.document_artifacts()["versions"]
        code_versions = code.artifacts(self.store)["versions"]
        review = self.store.document_delivery_review_state(self.doc.delivery["id"])["current_review"]
        for operation in (
            self.http.design_minimal_vdoc,
            self.http.register_minimal_vdoc_delivery,
            lambda: self.store.complete_review_agent_check(
                review["id"], "Project Main Agent", "重复核对当前正文及完整清单，无内容变化"),
        ):
            with self.subTest(operation=operation):
                operation()
                self.assertEqual(self.store.workstream("VDOC")["revision"], original["revision"])
                self.assertEqual(self.store.workstream("VDOC")["desired_state"], original["desired_state"])
                self.assertEqual(self.store.document_artifacts()["versions"], doc_versions)
                self.assertEqual(code.artifacts(self.store)["versions"], code_versions)
                self.assert_accepted()
        self.assertTrue(self.fixture.cli("closure", "evaluate", "--workstream", "VENV")["ready"])

    def test_legacy_document_artifact_reuses_original_signature(self):
        artifact_id = "art.doc:verification-plan"
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM vdoc_artifact_versions WHERE artifact_id=?", (artifact_id,)).fetchone()
            signature = vdoc_artifacts.digest(json.loads(row["payload_json"]))
            db.execute("UPDATE vdoc_artifact_versions SET signature=? WHERE artifact_id=?",
                       (signature, artifact_id))
        head = self.doc.head("cap.doc:verification-plan")["data"]["current"]
        self.assertEqual(head["signature"], signature)
        before = self.store.document_artifacts()["versions"]
        review = self.store.document_delivery_review_state(self.doc.delivery["id"])["current_review"]
        self.store.complete_review_agent_check(review["id"], "Project Main Agent", "重复检查说明")
        self.assertEqual(self.doc.head("cap.doc:verification-plan")["data"]["current"], head)
        self.assertEqual(self.store.document_artifacts()["versions"], before)

    def test_duplicate_owner_approvals_do_not_reversion_document(self):
        before = self.store.document_artifacts()["versions"]
        plan = self.store.node_plan_review_state(self.doc.plan["id"])
        delivery = self.store.document_delivery_review_state(self.doc.delivery["id"])
        with self.assertRaisesRegex(HarnessError, "无需重复提交"):
            self.store.complete_node_plan_review(self.doc.plan["id"], plan["definition_digest"], "fixture-owner")
        with self.assertRaisesRegex(HarnessError, "无需重复提交"):
            self.doc.approve()
        for route, body in (
            ("node-plan-complete", {"node": self.doc.plan["id"],
                                    "definition_digest": plan["definition_digest"]}),
            ("document-delivery", {"node": self.doc.delivery["id"], "verdict": "approve",
                                   "definition_digest": delivery["definition_digest"],
                                   "document_digest": delivery["document_digest"]}),
        ):
            with self.assertRaises(urllib.error.HTTPError) as failure:
                self.http.post("/api/reviews/" + route, {**body, "reviewer": "fixture-owner"},
                               self.http.server.write_token)
            self.assertEqual(failure.exception.code, 400)
            self.assertIn("无需重复提交", failure.exception.read().decode())
        self.assertEqual(self.store.node_plan_review_state(self.doc.plan["id"])["completion_reviews"], plan["completion_reviews"])
        self.assertEqual(self.store.document_delivery_review_state(self.doc.delivery["id"])["current_review"], delivery["current_review"])
        self.assertEqual(self.store.document_artifacts()["versions"], before)
        self.assert_accepted()

    def test_adding_delivery_does_not_reset_unchanged_accepted_node(self):
        path = self.store.root / "minimal-vdoc-delivery.json"
        proposal = json.loads(path.read_text())
        extra = {**proposal["nodes"][0], "key": "reset-content", "title": "复位边界独立验收"}
        proposal["nodes"].append(extra)
        path.write_text(json.dumps(proposal))
        original = self.store.document_delivery_review_state(self.doc.delivery["id"])
        self.store.design_workstream("VDOC", None, [], [], [], desired_file=path.name)
        current = self.store.document_delivery_review_state(self.doc.delivery["id"])
        self.assertEqual(current["current_review"], original["current_review"])
        self.assertEqual(current["status"], "APPROVED")
        extra_node = next(n for n in self.store.workstream("VDOC")["desired_state"] if n["key"] == "reset-content")
        self.assertIsNone(self.store.document_delivery_review_state(extra_node["id"])["current_review"])
        self.assertNotEqual(self.doc.head("cap.doc:verification-plan")["status"], "VALID")

    def test_changed_checklist_is_not_registration_metadata(self):
        original = self.doc.head("cap.doc:verification-plan")["data"]["current"]
        review = self.store.document_delivery_review_state(self.doc.delivery["id"])["current_review"]
        with self.store.connect() as db:
            db.execute("INSERT INTO vdoc_legacy_units VALUES(?,?,?,?,?)", (
                "legacy:extra-check", self.doc.delivery["id"],
                json.dumps({"title": "检查复位边界", "statement": "额外复位检查要求"}), "{}", "fixture-time",
            ))
        self.assertNotEqual(self.doc.head("cap.doc:verification-plan")["status"], "VALID")
        self.store.complete_review_agent_check(review["id"], "Project Main Agent", "已检查新增清单要求")
        self.assertNotEqual(self.doc.head("cap.doc:verification-plan")["data"]["current"], original)
        self.assertFalse(self.store.node_plan_review_state(self.fixture.plan_node["id"])["completed"])

    def test_body_and_plan_changes_still_require_new_approval(self):
        old_plan = self.store.node_plan_review_state(self.doc.plan["id"])["current_completion"]
        self.doc.path.write_text(self.doc.path.read_text() + "\n## 新增验证范围\n检查复位。\n")
        self.store.sync_documents(["document:vdoc:verification-plan"])
        self.http.register_minimal_vdoc_delivery()
        state = self.store.document_delivery_review_state(self.doc.delivery["id"])
        self.assertIsNone(state["current_review"])
        self.assertEqual(self.store.node_plan_review_state(self.doc.plan["id"])["current_completion"], old_plan)
        self.assertFalse(self.store.node_plan_review_state(self.fixture.plan_node["id"])["completed"])
        self.doc.finish()
        self.assertFalse(self.store.node_plan_review_state(self.fixture.plan_node["id"])["completed"])
        path = self.store.root / "minimal-vdoc-plan.json"
        proposal = json.loads(path.read_text())
        proposal["nodes"][0]["work_content"].append("补充复位边界验证要求")
        path.write_text(json.dumps(proposal))
        previous = self.store.workstream("VDOC")["revision"]
        result = self.store.design_workstream("VDOC", None, [], [], [], desired_file=path.name)
        self.assertEqual(result["revision"], previous + 1)
        node = next(n for n in result["desired_state"] if n["role"] == "document-writing-plan")
        self.assertFalse(self.store.node_plan_review_state(node["id"])["completed"])

    def test_document_body_comparison_uses_last_approval_and_rejects_stale_body(self):
        node = self.doc.delivery
        before = self.store.document_delivery_review_state(node["id"])
        old_body = self.doc.path.read_text()
        self.doc.path.write_text(old_body.replace("当前接口", "当前接口和复位"))
        with self.assertRaisesRegex(HarnessError, "正文版本已变化"):
            self.store.node_definition_changes(node["id"], before["definition_digest"])
        self.store.sync_documents(["document:vdoc:verification-plan"])
        self.http.register_minimal_vdoc_delivery()
        current = self.store.document_delivery_review_state(node["id"])
        result = self.store.node_definition_changes(node["id"], current["definition_digest"], current["document_digest"])
        self.assertEqual(result["previous_review"]["id"], before["current_review"]["id"])
        self.assertEqual(result["baseline_status"], "COMPLETE")
        self.assertEqual(result["changes"], [{"field": "document_body", "before": old_body, "after": self.doc.path.read_text()}])
        with self.assertRaisesRegex(HarnessError, "正文版本已变化"):
            self.store.node_definition_changes(node["id"], current["definition_digest"], before["document_digest"])

    def test_browser_same_node_document_body_changes(self):
        if not shutil.which('node') or subprocess.run(['node', '-e', "require('playwright')"], capture_output=True).returncode:
            self.skipTest('Node.js and Playwright required')
        self.doc.path.write_text(self.doc.path.read_text().replace("当前接口", "当前接口和复位"))
        self.store.sync_documents(["document:vdoc:verification-plan"])
        self.http.register_minimal_vdoc_delivery()
        config = {"url": self.http.url, "project": self.http.server.default_project_id, "token": self.http.server.write_token,
                  "workstream": "VDOC", "node": self.doc.delivery["id"], "field": "document_body", "added": "和复位", "unchanged": "当前接口"}
        result = subprocess.run(['node', str(Path(__file__).with_name('dashboard_approval_subject_browser.cjs'))],
                                input=json.dumps(config), text=True, capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_restart_and_owner_change_request_are_not_noops(self):
        previous = self.store.workstream("VDOC")["revision"]
        request = self.store.add_human_action("VDOC", "REQUEST_CHANGE", "fixture-owner", "增加复位文档范围")
        with self.assertRaisesRegex(HarnessError, "变更要求"):
            self.http.design_minimal_vdoc()
        self.assertEqual(self.store.human_action(request["id"])["status"], "OPEN")
        result = self.store.restart_vdoc_workflow("fixture-owner", "重新形成文档方案", True)
        self.assertEqual(result["revision"], previous + 1)
        # Even identical empty/catalog-only scopes must restart explicitly.
        result = self.store.restart_vdoc_workflow("fixture-owner", "再次确认重新启动", True)
        self.assertEqual(result["revision"], previous + 2)


if __name__ == "__main__":
    unittest.main()
