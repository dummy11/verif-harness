#!/usr/bin/env python3
"""Read-only v1 project health audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verif_harness.store import HarnessError, ProjectStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    store = ProjectStore(args.project_root)
    if not store.initialized:
        payload = {
            "project_root": str(args.project_root.resolve()),
            "status": "INFO",
            "findings": [{"severity": "INFO", "code": "BOOTSTRAP_REQUIRED", "message": "No v1 project model; bootstrap is the next mode."}],
            "next_mode": "bootstrap",
        }
    else:
        try:
            scan = store.audit()
            payload = {
                "project_root": str(args.project_root.resolve()),
                "status": scan["status"],
                "findings": [
                    {"severity": "ERROR", "code": "MODEL_FILE_MISSING", "message": item}
                    for item in scan["missing_files"]
                ],
                "next_mode": "closure" if scan["open_findings"] else "plan",
                "summary": store.status(),
            }
        except HarnessError as exc:
            payload = {"project_root": str(args.project_root.resolve()), "status": "ERROR", "findings": [{"severity": "ERROR", "code": "MODEL_INVALID", "message": str(exc)}], "next_mode": "doctor"}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(f"doctor {payload['status']}: {payload['project_root']}")
        for finding in payload["findings"]:
            print(f"- {finding['severity']} {finding['code']}: {finding['message']}")
        print(f"NEXT: {payload['next_mode']}")
    return 1 if payload["status"] == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
