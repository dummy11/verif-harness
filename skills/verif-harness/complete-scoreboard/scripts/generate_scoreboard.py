#!/usr/bin/env python3
"""Generate a FIFO-aligned UVM scoreboard from an explicit JSON contract."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


TOP_KEYS = {
    "schema_version", "class_name", "base_class", "expected_type",
    "actual_type", "alignment", "fields", "plan_refs",
}
BASE_FIELD_KEYS = {"name", "kind", "expected_expr", "actual_expr"}
IDENT = re.compile(r"[A-Za-z_]\w*")
SV_TEXT = re.compile(r"[A-Za-z0-9_.$'()\[\]:+\-*/&|~\s]+")
TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_:#(),\s]*")


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def ident(value: object, where: str) -> str:
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        fail(f"unsafe identifier for {where}: {value}")
    return value


def safe_text(value: object, where: str, pattern: re.Pattern[str] = SV_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or not pattern.fullmatch(value.strip()):
        fail(f"unsafe SystemVerilog text for {where}: {value}")
    if any(word in value for word in ("endclass", "endmodule", "endpackage")):
        fail(f"forbidden terminator in {where}")
    return value.strip()


def validate(spec: object) -> dict:
    if not isinstance(spec, dict):
        fail("top level must be an object")
    unknown, missing = set(spec) - TOP_KEYS, TOP_KEYS - set(spec)
    if unknown or missing:
        fail(f"top-level keys unknown={sorted(unknown)} missing={sorted(missing)}")
    if spec["schema_version"] != 1 or spec["alignment"] != "fifo":
        fail("schema_version must be 1 and alignment must be 'fifo'")
    spec["class_name"] = ident(spec["class_name"], "class_name")
    for key in ("base_class", "expected_type", "actual_type"):
        spec[key] = safe_text(spec[key], key, TYPE)
    fields = spec["fields"]
    if not isinstance(fields, list) or not fields:
        fail("fields must be a non-empty list")
    checked: list[dict] = []
    names: set[str] = set()
    for index, field in enumerate(fields):
        if not isinstance(field, dict):
            fail(f"fields[{index}] must be an object")
        kind = field.get("kind")
        allowed = BASE_FIELD_KEYS | ({"mask_expr"} if kind == "masked" else {"tolerance"} if kind == "abs_tolerance" else set())
        if kind not in {"exact", "masked", "abs_tolerance"} or set(field) != allowed:
            fail(f"fields[{index}] has invalid kind or keys")
        item = dict(field)
        item["name"] = ident(field["name"], f"fields[{index}].name")
        if item["name"] in names:
            fail(f"duplicate field name: {item['name']}")
        names.add(item["name"])
        item["expected_expr"] = safe_text(field["expected_expr"], f"fields[{index}].expected_expr")
        item["actual_expr"] = safe_text(field["actual_expr"], f"fields[{index}].actual_expr")
        if kind == "masked":
            item["mask_expr"] = safe_text(field["mask_expr"], f"fields[{index}].mask_expr")
        if kind == "abs_tolerance" and (not isinstance(field["tolerance"], int) or field["tolerance"] < 0):
            fail(f"fields[{index}].tolerance must be a non-negative integer")
        checked.append(item)
    refs = spec["plan_refs"]
    if not isinstance(refs, list) or not refs or not all(isinstance(ref, str) and ref.strip() for ref in refs):
        fail("plan_refs must be a non-empty list")
    spec["fields"] = checked
    return spec


def render(spec: dict) -> str:
    c = spec["class_name"]
    exp_type, act_type = spec["expected_type"], spec["actual_type"]
    lines = [
        f"// Plan: {'; '.join(spec['plan_refs'])}",
        "// Alignment policy: FIFO; reset flushing remains project-owned.",
        f"class {c} extends {spec['base_class']};",
        f"  `uvm_component_utils({c})",
        f"  uvm_tlm_analysis_fifo #({exp_type}) expected_fifo;",
        f"  uvm_tlm_analysis_fifo #({act_type}) actual_fifo;",
        "  int unsigned compared_count;",
        "  int unsigned mismatch_count;",
        "",
        "  function new(string name, uvm_component parent);",
        "    super.new(name, parent);",
        "    expected_fifo = new(\"expected_fifo\", this);",
        "    actual_fifo = new(\"actual_fifo\", this);",
        "  endfunction",
        "",
        "  virtual task run_phase(uvm_phase phase);",
        f"    {exp_type} expected_item;",
        f"    {act_type} actual_item;",
        "    forever begin",
        "      expected_fifo.get(expected_item);",
        "      actual_fifo.get(actual_item);",
        "      compare_pair(expected_item, actual_item);",
        "    end",
        "  endtask",
        "",
        f"  virtual function void compare_pair({exp_type} expected_item, {act_type} actual_item);",
        "    bit pair_match = 1'b1;",
        "    longint signed delta;",
    ]
    for field in spec["fields"]:
        exp, act, name = field["expected_expr"], field["actual_expr"], field["name"]
        if field["kind"] == "exact":
            condition = f"({exp}) !== ({act})"
        elif field["kind"] == "masked":
            mask = field["mask_expr"]
            condition = f"((({exp}) & ({mask})) !== (({act}) & ({mask})))"
        else:
            lines.append(f"    delta = $signed({exp}) - $signed({act});")
            condition = f"(delta < -{field['tolerance']}) || (delta > {field['tolerance']})"
        lines.extend([
            f"    if ({condition}) begin",
            "      pair_match = 1'b0;",
            f"      `uvm_error(\"{c.upper()}_MISMATCH\", \"field {name} mismatch\")",
            "    end",
        ])
    lines.extend([
        "    compared_count++;",
        "    if (!pair_match) mismatch_count++;",
        "  endfunction",
        "",
        "  virtual function void check_phase(uvm_phase phase);",
        "    super.check_phase(phase);",
        "    if (compared_count == 0)",
        f"      `uvm_error(\"{c.upper()}_NO_COMPARE\", \"no transaction pair was compared\")",
        "    if (expected_fifo.used() != 0 || actual_fifo.used() != 0)",
        f"      `uvm_error(\"{c.upper()}_RESIDUAL\", \"unpaired transactions remain\")",
        "    if (mismatch_count != 0)",
        f"      `uvm_error(\"{c.upper()}_SUMMARY\", $sformatf(\"%0d mismatched pairs\", mismatch_count))",
        "  endfunction",
        "endclass",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        fail(f"refusing to overwrite: {args.out}")
    spec = validate(json.loads(args.spec.read_text(encoding="utf-8")))
    content = render(spec)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temp = args.out.with_name(f".{args.out.name}.{os.getpid()}.tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, args.out)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
