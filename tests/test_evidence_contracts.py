from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from verif_harness.evidence_contracts import (
    EvidenceContractError, SCHEMAS, validate_workstream_evidence,
)
from verif_harness.evidence_policy import policy_for


DIGEST = "a" * 64


class EvidenceContractsTest(unittest.TestCase):
    def validate(self, workstream: str, claim: str, result: dict) -> dict:
        policy = policy_for(workstream, claim)
        artifacts = []
        for index, item in enumerate(policy["requirements"]):
            selected = item["alternatives"][0]
            artifacts.append({
                "path": f"results/native-{index}", "sha256": DIGEST,
                "kind": selected["kind"], "analyzed_by": [selected["analyzer"]],
            })
        payload = {
            "schema": SCHEMAS[workstream], "claim": claim, "revision": "revision-1",
            "tool": "test-tool/1", "artifacts": artifacts,
            "result": result,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return validate_workstream_evidence(path, workstream, claim)

    def test_every_standard_claim_has_a_passing_contract(self) -> None:
        cases = {
            ("VENV", "interface-ready"): {
                "interfaces": [{"id": "dut_if", "connected": True,
                                "virtual_interface_set": True, "source_digest": DIGEST}],
            },
            ("VENV", "clock-reset-ready"): {
                "clocks": [{"id": "clk", "configured": True}],
                "resets": [{"id": "rst_n", "configured": True}],
                "implementation_digest": DIGEST,
            },
            ("VENV", "topology-ready"): {
                "components": [{"id": "env", "kind": "uvm_env", "constructed": True,
                                "connected": True}],
                "topology_digest": DIGEST,
            },
            ("VENV", "build-ready"): {
                "compiled": True, "elaborated": True, "errors": 0,
                "build_log_digest": DIGEST, "environment_digest": DIGEST,
            },
            ("VENV", "run-ready"): {
                "selftest_passed": True, "clean_exit": True,
                "failure_propagated": True, "command_digest": DIGEST,
                "collector_digest": DIGEST,
            },
            ("VENV", "observation-ready"): {
                "points": [{"id": "input_monitor", "boundary": "dut-input", "connected": True}],
                "implementation_digest": DIGEST,
            },
            ("VENV", "environment-smoke-evidence"): {
                "clock_edges": 10, "reset_assertions": 1, "reset_deassertions": 1,
                "observations": 2, "errors": 0, "fatals": 0,
                "timeout": False, "clean_exit": True,
                "environment_digest": DIGEST, "log_digest": DIGEST,
            },
            ("VSTIM", "transaction-contract"): {
                "contract_ref": "verification_plan.md#transactions", "contract_digest": DIGEST,
                "review_ref": "review-1", "transactions": [
                    {"id": "input_txn", "direction": "input", "fields": ["data"],
                     "handshake": "valid && ready"},
                ],
            },
            ("VSTIM", "stimulus-implementation"): {
                "required_features": ["VF.INPUT.1"], "components": [
                    {"id": "input_sequence", "kind": "sequence", "features": ["VF.INPUT.1"],
                     "compiled": True, "registered": True, "source_digest": DIGEST},
                ],
            },
            ("VSTIM", "corner-scenarios"): {
                "required_scenarios": ["backpressure"],
                "mappings": [{"scenario": "backpressure", "generator": "input_sequence"}],
            },
            ("VCHK", "compare-policy"): {
                "policy_ref": "verification_plan.md#compare", "policy_digest": DIGEST, "review_ref": "review-1",
            },
            ("VCHK", "reference-model"): {
                "configured": True, "compiled": True, "implementation_digest": DIGEST,
            },
            ("VCHK", "scoreboard"): {
                "configured": True, "compiled": True, "implementation_digest": DIGEST,
            },
            ("VCHK", "assertions"): {
                "planned": 1, "compiled": 1, "bound": 1, "implementation_digest": DIGEST,
            },
            ("VCHK", "reference-model-evidence"): {
                "engaged": True, "comparisons": 2, "mismatches": 0, "residual": 0,
                "implementation_digest": DIGEST,
            },
            ("VCHK", "scoreboard-evidence"): {
                "engaged": True, "comparisons": 2, "mismatches": 0, "residual": 0,
                "implementation_digest": DIGEST,
            },
            ("VCHK", "assertion-evidence"): {
                "assertions": [{"id": "A.DEMO.1", "compiled": True, "bound": True,
                                "attempts": 2, "failures": 0, "vacuous": False, "plan_ref": "assertion_plan.md"}],
            },
            ("VCOV", "coverage-model"): {
                "plan_digest": DIGEST, "model_digest": DIGEST, "planned_items": 2,
                "mapped_items": 2, "compiled": True,
            },
            ("VCOV", "coverage-collection"): {"configured": True, "exporter_digest": DIGEST},
            ("VCOV", "coverage-collection-evidence"): {
                "database_ids": ["db-1"], "runs": 1, "merge_errors": 0, "stale_shards": 0,
            },
            ("VCOV", "hole-analysis-evidence"): {
                "items": [{"id": "C.DEMO.1", "status": "covered", "hits": 1,
                           "plan_ref": "coverage_plan.md"}],
            },
            ("VCASE", "case-matrix"): {
                "required_features": ["F.DEMO.1"],
                "mappings": [{"feature": "F.DEMO.1", "cases": ["demo_test"]}],
            },
            ("VCASE", "case-implementation"): {
                "cases": [{"id": "demo_test", "source_digest": DIGEST,
                           "registered": True, "compiled": True}],
            },
            ("VCASE", "targeted-evidence"): {
                "runs": [{"case": "demo_test", "seed": 1, "verdict": "PASS",
                          "uvm_error": 0, "uvm_fatal": 0, "log_digest": DIGEST}],
            },
            ("VREG", "regression-policy"): {
                "policy_digest": DIGEST, "manifest_digest": DIGEST, "review_ref": "review-1",
                "seed_policy": "explicit batch seed", "timeout_policy": "per-test timeout",
                "rerun_policy": "same-seed failed-only rerun",
            },
            ("VREG", "executor-ready"): {
                "runner_digest": DIGEST, "collector_digest": DIGEST, "selftest_passed": True,
            },
            ("VREG", "execution-evidence"): {
                "golden_required": True, "batch_seed": "1", "manifest_digest": DIGEST,
                "results": [{"test": "demo_test", "seed": 1, "verdict": "PASS", "log_digest": DIGEST}],
            },
            ("VREG", "triage-evidence"): {"failures": []},
            ("VREG", "fresh-evidence"): {
                "snapshot_revision": "revision-1",
            },
        }
        for (workstream, claim), result in cases.items():
            with self.subTest(workstream=workstream, claim=claim):
                self.assertTrue(self.validate(workstream, claim, result)["ready"])

    def test_semantic_blockers_derive_failure(self) -> None:
        summary = self.validate("VCHK", "scoreboard-evidence", {
            "engaged": True, "comparisons": 1, "mismatches": 1, "residual": 0,
            "implementation_digest": DIGEST,
        })
        self.assertFalse(summary["ready"])
        self.assertTrue(summary["blockers"])

    def test_missing_required_artifact_or_analyzer_blocks_admission(self) -> None:
        payload = {
            "schema": "CheckingEvidence/1", "claim": "scoreboard-evidence",
            "revision": "revision-1", "tool": "test-tool/1",
            "artifacts": [{
                "path": "results/run.log", "sha256": DIGEST,
                "kind": "simulation-log", "analyzed_by": ["xverif"],
            }],
            "result": {"engaged": True, "comparisons": 2, "mismatches": 0,
                       "residual": 0, "implementation_digest": DIGEST},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            summary = validate_workstream_evidence(path, "VCHK", "scoreboard-evidence")
        self.assertFalse(summary["ready"])
        self.assertTrue(any("波形数据库" in item for item in summary["blockers"]))
        self.assertTrue(any("结构化分析结果" in item for item in summary["blockers"]))

    def test_environment_smoke_requires_clock_reset_observation_and_clean_exit(self) -> None:
        summary = self.validate("VENV", "environment-smoke-evidence", {
            "clock_edges": 0, "reset_assertions": 1, "reset_deassertions": 0,
            "observations": 0, "errors": 1, "fatals": 0,
            "timeout": True, "clean_exit": False,
            "environment_digest": DIGEST, "log_digest": DIGEST,
        })
        self.assertFalse(summary["ready"])
        self.assertGreaterEqual(len(summary["blockers"]), 5)

    def test_claim_digest_must_bind_to_native_artifact(self) -> None:
        with self.assertRaises(EvidenceContractError):
            self.validate("VCHK", "scoreboard-evidence", {
                "engaged": True, "comparisons": 1, "mismatches": 0, "residual": 0,
                "implementation_digest": "b" * 64,
            })

    def test_boolean_seed_is_rejected(self) -> None:
        with self.assertRaises(EvidenceContractError):
            self.validate("VCASE", "targeted-evidence", {
                "runs": [{"case": "demo_test", "seed": False, "verdict": "PASS",
                          "uvm_error": 0, "uvm_fatal": 0, "log_digest": DIGEST}],
            })

    def test_coverage_exclusion_requires_approved_human_waiver(self) -> None:
        summary = self.validate("VCOV", "hole-analysis-evidence", {
            "items": [{"id": "C.DEMO.1", "status": "excluded", "hits": 0,
                       "plan_ref": "coverage_plan.md",
                       "waiver": {"id": "waiver-1", "reviewer": "alice",
                                  "decision_date": "2026-09-15", "rationale": "unreachable",
                                  "status": "Pending"}}],
        })
        self.assertFalse(summary["ready"])
        self.assertIn("负责人例外评审", summary["blockers"][0])


if __name__ == "__main__":
    unittest.main()
