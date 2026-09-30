"""VDOC capability-gated downstream workflow launch choices."""

import unittest

from tests import test_vdoc_artifacts as vdoc_fixture
from verif_harness import agent_service, workflow_launch
from verif_harness.store import HarnessError, ProjectStore


class WorkflowLaunchTest(unittest.TestCase):
    def setUp(self):
        self.fixture = vdoc_fixture.VdocArtifactsTest()
        self.fixture.setUp()
        self.fixture.prepare()
        self.fixture.finish()
        self.store = self.fixture.store

    def tearDown(self):
        self.fixture.tearDown()

    def choose(self, strategy):
        before = self.store.dashboard_snapshot()["workflow_launch"]
        self.assertTrue(before["available"])
        self.assertIsNone(before["decision"])
        response = self.fixture.fixture.post("/api/workflow-launch", {
            "strategy": strategy,
            "reviewer": "fixture-owner",
            "vdoc_signature": before["vdoc_signature"],
        }, self.fixture.fixture.server.write_token)
        return response["result"]

    def test_parallel_choice_is_persisted_and_starts_empty_workflow_envelopes(self):
        result = self.choose("parallel")
        self.assertEqual(result["strategy"], "parallel")
        self.assertEqual(set(result["allowed_workstreams"]), set(workflow_launch.WORKSTREAMS))
        reopened = ProjectStore(self.store.root)
        observed = workflow_launch.status(reopened)
        self.assertEqual(observed["decision"]["reviewer"], "fixture-owner")
        for name in ("VENV", "VSTIM", "VCOV", "VREG"):
            plan = reopened.workstream(name)
            self.assertEqual(plan["desired_state"], [])
            self.assertEqual(plan["planning_context"]["code_model"], 2)
        tasks = agent_service.candidates(reopened)
        self.assertTrue(any(task["workstream"] == "VCOV" for task in tasks))
        self.assertTrue(any(task["workstream"] == "VREG" for task in tasks))

    def test_dependency_order_only_dispatches_the_current_gate(self):
        result = self.choose("dependency_order")
        self.assertEqual(result["allowed_workstreams"], ["VENV"])
        tasks = agent_service.candidates(self.store)
        self.assertTrue(any(task["workstream"] == "VENV" for task in tasks))
        self.assertFalse(any(task["workstream"] in {"VSTIM", "VCHK", "VCASE", "VCOV", "VREG"}
                             for task in tasks))

    def test_choice_is_bound_to_the_current_vdoc_signature(self):
        current = self.store.dashboard_snapshot()["workflow_launch"]
        with self.assertRaisesRegex(HarnessError, "版本已经变化"):
            workflow_launch.choose(self.store, "parallel", "fixture-owner", "stale")
        workflow_launch.choose(
            self.store, "parallel", "fixture-owner", current["vdoc_signature"],
        )
        with self.assertRaisesRegex(HarnessError, "已经选择"):
            workflow_launch.choose(
                self.store, "dependency_order", "fixture-owner", current["vdoc_signature"],
            )


if __name__ == "__main__":
    unittest.main()
