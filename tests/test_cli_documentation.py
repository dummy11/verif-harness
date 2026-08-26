from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_ROOTS = (
    ROOT / "README.md",
    ROOT / "docs",
    ROOT / "integrations",
    ROOT / "skills/verif-harness",
)
NATIVE_PREFIXES = (
    "$verif-harness",
    "/skill:verif-harness",
    ".agents/skills/verif-harness/scripts/verif-harness",
    ".kimi-code/skills/verif-harness/scripts/verif-harness",
)


def markdown_files() -> list[Path]:
    files: list[Path] = []
    for root in DOC_ROOTS:
        if root.is_file():
            files.append(root)
        else:
            files.extend(root.rglob("*.md"))
    return sorted(set(files))


class CliDocumentationTest(unittest.TestCase):
    def test_native_skill_examples_inherit_setup_context(self) -> None:
        failures: list[str] = []
        for path in markdown_files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if not stripped.startswith(NATIVE_PREFIXES):
                    continue
                if "--project-root ." in stripped:
                    failures.append(f"{path.relative_to(ROOT)}:{number}: {stripped}")
                if re.search(r"\bbootstrap\b.*--integration\s+(?:codex|kimi)\b", stripped):
                    failures.append(f"{path.relative_to(ROOT)}:{number}: {stripped}")
        self.assertEqual(failures, [], "redundant setup context in native examples:\n" + "\n".join(failures))

    def test_evidence_and_freeze_examples_keep_required_project_roots(self) -> None:
        required = {
            "skills/verif-harness/xverif/INSTRUCTIONS.md": "--project-root . --request",
            "skills/verif-harness/change-control/INSTRUCTIONS.md": "--project-root . --audit-git",
            "skills/verif-harness/freeze-baseline/INSTRUCTIONS.md": "--project-root .",
        }
        for relative, marker in required.items():
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(marker, text, relative)


if __name__ == "__main__":
    unittest.main()
