#!/usr/bin/env python3
"""Add one UVM test/vseq pair and register package includes additively."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verif_harness.case_traceability import (  # noqa: E402
    CaseTraceabilityError, confirmation_context, validate_traceability,
)

IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
SHA256 = re.compile(r"[0-9a-f]{64}")


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


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def project_path(root: Path, value: str, label: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit(f"ERROR: {label} must be a project-relative path")
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {label} must stay under project root") from exc
    return target


def load_submit_profile_ref(root: Path, path: Path) -> dict:
    source = path if path.is_absolute() else root / path
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: cannot read SubmitProfileRef: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "SubmitProfileRef/1":
        raise SystemExit("ERROR: submit profile ref schema must be SubmitProfileRef/1")
    profile_id = payload.get("profile_id")
    if not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", profile_id):
        raise SystemExit("ERROR: submit profile ref profile_id is invalid")
    submit_file = payload.get("submit_file")
    if not isinstance(submit_file, str) or not submit_file.strip():
        raise SystemExit("ERROR: submit profile ref submit_file is invalid")
    submit_path = project_path(root, submit_file, "submit_file")
    if not submit_path.is_file():
        raise SystemExit(f"ERROR: submit_file does not exist: {submit_file}")
    source_digest = payload.get("submit_file_digest")
    if not isinstance(source_digest, str) or not SHA256.fullmatch(source_digest):
        raise SystemExit("ERROR: submit_file_digest must be lowercase SHA-256")
    if file_digest(submit_path) != source_digest:
        raise SystemExit("ERROR: submit_file_digest does not match current submit file")
    profile_digest = payload.get("profile_digest")
    if not isinstance(profile_digest, str) or not SHA256.fullmatch(profile_digest):
        raise SystemExit("ERROR: profile_digest must be lowercase SHA-256")
    adapter = payload.get("adapter")
    if (not isinstance(adapter, dict) or
            not isinstance(adapter.get("name"), str) or not adapter["name"].strip() or
            not isinstance(adapter.get("version"), str) or not adapter["version"].strip()):
        raise SystemExit("ERROR: submit profile ref adapter name/version are required")
    return payload


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
    parser.add_argument("--submit-profile-ref", type=Path, required=True)
    parser.add_argument("--traceability", type=Path, required=True, help="用例来源、文件版本和预期结果依据 JSON")
    parser.add_argument("--entry-kind", choices=("testcase", "sequence"), default="testcase")
    parser.add_argument("--case-manifest-out", type=Path)
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
    submit_profile = load_submit_profile_ref(root, args.submit_profile_ref)
    traceability_path = args.traceability if args.traceability.is_absolute() else root / args.traceability
    def check_source(ref, kind):
        target = project_path(root, ref["path"], "用例来源")
        if not target.is_file() or file_digest(target) != ref["sha256"]:
            raise CaseTraceabilityError("用例来源文件缺失或版本已经变化：" + ref["path"])
    try:
        traceability = validate_traceability(json.loads(traceability_path.read_text(encoding="utf-8")),
                                             test_name, check_source)
    except (OSError, ValueError) as exc:
        raise SystemExit("ERROR: 用例来源或预期结果依据无效：" + str(exc)) from exc
    traceability_status = traceability["expected_result"]["status"]
    traceability_info = {"traceability_status": traceability_status,
                         "confirmation_context": confirmation_context(test_name, traceability),
                         "traceability_notice": ("RTL 推导，尚未确认；完成负责人确认前不能作为交付通过依据"
                                                 if traceability_status == "rtl-derived-unconfirmed" else
                                                 "负责人确认记录须由控制面核对" if traceability_status == "confirmed" else "")}
    safe_profile = re.sub(r"[^A-Za-z0-9_.-]+", "-", submit_profile["profile_id"])
    manifest_path = args.case_manifest_out
    if manifest_path is None:
        manifest_path = verif_root / "regress" / "cases" / f"{test_name}--{safe_profile}.case.json"
    elif not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    manifest_path = manifest_path.resolve()
    try:
        manifest_path.relative_to(root)
    except ValueError as exc:
        raise SystemExit("ERROR: case manifest must stay under project root") from exc
    for path in (test_path, vseq_path, manifest_path):
        if path.exists():
            raise SystemExit(f"ERROR: refusing to overwrite: {path}")
    new_test_pkg = insert_include(test_pkg.read_text(encoding="utf-8"), test_path.name)
    new_env_pkg = insert_include(env_pkg.read_text(encoding="utf-8"), f"vseq/{vseq_path.name}")
    actions = [str(test_path), str(vseq_path), str(test_pkg), str(env_pkg), str(manifest_path)]
    if args.dry_run:
        print(json.dumps({"dry_run": True, "would_update": actions, **traceability_info}, indent=2))
        return 0

    test_dir.mkdir(parents=True, exist_ok=True)
    vseq_dir.mkdir(parents=True, exist_ok=True)
    test_path.write_text(test_source(test_name, base_test, vseq_name), encoding="utf-8")
    vseq_path.write_text(vseq_source(vseq_name, base_vseq), encoding="utf-8")
    test_pkg.write_text(new_test_pkg, encoding="utf-8")
    env_pkg.write_text(new_env_pkg, encoding="utf-8")
    source_paths = (test_path, vseq_path, test_pkg, env_pkg)
    manifest = {
        "schema": "CaseManifest/2",
        "case_id": test_name,
        "entry": ({"kind": "testcase", "name": test_name}
                  if args.entry_kind == "testcase" else
                  {"kind": "sequence", "name": vseq_name, "launcher_test": test_name}),
        "source_files": [
            {"path": str(path.relative_to(root)), "sha256": file_digest(path)}
            for path in source_paths
        ],
        "submit_profile": submit_profile, "traceability": traceability,
    }
    manifest["case_digest"] = canonical_digest(manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"created": [str(test_path), str(vseq_path), str(manifest_path)],
                      "registered": [str(test_pkg), str(env_pkg)],
                      "submit_profile_id": submit_profile["profile_id"], **traceability_info}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
