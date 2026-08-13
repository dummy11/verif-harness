#!/usr/bin/env python3
"""Evaluate pipe-delimited performance records against a reviewed JSON contract."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


OPS = {"eq", "ne", "lt", "le", "gt", "ge"}
TOP_KEYS = {
    "marker", "schema_field", "schema_value", "required_fields", "key_fields",
    "predicates", "completeness",
}


@dataclass
class Failure:
    source: str
    identity: str
    check: str
    message: str


def load_contract(path: Path) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict) or set(contract) != TOP_KEYS:
        raise SystemExit(f"ERROR: contract keys must be {sorted(TOP_KEYS)}")
    for field in ("marker", "schema_field", "schema_value"):
        if not isinstance(contract[field], str) or not contract[field]:
            raise SystemExit(f"ERROR: {field} must be a non-empty string")
    for field in ("required_fields", "key_fields"):
        values = contract[field]
        if not isinstance(values, list) or not values or not all(isinstance(x, str) and x for x in values):
            raise SystemExit(f"ERROR: {field} must be a non-empty string list")
        if len(values) != len(set(values)):
            raise SystemExit(f"ERROR: {field} contains duplicates")
    if not set(contract["key_fields"]).issubset(contract["required_fields"]):
        raise SystemExit("ERROR: key_fields must be included in required_fields")
    if contract["schema_field"] not in contract["required_fields"]:
        raise SystemExit("ERROR: schema_field must be included in required_fields")
    predicates = contract["predicates"]
    if not isinstance(predicates, list) or not predicates:
        raise SystemExit("ERROR: predicates must be a non-empty list")
    names: set[str] = set()
    for index, predicate in enumerate(predicates):
        if not isinstance(predicate, dict) or set(predicate) != {"name", "lhs", "op", "rhs", "tolerance"}:
            raise SystemExit(f"ERROR: predicates[{index}] has invalid keys")
        name = predicate["name"]
        if not isinstance(name, str) or not name or name in names:
            raise SystemExit(f"ERROR: invalid or duplicate predicate name: {name}")
        names.add(name)
        if predicate["op"] not in OPS:
            raise SystemExit(f"ERROR: unsupported operator: {predicate['op']}")
        tolerance = predicate["tolerance"]
        if not isinstance(tolerance, (int, float)) or tolerance < 0:
            raise SystemExit(f"ERROR: {name} tolerance must be non-negative")
        validate_operand(predicate["lhs"], f"{name}.lhs")
        validate_operand(predicate["rhs"], f"{name}.rhs")
    completeness = contract["completeness"]
    if not isinstance(completeness, list):
        raise SystemExit("ERROR: completeness must be a list")
    for index, rule in enumerate(completeness):
        if not isinstance(rule, dict) or set(rule) != {"field", "required_values"}:
            raise SystemExit(f"ERROR: completeness[{index}] has invalid keys")
        if not isinstance(rule["field"], str) or not rule["field"]:
            raise SystemExit(f"ERROR: completeness[{index}].field is invalid")
        if not isinstance(rule["required_values"], list) or not rule["required_values"]:
            raise SystemExit(f"ERROR: completeness[{index}].required_values must be non-empty")
    return contract


def validate_operand(operand: Any, where: str) -> None:
    if not isinstance(operand, dict) or len(operand) != 1:
        raise SystemExit(f"ERROR: {where} must have exactly one of field, value, ratio")
    kind, value = next(iter(operand.items()))
    if kind == "field":
        if not isinstance(value, str) or not value:
            raise SystemExit(f"ERROR: {where}.field must be non-empty")
    elif kind == "value":
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise SystemExit(f"ERROR: {where}.value must be string or number")
    elif kind == "ratio":
        if not isinstance(value, list) or len(value) != 2 or not all(isinstance(x, str) and x for x in value):
            raise SystemExit(f"ERROR: {where}.ratio must contain numerator and denominator fields")
    else:
        raise SystemExit(f"ERROR: unsupported operand kind in {where}: {kind}")


def parse_records(paths: list[Path], marker: str) -> tuple[list[dict[str, str]], list[Failure]]:
    records: list[dict[str, str]] = []
    failures: list[Failure] = []
    for path in paths:
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            position = line.find(marker)
            if position < 0:
                continue
            payload = line[position + len(marker):]
            record: dict[str, str] = {"__source": f"{path}:{line_no}"}
            malformed = False
            for token in payload.split("|"):
                if "=" not in token:
                    failures.append(Failure(record["__source"], "?", "record", f"malformed token: {token}"))
                    malformed = True
                    break
                key, value = token.split("=", 1)
                key, value = key.strip(), value.strip()
                if not key or key in record:
                    failures.append(Failure(record["__source"], "?", "record", f"empty or duplicate key: {key}"))
                    malformed = True
                    break
                record[key] = value
            if not malformed:
                records.append(record)
    return records, failures


def numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def operand_value(operand: dict[str, Any], record: dict[str, str]) -> tuple[Any, str | None]:
    kind, value = next(iter(operand.items()))
    if kind == "value":
        return value, None
    if kind == "field":
        return (record[value], None) if value in record else (None, f"missing field: {value}")
    numerator_name, denominator_name = value
    if numerator_name not in record or denominator_name not in record:
        return None, f"missing ratio field: {numerator_name}/{denominator_name}"
    numerator, denominator = numeric(record[numerator_name]), numeric(record[denominator_name])
    if numerator is None or denominator is None:
        return None, f"non-numeric ratio: {record[numerator_name]}/{record[denominator_name]}"
    if denominator == 0:
        return None, "division by zero"
    return numerator / denominator, None


def compare(lhs: Any, op: str, rhs: Any, tolerance: float) -> tuple[bool, str | None]:
    left_num, right_num = numeric(lhs), numeric(rhs)
    if left_num is not None and right_num is not None:
        if op == "eq":
            return abs(left_num - right_num) <= tolerance, None
        if op == "ne":
            return abs(left_num - right_num) > tolerance, None
        operations = {
            "lt": left_num < right_num,
            "le": left_num <= right_num,
            "gt": left_num > right_num,
            "ge": left_num >= right_num,
        }
        return operations[op], None
    if op not in {"eq", "ne"}:
        return False, "ordered comparison requires numeric operands"
    return (str(lhs) == str(rhs)) if op == "eq" else (str(lhs) != str(rhs)), None


def evaluate(contract: dict[str, Any], records: list[dict[str, str]], failures: list[Failure]) -> dict[str, Any]:
    identities: set[tuple[str, ...]] = set()
    passed_checks = 0
    for record in records:
        source = record["__source"]
        missing = [field for field in contract["required_fields"] if field not in record]
        identity = "/".join(record.get(field, "?") for field in contract["key_fields"])
        if missing:
            failures.append(Failure(source, identity, "required_fields", ", ".join(missing)))
            continue
        if record[contract["schema_field"]] != contract["schema_value"]:
            failures.append(Failure(source, identity, "schema", "unexpected schema value"))
        key = tuple(record[field] for field in contract["key_fields"])
        if key in identities:
            failures.append(Failure(source, identity, "identity", "duplicate record identity"))
        identities.add(key)
        for predicate in contract["predicates"]:
            lhs, lhs_error = operand_value(predicate["lhs"], record)
            rhs, rhs_error = operand_value(predicate["rhs"], record)
            error = lhs_error or rhs_error
            if error:
                failures.append(Failure(source, identity, predicate["name"], error))
                continue
            passed, error = compare(lhs, predicate["op"], rhs, float(predicate["tolerance"]))
            if error or not passed:
                message = error or f"{lhs!r} {predicate['op']} {rhs!r} failed"
                failures.append(Failure(source, identity, predicate["name"], message))
            else:
                passed_checks += 1
    for rule in contract["completeness"]:
        observed = {str(record[rule["field"]]) for record in records if rule["field"] in record}
        missing_values = [str(value) for value in rule["required_values"] if str(value) not in observed]
        if missing_values:
            failures.append(Failure("all logs", "all records", f"completeness:{rule['field']}",
                                    "missing values: " + ", ".join(missing_values)))
    return {
        "state": "PASS" if records and not failures else "FAIL",
        "records": len(records),
        "unique_identities": len(identities),
        "passed_checks": passed_checks,
        "failed_checks": len(failures),
    }


def markdown(summary: dict[str, Any], failures: list[Failure]) -> str:
    lines = [
        "# Performance Gate Report", "",
        f"- State: **{summary['state']}**",
        f"- Records: {summary['records']}",
        f"- Unique identities: {summary['unique_identities']}",
        f"- Passed predicate checks: {summary['passed_checks']}",
        f"- Failures: {summary['failed_checks']}", "", "## Failures", "",
    ]
    lines.extend(
        [f"- `{item.identity}` — **{item.check}**: {item.message} ({item.source})" for item in failures]
        or ["- None."]
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--log", type=Path, action="append", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    contract = load_contract(args.contract)
    records, failures = parse_records(args.log, contract["marker"])
    if not records:
        failures.append(Failure("all logs", "all records", "records", "no performance records found"))
    summary = evaluate(contract, records, failures)
    payload = (json.dumps({"summary": summary, "failures": [asdict(item) for item in failures]}, indent=2) + "\n"
               if args.json else markdown(summary, failures))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if summary["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
