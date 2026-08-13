#!/usr/bin/env python3
"""Audit structural completeness of a final RTL verification sign-off packet."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Finding:
    severity: str
    code: str
    message: str


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def manifest_entries(path: Path) -> list[str]:
    entries: list[str] = []
    for line in read(path).splitlines():
        value = line.split("#", 1)[0].strip()
        if value:
            entries.append(value.split()[0])
    return entries


def git_output(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], check=False,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def audit(root: Path, stage: int, packet_arg: Path | None,
          manifest_arg: Path | None) -> tuple[dict, list[Finding]]:
    root = root.resolve()
    findings: list[Finding] = []
    config_path = root / ".harness-config.json"
    if not config_path.is_file():
        return {}, [Finding("ERROR", "CONFIG_MISSING", ".harness-config.json is missing")]
    config = json.loads(read(config_path))
    docs_root = resolve(root, Path(config["verif"]["docs_root"]))
    rtl_root = Path(config["rtl"]["root"])
    packet = resolve(root, packet_arg) if packet_arg else docs_root / f"stage{stage}_gate_re_review.md"
    manifest = resolve(root, manifest_arg) if manifest_arg else docs_root / "caselist" / "default_regression.caselist"
    if not packet.is_file():
        findings.append(Finding("ERROR", "PACKET_MISSING", f"Sign-off packet missing: {packet}"))
        packet_text = ""
    else:
        packet_text = read(packet)
    if not manifest.is_file():
        findings.append(Finding("ERROR", "MANIFEST_MISSING", f"Manifest missing: {manifest}"))
    entries = manifest_entries(manifest)
    duplicates = sorted({item for item in entries if entries.count(item) > 1})
    if not entries:
        findings.append(Finding("ERROR", "MANIFEST_EMPTY", "Regression manifest has no cases"))
    if duplicates:
        findings.append(Finding("ERROR", "MANIFEST_DUPLICATE", ", ".join(duplicates)))

    status_match = re.search(r"^- \*\*Status\*\*:\s*(.+?)\s*$", packet_text, re.MULTILINE)
    reviewer_match = re.search(r"^- \*\*Reviewer\*\*:\s*(.+?)\s*$", packet_text, re.MULTILINE)
    date_match = re.search(r"^- \*\*Decision date\*\*:\s*(.+?)\s*$", packet_text, re.MULTILINE | re.IGNORECASE)
    status = status_match.group(1).strip() if status_match else "MISSING"
    reviewer = reviewer_match.group(1).strip() if reviewer_match else "MISSING"
    decision_date = date_match.group(1).strip() if date_match else "MISSING"
    approved = status.lower() == "approved"
    if status == "MISSING":
        findings.append(Finding("ERROR", "STATUS_MISSING", "Packet metadata has no Status"))
    if approved and reviewer.lower() in {"missing", "tbd", "pending"}:
        findings.append(Finding("ERROR", "APPROVER_MISSING", "Approved packet lacks a concrete reviewer"))
    if approved and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", decision_date):
        findings.append(Finding("ERROR", "DECISION_DATE", "Approved packet lacks YYYY-MM-DD decision date"))

    required_topics = {
        "REGRESSION_EVIDENCE": r"regression",
        "FUNCTIONAL_COVERAGE": r"functional coverage",
        "ASSERTION_EVIDENCE": r"assertion",
        "CI_EVIDENCE": r"\bCI\b|GitLab|Jenkins",
        "OPEN_QUESTION_REVIEW": r"Open[- ]Question|开放问题",
        "CHANGE_REQUEST_REVIEW": r"Change Request|CR-\d+",
    }
    for code, pattern in required_topics.items():
        if not re.search(pattern, packet_text, re.IGNORECASE):
            findings.append(Finding("ERROR", code, f"Packet lacks required topic: {code}"))
    placeholder_pattern = re.compile(
        r"(?im)(?:^\s*(?:TBD|TODO|PENDING)\b|:\s*(?:TBD|TODO|PENDING)\s*$|"
        r"\|\s*(?:TBD|TODO|PENDING)\s*\||\{\{[^}]+\}\})"
    )
    if placeholder_pattern.search(packet_text):
        findings.append(Finding("WARNING", "PLACEHOLDER_TEXT", "Packet still contains TBD/TODO/PENDING text"))
    if not re.search(r"artifact|evidence boundary|证据边界|unavailable|无法归档", packet_text, re.IGNORECASE):
        findings.append(Finding("WARNING", "EVIDENCE_BOUNDARY", "Packet does not state artifact/evidence availability"))

    rtl_changes = set(git_output(root, "diff", "--name-only", "--", str(rtl_root)).splitlines())
    rtl_changes.update(git_output(root, "diff", "--cached", "--name-only", "--", str(rtl_root)).splitlines())
    rtl_changes.discard("")
    if rtl_changes:
        findings.append(Finding("ERROR", "RTL_DIRTY", ", ".join(sorted(rtl_changes))))
    head = git_output(root, "rev-parse", "--short=12", "HEAD") or "unknown"
    branch = git_output(root, "branch", "--show-current") or "unknown"
    errors = sum(item.severity == "ERROR" for item in findings)
    if errors:
        state = "INCOMPLETE"
    elif approved:
        state = "APPROVED_RECORDED"
    else:
        state = "READY_FOR_HUMAN_REVIEW"
    summary = {
        "state": state,
        "stage": stage,
        "packet": str(packet),
        "packet_status": status,
        "reviewer": reviewer,
        "decision_date": decision_date,
        "manifest": str(manifest),
        "manifest_entries": len(entries),
        "unique_manifest_entries": len(set(entries)),
        "git_head": head,
        "branch": branch,
    }
    return summary, findings


def markdown(summary: dict, findings: list[Finding]) -> str:
    lines = ["# Sign-off Structural Audit", ""]
    if summary:
        lines.extend([
            f"- State: **{summary['state']}**",
            f"- Stage: {summary['stage']}",
            f"- Packet status: `{summary['packet_status']}`",
            f"- Reviewer/date: `{summary['reviewer']}` / `{summary['decision_date']}`",
            f"- Manifest: {summary['manifest_entries']} entries / {summary['unique_manifest_entries']} unique",
            f"- Git: `{summary['branch']}` @ `{summary['git_head']}`",
            "",
        ])
    lines.extend(["## Findings", ""])
    lines.extend(
        [f"- **{item.severity} {item.code}**: {item.message}" for item in findings]
        or ["- None."]
    )
    lines.extend(["", "> APPROVED_RECORDED describes repository metadata; it is not a new approval.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    summary, findings = audit(args.project_root, args.stage, args.packet, args.manifest)
    payload = (json.dumps({"summary": summary, "findings": [asdict(item) for item in findings]}, indent=2) + "\n"
               if args.json else markdown(summary, findings))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    errors = any(item.severity == "ERROR" for item in findings)
    warnings = any(item.severity == "WARNING" for item in findings)
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
