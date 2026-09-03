---
name: verif-harness
description: Govern continuous RTL verification engineering with the Verification Planner, Verification Knowledge Model, Verification Consistency Engine, Verification Closure Engine, and Verification Reasoning Engine. Use for project bootstrap, interactive Workstream desired-state design, traceability, change invalidation, closure actions, UVM/harness generation, deterministic evidence, and Human review/freeze. Never modify DUT RTL or approve Human Decisions.
---

# verif-harness v1

Use `.verif-harness/model.sqlite3` as the machine fact source. Markdown and JSON
under `.verif-harness/` are review projections. Never manufacture facts by
editing projections or by claiming that an Agent/tool command is evidence.

The control loop is continuous:

```text
Verification Planner -> Verification Knowledge Model
  -> Verification Consistency Engine -> Verification Closure Engine
  -> act/verify/review -> Verification Knowledge Model
  \-> Verification Reasoning Engine only for ambiguity
```

`VDOC`, `VSTIM`, `VCHK`, `VCOV`, `VCASE`, and `VREG` are parallel, re-entrant
Workstreams, not lifecycle steps. Each has a local `desired -> plan -> act ->
observe -> evaluate -> replan` loop. Evidence or findings may reopen any
Workstream. Project lifecycle is separate.

## Core dispatch

- `bootstrap`: inventory a project and create the minimal model shell. It does
  not make verification decisions or generate a monolithic plan.
- Verification Planner (`plan`): combine a detailed Workstream template, current
  Verification Knowledge Model, project
  context, and Human dialogue into revisioned desired state. Read
  `vplan/INSTRUCTIONS.md`.
- Verification Knowledge Model: read-only `inspect/trace/impact` access to typed facts.
  Read `vmodel/INSTRUCTIONS.md`.
- `record`: structured ingress for facts, relations, evidence, changes, and
  Human waivers. It automatically reconciles the consistency and closure engines.
- Verification Consistency Engine (`check`): scan model facts and propagate change invalidation. Read
  `vcheck/INSTRUCTIONS.md`.
- Verification Closure Engine (`closure`): compute the smallest next actions across Workstreams. Read
  `vclosure/INSTRUCTIONS.md`.
- Verification Reasoning Engine (`reason`): prepare backend-neutral reasoning requests only when deterministic
  rules cannot decide. Read `vreason/INSTRUCTIONS.md`.

Prefer the human-facing spellings in interactive work: `plan VDOC`, `review
[VDOC]`, `status [VDOC]`, `prove NODE FILE`, `changed PATH`, `waive NODE
--reason ...`, and `freeze VDOC|final`. Use the expanded `plan
design|review|freeze` and `record ...` forms only when automation needs explicit
fields. The older `model` and `v*` spellings are compatibility-only and must not
be presented as the interactive interface. There is no detached worker,
task-resume protocol, linear Stage 0–5 state machine, or legacy project initialization command.

## Capability dispatch

These lower-level modes remain available to implement a closure action:

- `doctor`
- `add-interface`
- `add-shared-pkg`
- `add-uvc-skeleton [name]`
- `add-harness-layer`
- `add-env-layer`
- `finalize-filelist-and-make`
- `xverif`
- `wavepeek`
- `add-regression-runner`
- `add-simulator-profile`
- `add-testcase`
- `add-coverage-skeleton`
- `add-assertion-skeleton`
- `add-refmodel-bridge`
- `complete-uvc`
- `complete-scoreboard`
- `add-ci-hook`
- `add-performance-gate`
- `regression-triage`
- `coverage-closure`
- `assertion-closure`
- `audit-traceability`
- `change-control`
- `signoff-audit`
- `freeze-baseline`
- `oss-readiness`

Read the selected mode's `INSTRUCTIONS.md` completely before acting. Generated
files are review candidates. DUT RTL and Human approval remain out of bounds.

## Authority boundaries

- Bootstrap may inventory paths, tools, revisions, and file metadata only.
- The Verification Planner may propose; only a named Human review changes a Workstream to `ACTIVE` or
  `BASELINED`.
- The Verification Consistency Engine may mark facts stale/invalid but may not waive them.
- The Verification Closure Engine recommends actions; it does not silently execute write modes.
- The Verification Reasoning Engine returns structured diagnosis/proposals and never grants approval.
- xverif, WavePeek, simulation, regression, and coverage outputs become
  evidence only when recorded with provenance and verdict.
