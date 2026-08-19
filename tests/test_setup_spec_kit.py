from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts/setup_spec_kit.py"


class SetupSpecKitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        (self.project / "deps").mkdir(parents=True)
        lock = json.loads((ROOT / "deps/spec-kit.lock.json").read_text(encoding="utf-8"))
        (self.project / "deps/spec-kit.lock.json").write_text(
            json.dumps(lock), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_setup(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable, str(SETUP), "--project-root", str(self.project),
                "--json", *arguments,
            ],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def test_check_reports_missing_without_creating_dependency(self) -> None:
        checked = self.run_setup("--check")
        self.assertEqual(checked.returncode, 1)
        payload = json.loads(checked.stdout)
        self.assertEqual(payload["state"], "BLOCKED")
        self.assertIn("managed Spec Kit install missing", payload["blockers"][0])
        self.assertEqual(payload["supported_integrations"], ["codex", "kimi"])
        self.assertFalse((self.project / ".deps").exists())

    def test_existing_partial_state_is_preserved(self) -> None:
        source = self.project / ".deps/spec-kit"
        source.mkdir(parents=True)
        marker = source / "human.txt"
        marker.write_text("preserve\n", encoding="utf-8")
        checked = self.run_setup()
        self.assertEqual(checked.returncode, 1)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")

    def test_destination_must_remain_under_project(self) -> None:
        checked = self.run_setup("--check", "--source-dest", str(self.root / "outside"))
        self.assertEqual(checked.returncode, 1)
        self.assertIn("must remain under", checked.stderr)

    def test_lock_rejects_moving_ref(self) -> None:
        path = self.project / "deps/spec-kit.lock.json"
        lock = json.loads(path.read_text(encoding="utf-8"))
        lock["ref"] = "refs/heads/main"
        path.write_text(json.dumps(lock), encoding="utf-8")
        checked = self.run_setup("--check")
        self.assertEqual(checked.returncode, 1)
        self.assertIn("ref must match", checked.stderr)

    def test_lock_rejects_runtime_identity(self) -> None:
        path = self.project / "deps/spec-kit.lock.json"
        lock = json.loads(path.read_text(encoding="utf-8"))
        lock["integration"] = "codex"
        path.write_text(json.dumps(lock), encoding="utf-8")
        checked = self.run_setup("--check")
        self.assertEqual(checked.returncode, 1)
        self.assertIn("lock keys must be exactly", checked.stderr)


if __name__ == "__main__":
    unittest.main()
