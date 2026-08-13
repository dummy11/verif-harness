#!/usr/bin/env python3
"""Audit tool-neutral functional coverage closure evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date
from pathlib import Path


ITEM_KEYS = {"id", "status", "hits", "plan_ref", "waiver"}
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
    required = {"schema_version", "tool", "database_ids", "plan_items", "reported"}
    if not isinstance(evidence, dict) or set(evidence) != required or evidence.get("schema_version") != 1:
        fail("invalid top-level keys or schema_version")
    if not isinstance(evidence["tool"], str) or not evidence["tool"].strip():
        fail("tool must identify the exporter and version")
    databases = evidence["database_ids"]
    if not isinstance(databases, list) or not databases or not all(isinstance(v, str) and v.strip() for v in databases):
        fail("database_ids must be a non-empty string list")
    if len(databases) != len(set(databases)):
        fail("database_ids contains duplicates")
    items = evidence["plan_items"]
    if not isinstance(items, list) or not items:
        fail("plan_items must be a non-empty list")
    blockers, ids = [], set()
    counts = {"covered": 0, "excluded": 0, "uncovered": 0}
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not set(item).issubset(ITEM_KEYS) or not {"id", "status", "hits", "plan_ref"}.issubset(item):
            fail(f"plan_items[{index}] has invalid keys")
        item_id = item["id"]
        if not isinstance(item_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", item_id):
            fail(f"plan_items[{index}].id is invalid")
        if item_id in ids:
            blockers.append(f"duplicate plan item: {item_id}")
        ids.add(item_id)
        status, hits = item["status"], item["hits"]
        if status not in counts:
            fail(f"{item_id}: invalid status {status}")
        if not isinstance(hits, int) or hits < 0:
            fail(f"{item_id}: hits must be a non-negative integer")
        if not isinstance(item["plan_ref"], str) or not item["plan_ref"].strip():
            fail(f"{item_id}: plan_ref is required")
        counts[status] += 1
        if status == "covered" and hits == 0:
            blockers.append(f"{item_id}: covered item has zero hits")
        if status == "uncovered":
            blockers.append(f"{item_id}: uncovered")
        if status == "excluded" and not valid_waiver(item.get("waiver")):
            blockers.append(f"{item_id}: exclusion lacks complete approved-waiver metadata")
        if status != "excluded" and "waiver" in item:
            blockers.append(f"{item_id}: waiver is only valid for excluded status")
    reported = evidence["reported"]
    if not isinstance(reported, dict) or set(reported) != {"covered", "excluded", "uncovered", "closure_percent"}:
        fail("reported must contain covered, excluded, uncovered, and closure_percent")
    for key in counts:
        if reported[key] != counts[key]:
            blockers.append(f"reported {key}={reported[key]} but audited {counts[key]}")
    closure = 100.0 * (counts["covered"] + counts["excluded"]) / len(items)
    if not isinstance(reported["closure_percent"], (int, float)) or abs(float(reported["closure_percent"]) - closure) > 0.0001:
        blockers.append(f"reported closure_percent does not match audited {closure:.4f}")
    return {
        "schema_version": 1,
        "summary": {
            "state": "READY_FOR_HUMAN_FREEZE_REVIEW" if not blockers else "BLOCKED",
            **counts,
            "closure_percent": round(closure, 4),
            "blockers": len(blockers),
        },
        "database_ids": databases,
        "blockers": blockers,
        "notice": "Readiness is not approval; compare this export with native coverage evidence.",
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
