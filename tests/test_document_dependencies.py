"""Document edits must not invalidate unrelated approvals through legacy inputs."""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests import test_document_authoring as authoring_fixtures
from tests import test_code_workflow as code_fixtures
from verif_harness import document_authoring, document_dependencies
from verif_harness.store import ProjectStore, now


class DocumentDependenciesTest(unittest.TestCase):
    def setUp(self):
        self.fixture = authoring_fixtures.VerificationDocumentAuthoringTest()
        self.fixture.setUp()
        self.store, self.root = self.fixture.store, self.fixture.root
        self.fixture.register_authoring_plan()
        self.store.review_workstream("VDOC", "approve", "fixture-owner", "准备合成文档")
        for doc in self.store.documents(include_delivery_nodes=False):
            (self.root / doc["path"]).write_text("# 合成验证文档\n\n## DUT 范围\n检查握手。\n")
        self.store.sync_documents()

    def tearDown(self):
        self.fixture.tearDown()

    def prepare_legacy(self):
        original = document_authoring._source_matches
        with mock.patch.object(document_authoring, "_source_matches", side_effect=lambda kind, source:
                               (kind == "verification-artifact" and source["kind"] == "verification-document")
                               or original(kind, source)):
            proposal = self.store.build_vdoc_authoring_proposal()
        documents = {source["document_key"]: source for node in proposal["nodes"]
                     for source in node["authoring_contract"]["source_snapshot"]
                     if source["kind"] == "verification-document"}
        for node in proposal["nodes"]:
            node["authoring_contract"]["source_snapshot"].append(documents[node["document_key"]])
        path = self.root / "legacy-plan.json"
        path.write_text(json.dumps(proposal))
        with mock.patch("verif_harness.store.authoring_source_is_dependency", return_value=True):
            self.store.design_workstream("VDOC", None, [], [], [], desired_file=path.name)
            self.store.review_workstream("VDOC", "approve", "fixture-owner", "批准合成方案")
            delivery = self.fixture.delivery_proposal(proposal)
            path = self.root / "legacy-delivery.json"
            path.write_text(json.dumps(delivery))
            self.store.design_workstream("VDOC", None, [], [], [], desired_file=path.name)
        for item in self.store.workstream("VDOC")["desired_state"]:
            if item.get("role") != "document-deliverable":
                continue
            state = self.store.document_delivery_review_state(item["id"])
            review = self.store.review_document_delivery(
                item["id"], state["definition_digest"], state["document_digest"],
                "approve", "fixture-owner", "已检查合成正文",
            )
            self.store.complete_review_agent_check(review["review_id"], "Project Main Agent", "已检查全部清单")
        self.original_plan = self.store.workstream("VDOC")
        self.original_versions = self.store.document_artifacts()["versions"]
        self.assertTrue(self.store.evaluate_closure("VDOC")["ready"])

    def edit(self, key="testcase-list", legacy=False):
        doc = self.store.documents("document:vdoc:" + key, include_delivery_nodes=False)[0]
        (self.root / doc["path"]).write_text("# 合成验证文档\n\n增加当前用例的运行入口。\n")
        if legacy:
            def old_graph(connection):
                return document_dependencies._graph([dict(row) for row in connection.execute("SELECT * FROM edges")])
            with mock.patch.object(ProjectStore, "_impact_graph", side_effect=old_graph):
                self.store.sync_documents([doc["id"]])
        else:
            self.store.sync_documents([doc["id"]])
        return doc

    def table_history(self):
        with self.store.read_connect() as con:
            return {table: [tuple(row) for row in con.execute("SELECT * FROM " + table)] for table in (
                "node_plan_reviews", "node_plan_section_reviews", "document_delivery_reviews",
                "review_agent_checks", "vdoc_manifest_checks", "vdoc_artifact_versions",
            )}

    def test_new_generation_only_names_upstream_documents(self):
        proposal = self.store.build_vdoc_authoring_proposal()
        for node in proposal["nodes"]:
            contract = node["authoring_contract"]
            documents = {s["document_key"] for s in contract["source_snapshot"]
                         if s["kind"] == "verification-document"}
            self.assertEqual(documents, set(contract["document_dependencies"]))
            self.assertNotIn(node["document_key"], documents)

    def test_existing_edges_no_longer_propagate_self_or_unrelated_body_edits(self):
        self.prepare_legacy()
        self.edit()
        snap = self.store.dashboard_snapshot()
        view = next(w for w in snap["workstreams"] if w["workstream"] == "VDOC")
        self.assertEqual(view["progress"]["satisfied"], 15)
        self.assertEqual(self.store.document_artifacts()["versions"], self.original_versions)
        self.assertEqual(self.store.workstream("VDOC")["desired_state"], self.original_plan["desired_state"])

    def test_repair_preserves_approvals_and_cli_dashboard_agree(self):
        self.prepare_legacy()
        code = code_fixtures.CodeWorkflowProfileTest()
        code.store, code.root = self.store, self.root
        plan, _ = code.design("VENV", ["build-ready"], ["cap.doc:verification-plan"])
        node = plan["desired_state"][0]
        state = self.store.node_plan_review_state(node["id"])
        self.store.complete_node_plan_review(node["id"], state["definition_digest"], "fixture-owner")
        self.edit(legacy=True)
        history = self.table_history()
        with self.store.read_connect() as con:
            before = list(con.iterdump())
        preview = self.store.repair_document_dependencies()
        self.assertEqual(len(preview["restored_nodes"]), 15)
        with self.store.read_connect() as con:
            self.assertEqual(list(con.iterdump()), before)
        result = subprocess.run(
            [sys.executable, "scripts/verif_harness.py", "docs", "repair-dependencies", "--project", str(self.root), "--apply"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["applied"])
        fresh = ProjectStore(self.root)
        self.assertTrue(fresh.node_plan_review_state(node["id"])["completed"])
        snapshot = fresh.dashboard_snapshot()
        view = next(w for w in snapshot["workstreams"] if w["workstream"] == "VDOC")
        self.assertEqual(view["progress"]["satisfied"], 15)
        self.assertEqual(view["closure"], fresh.evaluate_closure("VDOC", persist=False))
        self.assertEqual(self.table_history(), history)
        self.assertEqual(fresh.workstream("VDOC")["desired_state"], self.original_plan["desired_state"])
        again = fresh.repair_document_dependencies(apply=True)
        self.assertFalse(again["changed"])

    def test_real_upstream_document_change_still_invalidates_consumers(self):
        self.prepare_legacy()
        self.edit("verification-plan")
        with self.store.read_connect() as con:
            changed = {row[0] for row in con.execute("SELECT subject FROM findings WHERE status='OPEN'")}
        plans = [n for n in self.original_plan["desired_state"] if n.get("role") == "document-writing-plan"]
        self.assertNotIn(next(n["id"] for n in plans if n["document_key"] == "verification-plan"), changed)
        self.assertIn(next(n["id"] for n in plans if n["document_key"] == "feature-matrix"), changed)

    def test_repair_keeps_other_findings_questions_changed_sources_and_missing_checks(self):
        self.prepare_legacy()
        self.edit(legacy=True)
        nodes = {n.get("key"): n for n in self.original_plan["desired_state"]}
        blocked = nodes["verification_workflow_authoring"]["id"]
        self.store.ask_agent_question(blocked, "需要确认范围", [
            {"id": "yes", "label": "确认"}, {"id": "revise", "label": "修改"},
        ])
        delivery = nodes["testcase_list_delivery"]["id"]
        with self.store.connect() as con:
            con.execute("INSERT INTO findings VALUES(?,?,?,?,?,?,?)",
                        ("finding:independent", blocked, "MEDIUM", "OPEN", None, "独立工程问题", now()))
            con.execute("UPDATE review_agent_checks SET status='PENDING' WHERE node_id=?", (delivery,))
        (self.root / "rtl/dut.sv").write_text("module changed_dut; endmodule\n")
        result = self.store.repair_document_dependencies(apply=True)
        self.assertFalse(result["restored_nodes"])
        with self.store.read_connect() as con:
            self.assertEqual(con.execute("SELECT status FROM findings WHERE id='finding:independent'").fetchone()[0], "OPEN")
            self.assertEqual(con.execute("SELECT status FROM review_agent_checks WHERE node_id=?", (delivery,)).fetchone()[0], "PENDING")
        self.assertTrue(any("实际输入已变化" in reason for reason in result["blocked_nodes"].values()))

    def test_missing_agent_check_does_not_restore_unchanged_body(self):
        self.prepare_legacy()
        self.edit(legacy=True)
        node = next(n for n in self.original_plan["desired_state"] if n["key"] == "assertion_plan_delivery")
        with self.store.connect() as con:
            con.execute("DELETE FROM vdoc_manifest_checks WHERE node_id=?", (node["id"],))
        result = self.store.repair_document_dependencies(apply=True)
        self.assertNotIn(node["id"], result["restored_nodes"])
        self.assertIn("完整的 Agent 检查", result["blocked_nodes"][node["id"]])
        self.assertNotEqual(self.store.document_delivery_review_state(node["id"])["status"], "APPROVED")

    def test_unsynced_body_edit_and_changed_definition_cannot_reuse_old_approval(self):
        self.prepare_legacy()
        self.edit(legacy=True)
        doc = self.store.documents("document:vdoc:assertion-plan", include_delivery_nodes=False)[0]
        (self.root / doc["path"]).write_text("# 实际正文也发生了变化\n")
        plan = self.store.workstream("VDOC")
        node = next(n for n in plan["desired_state"] if n["key"] == "coverage_plan_authoring")
        node["title"] = "已改变的方案范围"
        with self.store.connect() as con:
            con.execute("UPDATE workstreams SET desired_json=? WHERE name='VDOC'", (json.dumps(plan["desired_state"]),))
            con.execute("UPDATE nodes SET data_json=? WHERE id=?", (json.dumps(node), node["id"]))
        history = self.table_history()
        result = self.store.repair_document_dependencies(apply=True)
        self.assertNotIn(node["id"], result["restored_nodes"])
        self.assertIn("当前方案", result["blocked_nodes"][node["id"]])
        delivery = next(n for n in plan["desired_state"] if n["key"] == "assertion_plan_delivery")
        self.assertNotIn(delivery["id"], result["restored_nodes"])
        self.assertIn("正文已经变化", result["blocked_nodes"][delivery["id"]])
        self.assertEqual(self.table_history(), history)

    def test_explicit_dependency_path_is_preserved(self):
        self.prepare_legacy()
        doc = self.edit(legacy=True)
        node = next(n for n in self.original_plan["desired_state"] if n["key"] == "assertion_plan_authoring")
        with self.store.connect() as con:
            con.execute("UPDATE edges SET origin='explicit-engineering-dependency' WHERE source=? AND target=?",
                        ("file:" + doc["path"], node["id"]))
        result = self.store.repair_document_dependencies(apply=True)
        self.assertNotIn(node["id"], result["restored_nodes"])
        with self.store.read_connect() as con:
            self.assertIsNotNone(con.execute("SELECT 1 FROM findings WHERE subject=? AND status='OPEN'", (node["id"],)).fetchone())


if __name__ == "__main__":
    unittest.main()
