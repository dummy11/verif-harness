#!/usr/bin/env python3
"""Run the bundled open-source readiness audit for this repository."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "skills/verif-harness/oss-readiness/scripts/audit_oss_readiness.py"


def main() -> int:
    command = [sys.executable, str(AUDIT), "--project-root", str(ROOT), "--require-community"]
    if (ROOT / ".git").is_dir():
        command.append("--history")
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
