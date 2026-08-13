#!/usr/bin/env python3
"""Audit tool-neutral assertion closure evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date
from pathlib import Path


BASE_KEYS = {"id", "compiled", "bound", "attempts", "passes", "failures", "vacuous", "plan_ref"}
WAIVER_KEYS = {"id", "status", "reviewer", "decision_date", "rationale"}


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def valid_waiver(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != WAIVER_KEYS:
        return False
    if not all(isinstance(value[key], str) and value[key].strip() for key in WAIVER_KEYS):
        return False
    if value["status"] != "Approved":
        return False
    try:
        date.fromisoformat(value["decision_date"])
    except ValueError:
        return False
    return True


def audit(evidence: object) -> dict:
    required = {"schema_version", "tool", "compile_log", "elaboration_log", "assertions"}
    if not isinstance(evidence, dict) or set(evidence) != required or evidence.get("schema_version") != 1:
        fail("invalid top-level keys or schema_version")
    for key in ("tool", "compile_log", "elaboration_log"):
        if not isinstance(evidence[key], str) or not evidence[key].strip():
            fail(f"{key} must be a non-empty evidence reference")
    assertions = evidence["assertions"]
    if not isinstance(assertions, list) or not assertions:
        fail("assertions must be a non-empty list")
    blockers, ids = [], set()
    attempts = passes = failures = 0
    for index, item in enumerate(assertions):
        if not isinstance(item, dict) or not BASE_KEYS.issubset(item) or not set(item).issubset(BASE_KEYS | {"waiver"}):
            fail(f"assertions[{index}] has invalid keys")
        assertion_id = item["id"]
        if not isinstance(assertion_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", assertion_id):
            fail(f"assertions[{index}].id is invalid")
        if assertion_id in ids:
            blockers.append(f"duplicate assertion: {assertion_id}")
        ids.add(assertion_id)
        for key in ("compiled", "bound", "vacuous"):
            if not isinstance(item[key], bool):
                fail(f"{assertion_id}: {key} must be boolean")
        for key in ("attempts", "passes", "failures"):
            if not isinstance(item[key], int) or item[key] < 0:
                fail(f"{assertion_id}: {key} must be a non-negative integer")
        if not isinstance(item["plan_ref"], str) or not item["plan_ref"].strip():
            fail(f"{assertion_id}: plan_ref is required")
        attempts += item["attempts"]
        passes += item["passes"]
        failures += item["failures"]
        waived = valid_waiver(item.get("waiver"))
        if not item["compiled"]:
            blockers.append(f"{assertion_id}: not compiled")
        if not item["bound"]:
            blockers.append(f"{assertion_id}: not bound/elaborated")
        if item["attempts"] == 0:
            blockers.append(f"{assertion_id}: zero attempts")
        if item["passes"] + item["failures"] > item["attempts"]:
            blockers.append(f"{assertion_id}: passes + failures exceeds attempts")
        if item["failures"] > 0 and not waived:
            blockers.append(f"{assertion_id}: failures without approved waiver")
        if item["vacuous"] and not waived:
            blockers.append(f"{assertion_id}: vacuous result without approved waiver")
        if "waiver" in item and not waived:
            blockers.append(f"{assertion_id}: incomplete waiver metadata")
    return {
        "schema_version": 1,
        "summary": {
            "state": "READY_FOR_HUMAN_FREEZE_REVIEW" if not blockers else "BLOCKED",
            "assertions": len(assertions),
            "attempts": attempts,
            "passes": passes,
            "failures": failures,
            "blockers": len(blockers),
        },
        "compile_log": evidence["compile_log"],
        "elaboration_log": evidence["elaboration_log"],
        "blockers": blockers,
        "notice": "Readiness is not approval; compare this export with native assertion evidence.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = audit(json.loads(args.evidence.read_text(encoding="utf-8")))
    output = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out:
        if args.out.exists():
            fail(f"refusing to overwrite: {args.out}")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        temp = args.out.with_name(f".{args.out.name}.{os.getpid()}.tmp")
        temp.write_text(output, encoding="utf-8")
        os.replace(temp, args.out)
        print(args.out)
    if args.json or not args.out:
        print(output, end="")
    return 1 if payload["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
