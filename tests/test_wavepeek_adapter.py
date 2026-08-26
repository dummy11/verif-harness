from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "skills/verif-harness/wavepeek/scripts/wavepeek_adapter.py"
CLI = ROOT / "scripts/verif_harness.py"
FAKE = """#!/usr/bin/env python3
import json,sys,time
op=sys.argv[1]
if op=='--version': print('wavepeek v2.2.3')
elif op=='schema': print(json.dumps({'$schema':'fixture'}))
elif op=='docs': print('bad')
elif op=='skill': time.sleep(2)
else: print(json.dumps({'command':op,'data':{},'diagnostics':[]}))
"""


def request(operation: str = "schema", **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1, "operation": operation, "arguments": [operation],
        "working_directory": ".", "environment_keys": [], "timeout_seconds": 10,
        "output_format": "json", "acceptable_exit_codes": [0], "expected_artifacts": [],
    }
    value.update(overrides)
    return value


class WavepeekAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.source = self.root / "wavepeek"
        self.source.mkdir()
        self.binary = self.root / "wavepeek-bin"
        self.binary.write_text(FAKE)
        self.binary.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_adapter(self, value: dict[str, object], out: str = "evidence") -> tuple[subprocess.CompletedProcess[str], dict[str, object] | None]:
        request_path = self.project / "request.json"
        request_path.write_text(json.dumps(value))
        out_dir = self.project / out
        result = subprocess.run([sys.executable, str(ADAPTER), "run", "--project-root", str(self.project), "--request", str(request_path), "--wavepeek-root", str(self.source), "--wavepeek-binary", str(self.binary), "--out-dir", str(out_dir)], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        payload = json.loads((out_dir / "result.json").read_text()) if (out_dir / "result.json").is_file() else None
        return result, payload

    def test_root_cli_probe(self) -> None:
        result = subprocess.run([sys.executable, str(CLI), "wavepeek", "probe", "--project-root", str(self.project), "--wavepeek-root", str(self.source), "--wavepeek-binary", str(self.binary)], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["version"], "wavepeek v2.2.3")

    def test_schema_pass_records_hashes(self) -> None:
        result, payload = self.run_adapter(request())
        self.assertEqual(result.returncode, 0, result.stderr)
        assert payload is not None
        self.assertEqual(payload["state"], "PASS")
        self.assertEqual(payload["parsed_stdout"]["$schema"], "fixture")
        self.assertEqual(len(payload["tool_identity"]["binary_sha256"]), 64)

    def test_protocol_error_and_timeout_fail_closed(self) -> None:
        bad, payload = self.run_adapter(request("docs"), "bad")
        self.assertEqual(bad.returncode, 1)
        assert payload is not None
        self.assertEqual(payload["state"], "PROTOCOL_ERROR")
        timed, payload = self.run_adapter(request("skill", timeout_seconds=1), "timed")
        self.assertEqual(timed.returncode, 1)
        assert payload is not None
        self.assertEqual(payload["state"], "TIMEOUT")

    def test_rejects_unknown_key(self) -> None:
        value = request()
        value["extra"] = True
        result, payload = self.run_adapter(value)
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(payload)

    def test_non_executable_binary_fails_with_evidence(self) -> None:
        self.binary.chmod(0o644)
        result, payload = self.run_adapter(request(), "not-executable")
        self.assertEqual(result.returncode, 1)
        assert payload is not None
        self.assertEqual(payload["state"], "TOOL_NOT_FOUND")

    def test_private_glibc_descriptor_uses_loader_and_records_identity(self) -> None:
        deps = self.root / ".deps"
        binary = deps / "wavepeek-bin/wavepeek"
        binary.parent.mkdir(parents=True)
        binary.write_text(FAKE)
        binary.chmod(0o755)
        library = deps / "glibc-2.34/lib"
        library.mkdir(parents=True)
        loader = library / "ld-linux-x86-64.so.2"
        loader.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = --library-path ]; then shift 2; fi\n"
            "exec \"$@\"\n"
        )
        loader.chmod(0o755)
        libgcc = library / "libgcc_s.so.1"
        libgcc.write_text("fixture libgcc runtime\n")
        descriptor = {
            "schema_version": 2, "kind": "private-glibc", "version": "2.34",
            "root": "../glibc-2.34", "loader": "lib/ld-linux-x86-64.so.2",
            "loader_sha256": hashlib.sha256(loader.read_bytes()).hexdigest(),
            "library_dirs": ["lib"], "license": "LGPL-2.1-or-later",
            "libgcc_s": "lib/libgcc_s.so.1",
            "libgcc_s_sha256": hashlib.sha256(libgcc.read_bytes()).hexdigest(),
            "libgcc_license": "GPL-3.0-or-later WITH GCC-exception-3.1",
            "license_file_sha256": "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551",
            "licenses_file_sha256": "b33d0bd9f685b46853548814893a6135e74430d12f6d94ab3eba42fc591f83bc",
        }
        (binary.parent / "wavepeek-runtime.json").write_text(json.dumps(descriptor))
        self.binary = binary
        result, payload = self.run_adapter(request())
        self.assertEqual(result.returncode, 0, result.stderr)
        assert payload is not None
        self.assertEqual(payload["tool_identity"]["runtime"]["version"], "2.34")
        self.assertEqual(
            payload["tool_identity"]["runtime"]["libgcc_s_sha256"],
            descriptor["libgcc_s_sha256"],
        )
        self.assertEqual(payload["argv"][0], str(loader.resolve()))
        self.assertNotIn("LD_LIBRARY_PATH", payload["environment_keys"])


if __name__ == "__main__":
    unittest.main()
