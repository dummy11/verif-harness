# spec-kit mode

Use this mode to make verif-harness the top-level control plane while GitHub
Spec Kit owns the editable specification lifecycle.

## Required context

1. Read project `AGENTS.md` and `.harness-config.json`.
2. Resolve the complete verif-harness checkout through the active runtime Skill
   link and its `scripts/verif-harness` launcher. Do not look for repository
   scripts, locks, or integrations below a separate verification workspace.
3. Read `integrations/spec-kit/README.md` from that resolved checkout.
4. Read the current Spec Kit constitution, program/stage spec, plan, tasks, and
   the `specify`/`clarify`-maintained `checklists/requirements.md` before
   dispatching an execution mode. Read custom checklists only when the reviewer
   explicitly requested them.
5. Read the requested verif-harness mode instructions before writing.

## Supported operations

- `probe`: validate the pinned Spec Kit source and managed Python environment.
- `bootstrap`: resolve `auto|codex|kimi`, initialize the matching Spec Kit
  integration, then add the local `verif-harness-rtl` preset. Treat
  `.specify/integration.json` as the runtime source of truth. Refuse existing
  `.specify/`; never force-merge it. Invoke the wrapper without `--force`, even
  when setup has already populated the initially empty workspace. After the
  refusal check, the wrapper handles Spec Kit's non-empty-directory bypass
  internally and noninteractively.
- `stage`: run the local `verif-stage-lifecycle.yml` for exactly one Stage 0-5
  objective. The workflow has document review gates and an execution gate but
  does not approve a Stage. Project-review Markdown generated under `specs/`
  and the constitution default to Simplified Chinese; code, commands, paths,
  configuration keys, protocol names, stable identifiers, and original quoted
  material remain unchanged. Upstream `.specify/` infrastructure files remain
  in their distribution language. For a new Stage 0 project without
  `.harness-config.json`, the reviewed task set must contain exactly one
  `verif-harness mode: init` task. After execution authorization, the persistent
  task runner dispatches that mode; no separate successful-path manual `init`
  call follows the workflow.
- `status`: inspect one run or list all workflow run states. For a delayed
  recheck, use one bounded `status <run-id> --wait-seconds 30` call. Never
  create a shell polling loop or parse status JSON with `grep`.
- `resume`: resume a paused run with an explicit `--verdict approve|reject` for
  its current review gate. A reviewer must inspect the named artifact before
  choosing the verdict; one verdict never carries into the next gate, and
  resuming does not approve the Stage. When the task runner is `BLOCKED`, use
  `--answer` instead; it retries only `current_task_id`. Always inspect
  `status <run-id>` first. Its `resume_allowed` result is authoritative over
  the requested command: when false, do not call resume. A live `running`
  worker requires `action_required: wait-for-worker` and status polling, not a
  verdict, even if the user already supplied one.
- `block`: while one task is `RUNNING`, persist its concrete Human, authority,
  specification, or execution question. The runner observes the state and
  terminates that task's Agent process instead of waiting for terminal input.
- `revise-tasks`: with explicit Human `--verdict approve --reason`, rebind a
  corrected contract for a legacy run paused at `authorize-execution` after
  analyze, or for an implementation-blocked run with no DONE task. A
  pre-execution revision does not authorize execution; review that gate
  separately afterward.
- `recover`: after a fixed-duration outer task killed a worker, convert a
  confirmed stale `running` run to resumable `failed` state while preserving
  its current step and evidence. For an interrupted task, reconcile reviewed
  postconditions first: mark it `DONE` without replay when they pass, otherwise
  persist `BLOCKED`. Require `--confirm-stale`, refuse a live worker, and resume
  the same run; never start a replacement run silently.
- `docs-zh`: refresh `.specify/docs/zh-CN/`, a non-executable Simplified
  Chinese reading mirror. Its manifest records source/translation hashes and
  `full|source-is-chinese|summary|pending` status. The mirror is never a
  template, command, workflow, specification authority, or approval artifact.

When operating through Codex or Kimi Code, invoke this mode through the
runtime-native Skill inside the Agent CLI:

```text
# Codex
$verif-harness probe
$verif-harness bootstrap

# Kimi Code
/skill:verif-harness probe
/skill:verif-harness bootstrap
```

The runtime-native launcher detaches `stage` and `resume`, records a
per-run worker PID and log, and returns immediately. Poll with
`status <run-id>`. Do not place these commands inside a 600-second (or
other fixed-duration) background shell task, and do not submit a duplicate
stage while the worker is active. Direct Python automation remains foreground
unless it explicitly passes `--detach`.
Each polling command must be independently bounded: use plain `status` or one
`--wait-seconds` value from 1 to 50. Do not use `for`/`while`, repeated `sleep`,
`watch`, `tail -f`, or `grep`-based JSON parsing. Report `wait-for-worker`
progress before issuing another poll.

The repository Python wrapper remains available for CI, automation, or hosts
without an Agent CLI:

```bash
python3 scripts/verif_harness.py spec-kit probe
python3 scripts/verif_harness.py spec-kit bootstrap --project-root <project>
python3 scripts/verif_harness.py spec-kit stage \
  --project-root <project> --stage <0-5> --objective <reviewed-objective>
python3 scripts/verif_harness.py spec-kit status --project-root <project>
python3 scripts/verif_harness.py spec-kit docs-zh --project-root <project>
python3 scripts/verif_harness.py spec-kit resume \
  --project-root <project> <run-id> --verdict approve
python3 scripts/verif_harness.py spec-kit recover \
  --project-root <project> <run-id> --confirm-stale
python3 scripts/verif_harness.py runtime status --project-root <project>
python3 scripts/verif_harness.py runtime switch \
  --project-root <project> --to <codex|kimi>
```

Inside an Agent session whose current directory is a separate verification
workspace, fulfill the native Skill invocation with the matching project-local
launcher:

```text
# Codex internal dispatch
.agents/skills/verif-harness/scripts/verif-harness bootstrap

# Kimi Code internal dispatch
.kimi-code/skills/verif-harness/scripts/verif-harness bootstrap
```

These paths traverse setup-managed Skill links into the complete checkout. A
valid link is evidence that the package is available; do not report missing
`scripts/`, `deps/`, or `integrations/` based only on the workspace root.
The launcher inherits the workspace current directory and resolves its single
runtime marker. Add `--project-root` or `--integration` only for an explicit
cross-project, automation, recovery, or ambiguous-marker case.

Do not drive a workflow review gate by opening a PTY and feeding a numeric menu
choice. The wrapper deliberately gives the Spec Kit workflow no interactive
stdin so every gate persists `paused`; inspect it with `status`, then
resume with the explicit verdict option. EOF must never become an implicit
rejection.

The default lifecycle does not invoke the optional, generic
`speckit.checklist` command. `specify` and `clarify` maintain
`checklists/requirements.md`, whose quality result is reviewed together with
the analyze report and task contract at `review-tasks`. Analyze runs before
that gate so findings cannot arrive after the contract is approved. Generate a custom checklist only when a
reviewer explicitly requests a domain-specific question set. The lifecycle
pauses after task generation, analysis, task execution, and convergence.
Execution uses the project-managed task runner, not the monolithic upstream
`speckit.implement` command. Each task has persisted
`READY/RUNNING/DONE/BLOCKED` state; `status` exposes the exact current task and
block question, and resume never replays `DONE` tasks.

## Source-of-truth policy

- New projects use `specs/` as the sole editable specification authority.
- `.specify/docs/zh-CN/` is a derived reading aid only. Never dispatch its
  files or use them as inputs to template resolution, command discovery,
  workflow execution, evidence evaluation, or Human review decisions.
- Other documentation trees contain governance, generated views, evidence
  indexes, review packets, and historical baselines, not duplicated editable
  requirements.
- Import existing approved projects as immutable baselines. Do not rewrite old
  decisions, approval dates, evidence, or provenance.
- Every executable task must map
  `REQ -> VF -> PLAN -> TASK -> MODE -> ARTIFACT -> EVIDENCE -> GATE`.
- Keep executable tasks `interaction: none`. Record Human answers, new authority,
  or unresolved semantics as `OPEN B###`; do not approve task review while any
  such blocker remains.
- Separate multiple `outputs`, `evidence`, and `needs` values with commas.
  Require `validate` to be a real noninteractive `/bin/sh` command, never a
  natural-language completion condition, Agent instruction, placeholder, or
  mutating `--fix|--write|--update|--in-place` invocation. Doctor validation
  must preserve the direct doctor exit code. Owned output/evidence paths must
  stay project-relative and outside the configured read-only RTL root.
- Bind `review-tasks` approval to the compact contract hash. Refuse execution
  authorization if any later action changes task semantics; checkbox
  changes made by the runner do not change that hash.

## Boundaries

- Spec Kit is agentic and requires Python 3.11+. It is not a deterministic
  evidence tool.
- Never edit DUT RTL, infer ambiguous semantics, or change frozen Human
  Decisions without an approved change request.
- A Spec Kit command, workflow, checklist, or gate reporting success is not
  compile, simulation, regression, coverage, assertion, performance, Stage,
  sign-off, freeze, or publication approval.
- Treat dispatch as successful only when every reviewed task's owned output
  paths exist and its validation command passes. In Stage 0, absence of
  `.harness-config.json`, `AGENTS.md`, the harness assets, derived governance
  views, review packet, or required scaffold is an incomplete `init` task.
  Apply the same rule to every Stage and every named mode: missing generated
  files, tool evidence, reports, or audit outputs leave that task incomplete.
  Record the deviation and stop convergence; do not hide it with an untracked
  duplicate manual invocation.
- EDA runs, commit, push, tag, release, waivers, and approval require their own
  authority under the project rules.
- Model selection remains owned by the active Agent runtime. Changing a model
  within Codex or Kimi Code does not rewrite integration state, specifications,
  tasks, evidence, or approvals. Switch runtimes only at a stable review gate;
  never force replacement of modified managed Skill files automatically.
- `--ignore-agent-tools` is reserved for CI/scaffold validation. Do not use it
  in a normal Agent-driven project bootstrap to hide a missing runtime.

## Output

Report the Spec Kit version/commit, project path, specification artifacts,
workflow run identity, dispatched verif-harness modes, deterministic/dynamic
evidence paths, unresolved questions, and the next Human authority boundary.
