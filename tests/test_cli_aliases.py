from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verif_harness_cli", ROOT / "scripts/verif_harness.py")
CLI = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CLI)


class CliAliasTest(unittest.TestCase):
    def test_public_short_aliases_map_to_spec_kit_commands(self) -> None:
        self.assertEqual(CLI.COMMAND_ALIASES["probe"], ("spec-kit", "probe"))
        self.assertEqual(CLI.COMMAND_ALIASES["bootstrap"], ("spec-kit", "bootstrap"))
        self.assertEqual(CLI.COMMAND_ALIASES["stage"], ("spec-kit", "stage"))
        self.assertEqual(CLI.COMMAND_ALIASES["workflow-status"], ("spec-kit", "status"))
        self.assertEqual(CLI.COMMAND_ALIASES["workflow-resume"], ("spec-kit", "resume"))
        self.assertEqual(CLI.COMMAND_ALIASES["evidence"], ("xverif",))
        self.assertEqual(CLI.COMMAND_ALIASES["waveform"], ("wavepeek",))

    def test_alias_rewrite_preserves_arguments(self) -> None:
        raw = ["bootstrap", "--project-root", ".", "--integration", "codex"]
        alias = CLI.COMMAND_ALIASES[raw[0]]
        self.assertEqual([*alias, *raw[1:]], [
            "spec-kit", "bootstrap", "--project-root", ".", "--integration", "codex",
        ])


if __name__ == "__main__":
    unittest.main()
