from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "deps/runtime.lock.json"
SETUP = ROOT / "scripts/setup_managed.sh"
RUNTIME = ROOT / "scripts/setup_managed_runtime.py"
LAUNCHER = ROOT / "scripts/managed-python"


class SetupManagedTest(unittest.TestCase):
    def test_runtime_lock_pins_supported_python_assets(self) -> None:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        self.assertEqual(lock["schema_version"], 1)
        self.assertEqual(lock["name"], "verif-harness-managed-runtime")
        self.assertEqual(lock["python"]["version"], "3.12.11")
        self.assertEqual(lock["python"]["release"], "20251007")
        self.assertEqual(
            set(lock["python"]["assets"]),
            {
                "aarch64-apple-darwin", "x86_64-apple-darwin",
                "aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu",
            },
        )
        for asset in lock["python"]["assets"].values():
            self.assertEqual(len(asset["sha256"]), 64)

    def test_requirements_lock_hash_and_mcp_version_are_pinned(self) -> None:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        requirements = ROOT / lock["python_packages"]["requirements"]
        observed = hashlib.sha256(requirements.read_bytes()).hexdigest()
        self.assertEqual(observed, lock["python_packages"]["requirements_sha256"])
        self.assertIn("mcp==1.29.1", requirements.read_text(encoding="utf-8"))
        self.assertEqual(lock["python_packages"]["mcp_version"], "1.29.1")

    def test_shell_bootstrap_matches_locked_asset_hashes(self) -> None:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        source = SETUP.read_text(encoding="utf-8")
        for asset in lock["python"]["assets"].values():
            self.assertIn(asset["sha256"], source)
        self.assertIn("python-build-standalone/releases/download", source)
        self.assertIn("sha256sum", source)
        self.assertIn("shasum", source)
        self.assertIn("curl", source)
        self.assertIn("wget", source)
        self.assertNotIn("sudo", source)
        self.assertNotIn("python3 --version", source)

    def test_python_runtime_loader_accepts_the_repository_lock(self) -> None:
        spec = importlib.util.spec_from_file_location("managed_runtime_under_test", RUNTIME)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        lock = module.load_lock(ROOT)
        self.assertEqual(lock["python_packages"]["mcp_requirement"], "mcp[cli]==1.29.1")

    def test_minimal_host_contract_is_explicit(self) -> None:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            lock["host_contract"]["required_commands"],
            [
                "awk", "bash", "cp", "dirname", "git", "ln", "mkdir", "mv",
                "readlink", "rm", "tar", "uname",
            ],
        )
        self.assertEqual(
            lock["host_contract"]["conditional_private_glibc_build_commands"],
            ["as", "bison", "gcc", "gawk", "ld", "make", "sed"],
        )

    def test_managed_python_launcher_never_falls_back_to_host_python(self) -> None:
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("setup_managed.sh", source)
        self.assertIn("--check", source)
        self.assertIn('exec "$python_cmd" "$@"', source)
        self.assertNotIn("python3", source)


if __name__ == "__main__":
    unittest.main()
