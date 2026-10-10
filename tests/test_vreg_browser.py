"""Real Dashboard rerun clicks against isolated synthetic VREG evidence."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from tests import test_vreg_workflow as vreg_fixtures
from verif_harness.dashboard import dashboard_project_id


class VregBrowserTest(unittest.TestCase):
    def setUp(self):
        self.node_executable = shutil.which("node")
        if not self.node_executable:
            self.skipTest("Node.js is required for the real VREG browser test")
        probe = subprocess.run(
            [self.node_executable, "-e", "require('playwright')"],
            capture_output=True, timeout=15, env=os.environ.copy(),
        )
        if probe.returncode:
            self.skipTest("Playwright is required for the real VREG browser test")
        # Composition keeps imported VREG test methods out of this module's
        # unittest discovery while reusing its owned temporary HTTP fixture.
        self.scenario = vreg_fixtures.VregWorkflowTest()
        self.scenario.setUp()
        self.addCleanup(self.scenario.tearDown)

    def test_browser_infrastructure_only_has_no_overall_percentage(self):
        scenario = self.scenario
        scenario.design([scenario.items[0]])
        scenario.finish_infrastructure()
        process = subprocess.run(
            [self.node_executable, str(Path(__file__).with_name("dashboard_code_workflow.cjs"))],
            input=json.dumps({
                "url": scenario.http.url, "project": dashboard_project_id(scenario.root),
                "token": scenario.http.server.write_token, "workstream": "VREG",
                "phase": "regression-progress",
            }),
            text=True, capture_output=True, timeout=90, env=os.environ.copy(),
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("incomplete scope has no overall percentage", process.stdout)
        self.assertIsNone(scenario.view()["progress"]["percentage"])

    def test_browser_rerun_preserves_approved_plan_and_revokes_old_acceptance(self):
        scenario = self.scenario
        delivery = scenario.finish_all()
        results_plan = scenario.node("regression-results-plan")
        infrastructure = scenario.node("regression-infrastructure-deliverable")
        revision = scenario.store.workstream("VREG")["revision"]
        before = scenario.cli("code", "status", delivery["id"])
        old_round = copy.deepcopy(before["regression_execution"]["current"])
        approved_plan = copy.deepcopy(scenario.head("art.code_plan:vreg:dut:results")["data"]["current"])
        executor = copy.deepcopy(scenario.head("cap.vreg:executor-ready")["data"]["current"])
        config = copy.deepcopy(delivery["regression_config"])
        self.assertTrue(before["completed"])
        self.assertTrue(before["validation"]["current"])
        self.assertEqual(old_round["status"], "ACCEPTED")
        self.assertTrue(before["regression_execution"]["can_rerun"])
        # Archive JSON uses canonical path order; the browser opens the first
        # available historical file in that projection, which need not be JSON.
        history_file = next(item for item in sorted(old_round["files"], key=lambda item: item["path"])
                            if item["available"])
        history_path = scenario.root / history_file["path"]
        self.assertEqual(scenario.store._digest(history_path), history_file["sha256"])
        history_lines = [line.strip() for line in history_path.read_text(encoding="utf-8").splitlines()
                         if len(line.strip()) >= 12]
        self.assertTrue(history_lines, "历史文件必须包含可辨识的 fixture 原文，不能用 JSON 标点代替内容断言")
        history_preview_text = max(history_lines, key=len)

        http = scenario.http
        project = dashboard_project_id(scenario.root)
        process = subprocess.run(
            [self.node_executable, str(Path(__file__).with_name("dashboard_code_workflow.cjs"))],
            input=json.dumps({
                "url": http.url, "project": project, "token": http.server.write_token,
                "workstream": "VREG", "phase": "regression-rerun", "node": delivery["id"],
                "expectedRole": "回归结果交付", "expectedRegressionConfig": config,
                "historyPreviewText": history_preview_text,
            }),
            text=True, capture_output=True, timeout=90, env=os.environ.copy(),
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("VREG rerun confirmation", process.stdout)

        # A successful browser request creates execution intent, not evidence,
        # acceptance, a new plan revision, or an actual simulator-run claim.
        current = scenario.cli("code", "status", delivery["id"])
        execution = current["regression_execution"]
        new_round = execution["current"]
        self.assertEqual(new_round["round_number"], old_round["round_number"] + 1)
        self.assertNotEqual(new_round["round_id"], old_round["round_id"])
        self.assertEqual(new_round["status"], "REQUESTED")
        self.assertEqual(new_round["requested_by"], "browser-owner")
        self.assertEqual(new_round["execution_binding"]["plan_digest"], old_round["execution_binding"]["plan_digest"])
        self.assertFalse(new_round["execution_confirmed"])
        self.assertFalse(execution["can_rerun"])
        self.assertFalse(current["completed"])
        self.assertFalse(current["can_approve"])
        self.assertFalse(current["validation"]["current"])
        self.assertEqual(current["completion_reviews"], before["completion_reviews"])
        self.assertEqual(current["regression_config"], config)

        self.assertEqual(scenario.store.workstream("VREG")["revision"], revision)
        self.assertTrue(scenario.store.node_plan_review_state(results_plan["id"])["completed"])
        self.assertTrue(scenario.store.node_plan_review_state(infrastructure["id"])["completed"])
        self.assertEqual(scenario.head("art.code_plan:vreg:dut:results")["data"]["current"], approved_plan)
        self.assertEqual(scenario.head("cap.vreg:executor-ready")["data"]["current"], executor)
        self.assertEqual(scenario.head("cap.vreg:executor-ready")["status"], "VALID")
        self.assertNotEqual(scenario.head("cap.vreg:fresh-evidence")["status"], "VALID")
        self.assertFalse(scenario.cli("closure", "--workstream", "VREG")["ready"])

        historic = next(item for item in execution["history"] if item["round_id"] == old_round["round_id"])
        self.assertEqual(historic["status"], "ACCEPTED")
        self.assertEqual(historic["accepted_at"], old_round["accepted_at"])
        self.assertTrue(any(item["available"] for item in historic["files"]))
        self.assertEqual(next(item for item in historic["files"] if item["available"])["path"], history_file["path"])
        view = scenario.view()
        projected = next(item for item in view["nodes"] if item["id"] == delivery["id"])
        self.assertEqual(projected["plan_review"]["regression_execution"], execution)
        self.assertFalse(projected["plan_review"]["completed"])
        self.assertEqual(view["revision"], revision)
        self.assertEqual(view["progress"]["percentage"], 75)


if __name__ == "__main__":
    unittest.main()
