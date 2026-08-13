#!/usr/bin/env python3
"""Audit a repository for structural open-source release readiness."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


REQUIRED = [
    "README.md", "LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
    "SECURITY.md", "ARCHITECTURE.md", "AGENTS.md",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/pull_request_template.md", ".github/workflows/ci.yml",
    "examples/simple_fifo/README.md", "scripts/run_example.sh",
]
SKIP_PARTS = {".git", "build", "dist", "site", "__pycache__", ".venv"}
SKIP_FILES = {Path(".github/public-release-denylist.txt")}
GENERIC_PATTERNS = {
    "ABSOLUTE_USER_PATH": re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/"),
    "PROJECT_MOUNT_PATH": re.compile(r"/(?:proj|projects)/[A-Za-z0-9._/-]+"),
    "LICENSE_SERVER": re.compile(r"\b\d{2,5}@[A-Za-z0-9.-]+\b"),
    "PRIVATE_DOMAIN": re.compile(r"https?://[^\s)]+\.(?:internal|corp)(?:[/:]|$)", re.I),
    "PLACEHOLDER_SECRET": re.compile(r"(?i)(?:password|private[_-]?key|access[_-]?token)\s*[:=]\s*[^<$\s][^\s]*"),
}


@dataclass
class Finding:
    severity: str
    code: str
    location: str
    message: str


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def included(path: Path) -> bool:
    return path not in SKIP_FILES and not any(part in SKIP_PARTS for part in path.parts)


def deny_terms(root: Path) -> list[str]:
    path = root / ".github/public-release-denylist.txt"
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def scan_text(text: str, location: str, terms: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for code, pattern in GENERIC_PATTERNS.items():
            if pattern.search(line):
                findings.append(Finding("ERROR", code, f"{location}:{line_no}",
                                        "sensitive pattern matched; content redacted"))
        lowered = line.casefold()
        for term in terms:
            if term.casefold() in lowered:
                findings.append(Finding("ERROR", "DENYLIST_TERM", f"{location}:{line_no}",
                                        f"forbidden identifier matched: {term}"))
    return findings


def scan_worktree(root: Path, terms: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or not included(relative):
            continue
        findings.extend(scan_text(str(relative), "repository path", terms))
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(scan_text(text, str(relative), terms))
    return findings


def scan_history(root: Path, terms: list[str]) -> list[Finding]:
    if git(root, "rev-parse", "--is-inside-work-tree").returncode != 0:
        return [Finding("ERROR", "GIT_REQUIRED", ".git", "history scan requested outside Git")]
    findings: list[Finding] = []
    log_text = git(root, "log", "--all", "--format=%H%n%B").stdout
    findings.extend(scan_text(log_text, "git log", terms))
    revisions = git(root, "rev-list", "--all").stdout.splitlines()
    for revision in revisions:
        paths = git(root, "ls-tree", "-r", "--name-only", revision).stdout.splitlines()
        for name in paths:
            relative = Path(name)
            if not included(relative):
                continue
            findings.extend(scan_text(name, f"{revision[:12]}:repository path", terms))
            result = git(root, "show", f"{revision}:{name}")
            if result.returncode != 0:
                continue
            findings.extend(scan_text(result.stdout, f"{revision[:12]}:{name}", terms))
    return findings


def audit(root: Path, require_community: bool, history: bool) -> tuple[dict, list[Finding]]:
    root = root.resolve()
    findings: list[Finding] = []
    if require_community:
        for name in REQUIRED:
            if not (root / name).is_file():
                findings.append(Finding("ERROR", "REQUIRED_FILE", name, "required public file missing"))
    license_text = (root / "LICENSE").read_text(encoding="utf-8", errors="replace") \
        if (root / "LICENSE").is_file() else ""
    if require_community and "Apache License" not in license_text:
        findings.append(Finding("ERROR", "LICENSE_TEXT", "LICENSE", "Apache-2.0 text not detected"))
    terms = deny_terms(root)
    findings.extend(scan_worktree(root, terms))
    if history:
        findings.extend(scan_history(root, terms))
    summary = {
        "state": "READY_FOR_HUMAN_REVIEW" if not findings else "NOT_READY",
        "errors": sum(item.severity == "ERROR" for item in findings),
        "history_scanned": history,
        "denylist_terms": len(terms),
    }
    return summary, findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--require-community", action="store_true")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    summary, findings = audit(args.project_root, args.require_community, args.history)
    if args.json:
        print(json.dumps({"summary": summary, "findings": [asdict(x) for x in findings]}, indent=2))
    else:
        print(f"OSS readiness: {summary['state']} ({summary['errors']} errors)")
        for item in findings:
            print(f"{item.severity} {item.code} {item.location}: {item.message}")
        print("A clean audit is not publication authorization.")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
