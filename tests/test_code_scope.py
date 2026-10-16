"""Unchanged-package recovery reuses verified approvals without creating any."""

import copy
import json
import unittest
import uuid

from tests import test_code_workflow as fixtures
from verif_harness import code_scope, code_workflow as code
from verif_harness.store import HarnessError, now


class CodeScopeRepairTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CodeWorkflowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.store = self.fixture.store
        self.fixture.implement()
        self.validate("original.json")
        self.fixture.approve(self.fixture.delivery)
        self.original_plan = self.fixture.plan_node
        self.original_delivery = self.fixture.delivery
        self.original_review = self.store.node_plan_review_state(self.original_delivery["id"])["current_completion"]

        # Reproduce historical all-package replacement even though scope is
        # identical. Current design() must no longer create this state.
        plan = self.store.workstream("VENV")
        desired = copy.deepcopy(plan["desired_state"])
        for node in desired:
            node["id"] = node["id"].replace(":r1:", ":r2:")
            if node.get("parent_id"):
                node["parent_id"] = node["parent_id"].replace(":r1:", ":r2:")
        with self.store.connect() as db:
            db.execute("UPDATE nodes SET workstream=NULL,status='STALE' WHERE workstream='VENV' AND type='desired-state'")
            db.execute("UPDATE workstreams SET revision=2,desired_json=? WHERE name='VENV'", (code.encoded(desired),))
            for node in desired:
                from verif_harness.store import Validity
                self.store.upsert_node(db, node["id"], "desired-state", node["title"], Validity.UNKNOWN, "VENV", node)
                if code.is_plan(node):
                    for target in node["inputs"]:
                        code.edge(db, node["id"], target, now())
                else:
                    code.edge(db, node["id"], code.ids(node["implementation_key"])[0], now())
                    code.edge(db, node["id"], node["parent_id"], now(), "CHILD_OF")
            db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", (
                "event:" + uuid.uuid4().hex, "venv-replan", "workstream:VENV", "2",
                code.encoded({"previous_nodes": plan["desired_state"], "restart": None}), now(),
            ))
        self.fixture.plan_node = next(n for n in desired if code.is_plan(n))
        self.fixture.delivery = next(n for n in desired if code.is_delivery(n))
        self.fixture.approve(self.fixture.plan_node)
        self.validate("replacement.json")

    def validate(self, name):
        self.fixture.validate(register=False)
        path = self.store.root / name
        path.write_text(self.fixture.report_path.read_text())
        return code.validate(self.store, self.fixture.delivery["id"], name)

    def restore(self, apply=False):
        state = self.store.node_plan_review_state(self.fixture.plan_node["id"])
        return code_scope.restore_package(self.store, self.fixture.plan_node["id"],
                                          self.original_plan["id"], state["definition_digest"], apply=apply)

    def test_dry_run_and_repair_preserve_original_review_and_audit_history(self):
        with self.store.read_connect() as db:
            reviews_before = db.execute("SELECT COUNT(*) FROM node_plan_reviews").fetchone()[0]
            validations_before = db.execute("SELECT COUNT(*) FROM code_validations").fetchone()[0]
        self.assertEqual(self.restore()["status"], "VERIFIED")
        self.assertIn(self.fixture.delivery, self.store.workstream("VENV")["desired_state"])
        self.assertEqual(self.restore(apply=True)["status"], "RESTORED")
        state = self.store.node_plan_review_state(self.original_delivery["id"])
        self.assertTrue(state["completed"])
        self.assertEqual(state["current_completion"], self.original_review)
        self.assertEqual(self.store.workstream("VENV")["revision"], 2)
        self.assertTrue(self.store.evaluate_closure("VENV")["ready"])
        with self.store.read_connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM node_plan_reviews").fetchone()[0], reviews_before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM code_validations").fetchone()[0], validations_before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='code-scope-repair'").fetchone()[0], 1)
            self.assertIsNotNone(db.execute("SELECT id FROM nodes WHERE id=?", (self.fixture.delivery["id"],)).fetchone())

    def test_changed_native_evidence_cannot_recover_an_old_approval(self):
        self.fixture.output.write_text("module changed; endmodule\n")
        self.validate("changed.json")
        with self.assertRaisesRegex(HarnessError, "原交付批准或原始证据已失效"):
            self.restore(apply=True)
        self.assertIn(self.fixture.delivery, self.store.workstream("VENV")["desired_state"])

    def test_current_owner_acceptance_is_not_replaced(self):
        self.fixture.approve(self.fixture.delivery)
        self.assertEqual(self.restore(apply=True)["status"], "ALREADY_ACCEPTED")
        self.assertIn(self.fixture.delivery, self.store.workstream("VENV")["desired_state"])

    def test_restart_and_stale_digest_cannot_restore(self):
        with self.assertRaisesRegex(HarnessError, "当前方案版本已变化"):
            code_scope.restore_package(self.store, self.fixture.plan_node["id"],
                                       self.original_plan["id"], "stale", apply=True)
        with self.store.connect() as db:
            db.execute("UPDATE events SET payload_json=? WHERE kind='venv-replan' AND revision='2'",
                       (json.dumps({"restart": {"reason": "owner restart"}}),))
        with self.assertRaisesRegex(HarnessError, "显式重启"):
            self.restore(apply=True)


if __name__ == "__main__":
    unittest.main()
