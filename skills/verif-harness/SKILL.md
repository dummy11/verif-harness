---
name: verif-harness
description: Govern continuous RTL verification engineering with the Verification Planner, Verification Knowledge Model, Verification Consistency Engine, Verification Closure Engine, and Verification Reasoning Engine. Use for project bootstrap, interactive Workstream desired-state design, traceability, change invalidation, closure actions, UVM/harness generation, deterministic evidence, and Human review/freeze. Never modify DUT RTL or approve Human Decisions.
---

# verif-harness v1

Use project VDOC Markdown as the source for verification engineering semantics,
and `.verif-harness/model.sqlite3` as the source for governance state, relations,
reviews and evidence. Markdown and JSON under `.verif-harness/` are reading
projections. Never manufacture facts by editing projections or by claiming that
an Agent/tool command is evidence.

The control loop is continuous:

```text
Verification Planner -> Verification Knowledge Model
  -> Verification Consistency Engine -> Verification Closure Engine
  -> act/verify/review -> Verification Knowledge Model
  \-> Verification Reasoning Engine only for ambiguity
```

`VDOC`, `VENV`, `VSTIM`, `VCHK`, `VCOV`, `VCASE`, and `VREG` are parallel, re-entrant
Workstreams, not lifecycle steps. Each has a local `desired -> plan -> act ->
observe -> evaluate -> replan` loop. Evidence or findings may reopen any
Workstream. Project lifecycle is separate.

## Core dispatch

- `bootstrap`: inventory a project and create the minimal model shell. It does
  not make verification decisions or generate a monolithic plan. Read
  `bootstrap/INSTRUCTIONS.md`; require conversational user input for `rtl root`,
  `dut top`, and `dut top file`, with optional `spec`, `testbench` directory,
  reference/golden model, and verification scripts. The three verification inputs
  are independent and may all be omitted. Ask exactly one unanswered bootstrap
  field at a time in the documented order, wait for and validate that answer,
  then ask the next field. Never combine multiple unanswered fields into one
  prompt. Every optional field requires an explicit path or `skip`; silence is
  not an answer. After all fields, show one consolidated summary and obtain final
  Human confirmation before invoking the non-interactive CLI. Values already
  explicitly supplied in the current conversation count as answered and are not
  asked twice. Never discover candidates or run initialization while mandatory
  inputs are missing. After validation,
  create or refresh only the marked verif-harness block in the project-root
  `AGENTS.md`; preserve all project-owned instructions outside it. When the Human
  requests only `bootstrap --refresh`, treat that as a request to reopen the
  bootstrap dialogue: show the current values, reconfirm every path and DUT field,
  then call the low-level CLI with the complete confirmed parameter set. Refresh
  must synchronize bootstrap-managed `.harness-config.json` fields while preserving
  optional project-owned fields. For a live Human/Agent bootstrap, pass
  `--dashboard` so the background Dashboard is started or reused after bootstrap.
  Never add `--no-dashboard` unless the Human explicitly asks to disable the
  Dashboard; SSH, a headless server, or a non-interactive Agent invocation is not
  permission to disable it. CI may use the CLI's normal skip policy.
- Verification Planner (`plan`): combine a detailed Workstream template, current
  Verification Knowledge Model, project
  context, and Human dialogue into revisioned desired state. Read
  `vplan/INSTRUCTIONS.md`.
  For VDOC document drafting and cross-Workstream document revisions, read
  `vplan/vdoc.md` and the selected templates under `assets/vdoc/`.
- Document governance (`docs`): create missing semantic templates during VDOC
  planning, synchronize content digests, track decision/open-question state,
  record Human content reviews, and render status on demand. Never overwrite an
  existing semantic document or write generated state back into its body.
- Verification Knowledge Model: read-only `inspect/trace/impact` access to typed facts.
  Read `vmodel/INSTRUCTIONS.md`.
- `record`: structured ingress for facts, relations, evidence, changes, and
  Human waivers. It automatically reconciles the consistency and closure engines.
- `evidence`: validate VENV, VSTIM capability, VCHK, VCOV, VCASE, and VREG typed
  evidence and derive the verdict from content. Read `evidence/INSTRUCTIONS.md`;
  do not use generic `prove` to bypass a standard Workstream contract. Enforce
  cross-evidence exit predicates and derive VREG fresh-evidence membership from
  the current Planner graph rather than a producer-supplied node list. Enforce
  each desired node's stored artifact/analyzer admission policy. Runtime claims
  require simulation or coverage data plus a stored xverif or WavePeek analysis
  report; an arbitrary PASS file or analyzer label is not sufficient evidence.
- `reachability`: validate and record VSTIM-owned scenario reachability or
  deterministic-replay evidence. Read `reachability/INSTRUCTIONS.md`. Coverage,
  cover properties, and waveforms are corroboration rather than the sole VSTIM
  closure authority.
- Verification Consistency Engine (`check`): scan model facts and propagate change invalidation. Read
  `vcheck/INSTRUCTIONS.md`.
- Verification Closure Engine (`closure`): compute the smallest next actions across Workstreams. Read
  `vclosure/INSTRUCTIONS.md`.
- Human dashboard (`dashboard`): start the loopback-only live view when the Human
  asks to monitor Workstreams, nodes, evidence, progress, or intervene before
  closure. The plain `dashboard` command and bootstrap both use the same detached
  start-or-reuse action; never keep it alive with a foreground shell, pipe it to
  `head`, or assume that a printed URL proves the service is still running. Use
  `dashboard --status` to verify it. `dashboard --stop` unregisters only the
  current project; the shared service stops only after the last registered
  project is removed. Projects share the loopback UI process and nothing else:
  route every read, event stream, and write to the explicitly selected project's
  own SQLite store. Register every non-trivial bounded Agent/tool operation with `activity
  start` before doing the work; for a native subagent use `agent-work claim`, which
  creates the Activity atomically. Update it when progress changes or Human input is
  required, and close it with the real terminal result. Before a desired-state
  node exists, use `activity start project`; afterwards bind the Activity to the
  most specific current node. Before starting, resuming, or completing an Activity, read
  open `human-action` records and apply relevant Human input. Dashboard writes
  are persistent control-plane input, not arbitrary chat-message injection into
  a running Agent. Dashboard and `verif-harness agent-question answer` are two
  interaction entries backed by the same persisted question state; an answer from
  either entry must be visible from the other. The Agent may mirror the registered
  question in its current CLI conversation; if the Human answers there, persist
  that answer immediately with `agent-question answer` using the same question ID.
  If the Main Agent must stop for Human
  input, it must register the
  question with `agent-question ask` before waiting. Use target `project` before
  a Workstream or node exists; otherwise use the most specific current Workstream
  or node. Include the choices, recommendation, context, and engineering impact.
  Native Codex/Kimi terminal selectors are not a substitute and must not be the
  only place where a blocking question appears. When Closure contains `HUMAN_REVIEW`, bind the current
  Workstream revision and current Activity with `await-human`; retry bounded
  TIMEOUT results while the Human is still expected to decide. Continue normal
  work only for `APPROVE`; handle `MODIFY`, `CLARIFY`, and `REJECT` according to
  the returned `next` action. A comment or Human action never satisfies this
  checkpoint. Use
  `human-action` to preserve comments or requested changes. Dashboard state is
  an audited view of the same model; never manufacture progress or validity.
  In each desired-state node, show the current `NodeClosureAssessment/1` before
  describing the node as closed: current revision, rule, evidence, prerequisite
  state, findings, criterion checks, reasons, and digest. Human approval of this
  assessment confirms the explanation only and never creates PASS evidence.
  Treat modify/clarify/reject as a reopened node and finding; never reuse an old
  assessment digest after facts change.
  For VDOC, show each governed document as a parent node and its tracked Human
  decisions/open questions inside that node. Count pending document items as
  Human attention. Allow the Human to preview and review the registered current
  document through the node, but keep Markdown as the semantic authority and do
  not claim that a document node represents all engineering work inside it.
- Multi-agent execution (`agent-work`): use only the native subagent capability of
  the single runtime selected for the project, Codex or Kimi. Do not launch the
  other runtime and do not build a hidden process scheduler. The Project Main
  Agent is the sole Human-facing coordinator and the sole writer of verif-harness
  control state. Subagents only execute bounded work and return results to Main;
  they must not call `agent-question`, `review`, `waive`, `freeze`, `record`, or
  `evidence`, and must not contact the Human or delegate recursively.
  Before dispatch, Main must read `agent-work candidates`, atomically claim the
  selected current action, and include the returned assignment ID, node revision,
  definition digest, and allowed write scope in the child task. Parallelize only
  independent nodes. Multiple read-only explorers/reviewers may run concurrently;
  write scopes must be explicit and non-overlapping, and may not include DUT/spec,
  `.verif-harness`, `.harness-config.json`, `.deps`, VCS metadata, runtime
  configuration, or `AGENTS.md`. Reserved names are matched case-insensitively.
  A declared scope is a cooperative scheduling contract, not an OS-level sandbox. Main must
  inspect the actual diff; put untrusted children in an isolated worktree or a
  stricter runtime sandbox. Keep the fan-out small and justified by independent
  work rather than using subagents for simple tasks.
  Main owns heartbeats. When a child reports missing engineering input, record
  `WAITING_FOR_PARENT`; Main first attempts internal coordination. Only Main may
  convert a structured `NEEDS_HUMAN` report into an `agent-question`. After the
  Human answer, Main decides whether to resume or replace the child.
  Wait for all requested child results, inspect the actual files and check output,
  then call `agent-work finish` and recompute closure. A completed assignment,
  Agent consensus, or successful child command is never evidence or `VALID`.
- Verification Reasoning Engine (`reason`): prepare backend-neutral reasoning requests only when deterministic
  rules cannot decide. Read `vreason/INSTRUCTIONS.md`.

Prefer the human-facing spellings in interactive work: `plan VDOC`, `review
[VDOC]`, `status [VDOC]`, `evidence NODE FILE`, `changed PATH`, `waive NODE
--reason ...`, `dashboard --open-browser`, and `freeze VDOC|final`. Use the expanded `plan
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

- All RTL and RTL specifications are read-only for the current Agent in every
  mode. Never edit, create, overwrite, delete, rename, format, or generate into
  those inputs, including through adapters or subprocesses. Report defects for
  the user to resolve; keep verification outputs in separate paths. Explicit
  RTL/spec inputs may be outside the project root, but control state and every
  generated verification output must remain inside it.
- Bootstrap may inventory paths, tools, revisions, and file metadata only.
- The Verification Planner may propose; only a named Human review changes a Workstream to `ACTIVE` or
  `BASELINED`.
- The Verification Consistency Engine may mark facts stale/invalid but may not waive them.
- The Verification Closure Engine recommends actions; it does not silently execute write modes.
- The Verification Reasoning Engine returns structured diagnosis/proposals and never grants approval.
- xverif, WavePeek, simulation, regression, and coverage outputs become
  evidence only after a project adapter/collector converts raw outputs into the
  appropriate typed report and the control plane derives its verdict. The core
  does not yet provide a universal vendor log/VDB/UCDB extractor.
