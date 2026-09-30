"""VREG four-node governance using isolated synthetic adapter evidence."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tests import test_vdoc_artifacts as fixtures
from verif_harness import agent_service as service, code_workflow as code, workflow_launch
from verif_harness.store import HarnessError, ProjectStore, Validity, now


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_RECEIPT = {
    "adapter_schema_version": 1, "state": "PASS", "blockers": [],
    "request_sha256": "a" * 64, "operation": "synthetic-regression-analysis",
    "tool_identity": {"state": "PASS"}, "tool": "synthetic-contract-fixture/1",
}


class VregWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.VdocArtifactsTest()
        self.fixture.setUp()
        self.fixture.prepare()
        self.fixture.finish()
        self.store = self.fixture.store
        self.root = self.store.root
        self.http = self.fixture.fixture
        self.write("regression-plan.md", "# 回归计划\n\n定向用例 demo_test，显式 seed 和同 seed 重跑。\n")
        # The Dashboard fixture includes historical VCHK nodes. Its explicit
        # synthetic upstream waivers preserve the fresh-set governance contract.
        for node in self.store.workstream("VCHK")["desired_state"]:
            if node.get("role") == "closure-evidence" and node.get("required", True):
                self.store.waive_node(node["id"], "fixture-owner", "synthetic upstream fixture exception")
        with self.store.connect() as connection:
            for identifier in (
                "cap.venv:environment-smoke-evidence", "cap.vstim:reachability-evidence",
                "cap.vchk:scoreboard-evidence", "cap.vcase:targeted-evidence",
                "cap.vcov:hole-analysis-evidence",
            ):
                self.store.upsert_node(connection, identifier, "capability", identifier, Validity.VALID,
                                       data={"derived": True, "current": {"fixture": identifier}})
        common = {
            "statement": "执行并核对当前 DUT 的定向回归范围", "scope": ["定向回归和同 seed 重跑"],
            "work_content": ["按批准回归范围完成当前验证工作"],
            "implementation_approach": ["保持 DUT 只读，使用可复现的运行与结果检查入口"],
            "validation_methods": ["核对当前回归报告和运行版本"],
            "deliverables": ["当前交付文件与逐项验证报告"],
            "acceptance_criteria": ["当前执行范围完整且回归证据有效"],
            "source_refs": ["regression-plan.md"], "input_files": ["regression-plan.md"],
        }
        self.items = [
            {**copy.deepcopy(common), "key": "dut-infrastructure", "implementation_key": "dut:infrastructure",
             "role": "regression-infrastructure-plan", "title": "DUT 回归基础设施方案",
             "inputs": ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence"],
             "output_paths": ["verification/regression/policy.json", "verification/regression/tests.json",
                              "verification/regression/runner.sh", "verification/regression/collector.json"],
             "capabilities": ["regression-policy", "executor-ready"]},
            {**copy.deepcopy(common), "key": "dut-results", "implementation_key": "dut:results",
             "role": "regression-results-plan", "title": "DUT 回归结果方案",
             "inputs": ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence",
                        "cap.vstim:reachability-evidence", "cap.vchk:scoreboard-evidence",
                        "cap.vcase:targeted-evidence", "cap.vcov:hole-analysis-evidence",
                        "cap.vreg:dut:infrastructure"],
             "output_paths": ["verification/results/regression/run.log", "verification/results/regression/analysis.json"],
             "capabilities": ["execution-evidence", "triage-evidence", "fresh-evidence"]},
        ]
        self.design()

    def tearDown(self):
        self.fixture.tearDown()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_json(self, name, payload):
        return self.write(name, json.dumps(payload, sort_keys=True, ensure_ascii=False))

    def design(self, items=None):
        proposal = self.write_json("vreg-proposal.json", {
            "schema": "DesiredStateProposal/1", "workstream": "VREG",
            "nodes": self.items if items is None else items,
        })
        return self.store.design_workstream("VREG", None, [], [], [], desired_file=proposal.name)

    def node(self, role):
        return next(node for node in self.store.workstream("VREG")["desired_state"] if node["role"] == role)

    def head(self, identifier):
        return next(node for node in code.artifacts(self.store, "VREG")["heads"] if node["id"] == identifier)

    def cli(self, *arguments):
        process = subprocess.run([sys.executable, str(ROOT / "scripts/verif_harness.py"),
                                  *arguments, "--project-root", str(self.root)], text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def view(self):
        with self.http.get("/api/snapshot") as response:
            return next(view for view in json.load(response)["workstreams"] if view["workstream"] == "VREG")

    def approve(self, node, http=False):
        state = self.store.node_plan_review_state(node["id"])
        self.assertTrue(state["can_approve"], state["blockers"])
        if http:
            return self.http.post("/api/reviews/node-plan-complete", {
                "node": node["id"], "definition_digest": state["definition_digest"], "reviewer": "http-owner",
            }, self.http.server.write_token)["result"]
        return self.store.complete_node_plan_review(node["id"], state["definition_digest"], "fixture-owner")

    def infrastructure(self, approve=True):
        if approve:
            self.approve(self.node("regression-infrastructure-plan"))
        self.write_json("verification/regression/policy.json", {"synthetic": True, "timeout": 10, "rerun": "same-seed"})
        self.write_json("verification/regression/tests.json", {"synthetic": True, "tests": ["demo_test"], "seed": 17})
        self.write("verification/regression/runner.sh", "#!/bin/sh\n# Synthetic fixture; no simulator executed.\n")
        self.write_json("verification/regression/collector.json", {"synthetic": True, "collector": "fixture"})
        self.write("verification/results/infrastructure/build.log", "synthetic runner self-test receipt\n")
        return self.node("regression-infrastructure-deliverable")

    def results(self, approve=True, plan=None):
        plan = self.node("regression-results-plan") if plan is None else plan
        if approve:
            self.approve(plan)
        self.write(plan["output_paths"][0], "synthetic fixture demo_test seed=17\n")
        self.write_json(plan["output_paths"][1], {
            **ANALYSIS_RECEIPT, "synthetic": True, "summary": "fixture run analyzed",
        })
        return next(node for node in self.store.workstream("VREG")["desired_state"]
                    if node["role"] == "regression-results-deliverable"
                    and node["implementation_key"] == plan["implementation_key"])

    def artifact(self, name, kind, analyzer="xverif"):
        return {"path": name, "sha256": self.store._digest(self.root / name),
                "kind": kind, "analyzed_by": [analyzer]}

    def validate(self, node, *, execution_verdict="PASS", failures=None, via_cli=False, snapshot_revision=None):
        stage = "infrastructure" if "executor-ready" in node["capabilities"] else "results"
        if stage == "results" and node["implementation_key"] != "dut:results":
            stage += "-" + node["implementation_key"].replace(":", "-")
        state = self.store.node_plan_review_state(node["id"])
        project = json.loads((self.store.state / "project.json").read_text())
        revision = project.get("baseline_revision") or "fixture-revision"
        checks = []
        for claim in node["capabilities"]:
            if claim == "regression-policy":
                artifacts = [self.artifact("verification/regression/policy.json", "document", "human-review"),
                             self.artifact("verification/regression/tests.json", "regression-manifest")]
                result = {"policy_digest": artifacts[0]["sha256"], "manifest_digest": artifacts[1]["sha256"],
                          "review_ref": "synthetic-policy-review", "seed_policy": "explicit seed",
                          "timeout_policy": "per-case timeout", "rerun_policy": "same-seed rerun"}
            elif claim == "executor-ready":
                artifacts = [self.artifact("verification/regression/runner.sh", "source"),
                             self.artifact("verification/regression/collector.json", "source"),
                             self.artifact("verification/results/infrastructure/build.log", "build-log")]
                result = {"runner_digest": artifacts[0]["sha256"], "collector_digest": artifacts[1]["sha256"],
                          "selftest_passed": True}
            else:
                artifacts = [self.artifact("verification/regression/tests.json", "regression-manifest"),
                             self.artifact(node["output_paths"][0], "simulation-log"),
                             self.artifact(node["output_paths"][1], "analysis-report")]
                if claim == "execution-evidence":
                    result = {"golden_required": True, "batch_seed": "17", "manifest_digest": artifacts[0]["sha256"],
                              "results": [{"test": "demo_test", "seed": 17, "verdict": execution_verdict,
                                           "log_digest": artifacts[1]["sha256"]}]}
                elif claim == "triage-evidence":
                    result = {"failures": [] if failures is None else [
                        {**failure, "rerun_log_digest": artifacts[1]["sha256"]} for failure in failures]}
                else:
                    # The Engine must derive the complete set despite a producer
                    # trying to supply an empty required-node list.
                    result = {"snapshot_revision": revision if snapshot_revision is None else snapshot_revision,
                              "required_nodes": []}
            evidence_file = self.write_json(f"verification/results/{stage}/{claim}.json", {
                "schema": "RegressionEvidence/1", "claim": claim, "revision": revision,
                "tool": "synthetic-contract-fixture/1", "artifacts": artifacts, "result": result,
            })
            checks.append({"criterion": node["acceptance_criteria"][0], "method": "synthetic 合同检查",
                           "expected": "当前回归范围完整且证据有效", "actual": "逐项核对",
                           "report": str(evidence_file.relative_to(self.root)), "claim": claim})
        report_file = self.write_json(f"verification/results/{stage}/validation.json", {
            "schema": "CodeValidation/1", "node_id": node["id"], "revision": state["revision"],
            "input_signature": state["input_signature"], "code_files": state["code_files"],
            "checked_by": "Project Main Agent", "summary": "已核对当前 synthetic 回归报告", "checks": checks,
        })
        self.last_report = report_file
        return self.cli("code", "validate", node["id"], str(report_file.relative_to(self.root))) if via_cli \
            else code.validate(self.store, node["id"], str(report_file.relative_to(self.root)))

    def finish_infrastructure(self):
        delivery = self.infrastructure()
        self.assertTrue(self.validate(delivery)["ready"])
        self.approve(delivery)
        return delivery

    def finish_all(self):
        self.finish_infrastructure()
        delivery = self.results()
        self.assertTrue(self.validate(delivery)["ready"])
        self.approve(delivery)
        return delivery

    def test_four_roles_cli_validation_http_approval_and_fresh_set_share_authority(self):
        infrastructure_plan = self.node("regression-infrastructure-plan")
        results_plan = self.node("regression-results-plan")
        self.assertFalse(self.store.node_plan_review_state(results_plan["id"])["can_approve"])
        self.approve(infrastructure_plan, http=True)
        self.assertTrue(self.cli("code", "status", infrastructure_plan["id"])["completed"])
        infrastructure_delivery = self.infrastructure(approve=False)
        self.assertTrue(self.validate(infrastructure_delivery, via_cli=True)["ready"])
        view = self.view()
        current = next(node for node in view["nodes"] if node["id"] == infrastructure_delivery["id"])
        self.assertTrue(current["plan_review"]["can_approve"])
        self.assertFalse(current["plan_review"]["completed"])
        self.assertNotEqual(self.head("cap.vreg:executor-ready")["status"], "VALID")
        self.assertFalse(self.store.node_plan_review_state(results_plan["id"])["can_approve"])
        self.approve(infrastructure_delivery, http=True)
        self.assertEqual(self.head("cap.vreg:executor-ready")["status"], "VALID")
        self.assertFalse(self.cli("closure", "--workstream", "VREG")["ready"])
        self.approve(results_plan, http=True)
        results_delivery = self.results(approve=False)
        self.assertTrue(self.validate(results_delivery, via_cli=True)["ready"])
        state = self.cli("code", "status", results_delivery["id"])
        self.assertEqual(state["validation"]["regression_contract"], "RegressionResults/2")
        fresh = next(check["validation"]["facts"] for check in state["validation"]["checks"]
                     if check["claim"] == "fresh-evidence")
        self.assertIn(infrastructure_delivery["id"], {node["id"] for node in fresh["required_nodes"]})
        self.assertNotIn(results_delivery["id"], {node["id"] for node in fresh["required_nodes"]})
        self.approve(results_delivery, http=True)
        closure = self.cli("closure", "--workstream", "VREG")
        view = self.view()
        self.assertTrue(closure["ready"])
        self.assertEqual(closure["lifecycle"], "SATISFIED")
        self.assertEqual(view["closure"], closure)
        self.assertEqual(view["progress"]["required"], 4)
        self.assertEqual(view["progress"]["satisfied"], 4)
        self.assertEqual({node["role"] for node in view["nodes"]}, {
            "regression-infrastructure-plan", "regression-infrastructure-deliverable",
            "regression-results-plan", "regression-results-deliverable"})
        self.assertTrue(all(node["capabilities"] for node in view["nodes"]))
        self.assertEqual(self.head("cap.vreg:fresh-evidence")["status"], "VALID")

    def test_infrastructure_only_cannot_finish_vreg(self):
        self.design([self.items[0]])
        self.finish_infrastructure()
        closure = self.store.evaluate_closure("VREG")
        self.assertFalse(closure["ready"])
        self.assertTrue(any(action["kind"] == "REFINE_DESIRED_STATE" and "回归结果方案" in action["reason"]
                            for action in closure["actions"]))
        self.assertEqual(self.head("cap.vreg:executor-ready")["status"], "VALID")

    def test_approved_required_plan_without_delivery_cannot_finish_vreg(self):
        delivery = self.finish_all()
        current = self.store.workstream("VREG")
        desired = [node for node in current["desired_state"] if node["id"] != delivery["id"]]
        with self.store.connect() as connection:
            connection.execute("UPDATE workstreams SET desired_json=? WHERE name='VREG'", (json.dumps(desired),))
        closure = self.store.evaluate_closure("VREG")
        self.assertFalse(closure["ready"])
        self.assertTrue(any(action["kind"] == "REFINE_DESIRED_STATE" and "交付" in action["reason"]
                            for action in closure["actions"]))

    def test_roles_claims_input_cycles_and_legacy_downgrade_are_rejected(self):
        before = self.store.workstream("VREG")
        malformed = []
        roles = copy.deepcopy(self.items)
        roles[0]["role"] = "regression-results-plan"
        malformed.append(roles)
        claims = copy.deepcopy(self.items)
        claims[1]["capabilities"] = ["execution-evidence", "triage-evidence"]
        malformed.append(claims)
        cycle = copy.deepcopy(self.items)
        cycle[0]["inputs"].append("cap.vreg:dut:results")
        malformed.append(cycle)
        foreign_role = copy.deepcopy(self.items)
        foreign_role[0]["role"] = "coverage-implementation-plan"
        malformed.append(foreign_role)
        legacy = copy.deepcopy(self.items)
        legacy[0]["role"] = "capability"
        malformed.append(legacy)
        delivery_proposal = copy.deepcopy(self.items)
        delivery_proposal[0]["role"] = "regression-infrastructure-deliverable"
        malformed.append(delivery_proposal)
        for items in malformed:
            with self.subTest(role=items[0]["role"], claims=items[1]["capabilities"]):
                with self.assertRaises(HarnessError):
                    self.design(items)
                current = self.store.workstream("VREG")
                self.assertEqual(current["revision"], before["revision"])
                self.assertEqual(current["desired_state"], before["desired_state"])

    def test_results_must_bind_required_infrastructure_not_generic_executor_alias(self):
        invalid = copy.deepcopy(self.items)
        invalid[1]["inputs"][-1] = "cap.vreg:executor-ready"
        with self.assertRaises(HarnessError):
            self.design(invalid)

    def test_infrastructure_cannot_depend_on_coverage_results(self):
        invalid = copy.deepcopy(self.items)
        invalid[0]["inputs"].append("cap.vcov:hole-analysis-evidence")
        revision = self.store.workstream("VREG")["revision"]
        with self.assertRaisesRegex(HarnessError, "基础设施只能依赖"):
            self.design(invalid)
        self.assertEqual(self.store.workstream("VREG")["revision"], revision)

    def test_multiple_results_scopes_validate_independently_and_all_require_acceptance(self):
        other = copy.deepcopy(self.items[1])
        other.update(key="dut-other-results", implementation_key="dut:other-results",
                     title="DUT 第二组回归结果方案",
                     output_paths=[path.replace("regression/", "regression-other/")
                                   for path in other["output_paths"]])
        self.design([*self.items, other])
        self.finish_infrastructure()
        plans = [node for node in self.store.workstream("VREG")["desired_state"]
                 if node["role"] == "regression-results-plan"]
        for plan in plans:
            self.approve(plan)
        deliveries = []
        for plan in plans:
            delivery = self.results(approve=False, plan=plan)
            receipt = self.validate(delivery)
            self.assertTrue(receipt["ready"], receipt["blockers"])
            deliveries.append(delivery)
        self.assertTrue(all(self.store.node_plan_review_state(delivery["id"])["can_approve"]
                            for delivery in deliveries))
        self.approve(deliveries[0])
        self.assertFalse(self.store.evaluate_closure("VREG")["ready"])
        self.assertTrue(self.store.node_plan_review_state(deliveries[1]["id"])["can_approve"])
        self.approve(deliveries[1])
        self.assertTrue(self.store.evaluate_closure("VREG")["ready"])
        self.assertEqual(self.view()["progress"]["required"], 6)

    def test_unconsumed_required_infrastructure_cannot_finish_vreg(self):
        other = copy.deepcopy(self.items[0])
        other.update(key="other-infrastructure", implementation_key="other:infrastructure",
                     output_paths=[path.replace("regression/", "regression-other/") for path in other["output_paths"]])
        self.design([*self.items, other])
        closure = self.store.evaluate_closure("VREG")
        self.assertFalse(closure["ready"])
        self.assertTrue(any(action["kind"] == "REFINE_DESIRED_STATE" and "基础设施" in action["reason"]
                            for action in closure["actions"]))

    def test_execution_failures_require_complete_triage_and_recorded_waivers(self):
        self.finish_infrastructure()
        delivery = self.results()
        missing = self.validate(delivery, execution_verdict="FAIL")
        self.assertFalse(missing["ready"])
        self.assertTrue(any("triage" in reason or "分类" in reason for reason in missing["blockers"]), missing["blockers"])
        forged = self.validate(delivery, execution_verdict="FAIL", failures=[{
            "test": "demo_test", "original_seed": 17, "rerun_seed": 17,
            "classification": "DUT", "disposition": "accepted-known-fail", "rerun_verdict": "FAIL",
            "waiver_ref": "nonexistent-owner-review",
        }])
        self.assertFalse(forged["ready"])
        self.assertTrue(any("例外" in reason or "waiver_ref" in reason for reason in forged["blockers"]), forged["blockers"])
        closed = self.validate(delivery, execution_verdict="FAIL", failures=[{
            "test": "demo_test", "original_seed": 17, "rerun_seed": 17,
            "classification": "STIMULUS", "disposition": "fixed", "rerun_verdict": "PASS",
        }])
        self.assertTrue(closed["ready"], closed["blockers"])

    def test_known_failure_waiver_must_belong_to_current_vreg_revision(self):
        self.design()  # Establish a real earlier revision in this isolated fixture.
        self.finish_infrastructure()
        delivery = self.results()
        with self.assertRaises(HarnessError):
            self.store.waive_node(delivery["id"], "fixture-owner", "不能跳过当前交付验收")
        revision = self.store.workstream("VREG")["revision"]
        # Modern delivery waiver APIs intentionally reject bypassing approval.
        # These synthetic database records model independently recorded owner
        # exceptions; they are not inserted into any real project database.
        records = [
            ("synthetic-other-workstream-waive", "VCHK", revision),
            ("synthetic-old-vreg-waive", "VREG", revision - 1),
            ("synthetic-current-vreg-waive", "VREG", revision),
        ]
        with self.store.connect() as connection:
            for identifier, workstream, record_revision in records:
                connection.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?)", (
                    identifier, workstream, record_revision, "WAIVE", "fixture-owner",
                    "synthetic owner exception for demo_test/17", now(),
                ))
        for identifier, _workstream, _revision in records:
            with self.subTest(waiver_ref=identifier):
                receipt = self.validate(delivery, execution_verdict="FAIL", failures=[{
                    "test": "demo_test", "original_seed": 17, "rerun_seed": 17,
                    "classification": "DUT", "disposition": "accepted-known-fail", "rerun_verdict": "FAIL",
                    "waiver_ref": identifier,
                }])
                expected_ready = identifier == "synthetic-current-vreg-waive"
                self.assertEqual(receipt["ready"], expected_ready, receipt["blockers"])
                self.assertEqual(self.store.node_plan_review_state(delivery["id"])["can_approve"], expected_ready)
                if not expected_ready:
                    self.assertTrue(any("当前 VREG 版本" in reason for reason in receipt["blockers"]))
        self.approve(delivery)
        self.assertTrue(self.store.evaluate_closure("VREG")["ready"])

    def test_fresh_snapshot_and_extra_triage_cannot_authorize_acceptance(self):
        self.finish_infrastructure()
        delivery = self.results()
        old = self.validate(delivery, snapshot_revision="old-synthetic-revision")
        self.assertFalse(old["ready"])
        self.assertTrue(any("snapshot_revision" in reason or "快照" in reason for reason in old["blockers"]), old["blockers"])
        extra = self.validate(delivery, failures=[{
            "test": "unexecuted_test", "original_seed": 17, "rerun_seed": 17,
            "classification": "STIMULUS", "disposition": "fixed", "rerun_verdict": "PASS",
        }])
        self.assertFalse(extra["ready"])
        self.assertTrue(any("triage" in reason or "分类" in reason for reason in extra["blockers"]), extra["blockers"])
        self.assertFalse(self.store.node_plan_review_state(delivery["id"])["can_approve"])
        failure = {"test": "demo_test", "original_seed": 17, "rerun_seed": 17,
                   "classification": "STIMULUS", "disposition": "fixed", "rerun_verdict": "PASS"}
        duplicate = self.validate(delivery, execution_verdict="FAIL", failures=[failure, failure])
        self.assertFalse(duplicate["ready"])
        self.assertTrue(any("重复" in reason for reason in duplicate["blockers"]), duplicate["blockers"])

    def test_historical_unchecked_regression_receipt_requires_revalidation(self):
        delivery = self.finish_all()
        with self.store.connect() as connection:
            row = connection.execute("SELECT id,payload_json FROM code_validations WHERE node_id=?", (delivery["id"],)).fetchone()
            payload = json.loads(row["payload_json"])
            payload.pop("regression_contract")
            connection.execute("UPDATE code_validations SET payload_json=? WHERE id=?", (json.dumps(payload), row["id"]))
        state = self.store.node_plan_review_state(delivery["id"])
        self.assertFalse(state["validation"]["current"])
        self.assertFalse(state["completed"])
        self.assertNotEqual(self.head("cap.vreg:fresh-evidence")["status"], "VALID")

    def test_changed_required_upstream_range_revokes_fresh_results(self):
        delivery = self.finish_all()
        # A new historical checking revision changes the Engine-owned required
        # evidence universe while the synthetic cap.vchk dependency ID is stable.
        self.store._design_workstream("VCHK", None, [], [], [])
        state = self.store.node_plan_review_state(delivery["id"])
        self.assertFalse(state["completed"])
        self.assertFalse(self.store.evaluate_closure("VREG")["ready"])
        self.assertNotEqual(self.head("cap.vreg:fresh-evidence")["status"], "VALID")

    def test_feedback_routes_are_current_and_do_not_mutate_upstream(self):
        self.finish_infrastructure()
        delivery = self.results()
        failed = self.validate(delivery, execution_verdict="FAIL", failures=[{
            "test": "demo_test", "original_seed": 17, "rerun_seed": 17,
            "classification": "STIMULUS", "disposition": "replan", "rerun_verdict": "FAIL",
            "responsible_workstream": "VSTIM", "next_action": "修正约束并使用原 seed 重跑",
        }])
        self.assertFalse(failed["ready"])
        actions = self.store.evaluate_closure("VREG")["actions"]
        action = next(action for action in actions if action["kind"] == "ANALYZE_VERIFICATION_FEEDBACK")
        self.assertEqual(action["feedback_routes"][0]["responsible_workstream"], "VSTIM")
        self.assertFalse(any(plan["workstream"] == "VSTIM" for plan in self.store.workstreams()))
        self.write("verification/results/results/triage-evidence.json", "changed synthetic report\n")
        self.assertFalse(self.store.node_plan_review_state(delivery["id"])["validation"]["current"])
        actions = self.store.evaluate_closure("VREG")["actions"]
        self.assertFalse(any(action["kind"] == "ANALYZE_VERIFICATION_FEEDBACK" for action in actions))

    def test_output_change_preserves_infrastructure_plan_and_revokes_results(self):
        self.finish_all()
        before = self.head("art.code_plan:vreg:dut:infrastructure")["data"]["current"]
        self.write("verification/regression/runner.sh", "#!/bin/sh\n# changed synthetic runner\n")
        self.assertEqual(self.head("art.code_plan:vreg:dut:infrastructure")["data"]["current"], before)
        self.assertTrue(self.store.node_plan_review_state(self.node("regression-infrastructure-plan")["id"])["completed"])
        for role in ("regression-infrastructure-deliverable", "regression-results-plan", "regression-results-deliverable"):
            self.assertFalse(self.store.node_plan_review_state(self.node(role)["id"])["completed"])
        self.assertNotEqual(self.head("cap.vreg:executor-ready")["status"], "VALID")
        self.assertNotEqual(self.head("cap.vreg:fresh-evidence")["status"], "VALID")
        self.assertFalse(self.cli("closure", "--workstream", "VREG")["ready"])
        self.assertFalse(self.view()["closure"]["ready"])

    def test_new_revision_does_not_inherit_old_approval_or_receipts(self):
        self.finish_all()
        old = self.store.workstream("VREG")
        versions = code.artifacts(self.store, "VREG")["versions"]
        self.design()
        current = self.store.workstream("VREG")
        self.assertEqual(current["revision"], old["revision"] + 1)
        self.assertEqual(len(current["desired_state"]), 2)
        self.assertTrue(all(not self.store.node_plan_review_state(node["id"])["completed"] for node in current["desired_state"]))
        self.assertFalse(self.store.evaluate_closure("VREG")["ready"])
        self.assertTrue(all(version in code.artifacts(self.store, "VREG")["versions"] for version in versions))

    def test_new_vreg_cli_planning_does_not_create_legacy_nodes(self):
        fresh_root = self.root / "fresh-vreg"
        fresh_root.mkdir()
        fresh = ProjectStore(fresh_root)
        fresh.bootstrap(project_name="fresh-regression", runtime="none", rtl_roots=[str(self.root / "rtl")],
                        verif_root="verification", dut_top="dut", dut_top_file=str(self.root / "rtl/dut.sv"))
        planned = fresh.design_workstream("VREG", None, [], [], [])
        self.assertTrue(code.modern(planned))
        self.assertEqual(planned["desired_state"], [])
        self.assertFalse(planned["auto_closure"]["ready"])
        self.assertEqual(planned["auto_closure"]["actions"][0]["kind"], "REFINE_DESIRED_STATE")

    def test_legacy_code_roles_normalize_new_proposals_without_mutating_old_history(self):
        legacy = copy.deepcopy(self.items)
        for node in legacy:
            node["role"] = "code-plan"
        self.design(legacy)
        self.assertEqual({node["role"] for node in self.store.workstream("VREG")["desired_state"]}, {
            "regression-infrastructure-plan", "regression-results-plan"})
        self.finish_all()
        old = self.store.workstream("VREG")
        with self.store.read_connect() as connection:
            reviews_before = [dict(row) for row in connection.execute(
                "SELECT * FROM node_plan_reviews WHERE workstream='VREG' ORDER BY rowid")]
        historical = copy.deepcopy(old["desired_state"])
        for node in historical:
            node["role"] = "code-plan" if code.is_plan(node) else "code-deliverable"
        with self.store.connect() as connection:
            connection.execute("UPDATE workstreams SET desired_json=? WHERE name='VREG'", (json.dumps(historical),))
            for node in historical:
                connection.execute("UPDATE nodes SET data_json=? WHERE id=?", (json.dumps(node), node["id"]))
        view = self.view()
        self.assertEqual({node["role"] for node in view["nodes"]}, {"code-plan", "code-deliverable"})
        self.assertEqual({code.node_label(node, "VREG") for node in view["nodes"]}, {
            "回归基础设施方案", "回归基础设施交付", "回归结果方案", "回归结果交付"})
        self.assertTrue(all(node["capabilities"] for node in view["nodes"]))
        with self.store.read_connect() as connection:
            reviews_after = [dict(row) for row in connection.execute(
                "SELECT * FROM node_plan_reviews WHERE workstream='VREG' ORDER BY rowid")]
        self.assertEqual(reviews_after, reviews_before)
        self.assertEqual([node["role"] for node in self.store.workstream("VREG")["desired_state"]],
                         [node["role"] for node in historical])

    def feedback(self, node):
        state = self.store.node_plan_review_state(node["id"])
        self.http.post("/api/reviews/node-plan-section", {
            "node": node["id"], "section": "writing-plan", "definition_digest": state["definition_digest"],
            "verdict": "modify", "reviewer": "http-owner", "reason": "核对当前回归范围和同 seed 重跑方法",
        }, self.http.server.write_token)
        state = self.cli("code", "status", node["id"])
        self.assertFalse(state["can_approve"])
        batch = self.http.post("/api/reviews/node-feedback-submit", {
            "node": node["id"], "definition_digest": state["definition_digest"],
        }, self.http.server.write_token)["result"]
        self.assertEqual(batch["count"], 1)
        self.assertEqual(self.store.node_plan_review_state(node["id"])["feedback"]["processing_count"], 1)
        self.store.complete_review_feedback(batch["batch_id"], "Project Main Agent", "已核对当前回归和重跑方法，无需改动")
        self.assertTrue(self.store.node_plan_review_state(node["id"])["can_approve"])

    def test_all_four_roles_support_batched_opinions(self):
        for stage in ("infrastructure", "results"):
            plan = self.node(f"regression-{stage}-plan")
            self.feedback(plan)
            self.approve(plan)
            delivery = self.infrastructure(approve=False) if stage == "infrastructure" else self.results(approve=False)
            self.assertTrue(self.validate(delivery)["ready"])
            self.feedback(delivery)
            self.approve(delivery)
        self.assertTrue(self.store.evaluate_closure("VREG")["ready"])

    def test_typed_delivery_assignment_completion_never_approves_delivery(self):
        project_path = self.store.state / "project.json"
        project = json.loads(project_path.read_text())
        project["runtime"] = "codex"
        project_path.write_text(json.dumps(project), encoding="utf-8")
        self.approve(self.node("regression-infrastructure-plan"))
        delivery = self.node("regression-infrastructure-deliverable")
        action = next(action for action in self.store.evaluate_closure("VREG")["actions"]
                      if action["target"] == delivery["id"] and action["executor"] == "reasoning")
        assignment = self.store.claim_agent_work(action["id"], "regression-worker", "TestEngineer", "实现回归执行器",
                                                 write_scope=delivery["output_paths"])
        self.assertEqual(assignment["node_id"], delivery["id"])
        self.assertEqual(assignment["workstream_revision"], self.store.workstream("VREG")["revision"])
        finished = self.store.finish_agent_work(assignment["id"], "regression-worker", "COMPLETED", "synthetic worker completed")
        self.assertEqual(finished["status"], "COMPLETED")
        self.assertFalse(self.store.node_plan_review_state(delivery["id"])["completed"])
        self.assertNotEqual(self.head("cap.vreg:executor-ready")["status"], "VALID")

    def test_managed_vreg_prompt_uses_four_direct_types_and_current_dependencies(self):
        launch = workflow_launch.status(self.store)
        workflow_launch.choose(self.store, "parallel", "fixture-owner", launch["vdoc_signature"])
        # New parallel workflow envelopes legitimately revoke the synthetic
        # upstream capability. Request the explicit results-scope planning action
        # instead of approving implementation with that invalid dependency.
        self.design([self.items[0]])
        task = next(task for task in service.candidates(self.store) if task["workstream"] == "VREG")
        prompt = service.prompt_for(self.store, task)
        for label in ("回归基础设施方案", "回归基础设施交付", "回归结果方案", "回归结果交付"):
            self.assertIn(label, prompt)
        self.assertIn("regression-infrastructure-plan", prompt)
        self.assertIn("regression-results-plan", prompt)
        self.assertIn("cap.vreg:executor-ready", prompt)
        self.assertIn("cap.vreg:<implementation_key>", prompt)
        self.assertIn("只有方案与依赖仍有效", prompt)
        for obsolete in ("同工作包", "其他包", "code-deliverable", "工作包"):
            self.assertNotIn(obsolete, prompt)


if __name__ == "__main__":
    unittest.main()
