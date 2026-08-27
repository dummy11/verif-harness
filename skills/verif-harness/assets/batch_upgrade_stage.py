#!/usr/bin/env python3
"""Batch upgrade Stage <N> docs from Draft/Pending to Approved / Living.

Reads .harness-config.json for project doc paths, then updates all
required docs' Lifecycle + Review Trace + Review Metadata + Approval
Decision + Revision Log in one pass.

Usage:
    python3 .harness/batch_upgrade_stage.py --stage 0 --date 2026-07-07
    python3 .harness/batch_upgrade_stage.py --stage 1 --date 2026-10-15 \\
        --living sim/docs/verification/coverage_plan.md \\
        --living sim/docs/verification/testcase_list.md
    python3 .harness/batch_upgrade_stage.py --stage 0 --date 2026-07-07 --dry-run

Options:
    --stage N              Stage number (0 = initial baseline).
    --date YYYY-MM-DD      Approval date. Defaults to today.
    --living <path>        Mark this doc as Living lifecycle (repeat as needed).
                           Path is relative to project root.
    --dry-run              Preview without writing.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

CONFIG_PATH = Path(".harness-config.json")

# Default docs to mark Living for growth (Stage 3+ evolution)
DEFAULT_LIVING_DOCS_SUFFIXES = {
    "verification/coverage_plan.md",
    "verification/testcase_list.md",
    "verification/feature_matrix.md",
    "verification/reference_model_spec.md",
}


def load_config():
    if not CONFIG_PATH.is_file():
        sys.exit(f"ERROR: {CONFIG_PATH} not found. Run verif-harness skill first.")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def stage_docs(config: dict) -> list[Path]:
    """Derive required doc paths from harness-config."""
    docs_root = Path(config["verif"]["docs_root"])
    verif_sub = config["verif"].get("verification_subdir", "verification")
    gov_sub = config["verif"].get("governance_subdir", "governance")

    docs = [
        Path("AGENTS.md"),
        docs_root / "roadmap.md",
        docs_root / "harness_style_methodology.md",
        docs_root / gov_sub / "verification_workflow.md",
    ]

    verif_docs = [
        "verification_plan.md",
        "feature_matrix.md",
        "testcase_list.md",
        "tb_architecture.md",
        "assertion_plan.md",
        "coverage_plan.md",
    ]
    if config.get("reference_model", {}).get("enabled", False):
        verif_docs.append("reference_model_spec.md")
    for name in verif_docs:
        docs.append(docs_root / verif_sub / name)

    return docs


def default_living_paths(config: dict) -> set[Path]:
    docs_root = Path(config["verif"]["docs_root"])
    verif_sub = config["verif"].get("verification_subdir", "verification")
    result = set()
    for suffix in DEFAULT_LIVING_DOCS_SUFFIXES:
        # replace "verification/" prefix with actual verif_sub
        rel = suffix.replace("verification/", f"{verif_sub}/", 1)
        result.add(docs_root / rel)
    # Only keep those that exist in required docs
    return result


APPROVED_LIFECYCLE = """## Lifecycle

Status: Approved
Baseline: Stage {stage} approved
Frozen Sections:

- Human Decisions
- Approval Decision

Mutable Sections:

- 暂定决策 (Provisional)
- 开放问题
- Revision Log
- Review Trace
- Human Review Notes"""

LIVING_LIFECYCLE = """## Lifecycle

Status: Living
Baseline: Stage {stage} living
Frozen Sections:

- Human Decisions
- Approval Decision

Mutable Sections:

- Body content (随 Stage 演进增长)
- 暂定决策 (Provisional)
- 开放问题
- Revision Log
- Review Trace
- Human Review Notes"""

NEW_REVIEW_ENTRY_TEMPLATE = """### Approved {date}

Reviewer: Human
Status: Approved

Findings:

- Baseline reviewed via `stage{stage}_review_packet.md`; Human Decisions
  approved; Provisional decisions accepted for Stage gate revisit; open
  questions tracked per external-dependency assignments.

Required Changes:

- None. Provisional revisits scheduled per `roadmap.md § Stage Entry Gate
  Re-review`.

Resolution:

- Baseline approved as part of Stage {stage} doc set on {date}."""

REVLOG_ENTRY_TEMPLATE = (
    "- {date} (Stage {stage} baseline approved{tag}): reviewed by Human "
    "against stage{stage}_review_packet.md; Human Decisions accepted; "
    "Provisional decisions kept for Stage gate revisit; open questions "
    "tracked per external-dependency assignments."
)

OLD_LIFECYCLE = """## Lifecycle

Status: Draft
Baseline: Pre-Stage 0
Frozen Sections:

- None

Mutable Sections:

- All"""

OLD_REVIEW_METADATA = """- Status: Pending
- Reviewer: Human
- Decision Date: TBD"""


def upgrade_doc(path: Path, is_living: bool, stage: int, date: str, dry_run: bool) -> str:
    if not path.is_file():
        return f"SKIP {path}: file missing"

    text = path.read_text(encoding="utf-8")
    original = text
    changes = []

    # 1. Lifecycle block (only if exact "Pre-Stage 0" pattern present)
    old_lifecycle = OLD_LIFECYCLE
    new_lifecycle_tpl = LIVING_LIFECYCLE if is_living else APPROVED_LIFECYCLE
    new_lifecycle = new_lifecycle_tpl.format(stage=stage)
    if old_lifecycle in text:
        text = text.replace(old_lifecycle, new_lifecycle, 1)
        changes.append("Lifecycle")

    # 2. Review Trace: '### Review Pending' block
    pattern = re.compile(
        r"### Review Pending\n\nReviewer: Human\nStatus: Pending\n\n"
        r"Findings:\n\n- .+?\n\n"
        r"Required Changes:\n\n- Pending human review\.\n\n"
        r"Resolution:\n\n- Pending human review\.",
        re.DOTALL,
    )
    new_review_entry = NEW_REVIEW_ENTRY_TEMPLATE.format(stage=stage, date=date)
    if pattern.search(text):
        text = pattern.sub(new_review_entry, text, count=1)
        changes.append("ReviewTrace")

    # 3. Review Metadata
    new_metadata = f"- Status: Approved\n- Reviewer: Human\n- Decision Date: {date}"
    if OLD_REVIEW_METADATA in text:
        text = text.replace(OLD_REVIEW_METADATA, new_metadata, 1)
        changes.append("ReviewMetadata")

    # 4. Approval Decision (only under ### Approval Decision heading)
    tag = " (Living)" if is_living else ""
    new_approval = f"Approved as part of Stage {stage} baseline on {date}{tag}."
    approval_pattern = re.compile(r"(### Approval Decision\n\n)Pending human review\.")
    if approval_pattern.search(text):
        text = approval_pattern.sub(r"\g<1>" + new_approval, text)
        changes.append("ApprovalDecision")

    # 5. Revision Log — append entry
    revlog_pattern = re.compile(
        r"(## Revision Log\n\n(?:- .+?(?:\n {2}.+)*(?:\n\n)?)+)",
        re.DOTALL,
    )
    m = revlog_pattern.search(text)
    if m:
        entry = REVLOG_ENTRY_TEMPLATE.format(date=date, stage=stage, tag=tag)
        block = m.group(0).rstrip() + "\n\n" + entry + "\n\n"
        text = revlog_pattern.sub(block, text, count=1)
        changes.append("RevLog")

    if text == original:
        return f"NOOP {path}: no changes applied (already upgraded or non-standard block)"

    if not dry_run:
        path.write_text(text, encoding="utf-8")

    status = "DRY-RUN" if dry_run else "OK"
    return f"{status:<7} {path}: {', '.join(changes)}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=int, required=True,
                        help="Stage number (0 = initial baseline).")
    parser.add_argument("--date", default=None,
                        help="Approval date (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--living", action="append", default=[],
                        help="Mark this doc as Living lifecycle (repeatable).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing.")
    parser.add_argument("--use-defaults", action="store_true",
                        help="Auto-mark default growth docs (coverage_plan / "
                             "testcase_list / feature_matrix / reference_model_spec) "
                             "as Living.")
    args = parser.parse_args()

    date = args.date or "1970-01-01"  # placeholder; validated below
    if args.date is None:
        sys.stderr.write("ERROR: --date is required (date generation avoided intentionally)\n")
        sys.exit(1)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        sys.exit(f"ERROR: --date must be YYYY-MM-DD, got: {date}")

    config = load_config()
    docs = stage_docs(config)

    living_paths = set(Path(p) for p in args.living)
    if args.use_defaults:
        living_paths |= default_living_paths(config)

    print(f"Batch upgrade Stage {args.stage} on {date} "
          f"({'DRY-RUN' if args.dry_run else 'writing changes'}):")
    print(f"  Docs to process: {len(docs)}")
    print(f"  Marked Living  : {sorted(str(p) for p in living_paths)}")
    print("")

    for path in docs:
        is_living = path in living_paths
        print(upgrade_doc(path, is_living, args.stage, date, args.dry_run))

    print("")
    if not args.dry_run:
        print("Run: python3 .harness/check_ai_workflow.py --skip-markdownlint")
        print("     to verify consistency.")


if __name__ == "__main__":
    main()
