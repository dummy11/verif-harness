from __future__ import annotations

import hashlib
import io
import json
import tarfile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts/setup_wavepeek.py"


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *arguments], cwd=root, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


class SetupWavepeekTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        self.assertEqual(git(self.upstream, "init").returncode, 0)
        git(self.upstream, "config", "user.name", "Fixture")
        git(self.upstream, "config", "user.email", "fixture@example.invalid")
        license_text, cargo_lock = "Apache License fixture\n", "# lock fixture\n"
        (self.upstream / "LICENSE").write_text(license_text)
        (self.upstream / "Cargo.lock").write_text(cargo_lock)
        (self.upstream / "Cargo.toml").write_text('[package]\nname="wavepeek"\nversion="2.2.3"\n')
        git(self.upstream, "add", ".")
        self.assertEqual(git(self.upstream, "commit", "-m", "fixture").returncode, 0)
        self.commit = git(self.upstream, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(git(self.upstream, "tag", "v2.2.3").returncode, 0)
        self.project = self.root / "project"
        (self.project / "deps").mkdir(parents=True)
        self.archive = self.root / "wavepeek-fixture.tar.gz"
        binary = b'#!/usr/bin/env sh\nprintf "wavepeek v2.2.3\\n"\n'
        with tarfile.open(self.archive, "w:gz") as bundle:
            info = tarfile.TarInfo("wavepeek-fixture/wavepeek")
            info.mode = 0o755
            info.size = len(binary)
            bundle.addfile(info, io.BytesIO(binary))
        archive_sha = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        targets = [
            "aarch64-apple-darwin", "x86_64-apple-darwin",
            "aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu",
        ]
        lock = {
            "schema_version": 1, "name": "wavepeek", "repository": str(self.upstream),
            "commit": self.commit, "ref": "refs/tags/v2.2.3", "version": "2.2.3", "license": "Apache-2.0",
            "license_file_sha256": hashlib.sha256(license_text.encode()).hexdigest(),
            "cargo_lock_sha256": hashlib.sha256(cargo_lock.encode()).hexdigest(),
            "binary": "wavepeek", "cargo_features": [],
            "release_base_url": "https://github.com/kleverhq/wavepeek/releases/download/v2.2.3",
            "release_assets": {
                target: {"archive": f"wavepeek-{target}.tar.gz", "sha256": archive_sha}
                for target in targets
            },
        }
        (self.project / "deps/wavepeek.lock.json").write_text(json.dumps(lock))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def setup(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SETUP), "--project-root", str(self.project), "--archive", str(self.archive), "--json", *extra], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_install_and_recheck(self) -> None:
        installed = self.setup()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(json.loads(installed.stdout)["state"], "INSTALLED")
        checked = self.setup("--check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["state"], "READY")

    def test_dirty_source_fails_closed(self) -> None:
        self.assertEqual(self.setup().returncode, 0)
        (self.project / ".deps/wavepeek/local.txt").write_text("dirty\n")
        payload = json.loads(self.setup("--check").stdout)
        self.assertEqual(payload["state"], "BLOCKED")
        self.assertIn("managed source checkout is dirty or unreadable", payload["blockers"])

    def test_existing_unmanaged_state_is_preserved(self) -> None:
        source = self.project / ".deps/wavepeek"
        source.mkdir(parents=True)
        marker = source / "human.txt"
        marker.write_text("preserve\n")
        self.assertEqual(self.setup().returncode, 1)
        self.assertEqual(marker.read_text(), "preserve\n")


if __name__ == "__main__":
    unittest.main()
