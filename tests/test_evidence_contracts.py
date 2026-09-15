from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from verif_harness.evidence_contracts import (
    EvidenceContractError, SCHEMAS, validate_workstream_evidence,
)


DIGEST = "a" * 64


class EvidenceContractsTest(unittest.TestCase):
    def validate(self, workstream: str, claim: str, result: dict) -> dict:
        payload = {
            "schema": SCHEMAS[workstream], "claim": claim, "revision": "revision-1",
            "tool": "test-tool/1", "artifacts": [{"path": "results/native.log", "sha256": DIGEST}],
            "result": result,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return validate_workstream_evidence(path, workstream, claim)

    def test_every_standard_claim_has_a_passing_contract(self) -> None:
        cases = {
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
        self.assertIn("Human waiver", summary["blockers"][0])


if __name__ == "__main__":
    unittest.main()
