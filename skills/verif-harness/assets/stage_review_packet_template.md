# Stage <N> Review Packet Template

Skill asset. **Not copied to project** —— the SKILL orchestration reads
this to generate a Stage-specific `stage<N>_review_packet.md` per project
per Stage.

Filename in project: `<docs_root>/stage<N>_review_packet.md`
(where `<docs_root>` = `sim/docs/` by default).

## Purpose

Aggregate all Human Decisions + Provisional decisions + open questions
across the Stage <N> doc set into a single reviewer-friendly checklist.
Enables a **one-shot review meeting** (typically 2-3 hours) to sign off
the entire Stage baseline, then batch-upgrade docs from Draft/Pending to
Approved / Living.

## Template Structure

The generated packet has 5 parts. Below is the structure with example
entries per part (copy structure, fill from actual project docs).

---

## Part 1: Human Decisions Checklist

Enumerate every `- **HD-<n>**` / `- **LD-<n>**` / `- **H-<n>**` entry from
each doc's `### Human Decisions` section. Classify by priority.

**Priority classification**:

| Priority | 语义 | 处理策略 |
|---------|-----|--------|
| **P0** | 影响架构核心 / sign-off 阈值 / 无法回滚 | 必审必答 |
| **P1** | 影响 verification strategy / scope 边界 | 应审 |
| **P2** | 细节决策 / 支持性 | 可默认信任 |

Each HD entry format:

```markdown
### HD-<n> · <short title> [<source doc>.<original ID>]

- **Decision**: <decision text>
- **Doc**: `<doc path>` L<line> (<original section>)
- **依据**: <rationale>
- **影响**: <impact scope>
- **Review**: `[ ] Approve`  `[ ] Changes`  `[ ] Reject`
- **Note**: ____________________________________________
```

---

## Part 2: Provisional Decisions Checklist

Enumerate every `- **P<n>**` entry from each doc's
`## 暂定决策 (Provisional)` section. Group by target revisit Stage.

Section structure:

```markdown
### Stage <M> gate revisit (<count> 条)

#### PROV-<n> · <short title>

- **Doc**: `<doc path> P<original id>`
- **Decision**: <decision content>
- **依据**: <rationale>
- **目标复审**: Stage <M> gate
- **Review**: `[ ] Accept as provisional`  `[ ] Escalate to HD`  `[ ] Reject direction`
```

**Review options meaning**:

- **Accept**: 方向合理，保持 Provisional 状态，Stage gate 时复审
- **Escalate to HD**: 证据充分，直接升级为 Human Decision（转到对应 doc
  的 `### Human Decisions` section，编号 HD-<N+1>）
- **Reject direction**: 方向错误，退回开放问题（转到 `## 开放问题` 并说明
  原因）

---

## Part 3: Open Questions Checklist

Enumerate every `- **OQ<n>**` entry from `## 开放问题` sections. These are
**external dependencies** — cannot be answered within the project.

Each OQ entry format:

```markdown
### OQ-<n> · <short title>

- **Doc**: `<doc path>`
- **Depends on**: <external dependency>
- **Blocks**: <what this blocks>
- **Action needed**: <what needs to happen to close>
- **Owner assignment**: ____________________
- **Target update date**: ____________________
```

---

## Part 4: Batch Upgrade Template

Instructions for using `batch_upgrade_stage.py`:

```bash
# After review meeting sign-off is complete:
python3 .harness/batch_upgrade_stage.py \
  --stage <N> \
  --date <YYYY-MM-DD> \
  [--living <doc-path> [--living <doc-path> ...]] \
  [--dry-run]
```

Options:

- `--stage <N>`: Stage number (0 = initial baseline)
- `--date <YYYY-MM-DD>`: approval date (goes into Decision Date + Revision
  Log)
- `--living <path>`: mark this doc as Living lifecycle (repeat for each).
  Default candidates:
  - `<docs_root>/verification/coverage_plan.md`
  - `<docs_root>/verification/testcase_list.md`
  - `<docs_root>/verification/feature_matrix.md`
  - `<docs_root>/verification/reference_model_spec.md`
- `--dry-run`: preview without writing

Docs not marked Living become Approved.

After batch upgrade, run:

```bash
python3 .harness/check_ai_workflow.py --skip-markdownlint
# Must exit 0
```

If any doc's Review Pending block has non-standard content
(e.g., `reference_model_spec.md` had custom Required Changes with actual
items), the script may skip that doc and print `SKIP <path>: ...`. Handle
those docs manually via Edit.

---

## Part 5: Post-Review Checklist

After batch upgrade + workflow check:

- [ ] All docs' Lifecycle Status = Approved or Living
- [ ] All Review Metadata Status = Approved
- [ ] All Approval Decision text contains "Approved"
- [ ] All Decision Date = <approval date>
- [ ] All Frozen Sections at least include `Human Decisions` +
      `Approval Decision`
- [ ] Revision Log each has a `<date> (Stage <N> baseline approved)` entry
- [ ] `python3 .harness/check_ai_workflow.py --skip-markdownlint` exit 0
- [ ] Git commit: `freeze Stage <N> baseline: all <count> docs approved`
- [ ] (Optional) Push to remote
- [ ] (Optional) markdownlint full pass

## Post-Review Deliverable

- Provisional decisions accepted → monitored per `roadmap.md § Stage
  Entry Gate Re-review` (revisit at target Stage)
- Open questions → tracked with Owner + Target date
- Stage <N+1> can be launched — target: <depends on stage>

---

## Generation Instructions (for SKILL orchestrator)

When generating the actual `stage<N>_review_packet.md` for a project:

1. **Scan all Stage <N> docs** for HD / Provisional / OQ entries. Read
   each doc's `### Human Decisions`, `## 暂定决策 (Provisional)`, and
   `## 开放问题` sections.
2. **Classify HDs by priority** (P0/P1/P2). Default heuristic:
   - **P0**: covers sign-off criteria, architecture-defining decisions
     (interface layout, DUT variant, package structure), assertion
     severity, coverage targets
   - **P1**: verification strategy scope, DUT variant policies, testcase
     scope decisions, protocol layer choices
   - **P2**: incidental / supporting decisions (naming conventions, minor
     bind targets, delegation patterns)
3. **Group Provisionals** by their `目标复审` stage. Preserve original
   `P<n>` numbering per source doc, add packet-global `PROV-<n>` prefix.
4. **Aggregate OQs** by external dependency.
5. **Fill in real counts** in the packet's Overview 统计 section.
6. **Include TODO / customization notes** where the template has generic
   placeholders like `<count>` or `<stage entry criteria>`.

Do NOT invent decisions. If a doc has zero HDs, Provisionals, or OQs, note
"None." Do not fabricate to fill space.

## Example expectations

Use the target project's approved Stage 0 packet as the only source for Human
Decision, Provisional, and Open Question counts. Preserve source identifiers
and generate fresh content; never copy counts or decisions from another
project.
