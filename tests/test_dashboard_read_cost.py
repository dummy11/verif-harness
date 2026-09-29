"""Bound database reads without caching approval decisions across requests."""

import json
import sqlite3
import threading
import unittest
import urllib.error
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
        connections = []
        def traced_factory(original):
            def connect():
                connection = original()
                connection.set_trace_callback(statements.append)
                connections.append(connection)
                return connection
            return connect

        try:
            with mock.patch.object(self.fixture.store, "read_connect", side_effect=traced_factory(self.fixture.store.read_connect)), \
                 mock.patch.object(self.fixture.store, "connect", side_effect=traced_factory(self.fixture.store.connect)):
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

    def test_manifest_entries_do_not_add_queries_or_work_nodes(self) -> None:
        store = self.fixture.store
        store.dashboard_snapshot()
        _, small_queries = self.traced(store.dashboard_snapshot)
        plan = store.workstream("VDOC")
        delivery = next(n for n in plan["desired_state"] if n["role"] == "document-deliverable")
        prototype = delivery["internal_semantic_units"][0]
        copies = [
            {**prototype, "id": f"cost-entry-{i}", "content": "x" * 4096}
            for i in range(1000)
        ]
        delivery["internal_semantic_units"].extend(copies)
        with store.connect() as connection:
            connection.execute("UPDATE workstreams SET desired_json=? WHERE name='VDOC'",
                               (json.dumps(plan["desired_state"]),))
        store.dashboard_snapshot()
        snapshot, large_queries = self.traced(store.dashboard_snapshot)
        self.assertEqual(len(large_queries), len(small_queries))
        vdoc = next(w for w in snapshot["workstreams"] if w["workstream"] == "VDOC")
        self.assertEqual(len([n for n in vdoc["nodes"] if n["role"] != "document-catalog"]), 2)
        node = next(n for n in vdoc["nodes"] if n["id"] == delivery["id"])
        self.assertFalse(node["delivery_review"]["internal_work"]["ready"])
        self.assertGreater(node["delivery_review"]["internal_work"]["total"], 1000)
        self.assertNotIn("cost-entry-", json.dumps(snapshot))
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

    def test_operation_reuses_payload_but_observes_external_and_same_revision_writes(self) -> None:
        store = self.fixture.store
        other = fixtures.ProjectStore(store.root)
        def exercise():
            with store.operation():
                before = store.workstream("VDOC")
                # Callers cannot mutate the cached definition through returned lists.
                before["desired_state"][0]["title"] = "caller-local"
                self.assertNotEqual(store.workstream("VDOC")["desired_state"][0]["title"], "caller-local")
                with other.connect() as connection:
                    connection.execute("UPDATE workstreams SET lifecycle='PARTIALLY_STALE' WHERE name='VDOC'")
                self.assertEqual(store.workstream("VDOC")["lifecycle"], "PARTIALLY_STALE")
                changed = store.workstream("VDOC")["desired_state"]
                changed[0]["title"] = "数据库中的新标题"
                with other.connect() as connection:
                    connection.execute("UPDATE workstreams SET desired_json=? WHERE name='VDOC'", (json.dumps(changed),))
                self.assertEqual(store.workstream("VDOC")["desired_state"][0]["title"], "数据库中的新标题")
        _, statements = self.traced(exercise)
        payload_reads = [s for s in statements if s.startswith("SELECT desired_json,")]
        self.assertEqual(len(payload_reads), 2)
        self.assertIsNone(store._operation_state.get())

    def test_rollback_exception_and_threads_do_not_leak_cached_definitions(self) -> None:
        store = self.fixture.store
        before = store.workstream("VDOC")
        with store.operation():
            store.workstream("VDOC")
            with self.assertRaisesRegex(RuntimeError, "rollback"):
                with store.connect() as connection:
                    connection.execute("UPDATE workstreams SET desired_json='[]' WHERE name='VDOC'")
                    self.assertEqual(store._read_workstream(connection, "VDOC")["desired_state"], [])
                    raise RuntimeError("rollback")
            self.assertEqual(store.workstream("VDOC"), before)
            observed = []
            thread = threading.Thread(target=lambda: observed.append(store._operation_state.get()))
            thread.start(); thread.join(timeout=2)
            self.assertEqual(observed, [None])
        with self.assertRaises(RuntimeError):
            with store.operation():
                raise RuntimeError("discard")
        self.assertIsNone(store._operation_state.get())

    def test_approval_reuses_plan_and_exports_once(self) -> None:
        store = self.fixture.store
        plan = store.workstream("VDOC")
        node = next(n for n in plan["desired_state"] if n["role"] == "document-deliverable")
        state = store.document_delivery_review_state(node["id"])
        with mock.patch.object(store, "_write_model_projection", wraps=store._write_model_projection) as model, \
             mock.patch.object(store, "_write_workstream_projection", wraps=store._write_workstream_projection) as projection:
            receipt, statements = self.traced(lambda: store.review_document_delivery(
                node["id"], state["definition_digest"], state["document_digest"],
                "approve", "fixture-owner", "",
            ))
        reads = [s for s in statements if s.startswith("SELECT desired_json,") and "'VDOC'" in s]
        self.assertEqual(len(reads), 1)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(projection.call_count, 1)
        self.assertEqual(receipt["delivery_review"]["status"], "AGENT_CHECKING")

    def test_unchanged_sync_and_closure_do_not_rewrite_database(self) -> None:
        store = self.fixture.store
        store.evaluate_closure("VDOC")
        token = store.dashboard_change_token()
        store.sync_documents([self.document["id"]])
        self.assertEqual(store.dashboard_change_token(), token)
        with store.operation(), mock.patch.object(store, "_evaluate_closure", wraps=store._evaluate_closure) as evaluate:
            first = store.evaluate_closure("VDOC")
            self.assertEqual(store.evaluate_closure("VDOC"), first)
            self.assertEqual(evaluate.call_count, 1)
        self.assertEqual(store.dashboard_change_token(), token)
        target = self.path.with_suffix(".copy")
        target.write_bytes(self.path.read_bytes())
        self.path.unlink(); self.path.symlink_to(target)
        with self.assertRaisesRegex(fixtures.HarnessError, "符号链接"):
            store.sync_documents([self.document["id"]])

    def test_approval_status_is_authorized_current_and_independent_of_snapshot(self) -> None:
        f = self.fixture
        node = next(n for n in f.store.workstream("VDOC")["desired_state"] if n["role"] == "document-writing-plan")
        endpoint = "/api/approval-status?node=" + node["id"]
        with mock.patch.object(fixtures.ProjectStore, "dashboard_snapshot", side_effect=AssertionError("full snapshot")), \
             mock.patch.object(fixtures.ProjectStore, "evaluate_closure", side_effect=AssertionError("closure")):
            with f.get(endpoint) as response:
                result = json.load(response)["result"]
            self.assertEqual(result["current_review"]["verdict"], "APPROVE")
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f.url + endpoint.lstrip("/"), timeout=3)
        self.assertEqual(error.exception.code, 403)
        for suffix in ("&project=missing", "-missing"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                f.get(endpoint + suffix)
            self.assertEqual(error.exception.code, 400)
        with f.store.connect() as connection:
            connection.execute("UPDATE workstreams SET revision=revision+1 WHERE name='VDOC'")
        with f.get(endpoint) as response:
            self.assertIsNone(json.load(response)["result"]["current_review"])

    def test_connection_context_closes_and_legacy_header_migration_preserves_plan(self) -> None:
        store = self.fixture.store
        before = store.workstream("VDOC")
        with store.read_connect() as connection:
            connection.execute("SELECT 1")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        with store.connect() as connection:
            for trigger in ("workstream_header_insert", "workstream_header_update",
                            "workstream_definition_update", "workstream_header_delete"):
                connection.execute("DROP TRIGGER " + trigger)
            connection.execute("DROP TABLE workstream_read_headers")
        reopened = fixtures.ProjectStore(store.root)
        with reopened.read_connect() as connection:
            self.assertTrue(reopened._current_desired_nodes(connection))
        self.assertEqual(reopened.workstream("VDOC"), before)

    def test_snapshot_does_not_cache_state_that_changed_during_read(self) -> None:
        f = self.fixture
        original = fixtures.ProjectStore.dashboard_snapshot
        calls = []
        def changing(store):
            result = original(store)
            calls.append(True)
            if len(calls) == 1:
                with store.connect() as connection:
                    connection.execute("UPDATE workstreams SET objective='updated fixture objective' WHERE name='VCHK'")
            return result
        f.server._snapshot_cache.clear()
        with mock.patch.object(fixtures.ProjectStore, "dashboard_snapshot", autospec=True, side_effect=changing):
            with f.get("/api/snapshot") as response:
                result = json.load(response)
        self.assertEqual(len(calls), 2)
        self.assertEqual(next(w for w in result["workstreams"] if w["workstream"] == "VCHK")["objective"],
                         "updated fixture objective")


if __name__ == "__main__":
    unittest.main()
