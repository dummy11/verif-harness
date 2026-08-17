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

    def test_preset_carries_authority_and_traceability_guards(self) -> None:
        preset = INTEGRATION / "preset/rtl-verification"
        manifest = (preset / "preset.yml").read_text(encoding="utf-8")
        self.assertIn('id: "verif-harness-rtl"', manifest)
        self.assertIn('strategy: "prepend"', manifest)
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(preset.rglob("*.md"))
        )
        self.assertIn("DUT RTL", combined)
        self.assertIn("REQ -> VF -> PLAN -> TASK -> MODE", combined)
        self.assertIn("Human approval", combined)

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
