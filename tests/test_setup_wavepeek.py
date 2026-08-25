from __future__ import annotations

import hashlib
import importlib.util
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
            "schema_version": 2, "name": "wavepeek", "repository": str(self.upstream),
            "commit": self.commit, "ref": "refs/tags/v2.2.3", "version": "2.2.3", "license": "Apache-2.0",
            "license_file_sha256": hashlib.sha256(license_text.encode()).hexdigest(),
            "cargo_lock_sha256": hashlib.sha256(cargo_lock.encode()).hexdigest(),
            "binary": "wavepeek", "cargo_features": [],
            "private_glibc": {
                "minimum_host_version": "2.34", "version": "2.34",
                "source_url": "https://ftp.gnu.org/gnu/glibc/glibc-2.34.tar.xz",
                "source_sha256": "44d26a1fe20b8853a48f470ead01e4279e869ac149b195dda4e44a195d981ab2",
                "license": "LGPL-2.1-or-later", "license_file": "COPYING.LIB",
                "license_file_sha256": "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551",
                "licenses_file": "LICENSES",
                "licenses_file_sha256": "b33d0bd9f685b46853548814893a6135e74430d12f6d94ab3eba42fc591f83bc",
                "configure_args": ["--disable-werror"],
            },
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

    def test_old_linux_glibc_requires_private_runtime(self) -> None:
        spec = importlib.util.spec_from_file_location("setup_wavepeek_under_test", SETUP)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(
            module.requires_private_glibc(
                "x86_64-unknown-linux-gnu", "2.28", "2.34"
            )
        )
        self.assertFalse(
            module.requires_private_glibc(
                "x86_64-unknown-linux-gnu", "2.34", "2.34"
            )
        )
        self.assertFalse(
            module.requires_private_glibc(
                "x86_64-apple-darwin", None, "2.34"
            )
        )

    def test_private_glibc_build_tool_minimum_comparison(self) -> None:
        spec = importlib.util.spec_from_file_location("setup_wavepeek_tool_versions", SETUP)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(module.tool_version_at_least("gcc (GCC) 6.2.0", "6.2"))
        self.assertFalse(module.tool_version_at_least("GNU Make 3.81", "4.0"))
        self.assertEqual(
            module.PRIVATE_GLIBC_BUILD_REQUIREMENTS,
            {
                "as": "2.25", "bison": "2.7", "gcc": "6.2",
                "gawk": "3.1.2", "ld": "2.25", "make": "4.0",
                "sed": "3.02",
            },
        )

    def test_private_loader_runs_wavepeek_without_global_library_path(self) -> None:
        spec = importlib.util.spec_from_file_location("setup_wavepeek_under_test", SETUP)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        deps = self.project / ".deps"
        binary = deps / "wavepeek-bin/wavepeek"
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\nprintf "wavepeek v2.2.3\\n"\n')
        binary.chmod(0o755)
        glibc = deps / "glibc-2.34"
        library = glibc / "lib"
        library.mkdir(parents=True)
        loader = library / "ld-linux-x86-64.so.2"
        loader.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = --version ]; then printf 'ld.so 2.34\\n'; exit 0; fi\n"
            "if [ \"$1\" = --library-path ]; then shift 2; fi\n"
            "exec \"$@\"\n"
        )
        loader.chmod(0o755)
        (library / "libc.so.6").write_text("fixture\n")
        license_text = "fixture private glibc license\n"
        license_path = glibc / "share/licenses/glibc/COPYING.LIB"
        license_path.parent.mkdir(parents=True)
        license_path.write_text(license_text)
        licenses_text = "fixture private glibc notices\n"
        (license_path.parent / "LICENSES").write_text(licenses_text)
        contract = {
            "version": "2.34", "license": "LGPL-2.1-or-later",
            "license_file": "COPYING.LIB",
            "license_file_sha256": hashlib.sha256(license_text.encode()).hexdigest(),
            "licenses_file": "LICENSES",
            "licenses_file_sha256": hashlib.sha256(licenses_text.encode()).hexdigest(),
        }
        blockers, descriptor = module.validate_private_glibc(
            glibc, "x86_64-unknown-linux-gnu", contract
        )
        self.assertEqual(blockers, [])
        self.assertIsNotNone(descriptor)
        descriptor["license_file_sha256"] = (
            "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551"
        )
        descriptor["licenses_file_sha256"] = (
            "b33d0bd9f685b46853548814893a6135e74430d12f6d94ab3eba42fc591f83bc"
        )
        module.write_runtime_descriptor(binary, descriptor)
        blockers, observed = module.validate_binary(binary, {"version": "2.2.3"})
        self.assertEqual(blockers, [])
        self.assertEqual(observed, "wavepeek v2.2.3")


if __name__ == "__main__":
    unittest.main()
