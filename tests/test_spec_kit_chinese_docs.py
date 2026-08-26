from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "configure_spec_kit_chinese_docs",
    ROOT / "scripts/configure_spec_kit_chinese_docs.py",
)
assert SPEC is not None and SPEC.loader is not None
DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCS)


class SpecKitChineseDocsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.specify = self.root / ".specify"
        (self.specify / "templates").mkdir(parents=True)
        translated = self.specify / "presets/verif-harness-rtl/templates"
        translated.mkdir(parents=True)
        (self.specify / "templates/spec-template.md").write_text(
            "# Feature Specification\n", encoding="utf-8"
        )
        (translated / "spec-template.md").write_text(
            "# 验证规格\n\n默认使用简体中文。\n", encoding="utf-8"
        )
        command = self.specify / "presets/verif-harness-rtl/commands"
        command.mkdir(parents=True)
        (command / "speckit.implement.md").write_text(
            "# Implement command\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_builds_non_executable_mirror_with_hash_manifest(self) -> None:
        manifest = DOCS.build_mirror(self.root, ROOT)
        mirror = self.root / ".specify/docs/zh-CN"
        translated = mirror / "templates/spec-template.md"
        summary = mirror / "presets/verif-harness-rtl/commands/speckit.implement.md"

        self.assertIn("默认使用简体中文", translated.read_text(encoding="utf-8"))
        self.assertIn("中文导读", summary.read_text(encoding="utf-8"))
        self.assertEqual(manifest["counts"]["full"], 1)
        self.assertEqual(manifest["counts"]["source-is-chinese"], 1)
        self.assertEqual(manifest["counts"]["summary"], 1)
        self.assertEqual(manifest["counts"]["pending"], 0)
        persisted = json.loads((mirror / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(persisted["execution_authority"])
        self.assertEqual(len(persisted["entries"]), 3)

    def test_unknown_markdown_is_marked_pending(self) -> None:
        unknown = self.specify / "presets/new-preset/README.md"
        unknown.parent.mkdir(parents=True)
        unknown.write_text("# New upstream documentation\n", encoding="utf-8")

        manifest = DOCS.build_mirror(self.root, ROOT)

        self.assertEqual(manifest["counts"]["pending"], 1)
        destination = self.root / ".specify/docs/zh-CN/presets/new-preset/README.md"
        self.assertIn("待补充中文导读", destination.read_text(encoding="utf-8"))

    def test_refresh_does_not_index_its_own_mirror(self) -> None:
        first = DOCS.build_mirror(self.root, ROOT)
        second = DOCS.build_mirror(self.root, ROOT)
        self.assertEqual(len(first["entries"]), len(second["entries"]))

    def test_rejects_symlinked_mirror_parent(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (self.specify / "docs").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "symlinked"):
            DOCS.build_mirror(self.root, ROOT)


if __name__ == "__main__":
    unittest.main()
