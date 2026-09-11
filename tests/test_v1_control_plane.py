from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/verif_harness.py"


class V1ControlPlaneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "rtl").mkdir()
        (self.root / "rtl/dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def invoke(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["GIT_AUTHOR_NAME"] = "test-user"
        environment.pop("USER", None)
        return subprocess.run(
            [sys.executable, str(CLI), *arguments, "--project-root", str(self.root)],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
        )

    def run_cli(self, *arguments: str, expected: int = 0) -> dict:
        result = self.invoke(*arguments)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout) if result.stdout else {}

    def bootstrap(self) -> dict:
        return self.run_cli(
            "bootstrap", "--runtime", "none", "--rtl-root", "rtl",
            "--verif-root", "verification", "--dut-top", "dut", "--dut-top-file", "rtl/dut.sv",
        )

    def design(self, workstream: str = "VDOC", *extra: str) -> dict:
        return self.run_cli("plan", "design", "--workstream", workstream, *extra)

    def test_bootstrap_creates_minimal_model_without_verification_semantics(self) -> None:
        payload = self.bootstrap()
        state = self.root / ".verif-harness"
        self.assertEqual(payload["rtl_roots"], ["rtl"])
        self.assertTrue((state / "model.sqlite3").is_file())
        self.assertTrue((state / "model.md").is_file())
        instructions = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("verif-harness 项目合同", instructions)
        self.assertIn("DUT top: `dut`", instructions)
        self.assertIn("VDOC 文档路由尚未建立", instructions)
        self.assertIn("不采用 Stage 或 Spec Kit", instructions)
        with sqlite3.connect(state / "model.sqlite3") as connection:
            version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
            workstreams = connection.execute("SELECT COUNT(*) FROM workstreams").fetchone()[0]
        self.assertEqual(version, "2")
        self.assertEqual(workstreams, 0)

    def test_bootstrap_requires_explicit_dut_identity(self) -> None:
        result = self.invoke("bootstrap", "--runtime", "none", "--rtl-root", "rtl")
        self.assertEqual(result.returncode, 2)
        self.assertIn("rtl root、dut top 和 dut top file", result.stderr)

    def test_bootstrap_preserves_existing_agents_content_and_refresh_is_idempotent(self) -> None:
        instructions = self.root / "AGENTS.md"
        instructions.write_text("# Team policy\n\nKeep this.\n", encoding="utf-8")
        self.bootstrap()
        self.run_cli("bootstrap", "--refresh")
        source = instructions.read_text(encoding="utf-8")
        self.assertIn("# Team policy", source)
        self.assertIn("Keep this.", source)
        self.assertEqual(source.count("BEGIN verif-harness managed project instructions"), 1)
        self.assertEqual(source.count("END verif-harness managed project instructions"), 1)

    def test_bootstrap_refuses_implicit_overwrite(self) -> None:
        self.bootstrap()
        result = self.invoke("bootstrap")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--refresh", result.stderr)

    def test_bootstrap_can_project_complete_dut_identity(self) -> None:
        payload = self.run_cli(
            "bootstrap", "--runtime", "none", "--rtl-root", "rtl", "--verif-root", "verification",
            "--dut-top", "dut", "--dut-top-file", "rtl/dut.sv",
        )
        config = json.loads((self.root / ".harness-config.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["dut"]["top_module"], "dut")
        self.assertEqual(config["rtl"]["top_file"], "rtl/dut.sv")
        self.assertEqual(config["verif"]["docs_root"], "verification/docs")

    def test_bootstrap_accepts_explicit_external_readonly_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as external_directory:
            external = Path(external_directory)
            rtl = external / "rtl"
            rtl.mkdir()
            top = rtl / "external_dut.sv"
            top.write_text("module external_dut; endmodule\n", encoding="utf-8")
            specification = external / "spec.md"
            specification.write_text("# External read-only specification\n", encoding="utf-8")
            original_top = top.read_bytes()
            original_specification = specification.read_bytes()
            payload = self.run_cli(
                "bootstrap", "--runtime", "none", "--rtl-root", str(rtl),
                "--docs-root", str(specification), "--verif-root", "verification",
                "--dut-top", "external_dut", "--dut-top-file", str(top),
            )
            self.assertEqual(payload["rtl_roots"], [str(rtl.resolve())])
            self.assertEqual(payload["docs_roots"], [str(specification.resolve())])
            self.assertEqual(payload["dut"]["top_file"], str(top.resolve()))
            inventory = json.loads((self.root / ".verif-harness/inventory.json").read_text(encoding="utf-8"))
            self.assertIn(str(top.resolve()), {item["path"] for item in inventory})
            self.assertIn(str(specification.resolve()), {item["path"] for item in inventory})
            config = json.loads((self.root / ".harness-config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["rtl"]["root"], str(rtl.resolve()))
            refreshed = self.run_cli("bootstrap", "--refresh")
            self.assertEqual(refreshed["rtl_roots"], [str(rtl.resolve())])
            changed = self.run_cli("changed", str(top))
            self.assertEqual(changed["subject"], f"file:{top.resolve()}")
            unrelated = external / "unrelated.txt"
            unrelated.write_text("not declared\n", encoding="utf-8")
            refused = self.invoke("changed", str(unrelated))
            self.assertEqual(refused.returncode, 2)
            self.assertIn("已声明的只读 RTL/spec 输入", refused.stderr)
            external_output = self.invoke("plan", "VDOC", "--document-root", str(external / "generated"))
            self.assertEqual(external_output.returncode, 2)
            self.assertIn("路径必须位于项目内", external_output.stderr)
            self.assertEqual(top.read_bytes(), original_top)
            self.assertEqual(specification.read_bytes(), original_specification)

    def test_bootstrap_requires_top_file_to_belong_to_declared_rtl_root(self) -> None:
        with tempfile.TemporaryDirectory() as external_directory:
            top = Path(external_directory) / "other.sv"
            top.write_text("module other; endmodule\n", encoding="utf-8")
            result = self.invoke(
                "bootstrap", "--runtime", "none", "--rtl-root", "rtl",
                "--verif-root", "verification", "--dut-top", "other",
                "--dut-top-file", str(top),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("某个已声明的 RTL root", result.stderr)

    def test_planner_uses_detailed_template_and_current_knowledge_context(self) -> None:
        self.bootstrap()
        plan = self.design("VCHK")
        self.assertEqual(plan["workstream"], "VCHK")
        self.assertEqual(plan["lifecycle"], "REVIEW")
        self.assertGreaterEqual(len(plan["desired_state"]), 4)
        self.assertGreater(plan["planning_context"]["model_summary"]["node_count"], 0)
        self.assertTrue(plan["planning_context"]["model_excerpt"]["nodes"])
        self.assertEqual(len(plan["questions_for_human"]), len(plan["desired_state"]))
        self.assertEqual(plan["auto_closure"]["actions"][0]["executor"], "human")
        self.assertTrue((self.root / ".verif-harness/workstreams/vchk/desired-state.json").is_file())
        self.assertTrue((self.root / ".verif-harness/workstreams/vchk/plan.md").is_file())

    def test_workstream_is_reentrant_and_revisioned(self) -> None:
        self.bootstrap()
        first = self.design("VSTIM", "--desired", "基础激励可达")
        second = self.design("VSTIM", "--desired", "补充 backpressure 场景")
        self.assertEqual(second["revision"], first["revision"] + 1)
        model = self.run_cli("model", "show")
        status = {node["id"]: node["status"] for node in model["nodes"]}
        self.assertEqual(status[first["desired_state"][0]["id"]], "STALE")
        self.assertEqual(status[second["desired_state"][0]["id"]], "UNKNOWN")

    def test_vdoc_materializes_missing_semantic_documents_without_approving_them(self) -> None:
        self.bootstrap()
        readonly_source = self.root / "rtl/dut.sv"
        original = readonly_source.read_bytes()
        plan = self.run_cli("plan", "VDOC")
        restored = self.run_cli("status", "VDOC")["plan"]
        expected = {"verification_workflow.md", "verification_plan.md", "feature_matrix.md", "tb_architecture.md",
                    "reference_model_spec.md", "coverage_plan.md", "assertion_plan.md", "testcase_list.md"}
        self.assertEqual({row["document"]["filename"] for row in restored["desired_state"]}, expected)
        for row in restored["desired_state"]:
            self.assertTrue((ROOT / "skills/verif-harness" / row["document"]["template"]).is_file())
            self.assertEqual(self.run_cli("inspect", row["id"])["nodes"][0]["status"], "UNKNOWN")
        self.assertEqual(restored["desired_state"], plan["desired_state"])
        optional = plan["document_guidance"]["optional_documents"][0]
        self.assertNotIn(optional["filename"], expected)
        self.assertTrue((ROOT / "skills/verif-harness" / optional["template"]).is_file())
        self.assertEqual(plan["document_guidance"]["document_root"], "verification/docs/verification")
        self.assertEqual(len(plan["document_guidance"]["documents"]), 8)
        instructions = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("VDOC 文档根目录：`verification/docs/verification`", instructions)
        self.assertIn("verification_workflow.md", instructions)
        document_root = self.root / "verification/docs/verification"
        self.assertEqual({path.name for path in document_root.glob("*.md")}, expected)
        status = self.run_cli("docs", "status")
        self.assertEqual(len(status["documents"]), 8)
        self.assertTrue(all(row["status"] == "REVIEW_REQUIRED" for row in status["documents"]))
        self.assertTrue(all(not row["content_changed"] for row in status["documents"]))
        premature = self.invoke("docs", "review", "verification_plan.md", "--reviewer", "alice")
        self.assertEqual(premature.returncode, 2)
        self.assertIn("approve 当前 VDOC desired-state revision", premature.stderr)
        self.assertEqual(readonly_source.read_bytes(), original)
        self.assertEqual(self.invoke("freeze", "VDOC").returncode, 2)

    def test_existing_semantic_document_is_preserved_and_digest_change_requires_review(self) -> None:
        self.bootstrap()
        root = self.root / "verification/docs/verification"
        root.mkdir(parents=True)
        plan_path = root / "verification_plan.md"
        plan_path.write_text("# Project-specific verification plan\n", encoding="utf-8")
        self.run_cli("plan", "VDOC")
        self.assertEqual(plan_path.read_text(encoding="utf-8"), "# Project-specific verification plan\n")
        plan_path.write_text("# Project-specific verification plan\n\nUpdated semantics.\n", encoding="utf-8")
        before = self.run_cli("docs", "status", "verification_plan.md")["documents"][0]
        self.assertTrue(before["content_changed"])
        synced = self.run_cli("docs", "sync", "verification_plan.md")
        self.assertEqual(synced["changed"], ["verification/docs/verification/verification_plan.md"])
        after = self.run_cli("docs", "status", "verification_plan.md")["documents"][0]
        self.assertEqual(after["semantic_revision"], 2)
        self.assertEqual(after["status"], "REVIEW_REQUIRED")
        rendered = self.invoke("docs", "render", "verification_plan.md")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn("### Revision Log", rendered.stdout)
        self.assertIn("语义正文内容摘要发生变化", rendered.stdout)

    def test_missing_document_change_is_idempotent_and_restore_requires_review(self) -> None:
        self.bootstrap()
        self.run_cli("plan", "VDOC")
        path = self.root / "verification/docs/verification/verification_plan.md"
        original = path.read_text(encoding="utf-8")
        path.unlink()
        first = self.run_cli("docs", "sync", "verification_plan.md")
        self.assertEqual(first["missing"], ["verification/docs/verification/verification_plan.md"])
        with sqlite3.connect(self.root / ".verif-harness/model.sqlite3") as connection:
            first_events = connection.execute(
                "SELECT COUNT(*) FROM events WHERE kind='delete' AND subject='file:verification/docs/verification/verification_plan.md'"
            ).fetchone()[0]
        self.run_cli("docs", "sync", "verification_plan.md")
        with sqlite3.connect(self.root / ".verif-harness/model.sqlite3") as connection:
            second_events = connection.execute(
                "SELECT COUNT(*) FROM events WHERE kind='delete' AND subject='file:verification/docs/verification/verification_plan.md'"
            ).fetchone()[0]
        self.assertEqual(first_events, 1)
        self.assertEqual(second_events, first_events)
        path.write_text(original, encoding="utf-8")
        restored = self.run_cli("docs", "sync", "verification_plan.md")
        self.assertEqual(restored["restored"], ["verification/docs/verification/verification_plan.md"])
        status = self.run_cli("docs", "status", "verification_plan.md")["documents"][0]
        self.assertEqual(status["status"], "REVIEW_REQUIRED")

    def test_document_governance_items_and_review_are_sqlite_projections(self) -> None:
        self.bootstrap()
        plan = self.run_cli("plan", "VDOC")
        self.run_cli("review", "VDOC", "--reviewer", "alice")
        tracked = self.run_cli(
            "docs", "track", "verification_plan.md", "--id", "D-001",
            "--kind", "provisional", "--title", "暂按 transaction-level 比较",
            "--status", "ACTIVE", "--owner", "alice", "--review-trigger", "获得首轮回归 evidence",
            "--affects", "VF-001", "--anchor", "#compare-policy",
        )
        self.assertEqual(tracked["kind"], "provisional")
        reviewed = self.run_cli(
            "docs", "review", "verification_plan.md", "--reviewer", "alice",
            "--notes", "正文语义已确认",
        )
        self.assertEqual(reviewed["document"]["status"], "VALID")
        desired = next(row["id"] for row in plan["desired_state"] if row["key"] == "verification-plan")
        self.assertEqual(self.run_cli("inspect", desired)["nodes"][0]["status"], "VALID")
        rendered = self.invoke("docs", "render", "verification_plan.md")
        self.assertIn("D-001", rendered.stdout)
        self.assertIn("### Human Review Notes", rendered.stdout)
        self.assertIn("正文语义已确认", rendered.stdout)
        self.assertFalse((self.root / "verification/docs/verification/verification_plan.status.md").exists())
        written = self.run_cli(
            "docs", "render", "verification_plan.md", "--output", "verification/review/document-state.md",
        )
        self.assertEqual(written["source"], ".verif-harness/model.sqlite3")
        self.assertTrue((self.root / written["path"]).is_file())
        refused = self.invoke(
            "docs", "render", "verification_plan.md", "--output",
            "verification/docs/verification/verification_plan.md",
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("不能覆盖工程语义文档", refused.stderr)

    def test_vdoc_freeze_snapshots_reviewed_semantic_documents(self) -> None:
        self.bootstrap()
        self.run_cli("plan", "VDOC")
        self.run_cli("review", "VDOC", "--reviewer", "alice")
        for document in self.run_cli("docs", "status")["documents"]:
            self.run_cli("docs", "review", document["path"], "--reviewer", "alice")
        frozen = self.run_cli("freeze", "VDOC", "--reviewer", "alice", "--reason", "reviewed documents")
        bundle = self.root / ".verif-harness" / Path(frozen["path"]).parent
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["documents"]), 8)
        self.assertEqual(len(list((bundle / "documents").glob("*.md"))), 8)
        self.assertTrue((bundle / "document-governance.md").is_file())

    def test_vdoc_document_root_is_agent_supplied_and_cannot_overlap_readonly_input(self) -> None:
        self.bootstrap()
        plan = self.run_cli("plan", "VDOC", "--document-root", "verification/contracts")
        self.assertEqual(plan["planning_context"]["document_root"], "verification/contracts")
        self.assertIn(
            "VDOC 文档根目录：`verification/contracts`",
            (self.root / "AGENTS.md").read_text(encoding="utf-8"),
        )
        result = self.invoke("plan", "VDOC", "--document-root", "rtl/docs")
        self.assertEqual(result.returncode, 2)
        self.assertIn("不得位于只读输入内", result.stderr)

    def test_custom_vdoc_goal_is_not_mislabelled_as_default_document(self) -> None:
        self.bootstrap()
        plan = self.run_cli("plan", "VDOC", "--desired", "审查新增接口的 reset 语义")
        self.assertEqual(len(plan["desired_state"]), 1)
        self.assertNotIn("document", plan["desired_state"][0])

    def test_review_evidence_auto_closure_and_immutable_freeze(self) -> None:
        self.bootstrap()
        plan = self.design("VDOC", "--desired", "requirements reviewed")
        desired = plan["desired_state"][0]["id"]
        reviewed = self.run_cli("review", "--workstream", "VDOC", "--verdict", "approve",
                                "--reviewer", "alice", "--reason", "reviewed")
        self.assertEqual(reviewed["lifecycle"], "ACTIVE")
        evidence = self.root / "evidence.json"
        evidence.write_text('{"pass": true}\n', encoding="utf-8")
        recorded = self.run_cli("record", "evidence", "--subject", desired, "--kind", "review",
                                "--source", "evidence.json", "--verdict", "pass")
        closure = next(item for item in recorded["auto_closure"]["workstreams"] if item["workstream"] == "VDOC")
        self.assertTrue(closure["ready"])
        frozen = self.run_cli("freeze", "--workstream", "VDOC", "--reviewer", "alice", "--reason", "complete")
        baseline = self.root / ".verif-harness" / frozen["path"]
        self.assertTrue(baseline.is_file())
        self.assertEqual(json.loads(baseline.read_text(encoding="utf-8"))["schema"], "WorkstreamBaseline/1")

    def test_change_crosses_workstream_edges_and_auto_reconciles(self) -> None:
        self.bootstrap()
        stim = self.design("VSTIM", "--desired", "stimulus stable")["desired_state"][0]["id"]
        check = self.design("VCHK", "--desired", "checker stable")["desired_state"][0]["id"]
        self.run_cli("record", "edge", "file:rtl/dut.sv", stim, "--relation", "AFFECTS")
        self.run_cli("record", "edge", stim, check, "--relation", "AFFECTS")
        event = self.run_cli("record", "change", "--path", "rtl/dut.sv", "--kind", "rtl-change")
        self.assertEqual(event["affected"], ["file:rtl/dut.sv", stim, check])
        states = {node["id"]: node["status"] for node in self.run_cli("model", "show")["nodes"]}
        self.assertEqual(states[stim], "REVALIDATION_REQUIRED")
        self.assertEqual(states[check], "REVALIDATION_REQUIRED")
        self.assertEqual({item["workstream"] for item in event["auto_closure"]["workstreams"]}, {"VSTIM", "VCHK"})

    def test_repeated_change_and_legacy_duplicate_findings_do_not_break_closure(self) -> None:
        self.bootstrap()
        desired = self.design("VDOC", "--desired", "document remains consistent")["desired_state"][0]["id"]
        self.run_cli("record", "edge", "file:rtl/dut.sv", desired, "--relation", "AFFECTS")
        self.run_cli("changed", "rtl/dut.sv")
        self.run_cli("changed", "rtl/dut.sv")
        with sqlite3.connect(self.root / ".verif-harness/model.sqlite3") as connection:
            connection.row_factory = sqlite3.Row
            open_findings = list(connection.execute(
                "SELECT * FROM findings WHERE status='OPEN' ORDER BY subject"
            ))
            self.assertEqual(len(open_findings), 2)
            source = next(row for row in open_findings if row["subject"] == desired)
            connection.execute(
                "INSERT INTO findings VALUES(?,?,?,?,?,?,?)",
                ("finding:legacy-duplicate", source["subject"], source["severity"],
                 source["status"], source["cause_event"], source["details"], source["created_at"]),
            )
        closure = self.run_cli("closure", "--workstream", "VDOC")
        action_ids = [action["id"] for action in closure["actions"]]
        self.assertEqual(len(action_ids), len(set(action_ids)))
        matching = [
            action for action in closure["actions"]
            if action["kind"] == "RESOLVE_FINDING" and action["target"] == desired
        ]
        self.assertEqual(len(matching), 1)

    def test_knowledge_query_surface_is_read_only(self) -> None:
        self.bootstrap()
        result = self.invoke("model", "add-node", "x")
        self.assertEqual(result.returncode, 2)
        self.run_cli("record", "node", "req:1", "--type", "requirement", "--title", "one")
        shown = self.run_cli("model", "show", "req:1")
        self.assertEqual(shown["nodes"][0]["id"], "req:1")
        self.assertEqual(self.run_cli("model", "trace", "req:1")["node"]["id"], "req:1")
        invalid = self.invoke("record", "node", "req:2", "--type", "requirement", "--title", "two", "--status", "VALID")
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("evidence", invalid.stderr)

    def test_legacy_engine_aliases_remain_compatible(self) -> None:
        self.bootstrap(); self.design("VCOV")
        self.assertEqual(self.run_cli("vcheck")["status"], "PASS")
        payload = self.run_cli("vclosure")
        self.assertEqual(payload["workstreams"][0]["workstream"], "VCOV")

    def test_refresh_preserves_semantic_validity(self) -> None:
        self.bootstrap()
        desired = self.design("VDOC", "--desired", "reviewed")["desired_state"][0]["id"]
        evidence = self.root / "review.json"; evidence.write_text("{}\n", encoding="utf-8")
        self.run_cli("record", "evidence", "--subject", desired, "--kind", "review", "--source", "review.json", "--verdict", "pass")
        self.run_cli("bootstrap", "--refresh")
        states = {item["id"]: item["status"] for item in self.run_cli("model", "show")["nodes"]}
        self.assertEqual(states[desired], "VALID")

    def test_valid_status_requires_real_evidence(self) -> None:
        self.bootstrap(); desired = self.design("VDOC", "--desired", "baseline")["desired_state"][0]["id"]
        result = self.invoke("record", "evidence", "--subject", desired, "--kind", "simulation",
                             "--source", "missing.json", "--verdict", "pass")
        self.assertEqual(result.returncode, 2)
        self.assertIn("evidence source", result.stderr)

    def test_reason_request_separates_role_and_backend(self) -> None:
        payload = self.run_cli("reason", "request", "--purpose", "triage ambiguity", "--context", "two causes",
                               "--role", "DebugEngineer", "--backend", "codex")
        self.assertEqual(payload["schema"], "VerificationReasoningRequest/2")
        self.assertEqual(payload["role"], "DebugEngineer")
        self.assertEqual(payload["backend"], "codex")
        self.assertFalse(payload["executed"])

    def test_final_freeze_fails_closed_until_all_workstreams_are_baselined(self) -> None:
        self.bootstrap()
        result = self.invoke("freeze", "--final", "--reviewer", "alice", "--reason", "premature")
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing=", result.stderr)

    def test_removed_v0_and_linear_stage_commands_are_not_accepted(self) -> None:
        for command in ("init", "resume", "recover"):
            self.assertEqual(subprocess.run([sys.executable, str(CLI), command], check=False,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).returncode, 2)
        self.bootstrap()
        result = self.invoke("plan", "design", "--stage", "0")
        self.assertEqual(result.returncode, 2)

    def test_short_plan_review_status_and_model_commands(self) -> None:
        self.bootstrap()
        plan = self.run_cli("plan", "VDOC", "--desired", "requirements reviewed")
        desired = plan["desired_state"][0]["id"]
        reviewed = self.run_cli("review")
        self.assertEqual(reviewed["workstream"], "VDOC")
        self.assertEqual(reviewed["verdict"], "APPROVE")
        self.assertEqual(self.run_cli("status", "VDOC")["plan"]["lifecycle"], "ACTIVE")
        self.assertEqual(self.run_cli("model", desired)["nodes"][0]["id"], desired)
        self.assertEqual(self.run_cli("inspect", desired)["nodes"][0]["id"], desired)
        self.assertEqual(self.run_cli("trace", desired)["node"]["id"], desired)
        self.assertEqual(self.run_cli("impact", desired)["source"], desired)

    def test_review_inference_fails_closed_when_ambiguous(self) -> None:
        self.bootstrap()
        self.run_cli("plan", "VDOC")
        self.run_cli("plan", "VSTIM")
        result = self.invoke("review")
        self.assertEqual(result.returncode, 2)
        self.assertIn("VDOC", result.stderr)
        self.assertIn("VSTIM", result.stderr)

    def test_non_approval_review_requires_reason(self) -> None:
        self.bootstrap()
        self.run_cli("plan", "VDOC")
        result = self.invoke("review", "VDOC", "--verdict", "reject")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--reason", result.stderr)

    def test_prove_changed_and_short_freeze(self) -> None:
        self.bootstrap()
        plan = self.run_cli("plan", "VDOC", "--desired", "requirements reviewed")
        desired = plan["desired_state"][0]["id"]
        self.run_cli("review")
        evidence = self.root / "review.json"
        evidence.write_text('{"reviewed": true}\n', encoding="utf-8")
        proved = self.run_cli("prove", desired, "review.json", "--kind", "review")
        self.assertEqual(proved["verdict"], "PASS")
        frozen = self.run_cli("freeze", "VDOC")
        self.assertEqual(frozen["lifecycle"], "BASELINED")
        changed = self.run_cli("changed", "rtl/dut.sv")
        self.assertEqual(changed["kind"], "rtl-change")

    def test_final_freeze_short_spelling_is_supported(self) -> None:
        self.bootstrap()
        result = self.invoke("freeze", "final")
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing=", result.stderr)

    def test_short_commands_cover_bootstrap_through_final_freeze(self) -> None:
        self.bootstrap()
        evidence = self.root / "evidence.json"
        evidence.write_text('{"verified": true}\n', encoding="utf-8")
        for workstream in ("VDOC", "VSTIM", "VCHK", "VCOV", "VCASE", "VREG"):
            plan = self.run_cli("plan", workstream, "--desired", f"{workstream} verified")
            self.run_cli("review", workstream)
            self.run_cli("prove", plan["desired_state"][0]["id"], "evidence.json")
            self.assertEqual(self.run_cli("freeze", workstream)["lifecycle"], "BASELINED")
        final = self.run_cli("freeze", "final")
        self.assertEqual(final["kind"], "FINAL")
        self.assertTrue((self.root / ".verif-harness" / final["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
