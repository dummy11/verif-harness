#!/usr/bin/env python3
"""Add one UVM test/vseq pair and register package includes additively."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


def safe_identifier(value: str, label: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise SystemExit(f"ERROR: unsafe {label}: {value}")
    return value


def load_config(root: Path) -> dict:
    path = root / ".harness-config.json"
    if not path.is_file():
        raise SystemExit("ERROR: .harness-config.json is missing")
    return json.loads(path.read_text(encoding="utf-8"))


def unique_package(directory: Path, suffix: str) -> Path:
    matches = sorted(directory.glob(f"*{suffix}"))
    if len(matches) != 1:
        raise SystemExit(
            f"ERROR: expected exactly one *{suffix} under {directory}, found {len(matches)}"
        )
    return matches[0]


def insert_include(text: str, filename: str) -> str:
    directive = f'  `include "{filename}"'
    if re.search(rf'`include\s+"{re.escape(filename)}"', text):
        raise SystemExit(f"ERROR: include already registered: {filename}")
    matches = list(re.finditer(r"^endpackage\s*$", text, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit("ERROR: package must contain exactly one endpackage line")
    pos = matches[0].start()
    return text[:pos].rstrip() + "\n" + directive + "\n" + text[pos:]


def test_source(test_name: str, base_test: str, vseq_name: str) -> str:
    return f'''// Generated control skeleton. Add testcase/feature traceability before review.
class {test_name} extends {base_test};
  `uvm_component_utils({test_name})

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  task run_phase(uvm_phase phase);
    {vseq_name} vseq;
    phase.raise_objection(this, "{test_name} running");
    vseq = {vseq_name}::type_id::create("vseq");
    vseq.start(env.vseqr);
    phase.drop_objection(this, "{test_name} done");
  endtask
endclass
'''


def vseq_source(vseq_name: str, base_vseq: str) -> str:
    return f'''// Generated virtual-sequence skeleton. Replace TODO with approved stimulus.
class {vseq_name} extends {base_vseq};
  `uvm_object_utils({vseq_name})

  function new(string name = "{vseq_name}");
    super.new(name);
  endfunction

  task body();
    `uvm_info(get_type_name(), "TODO: implement approved testcase stimulus", UVM_LOW)
  endtask
endclass
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--test-name", required=True)
    parser.add_argument("--vseq-name")
    parser.add_argument("--base-test", required=True)
    parser.add_argument("--base-vseq", required=True)
    parser.add_argument("--candidate-caselist", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = args.project_root.resolve()
    test_name = safe_identifier(args.test_name, "test name")
    if not test_name.endswith("_test"):
        raise SystemExit("ERROR: test name must end with _test")
    vseq_name = safe_identifier(
        args.vseq_name or test_name[:-5] + "_vseq", "vseq name"
    )
    if not vseq_name.endswith("_vseq"):
        raise SystemExit("ERROR: vseq name must end with _vseq")
    base_test = safe_identifier(args.base_test, "base test")
    base_vseq = safe_identifier(args.base_vseq, "base vseq")
    config = load_config(root)
    verif_root = root / config["verif"]["root"]
    test_dir = verif_root / "testbench" / "test"
    vseq_dir = verif_root / "testbench" / "env" / "vseq"
    test_pkg = unique_package(test_dir, "_test_pkg.sv")
    env_pkg = unique_package(verif_root / "testbench" / "env", "_env_pkg.sv")
    test_path = test_dir / f"{test_name}.svh"
    vseq_path = vseq_dir / f"{vseq_name}.svh"
    for path in (test_path, vseq_path):
        if path.exists():
            raise SystemExit(f"ERROR: refusing to overwrite: {path}")
    new_test_pkg = insert_include(test_pkg.read_text(encoding="utf-8"), test_path.name)
    new_env_pkg = insert_include(env_pkg.read_text(encoding="utf-8"), f"vseq/{vseq_path.name}")
    caselist = args.candidate_caselist
    if caselist and not caselist.is_absolute():
        caselist = root / caselist
    if caselist and caselist.is_file():
        entries = {
            line.split("#", 1)[0].strip().split()[0]
            for line in caselist.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        if test_name in entries:
            raise SystemExit(f"ERROR: testcase already in candidate caselist: {test_name}")

    actions = [str(test_path), str(vseq_path), str(test_pkg), str(env_pkg)]
    if caselist:
        actions.append(str(caselist))
    if args.dry_run:
        print(json.dumps({"dry_run": True, "would_update": actions}, indent=2))
        return 0

    test_dir.mkdir(parents=True, exist_ok=True)
    vseq_dir.mkdir(parents=True, exist_ok=True)
    test_path.write_text(test_source(test_name, base_test, vseq_name), encoding="utf-8")
    vseq_path.write_text(vseq_source(vseq_name, base_vseq), encoding="utf-8")
    test_pkg.write_text(new_test_pkg, encoding="utf-8")
    env_pkg.write_text(new_env_pkg, encoding="utf-8")
    if caselist:
        caselist.parent.mkdir(parents=True, exist_ok=True)
        prefix = caselist.read_text(encoding="utf-8") if caselist.exists() else ""
        separator = "\n" if prefix.strip() else ""
        caselist.write_text(prefix.rstrip() + separator + f"{test_name}\n", encoding="utf-8")
    print(json.dumps({"created": [str(test_path), str(vseq_path)],
                      "registered": actions[2:]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
