from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "skills/verif-harness/scripts/verif-harness"


class SkillLauncherTest(unittest.TestCase):
    def make_package(self, root: Path) -> Path:
        package = root / "package"
        launcher = package / "skills/verif-harness/scripts/verif-harness"
        launcher.parent.mkdir(parents=True)
        shutil.copy2(LAUNCHER, launcher)
        launcher.chmod(0o755)

        scripts = package / "scripts"
        scripts.mkdir()
        managed_python = scripts / "managed-python"
        managed_python.write_text(
            '#!/usr/bin/env bash\nprintf "arg=%s\\n" "$@"\n',
            encoding="utf-8",
        )
        managed_python.chmod(0o755)
        (scripts / "verif_harness.py").touch()
        core = package / "verif_harness"
        core.mkdir()
        (core / "__init__.py").touch()
        (core / "store.py").touch()
        return package

    def test_kimi_workspace_link_resolves_complete_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = self.make_package(root)
            workspace = root / "workspace"
            skill_parent = workspace / ".kimi-code/skills"
            skill_parent.mkdir(parents=True)
            (skill_parent / "verif-harness").symlink_to(
                package / "skills/verif-harness", target_is_directory=True
            )

            result = subprocess.run(
                [
                    str(skill_parent / "verif-harness/scripts/verif-harness"),
                    "bootstrap",
                    "--project-root",
                    ".",
                    "--runtime",
                    "kimi",
                ],
                cwd=workspace,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.splitlines(),
                [
                    f"arg={package.resolve() / 'scripts/verif_harness.py'}",
                    "arg=bootstrap",
                    "arg=--project-root",
                    "arg=.",
                    "arg=--runtime",
                    "arg=kimi",
                ],
            )

    def test_incomplete_package_fails_without_cloning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = self.make_package(root)
            (package / "verif_harness/store.py").unlink()

            result = subprocess.run(
                [str(package / "skills/verif-harness/scripts/verif-harness"), "probe"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("does not resolve to a complete verif-harness checkout", result.stderr)
            self.assertIn("do not clone into the workspace", result.stderr)


if __name__ == "__main__":
    unittest.main()
