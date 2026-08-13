#!/usr/bin/env python3
"""Build a hash-anchored verification freeze candidate manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import date
from pathlib import Path


REQUIRED_KEYS = {
    "schema_version", "freeze_name", "baseline_ref", "rtl_root",
    "require_rtl_unchanged", "required_evidence", "state_checks",
    "include_files", "tool_versions",
}
OPTIONAL_KEYS = {"approval_record"}


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if result.returncode:
        fail(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def safe_rel(raw: object, where: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        fail(f"{where} must be a non-empty relative path")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        fail(f"{where} is not project-relative: {raw}")
    return path.as_posix()


def string_list(value: object, where: str) -> list[str]:
    if not isinstance(value, list):
        fail(f"{where} must be a list")
    result = [safe_rel(item, where) for item in value]
    if len(result) != len(set(result)):
        fail(f"{where} contains duplicates")
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def lookup(value: object, path: list[str]) -> object:
    current = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            fail(f"state check key path is absent: {'.'.join(path)}")
        current = current[key]
    return current


def approval_state(contract: dict, required: list[str], root: Path) -> tuple[str, dict | None]:
    record = contract.get("approval_record")
    if record is None:
        return "READY_FOR_HUMAN_FREEZE_REVIEW", None
    keys = {"status", "reviewer", "decision_date", "evidence_ref"}
    if not isinstance(record, dict) or set(record) != keys or record.get("status") != "Approved":
        fail("approval_record must contain an existing Approved Human decision")
    if not all(isinstance(record[key], str) and record[key].strip() for key in keys):
        fail("approval_record fields must be non-empty strings")
    try:
        date.fromisoformat(record["decision_date"])
    except ValueError:
        fail("approval_record.decision_date must be ISO-8601")
    evidence_ref = safe_rel(record["evidence_ref"], "approval_record.evidence_ref")
    if evidence_ref not in required or not (root / evidence_ref).is_file():
        fail("approval_record.evidence_ref must be a hashed required-evidence file")
    return "APPROVED_RECORDED", record


def build(root: Path, contract: object) -> dict:
    if not isinstance(contract, dict):
        fail("contract must be an object")
    unknown = set(contract) - REQUIRED_KEYS - OPTIONAL_KEYS
    missing = REQUIRED_KEYS - set(contract)
    if unknown or missing or contract.get("schema_version") != 1:
        fail(f"contract keys/schema invalid unknown={sorted(unknown)} missing={sorted(missing)}")
    if not isinstance(contract["freeze_name"], str) or not contract["freeze_name"].strip():
        fail("freeze_name is required")
    if not isinstance(contract["baseline_ref"], str) or not contract["baseline_ref"].strip():
        fail("baseline_ref is required")
    rtl_root = safe_rel(contract["rtl_root"], "rtl_root")
    if not isinstance(contract["require_rtl_unchanged"], bool):
        fail("require_rtl_unchanged must be boolean")
    required = string_list(contract["required_evidence"], "required_evidence")
    included = string_list(contract["include_files"], "include_files")
    if not required or not included:
        fail("required_evidence and include_files must be non-empty")
    dirty = git(root, "status", "--porcelain")
    if dirty:
        fail("Git worktree must be clean before building a freeze candidate")
    commit = git(root, "rev-parse", "HEAD")
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    git(root, "rev-parse", "--verify", contract["baseline_ref"])
    rtl_changed = [line for line in git(
        root, "diff", "--name-only", f"{contract['baseline_ref']}...HEAD", "--", rtl_root,
    ).splitlines() if line]
    if contract["require_rtl_unchanged"] and rtl_changed:
        fail(f"RTL changed since baseline: {rtl_changed}")
    files = sorted(set(required + included))
    hashes = []
    for relative in files:
        path = root / relative
        if not path.is_file():
            fail(f"required file is missing: {relative}")
        hashes.append({"path": relative, "sha256": sha256(path), "bytes": path.stat().st_size})
    checks = contract["state_checks"]
    if not isinstance(checks, list) or not checks:
        fail("state_checks must be a non-empty list")
    checked_states = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict) or set(check) != {"path", "key_path", "allowed"}:
            fail(f"state_checks[{index}] has invalid keys")
        relative = safe_rel(check["path"], f"state_checks[{index}].path")
        if relative not in required:
            fail(f"state_checks[{index}].path must also be required evidence")
        key_path = check["key_path"]
        allowed = check["allowed"]
        if not isinstance(key_path, list) or not key_path or not all(isinstance(key, str) and key for key in key_path):
            fail(f"state_checks[{index}].key_path is invalid")
        if not isinstance(allowed, list) or not allowed:
            fail(f"state_checks[{index}].allowed is invalid")
        path = root / relative
        if not path.is_file():
            fail(f"state-check file is missing: {relative}")
        value = lookup(json.loads(path.read_text(encoding="utf-8")), key_path)
        if value not in allowed:
            fail(f"state check failed for {relative}:{'.'.join(key_path)} value={value!r}")
        checked_states.append({"path": relative, "key_path": key_path, "value": value})
    versions = contract["tool_versions"]
    if not isinstance(versions, dict) or not versions or not all(
        isinstance(key, str) and key and isinstance(value, str) and value.strip()
        for key, value in versions.items()
    ):
        fail("tool_versions must be a non-empty string map")
    state, approval = approval_state(contract, required, root)
    return {
        "schema_version": 1,
        "freeze_name": contract["freeze_name"],
        "summary": {"state": state},
        "git": {
            "commit": commit,
            "branch": branch,
            "baseline_ref": contract["baseline_ref"],
            "worktree_clean": True,
            "rtl_changed_files": rtl_changed,
        },
        "tool_versions": dict(sorted(versions.items())),
        "state_checks": checked_states,
        "files": hashes,
        "approval_record": approval,
        "notice": "This manifest records evidence identity; it grants no approval or publication authorization.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        fail(f"refusing to overwrite: {args.out}")
    payload = build(args.project_root.resolve(), json.loads(args.contract.read_text(encoding="utf-8")))
    output = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temp = args.out.with_name(f".{args.out.name}.{os.getpid()}.tmp")
    temp.write_text(output, encoding="utf-8")
    os.replace(temp, args.out)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
