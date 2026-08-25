from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts/check_runtime_versions.py"
LAUNCHER = ROOT / "scripts/runtime-versions"


class RuntimeVersionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("runtime_versions_under_test", CHECK)
        assert spec is not None and spec.loader is not None
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        spec.loader.exec_module(cls.module)

    def test_version_parser_and_minimum_comparison(self) -> None:
        self.assertEqual(self.module.parsed_version("GNU bash 3.2.57"), (3, 2, 57))
        self.assertTrue(self.module.at_least("git version 2.50.1", ">=2.25"))
        self.assertFalse(self.module.at_least("GNU Make 3.81", ">=4.0"))

    def test_marker_filter_matches_managed_platform(self) -> None:
        self.assertTrue(self.module.marker_applies("implementation_name != 'PyPy'"))
        self.assertFalse(self.module.marker_applies("sys_platform == 'win32'"))

    def test_required_inventory_covers_locked_and_host_boundaries(self) -> None:
        source = CHECK.read_text(encoding="utf-8")
        for component in (
            "Managed CPython", "MCP Python SDK", "Python package lock",
            "xverif", "xverif MCP API", "POSIX bootstrap tools", "WavePeek",
            "WavePeek glibc", "GitHub Spec Kit", "Bash", "Git",
            "HTTPS downloader", "SHA-256 tool", "Verilator", "Synopsys VCS",
            "LSF bsub", "Verdi/NPI SDK", "UVM", "Codex CLI", "Kimi CLI",
        ):
            self.assertIn(component, source)

    def test_runtime_lock_records_conditional_build_versions(self) -> None:
        lock = json.loads((ROOT / "deps/runtime.lock.json").read_text(encoding="utf-8"))
        versions = lock["host_contract"]["version_requirements"]
        self.assertEqual(versions["private_glibc_gcc"], ">=6.2")
        self.assertEqual(versions["private_glibc_make"], ">=4.0")
        self.assertEqual(versions["private_glibc_binutils"], ">=2.25")
        self.assertEqual(versions["private_glibc_texinfo"], ">=4.7")
        self.assertEqual(versions["verilator"], "5.x")

    def test_launcher_uses_managed_python(self) -> None:
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("scripts/managed-python", source)
        self.assertIn("check_runtime_versions.py", source)
        self.assertNotIn("python3", source)


if __name__ == "__main__":
    unittest.main()
