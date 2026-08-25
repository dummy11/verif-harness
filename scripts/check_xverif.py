#!/usr/bin/env python3
"""Validate the managed xverif checkout and run a real xbit adapter smoke."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts/setup_xverif.py"
CLI = ROOT / "scripts/verif_harness.py"
REQUEST = ROOT / "skills/verif-harness/xverif/xverif-request.example.json"
LOCK = ROOT / "deps/xverif.lock.json"


def main() -> int:
    checked = subprocess.run(
        [sys.executable, str(SETUP), "--project-root", str(ROOT), "--check", "--json"],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if checked.returncode != 0:
        print(checked.stdout, end="")
        print(checked.stderr, end="", file=sys.stderr)
        return checked.returncode
    dependency = json.loads(checked.stdout)
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    managed_root = ROOT / ".deps/xverif"
    mcp = lock["mcp"]
    for relative in (
        mcp["source_root"],
        mcp["python_source_root"],
        f"{mcp['python_source_root']}/{mcp['package']}",
    ):
        if not (managed_root / relative).is_dir():
            print(f"ERROR: managed xverif MCP source is missing: {relative}", file=sys.stderr)
            return 1
    launcher = managed_root / mcp["launcher"]
    if not launcher.is_file():
        print(f"ERROR: managed xverif MCP launcher is missing: {mcp['launcher']}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="verif-harness-xverif-") as temporary:
        evidence = Path(temporary) / "evidence"
        result = subprocess.run(
            [
                sys.executable, str(CLI), "xverif", "run",
                "--project-root", str(ROOT), "--request", str(REQUEST),
                "--out-dir", str(evidence),
            ],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if result.returncode != 0:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            result_path = evidence / "result.json"
            if result_path.is_file():
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                print(
                    f"ERROR: xbit adapter smoke state is {payload['state']}",
                    file=sys.stderr,
                )
                for blocker in payload.get("blockers", []):
                    print(f"ERROR: {blocker}", file=sys.stderr)
                stderr_path = evidence / "stderr.log"
                if stderr_path.is_file():
                    native_stderr = stderr_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).strip()
                    if native_stderr:
                        print("xbit stderr:", file=sys.stderr)
                        print(native_stderr, file=sys.stderr)
            return result.returncode
        payload = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
        if payload["state"] != "PASS":
            print(f"ERROR: xbit adapter smoke state is {payload['state']}", file=sys.stderr)
            return 1
        if payload["tool_identity"]["git_commit"] != lock["commit"]:
            print("ERROR: adapter evidence commit does not match xverif lock", file=sys.stderr)
            return 1
        if payload["parsed_stdout"].get("ok") is not True:
            print("ERROR: xbit native response is not ok", file=sys.stderr)
            return 1
    print(
        "Managed xverif PASS: "
        f"{dependency['commit']} with real xbit adapter smoke and MCP source validation"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
