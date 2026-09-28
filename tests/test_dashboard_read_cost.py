"""Bound database reads without caching approval decisions across requests."""

import json
import unittest
from unittest import mock

from tests import test_dashboard as fixtures


class DashboardReadCostTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = f = fixtures.DashboardTest()
        f.setUp()
        f.design_minimal_vdoc()
        plan = next(n for w in f.store.dashboard_snapshot()["workstreams"]
                    for n in w["nodes"] if n["plan_review"])
        f.store.complete_node_plan_review(
            plan["id"], plan["plan_review"]["definition_digest"], "fixture-owner",
        )
        self.document = f.store.documents("verification_plan.md")[0]
        self.path = f.root / self.document["path"]
        self.path.write_text("# 验证计划\n\n检查当前 DUT 的接口。\n", encoding="utf-8")
        f.store.sync_documents([self.document["id"]])
        f.register_minimal_vdoc_delivery()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def traced(self, call):
        statements = []
        original = self.fixture.store.read_connect
        connections = []

        def connect():
            connection = original()
            connection.set_trace_callback(statements.append)
            connections.append(connection)
            return connection

        try:
            with mock.patch.object(self.fixture.store, "read_connect", side_effect=connect):
                result = call()
        finally:
            for connection in connections:
                connection.close()
        return result, statements

    def test_preview_does_not_load_workflow_and_still_checks_current_file(self) -> None:
        f = self.fixture
        with mock.patch.object(fixtures.ProjectStore, "workstream",
                               side_effect=AssertionError("preview loaded entire workflow")):
            with f.get("/api/document?selector=" + self.document["id"]) as response:
                body = json.load(response)
            self.assertEqual(body["content"], self.path.read_text(encoding="utf-8"))
            self.assertFalse(body["document"]["content_changed"])
            self.path.write_text("# 修改后的正文\n", encoding="utf-8")
            with f.get("/api/document?selector=" + self.document["id"]) as response:
                changed = json.load(response)
            self.assertTrue(changed["document"]["content_changed"])
            self.assertEqual(changed["content"], "# 修改后的正文\n")

    def test_snapshot_reads_each_workflow_once_and_checks_each_delivery_once(self) -> None:
        store = self.fixture.store
        with mock.patch.object(store, "workstream", wraps=store.workstream) as plans, \
             mock.patch.object(store, "document_delivery_review_state",
                               wraps=store.document_delivery_review_state) as reviews:
            snapshot = store.dashboard_snapshot()
        self.assertEqual([call.args[0] for call in plans.call_args_list], ["VCHK", "VDOC"])
        self.assertEqual(reviews.call_count, 1)
        for workstream in snapshot["workstreams"]:
            self.assertEqual(workstream["closure"], store.evaluate_closure(
                workstream["workstream"], persist=False,
            ))
            for node in workstream["nodes"]:
                self.assertEqual(node["closure_assessment"]["digest"],
                                 store.node_closure_assessment(node["id"])["digest"])

    def test_hidden_units_do_not_add_per_node_queries_or_escape_closure(self) -> None:
        store = self.fixture.store
        _, small_queries = self.traced(store.dashboard_snapshot)
        plan = store.workstream("VDOC")
        prototype = next(n for n in plan["desired_state"] if n["role"] == "document-semantic-unit")
        copies = [
            {**prototype, "key": f"cost-unit-{i}", "id": f"cost--semantic--unit-{i}",
             "fixture_provenance": "x" * 4096}
            for i in range(1000)
        ]
        plan["desired_state"].extend(copies)
        with store.connect() as connection:
            connection.execute("UPDATE workstreams SET desired_json=? WHERE name='VDOC'",
                               (json.dumps(plan["desired_state"]),))
            connection.executemany(
                "INSERT INTO nodes(id,type,title,workstream,status,data_json,created_at,updated_at) "
                "VALUES(?,'desired-state',?,'VDOC',?,?,?,?)",
                [(n["id"], n["title"], "UNKNOWN" if i == 0 else "VALID",
                  json.dumps(n), plan["updated_at"], plan["updated_at"])
                 for i, n in enumerate(copies)],
            )
            connection.execute(
                "INSERT INTO edges(source,target,relation,origin,confidence,data_json,created_at) "
                "VALUES('cost--semantic--unit-1','cost--semantic--unit-0',"
                "'DEPENDS_ON','fixture',1.0,'{}',?)", (plan["updated_at"],),
            )
        snapshot, large_queries = self.traced(store.dashboard_snapshot)
        self.assertEqual(len(large_queries), len(small_queries))
        vdoc = next(w for w in snapshot["workstreams"] if w["workstream"] == "VDOC")
        actions = {a["target"]: a for a in vdoc["closure"]["actions"]}
        self.assertEqual(actions["cost--semantic--unit-0"]["kind"], "SATISFY_DESIRED_STATE")
        self.assertEqual(actions["cost--semantic--unit-1"]["kind"], "WAIT_FOR_DEPENDENCY")
        self.assertEqual(actions["cost--semantic--unit-1"]["blocked_by"], ["cost--semantic--unit-0"])
        self.assertFalse(any(n["id"].startswith("cost--semantic--") for n in vdoc["nodes"]))
        self.assertEqual(vdoc["closure"], store.evaluate_closure("VDOC", persist=False))

    def test_new_request_does_not_reuse_old_body_or_revision(self) -> None:
        store = self.fixture.store
        before = store.dashboard_snapshot()
        old = next(n for w in before["workstreams"] for n in w["nodes"] if n["delivery_review"])
        self.assertTrue(old["delivery_review"]["document_available"])
        self.path.write_text("# 修改后的正文\n", encoding="utf-8")
        after = store.dashboard_snapshot()
        node = next(n for w in after["workstreams"] for n in w["nodes"] if n["id"] == old["id"])
        self.assertFalse(node["delivery_review"]["document_available"])
        self.assertFalse(any(a["kind"] == "HUMAN_REVIEW" for a in node["next_actions"]))
        with store.connect() as connection:
            connection.execute("UPDATE workstreams SET revision=revision+1 WHERE name='VDOC'")
        refreshed = store.dashboard_snapshot()
        node = next(n for w in refreshed["workstreams"] for n in w["nodes"] if n["id"] == old["id"])
        self.assertEqual(node["delivery_review"]["revision"], old["delivery_review"]["revision"] + 1)
        self.assertNotEqual(node["delivery_review"]["definition_digest"],
                            old["delivery_review"]["definition_digest"])


if __name__ == "__main__":
    unittest.main()
