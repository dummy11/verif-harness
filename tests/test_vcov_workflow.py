"""VCOV four-node governance and convergence using isolated synthetic evidence."""

import base64
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import urllib.error

from tests import test_vdoc_artifacts as fixtures
from verif_harness import code_workflow as code
from verif_harness.dashboard import dashboard_project_id
from verif_harness.evidence_contracts import validate_workstream_evidence
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
        coverage_config = self.write("verification/config/coverage.toml", "coverage = true\n")
        merge_profile = self.write("verification/config/coverage-merge.toml", "merge = true\n")
        submit_file = self.write("verification/config/submit.toml", "profile = 'coverage-nightly'\n")
        self.submit_profile = {
            "schema": "SubmitProfileRef/1", "profile_id": "coverage-nightly",
            "submit_file": str(submit_file.relative_to(self.root)),
            "submit_file_digest": self.store._digest(submit_file),
            "profile_digest": "b" * 64,
            "adapter": {"name": "synthetic-submit", "version": "1"},
        }
        with self.store.connect() as connection:
            for identifier in (
                "cap.venv:environment-smoke-evidence", "cap.vstim:reachability-evidence",
                "cap.vchk:scoreboard-evidence", "cap.vcase:targeted-evidence", "cap.vreg:executor-ready",
            ):
                self.store.upsert_node(connection, identifier, "capability", identifier, Validity.VALID,
                                       data={"derived": True, "current": {"fixture": identifier}})
        vreg_common = {
            "statement": "形成覆盖率采集所用的回归执行范围", "scope": ["coverage nightly"],
            "work_content": ["运行当前批准的 coverage case"],
            "implementation_approach": ["由 testbench submit profile 执行"],
            "validation_methods": ["核对 batch 和实际 seed"],
            "deliverables": ["回归结果"], "acceptance_criteria": ["运行范围完整"],
            "source_refs": ["coverage-plan.md"], "input_files": ["coverage-plan.md"],
        }
        self.write_json("vreg-source-proposal.json", {
            "schema": "DesiredStateProposal/1", "workstream": "VREG", "nodes": [
                {**copy.deepcopy(vreg_common), "key": "coverage-infrastructure",
                 "implementation_key": "coverage:infrastructure",
                 "role": "regression-infrastructure-plan", "title": "覆盖率回归基础设施",
                 "inputs": ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence"],
                 "output_paths": ["verification/regression/policy.json", "verification/regression/tests.json",
                                  "verification/regression/runner.sh", "verification/regression/collector.json"],
                 "capabilities": ["regression-policy", "executor-ready"]},
                {**copy.deepcopy(vreg_common), "key": "coverage-results",
                 "implementation_key": "coverage:results",
                 "role": "regression-results-plan", "title": "覆盖率回归结果",
                 "inputs": ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence",
                            "cap.vstim:reachability-evidence", "cap.vchk:scoreboard-evidence",
                            "cap.vcase:targeted-evidence", "cap.vcov:coverage-collection",
                            "cap.vreg:coverage:infrastructure"],
                 "input_files": ["coverage-plan.md", self.submit_profile["submit_file"]],
                 "output_paths": ["verification/results/regression/run.log"],
                 "capabilities": ["execution-evidence", "triage-evidence", "fresh-evidence"],
                 "regression_config": {
                     "regression_group": "coverage-nightly",
                     "cases": [{"case_id": "demo_test", "case_digest": "c" * 64}],
                     "submit_profile": self.submit_profile, "seed_mode": "fixed", "seed": 17,
                     "repeat": 1,
                 }},
            ],
        })
        self.store.design_workstream("VREG", None, [], [], [], desired_file="vreg-source-proposal.json")
        self.finish_vreg_infrastructure()
        self.vreg_plan = next(node for node in self.store.workstream("VREG")["desired_state"]
                              if node["role"] == "regression-results-plan")
        self.implementation_config = {
            "schema": "CoverageImplementationConfig/1", "code_coverage_target": "dut",
            "configuration_refs": [{
                "role": "collection", "path": str(coverage_config.relative_to(self.root)),
                "sha256": self.store._digest(coverage_config),
            }],
            "compatible_submit_profile_digests": [self.submit_profile["profile_digest"]],
            "toolchain": [{"role": "coverage", "name": "synthetic-vcs", "version": "1"}],
        }
        self.dut_build_fingerprint = {
            "schema": "DutBuildFingerprint/1", "coverage_target": "dut", "dut_design_id": "fifo",
            "rtl_digest": "1" * 64, "parameter_digest": "2" * 64,
            "macro_digest": "3" * 64, "dut_elaboration_digest": "4" * 64,
        }
        self.collection_config = {
            "schema": "CoverageCollectionConfig/1",
            "regression_sources": [{
                "plan_node_id": self.vreg_plan["id"],
                "plan_revision": self.store.workstream("VREG")["revision"],
                "regression_config_digest": code.config_digest(code.regression_config(self.vreg_plan)),
            }],
            "dut_build_fingerprint": self.dut_build_fingerprint,
            "merge_profile": {
                "path": str(merge_profile.relative_to(self.root)), "sha256": self.store._digest(merge_profile),
                "adapter": {"name": "synthetic-merge", "version": "1"},
                "tool": {"name": "synthetic-verdi", "version": "1"},
            },
        }
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
             "input_files": ["coverage-plan.md", str(coverage_config.relative_to(self.root))],
             "coverage_implementation_config": self.implementation_config,
             "coverage_scope": {
                 "schema": "CoverageScope/1",
                 "code": {"metrics": ["line"], "hierarchy_selectors": ["dut.u_fifo"]},
                 "functional": {"covergroup_selectors": ["tb.env.fifo_cov"],
                                "object_kinds": ["coverpoint-bin"]},
                 "semantic_goal_ids": ["C.DEMO.BOUNDARY"],
             }},
            {**copy.deepcopy(common), "key": "fifo-convergence", "implementation_key": "fifo:convergence",
             "role": "coverage-convergence-plan", "title": "FIFO 覆盖率收敛方案",
             "inputs": ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence",
                        "cap.vstim:reachability-evidence", "cap.vchk:scoreboard-evidence",
                        "cap.vcase:targeted-evidence", "cap.vreg:executor-ready", "cap.vcov:fifo:implementation"],
             "output_paths": ["verification/results/convergence/database.json", "verification/results/convergence/analysis.json"],
             "input_files": ["coverage-plan.md", str(merge_profile.relative_to(self.root))],
             "capabilities": ["coverage-collection-evidence", "hole-analysis-evidence"],
             "coverage_collection_config": self.collection_config},
        ]
        self.design()

    def finish_vreg_infrastructure(self):
        plan = self.store.workstream("VREG")
        node = next(item for item in plan["desired_state"] if item["role"] == "regression-infrastructure-plan")
        state = self.store.node_plan_review_state(node["id"])
        self.store.complete_node_plan_review(node["id"], state["definition_digest"], "fixture-owner")
        self.write_json("verification/regression/policy.json", {"synthetic": True})
        self.write_json("verification/regression/tests.json", {"synthetic": True})
        self.write("verification/regression/runner.sh", "#!/bin/sh\n")
        self.write_json("verification/regression/collector.json", {"synthetic": True})
        self.write("verification/results/infrastructure/build.log", "synthetic build\n")
        delivery = next(item for item in self.store.workstream("VREG")["desired_state"]
                        if item["role"] == "regression-infrastructure-deliverable")
        state = self.store.node_plan_review_state(delivery["id"])
        project = json.loads((self.store.state / "project.json").read_text())
        revision = project.get("baseline_revision") or "fixture-revision"
        checks = []
        evidence = {
            "regression-policy": (
                [self.artifact("verification/regression/policy.json", "document", "human-review"),
                 self.artifact("verification/regression/tests.json", "regression-manifest")],
                None,
            ),
            "executor-ready": (
                [self.artifact("verification/regression/runner.sh", "source"),
                 self.artifact("verification/regression/collector.json", "source"),
                 self.artifact("verification/results/infrastructure/build.log", "build-log")],
                None,
            ),
        }
        for claim in delivery["capabilities"]:
            artifacts = evidence[claim][0]
            result = ({
                "policy_digest": artifacts[0]["sha256"], "manifest_digest": artifacts[1]["sha256"],
                "review_ref": "fixture-review", "seed_policy": "VREG-owned",
                "timeout_policy": "per-case", "rerun_policy": "same-seed",
            } if claim == "regression-policy" else {
                "runner_digest": artifacts[0]["sha256"],
                "collector_digest": artifacts[1]["sha256"], "selftest_passed": True,
            })
            path = self.write_json(f"verification/results/infrastructure/{claim}.json", {
                "schema": "RegressionEvidence/3", "claim": claim, "revision": revision,
                "tool": "synthetic-contract-fixture/1", "artifacts": artifacts, "result": result,
            })
            checks.append({"criterion": delivery["acceptance_criteria"][0], "method": "synthetic",
                           "expected": "ready", "actual": "ready",
                           "report": str(path.relative_to(self.root)), "claim": claim})
        report = self.write_json("verification/results/infrastructure/validation.json", {
            "schema": "CodeValidation/1", "node_id": delivery["id"], "revision": state["revision"],
            "input_signature": state["input_signature"], "code_files": state["code_files"],
            "checked_by": "Project Main Agent", "summary": "synthetic infrastructure", "checks": checks,
        })
        receipt = code.validate(self.store, delivery["id"], str(report.relative_to(self.root)))
        self.assertTrue(receipt["ready"], receipt["blockers"])
        state = self.store.node_plan_review_state(delivery["id"])
        self.store.complete_node_plan_review(delivery["id"], state["definition_digest"], "fixture-owner")

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
        if node.get("role") == "coverage-convergence-plan" and not hasattr(self, "vreg_round"):
            self.prepare_vreg_execution()
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
            "schema": "CoverageObjectInventory/2",
            "scope_digest": code.coverage_scope_digest(self.items[0]),
            "implementation_config_digest": code.config_digest(self.implementation_config),
            "plan_digest": self.store._digest(self.root / "coverage-plan.md"),
            "model_digest": self.store._digest(self.root / "verification/coverage/model.sv"),
            "objects": [
                {"object_key": "C.DEMO.1", "category": "code", "kind": "line",
                 "native_path": "dut.u_fifo/rtl/fifo.sv:42"},
                {"object_key": "C.DEMO.2", "category": "functional", "kind": "coverpoint-bin",
                 "native_path": "tb.env.fifo_cov.empty"},
            ],
        }
        return self.node("coverage-implementation-deliverable")

    def prepare_vreg_execution(self):
        from verif_harness.store import now
        plan = self.store.workstream("VREG")
        source = next(node for node in plan["desired_state"] if node["id"] == self.vreg_plan["id"])
        state = self.store.node_plan_review_state(source["id"])
        if not state["completed"]:
            self.assertTrue(state["can_approve"], state["blockers"])
            self.store.complete_node_plan_review(
                source["id"], state["definition_digest"], "fixture-owner",
            )
        plan = self.store.workstream("VREG")
        source = next(node for node in plan["desired_state"] if node["id"] == self.vreg_plan["id"])
        delivery = next(node for node in plan["desired_state"] if node.get("parent_id") == source["id"])
        with self.store.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            value = code.execution_round(connection, delivery["id"])
            connection.execute(
                "UPDATE regression_execution_rounds SET status='VALIDATED',validated_at=? WHERE id=?",
                (now(), value["id"]),
            )
        self.vreg_delivery = delivery
        with self.store.read_connect() as connection:
            self.vreg_round = code.execution_round(connection, delivery["id"])

    def convergence(self, approve=True):
        if not hasattr(self, "vreg_round"):
            self.prepare_vreg_execution()
        if approve:
            self.approve(self.node("coverage-convergence-plan"))
        binding = code.execution_binding(self.store.workstream("VREG"), self.vreg_delivery, self.vreg_round)
        caselist = self.write("verification/results/convergence/coverage.caselist", "demo_test\n")
        batch = self.write_json("verification/results/convergence/regression-batch.json", {
            "schema": "RegressionBatchManifest/2", "batch_id": "coverage-nightly-local",
            "regression_group": "coverage-nightly", "submit_profile": self.submit_profile,
            "caselist": {"path": str(caselist.relative_to(self.root)), "sha256": self.store._digest(caselist)},
            "seed_mode": "fixed", "seed": 17, "repeat": 1,
            "cases": [{"case_id": "demo_test", "case_digest": "c" * 64}],
            "runs": [{"case_id": "demo_test", "seed": 17, "iteration": 0}],
            "timeout_seconds": 60, "execution_binding": binding,
        })
        shard_db = self.write_json("verification/results/convergence/demo-test.vdb.json", {
            "synthetic": True, "case": "demo_test", "seed": 17,
        })
        shard_manifest = self.write_json("verification/results/convergence/coverage-shards.json", {
            "schema": "CoverageDatabaseShardManifest/1", "execution_binding": binding,
            "regression_config_digest": self.collection_config["regression_sources"][0]["regression_config_digest"],
            "batch_manifest_digest": self.store._digest(batch),
            "dut_build_fingerprint": self.dut_build_fingerprint,
            "shards": [{
                "path": str(shard_db.relative_to(self.root)), "sha256": self.store._digest(shard_db),
                "runs": [{"case_id": "demo_test", "seed": 17, "iteration": 0}],
            }],
        })
        self.write_json("verification/results/convergence/database.json", {"synthetic": True, "hits": [1, 1]})
        merged = self.root / "verification/results/convergence/database.json"
        merge_manifest = self.write_json("verification/results/convergence/coverage-merge.json", {
            **ANALYSIS_RECEIPT,
            "schema": "CoverageMergeManifest/1",
            "collection_config_digest": code.config_digest(self.collection_config),
            "merge_profile_digest": self.collection_config["merge_profile"]["sha256"],
            "dut_build_fingerprint_digest": code.config_digest(self.dut_build_fingerprint),
            "input_database_digests": [self.store._digest(shard_db)],
            "output_database_digest": self.store._digest(merged),
            "adapter": self.collection_config["merge_profile"]["adapter"],
            "merge_tool": self.collection_config["merge_profile"]["tool"],
        })
        self.write_json("verification/results/convergence/analysis.json", {
            **ANALYSIS_RECEIPT, "synthetic": True, "summary": "all items covered",
        })
        self.convergence_artifacts = {
            "caselist": caselist, "batch": batch, "shard_db": shard_db,
            "shard_manifest": shard_manifest, "merge_manifest": merge_manifest,
        }
        return self.node("coverage-convergence-deliverable")

    def artifact(self, name, kind, analyzer="xverif"):
        return {"path": name, "sha256": self.store._digest(self.root / name),
                "kind": kind, "analyzed_by": [analyzer]}

    def provide_exclusions(self, node, content="exclude C.DEMO.2\n", via_cli=False):
        path = self.write("owner-exclusions.el", content)
        if via_cli:
            result = self.cli("code", "provide-exclusions", node["id"],
                              str(path.relative_to(self.root)), "--reviewer", "fixture-owner",
                              "--reason", "已核对 C.DEMO.2 不可达", "--confirm")
        else:
            result = code.provide_coverage_exclusions(
                self.store, node["id"], "fixture-owner", "已核对 C.DEMO.2 不可达",
                confirm=True, source=str(path.relative_to(self.root)),
            )
        return result["approval"]

    @staticmethod
    def waiver(approval):
        return {"id": approval["id"], "reviewer": approval["reviewer"],
                "decision_date": approval["created_at"][:10],
                "rationale": approval["reason"], "status": "Approved"}

    def validate(self, node, manifest=None, items=None, via_cli=False, exporter_digest=None,
                 hole_database=None, include_exclusion_artifact=True):
        stage = "implementation" if code.vcov_stage(node) == "implementation" else "convergence"
        manifest = copy.deepcopy(self.manifest if manifest is None else manifest)
        manifest_file = self.write_json(f"verification/results/{stage}/coverage-objects.json", manifest)
        manifest_artifact = self.artifact(str(manifest_file.relative_to(self.root)), "analysis-report")
        state = self.store.node_plan_review_state(node["id"])
        project = json.loads((self.store.state / "project.json").read_text())
        checks = []
        for claim in node["capabilities"]:
            if claim == "coverage-model":
                artifacts = [self.artifact("verification/coverage/model.sv", "source"),
                             self.artifact("verification/results/implementation/build.log", "build-log"),
                             self.artifact("coverage-plan.md", "document"), manifest_artifact]
                result = {"scope_digest": manifest["scope_digest"],
                          "implementation_config_digest": code.config_digest(self.implementation_config),
                          "plan_digest": manifest["plan_digest"], "model_digest": manifest["model_digest"],
                          "object_count": len(manifest["objects"]), "compiled": True,
                          "coverage_inventory_digest": manifest_artifact["sha256"]}
            elif claim == "coverage-collection":
                artifacts = [self.artifact("verification/coverage/collector.json", "configuration"),
                             self.artifact("verification/results/implementation/build.log", "build-log")]
                result = {"scope_digest": manifest["scope_digest"], "configured": True,
                          "implementation_config_digest": code.config_digest(self.implementation_config),
                          "exporter_digest": exporter_digest or artifacts[0]["sha256"]}
            else:
                database = hole_database if claim == "hole-analysis-evidence" and hole_database \
                    else "verification/results/convergence/database.json"
                merge_path = "verification/results/convergence/coverage-merge.json"
                if claim == "hole-analysis-evidence" and hole_database:
                    original_merge = json.loads((self.root / merge_path).read_text(encoding="utf-8"))
                    original_merge["output_database_digest"] = self.store._digest(self.root / database)
                    merge_path = "verification/results/convergence/coverage-merge-hole.json"
                    self.write_json(merge_path, original_merge)
                artifacts = [self.artifact(database, "coverage-database"),
                             self.artifact("verification/results/convergence/analysis.json", "analysis-report"),
                             self.artifact(merge_path, "analysis-report"),
                             self.artifact(self.collection_config["merge_profile"]["path"], "configuration"),
                             manifest_artifact]
                if claim == "coverage-collection-evidence":
                    artifacts.extend([
                        self.artifact("verification/results/convergence/demo-test.vdb.json", "coverage-database"),
                        self.artifact("verification/results/convergence/coverage-shards.json", "regression-manifest"),
                        self.artifact("verification/results/convergence/regression-batch.json", "regression-manifest"),
                        self.artifact("verification/results/convergence/coverage.caselist", "regression-manifest"),
                        self.artifact(self.submit_profile["submit_file"], "configuration"),
                    ])
                exclusion = state.get("coverage_exclusion", {}).get("current")
                if claim == "hole-analysis-evidence" and exclusion and include_exclusion_artifact:
                    artifacts.append({"path": exclusion["path"], "sha256": exclusion["sha256"],
                                      "kind": "configuration", "analyzed_by": ["xverif"]})
                result = {"coverage_inventory_digest": manifest_artifact["sha256"],
                          "coverage_collection_config_digest": code.config_digest(self.collection_config),
                          "merge_manifest_digest": self.store._digest(
                              self.root / merge_path)}
                if claim == "coverage-collection-evidence":
                    result.update(
                        shard_manifest_digests=[self.store._digest(
                            self.root / "verification/results/convergence/coverage-shards.json")],
                        runs=1, merge_errors=0, stale_shards=0,
                    )
                else:
                    dispositions = items if items is not None else [
                        {"id": item["object_key"], "status": "covered"}
                        for item in manifest["objects"]]
                    holes = []
                    for item in dispositions:
                        if item["status"] == "covered":
                            continue
                        holes.append({"object_key": item["id"], "status": item["status"],
                                      **{key: value for key, value in item.items()
                                         if key not in {"id", "status", "hits", "plan_ref"}}})
                    result.update(
                        required_objects=len(dispositions),
                        covered_objects=sum(item["status"] == "covered" for item in dispositions),
                        excluded_objects=sum(item["status"] == "excluded" for item in dispositions),
                        uncovered_objects=sum(item["status"] == "uncovered" for item in dispositions),
                        holes=holes,
                    )
            evidence_file = self.write_json(f"verification/results/{stage}/{claim}.json", {
                "schema": "CoverageEvidence/3", "claim": claim,
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
        self.prepare_vreg_execution()
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
                         "CoverageConvergence/5")
        current = next(n for n in self.view()["nodes"] if n["id"] == delivery["id"])
        self.assertEqual(current["coverage_scope"], self.items[0]["coverage_scope"])
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
                self.assertEqual(node["coverage_scope"], self.items[0]["coverage_scope"])
        self.assertEqual(self.head("cap.vcov:hole-analysis-evidence")["status"], "VALID")

    def test_convergence_plan_can_be_approved_before_vreg_execution_finishes(self):
        delivery = self.implement()
        self.assertTrue(self.validate(delivery)["ready"])
        self.approve(delivery)
        source_state = self.store.node_plan_review_state(self.vreg_plan["id"])
        self.assertTrue(source_state["can_approve"], source_state["blockers"])
        self.store.complete_node_plan_review(
            self.vreg_plan["id"], source_state["definition_digest"], "fixture-owner",
        )
        vreg = self.store.workstream("VREG")
        result_delivery = next(
            node for node in vreg["desired_state"] if node.get("parent_id") == self.vreg_plan["id"]
        )
        with self.store.read_connect() as connection:
            execution = code.execution_round(connection, result_delivery["id"])
        self.assertEqual(execution["status"], "REQUESTED")
        convergence = self.store.node_plan_review_state(self.node("coverage-convergence-plan")["id"])
        self.assertTrue(convergence["can_approve"], convergence["blockers"])

    def test_multiple_dut_fingerprint_partitions_create_multiple_convergence_deliveries(self):
        other = copy.deepcopy(self.items[1])
        other.update(
            key="fifo-convergence-other-build",
            implementation_key="fifo-other-build:convergence",
            title="FIFO 另一 DUT 构建覆盖率收敛方案",
            output_paths=[
                "verification/results/convergence-other/database.json",
                "verification/results/convergence-other/analysis.json",
            ],
        )
        other["coverage_collection_config"]["dut_build_fingerprint"]["parameter_digest"] = "5" * 64
        self.design([self.items[0], self.items[1], other])
        self.finish_implementation()
        plans = [node for node in self.store.workstream("VCOV")["desired_state"]
                 if node["role"] == "coverage-convergence-plan"]
        self.assertEqual(len(plans), 2)
        for plan in plans:
            self.approve(plan)
        current = self.store.workstream("VCOV")["desired_state"]
        deliveries = [node for node in current if node["role"] == "coverage-convergence-deliverable"]
        self.assertEqual(len(deliveries), 2)
        self.assertEqual({node["parent_id"] for node in deliveries}, {node["id"] for node in plans})
        self.assertEqual(len({
            code.config_digest(node["coverage_collection_config"]["dut_build_fingerprint"])
            for node in plans
        }), 2)

    def test_implementation_only_cannot_finish_vcov(self):
        self.design([self.items[0]])
        self.finish_implementation()
        closure = self.store.evaluate_closure("VCOV")
        self.assertFalse(closure["ready"])
        self.assertTrue(any(a["kind"] == "REFINE_DESIRED_STATE" and "收敛方案" in a["reason"]
                            for a in closure["actions"]))
        progress = self.view()["progress"]
        self.assertEqual((progress["satisfied"], progress["required"]), (2, 2))
        self.assertFalse(progress["scope_complete"])
        self.assertIsNone(progress["percentage"])
        self.assertIn("收敛方案", "；".join(progress["percentage_reasons"]))
        self.assertEqual(progress["stages"][1]["required"], 0)

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

    def test_inventory_must_match_approved_scope_and_current_outputs(self):
        delivery = self.implement()
        missing = {**self.manifest, "scope_digest": "b" * 64}
        receipt = self.validate(delivery, manifest=missing)
        self.assertFalse(receipt["ready"])
        self.assertTrue(any("批准的覆盖范围" in reason for reason in receipt["blockers"]))
        state = self.store.node_plan_review_state(delivery["id"])
        self.assertFalse(state["can_approve"])
        with self.assertRaises(HarnessError):
            self.store.complete_node_plan_review(delivery["id"], state["definition_digest"], "fixture-owner")

    def test_convergence_requires_complete_statistics_and_the_accepted_implementation_inventory(self):
        self.finish_implementation()
        delivery = self.convergence()
        incomplete = [{"id": "C.DEMO.1", "status": "covered", "hits": 1, "plan_ref": "coverage-plan.md"}]
        receipt = self.validate(delivery, items=incomplete)
        self.assertFalse(receipt["ready"])
        self.assertTrue(any("清单数量" in reason for reason in receipt["blockers"]))
        different = {**self.manifest, "objects": list(reversed(self.manifest["objects"]))}
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

    def test_vdb_merge_rejects_different_dut_parameter_or_macro_fingerprint(self):
        self.finish_implementation()
        delivery = self.convergence()
        merge_path = self.root / "verification/results/convergence/coverage-merge.json"
        merge = json.loads(merge_path.read_text(encoding="utf-8"))
        merge["dut_build_fingerprint_digest"] = "d" * 64
        self.write_json(str(merge_path.relative_to(self.root)), merge)
        receipt = self.validate(delivery)
        self.assertFalse(receipt["ready"])
        self.assertTrue(any("parameter" in reason and "禁止 merge" in reason
                            for reason in receipt["blockers"]), receipt["blockers"])

    def test_delivery_rejects_fingerprint_outside_approved_convergence_partition(self):
        self.finish_implementation()
        delivery = self.convergence()
        different = {**self.dut_build_fingerprint, "parameter_digest": "5" * 64}
        shard_path = self.root / "verification/results/convergence/coverage-shards.json"
        shards = json.loads(shard_path.read_text(encoding="utf-8"))
        shards["dut_build_fingerprint"] = different
        self.write_json(str(shard_path.relative_to(self.root)), shards)
        merge_path = self.root / "verification/results/convergence/coverage-merge.json"
        merge = json.loads(merge_path.read_text(encoding="utf-8"))
        merge["dut_build_fingerprint_digest"] = code.config_digest(different)
        self.write_json(str(merge_path.relative_to(self.root)), merge)
        receipt = self.validate(delivery)
        self.assertFalse(receipt["ready"])
        self.assertTrue(any("不同 DUT 指纹必须拆分为独立收敛节点" in reason
                            for reason in receipt["blockers"]), receipt["blockers"])

    def test_different_testbenches_can_merge_when_dut_build_fingerprint_matches(self):
        self.finish_implementation()
        self.convergence()
        other_submit = self.write("verification/config/other-tb-submit.toml", "profile = 'other-tb'\n")
        other_profile = {
            "schema": "SubmitProfileRef/1", "profile_id": "other-tb",
            "submit_file": str(other_submit.relative_to(self.root)),
            "submit_file_digest": self.store._digest(other_submit),
            "profile_digest": "d" * 64,
            "adapter": {"name": "other-testbench-submit", "version": "1"},
        }
        other_binding = {
            "round_id": "round-from-other-testbench",
            "plan_node_id": "workstream:VREG:r1:desired:other-testbench-results",
            "plan_revision": 1, "plan_digest": "e" * 64,
        }
        other_caselist = self.write(
            "verification/results/convergence/other-testbench.caselist", "other_test\n",
        )
        other_batch = self.write_json("verification/results/convergence/other-testbench-batch.json", {
            "schema": "RegressionBatchManifest/2", "batch_id": "other-testbench-batch",
            "regression_group": "other-testbench", "submit_profile": other_profile,
            "caselist": {"path": str(other_caselist.relative_to(self.root)),
                         "sha256": self.store._digest(other_caselist)},
            "seed_mode": "fixed", "seed": 23, "repeat": 1,
            "cases": [{"case_id": "other_test", "case_digest": "f" * 64}],
            "runs": [{"case_id": "other_test", "seed": 23, "iteration": 0}],
            "timeout_seconds": 60, "execution_binding": other_binding,
        })
        other_vdb = self.write_json("verification/results/convergence/other-testbench.vdb.json", {
            "synthetic": True, "testbench": "other", "case": "other_test", "seed": 23,
        })
        other_shards = self.write_json("verification/results/convergence/other-testbench-shards.json", {
            "schema": "CoverageDatabaseShardManifest/1", "execution_binding": other_binding,
            "regression_config_digest": "9" * 64,
            "batch_manifest_digest": self.store._digest(other_batch),
            "dut_build_fingerprint": self.dut_build_fingerprint,
            "shards": [{
                "path": str(other_vdb.relative_to(self.root)), "sha256": self.store._digest(other_vdb),
                "runs": [{"case_id": "other_test", "seed": 23, "iteration": 0}],
            }],
        })
        merge_path = self.root / "verification/results/convergence/coverage-merge.json"
        merge = json.loads(merge_path.read_text(encoding="utf-8"))
        merge["input_database_digests"] = sorted([
            self.store._digest(self.convergence_artifacts["shard_db"]), self.store._digest(other_vdb),
        ])
        self.write_json(str(merge_path.relative_to(self.root)), merge)
        inventory_path = self.write_json("verification/results/convergence/coverage-objects.json", self.manifest)
        artifacts = [
            self.artifact(str(inventory_path.relative_to(self.root)), "analysis-report"),
            self.artifact("verification/results/convergence/database.json", "coverage-database"),
            self.artifact("verification/results/convergence/analysis.json", "analysis-report"),
            self.artifact(str(merge_path.relative_to(self.root)), "analysis-report"),
            self.artifact(self.collection_config["merge_profile"]["path"], "configuration"),
            self.artifact(str(self.convergence_artifacts["shard_db"].relative_to(self.root)),
                          "coverage-database"),
            self.artifact(str(self.convergence_artifacts["shard_manifest"].relative_to(self.root)),
                          "regression-manifest"),
            self.artifact(str(self.convergence_artifacts["batch"].relative_to(self.root)),
                          "regression-manifest"),
            self.artifact(str(self.convergence_artifacts["caselist"].relative_to(self.root)),
                          "regression-manifest"),
            self.artifact(self.submit_profile["submit_file"], "configuration"),
            self.artifact(str(other_vdb.relative_to(self.root)), "coverage-database"),
            self.artifact(str(other_shards.relative_to(self.root)), "regression-manifest"),
            self.artifact(str(other_batch.relative_to(self.root)), "regression-manifest"),
            self.artifact(str(other_caselist.relative_to(self.root)), "regression-manifest"),
            self.artifact(str(other_submit.relative_to(self.root)), "configuration"),
        ]
        evidence_payload = {
            "schema": "CoverageEvidence/3", "claim": "coverage-collection-evidence",
            "revision": "fixture-revision", "tool": "synthetic-contract-fixture/1",
            "artifacts": artifacts,
            "result": {
                "coverage_inventory_digest": self.store._digest(inventory_path),
                "coverage_collection_config_digest": code.config_digest(self.collection_config),
                "shard_manifest_digests": sorted([
                    self.store._digest(self.convergence_artifacts["shard_manifest"]),
                    self.store._digest(other_shards),
                ]),
                "merge_manifest_digest": self.store._digest(merge_path),
                "runs": 2, "merge_errors": 0, "stale_shards": 0,
            },
        }
        evidence = self.write_json(
            "verification/results/convergence/two-testbenches.json", evidence_payload,
        )
        summary = validate_workstream_evidence(
            evidence, "VCOV", "coverage-collection-evidence", artifact_root=self.root,
        )
        self.assertTrue(summary["ready"], summary["blockers"])
        self.assertEqual(
            {batch["submit_profile"]["profile_id"] for batch in summary["facts"]["regression_batches"]},
            {"coverage-nightly", "other-tb"},
        )
        self.assertEqual(len(summary["facts"]["dut_build_fingerprint_digests"]), 1)

        incompatible = json.loads(other_shards.read_text(encoding="utf-8"))
        incompatible["dut_build_fingerprint"]["macro_digest"] = "6" * 64
        self.write_json(str(other_shards.relative_to(self.root)), incompatible)
        other_shard_digest = self.store._digest(other_shards)
        next(item for item in evidence_payload["artifacts"]
             if item["path"] == str(other_shards.relative_to(self.root)))["sha256"] = other_shard_digest
        evidence_payload["result"]["shard_manifest_digests"] = sorted([
            self.store._digest(self.convergence_artifacts["shard_manifest"]), other_shard_digest,
        ])
        self.write_json(str(evidence.relative_to(self.root)), evidence_payload)
        rejected = validate_workstream_evidence(
            evidence, "VCOV", "coverage-collection-evidence", artifact_root=self.root,
        )
        self.assertFalse(rejected["ready"])
        self.assertTrue(any("禁止 merge" in reason for reason in rejected["blockers"]))

    def test_bound_native_digests_must_describe_approved_inputs_and_actual_outputs(self):
        delivery = self.implement()
        log_digest = self.store._digest(self.root / "verification/results/implementation/build.log")
        different = {**self.manifest, "plan_digest": log_digest,
                     "model_digest": self.store._digest(self.root / "coverage-plan.md")}
        receipt = self.validate(delivery, manifest=different, exporter_digest=log_digest)
        self.assertFalse(receipt["ready"])
        for message in ("覆盖计划摘要不属于", "覆盖模型摘要不属于", "覆盖率采集配置摘要不属于"):
            self.assertTrue(any(message in reason for reason in receipt["blockers"]), receipt["blockers"])

    def test_excluded_items_require_one_owner_provided_file_then_agent_validation(self):
        self.finish_implementation()
        delivery = self.convergence()
        unapproved = [{"id": "C.DEMO.1", "status": "covered", "hits": 1, "plan_ref": "coverage-plan.md"},
                      {"id": "C.DEMO.2", "status": "excluded", "hits": 0, "plan_ref": "coverage-plan.md",
                       "waiver": {"id": "not-a-file-approval", "reviewer": "fixture-owner",
                                  "decision_date": "2026-09-30", "rationale": "synthetic declared exception",
                                  "status": "Approved"}}]
        receipt = self.validate(delivery, items=unapproved)
        self.assertFalse(receipt["ready"])
        self.assertTrue(receipt["blockers"])
        self.assertTrue(any("尚未为当前收敛范围提供" in reason for reason in receipt["blockers"]))
        action = next(a for a in self.store.evaluate_closure("VCOV")["actions"] if a["target"] == delivery["id"])
        self.assertEqual(action["kind"], "PROVIDE_COVERAGE_EXCLUSIONS")
        self.assertEqual(action["executor"], "human")
        self.assertFalse(self.store.node_plan_review_state(delivery["id"])["can_approve"])

        approval = self.provide_exclusions(delivery, via_cli=True)
        items = [{"id": "C.DEMO.1", "status": "covered", "hits": 1, "plan_ref": "coverage-plan.md"},
                 {"id": "C.DEMO.2", "status": "excluded", "hits": 0, "plan_ref": "coverage-plan.md",
                  "waiver": self.waiver(approval)}]
        missing_file = self.validate(delivery, items=items, include_exclusion_artifact=False)
        self.assertFalse(missing_file["ready"])
        self.assertTrue(any("没有引用并检查" in reason for reason in missing_file["blockers"]))
        mismatched = copy.deepcopy(items)
        mismatched[1]["waiver"]["id"] = "different-file-approval"
        wrong_reference = self.validate(delivery, items=mismatched)
        self.assertFalse(wrong_reference["ready"])
        self.assertTrue(any("同一个" in reason or "当前 exclude 文件审批记录" in reason
                            for reason in wrong_reference["blockers"]))
        receipt = self.validate(delivery, items=items)
        self.assertTrue(receipt["ready"], receipt["blockers"])
        state = self.store.node_plan_review_state(delivery["id"])
        self.assertEqual(state["validation"]["coverage_exclusion_approval"]["id"], approval["id"])
        self.assertTrue(state["can_approve"])

    def test_dashboard_file_provision_is_the_approval_and_replacement_invalidates_validation(self):
        self.finish_implementation()
        delivery = self.convergence()
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            self.http.post("/api/code/coverage-exclusions", {
                "node": delivery["id"], "reviewer": "http-owner",
                "filename": "fifo.el", "content_base64": base64.b64encode(b"exclude\n").decode(),
                "confirm": False,
            }, self.http.server.write_token)
        self.assertEqual(rejected.exception.code, 400)
        rejected.exception.close()
        response = self.http.post("/api/code/coverage-exclusions", {
            "node": delivery["id"], "reviewer": "http-owner",
            "reason": "已核对排除范围", "filename": "fifo.el",
            "content_base64": base64.b64encode(b"exclude C.DEMO.2\n").decode(),
            "confirm": True,
        }, self.http.server.write_token)["result"]
        approval = response["approval"]
        self.assertEqual(approval["reviewer"], "http-owner")
        with self.http.get(
            "/api/code-exclusion-file?node=" + delivery["id"] + "&path=" + approval["path"]
            + "&digest=" + approval["sha256"],
        ) as preview:
            self.assertIn("C.DEMO.2", json.load(preview)["content"])
        items = [{"id": "C.DEMO.1", "status": "covered", "hits": 1, "plan_ref": "coverage-plan.md"},
                 {"id": "C.DEMO.2", "status": "excluded", "hits": 0, "plan_ref": "coverage-plan.md",
                  "waiver": self.waiver(approval)}]
        self.assertTrue(self.validate(delivery, items=items)["ready"])
        self.assertTrue(self.store.node_plan_review_state(delivery["id"])["validation"]["current"])
        self.write(approval["path"], "tampered after approval\n")
        tampered = self.store.node_plan_review_state(delivery["id"])
        self.assertIsNone(tampered["coverage_exclusion"]["current"])
        self.assertFalse(tampered["validation"]["current"])
        replaced = code.provide_coverage_exclusions(
            self.store, delivery["id"], "fixture-owner", "修订后的排除范围",
            confirm=True, content=b"exclude C.DEMO.2 when reset\n", filename="fifo.el",
        )["approval"]
        self.assertNotEqual(replaced["id"], approval["id"])
        state = self.store.node_plan_review_state(delivery["id"])
        self.assertFalse(state["validation"]["current"])
        self.assertFalse(state["can_approve"])
        self.assertEqual(len(state["coverage_exclusion"]["history"]), 2)

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
        old_delivery = self.node("coverage-convergence-deliverable")
        exclusion = self.provide_exclusions(old_delivery)
        old = self.store.workstream("VCOV")
        old_versions = code.artifacts(self.store, "VCOV")["versions"]
        changed = copy.deepcopy(self.items)
        changed[0]["statement"] += "，并增加当前设计的复位检查"
        self.design(changed)
        current = self.store.workstream("VCOV")
        self.assertEqual(current["revision"], old["revision"] + 1)
        self.assertEqual(len(current["desired_state"]), 2)
        self.assertTrue(all(not self.store.node_plan_review_state(n["id"])["completed"] for n in current["desired_state"]))
        self.assertFalse(self.store.evaluate_closure("VCOV")["ready"])
        self.assertTrue(all(version in code.artifacts(self.store, "VCOV")["versions"] for version in old_versions))
        with self.store.read_connect() as db:
            approval_state = code.coverage_exclusion_state(self.store, db, current, old_delivery)
        self.assertIsNone(approval_state["current"])
        self.assertEqual(approval_state["history"][-1]["id"], exclusion["id"])

    def test_convergence_replan_retains_implementation_approvals_and_capabilities(self):
        self.finish_all()
        original = self.node("coverage-implementation-plan")
        delivery = self.node("coverage-implementation-deliverable")
        states = {node["id"]: self.store.node_plan_review_state(node["id"])
                  for node in (original, delivery)}
        heads = {key: self.head(key)["data"]["current"] for key in (
            "art.code_plan:vcov:fifo:implementation", "art.code:vcov:fifo:implementation",
            "cap.vcov:fifo:implementation", "cap.vcov:coverage-collection",
        )}
        changed = copy.deepcopy(self.items)
        changed[1]["statement"] += "，补充本轮缺口分析"
        current = self.design(changed)
        self.assertEqual(current["revision"], 2)
        for node in (original, delivery):
            self.assertIn(node, current["desired_state"])
            state = self.cli("code", "status", node["id"])
            self.assertEqual((state["revision"], state["workstream_revision"]), (1, 2))
            self.assertEqual(state["current_completion"], states[node["id"]]["current_completion"])
            self.assertEqual(state["definition_digest"], states[node["id"]]["definition_digest"])
            self.assertTrue(state["completed"])
        for key, head in heads.items():
            self.assertEqual(self.head(key)["data"]["current"], head)
        view = self.view()
        self.assertEqual(view["progress"]["satisfied"], 2)
        self.assertEqual(view["progress"]["required"], 4)
        self.assertFalse({original["id"], delivery["id"]} & {a["target"] for a in view["closure"]["actions"]})
        convergence = self.node("coverage-convergence-plan")
        self.assertIn(":r2:", convergence["id"])
        self.assertFalse(self.store.node_plan_review_state(convergence["id"])["completed"])
        self.approve(convergence, http=True)
        self.assertTrue(self.cli("code", "status", convergence["id"])["completed"])
        self.assertTrue(self.validate(delivery, via_cli=True)["ready"])
        self.assertTrue(self.store.node_plan_review_state(delivery["id"])["completed"])

        with self.store.connect() as db:
            db.execute("UPDATE nodes SET status='REVALIDATION_REQUIRED' WHERE id='cap.venv:environment-smoke-evidence'")
        self.assertFalse(self.store.node_plan_review_state(original["id"])["completed"])
        with self.store.connect() as db:
            db.execute("UPDATE nodes SET status='VALID' WHERE id='cap.venv:environment-smoke-evidence'")
        self.assertEqual(self.store.node_plan_review_state(original["id"])["current_completion"],
                         states[original["id"]]["current_completion"])

        # Retention never hides real output or upstream input changes.
        self.write("verification/coverage/model.sv", "module changed; endmodule\n")
        self.assertTrue(self.store.node_plan_review_state(original["id"])["completed"])
        self.assertFalse(self.store.node_plan_review_state(delivery["id"])["completed"])
        self.write("coverage-plan.md", "# Changed coverage requirements\n")
        self.assertFalse(self.store.node_plan_review_state(original["id"])["completed"])

    def test_implementation_approval_and_validation_after_convergence_scope_changes(self):
        original = self.node("coverage-implementation-plan")
        removed = self.design([self.items[0]])
        self.assertEqual(removed["revision"], 2)
        self.assertIn(original, removed["desired_state"])
        self.approve(original, http=True)
        delivery = self.implement(approve=False)
        self.assertIn(":r1:", delivery["id"])
        self.assertTrue(self.validate(delivery, via_cli=True)["ready"])
        added = self.design()
        self.assertEqual(added["revision"], 3)
        self.assertIn(delivery, added["desired_state"])
        self.approve(delivery, http=True)
        state = self.cli("code", "status", delivery["id"])
        self.assertEqual((state["revision"], state["workstream_revision"]), (1, 3))
        self.assertTrue(state["completed"])
        view = self.view()
        self.assertEqual(view["closure"], self.cli("closure", "--workstream", "VCOV"))
        with self.store.connect() as db:
            self.store.upsert_node(db, "cap.venv:environment-smoke-evidence", "capability", "changed environment",
                                   Validity.VALID, data={"derived": True, "current": {"version": "new"}})
        self.assertFalse(self.store.node_plan_review_state(original["id"])["completed"])
        self.assertNotEqual(self.head("cap.vcov:coverage-collection")["status"], "VALID")

    def test_restart_replaces_even_unchanged_coverage_implementation(self):
        delivery = self.finish_implementation()
        before = self.store.workstream("VCOV")
        current = code.design(self.store, "VCOV", "vcov-proposal.json", restart={
            "revision": before["revision"], "reviewer": "fixture-owner", "reason": "explicit restart",
        })
        self.assertEqual(current["revision"], before["revision"] + 1)
        self.assertNotIn(delivery, current["desired_state"])
        self.assertTrue(all(":r2:" in node["id"] for node in current["desired_state"]))
        self.assertTrue(all(not self.store.node_plan_review_state(node["id"])["completed"]
                            for node in current["desired_state"]))

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

        invalid_target = copy.deepcopy(self.items)
        invalid_target[0]["coverage_implementation_config"]["code_coverage_target"] = "testbench"
        with self.assertRaisesRegex(HarnessError, "必须是 dut"):
            self.design(invalid_target)
        missing_partition = copy.deepcopy(self.items)
        missing_partition[1]["coverage_collection_config"].pop("dut_build_fingerprint")
        with self.assertRaisesRegex(HarnessError, "dut_build_fingerprint"):
            self.design(missing_partition)

        unselected_profile = copy.deepcopy(self.items)
        unselected_profile[0]["coverage_implementation_config"][
            "compatible_submit_profile_digests"
        ] = ["a" * 64]
        other_implementation = copy.deepcopy(self.items[0])
        other_implementation.update(
            key="other-implementation",
            implementation_key="other:implementation",
            title="另一覆盖率实现方案",
            output_paths=[
                "verification/coverage/other-model.sv",
                "verification/coverage/other-collector.json",
            ],
        )
        unselected_profile.append(other_implementation)
        with self.assertRaisesRegex(HarnessError, "本收敛方案所选覆盖率实现支持"):
            self.design(unselected_profile)

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
        if node.get("role") == "coverage-convergence-plan" and not hasattr(self, "vreg_round"):
            self.prepare_vreg_execution()
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
        implementation_plan = self.node("coverage-implementation-plan")
        self.browser(implementation_plan, "plan", "覆盖率实现方案")
        implementation = self.implement(approve=False)
        self.assertTrue(self.validate(implementation)["ready"])
        self.browser(implementation, "delivery", "覆盖率实现交付",
                     expectedFileHeading="交付代码", previewText="fixture_coverage")

        convergence_plan = self.node("coverage-convergence-plan")
        self.browser(convergence_plan, "plan", "覆盖率收敛方案")
        convergence = self.convergence(approve=False)
        self.browser(convergence, "exclusions", "覆盖率收敛交付")
        approval = self.store.node_plan_review_state(convergence["id"])["coverage_exclusion"]["current"]
        items = [{"id": "C.DEMO.1", "status": "covered", "hits": 1, "plan_ref": "coverage-plan.md"},
                 {"id": "C.DEMO.2", "status": "excluded", "hits": 0, "plan_ref": "coverage-plan.md",
                  "waiver": self.waiver(approval)}]
        self.assertTrue(self.validate(convergence, items=items)["ready"])
        self.browser(convergence, "delivery", "覆盖率收敛交付",
                     expectedFileHeading="交付文件", previewText="synthetic")
        self.assertTrue(self.store.evaluate_closure("VCOV")["ready"])

    def browser(self, node, phase, expected_role, **extra):
        config = {"url": self.http.url, "project": dashboard_project_id(self.root),
                  "token": self.http.server.write_token, "workstream": "VCOV", "node": node["id"],
                  "phase": phase, "expectedRole": expected_role,
                  "expectedCoverageScope": node.get("coverage_scope"),
                  "expectedCoverageConfig": (node.get("coverage_implementation_config")
                                             or node.get("coverage_collection_config")),
                  **extra}
        process = subprocess.run(["node", str(Path(__file__).with_name("dashboard_code_workflow.cjs"))],
                                 input=json.dumps(config), text=True, capture_output=True, timeout=90,
                                 env=os.environ.copy())
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        if phase != "exclusions":
            self.assertTrue(self.cli("code", "status", node["id"])["completed"])


if __name__ == "__main__":
    unittest.main()
