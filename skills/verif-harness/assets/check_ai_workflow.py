#!/usr/bin/env python3
"""Check verification documentation workflow and Markdown hygiene.

Configuration is read from `.harness-config.json` at the project root.
The script itself is project-agnostic: all paths and required files are
derived from that config.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


CONFIG_PATH = Path(".harness-config.json")


DOC_FILENAMES = {
    "verification_plan": "verification_plan.md",
    "coverage_plan": "coverage_plan.md",
    "assertion_plan": "assertion_plan.md",
    "testcase_list": "testcase_list.md",
    "tb_architecture": "tb_architecture.md",
    "feature_matrix": "feature_matrix.md",
    "reference_model_spec": "reference_model_spec.md",
}

DOCS_ROOT_FILENAMES = {
    "plan": "plan.md",
    "roadmap": "roadmap.md",
    "harness_style_methodology": "harness_style_methodology.md",
}

WORKFLOW_FILENAME = "verification_workflow.md"

REVIEW_BLOCK_HEADINGS = [
    "## Lifecycle",
    "## Review Trace",
    "## Revision Log",
    "## File-Level Human Review",
    "### Project-Level References",
    "### Review Metadata",
    "### Human Decisions",
    "### Human Review Notes",
    "### Approval Decision",
]

UNREVIEWED_CONCLUSION_PATTERNS = [
    "已确认的验证基线",
    "已确认结论",
    "最终结论",
    "最终以",
]

VALID_REVIEW_STATUSES = {"pending", "approved", "changes requested", "frozen", "draft"}


class Config:
    def __init__(self, data: dict) -> None:
        self.project_name: str = data["project_name"]
        rtl = data["rtl"]
        self.rtl_root = Path(rtl["root"])
        self.rtl_top_module: str = rtl["top_module"]
        self.rtl_top_file = Path(rtl["top_file"])

        verif = data["verif"]
        self.verif_root = Path(verif["root"])
        self.docs_root = Path(verif["docs_root"])
        self.verification_subdir = verif.get("verification_subdir", "verification")
        self.governance_subdir = verif.get("governance_subdir", "governance")

        design = data.get("design_docs") or {}
        design_root = design.get("root")
        self.design_docs_root = Path(design_root) if design_root else None

        refmodel = data.get("reference_model") or {}
        self.refmodel_enabled: bool = bool(refmodel.get("enabled", False))
        spec_path = refmodel.get("spec_path")
        self.refmodel_spec_path = Path(spec_path).expanduser() if spec_path else None

    @property
    def workflow_path(self) -> Path:
        return self.docs_root / self.governance_subdir / WORKFLOW_FILENAME

    @property
    def verification_docs_root(self) -> Path:
        return self.docs_root / self.verification_subdir

    def required_docs(self) -> list[Path]:
        docs: list[Path] = [Path("AGENTS.md")]
        for filename in DOCS_ROOT_FILENAMES.values():
            docs.append(self.docs_root / filename)
        for key, filename in DOC_FILENAMES.items():
            if key == "reference_model_spec" and not self.refmodel_enabled:
                continue
            docs.append(self.verification_docs_root / filename)
        docs.append(self.workflow_path)
        return docs

    def agent_required_references(self) -> list[str]:
        refs: list[str] = [str(self.workflow_path)]
        for filename in DOCS_ROOT_FILENAMES.values():
            refs.append(str(self.docs_root / filename))
        for key, filename in DOC_FILENAMES.items():
            if key == "reference_model_spec" and not self.refmodel_enabled:
                continue
            refs.append(str(self.verification_docs_root / filename))
        refs.append(".harness/check_ai_workflow.py")
        return refs


def load_config() -> Config:
    if not CONFIG_PATH.is_file():
        raise SystemExit(
            f"ERROR: missing {CONFIG_PATH}. Run the verif-harness skill to bootstrap it."
        )
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: {CONFIG_PATH} is not valid JSON: {exc}")
    try:
        return Config(data)
    except KeyError as exc:
        raise SystemExit(f"ERROR: {CONFIG_PATH} missing required field: {exc}")


def markdown_files(config: Config) -> list[Path]:
    files = [Path("AGENTS.md")]
    if Path("README.md").is_file():
        files.append(Path("README.md"))
    if config.docs_root.exists():
        files.extend(sorted(config.docs_root.rglob("*.md")))
    return [path for path in files if path.is_file()]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def is_fence(line: str) -> bool:
    return line.lstrip().startswith("```")


def is_top_level_list(line: str) -> bool:
    return bool(re.match(r"^(-|\*|\+)\s+", line) or re.match(r"^\d+\.\s+", line))


def normalize_blank_lines_around_lists(lines: list[str]) -> list[str]:
    out: list[str] = []
    in_fence = False
    prev_was_list = False

    for line in lines:
        if is_fence(line):
            in_fence = not in_fence
            out.append(line)
            prev_was_list = False
            continue

        current_is_list = not in_fence and is_top_level_list(line)
        if current_is_list and not prev_was_list and out and out[-1].strip():
            out.append("")

        if not current_is_list and prev_was_list and line.strip() and not line.startswith("  "):
            out.append("")

        out.append(line)
        prev_was_list = current_is_list

    return out


def normalize_bare_urls(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        url = match.group("url")
        if prefix in {"(", "<"}:
            return match.group(0)
        return f"{prefix}<{url}>"

    pattern = re.compile(r"(?P<prefix>^|[\s])(?P<url>https?://[^\s)<|]+)")
    return pattern.sub(repl, text)


def normalize_markdown(path: Path) -> bool:
    original = read_text(path)
    lines = [line.rstrip() for line in original.splitlines()]
    lines = normalize_blank_lines_around_lists(lines)

    collapsed: list[str] = []
    blank_run = 0
    for line in lines:
        if line.strip():
            blank_run = 0
            collapsed.append(line)
            continue
        blank_run += 1
        if blank_run <= 1:
            collapsed.append(line)

    normalized = normalize_bare_urls("\n".join(collapsed).rstrip() + "\n")
    if normalized == original:
        return False

    write_text(path, normalized)
    return True


def markdown_section(text: str, heading: str) -> str:
    lines = text.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return ""

    level = len(heading) - len(heading.lstrip("#"))
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if not line.startswith("#"):
            continue
        current_level = len(line) - len(line.lstrip("#"))
        if current_level <= level:
            end = index
            break

    return "\n".join(lines[start:end])


def extract_status(review_metadata: str) -> str | None:
    match = re.search(r"^- Status:\s*(.+?)\s*$", review_metadata, re.MULTILINE)
    return match.group(1).strip() if match else None


def extract_lifecycle_status(lifecycle: str) -> str | None:
    match = re.search(r"^Status:\s*(.+?)\s*$", lifecycle, re.MULTILINE)
    return match.group(1).strip() if match else None


def extract_review_trace_statuses(review_trace: str) -> list[str]:
    return [
        match.strip()
        for match in re.findall(r"^Status:\s*(.+?)\s*$", review_trace, re.MULTILINE)
    ]


def lifecycle_has_no_frozen_sections(lifecycle: str) -> bool:
    match = re.search(
        r"Frozen Sections:\s*\n(?P<body>.*?)(?:\nMutable Sections:|\Z)",
        lifecycle,
        re.DOTALL,
    )
    return bool(match and re.search(r"^- None\s*$", match.group("body"), re.MULTILINE))


def extract_referenced_paths(project_references: str) -> list[str]:
    paths: list[str] = []
    for line in project_references.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-") or stripped.lower() == "- none":
            continue
        paths.extend(re.findall(r"`([^`]+)`", stripped))
    return paths


def check_required_files(config: Config) -> list[str]:
    return [
        f"missing required document: {path}"
        for path in config.required_docs()
        if not path.is_file()
    ]


def check_agent_references(config: Config) -> list[str]:
    path = Path("AGENTS.md")
    if not path.is_file():
        return ["missing agent instruction file: AGENTS.md"]

    text = read_text(path)
    return [
        f"AGENTS.md must require reading {reference}"
        for reference in config.agent_required_references()
        if reference not in text
    ]


def check_review_blocks(config: Config) -> list[str]:
    errors: list[str] = []
    for path in config.required_docs():
        if not path.is_file():
            continue

        text = read_text(path)
        for heading in REVIEW_BLOCK_HEADINGS:
            if heading not in text:
                errors.append(f"{path} missing review heading: {heading}")

        project_references = markdown_section(text, "### Project-Level References")
        for reference in extract_referenced_paths(project_references):
            if not Path(reference).exists():
                errors.append(f"{path} project-level reference does not exist: {reference}")

        review_metadata = markdown_section(text, "### Review Metadata")
        approval_decision = markdown_section(text, "### Approval Decision").lower()
        status = extract_status(review_metadata)
        if status is None:
            errors.append(f"{path} missing review metadata status")
            continue

        normalized_status = status.lower()
        if normalized_status not in VALID_REVIEW_STATUSES:
            errors.append(f"{path} has unsupported review metadata status: {status}")

        decision_is_approved = "approved" in approval_decision
        decision_is_pending = "pending" in approval_decision
        if normalized_status == "approved" and not decision_is_approved:
            errors.append(f"{path} has approved status without approved decision")
        if normalized_status == "approved" and decision_is_pending:
            errors.append(f"{path} has approved status but decision is pending")
        if normalized_status == "pending" and not decision_is_pending:
            errors.append(f"{path} has pending status but decision is not pending")
        if normalized_status == "changes requested" and decision_is_approved:
            errors.append(f"{path} has changes requested status but approved decision")

        lifecycle = markdown_section(text, "## Lifecycle")
        lifecycle_status = extract_lifecycle_status(lifecycle)
        if lifecycle_status is None:
            errors.append(f"{path} missing lifecycle status")
        else:
            normalized_lifecycle_status = lifecycle_status.lower()
            if normalized_status == "pending" and normalized_lifecycle_status not in {"draft", "living"}:
                errors.append(f"{path} has pending review but lifecycle is {lifecycle_status}")
            if normalized_status == "approved" and normalized_lifecycle_status not in {"approved", "living"}:
                errors.append(f"{path} has approved review but lifecycle is {lifecycle_status}")
            if normalized_status == "frozen" and normalized_lifecycle_status != "frozen":
                errors.append(f"{path} has frozen review but lifecycle is {lifecycle_status}")
            if normalized_lifecycle_status == "approved" and normalized_status != "approved":
                errors.append(f"{path} lifecycle is approved but review metadata is {status}")
            if normalized_lifecycle_status == "frozen" and normalized_status != "frozen":
                errors.append(f"{path} lifecycle is frozen but review metadata is {status}")

        if normalized_status in {"approved", "frozen"} and lifecycle_has_no_frozen_sections(lifecycle):
            errors.append(f"{path} has approved/frozen status but no frozen sections")

        review_trace = markdown_section(text, "## Review Trace")
        review_trace_statuses = extract_review_trace_statuses(review_trace)
        if normalized_status in {"approved", "frozen"}:
            if "### Review Pending" in review_trace:
                errors.append(f"{path} has approved/frozen status but review trace is still pending")
            if not review_trace_statuses:
                errors.append(f"{path} missing review trace status")
            elif review_trace_statuses[-1].lower() != normalized_status:
                errors.append(
                    f"{path} latest review trace status is {review_trace_statuses[-1]} "
                    f"but review metadata is {status}"
                )

    return errors


def check_unreviewed_conclusion_language(config: Config) -> list[str]:
    errors: list[str] = []
    for path in config.required_docs():
        if not path.is_file():
            continue
        text = read_text(path)
        review_metadata = markdown_section(text, "### Review Metadata")
        status = extract_status(review_metadata)
        if status and status.lower() == "approved":
            continue
        if "\n## 假设\n" in text:
            errors.append(
                f"{path} uses plain assumption heading before approval; "
                "use '## 待 Human Review 的假设'"
            )
        for pattern in UNREVIEWED_CONCLUSION_PATTERNS:
            if pattern in text:
                errors.append(f"{path} uses conclusion language before approval: {pattern}")
    return errors


def check_markdownlint(config: Config) -> list[str]:
    targets = ["AGENTS.md"]
    if Path("README.md").is_file():
        targets.append("README.md")
    if config.docs_root.exists():
        targets.append(f"{config.docs_root}/**/*.md")
    result = subprocess.run(
        ["npx", "markdownlint-cli2", *targets],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode == 0:
        return []

    output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
    return [output or "markdownlint failed"]


def run_fix(config: Config) -> list[Path]:
    changed: list[Path] = []
    for path in markdown_files(config):
        if normalize_markdown(path):
            changed.append(path)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Verification workflow check")
    parser.add_argument("--fix", action="store_true",
                        help="apply safe Markdown formatting fixes before checking")
    parser.add_argument("--skip-markdownlint", action="store_true",
                        help="skip markdownlint-cli2 check")
    args = parser.parse_args()

    config = load_config()

    if args.fix:
        for path in run_fix(config):
            print(f"formatted: {path}")

    errors: list[str] = []
    errors.extend(check_required_files(config))
    errors.extend(check_agent_references(config))
    errors.extend(check_review_blocks(config))
    errors.extend(check_unreviewed_conclusion_language(config))
    if not args.skip_markdownlint:
        errors.extend(check_markdownlint(config))

    if errors:
        for message in errors:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
