from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "configure_response_language", ROOT / "scripts/configure_response_language.py"
)
assert SPEC is not None and SPEC.loader is not None
LANGUAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LANGUAGE)


class ResponseLanguageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_codex_adds_project_developer_instructions(self) -> None:
        config = self.root / ".codex/config.toml"
        config.parent.mkdir()
        config.write_text('approval_policy = "never"\n', encoding="utf-8")

        LANGUAGE.configure_codex(self.root)

        source = config.read_text(encoding="utf-8")
        self.assertTrue(source.startswith('developer_instructions = "'))
        self.assertIn("默认使用简体中文", source)
        self.assertIn('approval_policy = "never"', source)

    def test_codex_preserves_existing_developer_instructions(self) -> None:
        config = self.root / ".codex/config.toml"
        config.parent.mkdir()
        original = 'developer_instructions = "team policy"\n'
        config.write_text(original, encoding="utf-8")

        LANGUAGE.configure_codex(self.root)

        self.assertEqual(config.read_text(encoding="utf-8"), original)

    def test_kimi_preserves_existing_content_and_is_idempotent(self) -> None:
        instructions = self.root / ".kimi-code/AGENTS.md"
        instructions.parent.mkdir()
        instructions.write_text("# Team policy\n", encoding="utf-8")

        LANGUAGE.configure_kimi(self.root)
        first = instructions.read_text(encoding="utf-8")
        LANGUAGE.configure_kimi(self.root)

        self.assertIn("# Team policy", first)
        self.assertIn("默认使用简体中文", first)
        self.assertEqual(instructions.read_text(encoding="utf-8"), first)

    def test_kimi_rejects_malformed_managed_block(self) -> None:
        instructions = self.root / ".kimi-code/AGENTS.md"
        instructions.parent.mkdir()
        instructions.write_text(LANGUAGE.KIMI_BLOCK_BEGIN, encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "malformed managed language block"):
            LANGUAGE.configure_kimi(self.root)


if __name__ == "__main__":
    unittest.main()
