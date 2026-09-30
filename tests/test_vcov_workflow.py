"""VCOV four-node governance and convergence using isolated synthetic evidence."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from tests import test_vdoc_artifacts as fixtures
from verif_harness import code_workflow as code
from verif_harness.dashboard import dashboard_project_id
from verif_harness.store import HarnessError, ProjectStore, Validity


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_RECEIPT = {
    "adapter_schema_version": 1, "state": "PASS", "blockers": [],
    "request_sha256": "a" * 64, "operation": "synthetic-coverage-analysis",
    "tool_identity": {"state": "PASS"}, "tool": "synthetic-contract-fixture/1",
}


class VcovWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.VdocArtifactsTest()
        self.fixture.setUp()
        self.fixture.prepare()
        self.fixture.finish()
        self.store = self.fixture.store
        self.root = self.store.root
        self.http = self.fixture.fixture
        self.write("coverage-plan.md", "# 覆盖计划\n\nC.DEMO.1 满边界；C.DEMO.2 空边界。\n")
        with self.store.connect() as connection:
            for identifier in (
                "cap.venv:environment-smoke-evidence", "cap.vstim:reachability-evidence",
                "cap.vchk:scoreboard-evidence", "cap.vcase:targeted-evidence", "cap.vreg:executor-ready",
            ):
                self.store.upsert_node(connection, identifier, "capability", identifier, Validity.VALID,
                                       data={"derived": True, "current": {"fixture": identifier}})
        common = {
            "statement": "实现并核对当前 DUT 的满空边界覆盖范围", "scope": ["满空边界"],
            "work_content": ["按批准覆盖清单完成当前验证工作"],
            "implementation_approach": ["保持 DUT 只读，使用版本绑定的采集与检查入口"],
            "validation_methods": ["核对受控清单及当前专用证据"],
            "deliverables": ["当前交付文件与逐项检查报告"],
            "acceptance_criteria": ["覆盖项全集与当前证据一致"],
            "source_refs": ["coverage-plan.md"], "input_files": ["coverage-plan.md"],
        }
        self.items = [
            {**copy.deepcopy(common), "key": "fifo-implementation", "implementation_key": "fifo:implementation",
             "role": "coverage-implementation-plan", "title": "FIFO 覆盖率实现方案",
             "inputs": ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence", "cap.vreg:executor-ready"],
             "output_paths": ["verification/coverage/model.sv", "verification/coverage/collector.json"],
             "capabilities": ["coverage-model", "coverage-collection"],
             "coverage_item_ids": ["C.DEMO.1", "C.DEMO.2"]},
            {**copy.deepcopy(common), "key": "fifo-convergence", "implementation_key": "fifo:convergence",
             "role": "coverage-convergence-plan", "title": "FIFO 覆盖率收敛方案",
             "inputs": ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence",
                        "cap.vstim:reachability-evidence", "cap.vchk:scoreboard-evidence",
                        "cap.vcase:targeted-evidence", "cap.vreg:executor-ready", "cap.vcov:fifo:implementation"],
             "output_paths": ["verification/results/convergence/database.json", "verification/results/convergence/analysis.json"],
             "capabilities": ["coverage-collection-evidence", "hole-analysis-evidence"]},
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
        proposal = self.write_json("vcov-proposal.json", {
            "schema": "DesiredStateProposal/1", "workstream": "VCOV",
            "nodes": self.items if items is None else items,
        })
        return self.store.design_workstream("VCOV", None, [], [], [], desired_file=proposal.name)

    def node(self, role):
        return next(n for n in self.store.workstream("VCOV")["desired_state"] if n["role"] == role)

    def head(self, identifier):
        return next(n for n in code.artifacts(self.store, "VCOV")["heads"] if n["id"] == identifier)

    def cli(self, *args):
        process = subprocess.run([sys.executable, str(ROOT / "scripts/verif_harness.py"),
                                  *args, "--project-root", str(self.root)], text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def view(self):
        with self.http.get("/api/snapshot") as response:
            return next(w for w in json.load(response)["workstreams"] if w["workstream"] == "VCOV")

    def approve(self, node, http=False):
        state = self.store.node_plan_review_state(node["id"])
        self.assertTrue(state["can_approve"], state["blockers"])
        if http:
            return self.http.post("/api/reviews/node-plan-complete", {
                "node": node["id"], "definition_digest": state["definition_digest"], "reviewer": "http-owner",
            }, self.http.server.write_token)["result"]
        return self.store.complete_node_plan_review(node["id"], state["definition_digest"], "fixture-owner")

    def implement(self, approve=True):
        if approve:
            self.approve(self.node("coverage-implementation-plan"))
        self.write("verification/coverage/model.sv", "module fixture_coverage; endmodule\n")
        self.write_json("verification/coverage/collector.json", {"synthetic": True, "export": "coverage"})
        self.write("verification/results/implementation/build.log", "synthetic coverage model compile check\n")
        self.manifest = {
            **ANALYSIS_RECEIPT,
            "schema": "CoverageItemManifest/1", "plan_digest": self.store._digest(self.root / "coverage-plan.md"),
            "model_digest": self.store._digest(self.root / "verification/coverage/model.sv"),
            "planned_item_ids": self.items[0]["coverage_item_ids"],
            "mapped_item_ids": self.items[0]["coverage_item_ids"],
        }
        return self.node("coverage-implementation-deliverable")

    def convergence(self, approve=True):
        if approve:
            self.approve(self.node("coverage-convergence-plan"))
        self.write_json("verification/results/convergence/database.json", {"synthetic": True, "hits": [1, 1]})
        self.write_json("verification/results/convergence/analysis.json", {
            **ANALYSIS_RECEIPT, "synthetic": True, "summary": "all items covered",
        })
        return self.node("coverage-convergence-deliverable")

    def artifact(self, name, kind):
        return {"path": name, "sha256": self.store._digest(self.root / name),
                "kind": kind, "analyzed_by": ["xverif"]}

    def validate(self, node, manifest=None, items=None, via_cli=False, exporter_digest=None, hole_database=None):
        stage = "implementation" if code.vcov_stage(node) == "implementation" else "convergence"
        manifest = copy.deepcopy(self.manifest if manifest is None else manifest)
        manifest_file = self.write_json(f"verification/results/{stage}/coverage-items.json", manifest)
        manifest_artifact = self.artifact(str(manifest_file.relative_to(self.root)), "analysis-report")
        state = self.store.node_plan_review_state(node["id"])
        project = json.loads((self.store.state / "project.json").read_text())
        checks = []
        for claim in node["capabilities"]:
            if claim == "coverage-model":
                artifacts = [self.artifact("verification/coverage/model.sv", "source"),
                             self.artifact("verification/results/implementation/build.log", "build-log"),
                             self.artifact("coverage-plan.md", "document"), manifest_artifact]
                result = {"plan_digest": manifest["plan_digest"], "model_digest": manifest["model_digest"],
                          "planned_items": len(manifest["planned_item_ids"]),
                          "mapped_items": len(manifest["mapped_item_ids"]), "compiled": True,
                          "coverage_manifest_digest": manifest_artifact["sha256"]}
            elif claim == "coverage-collection":
                artifacts = [self.artifact("verification/coverage/collector.json", "configuration"),
                             self.artifact("verification/results/implementation/build.log", "build-log")]
                result = {"configured": True, "exporter_digest": exporter_digest or artifacts[0]["sha256"]}
            else:
                database = hole_database if claim == "hole-analysis-evidence" and hole_database \
                    else "verification/results/convergence/database.json"
                artifacts = [self.artifact(database, "coverage-database"),
                             self.artifact("verification/results/convergence/analysis.json", "analysis-report"), manifest_artifact]
                result = {"coverage_manifest_digest": manifest_artifact["sha256"]}
                if claim == "coverage-collection-evidence":
                    result.update(database_ids=["synthetic-current-db"], runs=1, merge_errors=0, stale_shards=0)
                else:
                    result["items"] = items if items is not None else [
                        {"id": identifier, "status": "covered", "hits": 1, "plan_ref": "coverage-plan.md"}
                        for identifier in manifest["planned_item_ids"]]
            evidence_file = self.write_json(f"verification/results/{stage}/{claim}.json", {
                "schema": "CoverageEvidence/1", "claim": claim,
                "revision": project.get("baseline_revision") or "fixture-revision",
                "tool": "synthetic-contract-fixture/1", "artifacts": artifacts, "result": result,
            })
            checks.append({"criterion": node["acceptance_criteria"][0], "method": "synthetic 合同验证",
                           "expected": "当前覆盖范围完整且证据有效", "actual": "逐项核对",
                           "report": str(evidence_file.relative_to(self.root)), "claim": claim})
        report_file = self.write_json(f"verification/results/{stage}/validation.json", {
            "schema": "CodeValidation/1", "node_id": node["id"], "revision": state["revision"],
            "input_signature": state["input_signature"], "code_files": state["code_files"],
            "checked_by": "Project Main Agent", "summary": "已核对当前 synthetic 覆盖证据", "checks": checks,
        })
        self.last_report = report_file
        return self.cli("code", "validate", node["id"], str(report_file.relative_to(self.root))) if via_cli \
            else code.validate(self.store, node["id"], str(report_file.relative_to(self.root)))

    def finish_implementation(self):
        delivery = self.implement()
        self.assertTrue(self.validate(delivery)["ready"])
        self.approve(delivery)
        return delivery

    def finish_all(self):
        self.finish_implementation()
        delivery = self.convergence()
        self.assertTrue(self.validate(delivery)["ready"])
        self.approve(delivery)
        return delivery

    def test_four_nodes_cli_validation_and_http_acceptance_share_authority(self):
        implementation = self.node("coverage-implementation-plan")
        convergence = self.node("coverage-convergence-plan")
        self.assertFalse(self.store.node_plan_review_state(convergence["id"])["can_approve"])
        self.approve(implementation, http=True)
        self.assertTrue(self.cli("code", "status", implementation["id"])["completed"])
        delivery = self.implement(approve=False)
        receipt = self.validate(delivery, via_cli=True)
        self.assertTrue(receipt["ready"])
        self.assertEqual(self.cli("code", "status", delivery["id"])["validation"]["coverage_contract"],
                         "CoverageConvergence/2")
        current = next(n for n in self.view()["nodes"] if n["id"] == delivery["id"])
        self.assertEqual(current["coverage_item_ids"], self.items[0]["coverage_item_ids"])
        self.assertEqual(current["capabilities"], self.items[0]["capabilities"])
        self.assertTrue(current["plan_review"]["can_approve"])
        self.assertFalse(current["plan_review"]["completed"])
        self.assertNotEqual(self.head("cap.vcov:coverage-model")["status"], "VALID")
        self.approve(delivery, http=True)
        self.assertTrue(self.cli("code", "status", delivery["id"])["completed"])
        self.assertEqual(self.head("cap.vcov:coverage-model")["status"], "VALID")
        self.assertEqual(self.head("cap.vcov:coverage-collection")["status"], "VALID")
        self.approve(convergence, http=True)
        convergence_delivery = self.convergence(approve=False)
        self.assertTrue(self.validate(convergence_delivery, via_cli=True)["ready"])
        self.assertFalse(self.cli("closure", "--workstream", "VCOV")["ready"])
        self.approve(convergence_delivery, http=True)
        closure = self.cli("closure", "--workstream", "VCOV")
        view = self.view()
        self.assertTrue(closure["ready"])
        self.assertEqual(closure["lifecycle"], "SATISFIED")
        self.assertEqual(view["closure"], closure)
        self.assertEqual(view["progress"]["required"], 4)
        self.assertEqual(view["progress"]["satisfied"], 4)
        self.assertEqual({n["role"] for n in view["nodes"]}, {
            "coverage-implementation-plan", "coverage-implementation-deliverable",
            "coverage-convergence-plan", "coverage-convergence-deliverable"})
        for node in view["nodes"]:
            stage = code.vcov_stage(node)
            self.assertEqual(node["capabilities"], self.items[0 if stage == "implementation" else 1]["capabilities"])
            if stage == "implementation":
                self.assertEqual(node["coverage_item_ids"], self.items[0]["coverage_item_ids"])
        self.assertEqual(self.head("cap.vcov:hole-analysis-evidence")["status"], "VALID")

    def test_implementation_only_cannot_finish_vcov(self):
        self.design([self.items[0]])
        self.finish_implementation()
        closure = self.store.evaluate_closure("VCOV")
        self.assertFalse(closure["ready"])
        self.assertTrue(any(a["kind"] == "REFINE_DESIRED_STATE" and "收敛方案" in a["reason"]
                            for a in closure["actions"]))

    def test_historical_receipt_without_manifest_contract_requires_revalidation(self):
        delivery = self.finish_implementation()
        with self.store.connect() as connection:
            row = connection.execute("SELECT id,payload_json FROM code_validations WHERE node_id=?", (delivery["id"],)).fetchone()
            payload = json.loads(row["payload_json"])
            payload.pop("coverage_contract")
            connection.execute("UPDATE code_validations SET payload_json=? WHERE id=?", (json.dumps(payload), row["id"]))
        state = self.store.node_plan_review_state(delivery["id"])
        self.assertFalse(state["validation"]["current"])
        self.assertFalse(state["completed"])
        self.assertNotEqual(self.head("cap.vcov:coverage-model")["status"], "VALID")
        self.assertFalse(self.store.node_plan_review_state(self.node("coverage-convergence-plan")["id"])["can_approve"])

    def test_manifest_must_match_approved_item_universe_and_current_outputs(self):
        delivery = self.implement()
        missing = {**self.manifest, "planned_item_ids": ["C.DEMO.1"], "mapped_item_ids": ["C.DEMO.1"]}
        receipt = self.validate(delivery, manifest=missing)
        self.assertFalse(receipt["ready"])
        self.assertTrue(any("批准的必需覆盖范围" in reason for reason in receipt["blockers"]))
        state = self.store.node_plan_review_state(delivery["id"])
        self.assertFalse(state["can_approve"])
        with self.assertRaises(HarnessError):
            self.store.complete_node_plan_review(delivery["id"], state["definition_digest"], "fixture-owner")

    def test_convergence_requires_all_items_and_the_accepted_implementation_manifest(self):
        self.finish_implementation()
        delivery = self.convergence()
        incomplete = [{"id": "C.DEMO.1", "status": "covered", "hits": 1, "plan_ref": "coverage-plan.md"}]
        receipt = self.validate(delivery, items=incomplete)
        self.assertFalse(receipt["ready"])
        self.assertTrue(any("遗漏计划覆盖项" in reason for reason in receipt["blockers"]))
        different = {**self.manifest, "planned_item_ids": list(reversed(self.manifest["planned_item_ids"])),
                     "mapped_item_ids": list(reversed(self.manifest["mapped_item_ids"]))}
        receipt = self.validate(delivery, manifest=different)
        self.assertFalse(receipt["ready"])
        self.assertTrue(any("已验收实现不一致" in reason for reason in receipt["blockers"]))

    def test_collection_and_hole_analysis_must_use_the_same_native_database(self):
        self.finish_implementation()
        delivery = self.convergence()
        self.write_json("verification/results/convergence/other-database.json", {
            "synthetic": True, "database": "different-run", "hits": [2, 2],
        })
        receipt = self.validate(delivery, hole_database="verification/results/convergence/other-database.json")
        self.assertFalse(receipt["ready"])
        self.assertTrue(any("数据库" in reason for reason in receipt["blockers"]), receipt["blockers"])
        self.assertFalse(self.store.node_plan_review_state(delivery["id"])["can_approve"])

    def test_bound_native_digests_must_describe_approved_inputs_and_actual_outputs(self):
        delivery = self.implement()
        log_digest = self.store._digest(self.root / "verification/results/implementation/build.log")
        different = {**self.manifest, "plan_digest": log_digest,
                     "model_digest": self.store._digest(self.root / "coverage-plan.md")}
        receipt = self.validate(delivery, manifest=different, exporter_digest=log_digest)
        self.assertFalse(receipt["ready"])
        for message in ("覆盖计划摘要不属于", "覆盖模型摘要不属于", "覆盖率采集配置摘要不属于"):
            self.assertTrue(any(message in reason for reason in receipt["blockers"]), receipt["blockers"])

    def test_report_declared_approved_exclusion_requires_recorded_owner_decision(self):
        self.finish_implementation()
        delivery = self.convergence()
        items = [{"id": "C.DEMO.1", "status": "covered", "hits": 1, "plan_ref": "coverage-plan.md"},
                 {"id": "C.DEMO.2", "status": "excluded", "hits": 0, "plan_ref": "coverage-plan.md",
                  "waiver": {"id": "not-a-recorded-decision", "reviewer": "fixture-owner",
                             "decision_date": "2026-09-30", "rationale": "synthetic declared exception",
                             "status": "Approved"}}]
        receipt = self.validate(delivery, items=items)
        self.assertFalse(receipt["ready"])
        self.assertTrue(any("当前版本的负责人例外批准记录" in reason for reason in receipt["blockers"]))
        self.assertFalse(self.store.node_plan_review_state(delivery["id"])["can_approve"])

    def test_feedback_routes_are_current_and_do_not_mutate_upstream(self):
        self.finish_implementation()
        delivery = self.convergence()
        items = [{"id": "C.DEMO.1", "status": "covered", "hits": 1, "plan_ref": "coverage-plan.md"},
                 {"id": "C.DEMO.2", "status": "uncovered", "hits": 0, "plan_ref": "coverage-plan.md",
                  "responsible_workstream": "VCASE", "next_action": "增加空边界定向用例"}]
        receipt = self.validate(delivery, items=items)
        self.assertFalse(receipt["ready"])
        actions = self.store.evaluate_closure("VCOV")["actions"]
        action = next(a for a in actions if a["kind"] == "ANALYZE_VERIFICATION_FEEDBACK")
        self.assertEqual(action["feedback_routes"][0]["responsible_workstream"], "VCASE")
        self.assertFalse(any(w["workstream"] == "VCASE" for w in self.store.workstreams()))
        self.write("verification/results/convergence/hole-analysis-evidence.json", "changed report\n")
        self.assertFalse(self.store.node_plan_review_state(delivery["id"])["validation"]["current"])
        actions = self.store.evaluate_closure("VCOV")["actions"]
        self.assertFalse(any(a["kind"] == "ANALYZE_VERIFICATION_FEEDBACK" for a in actions))
        self.assertTrue(all(not a.get("feedback_routes") for a in actions))

    def test_output_change_preserves_implementation_plan_and_revokes_dependent_convergence(self):
        self.finish_all()
        before = self.head("art.code_plan:vcov:fifo:implementation")["data"]["current"]
        self.write("verification/coverage/model.sv", "module fixture_coverage_changed; endmodule\n")
        self.assertEqual(self.head("art.code_plan:vcov:fifo:implementation")["data"]["current"], before)
        self.assertTrue(self.store.node_plan_review_state(self.node("coverage-implementation-plan")["id"])["completed"])
        for role in ("coverage-implementation-deliverable", "coverage-convergence-plan", "coverage-convergence-deliverable"):
            self.assertFalse(self.store.node_plan_review_state(self.node(role)["id"])["completed"])
        self.assertNotEqual(self.head("cap.vcov:coverage-model")["status"], "VALID")
        self.assertNotEqual(self.head("cap.vcov:hole-analysis-evidence")["status"], "VALID")
        self.assertFalse(self.cli("closure", "--workstream", "VCOV")["ready"])
        self.assertFalse(self.view()["closure"]["ready"])

    def test_new_revision_does_not_inherit_old_approval_or_receipts(self):
        self.finish_all()
        old = self.store.workstream("VCOV")
        old_versions = code.artifacts(self.store, "VCOV")["versions"]
        self.design()
        current = self.store.workstream("VCOV")
        self.assertEqual(current["revision"], old["revision"] + 1)
        self.assertEqual(len(current["desired_state"]), 2)
        self.assertTrue(all(not self.store.node_plan_review_state(n["id"])["completed"] for n in current["desired_state"]))
        self.assertFalse(self.store.evaluate_closure("VCOV")["ready"])
        self.assertTrue(all(version in code.artifacts(self.store, "VCOV")["versions"] for version in old_versions))

    def test_fresh_default_vcov_planning_does_not_create_legacy_nodes(self):
        fresh_root = self.root / "fresh-vcov"
        fresh_root.mkdir()
        fresh = ProjectStore(fresh_root)
        fresh.bootstrap(project_name="fresh-coverage", runtime="none", rtl_roots=[str(self.root / "rtl")],
                        verif_root="verification", dut_top="dut", dut_top_file=str(self.root / "rtl/dut.sv"))
        planned = fresh.design_workstream("VCOV", None, [], [], [])
        self.assertTrue(code.modern(planned))
        self.assertEqual(planned["desired_state"], [])
        self.assertFalse(planned["auto_closure"]["ready"])
        self.assertEqual(planned["auto_closure"]["actions"][0]["kind"], "REFINE_DESIRED_STATE")

    def test_legacy_or_mixed_proposal_cannot_replace_current_typed_revision(self):
        before = self.store.workstream("VCOV")
        for role in ("coverage-goal", "coverage-implementation-deliverable"):
            with self.subTest(role=role):
                invalid = copy.deepcopy(self.items)
                invalid[0]["role"] = role
                with self.assertRaises(HarnessError):
                    self.design(invalid)
                current = self.store.workstream("VCOV")
                self.assertEqual(current["revision"], before["revision"])
                self.assertEqual(current["desired_state"], before["desired_state"])

    def test_legacy_roles_project_capabilities_without_rewriting_history(self):
        self.finish_all()
        old = self.store.workstream("VCOV")
        with self.store.read_connect() as connection:
            reviews_before = [dict(row) for row in connection.execute(
                "SELECT * FROM node_plan_reviews WHERE workstream='VCOV' ORDER BY rowid")]
        legacy = copy.deepcopy(old["desired_state"])
        for node in legacy:
            node["role"] = "code-plan" if code.is_plan(node) else "code-deliverable"
        with self.store.connect() as connection:
            connection.execute("UPDATE workstreams SET desired_json=? WHERE name='VCOV'", (json.dumps(legacy),))
            for node in legacy:
                connection.execute("UPDATE nodes SET data_json=? WHERE id=?", (json.dumps(node), node["id"]))
        view = self.view()
        self.assertEqual({node["id"] for node in view["nodes"]}, {node["id"] for node in legacy})
        self.assertEqual({node["role"] for node in view["nodes"]}, {"code-plan", "code-deliverable"})
        self.assertEqual({code.node_label(node, "VCOV") for node in view["nodes"]}, {
            "覆盖率实现方案", "覆盖率实现交付", "覆盖率收敛方案", "覆盖率收敛交付"})
        self.assertTrue(all(node["capabilities"] for node in view["nodes"]))
        with self.store.read_connect() as connection:
            reviews_after = [dict(row) for row in connection.execute(
                "SELECT * FROM node_plan_reviews WHERE workstream='VCOV' ORDER BY rowid")]
        self.assertEqual(reviews_after, reviews_before)
        self.assertEqual([node["role"] for node in self.store.workstream("VCOV")["desired_state"]],
                         [node["role"] for node in legacy])

    def test_all_four_roles_support_batched_opinions(self):
        for stage in ("implementation", "convergence"):
            plan = self.node(f"coverage-{stage}-plan")
            self.feedback(plan)
            self.approve(plan)
            delivery = self.implement(approve=False) if stage == "implementation" else self.convergence(approve=False)
            self.assertTrue(self.validate(delivery)["ready"])
            self.feedback(delivery)
            self.approve(delivery)
        self.assertTrue(self.store.evaluate_closure("VCOV")["ready"])

    def feedback(self, node):
        state = self.store.node_plan_review_state(node["id"])
        self.http.post("/api/reviews/node-plan-section", {
            "node": node["id"], "section": "writing-plan", "definition_digest": state["definition_digest"],
            "verdict": "modify", "reviewer": "http-owner", "reason": "核对当前满空边界采样时机",
        }, self.http.server.write_token)
        state = self.cli("code", "status", node["id"])
        self.assertFalse(state["can_approve"])
        batch = self.http.post("/api/reviews/node-feedback-submit", {
            "node": node["id"], "definition_digest": state["definition_digest"],
        }, self.http.server.write_token)["result"]
        self.assertEqual(batch["count"], 1)
        self.assertEqual(self.store.node_plan_review_state(node["id"])["feedback"]["processing_count"], 1)
        self.store.complete_review_feedback(batch["batch_id"], "Project Main Agent", "已核对当前采样方法，无需改动")
        self.assertTrue(self.store.node_plan_review_state(node["id"])["can_approve"])

    def test_browser_four_types_preview_approval_and_reload(self):
        if not shutil.which("node") or subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode:
            self.skipTest("Node.js and Playwright are required for real browser testing")
        for stage, title in (("implementation", "实现"), ("convergence", "收敛")):
            plan = self.node(f"coverage-{stage}-plan")
            self.browser(plan, "plan", "覆盖率" + title + "方案")
            delivery = self.implement(approve=False) if stage == "implementation" else self.convergence(approve=False)
            self.assertTrue(self.validate(delivery)["ready"])
            self.browser(delivery, "delivery", "覆盖率" + title + "交付",
                         expectedFileHeading="交付代码" if stage == "implementation" else "交付文件",
                         previewText="fixture_coverage" if stage == "implementation" else "synthetic")
        self.assertTrue(self.store.evaluate_closure("VCOV")["ready"])

    def browser(self, node, phase, expected_role, **extra):
        config = {"url": self.http.url, "project": dashboard_project_id(self.root),
                  "token": self.http.server.write_token, "workstream": "VCOV", "node": node["id"],
                  "phase": phase, "expectedRole": expected_role, **extra}
        process = subprocess.run(["node", str(Path(__file__).with_name("dashboard_code_workflow.cjs"))],
                                 input=json.dumps(config), text=True, capture_output=True, timeout=90,
                                 env=os.environ.copy())
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(self.cli("code", "status", node["id"])["completed"])


if __name__ == "__main__":
    unittest.main()
