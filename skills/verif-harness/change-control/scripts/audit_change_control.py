#!/usr/bin/env python3
"""Audit structured change requests and optional Git coverage."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import date
from pathlib import Path


TOP_KEYS = {"schema_version", "baseline_ref", "changes"}
CHANGE_KEYS = {"id", "status", "description", "files", "reviewer", "decision_date", "rationale", "impact"}
IMPACT_KEYS = {"tests", "coverage_ids", "assertion_ids", "docs", "regressions"}


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def string_list(value: object, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        fail(f"{where} must be a string list")
    if len(value) != len(set(value)):
        fail(f"{where} contains duplicates")
    return value


def audit(contract: object, project_root: Path | None, audit_git: bool) -> dict:
    if not isinstance(contract, dict) or set(contract) != TOP_KEYS or contract.get("schema_version") != 1:
        fail("invalid top-level keys or schema_version")
    baseline = contract["baseline_ref"]
    if not isinstance(baseline, str) or not baseline.strip() or re.search(r"\s", baseline):
        fail("baseline_ref must be a non-empty Git ref without whitespace")
    changes = contract["changes"]
    if not isinstance(changes, list):
        fail("changes must be a list")
    blockers, declared, active_declared, ids = [], set(), set(), set()
    normalized = []
    for index, change in enumerate(changes):
        if not isinstance(change, dict) or set(change) != CHANGE_KEYS:
            fail(f"changes[{index}] must contain exactly {sorted(CHANGE_KEYS)}")
        change_id = change["id"]
        if not isinstance(change_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", change_id):
            fail(f"changes[{index}].id is invalid")
        if change_id in ids:
            blockers.append(f"duplicate change request: {change_id}")
        ids.add(change_id)
        status = change["status"]
        if status not in {"approved", "rejected", "open"}:
            fail(f"{change_id}: invalid status {status}")
        for key in ("description", "rationale"):
            if not isinstance(change[key], str) or not change[key].strip():
                blockers.append(f"{change_id}: {key} is missing")
        files = string_list(change["files"], f"{change_id}.files")
        if not files:
            blockers.append(f"{change_id}: files is empty")
        for raw in files:
            path = Path(raw)
            if path.is_absolute() or ".." in path.parts:
                blockers.append(f"{change_id}: unsafe project-relative path {raw}")
            if raw in declared:
                blockers.append(f"file declared by multiple change requests: {raw}")
            declared.add(raw)
            if status in {"approved", "open"}:
                active_declared.add(raw)
            if project_root is not None and status in {"approved", "open"} and not (project_root / raw).is_file():
                blockers.append(f"{change_id}: declared changed file is missing: {raw}")
        impact = change["impact"]
        if not isinstance(impact, dict) or set(impact) != IMPACT_KEYS:
            fail(f"{change_id}.impact must contain exactly {sorted(IMPACT_KEYS)}")
        for key in IMPACT_KEYS:
            string_list(impact[key], f"{change_id}.impact.{key}")
        if status == "open":
            blockers.append(f"{change_id}: request remains open")
        else:
            if not isinstance(change["reviewer"], str) or not change["reviewer"].strip():
                blockers.append(f"{change_id}: reviewer is missing")
            try:
                date.fromisoformat(change["decision_date"])
            except (TypeError, ValueError):
                blockers.append(f"{change_id}: decision_date is invalid")
        if status == "approved":
            if not impact["docs"]:
                blockers.append(f"{change_id}: approved change lacks documentation impact")
            if not impact["tests"] or not impact["regressions"]:
                blockers.append(f"{change_id}: approved change lacks test/regression evidence")
        normalized.append({"id": change_id, "status": status, "files": files, "impact": impact})
    git_changed: list[str] = []
    if audit_git:
        if project_root is None:
            fail("--audit-git requires --project-root")
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{baseline}...HEAD"], cwd=project_root,
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if result.returncode:
            fail(f"git diff failed: {result.stderr.strip()}")
        git_changed = sorted(line for line in result.stdout.splitlines() if line)
        for path in sorted(set(git_changed) - active_declared):
            blockers.append(f"Git change is not declared by a change request: {path}")
        for path in sorted(active_declared - set(git_changed)):
            blockers.append(f"declared file is absent from Git diff: {path}")
    return {
        "schema_version": 1,
        "summary": {
            "state": "READY_FOR_HUMAN_REVIEW" if not blockers else "BLOCKED",
            "change_requests": len(changes),
            "declared_files": len(declared),
            "git_files": len(git_changed),
            "blockers": len(blockers),
        },
        "baseline_ref": baseline,
        "changes": normalized,
        "git_changed_files": git_changed,
        "blockers": blockers,
        "notice": "Recorded decisions remain Human decisions; this audit grants no approval.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--audit-git", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = audit(json.loads(args.contract.read_text(encoding="utf-8")), args.project_root, args.audit_git)
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
