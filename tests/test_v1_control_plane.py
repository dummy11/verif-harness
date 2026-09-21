from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from verif_harness.evidence_policy import policy_for


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

    @staticmethod
    def adapter_receipt(analyzer: str) -> dict:
        receipt = {
            "adapter_schema_version": 1, "adapter_version": "test",
            "state": "PASS", "operation": "analyze",
            "request_sha256": "c" * 64, "blockers": [],
            "tool_identity": {"state": "PASS"},
        }
        if analyzer == "xverif":
            receipt["tool"] = "fixture-simulator"
        else:
            receipt["tool_identity"]["binary_sha256"] = "d" * 64
        return receipt

    def write_reachability_report(self, producer_kind: str = "vstim-probe", repeated: bool = True) -> Path:
        native = self.root / "results/stimulus/probe.json"
        simulation_log = self.root / "results/stimulus/run.log"
        analysis_report = self.root / "results/stimulus/xverif-analysis.json"
        native.parent.mkdir(parents=True, exist_ok=True)
        native.write_text('{"accepted": 2}\n', encoding="utf-8")
        simulation_log.write_text("simulation passed\n", encoding="utf-8")
        analysis_report.write_text(
            json.dumps(self.adapter_receipt("xverif")) + "\n", encoding="utf-8",
        )
        run = {
            "id": "run-001", "test": "targeted", "seed": 17,
            "config_digest": "a" * 64, "stimulus_digest": "b" * 64,
            "errors": 0, "timeouts": 0,
            "scenarios": [{
                "id": "backpressure-release", "required": True,
                "generated": 2, "driven": 2, "accepted": 2, "hits": 2,
            }],
        }
        runs = [run]
        if repeated:
            runs.append({**run, "id": "run-002"})
        report = {
            "schema": "StimulusReachabilityEvidence/1",
            "revision": "test-revision",
            "artifacts": [
                {"path": "results/stimulus/run.log",
                 "sha256": hashlib.sha256(simulation_log.read_bytes()).hexdigest(),
                 "kind": "simulation-log", "analyzed_by": ["xverif"]},
                {"path": "results/stimulus/probe.json",
                 "sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
                 "kind": "transaction-trace", "analyzed_by": ["xverif"]},
                {"path": "results/stimulus/xverif-analysis.json",
                 "sha256": hashlib.sha256(analysis_report.read_bytes()).hexdigest(),
                 "kind": "analysis-report", "analyzed_by": ["xverif"]},
            ],
            "producer": {"kind": producer_kind, "name": "input-monitor", "version": "1"},
            "observation": {
                "boundary": "dut-input-accepted", "point": "monitor.accepted",
                "predicate": "valid && ready && tag == backpressure_release",
            },
            "runs": runs,
        }
        path = self.root / "reachability.json"
        path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        return path

    def materialize_evidence_example(self, filename: str) -> Path:
        source = ROOT / "skills/verif-harness/evidence" / filename
        payload = json.loads(source.read_text(encoding="utf-8"))
        digest_replacements: dict[str, str] = {}
        for index, artifact in enumerate(payload["artifacts"]):
            path = self.root / artifact["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            if artifact.get("kind") == "analysis-report":
                path.write_text(
                    json.dumps(self.adapter_receipt(artifact["analyzed_by"][0])) + "\n",
                    encoding="utf-8",
                )
            else:
                path.write_text(f"native artifact {filename} {index}\n", encoding="utf-8")
            old_digest = artifact["sha256"]
            artifact["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            digest_replacements[old_digest] = artifact["sha256"]

        def bind_artifacts(value):
            if isinstance(value, dict):
                return {key: bind_artifacts(item) for key, item in value.items()}
            if isinstance(value, list):
                return [bind_artifacts(item) for item in value]
            return digest_replacements.get(value, value)

        payload["result"] = bind_artifacts(payload["result"])
        target = self.root / filename
        target.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        return target

    def write_typed_report(self, filename: str, schema: str, claim: str, result: dict) -> Path:
        workstream = {
            "EnvironmentEvidence/1": "VENV", "StimulusCapabilityEvidence/1": "VSTIM",
            "CheckingEvidence/1": "VCHK", "CoverageEvidence/1": "VCOV",
            "TestcaseEvidence/1": "VCASE", "RegressionEvidence/1": "VREG",
        }[schema]
        policy = policy_for(workstream, claim)
        artifacts = []
        digest = ""
        for index, item in enumerate(policy["requirements"]):
            selected = item["alternatives"][0]
            native = self.root / "results/contracts" / f"{filename}.{index}.{selected['kind']}"
            native.parent.mkdir(parents=True, exist_ok=True)
            if selected["kind"] == "analysis-report":
                native.write_text(
                    json.dumps(self.adapter_receipt(selected["analyzer"])) + "\n",
                    encoding="utf-8",
                )
            else:
                native.write_text(f"native evidence for {claim}\n", encoding="utf-8")
            digest = hashlib.sha256(native.read_bytes()).hexdigest()
            artifacts.append({
                "path": native.relative_to(self.root).as_posix(), "sha256": digest,
                "kind": selected["kind"], "analyzed_by": [selected["analyzer"]],
            })

        def bind(value):
            if isinstance(value, dict):
                return {key: bind(item) for key, item in value.items()}
            if isinstance(value, list):
                return [bind(item) for item in value]
            return digest if value == "$ARTIFACT_DIGEST" else value

        payload = {
            "schema": schema, "claim": claim, "revision": "test-revision", "tool": "test-tool/1",
            "artifacts": artifacts,
            "result": bind(result),
        }
        target = self.root / filename
        target.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        return target

    def test_bootstrap_creates_minimal_model_without_verification_semantics(self) -> None:
        payload = self.bootstrap()
        state = self.root / ".verif-harness"
        self.assertEqual(payload["rtl_roots"], ["rtl"])
        self.assertEqual(payload["dashboard"]["schema"], "DashboardLaunch/1")
        self.assertEqual(payload["dashboard"]["status"], "SKIPPED")
        self.assertTrue((state / "model.sqlite3").is_file())
        self.assertTrue((state / "model.md").is_file())
        instructions = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("verif-harness 项目合同", instructions)
        self.assertIn("DUT top: `dut`", instructions)
        self.assertIn("ASIC 验证控制面约束", instructions)
        self.assertIn("不是通用项目管理、", instructions)
        self.assertIn("节点类型、数量、依赖和完成条件可以", instructions)
        self.assertIn("不机械翻译英文，不自行创造术语", instructions)
        self.assertIn("不是 ASIC 验证工程师的用户也能理解", instructions)
        self.assertIn("计划建立前使用项目级目标 `project`", instructions)
        self.assertIn("Dashboard 或当前 Agent 对话回答", instructions)
        self.assertIn("不得只使用未登记的原生终端", instructions)
        self.assertIn("不得让两个入口形成两套问题状态", instructions)
        self.assertIn("当前 Agent 对话必须显示已登记问题", instructions)
        self.assertIn("`agent-question ask --no-wait`", instructions)
        self.assertIn("`agent-question await QUESTION_ID --timeout 300`", instructions)
        self.assertIn("等待负责人时不得前台执行 `await`", instructions)
        self.assertIn("单独使用 `--no-wait`", instructions)
        self.assertIn("`activity start project`", instructions)
        self.assertIn("VDOC 文档路由尚未建立", instructions)
        self.assertIn("不采用 Stage 或 Spec Kit", instructions)
        self.assertIn("不要直接显示协议角色名 Human", instructions)
        self.assertIn("不能只说“等待计划评审”“空闲”或“未登记活动”", instructions)
        with sqlite3.connect(state / "model.sqlite3") as connection:
            version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
            workstreams = connection.execute("SELECT COUNT(*) FROM workstreams").fetchone()[0]
        self.assertEqual(version, "2")
        self.assertEqual(workstreams, 0)

    def test_bootstrap_can_explicitly_disable_dashboard(self) -> None:
        payload = self.run_cli(
            "bootstrap", "--runtime", "codex", "--rtl-root", "rtl",
            "--verif-root", "verification", "--dut-top", "dut",
            "--dut-top-file", "rtl/dut.sv", "--no-dashboard",
        )
        self.assertEqual(payload["dashboard"]["schema"], "DashboardLaunch/1")
        self.assertEqual(payload["dashboard"]["status"], "DISABLED")
        self.assertFalse((self.root / ".verif-harness/dashboard-runtime.json").exists())

    def test_bootstrap_agent_rules_keep_dashboard_enabled_by_default(self) -> None:
        skill = (ROOT / "skills/verif-harness/SKILL.md").read_text(encoding="utf-8")
        instructions = (
            ROOT / "skills/verif-harness/bootstrap/INSTRUCTIONS.md"
        ).read_text(encoding="utf-8")
        guide = (
            ROOT / "skills/verif-harness/docs/user_guide.md"
        ).read_text(encoding="utf-8")

        for source in (skill, instructions, guide):
            self.assertIn("--dashboard", source)
            self.assertIn("--no-dashboard", source)
        self.assertIn("Never add `--no-dashboard` unless the Human explicitly asks", skill)
        self.assertIn("SSH, a headless server, or a non-interactive Agent", skill)
        self.assertIn("只有 `STARTED` 和 `REUSED`", guide)

    def test_bootstrap_agent_rules_require_sequential_questions(self) -> None:
        skill = (ROOT / "skills/verif-harness/SKILL.md").read_text(encoding="utf-8")
        instructions = (
            ROOT / "skills/verif-harness/bootstrap/INSTRUCTIONS.md"
        ).read_text(encoding="utf-8")
        guide = (
            ROOT / "skills/verif-harness/docs/user_guide.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Ask exactly one unanswered bootstrap", skill)
        self.assertIn("Never combine multiple unanswered fields", skill)
        self.assertIn("Ask exactly one unanswered field per Agent turn", instructions)
        self.assertIn("Never batch several unanswered fields", instructions)
        self.assertNotIn("Ask for missing mandatory\n   fields together", instructions)
        self.assertIn("一次只问一个字段", guide)
        self.assertIn("最后确认一次", guide)
        self.assertIn('never leave a follow-up blocking prompt such as "start plan VDOC?"', instructions)
        self.assertIn("Dashboard and `verif-harness agent-question answer` are two", skill)
        self.assertIn("写回同一个 SQLite 问题记录", guide)

    def test_bootstrap_rejects_invalid_dashboard_port_before_writing_state(self) -> None:
        result = self.invoke(
            "bootstrap", "--runtime", "none", "--rtl-root", "rtl",
            "--verif-root", "verification", "--dut-top", "dut",
            "--dut-top-file", "rtl/dut.sv", "--dashboard-port", "0",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("bootstrap dashboard port 必须在 1..65535", result.stderr)
        self.assertFalse((self.root / ".verif-harness/project.json").exists())

    def test_bootstrap_requires_explicit_dut_identity(self) -> None:
        result = self.invoke("bootstrap", "--runtime", "none", "--rtl-root", "rtl")
        self.assertEqual(result.returncode, 2)
        self.assertIn("rtl root、dut top 和 dut top file", result.stderr)

    def test_bootstrap_preserves_existing_agents_content_and_refresh_is_idempotent(self) -> None:
        instructions = self.root / "AGENTS.md"
        instructions.write_text("# Team policy\n\nKeep this.\n", encoding="utf-8")
        self.bootstrap()
        self.run_cli(
            "bootstrap", "--refresh", "--rtl-root", "rtl", "--verif-root", "verification",
            "--dut-top", "dut", "--dut-top-file", "rtl/dut.sv",
        )
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

    def test_bare_refresh_returns_reconfiguration_questions_without_writing(self) -> None:
        original = self.bootstrap()
        prompted = self.run_cli("bootstrap", "--refresh")
        self.assertEqual(prompted["schema"], "BootstrapReconfiguration/1")
        self.assertEqual(prompted["status"], "ACTION_REQUIRED")
        self.assertEqual(prompted["current"]["rtl_roots"], ["rtl"])
        self.assertEqual(
            [item["id"] for item in prompted["questions_for_human"]],
            [
                "rtl_roots", "dut_top", "dut_top_file", "verif_root", "docs_roots",
                "testbench_root", "reference_model", "verification_scripts",
            ],
        )
        self.assertEqual(prompted["interaction"], {
            "mode": "SEQUENTIAL",
            "one_question_at_a_time": True,
            "current_question_id": "rtl_roots",
            "final_confirmation_required": True,
        })
        self.assertEqual(
            [item["sequence"] for item in prompted["questions_for_human"]],
            list(range(1, 9)),
        )
        self.assertTrue(all(
            item.get("skip_allowed") is True
            for item in prompted["questions_for_human"][4:]
        ))
        unchanged = json.loads(
            (self.root / ".verif-harness/project.json").read_text(encoding="utf-8")
        )
        self.assertEqual(unchanged["updated_at"], original["updated_at"])

    def test_bootstrap_can_project_complete_dut_identity(self) -> None:
        payload = self.run_cli(
            "bootstrap", "--runtime", "none", "--rtl-root", "rtl", "--verif-root", "verification",
            "--dut-top", "dut", "--dut-top-file", "rtl/dut.sv",
        )
        config = json.loads((self.root / ".harness-config.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["dut"]["top_module"], "dut")
        self.assertEqual(config["rtl"]["top_file"], "rtl/dut.sv")
        self.assertEqual(config["verif"]["docs_root"], "verification/docs")
        self.assertEqual(config["verification_inputs"], {
            "testbench_root": None, "reference_model": None, "scripts": [],
        })

    def test_bootstrap_registers_three_independent_optional_verification_inputs(self) -> None:
        testbench = self.root / "tb"
        testbench.mkdir()
        (testbench / "env.sv").write_text("module env; endmodule\n", encoding="utf-8")
        reference_model = self.root / "models/reference.py"
        reference_model.parent.mkdir()
        reference_model.write_text("def predict(value): return value\n", encoding="utf-8")
        run_script = self.root / "scripts/run_sim.sh"
        regression_script = self.root / "scripts/run_regression.py"
        run_script.parent.mkdir()
        run_script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        regression_script.write_text("raise SystemExit(0)\n", encoding="utf-8")

        payload = self.run_cli(
            "bootstrap", "--runtime", "none", "--rtl-root", "rtl",
            "--verif-root", "verification", "--dut-top", "dut",
            "--dut-top-file", "rtl/dut.sv", "--testbench-root", "tb",
            "--gold-model", "models/reference.py",
            "--verification-script", "scripts/run_sim.sh",
            "--verification-script", "scripts/run_regression.py",
        )
        self.assertEqual(payload["verification_inputs"], {
            "testbench_root": "tb", "reference_model": "models/reference.py",
            "scripts": ["scripts/run_sim.sh", "scripts/run_regression.py"],
        })
        config = json.loads((self.root / ".harness-config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["verification_inputs"], payload["verification_inputs"])
        inventory = json.loads(
            (self.root / ".verif-harness/inventory.json").read_text(encoding="utf-8")
        )
        by_path = {item["path"]: item for item in inventory}
        self.assertIn("tb/env.sv", by_path)
        self.assertEqual(by_path["scripts/run_sim.sh"]["kind"], "verification-asset")
        self.assertEqual(by_path["scripts/run_regression.py"]["kind"], "verification-asset")
        instructions = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Testbench 目录：`tb`", instructions)
        self.assertIn("参考模型（reference/golden model）：`models/reference.py`", instructions)
        self.assertIn("`scripts/run_sim.sh`, `scripts/run_regression.py`", instructions)

        refreshed = self.run_cli(
            "bootstrap", "--refresh", "--runtime", "none", "--rtl-root", "rtl",
            "--verif-root", "verification", "--dut-top", "dut",
            "--dut-top-file", "rtl/dut.sv", "--clear-testbench-root",
            "--clear-reference-model", "--clear-verification-scripts",
        )
        self.assertEqual(refreshed["verification_inputs"], {
            "testbench_root": None, "reference_model": None, "scripts": [],
        })

    def test_bootstrap_validates_each_optional_verification_input_independently(self) -> None:
        model = self.root / "reference-model"
        model.mkdir()
        script = self.root / "run.sh"
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

        invalid_testbench = self.invoke(
            "bootstrap", "--runtime", "none", "--rtl-root", "rtl",
            "--dut-top", "dut", "--dut-top-file", "rtl/dut.sv",
            "--testbench-root", "run.sh",
        )
        self.assertEqual(invalid_testbench.returncode, 2)
        self.assertIn("testbench 路径不是目录", invalid_testbench.stderr)

        missing_model = self.invoke(
            "bootstrap", "--runtime", "none", "--rtl-root", "rtl",
            "--dut-top", "dut", "--dut-top-file", "rtl/dut.sv",
            "--reference-model", "missing-model",
        )
        self.assertEqual(missing_model.returncode, 2)
        self.assertIn("reference/golden model 路径不存在", missing_model.stderr)

        invalid_script = self.invoke(
            "bootstrap", "--runtime", "none", "--rtl-root", "rtl",
            "--dut-top", "dut", "--dut-top-file", "rtl/dut.sv",
            "--reference-model", "reference-model",
            "--verification-script", "reference-model",
        )
        self.assertEqual(invalid_script.returncode, 2)
        self.assertIn("验证脚本不是文件", invalid_script.stderr)

    def test_bootstrap_refresh_synchronizes_capability_config_and_preserves_optional_fields(self) -> None:
        self.bootstrap()
        config_path = self.root / ".harness-config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["verif"]["verification_subdir"] = "plans"
        config["reference_model"] = {"enabled": True, "spec_path": "/reviewed/model.md"}
        config_path.write_text(json.dumps(config) + "\n", encoding="utf-8")

        replacement = self.root / "rtl-v2"
        replacement.mkdir()
        top = replacement / "dut_v2.sv"
        top.write_text("module dut_v2; endmodule\n", encoding="utf-8")
        refreshed = self.run_cli(
            "bootstrap", "--refresh", "--project-name", "updated-project",
            "--rtl-root", "rtl-v2", "--verif-root", "sim",
            "--dut-top", "dut_v2", "--dut-top-file", "rtl-v2/dut_v2.sv",
        )
        synchronized = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(refreshed["rtl_roots"], ["rtl-v2"])
        self.assertEqual(synchronized["project_name"], "updated-project")
        self.assertEqual(synchronized["rtl"], {
            "root": "rtl-v2", "top_module": "dut_v2", "top_file": "rtl-v2/dut_v2.sv",
        })
        self.assertEqual(synchronized["verif"]["root"], "sim")
        self.assertEqual(synchronized["verif"]["docs_root"], "sim/docs")
        self.assertEqual(synchronized["verif"]["verification_subdir"], "plans")
        self.assertEqual(synchronized["verif"]["governance_subdir"], "governance")
        self.assertEqual(
            synchronized["reference_model"],
            {"enabled": True, "spec_path": "/reviewed/model.md"},
        )

    def test_bootstrap_refresh_can_explicitly_clear_optional_spec_inputs(self) -> None:
        specification = self.root / "spec.md"
        specification.write_text("# DUT specification\n", encoding="utf-8")
        self.run_cli(
            "bootstrap", "--runtime", "none", "--rtl-root", "rtl",
            "--docs-root", "spec.md", "--verif-root", "verification",
            "--dut-top", "dut", "--dut-top-file", "rtl/dut.sv",
        )
        refreshed = self.run_cli(
            "bootstrap", "--refresh", "--clear-docs-root", "--rtl-root", "rtl",
            "--verif-root", "verification", "--dut-top", "dut",
            "--dut-top-file", "rtl/dut.sv",
        )
        self.assertEqual(refreshed["docs_roots"], [])

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
            refreshed = self.run_cli(
                "bootstrap", "--refresh", "--rtl-root", str(rtl),
                "--docs-root", str(specification), "--verif-root", "verification",
                "--dut-top", "external_dut", "--dut-top-file", str(top),
            )
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
        self.assertGreaterEqual(len(plan["questions_for_human"]), len(plan["desired_state"]))
        self.assertEqual(plan["auto_closure"]["actions"][0]["executor"], "human")
        self.assertTrue((self.root / ".verif-harness/workstreams/vchk/desired-state.json").is_file())
        self.assertTrue((self.root / ".verif-harness/workstreams/vchk/plan.md").is_file())
        for desired in plan["desired_state"]:
            self.assertTrue(desired["statement"])
            self.assertTrue(desired["purpose"])
            self.assertTrue(desired["scope"])
            self.assertTrue(desired["acceptance_criteria"])
            self.assertTrue(desired["source_refs"])
            self.assertEqual(desired["definition_status"], "REVIEW_CANDIDATE")
        projection = (self.root / ".verif-harness/workstreams/vchk/plan.md").read_text(encoding="utf-8")
        self.assertIn("**目标说明**", projection)
        self.assertIn("**满足条件**", projection)
        scoreboard = next(
            item for item in plan["desired_state"] if item["key"] == "scoreboard-evidence"
        )
        self.assertEqual(scoreboard["evidence_contract"]["claim"], "scoreboard-evidence")
        requirements = scoreboard["evidence_contract"]["requirements"]
        self.assertTrue(any(
            {choice["kind"] for choice in item["alternatives"]} == {"simulation-log"}
            for item in requirements
        ))
        self.assertTrue(any(
            {choice["kind"] for choice in item["alternatives"]}
            == {"waveform", "transaction-trace"}
            for item in requirements
        ))
        self.assertTrue(any(
            {choice["kind"] for choice in item["alternatives"]} == {"analysis-report"}
            for item in requirements
        ))

    def test_project_desired_state_proposal_adds_hierarchical_nodes(self) -> None:
        self.bootstrap()
        proposal = {
            "schema": "DesiredStateProposal/1", "workstream": "VCOV",
            "nodes": [{
                "key": "feature.conv.fp16.value-coverage",
                "title": "FP16 convolution value coverage",
                "role": "coverage-goal", "parent_key": "coverage-model",
                "required": True,
                "statement": "Required FP16 value classes and crosses are covered.",
                "purpose": "Expose feature-level coverage gaps.",
                "scope": ["FP16 convolution value and mode crosses"],
                "acceptance_criteria": ["Every required item is covered or Human-waived"],
                "source_refs": ["coverage_plan.md#fp16"],
                "work_content": ["Implement and map required coverage items"],
                "implementation_approach": ["Compile the model and analyze exported coverage"],
                "deliverables": ["Coverage model and item-level report"],
                "progress_measures": [{
                    "id": "required-items", "label": "Required items closed",
                    "unit": "items", "target": "all", "source": "CoverageEvidence/1",
                }],
                "quality_checks": ["No required item remains uncovered"],
                "suggested_mode": "evidence", "evidence_claim": "hole-analysis-evidence",
            }],
        }
        path = self.root / "vcov-desired.json"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        plan = self.run_cli("plan", "VCOV", "--desired-file", str(path))
        self.assertEqual(plan["project_goal_count"], 1)
        child = next(
            item for item in plan["desired_state"]
            if item["key"] == "feature.conv.fp16.value-coverage"
        )
        parent = next(item for item in plan["desired_state"] if item["key"] == "coverage-model")
        self.assertEqual(child["parent_id"], parent["id"])
        self.assertEqual(child["definition_origin"], "project-proposal")
        self.assertEqual(child["role"], "coverage-goal")
        trace = self.run_cli("trace", child["id"])
        self.assertIn(
            (child["id"], parent["id"], "CHILD_OF"),
            {(edge["source"], edge["target"], edge["relation"]) for edge in trace["outgoing"]},
        )
        snapshot = self.run_cli("dashboard", "--snapshot")
        view = next(item for item in snapshot["workstreams"] if item["workstream"] == "VCOV")
        rendered = next(item for item in view["nodes"] if item["id"] == child["id"])
        self.assertEqual(rendered["statement"], proposal["nodes"][0]["statement"])
        self.assertEqual(rendered["parent_key"], "coverage-model")
        self.assertEqual(rendered["work_content"], proposal["nodes"][0]["work_content"])
        self.assertEqual(rendered["progress_measures"], proposal["nodes"][0]["progress_measures"])

        del proposal["nodes"][0]["acceptance_criteria"]
        path.write_text(json.dumps(proposal), encoding="utf-8")
        rejected = self.invoke("plan", "VCOV", "--desired-file", str(path))
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("acceptance_criteria 必须是非空字符串数组", rejected.stderr)

    def test_vdoc_project_proposal_requires_delivery_coverage_before_review(self) -> None:
        self.bootstrap()
        proposal = {
            "schema": "DesiredStateProposal/1", "workstream": "VDOC",
            "nodes": [{
                "key": "dut-reset-plan", "title": "DUT reset 验证文档方案",
                "role": "document-writing-plan", "parent_key": "verification-plan",
                "document_key": "verification-plan", "required": True,
                "statement": "在验证计划中明确 DUT reset 行为。",
                "purpose": "为验证环境和检查器提供一致的 reset 契约。",
                "scope": ["reset 极性、同步方式、保持和释放行为"],
                "acceptance_criteria": ["每个 reset 域都有来源、预期行为和验证责任"],
                "source_refs": ["rtl/dut.sv", "verification_plan.md#reset"],
                "work_content": ["列出 DUT reset 域和验证场景"],
                "implementation_approach": ["从 DUT 顶层和已确认规格交叉核对"],
                "deliverables": ["验证计划中的 reset 方案章节"],
                "progress_measures": [{
                    "id": "reset-domains-reviewed", "label": "已确认 reset 域",
                    "unit": "域", "target": "全部", "source": "verification_plan.md",
                }],
                "quality_checks": ["不存在无来源或无验证责任的 reset 域"],
                "suggested_mode": "review", "evidence_claim": "document-review",
            }],
        }
        proposal_path = self.root / "vdoc-writing-only.json"
        proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
        rejected = self.invoke("plan", "VDOC", "--desired-file", str(proposal_path))
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("没有必需的文档交付节点", rejected.stderr)

        legacy = self.run_cli("plan", "VDOC", "--desired", "legacy writing plan")
        stored = legacy["desired_state"]
        stored[0]["definition_origin"] = "project-proposal"
        with sqlite3.connect(self.root / ".verif-harness/model.sqlite3") as connection:
            connection.execute(
                "UPDATE workstreams SET desired_json=? WHERE name='VDOC'",
                (json.dumps(stored),),
            )
        closure = self.run_cli("closure", "--workstream", "VDOC")
        self.assertEqual([item["kind"] for item in closure["actions"]], ["REFINE_DESIRED_STATE"])
        blocked_review = self.invoke(
            "review", "VDOC", "--verdict", "approve", "--reviewer", "alice",
            "--reason", "should be rejected",
        )
        self.assertEqual(blocked_review.returncode, 2)
        self.assertIn("文档工作分解不完整", blocked_review.stderr)

    def test_every_standard_desired_node_has_a_stored_evidence_contract(self) -> None:
        self.bootstrap()
        for workstream in ("VENV", "VSTIM", "VCHK", "VCOV", "VCASE", "VREG"):
            with self.subTest(workstream=workstream):
                plan = self.design(workstream)
                for desired in plan["desired_state"]:
                    self.assertEqual(
                        desired["evidence_contract"]["claim"], desired["evidence_claim"],
                    )
                    self.assertTrue(desired["evidence_contract"]["requirements"])

    def test_custom_implementation_goal_requires_explicit_evidence_claim(self) -> None:
        self.bootstrap()
        rejected = self.invoke("plan", "VCHK", "--desired", "custom checker behavior")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("--evidence-claim", rejected.stderr)
        planned = self.run_cli(
            "plan", "VCHK", "--desired", "custom checker behavior",
            "--evidence-claim", "scoreboard-evidence",
        )
        desired = planned["desired_state"][0]
        self.assertEqual(desired["evidence_claim"], "scoreboard-evidence")
        self.assertEqual(desired["evidence_contract"]["basis"], "runtime-comparison")

    def test_analysis_report_must_be_an_adapter_pass_receipt(self) -> None:
        self.bootstrap()
        plan = self.design(
            "VCHK", "--desired", "custom checker behavior",
            "--evidence-claim", "scoreboard-evidence",
        )
        report = self.write_typed_report(
            "custom-checker.json", "CheckingEvidence/1", "scoreboard-evidence",
            {"engaged": True, "comparisons": 2, "mismatches": 0,
             "residual": 0, "implementation_digest": "$ARTIFACT_DIGEST"},
        )
        payload = json.loads(report.read_text(encoding="utf-8"))
        analysis = next(item for item in payload["artifacts"] if item["kind"] == "analysis-report")
        analysis_path = self.root / analysis["path"]
        analysis_path.write_text('{"state":"PASS"}\n', encoding="utf-8")
        analysis["sha256"] = hashlib.sha256(analysis_path.read_bytes()).hexdigest()
        payload["result"]["implementation_digest"] = analysis["sha256"]
        report.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        rejected = self.invoke("evidence", plan["desired_state"][0]["id"], report.name)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("adapter_schema_version=1", rejected.stderr)

    def test_workstream_is_reentrant_and_revisioned(self) -> None:
        self.bootstrap()
        first = self.design(
            "VSTIM", "--desired", "基础激励可达",
            "--evidence-claim", "reachability-evidence",
        )
        second = self.design(
            "VSTIM", "--desired", "补充 backpressure 场景",
            "--evidence-claim", "reachability-evidence",
        )
        self.assertEqual(second["revision"], first["revision"] + 1)
        model = self.run_cli("model", "show")
        status = {node["id"]: node["status"] for node in model["nodes"]}
        self.assertEqual(status[first["desired_state"][0]["id"]], "STALE")
        self.assertEqual(status[second["desired_state"][0]["id"]], "UNKNOWN")

    def test_activity_human_action_and_dashboard_snapshot_are_persistent(self) -> None:
        self.bootstrap()
        plan = self.design("VCHK")
        node_id = plan["desired_state"][0]["id"]
        activity = self.run_cli(
            "activity", "start", node_id, "--operation", "targeted-simulation",
            "--actor", "Agent", "--message", "running seed 42", "--total", "10",
        )
        self.assertEqual(activity["status"], "RUNNING")
        self.assertEqual(activity["progress_current"], 0)
        updated = self.run_cli(
            "activity", "update", activity["id"], "--status", "WAITING_FOR_HUMAN",
            "--current", "3", "--message", "需要确认 tolerance",
        )
        self.assertEqual(updated["progress_current"], 3)
        self.assertEqual(updated["status"], "WAITING_FOR_HUMAN")

        action = self.run_cli(
            "human-action", "add", node_id, "--action", "REQUEST_CHANGE",
            "--reason", "absolute tolerance 改为 2", "--reviewer", "alice",
        )
        self.assertEqual(action["status"], "OPEN")
        self.assertEqual(action["target"], node_id)
        snapshot = self.run_cli("dashboard", "--snapshot")
        self.assertEqual(snapshot["schema"], "VerificationDashboard/1")
        self.assertEqual(snapshot["activities"][0]["status"], "WAITING_FOR_HUMAN")
        self.assertEqual(snapshot["human_actions"][0]["action"], "REQUEST_CHANGE")
        view = next(item for item in snapshot["workstreams"] if item["workstream"] == "VCHK")
        desired = next(item for item in view["nodes"] if item["id"] == node_id)
        self.assertEqual(desired["activities"][0]["id"], activity["id"])
        self.assertEqual(view["human_actions"][0]["id"], action["id"])

        resolved = self.run_cli(
            "human-action", "resolve", action["id"], "--reviewer", "bob",
            "--resolution", "已转入新 revision",
        )
        self.assertEqual(resolved["status"], "RESOLVED")

        replacement = self.design("VCHK")
        refreshed = self.run_cli("dashboard", "--snapshot")
        self.assertNotIn(node_id, {item["node_id"] for item in refreshed["activities"]})
        self.assertIn(activity["id"], {item["id"] for item in refreshed["activity_history"]})
        self.assertIn(action["id"], {item["id"] for item in refreshed["human_action_history"]})
        self.assertEqual(
            refreshed["current_node_count"], len(replacement["desired_state"]),
        )

    def test_activity_cannot_directly_change_node_validity(self) -> None:
        self.bootstrap()
        plan = self.design("VSTIM")
        node_id = plan["desired_state"][0]["id"]
        activity = self.run_cli("activity", "start", node_id, "--operation", "implementation")
        self.run_cli("activity", "update", activity["id"], "--status", "COMPLETED")
        node = self.run_cli("inspect", node_id)["nodes"][0]
        self.assertEqual(node["status"], "UNKNOWN")

    def test_split_agent_question_checkpoint_accepts_cli_answer_while_waiting(self) -> None:
        self.bootstrap()
        activity = self.run_cli(
            "activity", "start", "project", "--operation", "select-vdoc-route",
        )
        question = self.run_cli(
            "agent-question", "ask", "project",
            "--prompt", "现在开始 VDOC 规划吗？",
            "--option", "start", "开始", "生成并评审 DUT-specific 文档方案",
            "--option", "later", "稍后", "保持当前 bootstrap 状态",
            "--recommended", "start", "--activity", activity["id"], "--no-wait",
        )
        environment = os.environ.copy()
        environment["GIT_AUTHOR_NAME"] = "test-user"
        environment.pop("USER", None)
        waiter = subprocess.Popen(
            [
                sys.executable, str(CLI), "agent-question", "await", question["id"],
                "--timeout", "5", "--project-root", str(self.root),
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
        )
        try:
            time.sleep(0.2)
            self.assertIsNone(waiter.poll(), "后台 checkpoint 应在普通 CLI 回答期间保持活动")
            answered = self.run_cli(
                "agent-question", "answer", question["id"], "--option", "start",
                "--reviewer", "alice",
            )
            self.assertEqual(answered["status"], "ANSWERED")
            stdout, stderr = waiter.communicate(timeout=5)
            self.assertEqual(waiter.returncode, 0, stdout + stderr)
            checkpoint = json.loads(stdout)
            self.assertTrue(checkpoint["resume"])
            self.assertEqual(checkpoint["question"]["answer_option"], "start")
            self.assertEqual(
                self.run_cli("dashboard", "--snapshot")["activities"][0]["status"],
                "RUNNING",
            )
        finally:
            if waiter.poll() is None:
                waiter.terminate()
                waiter.communicate(timeout=5)

    def test_agent_question_is_dashboard_visible_and_answer_resumes_activity(self) -> None:
        self.bootstrap()
        plan = self.design("VCHK")
        node_id = plan["desired_state"][0]["id"]
        activity = self.run_cli(
            "activity", "start", node_id, "--operation", "reference-model-selection",
        )
        question = self.run_cli(
            "agent-question", "ask", node_id,
            "--prompt", "参考模型策略选哪个？",
            "--context", "规格明确该场景必须以 acc_cmodel.c 为准",
            "--option", "dpi", "DPI 直连 cmodel", "scoreboard 通过 DPI 逐事务调用",
            "--option", "sv", "按规格重写", "不依赖 cmodel 源文件",
            "--recommended", "dpi", "--activity", activity["id"], "--no-wait",
        )
        self.assertEqual(question["status"], "OPEN")
        self.assertEqual(question["recommended_option"], "dpi")
        self.assertEqual(len(question["options"]), 2)
        snapshot = self.run_cli("dashboard", "--snapshot")
        self.assertEqual(snapshot["activities"][0]["status"], "WAITING_FOR_HUMAN")
        waiting = next(
            item for item in snapshot["waiting_for_human"]
            if item["source"] == "agent-question"
        )
        self.assertEqual(waiting["question_id"], question["id"])
        self.assertEqual(waiting["recommended_option"], "dpi")

        answered = self.run_cli(
            "agent-question", "answer", question["id"],
            "--option", "dpi", "--reviewer", "alice",
            "--text", "以现有 cmodel 为只读参考模型",
        )
        self.assertEqual(answered["status"], "ANSWERED")
        checkpoint = self.run_cli(
            "agent-question", "await", question["id"], "--timeout", "0",
        )
        self.assertTrue(checkpoint["resume"])
        self.assertEqual(checkpoint["question"]["answer_option"], "dpi")
        refreshed = self.run_cli("dashboard", "--snapshot")
        self.assertEqual(refreshed["activities"][0]["status"], "RUNNING")
        self.assertFalse(any(
            item["source"] == "agent-question" for item in refreshed["waiting_for_human"]
        ))
        # A choice unblocks Agent reasoning but never proves the verification node.
        node = self.run_cli("inspect", node_id)["nodes"][0]
        self.assertEqual(node["status"], "UNKNOWN")

    def test_blocking_agent_question_ask_waits_for_dashboard_answer(self) -> None:
        self.bootstrap()
        activity = self.run_cli(
            "activity", "start", "project", "--operation", "select-vdoc-route",
        )
        environment = os.environ.copy()
        environment["GIT_AUTHOR_NAME"] = "test-user"
        environment.pop("USER", None)
        waiter = subprocess.Popen(
            [
                sys.executable, str(CLI), "agent-question", "ask", "project",
                "--prompt", "现在开始 VDOC 规划吗？",
                "--option", "start", "开始", "生成并评审 DUT-specific 文档方案",
                "--option", "later", "稍后", "保持当前 bootstrap 状态",
                "--recommended", "start", "--activity", activity["id"],
                "--wait-timeout", "5", "--project-root", str(self.root),
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
        )
        try:
            deadline = time.monotonic() + 3
            question = None
            while time.monotonic() < deadline:
                listed = self.run_cli("agent-question", "list", "--status", "open")
                if listed["agent_questions"]:
                    question = listed["agent_questions"][0]
                    break
                time.sleep(0.05)
            self.assertIsNotNone(question, "阻塞问题应先持久化，再等待 Dashboard 回答")
            self.assertIsNone(waiter.poll(), "默认 ask 不应在问题仍开放时返回到 runtime prompt")

            self.run_cli(
                "agent-question", "answer", question["id"], "--option", "start",
                "--reviewer", "alice",
            )
            stdout, stderr = waiter.communicate(timeout=5)
            self.assertEqual(waiter.returncode, 0, stdout + stderr)
            checkpoint = json.loads(stdout)
            self.assertEqual(checkpoint["schema"], "AgentQuestionCheckpoint/1")
            self.assertEqual(checkpoint["status"], "ANSWERED")
            self.assertTrue(checkpoint["resume"])
            self.assertEqual(checkpoint["question"]["answer_option"], "start")
        finally:
            if waiter.poll() is None:
                waiter.terminate()
                waiter.communicate(timeout=5)

    def test_project_question_is_visible_before_any_workstream_exists(self) -> None:
        self.bootstrap()
        idle_snapshot = self.run_cli("dashboard", "--snapshot")
        self.assertEqual(idle_snapshot["project_agent"]["id"], "project-agent")
        self.assertEqual(idle_snapshot["project_agent"]["scope"], "project")
        self.assertEqual(idle_snapshot["project_agent"]["status"], "IDLE")
        self.assertEqual(idle_snapshot["project_agent"]["label"], "当前项目的 Agent")
        self.assertEqual(
            idle_snapshot["project_agent"]["message"],
            "现在没有需要你回答的问题；Dashboard 也没有收到 Agent 正在处理验证工作的记录",
        )
        self.assertEqual(idle_snapshot["project_agent"]["active_activity_count"], 0)
        activity = self.run_cli(
            "activity", "start", "project", "--operation", "analyze-dut-for-vdoc",
            "--actor", "Kimi explore", "--message", "分析 DUT 规格与 RTL",
        )
        question = self.run_cli(
            "agent-question", "ask", "project",
            "--prompt", "VDOC 验证文档输出到哪个目录？",
            "--context", "当前尚未创建 VDOC 工作流或工作节点",
            "--option", "default", "使用默认目录", "verif/docs/verification",
            "--option", "custom", "指定其他目录", "由 Human 填写目录",
            "--recommended", "default", "--activity", activity["id"], "--no-wait",
        )
        self.assertEqual(question["target_type"], "project")
        self.assertEqual(question["workstream"], "PROJECT")

        snapshot = self.run_cli("dashboard", "--snapshot")
        self.assertEqual(snapshot["workstreams"], [])
        self.assertEqual(snapshot["activities"][0]["node_id"], "project")
        self.assertEqual(snapshot["activities"][0]["status"], "WAITING_FOR_HUMAN")
        self.assertEqual(snapshot["project_agent"]["status"], "WAITING_FOR_HUMAN")
        self.assertEqual(snapshot["project_agent"]["open_question_count"], 1)
        self.assertEqual(snapshot["agent_questions"][0]["id"], question["id"])
        self.assertTrue(any(
            item["source"] == "agent-question"
            and item["target_type"] == "project"
            for item in snapshot["waiting_for_human"]
        ))

        answered = self.run_cli(
            "agent-question", "answer", question["id"], "--option", "default",
            "--reviewer", "alice",
        )
        self.assertEqual(answered["status"], "ANSWERED")
        refreshed = self.run_cli("dashboard", "--snapshot")
        self.assertEqual(refreshed["activities"][0]["status"], "RUNNING")
        self.assertEqual(refreshed["agent_questions"][0]["status"], "ANSWERED")
        self.assertEqual(refreshed["project_agent"]["status"], "RUNNING")

    def test_await_human_is_revision_bound_and_only_formal_review_unblocks(self) -> None:
        self.bootstrap()
        proposal = {
            "schema": "DesiredStateProposal/1", "workstream": "VDOC",
            "nodes": [{
                "key": "dut-reset-plan", "title": "DUT reset 验证文档方案",
                "role": "document-writing-plan", "parent_key": "verification-plan",
                "document_key": "verification-plan",
                "required": True,
                "statement": "当前 DUT reset 行为和验证边界已写入验证计划。",
                "purpose": "让后续环境、检查和用例使用相同的 reset 语义。",
                "scope": ["DUT reset 极性、同步方式、保持和释放行为"],
                "acceptance_criteria": ["每个 reset 域都有来源、预期行为和验证责任"],
                "source_refs": ["rtl/dut.sv", "verification_plan.md#reset"],
                "work_content": ["列出 DUT reset 域和验证场景"],
                "implementation_approach": ["从 DUT 顶层和已确认规格交叉核对"],
                "deliverables": ["验证计划中的 reset 方案章节"],
                "progress_measures": [{
                    "id": "reset-domains-reviewed", "label": "已确认 reset 域",
                    "unit": "域", "target": "全部", "source": "verification_plan.md",
                }],
                "quality_checks": ["不存在无来源或无验证责任的 reset 域"],
                "suggested_mode": "review", "evidence_claim": "document-review",
            }, {
                "key": "dut-reset-semantics", "title": "DUT reset 正文交付",
                "role": "document-deliverable", "parent_key": "dut-reset-plan",
                "document_key": "verification-plan", "required": True,
                "statement": "验证计划正文已明确 DUT reset 行为和验证边界。",
                "purpose": "独立验收 reset 工程语义。",
                "scope": ["DUT reset 极性、同步方式、保持和释放行为"],
                "acceptance_criteria": ["每个 reset 域都有来源、预期行为和验证责任"],
                "source_refs": ["verification_plan.md#reset", "rtl/dut.sv"],
                "work_content": ["正文中的 reset 域、时序和验证场景"],
                "implementation_approach": ["对照当前正文与 DUT 顶层逐项验收"],
                "deliverables": ["reset 正文语义的独立验收结论"],
                "progress_measures": [{
                    "id": "reset-semantics-accepted", "label": "已验收 reset 域",
                    "unit": "域", "target": "全部", "source": "verification_plan.md",
                }],
                "quality_checks": ["不存在无来源或无验证责任的 reset 域"],
                "suggested_mode": "review", "evidence_claim": "document-review",
            }],
        }
        proposal_path = self.root / "vdoc-review-proposal.json"
        proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
        plan = self.design("VDOC", "--desired-file", str(proposal_path))
        revision = plan["revision"]
        node_id = next(
            item["id"] for item in plan["desired_state"]
            if item["key"] == "dut-reset-plan"
        )
        activity = self.run_cli(
            "activity", "start", node_id, "--operation", "prepare-vdoc-review",
        )
        self.run_cli(
            "human-action", "add", "VDOC", "--action", "REQUEST_CHANGE",
            "--reason", "请补充 reset 说明", "--reviewer", "alice",
        )
        timed_out = self.run_cli(
            "await-human", "VDOC", "--revision", str(revision),
            "--activity", activity["id"], "--timeout", "0",
        )
        self.assertEqual(timed_out["status"], "TIMEOUT")
        self.assertEqual(timed_out["activity"]["status"], "WAITING_FOR_HUMAN")

        environment = os.environ.copy()
        environment["GIT_AUTHOR_NAME"] = "test-user"
        environment.pop("USER", None)
        waiter = subprocess.Popen(
            [
                sys.executable, str(CLI), "await-human", "VDOC",
                "--revision", str(revision), "--activity", activity["id"],
                "--timeout", "3", "--project-root", str(self.root),
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
        )
        time.sleep(0.3)
        self.assertIsNone(waiter.poll(), "普通 Human action 不应解除正式评审等待")
        approved = self.run_cli(
            "review", "VDOC", "--verdict", "approve",
            "--reviewer", "alice", "--reason", "当前 revision 可以继续",
        )
        stdout, stderr = waiter.communicate(timeout=5)
        self.assertEqual(waiter.returncode, 0, stdout + stderr)
        decided = json.loads(stdout)
        self.assertEqual(decided["status"], "DECIDED")
        self.assertEqual(decided["review"]["id"], approved["review_id"])
        self.assertTrue(decided["resume"])
        self.assertEqual(decided["next"], "continue")
        self.assertEqual(decided["activity"]["status"], "RUNNING")

        replay = self.invoke(
            "await-human", "VDOC", "--revision", str(revision),
            "--after-review", approved["review_id"], "--timeout", "0",
        )
        self.assertEqual(replay.returncode, 2)
        self.assertIn("当前没有等待负责人评审的检查点", replay.stderr)
        modified = self.run_cli(
            "review", "VDOC", "--verdict", "modify", "--reviewer", "alice",
            "--reason", "仍需修改接口章节",
        )
        next_decision = self.run_cli(
            "await-human", "VDOC", "--revision", str(revision),
            "--after-review", approved["review_id"], "--timeout", "0",
        )
        self.assertEqual(next_decision["review"]["id"], modified["review_id"])
        self.assertFalse(next_decision["resume"])
        self.assertEqual(next_decision["next"], "revise")

        replacement = self.design("VDOC")
        self.assertGreater(replacement["revision"], revision)
        stale = self.invoke(
            "await-human", "VDOC", "--revision", str(revision), "--timeout", "0",
        )
        self.assertEqual(stale.returncode, 2)
        self.assertIn("旧 revision 的评审不能恢复当前工作", stale.stderr)

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
        self.assertIn("负责人批准当前 VDOC 文档撰写方案", premature.stderr)
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
        self.assertIn("验证文档正文摘要发生变化", rendered.stdout)

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
        self.assertIn("### 负责人评审意见", rendered.stdout)
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
        self.assertIn("不能覆盖验证文档", refused.stderr)

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
        stim = self.design(
            "VSTIM", "--desired", "stimulus stable",
            "--evidence-claim", "stimulus-implementation",
        )["desired_state"][0]["id"]
        check = self.design(
            "VCHK", "--desired", "checker stable",
            "--evidence-claim", "scoreboard",
        )["desired_state"][0]["id"]
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
        self.run_cli(
            "bootstrap", "--refresh", "--rtl-root", "rtl", "--verif-root", "verification",
            "--dut-top", "dut", "--dut-top-file", "rtl/dut.sv",
        )
        states = {item["id"]: item["status"] for item in self.run_cli("model", "show")["nodes"]}
        self.assertEqual(states[desired], "VALID")

    def test_valid_status_requires_real_evidence(self) -> None:
        self.bootstrap(); desired = self.design("VDOC", "--desired", "baseline")["desired_state"][0]["id"]
        result = self.invoke("record", "evidence", "--subject", desired, "--kind", "simulation",
                             "--source", "missing.json", "--verdict", "pass")
        self.assertEqual(result.returncode, 2)
        self.assertIn("evidence source", result.stderr)

    def test_vstim_reachability_uses_owned_probe_and_derived_verdict(self) -> None:
        self.bootstrap()
        plan = self.design(
            "VSTIM", "--desired", "reachability", "--evidence-claim", "reachability-evidence",
            "--desired", "determinism", "--evidence-claim", "determinism-evidence",
        )
        desired = [item["id"] for item in plan["desired_state"]]
        self.run_cli("review", "VSTIM")
        report = self.write_reachability_report()

        generic = self.invoke("prove", desired[0], report.name)
        self.assertEqual(generic.returncode, 2)
        self.assertIn("evidence 命令", generic.stderr)

        reached = self.run_cli("reachability", desired[0], report.name, "--claim", "reachability")
        deterministic = self.run_cli("reachability", desired[1], report.name, "--claim", "determinism")
        self.assertEqual(reached["claim"], "reachability")
        self.assertEqual(reached["verdict"], "PASS")
        self.assertTrue(reached["validation"]["reachability_ready"])
        self.assertEqual(deterministic["verdict"], "PASS")
        self.assertTrue(deterministic["validation"]["determinism_ready"])
        traced = self.run_cli("trace", desired[0])
        self.assertEqual(traced["evidence"][0]["data"]["claim"], "reachability")

        changed = self.run_cli("changed", report.name)
        self.assertIn(desired[0], changed["affected"])
        self.assertIn(desired[1], changed["affected"])

    def test_coverage_cannot_be_sole_vstim_reachability_authority(self) -> None:
        self.bootstrap()
        desired = self.design(
            "VSTIM", "--desired", "reachability",
            "--evidence-claim", "reachability-evidence",
        )["desired_state"][0]["id"]
        report = self.write_reachability_report(producer_kind="functional-coverage")
        result = self.invoke("reachability", desired, report.name, "--claim", "reachability")
        self.assertEqual(result.returncode, 2)
        self.assertIn("只能作为旁证", result.stderr)

    def test_node_dependency_blocks_only_subject_and_rejects_cycles(self) -> None:
        self.bootstrap()
        stim = self.design(
            "VSTIM", "--desired", "scenario reachable",
            "--evidence-claim", "reachability-evidence",
        )["desired_state"][0]["id"]
        cov = self.design(
            "VCOV", "--desired", "counter available",
            "--evidence-claim", "coverage-model",
        )["desired_state"][0]["id"]
        recorded = self.run_cli("record", "dependency", stim, cov)
        self.assertEqual(recorded["semantics"], "dependent-to-prerequisite")
        bypass = self.invoke("record", "edge", stim, cov, "--relation", "DEPENDS_ON")
        self.assertEqual(bypass.returncode, 2)
        self.assertIn("record dependency", bypass.stderr)
        closure = self.run_cli("closure", "--workstream", "VSTIM")
        wait = next(action for action in closure["actions"] if action["kind"] == "WAIT_FOR_DEPENDENCY")
        self.assertEqual(wait["target"], stim)
        self.assertEqual(wait["blocked_by"], [cov])
        self.assertIn(stim, {item["id"] for item in self.run_cli("impact", cov)["affected"]})

        cycle = self.invoke("record", "dependency", cov, stim)
        self.assertEqual(cycle.returncode, 2)
        self.assertIn("循环依赖", cycle.stderr)

        self.run_cli("waive", cov, "--reviewer", "alice", "--reason", "dependency test fixture")
        closure = self.run_cli("closure", "--workstream", "VSTIM")
        self.assertFalse(any(action["kind"] == "WAIT_FOR_DEPENDENCY" for action in closure["actions"]))
        self.assertTrue(any(action["target"] == stim for action in closure["actions"]))

    def test_planner_builds_revision_aware_default_capability_evidence_graph(self) -> None:
        self.bootstrap()
        plans = {}
        for workstream in ("VDOC", "VENV", "VREG", "VSTIM", "VCHK", "VCASE", "VCOV"):
            plans[workstream] = self.design(workstream)
        for plan in plans.values():
            template = plan["template"]
            roles = {desired["key"]: desired["role"] for desired in plan["desired_state"]}
            if plan["workstream"] == "VDOC":
                self.assertEqual(template["document_catalogs"], [
                    key for key, role in roles.items() if role == "document-catalog"
                ])
                self.assertEqual(template["capabilities"], [])
                self.assertEqual(template["closure_evidence"], [])
                self.assertEqual(set(roles.values()), {"document-catalog"})
                continue
            self.assertEqual(template["capabilities"], [
                key for key, role in roles.items() if role == "capability"
            ])
            self.assertEqual(template["closure_evidence"], [
                key for key, role in roles.items() if role == "closure-evidence"
            ])

        custom = self.design(
            "VCHK", "--desired", "custom name ending in evidence",
            "--evidence-claim", "scoreboard-evidence",
        )
        self.assertEqual(custom["desired_state"][0]["role"], "capability")

        current_vstim = {item["key"]: item["id"] for item in plans["VSTIM"]["desired_state"]}
        old_venv = {item["key"]: item["id"] for item in plans["VENV"]["desired_state"]}
        old_vreg = {item["key"]: item["id"] for item in plans["VREG"]["desired_state"]}
        model = self.run_cli("inspect")
        dependencies = {
            (edge["source"], edge["target"]) for edge in model["edges"]
            if edge["relation"] == "DEPENDS_ON" and edge["origin"] == "planner-default"
        }
        self.assertIn((current_vstim["stimulus-implementation"], old_venv["build-ready"]), dependencies)
        self.assertIn((old_vreg["executor-ready"], old_venv["run-ready"]), dependencies)
        self.assertIn((current_vstim["reachability-evidence"], old_vreg["executor-ready"]), dependencies)
        self.assertIn((current_vstim["determinism-evidence"], current_vstim["reachability-evidence"]), dependencies)

        revised_venv = {
            item["key"]: item["id"] for item in self.design("VENV")["desired_state"]
        }
        revised_vreg = {
            item["key"]: item["id"] for item in self.design("VREG")["desired_state"]
        }
        dependencies = {
            (edge["source"], edge["target"]) for edge in self.run_cli("inspect")["edges"]
            if edge["relation"] == "DEPENDS_ON" and edge["origin"] == "planner-default"
        }
        self.assertIn((current_vstim["stimulus-implementation"], revised_venv["build-ready"]), dependencies)
        self.assertNotIn((current_vstim["stimulus-implementation"], old_venv["build-ready"]), dependencies)
        self.assertIn((revised_vreg["executor-ready"], revised_venv["run-ready"]), dependencies)
        self.assertNotIn((revised_vreg["executor-ready"], old_venv["run-ready"]), dependencies)
        self.assertIn((current_vstim["reachability-evidence"], revised_vreg["executor-ready"]), dependencies)
        self.assertNotIn((current_vstim["reachability-evidence"], old_vreg["executor-ready"]), dependencies)

    def test_default_dependency_is_not_lost_when_prerequisite_is_unplanned(self) -> None:
        self.bootstrap()
        plan = self.design("VSTIM")
        closure = self.run_cli("closure", "--workstream", "VSTIM")
        missing = [action for action in closure["actions"] if action["kind"] == "PLAN_PREREQUISITE"]
        self.assertTrue(missing)
        blocked_by = {item for action in missing for item in action["blocked_by"]}
        self.assertIn("workstream:VDOC:desired:verification-plan", blocked_by)
        self.assertIn("workstream:VREG:desired:executor-ready", blocked_by)
        reachability = next(item["id"] for item in plan["desired_state"] if item["key"] == "reachability-evidence")
        recorded = self.run_cli("evidence", reachability, self.write_reachability_report().name)
        self.assertEqual(recorded["verdict"], "FAIL")
        self.assertTrue(any("prerequisite" in item for item in recorded["validation"]["blockers"]))

    def test_venv_smoke_must_match_current_environment_build(self) -> None:
        self.bootstrap()
        vdoc = self.design("VDOC")
        venv = self.design("VENV")
        vdoc_nodes = {item["key"]: item["id"] for item in vdoc["desired_state"]}
        nodes = {item["key"]: item["id"] for item in venv["desired_state"]}
        for node in (
            vdoc_nodes["verification-plan"], vdoc_nodes["tb-architecture"],
            nodes["interface-ready"], nodes["clock-reset-ready"],
            nodes["topology-ready"], nodes["observation-ready"],
        ):
            self.run_cli("waive", node, "--reviewer", "alice", "--reason", "VENV fixture")

        build_report = self.write_typed_report(
            "environment-build.json", "EnvironmentEvidence/1", "build-ready",
            {"compiled": True, "elaborated": True, "errors": 0,
             "build_log_digest": "$ARTIFACT_DIGEST",
             "environment_digest": "$ARTIFACT_DIGEST"},
        )
        self.assertEqual(
            self.run_cli("evidence", nodes["build-ready"], build_report.name)["verdict"], "PASS"
        )
        build_payload = json.loads(build_report.read_text(encoding="utf-8"))
        build_artifact = build_payload["artifacts"][0]

        run_report = self.write_typed_report(
            "environment-run.json", "EnvironmentEvidence/1", "run-ready",
            {"selftest_passed": True, "clean_exit": True, "failure_propagated": True,
             "command_digest": "$ARTIFACT_DIGEST", "collector_digest": "$ARTIFACT_DIGEST"},
        )
        self.assertEqual(
            self.run_cli("evidence", nodes["run-ready"], run_report.name)["verdict"], "PASS"
        )

        wrong_environment = self.root / "results/contracts/wrong-environment.sv"
        wrong_environment.write_text("module wrong_environment; endmodule\n", encoding="utf-8")
        smoke_log = self.root / "results/contracts/environment-smoke.log"
        smoke_wave = self.root / "results/contracts/environment-smoke.vcd"
        smoke_analysis = self.root / "results/contracts/environment-smoke-analysis.json"
        smoke_log.write_text("clock reset observation clean exit\n", encoding="utf-8")
        smoke_wave.write_text("$date test $end\n", encoding="utf-8")
        smoke_analysis.write_text(
            json.dumps(self.adapter_receipt("wavepeek")) + "\n", encoding="utf-8",
        )
        wrong_digest = hashlib.sha256(wrong_environment.read_bytes()).hexdigest()
        log_digest = hashlib.sha256(smoke_log.read_bytes()).hexdigest()
        wave_digest = hashlib.sha256(smoke_wave.read_bytes()).hexdigest()
        analysis_digest = hashlib.sha256(smoke_analysis.read_bytes()).hexdigest()
        smoke_payload = {
            "schema": "EnvironmentEvidence/1", "claim": "environment-smoke-evidence",
            "revision": "test-revision", "tool": "environment-smoke/1",
            "artifacts": [
                {"path": wrong_environment.relative_to(self.root).as_posix(), "sha256": wrong_digest,
                 "kind": "source", "analyzed_by": ["xverif"]},
                {"path": smoke_log.relative_to(self.root).as_posix(), "sha256": log_digest,
                 "kind": "simulation-log", "analyzed_by": ["xverif"]},
                {"path": smoke_wave.relative_to(self.root).as_posix(), "sha256": wave_digest,
                 "kind": "waveform", "analyzed_by": ["wavepeek"]},
                {"path": smoke_analysis.relative_to(self.root).as_posix(),
                 "sha256": analysis_digest, "kind": "analysis-report",
                 "analyzed_by": ["wavepeek"]},
            ],
            "result": {"clock_edges": 10, "reset_assertions": 1, "reset_deassertions": 1,
                       "observations": 1, "errors": 0, "fatals": 0, "timeout": False,
                       "clean_exit": True, "environment_digest": wrong_digest,
                       "log_digest": log_digest},
        }
        smoke_report = self.root / "environment-smoke.json"
        smoke_report.write_text(json.dumps(smoke_payload) + "\n", encoding="utf-8")
        rejected = self.run_cli(
            "evidence", nodes["environment-smoke-evidence"], smoke_report.name
        )
        self.assertEqual(rejected["verdict"], "FAIL")
        self.assertTrue(any(
            "environment digest" in blocker
            for blocker in rejected["validation"]["blockers"]
        ))

        smoke_payload["artifacts"][0] = build_artifact
        smoke_payload["result"]["environment_digest"] = build_artifact["sha256"]
        smoke_report.write_text(json.dumps(smoke_payload) + "\n", encoding="utf-8")
        self.assertEqual(
            self.run_cli("evidence", nodes["environment-smoke-evidence"], smoke_report.name)["verdict"],
            "PASS",
        )
        closure = self.run_cli("closure", "--workstream", "VENV")
        self.assertFalse(any(
            action["kind"] == "EXIT_CRITERION_BLOCKED" and
            any("environment digest" in blocker for blocker in action["blocked_by"])
            for action in closure["actions"]
        ))

    def test_standard_workstreams_require_typed_evidence_contracts(self) -> None:
        self.bootstrap()
        cases = (
            ("VENV", "environment-smoke-evidence", "environment-evidence.example.json"),
            ("VSTIM", "stimulus-implementation", "stimulus-capability-evidence.example.json"),
            ("VCHK", "scoreboard-evidence", "checking-evidence.example.json"),
            ("VCOV", "hole-analysis-evidence", "coverage-evidence.example.json"),
            ("VCASE", "targeted-evidence", "testcase-evidence.example.json"),
            ("VREG", "execution-evidence", "regression-evidence.example.json"),
        )
        for workstream, claim, filename in cases:
            standard = {item["key"]: item["id"] for item in self.design(workstream)["desired_state"]}[claim]
            target = self.materialize_evidence_example(filename)
            bypass = self.invoke("prove", standard, filename)
            self.assertEqual(bypass.returncode, 2)
            self.assertIn("evidence 命令", bypass.stderr)
            desired = self.design(
                workstream, "--desired", f"custom {claim}", "--evidence-claim", claim,
            )["desired_state"][0]["id"]
            recorded = self.run_cli("evidence", desired, filename, "--claim", claim)
            self.assertEqual(recorded["verdict"], "PASS", (workstream, recorded))
            self.assertTrue(recorded["validation"]["ready"])

    def test_standard_node_claim_cannot_be_overridden(self) -> None:
        self.bootstrap()
        plan = self.design("VCHK")
        scoreboard = next(item["id"] for item in plan["desired_state"] if item["key"] == "scoreboard-evidence")
        report = self.materialize_evidence_example("checking-evidence.example.json")
        rejected = self.invoke("evidence", scoreboard, report.name, "--claim", "reference-model-evidence")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("claim 固定为 scoreboard-evidence", rejected.stderr)

    def test_typed_evidence_rejects_arbitrary_pass_and_records_semantic_failure(self) -> None:
        self.bootstrap()
        desired = self.design(
            "VCHK", "--desired", "custom scoreboard evidence",
            "--evidence-claim", "scoreboard-evidence",
        )["desired_state"][0]["id"]
        arbitrary = self.root / "arbitrary.json"
        arbitrary.write_text('{"pass": true}\n', encoding="utf-8")
        rejected = self.invoke("evidence", desired, arbitrary.name, "--claim", "scoreboard-evidence")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("schema 必须是 CheckingEvidence/1", rejected.stderr)

        valid = self.materialize_evidence_example("checking-evidence.example.json")
        native = self.root / "results/checker/run.log"
        native.write_text("tampered after export\n", encoding="utf-8")
        mismatched = self.invoke("evidence", desired, valid.name, "--claim", "scoreboard-evidence")
        self.assertEqual(mismatched.returncode, 2)
        self.assertIn("artifact digest 不匹配", mismatched.stderr)

        valid = self.materialize_evidence_example("checking-evidence.example.json")
        report = json.loads(valid.read_text())
        report["result"]["mismatches"] = 1
        failed = self.root / "checker-failed.json"
        failed.write_text(json.dumps(report) + "\n", encoding="utf-8")
        recorded = self.run_cli("evidence", desired, failed.name, "--claim", "scoreboard-evidence")
        self.assertEqual(recorded["verdict"], "FAIL")
        self.assertFalse(recorded["validation"]["ready"])
        self.assertEqual(self.run_cli("inspect", desired)["nodes"][0]["status"], "INVALID")

    def test_native_evidence_artifact_change_invalidates_its_closure_node(self) -> None:
        self.bootstrap()
        desired = self.design(
            "VCHK", "--desired", "custom scoreboard evidence",
            "--evidence-claim", "scoreboard-evidence",
        )["desired_state"][0]["id"]
        report = self.materialize_evidence_example("checking-evidence.example.json")
        recorded = self.run_cli("evidence", desired, report.name, "--claim", "scoreboard-evidence")
        self.assertEqual(recorded["verdict"], "PASS")

        native = self.root / "results/checker/run.log"
        native.write_text("new simulator output\n", encoding="utf-8")
        changed = self.run_cli("changed", "results/checker/run.log")
        self.assertIn(desired, changed["affected"])
        self.assertEqual(self.run_cli("inspect", desired)["nodes"][0]["status"], "REVALIDATION_REQUIRED")

    def test_vdoc_unresolved_human_items_are_executable_exit_blockers(self) -> None:
        self.bootstrap()
        self.design("VDOC")
        self.run_cli("review", "VDOC")
        self.run_cli(
            "docs", "track", "verification_plan.md", "--id", "HD-001",
            "--kind", "human-decision", "--title", "选择 latency correctness policy",
            "--status", "PENDING",
        )
        closure = self.run_cli("closure", "--workstream", "VDOC")
        blockers = [item for item in closure["actions"] if item["kind"] == "EXIT_CRITERION_BLOCKED"]
        self.assertTrue(any("HD-001" in item["reason"] for item in blockers))
        self.run_cli(
            "docs", "track", "verification_plan.md", "--id", "HD-001",
            "--kind", "human-decision", "--title", "选择 latency correctness policy",
            "--status", "RESOLVED",
        )
        closure = self.run_cli("closure", "--workstream", "VDOC")
        self.assertFalse(any(item["kind"] == "EXIT_CRITERION_BLOCKED" for item in closure["actions"]))

    def test_vcase_matrix_and_implementation_are_cross_checked(self) -> None:
        self.bootstrap()
        plans = {name: self.design(name) for name in ("VDOC", "VREG", "VSTIM", "VCASE")}
        nodes = {
            name: {item["key"]: item["id"] for item in plan["desired_state"]}
            for name, plan in plans.items()
        }
        for node in (
            nodes["VDOC"]["feature-matrix"], nodes["VDOC"]["testcase-list"],
            nodes["VSTIM"]["stimulus-implementation"], nodes["VREG"]["executor-ready"],
        ):
            self.run_cli("waive", node, "--reviewer", "alice", "--reason", "cross-check fixture")
        matrix_report = self.write_typed_report(
            "case-matrix.json", "TestcaseEvidence/1", "case-matrix",
            {"required_features": ["VF.DEMO"],
             "mappings": [{"feature": "VF.DEMO", "cases": ["required_test"]}]},
        )
        self.assertEqual(
            self.run_cli("evidence", nodes["VCASE"]["case-matrix"], matrix_report.name)["verdict"], "PASS"
        )
        implementation_report = self.write_typed_report(
            "case-implementation.json", "TestcaseEvidence/1", "case-implementation",
            {"cases": [{"id": "different_test", "source_digest": "$ARTIFACT_DIGEST",
                        "registered": True, "compiled": True}]},
        )
        recorded = self.run_cli(
            "evidence", nodes["VCASE"]["case-implementation"], implementation_report.name
        )
        self.assertEqual(recorded["verdict"], "FAIL")
        self.assertTrue(any("required_test" in item for item in recorded["validation"]["blockers"]))

    def test_vreg_raw_failures_require_matching_triage_and_fresh_set_is_derived(self) -> None:
        self.bootstrap()
        plans = {
            name: self.design(name) for name in ("VDOC", "VENV", "VREG", "VSTIM", "VCHK", "VCASE", "VCOV")
        }
        nodes = {
            name: {item["key"]: item["id"] for item in plan["desired_state"]}
            for name, plan in plans.items()
        }
        execution_prerequisites = (
            nodes["VREG"]["executor-ready"], nodes["VENV"]["environment-smoke-evidence"],
            nodes["VSTIM"]["reachability-evidence"],
            nodes["VSTIM"]["determinism-evidence"], nodes["VCHK"]["reference-model-evidence"],
            nodes["VCHK"]["scoreboard-evidence"], nodes["VCHK"]["assertion-evidence"],
            nodes["VCASE"]["targeted-evidence"], nodes["VCOV"]["coverage-collection-evidence"],
            nodes["VCOV"]["hole-analysis-evidence"],
        )
        for node in execution_prerequisites:
            self.run_cli("waive", node, "--reviewer", "alice", "--reason", "regression fixture")

        execution_report = self.write_typed_report(
            "execution-with-failure.json", "RegressionEvidence/1", "execution-evidence",
            {"golden_required": True, "batch_seed": "17", "manifest_digest": "$ARTIFACT_DIGEST",
             "results": [{"test": "corner_test", "seed": 91, "verdict": "FAIL",
                          "log_digest": "$ARTIFACT_DIGEST"}]},
        )
        execution = self.run_cli("evidence", nodes["VREG"]["execution-evidence"], execution_report.name)
        self.assertEqual(execution["verdict"], "PASS")
        self.assertEqual(execution["validation"]["facts"]["failed_runs"][0]["test"], "corner_test")

        empty_triage = self.write_typed_report(
            "empty-triage.json", "RegressionEvidence/1", "triage-evidence", {"failures": []},
        )
        rejected = self.run_cli("evidence", nodes["VREG"]["triage-evidence"], empty_triage.name)
        self.assertEqual(rejected["verdict"], "FAIL")
        self.assertTrue(any("尚未 triage" in item for item in rejected["validation"]["blockers"]))

        triage_report = self.write_typed_report(
            "matching-triage.json", "RegressionEvidence/1", "triage-evidence",
            {"failures": [{"test": "corner_test", "original_seed": 91, "rerun_seed": 91,
                           "classification": "DUT_BUG", "disposition": "fixed",
                           "rerun_verdict": "PASS", "rerun_log_digest": "$ARTIFACT_DIGEST"}]},
        )
        triage = self.run_cli("evidence", nodes["VREG"]["triage-evidence"], triage_report.name)
        self.assertEqual(triage["verdict"], "PASS")

        fresh_report = self.write_typed_report(
            "fresh.json", "RegressionEvidence/1", "fresh-evidence",
            {"snapshot_revision": "test-revision"},
        )
        fresh = self.run_cli("evidence", nodes["VREG"]["fresh-evidence"], fresh_report.name)
        self.assertEqual(fresh["verdict"], "PASS", fresh)
        derived = fresh["validation"]["facts"]["required_nodes"]
        self.assertNotEqual(derived, [])
        self.assertTrue(all("id" in item and "status" in item for item in derived))

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
        custom_claims = {
            "VENV": "environment-smoke-evidence", "VSTIM": "reachability-evidence",
            "VCHK": "scoreboard-evidence", "VCOV": "hole-analysis-evidence",
            "VCASE": "targeted-evidence", "VREG": "execution-evidence",
        }
        for workstream in ("VDOC", "VENV", "VSTIM", "VCHK", "VCOV", "VCASE", "VREG"):
            arguments = ["plan", workstream, "--desired", f"{workstream} verified"]
            if workstream != "VDOC":
                arguments.extend(["--evidence-claim", custom_claims[workstream]])
            plan = self.run_cli(*arguments)
            self.run_cli("review", workstream)
            if workstream == "VDOC":
                self.run_cli("prove", plan["desired_state"][0]["id"], "evidence.json")
            else:
                self.run_cli("waive", plan["desired_state"][0]["id"], "--reviewer", "alice",
                             "--reason", "final-freeze command fixture")
            self.assertEqual(self.run_cli("freeze", workstream)["lifecycle"], "BASELINED")
        final = self.run_cli("freeze", "final")
        self.assertEqual(final["kind"], "FINAL")
        self.assertTrue((self.root / ".verif-harness" / final["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
