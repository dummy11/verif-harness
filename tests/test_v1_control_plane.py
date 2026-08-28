from __future__ import annotations

import json
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
        return subprocess.run(
            [sys.executable, str(CLI), *arguments, "--project-root", str(self.root)],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def run_cli(self, *arguments: str, expected: int = 0) -> dict:
        result = self.invoke(*arguments)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout) if result.stdout else {}

    def bootstrap(self) -> dict:
        return self.run_cli("bootstrap", "--runtime", "none", "--rtl-root", "rtl")

    def design(self, workstream: str = "VDOC", *extra: str) -> dict:
        return self.run_cli("plan", "design", "--workstream", workstream, *extra)

    def test_bootstrap_creates_minimal_model_without_verification_semantics(self) -> None:
        payload = self.bootstrap()
        state = self.root / ".verif-harness"
        self.assertEqual(payload["rtl_roots"], ["rtl"])
        self.assertTrue((state / "model.sqlite3").is_file())
        self.assertTrue((state / "model.md").is_file())
        with sqlite3.connect(state / "model.sqlite3") as connection:
            version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
            workstreams = connection.execute("SELECT COUNT(*) FROM workstreams").fetchone()[0]
        self.assertEqual(version, "2")
        self.assertEqual(workstreams, 0)

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

    def test_vplan_uses_detailed_template_and_current_model_context(self) -> None:
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

    def test_vmodel_public_surface_is_read_only(self) -> None:
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

    def test_explicit_vcheck_and_vclosure_aliases(self) -> None:
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
        self.assertEqual(payload["schema"], "VReasonRequest/2")
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


if __name__ == "__main__":
    unittest.main()
