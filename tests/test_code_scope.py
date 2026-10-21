"""Unchanged-package recovery reuses verified approvals without creating any."""

import copy
import json
import unittest
import uuid

from tests import test_code_workflow as fixtures
from tests import test_vreg_workflow as regression_fixtures
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


class RegressionInfrastructureRepairTest(unittest.TestCase):
    def setUp(self):
        self.fixture = regression_fixtures.VregWorkflowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.store = self.fixture.store
        self.original_delivery = self.fixture.finish_infrastructure()
        self.original_plan = self.fixture.node("regression-infrastructure-plan")
        self.original_review = self.store.node_plan_review_state(self.original_delivery["id"])["current_completion"]
        changed = copy.deepcopy(self.fixture.items)
        changed[1]["regression_config"]["repeat"] = 2
        plan = self.fixture.design(changed)
        # Reproduce the pre-fix whole-VREG replacement. Results retain their new
        # r2 scope; only the unchanged infrastructure was needlessly replaced.
        replacement = {**self.original_plan, "id": self.original_plan["id"].replace(":r1:", ":r2:")}
        desired = [replacement if n["id"] == self.original_plan["id"] else n
                   for n in plan["desired_state"] if n["id"] != self.original_delivery["id"]]
        with self.store.connect() as db:
            from verif_harness.store import Validity
            for old in (self.original_plan, self.original_delivery):
                db.execute("UPDATE nodes SET workstream=NULL,status='STALE' WHERE id=?", (old["id"],))
            db.execute("UPDATE workstreams SET desired_json=? WHERE name='VREG'", (code.encoded(desired),))
            self.store.upsert_node(db, replacement["id"], "desired-state", replacement["title"],
                                   Validity.UNKNOWN, "VREG", replacement)
            for target in replacement["inputs"]:
                code.edge(db, replacement["id"], target, now())
        self.current_plan = replacement
        self.fixture.approve(replacement)
        self.current_delivery = self.fixture.infrastructure(approve=False)
        self.assertTrue(self.fixture.validate(self.current_delivery)["ready"])
        self.fixture.approve(self.current_delivery)

    def restore(self, apply=False):
        state = self.store.node_plan_review_state(self.current_plan["id"])
        return code_scope.restore_package(
            self.store, self.current_plan["id"], self.original_plan["id"], state["definition_digest"],
            apply=apply, replace_accepted=True,
        )

    def test_explicit_equivalent_executor_repair_preserves_all_reviews_and_results_scope(self):
        before = self.store.workstream("VREG")
        results = [node for node in before["desired_state"] if code.vreg_stage(node) == "results"]
        with self.store.read_connect() as db:
            reviews = [dict(row) for row in db.execute("SELECT * FROM node_plan_reviews ORDER BY rowid")]
        self.assertEqual(self.restore()["status"], "VERIFIED")
        self.assertIn(self.current_delivery, self.store.workstream("VREG")["desired_state"])
        self.assertEqual(self.restore(apply=True)["status"], "RESTORED")
        after = self.store.workstream("VREG")
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual([n for n in after["desired_state"] if code.vreg_stage(n) == "results"], results)
        self.assertEqual(self.store.node_plan_review_state(self.original_delivery["id"])["current_completion"],
                         self.original_review)
        with self.store.read_connect() as db:
            self.assertEqual([dict(row) for row in db.execute("SELECT * FROM node_plan_reviews ORDER BY rowid")], reviews)

    def test_changed_native_evidence_blocks_executor_repair(self):
        self.fixture.write("verification/results/infrastructure/build.log", "different execution\n")
        self.fixture.validate(self.current_delivery)
        with self.assertRaisesRegex(HarnessError, "原交付批准或原始证据已失效"):
            self.restore(apply=True)
        self.assertIn(self.current_delivery, self.store.workstream("VREG")["desired_state"])


if __name__ == "__main__":
    unittest.main()
