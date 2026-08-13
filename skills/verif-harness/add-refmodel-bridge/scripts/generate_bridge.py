#!/usr/bin/env python3
"""Generate a Syscan wrapper or DPI-C import package from JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


def ident(value: str, where: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise SystemExit(f"ERROR: unsafe identifier for {where}: {value}")
    return value


def sv_text(value: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"ERROR: empty text for {where}")
    if re.search(r"\b(?:endmodule|endpackage)\b", value):
        raise SystemExit(f"ERROR: forbidden terminator in {where}")
    return value.strip()


def render_syscan(spec: dict) -> str:
    required = {"backend", "guard", "wrapper_name", "ports", "syscan"}
    if set(spec) != required:
        raise SystemExit(f"ERROR: syscan top keys must be {sorted(required)}")
    guard = ident(spec["guard"], "guard")
    wrapper = ident(spec["wrapper_name"], "wrapper_name")
    ports = spec["ports"]
    if not isinstance(ports, list) or not ports:
        raise SystemExit("ERROR: ports must be non-empty")
    backend = spec["syscan"]
    if set(backend) != {"golden_module", "instance", "connections", "disabled_assignments"}:
        raise SystemExit(
            "ERROR: syscan requires golden_module, instance, connections, disabled_assignments"
        )
    golden = ident(backend["golden_module"], "golden_module")
    instance = ident(backend["instance"], "instance")
    connections = backend["connections"]
    if not isinstance(connections, dict) or not connections:
        raise SystemExit("ERROR: syscan connections must be non-empty")
    disabled = backend["disabled_assignments"]
    if not isinstance(disabled, dict):
        raise SystemExit("ERROR: syscan disabled_assignments must be an object")
    mapped = [f"    .{ident(port, 'connection port')}({sv_text(expr, 'connection expression')})"
              for port, expr in connections.items()]
    fallback = [
        f"  assign {sv_text(lhs, 'disabled assignment lhs')} = "
        f"{sv_text(rhs, 'disabled assignment rhs')};"
        for lhs, rhs in disabled.items()
    ]
    return "\n".join([
        "// Structural Syscan adapter. Compare/alignment semantics remain project-specific.",
        f"module {wrapper} (",
        "  " + ",\n  ".join(sv_text(port, "port") for port in ports),
        ");",
        f"`ifdef {guard}",
        f"  {golden} {instance} (",
        ",\n".join(mapped),
        "  );",
        "`else",
        *fallback,
        "  initial $warning(\"Golden backend is not compiled; comparison must not be reported PASS\");",
        "`endif",
        "endmodule",
        "",
    ])


def render_dpi(spec: dict) -> str:
    required = {"backend", "guard", "package_name", "functions"}
    if set(spec) != required:
        raise SystemExit(f"ERROR: dpi-c top keys must be {sorted(required)}")
    guard = ident(spec["guard"], "guard")
    package = ident(spec["package_name"], "package_name")
    functions = spec["functions"]
    if not isinstance(functions, list) or not functions:
        raise SystemExit("ERROR: functions must be non-empty")
    lines = ["// Reviewed DPI-C declarations; semantic orchestration remains project-specific.",
             f"package {package};", f"`ifdef {guard}"]
    for index, function in enumerate(functions):
        if not isinstance(function, dict) or set(function) != {"name", "signature", "plan_ref"}:
            raise SystemExit(f"ERROR: functions[{index}] requires name, signature, plan_ref")
        name = ident(function["name"], f"functions[{index}].name")
        signature = sv_text(function["signature"], f"functions[{index}].signature")
        if name not in signature or not signature.endswith(";"):
            raise SystemExit(f"ERROR: DPI signature must contain {name} and end with ';'")
        plan_ref = function["plan_ref"]
        if not isinstance(plan_ref, str) or not plan_ref.strip():
            raise SystemExit(f"ERROR: {name} requires plan_ref")
        lines.extend([f"  // Plan: {plan_ref}", f"  import \"DPI-C\" {signature}"])
    lines.extend(["`endif", "endpackage", ""])
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
    backend = spec.get("backend")
    if backend == "syscan":
        output = render_syscan(spec)
    elif backend == "dpi-c":
        output = render_dpi(spec)
    else:
        raise SystemExit(f"ERROR: unsupported backend: {backend}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(output, encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
