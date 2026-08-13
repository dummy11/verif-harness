#!/usr/bin/env python3
"""Group regression failures and verify same-seed rerun evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"{path} must contain an object")
    return value


def results(report: dict, where: str) -> dict[str, dict]:
    values = report.get("results")
    if not isinstance(values, list):
        fail(f"{where}.results must be a list")
    indexed: dict[str, dict] = {}
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            fail(f"{where}.results[{index}] must be an object")
        for key in ("test", "verdict", "seed", "log"):
            if key not in item:
                fail(f"{where}.results[{index}] lacks {key}")
        if not isinstance(item["test"], str) or not item["test"]:
            fail(f"{where}.results[{index}].test is invalid")
        if item["test"] in indexed:
            fail(f"duplicate test in {where}: {item['test']}")
        indexed[item["test"]] = item
    return indexed


def rules(value: dict) -> tuple[set[str], list[tuple[str, str, list[re.Pattern[str]]]]]:
    if set(value) != {"schema_version", "acceptable_verdicts", "rules"} or value["schema_version"] != 1:
        fail("rules contract has invalid keys or schema_version")
    acceptable = value["acceptable_verdicts"]
    if not isinstance(acceptable, list) or not acceptable or not all(isinstance(v, str) and v for v in acceptable):
        fail("acceptable_verdicts must be a non-empty string list")
    compiled = []
    for index, rule in enumerate(value["rules"]):
        if not isinstance(rule, dict) or set(rule) != {"name", "candidate_classification", "patterns"}:
            fail(f"rules[{index}] has invalid keys")
        patterns = rule["patterns"]
        if not isinstance(patterns, list) or not patterns:
            fail(f"rules[{index}].patterns must be non-empty")
        try:
            regexes = [re.compile(pattern) for pattern in patterns]
        except (re.error, TypeError) as exc:
            fail(f"rules[{index}] invalid regex: {exc}")
        compiled.append((str(rule["name"]), str(rule["candidate_classification"]), regexes))
    return set(acceptable), compiled


def read_log(raw: object, report_path: Path) -> tuple[str, str | None]:
    if not isinstance(raw, str) or not raw:
        return "", "invalid log path"
    path = Path(raw)
    if not path.is_absolute():
        path = report_path.parent / path
    if not path.is_file():
        return "", f"missing log: {path}"
    return path.read_text(encoding="latin-1", errors="replace"), None


def signature(text: str) -> str:
    candidates = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.search(r"(?i)(error|fatal|failed|mismatch|timeout)", stripped):
            normalized = re.sub(r"\b\d+\b", "<n>", stripped)
            normalized = re.sub(r"0x[0-9a-fA-F]+", "<hex>", normalized)
            candidates.append(normalized[:240])
    value = candidates[0] if candidates else "NO_FAILURE_SIGNATURE"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{digest}:{value}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rerun-report", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    acceptable, classifications = rules(load(args.rules))
    primary = results(load(args.report), "report")
    rerun = results(load(args.rerun_report), "rerun_report")
    findings, blockers = [], []
    for test, item in sorted(primary.items()):
        if item["verdict"] in acceptable:
            continue
        log_text, log_error = read_log(item["log"], args.report)
        candidate, matched_rule = "UNCLASSIFIED", None
        for rule_name, classification, regexes in classifications:
            if any(regex.search(log_text) for regex in regexes):
                candidate, matched_rule = classification, rule_name
                break
        rerun_item = rerun.get(test)
        rerun_ok = bool(rerun_item and rerun_item.get("seed") == item.get("seed"))
        item_blockers = []
        if log_error:
            item_blockers.append(log_error)
        if candidate == "UNCLASSIFIED":
            item_blockers.append("no reviewed signature rule matched")
        if not rerun_ok:
            item_blockers.append("same-seed rerun evidence missing or mismatched")
        blockers.extend(f"{test}: {message}" for message in item_blockers)
        findings.append({
            "test": test,
            "seed": item.get("seed"),
            "verdict": item.get("verdict"),
            "signature": signature(log_text),
            "candidate_classification": candidate,
            "matched_rule": matched_rule,
            "primary_log": item.get("log"),
            "rerun_log": rerun_item.get("log") if rerun_item else None,
            "rerun_verdict": rerun_item.get("verdict") if rerun_item else None,
            "same_seed_rerun": rerun_ok,
            "blockers": item_blockers,
        })
    payload = {
        "schema_version": 1,
        "summary": {
            "state": "READY_FOR_HUMAN_TRIAGE" if not blockers else "BLOCKED",
            "failed_tests": len(findings),
            "blockers": len(blockers),
        },
        "findings": findings,
        "blockers": blockers,
        "notice": "Classifications are candidates and require Human review.",
    }
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
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
