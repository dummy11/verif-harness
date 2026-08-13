#!/usr/bin/env python3
"""Generate an SVA checker and optional bind statement from JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
ASSERTION_ID = re.compile(r"A\.[A-Z0-9][A-Z0-9_.-]*")
TOP_KEYS = {"module_name", "ports", "clock", "disable_iff", "assertions", "bind"}
ASSERT_KEYS = {"id", "name", "plan_ref", "property", "message"}
BIND_KEYS = {"target", "instance", "connections"}


def ident(value: str, where: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise SystemExit(f"ERROR: unsafe identifier for {where}: {value}")
    return value


def sv_text(value: str, where: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise SystemExit(f"ERROR: invalid SystemVerilog text for {where}")
    if re.search(r"\b(?:endmodule|endpackage|endclass)\b", value):
        raise SystemExit(f"ERROR: forbidden terminator in {where}")
    return value.strip()


def validate_keys(obj: dict, allowed: set[str], required: set[str], where: str) -> None:
    unknown = set(obj) - allowed
    missing = required - set(obj)
    if unknown or missing:
        raise SystemExit(f"ERROR: {where}: unknown={sorted(unknown)} missing={sorted(missing)}")


def render_checker(spec: dict) -> str:
    validate_keys(spec, TOP_KEYS, {"module_name", "ports", "clock", "disable_iff", "assertions"}, "top")
    module_name = ident(spec["module_name"], "module_name")
    ports = spec["ports"]
    if not isinstance(ports, list) or not ports:
        raise SystemExit("ERROR: ports must be a non-empty list")
    checked_ports = [sv_text(port, "ports") for port in ports]
    clock = sv_text(spec["clock"], "clock")
    disable = sv_text(spec["disable_iff"], "disable_iff")
    if not isinstance(spec["assertions"], list) or not spec["assertions"]:
        raise SystemExit("ERROR: assertions must be a non-empty list")
    lines = [f"module {module_name} (", "  " + ",\n  ".join(checked_ports), ");", ""]
    ids: set[str] = set()
    names: set[str] = set()
    for index, assertion in enumerate(spec["assertions"]):
        validate_keys(assertion, ASSERT_KEYS, {"id", "name", "plan_ref", "property", "message"},
                      f"assertions[{index}]")
        assertion_id = assertion["id"]
        if not isinstance(assertion_id, str) or not ASSERTION_ID.fullmatch(assertion_id):
            raise SystemExit(f"ERROR: invalid assertion ID: {assertion_id}")
        name = ident(assertion["name"], f"assertions[{index}].name")
        if assertion_id in ids or name in names:
            raise SystemExit(f"ERROR: duplicate assertion ID or name: {assertion_id}/{name}")
        ids.add(assertion_id)
        names.add(name)
        plan_ref = assertion["plan_ref"]
        if not isinstance(plan_ref, str) or not plan_ref.strip():
            raise SystemExit(f"ERROR: {assertion_id} requires plan_ref")
        prop = sv_text(assertion["property"], f"{assertion_id}.property", allow_empty=True)
        message = assertion["message"]
        if not isinstance(message, str) or '"' in message or "\n" in message:
            raise SystemExit(f"ERROR: unsafe assertion message for {assertion_id}")
        lines.extend([f"  // {assertion_id} · {plan_ref}"])
        if not prop:
            lines.extend([f"  // TODO {name}: property expression not approved.", ""])
            continue
        lines.extend([
            f"  property p_{name};",
            f"    @({clock}) disable iff ({disable})",
            f"      {prop};",
            "  endproperty",
            f"  a_{name}: assert property (p_{name})",
            f"    else $error(\"[{assertion_id}] {message}\");",
            f"  c_{name}: cover property (p_{name});",
            "",
        ])
    lines.extend(["endmodule", ""])
    return "\n".join(lines)


def render_bind(spec: dict) -> str | None:
    bind = spec.get("bind")
    if bind is None:
        return None
    validate_keys(bind, BIND_KEYS, BIND_KEYS, "bind")
    target = ident(bind["target"], "bind.target")
    instance = ident(bind["instance"], "bind.instance")
    module_name = ident(spec["module_name"], "module_name")
    connections = bind["connections"]
    if not isinstance(connections, dict) or not connections:
        raise SystemExit("ERROR: bind.connections must be a non-empty object")
    mapped = []
    for port, expression in connections.items():
        mapped.append(f"    .{ident(port, 'bind port')}({sv_text(expression, 'bind expression')})")
    return f"bind {target} {module_name} {instance} (\n" + ",\n".join(mapped) + "\n);\n"


def write(path: Path, text: str, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f"ERROR: refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--checker-out", type=Path, required=True)
    parser.add_argument("--bind-out", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.bind_out is not None and args.checker_out.resolve() == args.bind_out.resolve():
        raise SystemExit("ERROR: checker and bind outputs must be different files")
    outputs = [args.checker_out] + ([args.bind_out] if args.bind_out is not None else [])
    if not args.force:
        existing = [path for path in outputs if path.exists()]
        if existing:
            raise SystemExit("ERROR: refusing to overwrite: " + ", ".join(map(str, existing)))
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    checker = render_checker(spec)
    bind = render_bind(spec)
    if bind is not None and args.bind_out is None:
        raise SystemExit("ERROR: spec contains bind but --bind-out was not provided")
    write(args.checker_out, checker, True)
    if bind is not None:
        write(args.bind_out, bind, True)
    print(args.checker_out)
    if bind is not None:
        print(args.bind_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
