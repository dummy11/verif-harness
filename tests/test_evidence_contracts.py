from __future__ import annotations

import hashlib
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
    def validate(
        self, workstream: str, claim: str, result: dict, *, manifest: dict | None = None,
        legacy: bool = False, tamper_manifest: bool = False,
    ) -> dict:
        policy = policy_for(workstream, claim)
        artifacts = []
        for index, item in enumerate(policy["requirements"]):
            selected = item["alternatives"][0]
            artifacts.append({
                "path": f"results/native-{index}", "sha256": DIGEST,
                "kind": selected["kind"], "analyzed_by": [selected["analyzer"]],
            })
        result = dict(result)
        payload = {
            "schema": SCHEMAS[workstream], "claim": claim, "revision": "revision-1",
            "tool": "test-tool/1", "artifacts": artifacts,
            "result": result,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            if workstream == "VCOV" and claim in {
                "coverage-model", "coverage-collection-evidence", "hole-analysis-evidence",
            } and not legacy:
                default_ids = [f"C.DEMO.{index + 1}"
                               for index in range(result.get("planned_items", 1))]
                manifest = manifest or {
                    "schema": "CoverageItemManifest/1", "plan_digest": DIGEST,
                    "model_digest": DIGEST, "planned_item_ids": default_ids,
                    "mapped_item_ids": default_ids,
                }
                manifest_path = root / "results/coverage-items.json"
                manifest_path.parent.mkdir()
                manifest_bytes = json.dumps(manifest).encode("utf-8")
                manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
                manifest_path.write_bytes(manifest_bytes)
                artifacts.append({
                    "path": "results/coverage-items.json", "sha256": manifest_digest,
                    "kind": "analysis-report", "analyzed_by": ["xverif"],
                })
                result["coverage_manifest_digest"] = manifest_digest
                if tamper_manifest:
                    manifest_path.write_text(json.dumps({**manifest, "model_digest": "b" * 64}), encoding="utf-8")
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return validate_workstream_evidence(path, workstream, claim, artifact_root=root)

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

    @staticmethod
    def coverage_manifest(planned: list[str], mapped: list[str] | None = None) -> dict:
        return {
            "schema": "CoverageItemManifest/1", "plan_digest": DIGEST,
            "model_digest": DIGEST, "planned_item_ids": planned,
            "mapped_item_ids": planned if mapped is None else mapped,
        }

    def test_legacy_coverage_reports_remain_readable_but_require_revalidation(self) -> None:
        results = {
            "coverage-model": {
                "plan_digest": DIGEST, "model_digest": DIGEST, "planned_items": 1,
                "mapped_items": 1, "compiled": True,
            },
            "coverage-collection-evidence": {
                "database_ids": ["db-1"], "runs": 1, "merge_errors": 0, "stale_shards": 0,
            },
            "hole-analysis-evidence": {
                "items": [{"id": "C.DEMO.1", "status": "covered", "hits": 1,
                           "plan_ref": "coverage_plan.md"}],
            },
        }
        for claim, result in results.items():
            with self.subTest(claim=claim):
                summary = self.validate("VCOV", claim, result, legacy=True)
                self.assertFalse(summary["ready"])
                self.assertTrue(any("覆盖项清单" in item for item in summary["blockers"]))

    def test_coverage_model_checks_item_identity_not_only_matching_counts(self) -> None:
        summary = self.validate("VCOV", "coverage-model", {
            "plan_digest": DIGEST, "model_digest": DIGEST, "planned_items": 2,
            "mapped_items": 2, "compiled": True,
        }, manifest=self.coverage_manifest(
            ["C.DEMO.1", "C.DEMO.2"], ["C.DEMO.1", "C.OTHER.1"],
        ))
        self.assertFalse(summary["ready"])
        self.assertTrue(any("未实现计划覆盖项：C.DEMO.2" in item for item in summary["blockers"]))
        self.assertTrue(any("未登记计划的覆盖项：C.OTHER.1" in item for item in summary["blockers"]))

    def test_hole_analysis_must_cover_exact_manifest_item_universe(self) -> None:
        manifest = self.coverage_manifest(["C.DEMO.1", "C.DEMO.2"])
        covered = lambda item_id: {
            "id": item_id, "status": "covered", "hits": 1, "plan_ref": "coverage_plan.md",
        }
        for ids in (["C.DEMO.1"], ["C.DEMO.1", "C.OTHER.1"],
                    ["C.DEMO.1", "C.DEMO.2", "C.OTHER.1"],
                    ["C.DEMO.1", "C.DEMO.2", "C.DEMO.2"]):
            with self.subTest(ids=ids):
                summary = self.validate("VCOV", "hole-analysis-evidence", {
                    "items": [covered(item_id) for item_id in ids],
                    "required_item_ids": ids,
                }, manifest=manifest)
                self.assertFalse(summary["ready"])
                self.assertEqual(summary["facts"]["required_item_ids"], ["C.DEMO.1", "C.DEMO.2"])
        complete = self.validate("VCOV", "hole-analysis-evidence", {
            "items": [covered("C.DEMO.1"), covered("C.DEMO.2")],
        }, manifest=manifest)
        self.assertTrue(complete["ready"])
        self.assertTrue(complete["facts"]["coverage_manifest_digest"])

    def test_coverage_manifest_tampering_and_duplicate_ids_are_rejected(self) -> None:
        result = {"items": [{"id": "C.DEMO.1", "status": "covered", "hits": 1,
                             "plan_ref": "coverage_plan.md"}]}
        with self.assertRaisesRegex(EvidenceContractError, "摘要变化"):
            self.validate("VCOV", "hole-analysis-evidence", result, tamper_manifest=True)
        with self.assertRaisesRegex(EvidenceContractError, "重复项"):
            self.validate("VCOV", "hole-analysis-evidence", result,
                          manifest=self.coverage_manifest(["C.DEMO.1", "C.DEMO.1"]))

    def test_coverage_model_manifest_must_match_plan_and_source_version(self) -> None:
        summary = self.validate("VCOV", "coverage-model", {
            "plan_digest": DIGEST, "model_digest": DIGEST, "planned_items": 1,
            "mapped_items": 1, "compiled": True,
        }, manifest={**self.coverage_manifest(["C.DEMO.1"]), "model_digest": "b" * 64})
        self.assertFalse(summary["ready"])
        self.assertTrue(any("版本不一致" in item for item in summary["blockers"]))

    def test_coverage_collection_exposes_controlled_manifest_for_cross_claim_checks(self) -> None:
        summary = self.validate("VCOV", "coverage-collection-evidence", {
            "database_ids": ["db-1"], "runs": 1, "merge_errors": 0, "stale_shards": 0,
        }, manifest=self.coverage_manifest(["C.DEMO.1", "C.DEMO.2"]))
        self.assertTrue(summary["ready"])
        self.assertEqual(summary["facts"]["required_item_ids"], ["C.DEMO.1", "C.DEMO.2"])
        self.assertEqual(summary["facts"]["plan_digest"], DIGEST)

    def test_complete_hole_analysis_still_requires_hits_or_approved_exclusion(self) -> None:
        summary = self.validate("VCOV", "hole-analysis-evidence", {
            "items": [{"id": "C.DEMO.1", "status": "covered", "hits": 0,
                       "plan_ref": "coverage_plan.md"}],
        })
        self.assertFalse(summary["ready"])
        approved = self.validate("VCOV", "hole-analysis-evidence", {
            "items": [{"id": "C.DEMO.1", "status": "excluded", "hits": 0,
                       "plan_ref": "coverage_plan.md", "waiver": {
                           "id": "waiver-1", "reviewer": "alice", "decision_date": "2026-09-15",
                           "rationale": "unreachable", "status": "Approved",
                       }}],
        })
        self.assertTrue(approved["ready"])

    def test_hole_analysis_retains_waiver_binding_for_store_verification(self) -> None:
        waiver = {
            "id": "waive-1", "reviewer": "alice", "decision_date": "2026-09-15",
            "rationale": "unreachable", "status": "Approved", "item_id": "C.DEMO.1",
            "revision": "revision-1", "review_ref": "review-1",
        }
        summary = self.validate("VCOV", "hole-analysis-evidence", {
            "items": [{"id": "C.DEMO.1", "status": "excluded", "hits": 0,
                       "plan_ref": "coverage_plan.md", "waiver": waiver}],
        })
        self.assertTrue(summary["ready"])
        self.assertEqual(summary["facts"]["items"][0]["waiver"], waiver)
        collector = self.validate("VCOV", "coverage-collection", {
            "configured": True, "exporter_digest": DIGEST,
        })
        self.assertEqual(collector["facts"]["exporter_digest"], DIGEST)

    def test_uncovered_item_requires_an_explicit_feedback_route(self) -> None:
        summary = self.validate("VCOV", "hole-analysis-evidence", {
            "items": [{"id": "C.DEMO.2", "status": "uncovered", "hits": 0,
                       "plan_ref": "coverage_plan.md"}],
        })
        self.assertFalse(summary["ready"])
        self.assertTrue(any("责任工作流" in item for item in summary["blockers"]))
        routed = self.validate("VCOV", "hole-analysis-evidence", {
            "items": [{"id": "C.DEMO.2", "status": "uncovered", "hits": 0,
                       "plan_ref": "coverage_plan.md", "responsible_workstream": "VSTIM",
                       "next_action": "补充 backpressure 激励场景"}],
        })
        self.assertEqual(routed["facts"]["items"][0]["responsible_workstream"], "VSTIM")
        self.assertIn("尚未覆盖", routed["blockers"][0])

    def test_unclosed_regression_failure_requires_an_explicit_feedback_route(self) -> None:
        summary = self.validate("VREG", "triage-evidence", {
            "failures": [{"test": "demo_test", "original_seed": 7, "rerun_seed": 7,
                          "classification": "STIMULUS", "disposition": "replan",
                          "rerun_verdict": "FAIL", "rerun_log_digest": DIGEST,
                          "responsible_workstream": "VSTIM",
                          "next_action": "修正约束并用同 seed 重跑"}],
        })
        self.assertFalse(summary["ready"])
        self.assertEqual(summary["facts"]["failures"][0]["responsible_workstream"], "VSTIM")


if __name__ == "__main__":
    unittest.main()
