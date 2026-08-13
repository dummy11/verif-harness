#!/usr/bin/env python3
"""Audit structural traceability among plans, UVM tests, and a caselist."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path


TEST_CLASS_RE = re.compile(r"\bclass\s+(\w+_test)\b(?:\s*#\s*\([^;]*\))?\s+extends\b", re.DOTALL)
TEST_NAME_RE = re.compile(r"\b[A-Za-z_]\w*_test\b")
ID_PATTERNS = {
    "testcase": re.compile(r"\bT\.[A-Z0-9][A-Z0-9_.-]*\b"),
    "feature": re.compile(r"\bF\.[A-Z0-9][A-Z0-9_.-]*\b"),
    "coverage": re.compile(r"\bC\.[A-Z0-9][A-Z0-9_.-]*\b"),
    "assertion": re.compile(r"\bA\.[A-Z0-9][A-Z0-9_.-]*\b"),
}


@dataclass
class Finding:
    severity: str
    code: str
    message: str


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def caselist_entries(path: Path) -> list[str]:
    entries: list[str] = []
    for line in read(path).splitlines():
        item = line.split("#", 1)[0].strip()
        if item:
            entries.append(item.split()[0])
    return entries


def scan_test_classes(test_root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not test_root.exists():
        return result
    for path in sorted(test_root.rglob("*.sv*")):
        for match in TEST_CLASS_RE.finditer(read(path)):
            result[match.group(1)] = str(path)
    return result


def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def build_report(root: Path, manifest_arg: Path | None) -> tuple[dict, list[Finding]]:
    root = root.resolve()
    findings: list[Finding] = []
    config_path = root / ".harness-config.json"
    if not config_path.is_file():
        return {}, [Finding("ERROR", "CONFIG_MISSING", ".harness-config.json is missing")]
    try:
        config = json.loads(read(config_path))
    except json.JSONDecodeError as exc:
        return {}, [Finding("ERROR", "CONFIG_INVALID", str(exc))]

    verif_cfg = config.get("verif", {})
    verif_root = root / verif_cfg.get("root", "sim")
    docs_root = root / verif_cfg.get("docs_root", str(verif_root / "docs"))
    vsub = verif_cfg.get("verification_subdir", "verification")
    plan_root = docs_root / vsub
    test_root = verif_root / "testbench" / "test"
    manifest = manifest_arg
    if manifest is None:
        manifest = docs_root / "caselist" / "default_regression.caselist"
    elif not manifest.is_absolute():
        manifest = root / manifest

    if not manifest.is_file():
        findings.append(Finding("ERROR", "MANIFEST_MISSING", f"Manifest not found: {relative(manifest, root)}"))
    classes = scan_test_classes(test_root)
    entries = caselist_entries(manifest)
    counts = Counter(entries)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    unknown = sorted(set(entries) - set(classes))
    base_tests = {name for name in classes if name.endswith("base_test")}
    orphan = sorted(set(classes) - set(entries) - base_tests)

    if duplicates:
        findings.append(Finding("ERROR", "MANIFEST_DUPLICATE", ", ".join(duplicates)))
    if unknown:
        findings.append(Finding("ERROR", "MANIFEST_UNKNOWN_TEST", ", ".join(unknown)))
    if orphan:
        findings.append(Finding("WARNING", "TEST_NOT_IN_MANIFEST", ", ".join(orphan)))

    testcase_doc = plan_root / "testcase_list.md"
    prefix_counts = Counter(name.split("_", 1)[0] for name in classes if "_" in name)
    class_prefix = prefix_counts.most_common(1)[0][0] + "_" if prefix_counts else ""
    documented_tests = {
        name for name in TEST_NAME_RE.findall(read(testcase_doc))
        if not class_prefix or name.startswith(class_prefix)
    }
    documented_missing = sorted(documented_tests - set(classes))
    undocumented_classes = sorted(set(classes) - documented_tests - base_tests)
    if documented_missing:
        findings.append(Finding("WARNING", "DOCUMENTED_TEST_MISSING", ", ".join(documented_missing)))
    if undocumented_classes:
        findings.append(Finding("WARNING", "TEST_NOT_DOCUMENTED", ", ".join(undocumented_classes)))

    doc_paths = {
        "testcase": testcase_doc,
        "feature": plan_root / "feature_matrix.md",
        "coverage": plan_root / "coverage_plan.md",
        "assertion": plan_root / "assertion_plan.md",
    }
    id_summary: dict[str, dict] = {}
    sv_text = "\n".join(read(path) for path in sorted((verif_root / "testbench").rglob("*.sv*")))
    for kind, pattern in ID_PATTERNS.items():
        ids = sorted(set(pattern.findall(read(doc_paths[kind]))))
        mentioned_in_sv = sorted(identifier for identifier in ids if identifier in sv_text)
        id_summary[kind] = {
            "document": relative(doc_paths[kind], root),
            "defined": len(ids),
            "mentioned_in_sv": len(mentioned_in_sv),
            "ids": ids,
        }

    report = {
        "project_root": str(root),
        "manifest": relative(manifest, root),
        "test_classes": len(classes),
        "manifest_entries": len(entries),
        "unique_manifest_entries": len(set(entries)),
        "documented_test_names": len(documented_tests),
        "inferred_test_prefix": class_prefix,
        "id_summary": id_summary,
        "test_class_files": {name: relative(Path(path), root) for name, path in sorted(classes.items())},
    }
    return report, findings


def markdown(report: dict, findings: list[Finding]) -> str:
    lines = ["# Verification Traceability Audit", ""]
    if report:
        lines.extend([
            f"- Manifest: `{report['manifest']}`",
            f"- UVM test classes: {report['test_classes']}",
            f"- Manifest entries: {report['manifest_entries']} ({report['unique_manifest_entries']} unique)",
            f"- Test names in testcase document: {report['documented_test_names']}",
            "",
            "## Verification ID inventory",
            "",
            "| Kind | Defined in plan | Mentioned in SV |",
            "|---|---:|---:|",
        ])
        for kind, values in report["id_summary"].items():
            lines.append(f"| {kind} | {values['defined']} | {values['mentioned_in_sv']} |")
        lines.append("")
    lines.extend(["## Findings", ""])
    if findings:
        for finding in findings:
            lines.append(f"- **{finding.severity} {finding.code}**: {finding.message}")
    else:
        lines.append("- None.")
    lines.append("")
    lines.append("> Structural mapping only; this report does not prove semantic coverage or simulation PASS.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    report, findings = build_report(args.project_root, args.manifest)
    payload = json.dumps({"report": report, "findings": [asdict(f) for f in findings]}, indent=2) + "\n" if args.json else markdown(report, findings)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    has_error = any(f.severity == "ERROR" for f in findings)
    has_warning = any(f.severity == "WARNING" for f in findings)
    return 1 if has_error or (args.strict and has_warning) else 0


if __name__ == "__main__":
    raise SystemExit(main())
