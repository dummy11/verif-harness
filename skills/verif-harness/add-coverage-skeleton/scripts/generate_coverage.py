#!/usr/bin/env python3
"""Generate a UVM coverage-model class from a reviewed JSON contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
TOP_KEYS = {"class_name", "base_class", "fields", "covergroups"}
CG_KEYS = {"name", "plan_refs", "coverpoints", "crosses"}
CP_KEYS = {"name", "expression", "bins"}
CROSS_KEYS = {"name", "items", "bins"}
FIELD_KEYS = {"type", "name"}


def require_keys(obj: dict, allowed: set[str], required: set[str], where: str) -> None:
    unknown = set(obj) - allowed
    missing = required - set(obj)
    if unknown or missing:
        raise SystemExit(f"ERROR: {where}: unknown={sorted(unknown)} missing={sorted(missing)}")


def ident(value: str, where: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise SystemExit(f"ERROR: unsafe identifier for {where}: {value}")
    return value


def safe_sv(value: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"ERROR: empty SystemVerilog text for {where}")
    if re.search(r"\b(?:endclass|endmodule|endpackage)\b", value):
        raise SystemExit(f"ERROR: forbidden terminator in {where}")
    return value.strip()


def render(spec: dict) -> str:
    require_keys(spec, TOP_KEYS, TOP_KEYS, "top")
    class_name = ident(spec["class_name"], "class_name")
    base_class = ident(spec["base_class"], "base_class")
    if not isinstance(spec["fields"], list):
        raise SystemExit("ERROR: fields must be a list")
    if not isinstance(spec["covergroups"], list) or not spec["covergroups"]:
        raise SystemExit("ERROR: covergroups must be a non-empty list")
    names: set[str] = set()
    lines = [f"class {class_name} extends {base_class};",
             f"  `uvm_component_utils({class_name})", ""]
    for index, field in enumerate(spec["fields"]):
        require_keys(field, FIELD_KEYS, FIELD_KEYS, f"fields[{index}]")
        name = ident(field["name"], f"fields[{index}].name")
        if name in names:
            raise SystemExit(f"ERROR: duplicate generated name: {name}")
        names.add(name)
        lines.append(f"  {safe_sv(field['type'], f'fields[{index}].type')} {name};")
    lines.append("")
    cg_names: list[str] = []
    for cg_index, cg in enumerate(spec["covergroups"]):
        require_keys(cg, CG_KEYS, {"name", "plan_refs", "coverpoints", "crosses"},
                     f"covergroups[{cg_index}]")
        cg_name = ident(cg["name"], f"covergroups[{cg_index}].name")
        if cg_name in names:
            raise SystemExit(f"ERROR: duplicate generated name: {cg_name}")
        names.add(cg_name)
        cg_names.append(cg_name)
        refs = cg["plan_refs"]
        if not isinstance(refs, list) or not refs or not all(isinstance(x, str) and x for x in refs):
            raise SystemExit(f"ERROR: {cg_name} requires non-empty plan_refs")
        lines.append(f"  // Plan: {'; '.join(refs)}")
        lines.append(f"  covergroup {cg_name};")
        lines.append("    option.per_instance = 1;")
        local_cp: set[str] = set()
        if not isinstance(cg["coverpoints"], list) or not cg["coverpoints"]:
            raise SystemExit(f"ERROR: {cg_name}.coverpoints must be a non-empty list")
        if not isinstance(cg["crosses"], list):
            raise SystemExit(f"ERROR: {cg_name}.crosses must be a list")
        for cp_index, cp in enumerate(cg["coverpoints"]):
            require_keys(cp, CP_KEYS, CP_KEYS, f"{cg_name}.coverpoints[{cp_index}]")
            cp_name = ident(cp["name"], f"{cg_name}.coverpoint")
            if cp_name in local_cp:
                raise SystemExit(f"ERROR: duplicate coverpoint in {cg_name}: {cp_name}")
            local_cp.add(cp_name)
            expression = safe_sv(cp["expression"], f"{cg_name}.{cp_name}.expression")
            bins = cp["bins"]
            if not isinstance(bins, list) or not bins:
                raise SystemExit(f"ERROR: {cg_name}.{cp_name} requires bins")
            lines.append(f"    {cp_name}: coverpoint {expression} {{")
            for clause in bins:
                clause = safe_sv(clause, f"{cg_name}.{cp_name}.bins")
                if not clause.endswith(";"):
                    raise SystemExit(f"ERROR: bin clause must end with ';': {clause}")
                lines.append(f"      {clause}")
            lines.append("    }")
        for cross_index, cross in enumerate(cg["crosses"]):
            require_keys(cross, CROSS_KEYS, {"name", "items"},
                         f"{cg_name}.crosses[{cross_index}]")
            cross_name = ident(cross["name"], f"{cg_name}.cross")
            items = cross["items"]
            if not isinstance(items, list) or len(items) < 2:
                raise SystemExit(f"ERROR: {cg_name}.{cross_name} needs at least two items")
            checked = [ident(item, f"{cg_name}.{cross_name}.items") for item in items]
            if not set(checked).issubset(local_cp):
                raise SystemExit(f"ERROR: cross {cross_name} references unknown coverpoint")
            bins = cross.get("bins", [])
            if not isinstance(bins, list):
                raise SystemExit(f"ERROR: {cg_name}.{cross_name}.bins must be a list")
            if bins:
                lines.append(f"    {cross_name}: cross {', '.join(checked)} {{")
                for clause in bins:
                    clause = safe_sv(clause, f"{cg_name}.{cross_name}.bins")
                    if not clause.endswith(";"):
                        raise SystemExit(f"ERROR: cross bin clause must end with ';': {clause}")
                    lines.append(f"      {clause}")
                lines.append("    }")
            else:
                lines.append(f"    {cross_name}: cross {', '.join(checked)};")
        lines.extend(["  endgroup", ""])
    lines.extend([
        f"  function new(string name, uvm_component parent);",
        "    super.new(name, parent);",
    ])
    for name in cg_names:
        lines.append(f"    {name} = new();")
    lines.extend(["  endfunction", "endclass", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.out.exists() and not args.force:
        raise SystemExit(f"ERROR: refusing to overwrite: {args.out}")
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    output = render(spec)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(output, encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
