#!/usr/bin/env python3
"""Audit coverage closure counts and holes against a tool-generated object inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from pathlib import Path


APPROVAL_KEYS = {"id", "status", "reviewer", "decision_date", "rationale", "path", "sha256"}
SHA256 = set("0123456789abcdef")


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def valid_approval(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != APPROVAL_KEYS:
        return False
    if not all(isinstance(value[key], str) and value[key].strip() for key in APPROVAL_KEYS):
        return False
    if value["status"] != "Approved":
        return False
    if len(value["sha256"]) != 64 or set(value["sha256"]) - SHA256:
        return False
    try:
        date.fromisoformat(value["decision_date"])
    except ValueError:
        return False
    return True


def inventory_keys(inventory: object) -> set[str]:
    if not isinstance(inventory, dict) or inventory.get("schema") != "CoverageObjectInventory/2":
        fail("inventory schema must be CoverageObjectInventory/2")
    implementation_digest = inventory.get("implementation_config_digest")
    if (not isinstance(implementation_digest, str) or len(implementation_digest) != 64
            or set(implementation_digest) - SHA256):
        fail("inventory.implementation_config_digest must be a lowercase SHA-256")
    objects = inventory.get("objects")
    if not isinstance(objects, list) or not objects:
        fail("inventory.objects must be a non-empty list")
    keys: set[str] = set()
    for index, item in enumerate(objects):
        if not isinstance(item, dict):
            fail(f"inventory.objects[{index}] must be an object")
        key = item.get("object_key")
        if not isinstance(key, str) or not key.strip():
            fail(f"inventory.objects[{index}].object_key is required")
        if key in keys:
            fail(f"duplicate inventory object_key: {key}")
        keys.add(key)
    return keys


def audit(evidence: object, inventory: object, inventory_digest: str, evidence_path: Path) -> dict:
    required = {
        "schema_version", "tool", "merged_database_digest", "coverage_inventory_digest",
        "reported", "holes", "exclusion_approval",
    }
    if not isinstance(evidence, dict) or set(evidence) != required or evidence.get("schema_version") != 3:
        fail("invalid top-level keys or schema_version")
    if not isinstance(evidence["tool"], str) or not evidence["tool"].strip():
        fail("tool must identify the exporter and version")
    merged_database_digest = evidence["merged_database_digest"]
    if (not isinstance(merged_database_digest, str) or len(merged_database_digest) != 64
            or set(merged_database_digest) - SHA256):
        fail("merged_database_digest must be a lowercase SHA-256")
    if evidence["coverage_inventory_digest"] != inventory_digest:
        fail("coverage_inventory_digest does not match the supplied inventory")
    objects = inventory_keys(inventory)
    reported = evidence["reported"]
    count_keys = {"required", "covered", "excluded", "uncovered", "closure_percent"}
    if not isinstance(reported, dict) or set(reported) != count_keys:
        fail("reported must contain required, covered, excluded, uncovered, and closure_percent")
    for key in ("required", "covered", "excluded", "uncovered"):
        if not isinstance(reported[key], int) or isinstance(reported[key], bool) or reported[key] < 0:
            fail(f"reported.{key} must be a non-negative integer")
    blockers = []
    if reported["required"] != len(objects):
        blockers.append(
            f"reported required={reported['required']} but inventory contains {len(objects)} objects"
        )
    if reported["required"] != reported["covered"] + reported["excluded"] + reported["uncovered"]:
        blockers.append("required must equal covered + excluded + uncovered")
    holes = evidence["holes"]
    if not isinstance(holes, list):
        fail("holes must be a list")
    seen: set[str] = set()
    hole_counts = {"excluded": 0, "uncovered": 0}
    approval = evidence["exclusion_approval"]
    if approval is not None:
        if not valid_approval(approval):
            fail("exclusion_approval must be one complete approved file-level record")
        approval_path = Path(approval["path"])
        if approval_path.is_absolute() or ".." in approval_path.parts:
            fail("exclusion_approval.path must be relative and remain beside the evidence tree")
        try:
            observed = hashlib.sha256((evidence_path.parent / approval_path).read_bytes()).hexdigest()
        except OSError as exc:
            fail(f"cannot read exclusion_approval.path: {exc}")
        if observed != approval["sha256"]:
            fail("exclusion_approval file digest changed")
    for index, hole in enumerate(holes):
        if not isinstance(hole, dict):
            fail(f"holes[{index}] must be an object")
        key = hole.get("object_key")
        if not isinstance(key, str) or not key.strip():
            fail(f"holes[{index}].object_key is required")
        if key in seen:
            blockers.append(f"duplicate coverage hole: {key}")
        seen.add(key)
        if key not in objects:
            blockers.append(f"coverage hole is outside the inventory: {key}")
        status = hole.get("status")
        if status not in hole_counts:
            fail(f"{key}: status must be excluded or uncovered")
        hole_counts[status] += 1
        if status == "uncovered":
            blockers.append(f"{key}: uncovered")
        elif approval is None or hole.get("exclusion_approval_id") != approval["id"]:
            blockers.append(f"{key}: exclusion does not reference the approved exclusion file")
    for status in hole_counts:
        if hole_counts[status] != reported[status]:
            blockers.append(
                f"reported {status}={reported[status]} but holes contain {hole_counts[status]}"
            )
    required_count = reported["required"]
    closure = 100.0 * (reported["covered"] + reported["excluded"]) / required_count if required_count else 0.0
    if not isinstance(reported["closure_percent"], (int, float)) or isinstance(
        reported["closure_percent"], bool
    ) or abs(float(reported["closure_percent"]) - closure) > 0.0001:
        blockers.append(f"reported closure_percent does not match audited {closure:.4f}")
    return {
        "schema_version": 3,
        "summary": {
            "state": "READY_FOR_HUMAN_FREEZE_REVIEW" if not blockers else "BLOCKED",
            **{key: reported[key] for key in ("required", "covered", "excluded", "uncovered")},
            "closure_percent": round(closure, 4),
            "blockers": len(blockers),
        },
        "merged_database_digest": merged_database_digest,
        "coverage_inventory_digest": inventory_digest,
        "blockers": blockers,
        "notice": "Readiness is not approval; compare this export with native coverage evidence.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    inventory_raw = args.inventory.read_bytes()
    payload = audit(
        json.loads(args.evidence.read_text(encoding="utf-8")),
        json.loads(inventory_raw),
        hashlib.sha256(inventory_raw).hexdigest(),
        args.evidence,
    )
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
