"""v2 graph gates, version binding and non-destructive v1 migration."""

import json
import unittest
from unittest import mock

from tests import test_dashboard as fixtures
from verif_harness.store import HarnessError, ProjectStore, Validity, now


class VdocArtifactsTest(unittest.TestCase):
    def setUp(self):
        self.fixture = f = fixtures.DashboardTest()
        f.setUp()
        self.store = f.store
        f.design_minimal_vdoc()
        self.plan = next(n for n in self.store.workstream("VDOC")["desired_state"]
                         if n["role"] == "document-writing-plan")

    def tearDown(self):
        self.fixture.tearDown()

    def head(self, node_id):
        return next(n for n in self.store.document_artifacts()["heads"] if n["id"] == node_id)

    def prepare(self):
        state = self.store.node_plan_review_state(self.plan["id"])
        self.store.complete_node_plan_review(self.plan["id"], state["definition_digest"], "fixture-owner")
        document = self.store.documents("verification_plan.md")[0]
        self.path = self.fixture.root / document["path"]
        self.path.write_text("# 验证计划\n\n## DUT 范围\n检查当前接口。\n", encoding="utf-8")
        self.store.sync_documents([document["id"]])
        self.fixture.register_minimal_vdoc_delivery()
        self.delivery = next(n for n in self.store.workstream("VDOC")["desired_state"]
                             if n["role"] == "document-deliverable")

    def approve(self, verdict="approve"):
        state = self.store.document_delivery_review_state(self.delivery["id"])
        return self.store.review_document_delivery(
            self.delivery["id"], state["definition_digest"], state["document_digest"],
            verdict, "fixture-owner", "已审阅当前正文", **({"provisional_owner": "fixture-owner", "review_trigger": "后续复核"}
                                            if verdict == "provisional" else {}))

    def finish(self):
        review = self.approve()
        self.store.complete_review_agent_check(review["review_id"], "Project Main Agent", "已逐项检查正文、清单和依赖")
        return review

    def test_only_two_work_roles_and_three_distinct_result_gates(self):
        self.assertNotEqual(self.head("art.doc_plan:verification-plan")["status"], "VALID")
        self.prepare()
        self.assertEqual(self.head("art.doc_plan:verification-plan")["status"], "VALID")
        self.assertNotEqual(self.head("cap.doc:verification-plan")["status"], "VALID")
        before = self.store.document_manifest(self.delivery["id"])
        self.assertTrue(any(item["kind"] == "body-section" for item in before["items"]))
        approval = self.approve()
        self.assertNotEqual(self.head("art.doc:verification-plan")["status"], "VALID")
        self.assertFalse(approval["delivery_review"]["internal_work"]["ready"])
        self.store.complete_review_agent_check(approval["review_id"], "Project Main Agent", "已检查全部内容清单")
        self.assertEqual(self.head("cap.doc:verification-plan")["status"], "VALID")
        self.assertTrue(self.store.evaluate_closure("VDOC")["ready"])
        self.assertFalse(any(n["role"] == "document-semantic-unit" for n in self.store.workstream("VDOC")["desired_state"]))
        # Other catalog documents are NOT a blanket eight-document gate.
        self.assertNotEqual(self.store.documents("tb_architecture.md")[0]["status"], "VALID")
        with self.store.read_connect() as connection:
            stored = json.loads(connection.execute("SELECT payload_json FROM vdoc_artifact_versions WHERE artifact_id='art.doc:verification-plan'").fetchone()[0])
            self.assertEqual(stored["body"], self.path.read_text())
            self.assertEqual(stored["deliveries"][0]["manifest"]["digest"], before["digest"])
        versions = self.store.document_artifacts()["versions"]
        for _ in range(3):
            self.store.dashboard_snapshot()
        self.assertEqual(self.store.document_artifacts()["versions"], versions)

    def test_unsynced_body_edit_revokes_cap_not_plan_and_preserves_snapshot(self):
        self.prepare()
        self.finish()
        original = self.path.read_text()
        plan_version = self.head("art.doc_plan:verification-plan")["data"]["current"]
        self.path.write_text(original + "\n修改正文\n", encoding="utf-8")
        self.assertNotEqual(self.head("cap.doc:verification-plan")["status"], "VALID")
        self.assertEqual(self.head("art.doc_plan:verification-plan")["data"]["current"], plan_version)
        self.assertFalse(self.store.document_delivery_review_state(self.delivery["id"])["document_available"])
        self.assertNotEqual(self.store.model(self.delivery["id"])["nodes"][0]["status"], "VALID")
        self.assertNotEqual(self.store.node_closure_assessment(self.delivery["id"])["conclusion"], "CLOSED")
        with self.store.read_connect() as connection:
            payload = json.loads(connection.execute("SELECT payload_json FROM vdoc_artifact_versions WHERE artifact_id='art.doc:verification-plan'").fetchone()[0])
            self.assertEqual(payload["body"], original)

    def test_old_review_cannot_certify_new_body_and_provisional_is_not_cap(self):
        self.prepare()
        approval = self.approve("provisional")
        self.store.complete_review_agent_check(approval["review_id"], "Project Main Agent", "已核对条件和正文")
        self.assertNotEqual(self.head("cap.doc:verification-plan")["status"], "VALID")
        self.path.write_text("# 已变更正文\n", encoding="utf-8")
        self.store.sync_documents()
        with self.assertRaisesRegex(HarnessError, "版本"):
            self.store.complete_review_agent_check(approval["review_id"], "Project Main Agent", "旧结果")

    def test_derived_objects_cannot_be_forged_or_run_as_work(self):
        self.prepare()
        for node in ("art.doc:verification-plan", "cap.doc:verification-plan", "art.doc_plan:verification-plan"):
            for action in (
                lambda: self.store.set_status(node, Validity.UNKNOWN),
                lambda: self.store.waive_node(node, "fixture-owner", "fixture"),
                lambda: self.store.add_evidence(node, "document-review", "rtl/dut.sv", "pass"),
                lambda: self.store.create_activity(node, "implement", "agent"),
            ):
                with self.assertRaisesRegex(HarnessError, "不能直接"):
                    action()

    def test_downstream_stays_on_cap_and_reopens_after_body_change(self):
        self.prepare()
        self.finish()
        node = next(n for n in self.store.workstream("VCHK")["desired_state"] if n["key"] == "compare-policy")
        targets = {e["target"] for e in self.store.trace(node["id"])["outgoing"] if e["relation"] == "DEPENDS_ON"}
        self.assertIn("cap.doc:verification-plan", targets)
        self.assertNotIn(self.plan["id"], targets)
        with self.assertRaisesRegex(HarnessError, "cap.doc"):
            self.store.add_dependency(node["id"], self.plan["id"])
        with self.store.connect() as connection:
            connection.execute("UPDATE nodes SET status='VALID' WHERE id=?", (node["id"],))
        self.path.write_text("# Changed current body\n", encoding="utf-8")
        self.store.document_artifacts()
        self.assertEqual(self.store.model(node["id"])["nodes"][0]["status"], "REVALIDATION_REQUIRED")
        self.assertFalse(self.store.evaluate_closure("VCHK")["ready"])

    def test_missing_main_check_is_never_approval(self):
        self.prepare()
        approval = self.approve()
        with self.store.connect() as connection:
            connection.execute("DELETE FROM review_agent_checks WHERE review_id=?", (approval["review_id"],))
            connection.execute("UPDATE nodes SET status='VALID' WHERE id=?", (self.delivery["id"],))
        self.assertEqual(self.store.document_delivery_review_state(self.delivery["id"])["status"], "AGENT_CHECKING")
        self.assertNotEqual(self.head("cap.doc:verification-plan")["status"], "VALID")

    def test_migration_archives_history_preserves_owner_approval_and_rechecks(self):
        self.prepare()
        approval = self.finish()
        old_digest = self.store.node_plan_review_state(self.plan["id"])["definition_digest"]
        plan = self.store.workstream("VDOC")
        unit = self.delivery["internal_semantic_units"][0]
        child = {"id": "legacy:body-unit", "key": "legacy-unit", "title": "旧版内部范围检查",
                 "role": "document-semantic-unit", "parent_role": "document-deliverable",
                 "parent_id": self.delivery["id"], "parent_key": self.delivery["key"],
                 "document_key": self.delivery["document_key"], "semantic_unit_id": unit["id"],
                 "semantic_digest": unit["digest"], "visible_to_human": False, "required": True}
        # Also preserve a legacy extra check, even if absent from the public definition.
        child["semantic_unit_id"] = "legacy-extra-requirement"
        child["statement"] = "检查迁移前尚未确认的额外接口条件"
        plan["desired_state"].append(child)
        with self.store.connect() as connection:
            self.store.upsert_node(connection, child["id"], "desired-state", child["title"], Validity.UNKNOWN, "VDOC", child)
            connection.execute("UPDATE workstreams SET desired_json=? WHERE name='VDOC'", (json.dumps(plan["desired_state"]),))
            connection.execute("INSERT INTO findings VALUES('fixture-finding',?,'HIGH','OPEN',NULL,'待检查接口范围',?)", (child["id"], now()))
            connection.execute("INSERT INTO edges VALUES('file:rtl/dut.sv',?,'AFFECTS','fixture',1,'{}',?)", (child["id"], now()))
            connection.execute("DELETE FROM meta WHERE key IN ('vdoc_graph_v2','vdoc_cap_dependencies','vdoc_graph_checkpoint')")
        self.store = ProjectStore(self.fixture.root)
        self.store.ensure_dashboard_schema()
        current_plan = self.store.workstream("VDOC")
        self.assertNotIn(child["id"], {n["id"] for n in current_plan["desired_state"]})
        review = self.store.node_plan_review_state(self.plan["id"])
        self.assertEqual(review["definition_digest"], old_digest)
        self.assertEqual(review["status"], "APPROVED")
        state = self.store.document_delivery_review_state(self.delivery["id"])
        self.assertEqual(state["current_review"]["id"], approval["review_id"])
        self.assertEqual(state["agent_check"]["status"], "PENDING")
        self.assertNotEqual(self.head("cap.doc:verification-plan")["status"], "VALID")
        self.assertTrue(any(item["content"] == child["statement"] for item in self.store.document_manifest(self.delivery["id"])["items"]))
        with self.store.read_connect() as connection:
            self.assertIsNotNone(connection.execute("SELECT 1 FROM edges WHERE source='file:rtl/dut.sv' AND target=? AND relation='AFFECTS'", (self.delivery["id"],)).fetchone())
            self.assertEqual(connection.execute("SELECT subject FROM findings WHERE id='fixture-finding'").fetchone()[0], self.delivery["id"])
            self.assertIsNone(connection.execute("SELECT workstream FROM nodes WHERE id=?", (child["id"],)).fetchone()[0])
            history = json.loads(connection.execute("SELECT history_json FROM vdoc_legacy_units WHERE node_id=?", (child["id"],)).fetchone()[0])
            self.assertEqual(history["agent_checks"][0]["status"], "COMPLETED")
        with self.assertRaisesRegex(HarnessError, "历史记录"):
            self.store.create_activity(child["id"], "review", "agent")

    def test_unchanged_graph_does_not_scan_history_or_write(self):
        self.prepare()
        self.finish()
        self.store.document_artifacts()
        with mock.patch("verif_harness.vdoc_artifacts.manifest", side_effect=AssertionError("unchanged graph rebuilt")):
            self.store.document_artifacts()
        before = self.store.dashboard_change_token()
        self.store.document_artifacts()
        self.assertEqual(self.store.dashboard_change_token(), before)

    def test_second_body_version_preserves_first_and_reads_exact_result(self):
        self.prepare()
        self.finish()
        first = self.store.document_artifacts("art.doc:verification-plan", 1)
        self.path.write_text("# 验证计划\n\n本轮增加复位检查。\n", encoding="utf-8")
        self.store.sync_documents()
        self.finish()
        self.assertEqual(self.head("cap.doc:verification-plan")["data"]["current"]["version"], 2)
        self.assertEqual(self.store.document_artifacts("art.doc:verification-plan", 1), first)
        self.assertEqual(self.store.document_artifacts("art.doc:verification-plan", 2)["content"]["body"], self.path.read_text())

    def test_changed_plan_blocks_delivery_registration_and_keeps_old_artifacts(self):
        self.prepare()
        self.finish()
        old = self.store.document_artifacts("art.doc:verification-plan", 1)
        self.store.set_status(self.plan["id"], Validity.REVALIDATION_REQUIRED)
        self.assertNotEqual(self.head("art.doc_plan:verification-plan")["status"], "VALID")
        self.assertNotEqual(self.head("cap.doc:verification-plan")["status"], "VALID")
        with self.assertRaisesRegex(HarnessError, "失效"):
            self.fixture.register_minimal_vdoc_delivery()
        self.assertEqual(self.store.document_artifacts("art.doc:verification-plan", 1), old)

    def test_new_question_revokes_cap_until_rechecked(self):
        self.prepare()
        self.finish()
        self.store.ask_agent_question(self.delivery["id"], "复位条件是否需要重新确认？", [
            {"id": "yes", "label": "确认", "description": "当前条件正确"},
            {"id": "no", "label": "修改", "description": "需要修改条件"},
        ], "yes", "验收后发现待确认条件")
        self.assertNotEqual(self.head("cap.doc:verification-plan")["status"], "VALID")
        self.assertEqual(self.store.document_delivery_review_state(self.delivery["id"])["status"], "WAITING_FOR_HUMAN")

    def test_revision_restart_does_not_inherit_results(self):
        self.prepare()
        self.finish()
        old = self.store.document_artifacts("art.doc:verification-plan", 1)
        self.fixture.design_minimal_vdoc()
        self.assertNotEqual(self.head("art.doc_plan:verification-plan")["status"], "VALID")
        self.assertNotEqual(self.head("cap.doc:verification-plan")["status"], "VALID")
        self.assertEqual(self.store.document_artifacts("art.doc:verification-plan", 1), old)


if __name__ == "__main__":
    unittest.main()
