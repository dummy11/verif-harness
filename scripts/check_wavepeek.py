#!/usr/bin/env python3
"""Validate managed WavePeek and run a real schema adapter smoke."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts/setup_wavepeek.py"
CLI = ROOT / "scripts/verif_harness.py"
REQUEST = ROOT / "skills/verif-harness/wavepeek/wavepeek-request.example.json"
LOCK = ROOT / "deps/wavepeek.lock.json"


def main() -> int:
    checked = subprocess.run([sys.executable, str(SETUP), "--project-root", str(ROOT), "--check", "--json"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if checked.returncode != 0:
        print(checked.stdout, end="")
        print(checked.stderr, end="", file=sys.stderr)
        return checked.returncode
    dependency = json.loads(checked.stdout)
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="verif-harness-wavepeek-") as temporary:
        evidence = Path(temporary) / "evidence"
        result = subprocess.run([sys.executable, str(CLI), "wavepeek", "run", "--project-root", str(ROOT), "--request", str(REQUEST), "--out-dir", str(evidence)], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            return result.returncode
        payload = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
        if payload["state"] != "PASS" or payload["tool_identity"]["git_commit"] != lock["commit"]:
            print("ERROR: WavePeek adapter identity or smoke state mismatch", file=sys.stderr)
            return 1
        schema = payload["parsed_stdout"]
        if not isinstance(schema, dict) or "$schema" not in schema:
            print("ERROR: WavePeek schema smoke did not return a JSON Schema", file=sys.stderr)
            return 1
    print(f"Managed WavePeek PASS: {dependency['commit']} with real schema adapter smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
