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
        result = json.loads(json.dumps(result))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def write(relative: str, content: bytes) -> tuple[str, str]:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                return relative, hashlib.sha256(content).hexdigest()

            def bind(kind: str, relative: str, digest: str) -> None:
                match = next((item for item in artifacts if item["kind"] == kind), None)
                if match is None:
                    artifacts.append({
                        "path": relative, "sha256": digest,
                        "kind": kind, "analyzed_by": ["xverif"],
                    })
                else:
                    match.update(path=relative, sha256=digest)

            submit_relative, submit_digest = write(
                "verification/regression/submit.json", b'{"profiles":{"local":{}}}\n',
            )
            profile = {
                "schema": "SubmitProfileRef/1", "profile_id": "local",
                "submit_file": submit_relative, "submit_file_digest": submit_digest,
                "profile_digest": "b" * 64,
                "adapter": {"name": "test-submit-export", "version": "1"},
            }
            if workstream == "VCASE" and claim == "case-implementation":
                source_relative, source_digest = write("verification/tests/demo_test.svh", b"demo\n")
                bind("source", source_relative, source_digest)
                bind("configuration", submit_relative, submit_digest)
                requested = result["cases"][0]
                manifest = {
                    "schema": "CaseManifest/1", "case_id": requested.get("id", "demo_test"),
                    "entry": {"kind": "testcase", "name": requested.get("id", "demo_test")},
                    "source_files": [{"path": source_relative, "sha256": source_digest}],
                    "submit_profile": profile,
                }
                manifest["case_digest"] = hashlib.sha256(json.dumps(
                    manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                manifest_relative, manifest_digest = write(
                    "verification/regression/demo.case.json",
                    json.dumps(manifest).encode("utf-8"),
                )
                bind("case-manifest", manifest_relative, manifest_digest)
                result["cases"] = [{
                    "manifest_digest": manifest_digest,
                    "registered": requested["registered"], "compiled": requested["compiled"],
                }]
            if workstream == "VCASE" and claim == "targeted-evidence":
                result["runs"] = [{
                    "case_id": item.pop("case", item.get("case_id", "demo_test")),
                    "case_digest": item.get("case_digest", "c" * 64),
                    "submit_profile_id": item.get("submit_profile_id", "local"),
                    "submit_profile_digest": item.get("submit_profile_digest", "b" * 64),
                    "iteration": item.get("iteration", 0),
                    "checker_engaged": item.get("checker_engaged", True),
                    "checks": item.get("checks", 1),
                    **{key: value for key, value in item.items() if key != "case_id"},
                } for item in result["runs"]]
            if workstream == "VREG" and claim == "execution-evidence":
                bind("configuration", submit_relative, submit_digest)
                source_results = result["results"]
                case_ids = [item.get("case_id") or item.get("test") for item in source_results]
                caselist_relative, caselist_digest = write(
                    "verification/regression/nightly.caselist",
                    ("\n".join(case_ids) + "\n").encode("utf-8"),
                )
                artifacts.append({
                    "path": caselist_relative, "sha256": caselist_digest,
                    "kind": "regression-manifest", "analyzed_by": ["xverif"],
                })
                batch = {
                    "schema": "RegressionBatchManifest/1", "batch_id": "nightly-local",
                    "regression_group": "nightly", "submit_profile": profile,
                    "caselist": {"path": caselist_relative, "sha256": caselist_digest},
                    "seed": source_results[0]["seed"], "repeat": 1, "timeout_seconds": 60,
                    "cases": [{"case_id": case_id, "case_digest": "c" * 64}
                              for case_id in case_ids],
                }
                batch_relative, batch_digest = write(
                    "verification/regression/nightly.batch.json", json.dumps(batch).encode("utf-8"),
                )
                bind("regression-manifest", batch_relative, batch_digest)
                result = {
                    "golden_required": result["golden_required"],
                    "batch_manifest_digests": [batch_digest],
                    "results": [{
                        "batch_id": "nightly-local", "case_id": case_id,
                        "case_digest": "c" * 64, "submit_profile_id": "local",
                        "submit_profile_digest": "b" * 64, "seed": item["seed"],
                        "iteration": 0, "verdict": item["verdict"],
                        "log_digest": item["log_digest"],
                    } for case_id, item in zip(case_ids, source_results)],
                }
            if workstream == "VREG" and claim == "triage-evidence":
                result["failures"] = [{
                    "batch_id": item.get("batch_id", "nightly-local"),
                    "case_id": item.pop("test", item.get("case_id", "demo_test")),
                    "iteration": item.get("iteration", 0),
                    **{key: value for key, value in item.items() if key != "case_id"},
                } for item in result["failures"]]
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
            payload = {
                "schema": "RegressionEvidence/2" if workstream == "VREG" else SCHEMAS[workstream],
                "claim": claim, "revision": "revision-1",
                "tool": "test-tool/1", "artifacts": artifacts,
                "result": result,
            }
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

    def test_same_case_can_bind_multiple_submit_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def write(relative: str, value: object) -> tuple[str, str]:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                data = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
                path.write_bytes(data)
                return relative, hashlib.sha256(data).hexdigest()

            submit_path, submit_digest = write(
                "tb/submit.json", {"profiles": {"fast": {}, "debug": {}}},
            )
            source_path, source_digest = write("tb/demo_test.svh", b"demo\n")
            artifacts = [
                {"path": source_path, "sha256": source_digest,
                 "kind": "source", "analyzed_by": ["xverif"]},
                {"path": "results/build.log", "sha256": "a" * 64,
                 "kind": "build-log", "analyzed_by": ["xverif"]},
                {"path": submit_path, "sha256": submit_digest,
                 "kind": "configuration", "analyzed_by": ["xverif"]},
            ]
            manifest_digests = []
            for profile_id, profile_digest in (("fast", "b" * 64), ("debug", "d" * 64)):
                manifest = {
                    "schema": "CaseManifest/1", "case_id": "demo_test",
                    "entry": {"kind": "testcase", "name": "demo_test"},
                    "source_files": [{"path": source_path, "sha256": source_digest}],
                    "submit_profile": {
                        "schema": "SubmitProfileRef/1", "profile_id": profile_id,
                        "submit_file": submit_path, "submit_file_digest": submit_digest,
                        "profile_digest": profile_digest,
                        "adapter": {"name": "tb-submit-export", "version": "1"},
                    },
                }
                manifest["case_digest"] = hashlib.sha256(json.dumps(
                    manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                relative, digest = write(f"tb/{profile_id}.case.json", manifest)
                artifacts.append({"path": relative, "sha256": digest,
                                  "kind": "case-manifest", "analyzed_by": ["xverif"]})
                manifest_digests.append(digest)
            evidence = root / "case-evidence.json"
            evidence.write_text(json.dumps({
                "schema": "TestcaseEvidence/2", "claim": "case-implementation",
                "revision": "revision-1", "tool": "tb-submit-export/1", "artifacts": artifacts,
                "result": {"cases": [{"manifest_digest": digest, "registered": True,
                                       "compiled": True} for digest in manifest_digests]},
            }), encoding="utf-8")
            summary = validate_workstream_evidence(
                evidence, "VCASE", "case-implementation", artifact_root=root,
            )
        self.assertTrue(summary["ready"], summary["blockers"])
        self.assertEqual(summary["facts"]["cases"], ["demo_test"])
        self.assertEqual(summary["facts"]["case_count"], 2)

    def test_same_case_set_under_two_profiles_is_two_regression_batches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def write(relative: str, value: object) -> tuple[str, str]:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                data = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
                path.write_bytes(data)
                return relative, hashlib.sha256(data).hexdigest()

            submit_path, submit_digest = write(
                "tb/submit.json", {"profiles": {"fast": {}, "debug": {}}},
            )
            artifacts = [{"path": submit_path, "sha256": submit_digest,
                          "kind": "configuration", "analyzed_by": ["xverif"]}]
            batch_digests = []
            results = []
            for profile_id, profile_digest in (("fast", "b" * 64), ("debug", "d" * 64)):
                caselist_path, caselist_digest = write(
                    f"tb/nightly-{profile_id}.caselist", b"demo_test\n",
                )
                batch_id = f"nightly-{profile_id}"
                batch = {
                    "schema": "RegressionBatchManifest/1", "batch_id": batch_id,
                    "regression_group": "nightly",
                    "submit_profile": {
                        "schema": "SubmitProfileRef/1", "profile_id": profile_id,
                        "submit_file": submit_path, "submit_file_digest": submit_digest,
                        "profile_digest": profile_digest,
                        "adapter": {"name": "tb-submit-export", "version": "1"},
                    },
                    "caselist": {"path": caselist_path, "sha256": caselist_digest},
                    "seed": 17, "repeat": 1, "timeout_seconds": 60,
                    "cases": [{"case_id": "demo_test", "case_digest": "c" * 64}],
                }
                batch_path, batch_digest = write(f"tb/{batch_id}.json", batch)
                artifacts.extend([
                    {"path": caselist_path, "sha256": caselist_digest,
                     "kind": "regression-manifest", "analyzed_by": ["xverif"]},
                    {"path": batch_path, "sha256": batch_digest,
                     "kind": "regression-manifest", "analyzed_by": ["xverif"]},
                ])
                batch_digests.append(batch_digest)
                results.append({
                    "batch_id": batch_id, "case_id": "demo_test", "case_digest": "c" * 64,
                    "submit_profile_id": profile_id, "submit_profile_digest": profile_digest,
                    "seed": 17, "iteration": 0, "verdict": "PASS", "log_digest": "e" * 64,
                })
            artifacts.extend([
                {"path": "results/run.log", "sha256": "e" * 64,
                 "kind": "simulation-log", "analyzed_by": ["xverif"]},
                {"path": "results/analysis.json", "sha256": "f" * 64,
                 "kind": "analysis-report", "analyzed_by": ["xverif"]},
            ])
            evidence = root / "regression-evidence.json"
            evidence.write_text(json.dumps({
                "schema": "RegressionEvidence/2", "claim": "execution-evidence",
                "revision": "revision-1", "tool": "tb-submit-export/1", "artifacts": artifacts,
                "result": {"golden_required": True,
                           "batch_manifest_digests": batch_digests, "results": results},
            }), encoding="utf-8")
            summary = validate_workstream_evidence(
                evidence, "VREG", "execution-evidence", artifact_root=root,
            )
        self.assertTrue(summary["ready"], summary["blockers"])
        self.assertEqual(summary["facts"]["batch_count"], 2)
        self.assertEqual({item["submit_profile"]["profile_id"]
                          for item in summary["facts"]["batches"]}, {"fast", "debug"})


class RegressionRoundEvidenceTest(unittest.TestCase):
    """Synthetic adapter fixtures prove contracts, never simulator execution."""

    @staticmethod
    def binding() -> dict:
        return {
            "round_id": "round-1",
            "plan_node_id": "workstream:VREG:r1:desired:nightly-results",
            "plan_revision": 1, "plan_digest": "1" * 64,
        }

    def execution(
        self, *, mode: str = "random", batch_edit=None, result_edit=None,
        manifest_schema: str = "RegressionBatchManifest/2", tamper: bool = False,
    ) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = []

            def write(relative: str, value: object, kind: str) -> str:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                data = value if isinstance(value, bytes) else json.dumps(value).encode()
                target.write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                artifacts.append({"path": relative, "sha256": digest, "kind": kind,
                                  "analyzed_by": ["xverif"]})
                return digest

            submit_path = "tb/submit.json"
            submit_digest = write(submit_path, {"profiles": {"local": {}}}, "configuration")
            profile = {
                "schema": "SubmitProfileRef/1", "profile_id": "local",
                "submit_file": submit_path, "submit_file_digest": submit_digest,
                "profile_digest": "b" * 64,
                "adapter": {"name": "synthetic-submit-export", "version": "1"},
            }
            caselist = "tb/nightly.caselist"
            caselist_digest = write(caselist, b"demo_test\nedge_test\n", "regression-manifest")
            batch = {
                "schema": manifest_schema, "batch_id": "nightly-local",
                "regression_group": "nightly", "submit_profile": profile,
                "caselist": {"path": caselist, "sha256": caselist_digest},
                "seed_mode": mode, "repeat": 2, "timeout_seconds": 60,
                "cases": [{"case_id": case_id, "case_digest": "c" * 64}
                          for case_id in ("demo_test", "edge_test")],
                "runs": [
                    {"case_id": "demo_test", "seed": "00017", "iteration": 0},
                    {"case_id": "demo_test", "seed": 29, "iteration": 1},
                    {"case_id": "edge_test", "seed": 17, "iteration": 0},
                    {"case_id": "edge_test", "seed": 31, "iteration": 1},
                ],
                "execution_binding": self.binding(),
            }
            if mode == "fixed":
                batch["seed"] = "00017"
                for run in batch["runs"]:
                    run["seed"] = 17
            if batch_edit is not None:
                batch_edit(batch)
            manifest_path = "tb/nightly.batch.json"
            manifest_digest = write(manifest_path, batch, "regression-manifest")
            log_digest = write("results/run.log", b"synthetic adapter input\n", "simulation-log")
            write("results/analysis.json", {
                "adapter_schema_version": 1, "state": "PASS", "blockers": [],
                "request_sha256": "d" * 64, "operation": "synthetic-export",
                "tool_identity": {"state": "PASS", "executed_tool": "synthetic-xverif"},
            }, "analysis-report")
            result = {
                "execution_binding": self.binding(), "golden_required": True,
                "batch_manifest_digests": [manifest_digest],
                "results": [{
                    "batch_id": batch["batch_id"], "case_id": run["case_id"],
                    "case_digest": "c" * 64, "submit_profile_id": "local",
                    "submit_profile_digest": "b" * 64, "seed": run["seed"],
                    "iteration": run["iteration"], "verdict": "PASS", "log_digest": log_digest,
                } for run in batch["runs"]],
            }
            if result_edit is not None:
                result_edit(result)
            if tamper:
                (root / manifest_path).write_text(json.dumps({**batch, "timeout_seconds": 90}))
            path = root / "evidence.json"
            path.write_text(json.dumps({
                "schema": "RegressionEvidence/3", "claim": "execution-evidence",
                "revision": "revision-1", "tool": "synthetic-export/1",
                "artifacts": artifacts, "result": result,
            }))
            return validate_workstream_evidence(path, "VREG", "execution-evidence", artifact_root=root)

    def result_claim(self, claim: str, result: dict) -> dict:
        # Raw artifact admission is tested by ProjectStore separately. This
        # parser fixture preserves every required artifact class and binding.
        artifacts = []
        for index, requirement in enumerate(policy_for("VREG", claim)["requirements"]):
            selected = requirement["alternatives"][0]
            artifacts.append({"path": f"results/synthetic-{index}", "sha256": DIGEST,
                              "kind": selected["kind"], "analyzed_by": [selected["analyzer"]]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps({
                "schema": "RegressionEvidence/3", "claim": claim, "revision": "revision-1",
                "tool": "synthetic-export/1", "artifacts": artifacts, "result": result,
            }))
            return validate_workstream_evidence(path, "VREG", claim)

    def test_random_iterations_export_actual_numeric_seeds_and_current_binding(self) -> None:
        summary = self.execution()
        self.assertTrue(summary["ready"], summary["blockers"])
        facts = summary["facts"]
        self.assertEqual(facts["schema"], "RegressionEvidence/3")
        self.assertEqual(facts["execution_binding"], self.binding())
        self.assertEqual(facts["runs"], facts["run_records"])
        self.assertEqual(len(facts["run_records"]), 4)
        batch = facts["batches"][0]
        self.assertEqual(batch["schema"], "RegressionBatchManifest/2")
        self.assertEqual(batch["seed_mode"], "random")
        self.assertNotIn("seed", batch)
        self.assertEqual([run["seed"] for run in batch["runs"]], ["17", "29", "17", "31"])
        self.assertEqual(batch["submit_profile"]["adapter"],
                         {"name": "synthetic-submit-export", "version": "1"})
        self.assertTrue(all(run["execution_binding"] == self.binding() for run in facts["runs"]))

    def test_fixed_repeat_reuses_normalized_seed(self) -> None:
        summary = self.execution(mode="fixed")
        self.assertTrue(summary["ready"], summary["blockers"])
        self.assertEqual(summary["facts"]["batches"][0]["seed"], "17")
        self.assertEqual({run["seed"] for run in summary["facts"]["runs"]}, {"17"})

    def test_case_sliced_batch_is_self_contained_without_expanding_scope(self) -> None:
        def slice_batch(batch: dict) -> None:
            batch["cases"] = batch["cases"][:1]
            batch["runs"] = batch["runs"][:2]
        summary = self.execution(batch_edit=slice_batch)
        self.assertTrue(summary["ready"], summary["blockers"])
        self.assertEqual(summary["facts"]["batches"][0]["cases"],
                         [{"case_id": "demo_test", "case_digest": "c" * 64}])

    def test_failed_scheduled_run_is_execution_fact_not_a_hidden_rerun(self) -> None:
        summary = self.execution(result_edit=lambda result: result["results"][0].update(verdict="FAIL"))
        self.assertTrue(summary["ready"], summary["blockers"])
        self.assertEqual(len(summary["facts"]["failed_runs"]), 1)
        self.assertEqual(summary["facts"]["failed_runs"][0]["seed"], "17")
        self.assertEqual(summary["facts"]["runs"][0]["verdict"], "FAIL")
        self.assertEqual(len(summary["facts"]["runs"]), 4)

    def test_random_reuse_placeholder_bool_and_zero_seeds_are_rejected(self) -> None:
        for invalid in ("17", "random", "<seed>", True, 0, -1, 1.5):
            with self.subTest(seed=invalid), self.assertRaises(EvidenceContractError):
                self.execution(batch_edit=lambda batch: batch["runs"][1].update(seed=invalid))
        with self.assertRaises(EvidenceContractError):
            self.execution(batch_edit=lambda batch: batch.update(seed=17))
        for invalid in ("random", True, 0):
            with self.subTest(result_seed=invalid), self.assertRaises(EvidenceContractError):
                self.execution(result_edit=lambda result: result["results"][0].update(seed=invalid))

    def test_fixed_run_cannot_change_seed(self) -> None:
        with self.assertRaisesRegex(EvidenceContractError, "同一 seed"):
            self.execution(mode="fixed", batch_edit=lambda batch: batch["runs"][1].update(seed=29))

    def test_manifest_requires_exact_case_times_repeat_and_no_failure_rerun(self) -> None:
        mutations = [
            lambda batch: batch["runs"].pop(),
            lambda batch: batch["runs"].append(dict(batch["runs"][0])),
            lambda batch: batch["runs"][0].update(case_id="other_test"),
            lambda batch: batch["runs"][0].update(iteration=2),
            lambda batch: batch["runs"][0].update(rerun_kind="failure-rerun"),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index), self.assertRaises(EvidenceContractError):
                self.execution(batch_edit=mutation)

    def test_execution_missing_extra_repeated_or_wrong_version_run_fails_closed(self) -> None:
        mutations = [
            lambda result: result["results"].pop(),
            lambda result: result["results"].append({**result["results"][0], "seed": 41}),
            lambda result: result["results"].append(dict(result["results"][0])),
            lambda result: result["results"][0].update(case_digest="d" * 64),
            lambda result: result["results"][0].update(submit_profile_digest="e" * 64),
            lambda result: result["results"][0].update(seed=43),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index):
                summary = self.execution(result_edit=mutation)
                self.assertFalse(summary["ready"])
        with self.assertRaisesRegex(EvidenceContractError, "triage-evidence"):
            self.execution(result_edit=lambda result: result["results"][0].update(rerun_kind="failure-rerun"))

    def test_current_round_and_approved_plan_must_match_actual_manifest(self) -> None:
        for field, value in (("round_id", "round-old"), ("plan_revision", 2),
                             ("plan_digest", "2" * 64),
                             ("plan_node_id", "workstream:VREG:r1:desired:other-results")):
            with self.subTest(field=field):
                summary = self.execution(result_edit=lambda result: result["execution_binding"].update({field: value}))
                self.assertFalse(summary["ready"])
                self.assertTrue(any("执行轮次不一致" in item for item in summary["blockers"]))
        with self.assertRaises(EvidenceContractError):
            self.execution(result_edit=lambda result: result.pop("execution_binding"))

    def test_legacy_batch_and_changed_manifest_are_not_modern_execution(self) -> None:
        with self.assertRaisesRegex(EvidenceContractError, "RegressionBatchManifest/2"):
            self.execution(manifest_schema="RegressionBatchManifest/1")
        with self.assertRaisesRegex(EvidenceContractError, "摘要变化"):
            self.execution(tamper=True)

    def test_failure_rerun_is_separate_same_seed_triage(self) -> None:
        failure = {
            "batch_id": "nightly-local", "case_id": "demo_test", "iteration": 0,
            "original_seed": "00017", "rerun_seed": 17, "rerun_kind": "failure-rerun",
            "classification": "CHECKER", "disposition": "fixed", "rerun_verdict": "PASS",
            "rerun_log_digest": DIGEST,
        }
        result = {"execution_binding": self.binding(), "failures": [failure]}
        summary = self.result_claim("triage-evidence", result)
        self.assertTrue(summary["ready"], summary["blockers"])
        self.assertEqual(summary["facts"]["failures"][0]["rerun_kind"], "failure-rerun")
        self.assertEqual(summary["facts"]["failures"][0]["original_seed"], "17")
        result["failures"][0]["rerun_seed"] = 29
        summary = self.result_claim("triage-evidence", result)
        self.assertFalse(summary["ready"])
        self.assertTrue(any("same-seed" in item for item in summary["blockers"]))
        result["failures"][0]["rerun_kind"] = "planned-repeat"
        with self.assertRaisesRegex(EvidenceContractError, "failure-rerun"):
            self.result_claim("triage-evidence", result)

    def test_result_claims_require_well_formed_binding_but_infrastructure_does_not(self) -> None:
        for claim, result in (("triage-evidence", {"failures": []}),
                              ("fresh-evidence", {"snapshot_revision": "revision-1"})):
            with self.subTest(claim=claim), self.assertRaises(EvidenceContractError):
                self.result_claim(claim, result)
            summary = self.result_claim(claim, {**result, "execution_binding": self.binding()})
            self.assertTrue(summary["ready"], summary["blockers"])
            self.assertEqual(summary["facts"]["execution_binding"], self.binding())
        for invalid in ({**self.binding(), "plan_revision": True},
                        {**self.binding(), "plan_node_id": "workstream:VCOV:r1:desired:plan"},
                        {**self.binding(), "plan_digest": "placeholder"},
                        {**self.binding(), "command": "unsupported"}):
            with self.subTest(binding=invalid), self.assertRaises(EvidenceContractError):
                self.result_claim("fresh-evidence", {"snapshot_revision": "revision-1", "execution_binding": invalid})
        infrastructure = self.result_claim("executor-ready", {
            "runner_digest": DIGEST, "collector_digest": DIGEST, "selftest_passed": True,
        })
        self.assertTrue(infrastructure["ready"])
        self.assertEqual(infrastructure["facts"]["schema"], "RegressionEvidence/3")
        self.assertNotIn("execution_binding", infrastructure["facts"])

    def test_public_examples_describe_one_consistent_placeholder_round(self) -> None:
        evidence_root = Path(__file__).resolve().parents[1] / "skills/verif-harness/evidence"
        batch = json.loads((evidence_root / "regression-batch-manifest.example.json").read_text())
        report = json.loads((evidence_root / "regression-evidence.example.json").read_text())
        for name, value in (("regression-batch-manifest", batch), ("regression-evidence", report)):
            schema = json.loads((evidence_root / f"{name}.schema.json").read_text())
            self.assertEqual(value["schema"], schema["properties"]["schema"]["const"])
            self.assertTrue(value["example_only"])
            self.assertIn("不是", value["example_notice"])
        self.assertEqual(batch["execution_binding"], report["result"]["execution_binding"])
        self.assertEqual(batch["seed_mode"], "random")
        self.assertEqual(len(batch["runs"]), len(batch["cases"]) * batch["repeat"])
        planned = {(run["case_id"], str(run["seed"]), run["iteration"]) for run in batch["runs"]}
        actual = {(run["case_id"], str(run["seed"]), run["iteration"]) for run in report["result"]["results"]}
        self.assertEqual(planned, actual)


if __name__ == "__main__":
    unittest.main()
