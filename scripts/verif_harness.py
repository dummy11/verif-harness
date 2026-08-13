#!/usr/bin/env python3
"""Generate an additive DUT integration skeleton from public templates."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")
FILES = {
    "dut_if.sv.tmpl": "interfaces/{dut}_if.sv",
    "dut_tb_harness.sv.tmpl": "tb/harness/{dut}_tb_harness.sv",
    "dut_tb_top.sv.tmpl": "tb/{dut}_tb_top.sv",
    "dut_checker.sv.tmpl": "sva/{dut}_checker.sv",
    "dut_bind.sv.tmpl": "bind/{dut}_bind.sv",
    "dut.f.tmpl": "filelists/{dut}.f",
}


def generate(dut: str, output: Path, templates: Path, dry_run: bool) -> list[Path]:
    if not IDENTIFIER.fullmatch(dut):
        raise SystemExit("ERROR: DUT name must match [a-z][a-z0-9_]*")
    if not templates.is_dir():
        raise SystemExit(f"ERROR: template directory missing: {templates}")
    targets = [output / pattern.format(dut=dut) for pattern in FILES.values()]
    existing = [path for path in targets if path.exists()]
    if existing:
        raise SystemExit("ERROR: refusing to overwrite: " + ", ".join(map(str, existing)))
    if dry_run:
        return targets
    for template_name, pattern in FILES.items():
        source = templates / template_name
        if not source.is_file():
            raise SystemExit(f"ERROR: template missing: {source}")
        target = output / pattern.format(dut=dut)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8").replace("<DUT>", dut), encoding="utf-8")
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init", help="generate a DUT integration skeleton")
    init.add_argument("dut")
    init.add_argument("--output", type=Path, default=Path.cwd())
    init.add_argument("--templates", type=Path,
                      default=Path(__file__).resolve().parents[1] / "templates/dut")
    init.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    targets = generate(args.dut, args.output.resolve(), args.templates.resolve(), args.dry_run)
    print(json.dumps({"dry_run": args.dry_run, "files": [str(path) for path in targets]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
