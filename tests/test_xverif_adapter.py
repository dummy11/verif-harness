from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "skills/verif-harness/xverif/scripts/xverif_adapter.py"
CLI = ROOT / "scripts/verif_harness.py"


FAKE_TOOL = """#!/usr/bin/env python3
import json
import pathlib
import sys
import time

operation = sys.argv[1]
if operation == "emit":
    target = pathlib.Path(sys.argv[sys.argv.index("--artifact") + 1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"artifact": "PASS"}\\n', encoding="utf-8")
    print(json.dumps({"state": "PASS", "operation": operation}, sort_keys=True))
elif operation == "xout":
    print("@xbit.fixture.v1\\n\\nsummary:\\n  state: PASS")
elif operation == "bad-json":
    print("not-json")
elif operation == "fail":
    print(json.dumps({"state": "FAIL"}))
    raise SystemExit(7)
elif operation == "sleep":
    time.sleep(2)
else:
    print(json.dumps({"state": "PASS", "operation": operation}, sort_keys=True))
"""


def request(operation: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "tool": "xbit",
        "operation": operation,
        "arguments": [operation],
        "stdin_path": None,
        "working_directory": ".",
        "environment_keys": [],
        "timeout_seconds": 10,
        "output_format": "json",
        "acceptable_exit_codes": [0],
        "expected_artifacts": [],
    }
    value.update(overrides)
    return value


class XverifAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.xverif = self.root / "xverif-suite"
        tools = self.xverif / "tools"
        tools.mkdir(parents=True)
        self.tool = tools / "xbit"
        self.tool.write_text(FAKE_TOOL, encoding="utf-8")
        self.tool.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_request(self, value: dict[str, object]) -> Path:
        path = self.project / "request.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def run_adapter(
        self, value: dict[str, object], out_name: str = "evidence"
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object] | None]:
        request_path = self.write_request(value)
        out_dir = self.project / out_name
        result = subprocess.run(
            [
                sys.executable, str(ADAPTER), "run",
                "--project-root", str(self.project),
                "--request", str(request_path),
                "--xverif-root", str(self.xverif),
                "--out-dir", str(out_dir),
            ],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        payload = None
        if (out_dir / "result.json").is_file():
            payload = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
        return result, payload

    def test_probe_and_root_cli_delegation(self) -> None:
        result = subprocess.run(
            [
                sys.executable, str(CLI), "xverif", "probe",
                "--xverif-root", str(self.xverif), "--tool", "xbit",
            ],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["state"], "PASS")
        self.assertEqual(payload["tool"], "xbit")
        self.assertEqual(len(payload["wrapper_sha256"]), 64)

    def test_project_managed_dependency_is_discovered(self) -> None:
        managed = self.project / ".deps/xverif/tools"
        managed.mkdir(parents=True)
        wrapper = managed / "xbit"
        wrapper.write_text(FAKE_TOOL, encoding="utf-8")
        wrapper.chmod(0o755)
        request_path = self.write_request(request("doctor"))
        out_dir = self.project / "managed-evidence"
        result = subprocess.run(
            [
                sys.executable, str(ADAPTER), "run",
                "--project-root", str(self.project),
                "--request", str(request_path),
                "--out-dir", str(out_dir),
            ],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["state"], "PASS")
        self.assertEqual(payload["tool_identity"]["xverif_root"], str(managed.parent.resolve()))

    def test_pass_captures_json_logs_and_artifact_hash(self) -> None:
        relative = "result/summary.json"
        result, payload = self.run_adapter(
            request(
                "emit", arguments=["emit", "--artifact", relative],
                expected_artifacts=[relative],
            )
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        assert payload is not None
        self.assertEqual(payload["state"], "PASS")
        self.assertEqual(payload["parsed_stdout"]["operation"], "emit")
        self.assertEqual(payload["artifacts"][0]["path"], relative)
        self.assertEqual(len(payload["artifacts"][0]["sha256"]), 64)
        self.assertEqual(payload["environment_keys"], [])

    def test_xout_is_preserved_without_parsing(self) -> None:
        result, payload = self.run_adapter(
            request("xout", output_format="xout"), out_name="xout-evidence"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        assert payload is not None
        self.assertEqual(payload["state"], "PASS")
        self.assertIsNone(payload["parsed_stdout"])
        stdout = (self.project / "xout-evidence/stdout.log").read_text(encoding="utf-8")
        self.assertTrue(stdout.startswith("@xbit.fixture.v1"))

    def test_stdin_is_hashed_but_not_embedded(self) -> None:
        stdin = self.project / "request-input.json"
        stdin.write_text('{"action":"fixture"}\n', encoding="utf-8")
        result, payload = self.run_adapter(
            request("doctor", stdin_path="request-input.json"), out_name="stdin-evidence"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        assert payload is not None
        self.assertEqual(payload["stdin"]["path"], "request-input.json")
        self.assertNotIn("action", json.dumps(payload["stdin"]))

    def test_nonzero_exit_is_fail(self) -> None:
        result, payload = self.run_adapter(request("fail"))
        self.assertEqual(result.returncode, 1)
        assert payload is not None
        self.assertEqual(payload["state"], "FAIL")
        self.assertEqual(payload["exit_code"], 7)

    def test_invalid_json_is_protocol_error(self) -> None:
        result, payload = self.run_adapter(request("bad-json"))
        self.assertEqual(result.returncode, 1)
        assert payload is not None
        self.assertEqual(payload["state"], "PROTOCOL_ERROR")

    def test_timeout_is_fail_closed(self) -> None:
        result, payload = self.run_adapter(request("sleep", timeout_seconds=1))
        self.assertEqual(result.returncode, 1)
        assert payload is not None
        self.assertEqual(payload["state"], "TIMEOUT")

    def test_missing_artifact_is_fail_closed(self) -> None:
        result, payload = self.run_adapter(request("doctor", expected_artifacts=["missing.json"]))
        self.assertEqual(result.returncode, 1)
        assert payload is not None
        self.assertEqual(payload["state"], "MISSING_ARTIFACT")

    def test_rejects_unknown_request_key_before_running(self) -> None:
        value = request("doctor")
        value["extra"] = True
        result, payload = self.run_adapter(value)
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(payload)
        self.assertIn("request keys must be exactly", result.stderr)

    def test_refuses_to_overwrite_evidence_directory(self) -> None:
        (self.project / "evidence").mkdir()
        result, payload = self.run_adapter(request("doctor"))
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(payload)
        self.assertIn("refusing existing output directory", result.stderr)

    def test_tool_not_found_has_auditable_result(self) -> None:
        result, payload = self.run_adapter(
            request("doctor", tool="xdebug"), out_name="missing-tool"
        )
        self.assertEqual(result.returncode, 1)
        assert payload is not None
        self.assertEqual(payload["state"], "TOOL_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
