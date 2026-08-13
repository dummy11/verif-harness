# Stage <N> Gate Re-review Report Template

Skill asset. Copied to project as `.harness/stage_gate_re_review_template.md`
during bootstrap (Step 4). Used at every Stage entry gate to systematically
revisit Provisional decisions.

Filename in project when instantiated: `<docs_root>/stage<N>_gate_re_review.md`
(one file per Stage entry gate, e.g., `stage1_gate_re_review.md` before
starting Stage 2).

## When to Use

Before entering Stage N (i.e., at the transition Stage N-1 exit → Stage N
entry), copy this template to `<docs_root>/stage<N-1>_gate_re_review.md`
and fill in for every Provisional decision with `目标复审: Stage N-1 gate`
(or earlier) across all Stage docs.

## Purpose

Systematic re-review of Provisional decisions to prevent them from
lingering forever. Each Provisional gets one of three verdicts at the
appropriate Stage gate:

- **Keep provisional** (evidence still insufficient, update target)
- **Upgrade to Human Decision** (evidence collected, decide firm)
- **Downgrade to open question** (direction wrong, restart deliberation)

## Template

```markdown
# Stage <N-1> Gate Re-review Report

Report of Provisional decision reviews at the Stage <N-1> exit → Stage <N>
entry gate.

## Metadata

- **Reviewer**: <name>
- **Review date**: <YYYY-MM-DD>
- **Stage gate**: Stage <N-1> exit / Stage <N> entry
- **Scope**: all Provisional decisions with `目标复审: Stage <N-1> gate`
  or earlier across Stage 0 baseline docs

## Provisional Decisions Reviewed

For each entry, transcribe from source doc + fill Verdict.

### PROV-<packet id> (source: <doc>.<P-id>) · <short title>

- **Original Provisional** (from prior baseline / re-review):

  > <copy the decision, 依据, 目标复审, 影响, Provisional since verbatim
  > from the source doc>

- **Evidence collected during Stage <N-1>**:

  <regression data / test results / rtl-spec-diff report / upstream sync
  status / etc.>

- **Verdict**:

  - [ ] **Keep provisional** — update target to Stage <M>. Reason:
        _______________________________________________
  - [ ] **Upgrade to Human Decision** — new HD-<n> in `<doc path>`.
        Reason: _______________________________________
  - [ ] **Downgrade to open question** — new OQ<n> in `<doc path>`.
        Reason: _______________________________________

- **Follow-up action**: _______________________________________

## Open Questions Reviewed

External-dependency OQs. Update Owner / Target date / Status.

### OQ-<n> · <short title>

- **Doc**: `<doc path>`
- **Previous status**: <copy from source doc>
- **Update from external source**: <what has changed since last review>
- **New status**:
  - [ ] **Still open** (update Target update date to: __________)
  - [ ] **Answered by external** — action: close OQ and transfer to
        Human Decision as HD-<n> in `<doc path>`; content: __________
  - [ ] **Superseded by project decision** — close OQ, note reason:
        __________
- **Follow-up action**: _______________________________________

## Human Decisions Modified

If any Provisional was upgraded to HD, or existing HD was modified via
change request, list here.

- **HD-<n>**: <short title>
  - **Source**: PROV-<id> upgraded (or CR-<id> filed)
  - **Effective date**: <YYYY-MM-DD>
  - **Doc updated**: `<doc path>`

## Change Requests Filed

If any modification touched a Frozen Section (typically `Human Decisions`
or `Approval Decision` in Frozen / Approved docs), list here.

- **CR-<n>**: <title>
  - **Motivation**: <why needed>
  - **Impact scope**: <which docs / sections affected>
  - **Approval**: <who approved / when>
  - **Doc(s) updated**: `<doc path>`

## Summary Statistics

- Provisionals kept: <count>
- Provisionals upgraded to HD: <count>
- Provisionals downgraded to open: <count>
- OQs closed / transferred to HD: <count>
- OQs still open (with updated target): <count>
- CRs filed against Frozen Sections: <count>

## Approval

- **Reviewer signature**: __________ (<name>)
- **Signature date**: <YYYY-MM-DD>
- **Stage <N> entry cleared**: [ ] Yes / [ ] No (blocking issues:
  __________)

## Downstream Action

After re-review approval:

1. Update source docs:
   - Kept provisionals: update `目标复审` field to new Stage
   - Upgraded: move to source doc's `### Human Decisions` section,
     renumber HD IDs, remove from `## 暂定决策 (Provisional)`
   - Downgraded: move to source doc's `## 开放问题` with reason
2. Update source docs' Revision Log with a re-review entry.
3. Run `python3 .harness/check_ai_workflow.py --skip-markdownlint`.
4. Git commit: `stage <N-1> gate re-review completed`.
```

## Notes for Reviewers

- **Batch is better**: process all Provisionals for a Stage gate in one
  session; avoid piecemeal upgrades that scatter across days.
- **Cite evidence**: every Verdict needs concrete evidence (regression
  data / spec update / bug fix / etc.). Avoid "gut feel" upgrades.
- **Downgrade is normal**: not every direction survives contact with
  reality. Downgrading isn't failure — it's honest feedback.
- **HD numbering**: when upgrading, use next available HD-<n> in the
  source doc. Keep numbering monotonic; never reuse retired numbers.
