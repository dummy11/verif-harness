"""Synthetic case provenance, source versions and owner-confirmation boundaries."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tests.case_traceability_fixtures import traceability_fixture
from tests import test_code_workflow as workflow_fixtures
from verif_harness.case_traceability import (
    CaseTraceabilityError, behavior_digest, canonical_digest, confirmation_context, validate_traceability,
)
from verif_harness.evidence_contracts import EvidenceContractError, validate_workstream_evidence
from verif_harness import code_workflow as code


class CaseEvidenceFixture:
    def __init__(self, root, source_path="tb/demo_test.svh", revision="synthetic-r1"):
        self.root, self.revision = root, revision
        self.artifacts = []
        def artifact(path, content, kind):
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            item = {"path": path, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "kind": kind, "analyzed_by": ["xverif"]}
            self.artifacts.append(item)
            return item
        self.artifact = artifact
        source = artifact(source_path, "// synthetic testcase\n", "source")
        artifact("runs/build.log", "synthetic compile passed\n", "build-log")
        submit = artifact("tb/submit.json", '{"profiles":{"local":{}}}', "configuration")
        self.trace = traceability_fixture(root, "demo_test", self.artifacts)
        self.manifest = {"schema": "CaseManifest/2", "case_id": "demo_test",
                         "entry": {"kind": "testcase", "name": "demo_test"},
                         "source_files": [{"path": source_path, "sha256": source["sha256"]}],
                         "traceability": self.trace,
                         "submit_profile": {"schema": "SubmitProfileRef/1", "profile_id": "local",
                                            "submit_file": submit["path"], "submit_file_digest": submit["sha256"],
                                            "profile_digest": "b" * 64,
                                            "adapter": {"name": "synthetic-export", "version": "1"}}}
        self.manifest_artifact = artifact("tb/demo.case.json", "{}", "case-manifest")
        self.path = root / "case-evidence.json"
        self.write()

    def write(self):
        self.manifest["case_digest"] = canonical_digest({k: v for k, v in self.manifest.items() if k != "case_digest"})
        target = self.root / self.manifest_artifact["path"]
        target.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.manifest_artifact["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        self.path.write_text(json.dumps({"schema": "TestcaseEvidence/2", "revision": self.revision,
            "tool": "synthetic-export/1", "claim": "case-implementation", "artifacts": self.artifacts,
            "result": {"cases": [{"manifest_digest": self.manifest_artifact["sha256"],
                                   "registered": True, "compiled": True}]}}), encoding="utf-8")
        return self.path

    def validate(self):
        return validate_workstream_evidence(self.write(), "VCASE", "case-implementation", artifact_root=self.root)

    def rtl_only(self):
        self.trace["expected_result"].update(basis_source_ids=["rtl-handshake"], status="rtl-derived-unconfirmed")


class CaseTraceabilityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.case = CaseEvidenceFixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_mixed_sources_and_existing_testcase_list_are_bound(self):
        summary = self.case.validate()
        self.assertTrue(summary["ready"], summary["blockers"])
        record = summary["facts"]["case_records"][0]
        self.assertEqual(record["traceability"], self.case.trace)
        original = self.case.manifest["case_digest"]
        self.case.trace["expected_result"]["description"] = "新的预期行为"
        self.case.write()
        self.assertNotEqual(self.case.manifest["case_digest"], original)

    def test_rtl_only_is_marked_and_cannot_claim_specified(self):
        self.case.rtl_only()
        summary = self.case.validate()
        self.assertFalse(summary["ready"])
        self.assertIn("仅从 RTL 推导", "；".join(summary["blockers"]))
        self.assertEqual(summary["facts"]["case_records"][0]["traceability"]["expected_result"]["status"],
                         "rtl-derived-unconfirmed")
        self.case.trace["expected_result"]["status"] = "specified"
        with self.assertRaisesRegex(EvidenceContractError, "规格已明确"):
            self.case.validate()

    def test_coverage_hole_is_a_versioned_origin_not_an_oracle(self):
        ref = self.case.artifact("history/holes-r1.json", '{"uncovered":["VP-HANDSHAKE"]}', "document")
        self.case.trace["sources"].append({"id": "hole-1", "kind": "coverage-hole",
                                         "path": ref["path"], "sha256": ref["sha256"],
                                         "version": "coverage-r1", "locator": "uncovered / VP-HANDSHAKE"})
        self.assertTrue(self.case.validate()["ready"])
        (self.root / "live-holes.json").write_text('{"uncovered":[]}', encoding="utf-8")
        self.assertTrue(self.case.validate()["ready"])
        self.case.trace["expected_result"]["basis_source_ids"] = ["hole-1"]
        with self.assertRaisesRegex(EvidenceContractError, "不能单独作为预期"):
            self.case.validate()

    def test_changed_missing_unbound_and_unsafe_sources_fail_closed(self):
        source = self.root / self.case.trace["sources"][0]["path"]
        source.write_text("规格已经变化", encoding="utf-8")
        with self.assertRaisesRegex(EvidenceContractError, "摘要变化"):
            self.case.validate()
        source.unlink()
        with self.assertRaisesRegex(EvidenceContractError, "无法读取"):
            self.case.validate()
        self.case.trace["testcase_list"]["path"] = "../other-project.md"
        with self.assertRaisesRegex(EvidenceContractError, "项目内"):
            self.case.validate()

    def test_missing_dangling_and_duplicate_design_references_are_rejected(self):
        for mutation, message in (
            (lambda v: v.pop("sources"), "必需信息"),
            (lambda v: v["expected_result"].update(basis_source_ids=["missing"]), "未登记"),
            (lambda v: v["sources"].append(copy.deepcopy(v["sources"][0])), "编号重复"),
            (lambda v: v["testcase_list"].update(locator="other_case"), "当前 case ID"),
        ):
            value = copy.deepcopy(self.case.trace)
            mutation(value)
            with self.subTest(message=message), self.assertRaisesRegex(CaseTraceabilityError, message):
                validate_traceability(value, "demo_test")

    def test_confirmation_binds_expectation_and_basis_versions_not_listing_status(self):
        self.case.rtl_only()
        trace = self.case.trace
        before = behavior_digest(trace)
        trace["testcase_list"]["sha256"] = "d" * 64
        trace["expected_result"].update(status="confirmed", confirmation_question_id="question:example")
        self.assertEqual(behavior_digest(trace), before)
        trace["sources"][1]["sha256"] = "f" * 64
        self.assertNotEqual(behavior_digest(trace), before)
        del trace["expected_result"]["confirmation_question_id"]
        with self.assertRaisesRegex(CaseTraceabilityError, "确认问题"):
            validate_traceability(trace, "demo_test")

    def test_unverified_confirmation_claim_cannot_pass_standalone_evidence(self):
        self.case.rtl_only()
        self.case.trace["expected_result"].update(status="confirmed", confirmation_question_id="question:invented")
        result = self.case.validate()
        self.assertFalse(result["ready"])
        self.assertIn("不能代替确认", "；".join(result["blockers"]))

    def test_old_manifest_cannot_satisfy_current_traceability_contract(self):
        self.case.manifest["schema"] = "CaseManifest/1"
        del self.case.manifest["traceability"]
        with self.assertRaisesRegex(EvidenceContractError, "CaseManifest/2"):
            self.case.validate()


class CaseTraceabilityWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.fixture = f = workflow_fixtures.CodeWorkflowProfileTest()
        f.setUp()
        self.store, self.root = f.store, f.root
        inputs = ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence",
                  "cap.vstim:reachability-evidence", "cap.vchk:scoreboard-evidence"]
        f.seed(*inputs[1:])
        plan, item = f.design("VCASE", ["case-implementation", "targeted-evidence"], inputs)
        self.plan_node = plan["desired_state"][0]
        state = self.store.node_plan_review_state(self.plan_node["id"])
        self.store.complete_node_plan_review(self.plan_node["id"], state["definition_digest"], "fixture-owner")
        self.delivery = next(n for n in self.store.workstream("VCASE")["desired_state"] if code.is_delivery(n))
        revision = json.loads((self.store.state / "project.json").read_text())["baseline_revision"]
        self.case = CaseEvidenceFixture(self.root, item["output_paths"][0], revision or "synthetic-r1")

    def tearDown(self):
        self.fixture.tearDown()

    def validate(self):
        self.case.write()
        log = self.case.artifact("runs/targeted.log", "synthetic run passed\n", "simulation-log")
        trace = self.case.artifact("runs/trace.txt", "accepted once\n", "transaction-trace")
        analysis = self.case.artifact("runs/analysis.json", json.dumps({
            "adapter_schema_version": 1, "state": "PASS", "blockers": [], "request_sha256": "a" * 64,
            "operation": "synthetic-analysis", "tool_identity": {"state": "PASS"}, "tool": "fixture/1",
        }), "analysis-report")
        # Runtime evidence has its own artifacts, not duplicate registration entries.
        for item in (log, trace, analysis):
            self.case.artifacts.remove(item)
        run_path = self.root / "targeted-evidence.json"
        run_path.write_text(json.dumps({"schema": "TestcaseEvidence/2", "revision": self.case.revision,
            "claim": "targeted-evidence", "tool": "fixture/1", "artifacts": [log, trace, analysis],
            "result": {"runs": [{"case_id": "demo_test", "case_digest": self.case.manifest["case_digest"],
                                 "submit_profile_id": "local", "submit_profile_digest": "b" * 64,
                                 "seed": 7, "iteration": 0, "verdict": "PASS", "uvm_error": 0,
                                 "uvm_fatal": 0, "log_digest": log["sha256"], "checker_engaged": True, "checks": 1}]}}))
        state = self.store.node_plan_review_state(self.delivery["id"])
        criterion = self.delivery["acceptance_criteria"][0]
        report = {"schema": "CodeValidation/1", "node_id": self.delivery["id"], "revision": state["revision"],
                  "input_signature": state["input_signature"], "code_files": state["code_files"],
                  "checked_by": "Project Main Agent", "summary": "合成证据测试，不代表真实仿真",
                  "checks": [{"criterion": criterion, "method": "核对追溯和执行绑定", "expected": "绑定一致",
                              "actual": "合成测试记录", "report": path.name, "claim": claim}
                             for path, claim in ((self.case.path, "case-implementation"), (run_path, "targeted-evidence"))]}
        path = self.root / "code-validation.json"
        path.write_text(json.dumps(report))
        return code.validate(self.store, self.delivery["id"], path.name)

    def question(self, target=None, answer=None):
        question = self.store.ask_agent_question(target or self.delivery["id"],
            "demo_test 是否以列明的 RTL 版本和预期行为作为检查依据？",
            [{"id": "confirm", "label": "确认该行为"}, {"id": "clarify", "label": "需要修订行为"}],
            context=json.dumps(confirmation_context("demo_test", self.case.trace)))
        if answer:
            self.store.answer_agent_question(question["id"], answer, "fixture-owner")
        self.case.trace["expected_result"].update(status="confirmed", confirmation_question_id=question["id"])
        return question

    def test_existing_question_confirmation_then_original_delivery_acceptance(self):
        self.case.rtl_only()
        result = self.validate()
        self.assertFalse(result["ready"])
        self.question(answer="confirm")
        self.assertTrue(self.validate()["ready"])
        state = self.store.node_plan_review_state(self.delivery["id"])
        self.assertTrue(state["can_approve"])
        self.assertFalse(state["completed"])
        self.store.complete_node_plan_review(self.delivery["id"], state["definition_digest"], "fixture-owner")
        self.assertTrue(self.store.node_plan_review_state(self.delivery["id"])["completed"])
        self.assertEqual(len(self.store.workstream("VCASE")["desired_state"]), 2)
        self.case.trace["expected_result"]["description"] = "改成另一个预期"
        self.assertFalse(self.validate()["ready"])
        self.assertFalse(self.store.node_plan_review_state(self.delivery["id"])["can_approve"])

    def test_missing_wrong_node_and_negative_answers_do_not_confirm_behavior(self):
        self.case.rtl_only()
        self.case.trace["expected_result"].update(status="confirmed", confirmation_question_id="question:missing")
        self.assertFalse(self.validate()["ready"])
        self.question(target="VCASE", answer="confirm")
        self.assertFalse(self.validate()["ready"])
        self.question(answer="clarify")
        self.assertFalse(self.validate()["ready"])

    def test_source_change_revokes_delivery_evidence_and_preserves_plan(self):
        self.assertTrue(self.validate()["ready"])
        state = self.store.node_plan_review_state(self.delivery["id"])
        self.store.complete_node_plan_review(self.delivery["id"], state["definition_digest"], "fixture-owner")
        (self.root / self.case.trace["sources"][0]["path"]).write_text("changed specification")
        self.assertFalse(self.store.node_plan_review_state(self.delivery["id"])["completed"])
        self.assertTrue(self.store.node_plan_review_state(self.plan_node["id"])["completed"])

    def test_legacy_validation_receipt_cannot_keep_current_acceptance(self):
        self.assertTrue(self.validate()["ready"])
        state = self.store.node_plan_review_state(self.delivery["id"])
        self.store.complete_node_plan_review(self.delivery["id"], state["definition_digest"], "fixture-owner")
        with self.store.connect() as db:
            row = db.execute("SELECT id,payload_json FROM code_validations WHERE node_id=? ORDER BY rowid DESC LIMIT 1",
                             (self.delivery["id"],)).fetchone()
            value = json.loads(row["payload_json"])
            value["testcase_contract"] = "TestcaseExecution/2"
            db.execute("UPDATE code_validations SET payload_json=? WHERE id=?", (json.dumps(value), row["id"]))
        self.assertFalse(self.store.node_plan_review_state(self.delivery["id"])["completed"])
        self.assertFalse(self.store.node_plan_review_state(self.delivery["id"])["can_approve"])
