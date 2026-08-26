from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integrations/spec-kit"


class SpecKitAssetsTest(unittest.TestCase):
    def test_lock_is_exact_and_reviewed(self) -> None:
        lock = json.loads((ROOT / "deps/spec-kit.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["repository"], "https://github.com/github/spec-kit.git")
        self.assertEqual(lock["ref"], "refs/tags/v0.16.4")
        self.assertEqual(lock["commit"], "d1f50fcbe684a4222059c4ba7f2d7eabcca87402")
        self.assertEqual(lock["python_requires"], ">=3.11")
        self.assertEqual(lock["schema_version"], 2)
        self.assertNotIn("integration", lock)

    def test_workflow_has_full_agentic_cycle_without_shell(self) -> None:
        workflow = (
            INTEGRATION / "workflows/verif-stage-lifecycle.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("type: shell", workflow)
        for command in (
            "speckit.constitution", "speckit.specify", "speckit.clarify", "speckit.plan",
            "speckit.checklist", "speckit.tasks", "speckit.analyze",
            "speckit.implement", "speckit.converge",
        ):
            self.assertIn(f"command: {command}", workflow)
        self.assertIn("authorize-execution", workflow)
        self.assertIn("inputs.stage == '0'", workflow)
        self.assertIn("review-convergence", workflow)
        self.assertIn('version: "0.3.0"', workflow)
        self.assertIn('any: ["codex", "kimi"]', workflow)
        self.assertIn('enum: ["codex", "kimi"]', workflow)
        verdict_inputs = (
            "review_constitution_verdict",
            "review_spec_verdict",
            "review_clarification_verdict",
            "review_plan_verdict",
            "authorize_execution_verdict",
            "review_convergence_verdict",
        )
        self.assertEqual(workflow.count("verdict_input:"), len(verdict_inputs))
        self.assertEqual(
            workflow.count('enum: ["", approve, reject]'), len(verdict_inputs)
        )
        for verdict_input in verdict_inputs:
            self.assertEqual(workflow.count(f"verdict_input: {verdict_input}"), 1)
        wrapper = (ROOT / "scripts/verif_harness.py").read_text(encoding="utf-8")
        self.assertIn('["preset", "add", "constitution-sync"', wrapper)
        self.assertIn("configure_spec_kit_chinese_docs.py", wrapper)
        self.assertIn('"docs-zh"', wrapper)
        self.assertIn("stdin=subprocess.DEVNULL if noninteractive else None", wrapper)

    def test_preset_carries_authority_and_traceability_guards(self) -> None:
        preset = INTEGRATION / "preset/rtl-verification"
        manifest = (preset / "preset.yml").read_text(encoding="utf-8")
        self.assertIn('id: "verif-harness-rtl"', manifest)
        self.assertIn('strategy: "prepend"', manifest)
        self.assertEqual(manifest.count('strategy: "replace"'), 5)
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(preset.rglob("*.md"))
        )
        self.assertIn("DUT RTL", combined)
        self.assertIn("REQ -> VF -> PLAN -> TASK -> MODE", combined)
        self.assertIn("Human approval", combined)

    def test_project_review_templates_default_to_simplified_chinese(self) -> None:
        preset = INTEGRATION / "preset/rtl-verification"
        templates = sorted((preset / "templates").glob("*.md"))
        self.assertEqual(len(templates), 5)
        for path in templates:
            source = path.read_text(encoding="utf-8")
            self.assertIn("默认使用简体中文", source, path.name)
            self.assertIn("原始引用保持原文", source, path.name)

        workflow = (
            INTEGRATION / "workflows/verif-stage-lifecycle.yml"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(workflow.count("使用简体中文"), 8)
        self.assertIn(".specify/", (
            ROOT / "integrations/spec-kit/README.md"
        ).read_text(encoding="utf-8"))

    def test_user_guide_defines_one_specification_authority(self) -> None:
        guide = (
            ROOT / "skills/verif-harness/docs/user_guide.md"
        ).read_text(encoding="utf-8")
        self.assertIn("最上层控制面", guide)
        self.assertIn("唯一可编辑规格事实源", guide)
        self.assertIn("immutable imported baseline", guide)
        self.assertIn("31 个模式", guide)


if __name__ == "__main__":
    unittest.main()
