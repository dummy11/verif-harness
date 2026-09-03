# v1 control-plane architecture

verif-harness v1 stores typed project facts in one Verification Knowledge Model and runs
a continuous global loop:

```text
change/evidence -> Verification Knowledge Model
  -> Verification Consistency Engine -> Verification Closure Engine
  -> tool/Verification Reasoning Engine/Human -> Verification Knowledge Model
```

Verification Planner combines a detailed template, current model, project context, and Human
dialogue to create revisioned desired state. `VDOC`, `VSTIM`, `VCHK`, `VCOV`,
`VCASE`, and `VREG` are parallel, re-entrant Workstreams. Each has its own
`desired -> plan -> act -> observe -> evaluate -> replan` loop. They are not a
fixed lifecycle or prerequisite chain.

`.verif-harness/model.sqlite3` is authority. JSON and Markdown are review
projections. Verification Knowledge Model is read-only to Human-facing callers;
structured `record` ingress supplies mutations and triggers the consistency and closure engines.

- Verification Consistency Engine judges validity and propagates causal invalidation; it does not act.
- Verification Closure Engine selects/routes actions; it does not write code.
- Verification Reasoning Engine handles semantic uncertainty through independent Role × Backend.
- Tools produce deterministic artifacts/evidence with provenance.
- Human reviewers own approval, waiver, Workstream baseline, and final freeze.

Workstream and final baselines are immutable snapshots. The workspace can keep
evolving; new facts create revalidation/replanning rather than rewriting old
snapshots. DUT RTL remains external and read-only.
