# spec-kit mode

Use this mode to make verif-harness the top-level control plane while GitHub
Spec Kit owns the editable specification lifecycle.

## Required context

1. Read project `AGENTS.md` and `.harness-config.json`.
2. Read `integrations/spec-kit/README.md` from a complete verif-harness checkout.
3. Read the current Spec Kit constitution, program/stage spec, plan, tasks, and
   checklist before dispatching an execution mode.
4. Read the requested verif-harness mode instructions before writing.

## Supported operations

- `probe`: validate the pinned Spec Kit source and managed Python environment.
- `bootstrap`: initialize a new Codex Spec Kit project, then add the local
  `verif-harness-rtl` preset. Refuse existing `.specify/`; never force-merge it.
- `stage`: run the local `verif-stage-lifecycle.yml` for exactly one Stage 0-5
  objective. The workflow has document review gates and an execution gate but
  does not approve a Stage.
- `status`: inspect one run or list all workflow run states.
- `resume`: resume a paused run at its next review gate. A reviewer must inspect
  the named artifact before choosing a gate verdict; resuming does not approve
  the Stage.

Use the repository CLI:

```bash
python3 scripts/verif_harness.py spec-kit probe
python3 scripts/verif_harness.py spec-kit bootstrap --project-root <project>
python3 scripts/verif_harness.py spec-kit stage \
  --project-root <project> --stage <0-5> --objective <reviewed-objective>
python3 scripts/verif_harness.py spec-kit status --project-root <project>
python3 scripts/verif_harness.py spec-kit resume \
  --project-root <project> <run-id>
```

## Source-of-truth policy

- New projects use `specs/` as the sole editable specification authority.
- Other documentation trees contain governance, generated views, evidence
  indexes, review packets, and historical baselines, not duplicated editable
  requirements.
- Import existing approved projects as immutable baselines. Do not rewrite old
  decisions, approval dates, evidence, or provenance.
- Every executable task must map
  `REQ -> VF -> PLAN -> TASK -> MODE -> ARTIFACT -> EVIDENCE -> GATE`.

## Boundaries

- Spec Kit is agentic and requires Python 3.11+. It is not a deterministic
  evidence tool.
- Never edit DUT RTL, infer ambiguous semantics, or change frozen Human
  Decisions without an approved change request.
- A Spec Kit command, workflow, checklist, or gate reporting success is not
  compile, simulation, regression, coverage, assertion, performance, Stage,
  sign-off, freeze, or publication approval.
- EDA runs, commit, push, tag, release, waivers, and approval require their own
  authority under the project rules.

## Output

Report the Spec Kit version/commit, project path, specification artifacts,
workflow run identity, dispatched verif-harness modes, deterministic/dynamic
evidence paths, unresolved questions, and the next Human authority boundary.
