#!/usr/bin/env python3
"""Build a conservative Draft Stage N gate packet from project Markdown."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def section(text: str, heading_pattern: str) -> str:
    lines = text.splitlines()
    start = None
    level = 0
    matcher = re.compile(heading_pattern)
    for index, line in enumerate(lines):
        if matcher.fullmatch(line.strip()):
            start = index + 1
            level = len(line) - len(line.lstrip("#"))
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start, len(lines)):
        line = lines[index]
        if not line.startswith("#"):
            continue
        current = len(line) - len(line.lstrip("#"))
        if current <= level:
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def stage_block(roadmap: str, stage: int) -> str:
    pattern = rf"## Stage {stage}\b.*"
    lines = roadmap.splitlines()
    start = next((i for i, line in enumerate(lines) if re.fullmatch(pattern, line.strip())), None)
    if start is None:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## Stage ")), len(lines))
    return "\n".join(lines[start:end])


def bullet_items(body: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and re.match(r"^-\s+", line):
            if current:
                items.append("\n".join(current).strip())
            current = [line]
        elif current:
            current.append(line)
    if current:
        items.append("\n".join(current).strip())
    return items


def due_provisionals(
    path: Path, completed_stage: int, source: str | None = None
) -> list[tuple[str, str]]:
    body = section(read(path), r"## 暂定决策 \(Provisional\)|## Provisional Decisions")
    result: list[tuple[str, str]] = []
    for item in bullet_items(body):
        if re.search(r"\b(?:Resolved|Upgraded)\b|已于.*?升为 Human Decision", item,
                     re.IGNORECASE | re.DOTALL):
            continue
        if re.search(rf"Stage\s*{completed_stage}\s+re-review", item, re.IGNORECASE):
            continue
        stages = [int(value) for value in re.findall(r"(?:Stage|stage)\s*(\d+)", item)]
        if stages and min(stages) <= completed_stage:
            result.append((source or path.name, item))
    return result


def open_questions(path: Path, source: str | None = None) -> list[tuple[str, str]]:
    body = section(read(path), r"## 开放问题|## Open Questions")
    if not body or re.fullmatch(r"-\s*(None|无)[.]?", body.strip(), re.IGNORECASE):
        return []
    result: list[tuple[str, str]] = []
    for item in bullet_items(body):
        first_line = item.splitlines()[0]
        if re.match(r"^-\s*(?:None|无)(?:\b|（|。|$)", first_line, re.IGNORECASE):
            continue
        if re.search(r"\bClosed\b|已关闭", item, re.IGNORECASE):
            continue
        result.append((source or path.name, item))
    return result


def authoritative_stage_plan(root: Path, docs_root: Path, stage: int) -> Path:
    """Resolve the reviewed Spec Kit plan, with legacy-only fallback."""
    specify = root / ".specify"
    if not specify.exists():
        legacy = docs_root / "plan.md"
        if legacy.is_file():
            return legacy
        raise ValueError(
            "no Spec Kit project or legacy docs_root/plan.md was found for the gate"
        )

    feature_state = specify / "feature.json"
    try:
        payload = json.loads(read(feature_state))
    except json.JSONDecodeError as exc:
        raise ValueError(f"cannot parse {feature_state.relative_to(root)}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(
        payload.get("feature_directory"), str
    ):
        raise ValueError(
            ".specify/feature.json must identify the current feature_directory"
        )

    feature = Path(payload["feature_directory"])
    candidate = feature if feature.is_absolute() else root / feature
    candidate = candidate.resolve()
    specs_root = (root / "specs").resolve()
    try:
        candidate.relative_to(specs_root)
    except ValueError as exc:
        raise ValueError("current Spec Kit feature must remain below project specs/") from exc

    plan = candidate / "plan.md"
    spec = candidate / "spec.md"
    if not plan.is_file() or not spec.is_file():
        raise ValueError(
            f"current Spec Kit feature lacks spec.md or plan.md: {candidate.relative_to(root)}"
        )
    if not (
        re.search(rf"\bStage\s*{stage}\b", read(spec), re.IGNORECASE)
        or re.search(rf"(?:^|[-_])stage[-_]?{stage}(?:[-_]|$)", candidate.name, re.IGNORECASE)
    ):
        raise ValueError(
            f"current Spec Kit feature does not identify completed Stage {stage}: "
            f"{candidate.relative_to(root)}"
        )
    return plan


def markdown(root: Path, config: dict, stage: int, final_gate: bool) -> str:
    verif = config["verif"]
    docs_root = root / verif["docs_root"]
    vsub = verif.get("verification_subdir", "verification")
    gsub = verif.get("governance_subdir", "governance")
    stage_plan = authoritative_stage_plan(root, docs_root, stage)
    sources = [
        stage_plan,
        docs_root / "roadmap.md",
        docs_root / "harness_style_methodology.md",
        docs_root / gsub / "verification_workflow.md",
        docs_root / vsub / "verification_plan.md",
        docs_root / vsub / "tb_architecture.md",
        docs_root / vsub / "coverage_plan.md",
        docs_root / vsub / "assertion_plan.md",
        docs_root / vsub / "testcase_list.md",
        docs_root / vsub / "feature_matrix.md",
    ]
    refspec = docs_root / vsub / "reference_model_spec.md"
    if refspec.is_file():
        sources.append(refspec)

    provisionals: list[tuple[str, str]] = []
    questions: list[tuple[str, str]] = []
    for path in sources:
        source = str(path.relative_to(root))
        provisionals.extend(due_provisionals(path, stage, source))
        questions.extend(open_questions(path, source))

    roadmap = read(docs_root / "roadmap.md")
    completed = stage_block(roadmap, stage)
    exit_criteria = section(completed, r"### Exit Criteria")
    cr_path = docs_root / "change_requests.md"
    cr_headings = re.findall(r"^##\s+(CR-[^\n]+)$", read(cr_path), re.MULTILINE)

    transition = f"Stage {stage} final sign-off" if final_gate else f"Stage {stage} exit / Stage {stage + 1} entry"
    lines = [
        f"# Stage {stage} Gate Re-review Report",
        "",
        f"Draft for {transition} review.",
        "",
        "## Metadata",
        "",
        "- **Status**: Draft",
        "- **Reviewer**: TBD",
        "- **Review date**: TBD",
        f"- **Stage gate**: {transition}",
        f"- **Authoritative Stage plan**: `{stage_plan.relative_to(root)}`",
        "- **Evidence boundary**: repository evidence only; add Human-confirmed",
        "  evidence explicitly when raw artifacts are unavailable.",
        "",
        "## Stage Exit Audit",
        "",
    ]
    if exit_criteria:
        for item in bullet_items(exit_criteria):
            lines.extend([f"- [ ] {item[2:] if item.startswith('- ') else item}", "  Evidence: TBD"])
    else:
        lines.append("- [ ] Roadmap exit criteria were not found; resolve before review.")

    lines.extend(["", "## Provisional Decisions Due", ""])
    if provisionals:
        for index, (source, item) in enumerate(provisionals, 1):
            lines.extend([
                f"### PROV-{index:02d} · source `{source}`",
                "",
                item,
                "",
                "- **Evidence**: TBD",
                "- **Verdict**:",
                "  - [ ] Keep provisional; set a new target gate.",
                "  - [ ] Upgrade through Human Decision/change-request workflow.",
                "  - [ ] Downgrade to an open question.",
                "",
            ])
    else:
        lines.append("- None detected by the structural scan.")

    lines.extend(["", "## Open Questions", ""])
    if questions:
        for source, item in questions:
            lines.append(f"- Source `{source}`: {item[2:] if item.startswith('- ') else item}")
    else:
        lines.append("- None detected by the structural scan.")

    lines.extend(["", "## Change Requests", ""])
    if cr_headings:
        lines.extend(f"- [ ] `{heading}` disposition and evidence reviewed." for heading in cr_headings)
    else:
        lines.append("- No change-request headings detected.")

    lines.extend([
        "",
        "## Required Evidence",
        "",
        "- [ ] Compile/elaboration evidence recorded where required.",
        "- [ ] Regression manifest, case count, seed, and verdict recorded.",
        "- [ ] Golden/reference-model engagement and mismatch status recorded.",
        "- [ ] Functional, code, and assertion coverage evidence recorded as applicable.",
        "- [ ] CI result recorded as applicable.",
        "- [ ] Missing artifacts and evidence limitations stated explicitly.",
        "- [ ] Traceability audit reviewed.",
        "- [ ] RTL root confirmed unchanged by verification work.",
        "",
        "## Human Decisions Modified",
        "",
        "- None in this Draft. Record approved changes through the project workflow.",
        "",
        "## Approval",
        "",
        "- [ ] Approved",
        "- [ ] Approved with conditions",
        "- [ ] Changes requested",
        "",
        "Reviewer: TBD",
        "Decision date: TBD",
        "Decision rationale: TBD",
        "",
        "> Generated conservatively. Unchecked boxes and TBD fields must not be interpreted as PASS.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--completed-stage", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--final", action="store_true",
                        help="label this as terminal project sign-off, not Stage N+1 entry")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = args.project_root.resolve()
    config_path = root / ".harness-config.json"
    if not config_path.is_file():
        raise SystemExit("ERROR: .harness-config.json is missing")
    config = json.loads(read(config_path))
    out = args.out if args.out.is_absolute() else root / args.out
    if out.exists() and not args.force:
        raise SystemExit(f"ERROR: refusing to overwrite existing packet: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        content = markdown(root, config, args.completed_stage, args.final)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    out.write_text(content, encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
