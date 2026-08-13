---
name: verif-harness
description: Bootstrap, extend, audit, and govern harness-style RTL verification projects from Stage 0 through sign-off and public-release readiness. Use for UVM/harness scaffolding, test registration, coverage and assertion skeletons, reference-model adapters, deterministic regression, CI fragments, performance contracts, diagnostics, traceability, stage gates, structural sign-off, and open-source readiness audits. Never modify DUT RTL, approve Human Decisions, or declare confidential material safe to publish.
---

# verif-harness

Build and maintain an RTL verification project around `.harness-config.json`.
Keep DUT RTL read-only, preserve human approval boundaries, and prefer
deterministic scripts for structural checks.

## Dispatch

Support these explicit modes:

- `init`
- `add-interface`
- `add-shared-pkg`
- `add-uvc-skeleton [name]`
- `add-harness-layer`
- `add-env-layer`
- `finalize-filelist-and-make`
- `doctor`
- `add-regression-runner`
- `add-testcase`
- `add-coverage-skeleton`
- `add-assertion-skeleton`
- `add-refmodel-bridge`
- `add-ci-hook`
- `add-performance-gate`
- `audit-traceability`
- `stage-gate-review <completed-stage>`
- `signoff-audit <stage>`
- `oss-readiness`
- `patterns [topic]`

With no mode, run `doctor` when `.harness-config.json` exists. If it does not
exist, dispatch to `init`. After `doctor`, recommend the next mode but do not
perform a write mode automatically. Stage state becomes ambiguous after the
M1.1 scaffold and requires human judgment.

If the requested state is partial or ambiguous, stop before writing and report
the conflicting evidence.

## Global invariants

Apply these rules in every mode:

1. Read project `AGENTS.md` and obey repository-local instructions.
2. Read `.harness-config.json` when present; treat its paths as project-root
   relative unless explicitly documented otherwise.
3. Never modify the configured RTL root.
4. Before changing verification files, read the workflow, roadmap,
   methodology, verification plan, architecture, coding guide, and affected
   plans required by `AGENTS.md`.
5. Keep driver, monitor, sequencer, agent, env, scoreboard, coverage, and
   reference-model responsibilities layered.
6. Treat frozen Human Decisions and Approval Decisions as immutable without an
   approved change request.
7. Record ambiguity as an open question. Never turn missing evidence into a
   PASS or approval.
8. Make write modes additive by default. Refuse to overwrite non-generated
   content unless the user explicitly approves the exact files.
9. After Markdown changes, run the repository's documented Markdown workflow
   check and review any formatter changes.
10. Report all generated files and validation results. Do not commit, push,
    modify CI state, or run an EDA simulation unless the user separately asks.

## Bootstrap and M1.1 modes

### `init`

Use only when `.harness-config.json` is absent. Read
`stage0/INSTRUCTIONS.md` completely. Generate the Stage 0 documentation,
workflow assets, `AGENTS.md`, and the M1.1 directory scaffold. Stop for Human
review; do not start TB implementation.

### `add-interface`

Read `add-interface/INSTRUCTIONS.md` and the referenced sections of
`references/stage1-patterns.md`. Generate protocol interfaces and UVC landing
directories from `harness-spec.yaml`.

### `add-shared-pkg`

Read `add-shared-pkg/INSTRUCTIONS.md`. Generate the shared typedef/enum package
and pack/unpack package from the approved interface specification.

### `add-uvc-skeleton [name]`

Read `add-uvc-skeleton/INSTRUCTIONS.md`. Generate one or all UVC class
skeletons. Preserve parameterized top-agent/sub-agent structure when declared
by the harness specification.

### `add-harness-layer`

Read `add-harness-layer/INSTRUCTIONS.md`. Generate DUT harness, TB harness, and
SVA stubs. Parse the configured DUT top read-only.

### `add-env-layer`

Read `add-env-layer/INSTRUCTIONS.md`. Generate env configuration, virtual
sequencer, env, scoreboard, coverage collector, base test, packages, and
`tb_top` skeletons.

### `finalize-filelist-and-make`

Read `finalize-filelist-and-make/INSTRUCTIONS.md`. Generate canonical
filelists and the M1.1 compile-only Makefile target.

## Lifecycle modes

### `doctor`

Read `doctor/INSTRUCTIONS.md`, then run `doctor/scripts/doctor.py` against the
project root. This mode is read-only. Report errors, warnings, discovered
stage state, legacy Claude artifacts, RTL dirtiness, and a recommended next
mode. Do not repair findings unless the user asks.

### `add-regression-runner`

Read `add-regression-runner/INSTRUCTIONS.md`. Add a simulator-neutral isolated
regression launcher, result collector, same-seed failed-only rerun support, and
unit tests. Integrate with an existing Makefile only after inspecting its
targets; do not replace a working project-specific launcher.

### `add-testcase`

Read `add-testcase/INSTRUCTIONS.md`. Generate one test/vseq control skeleton
and register package includes additively. Update only an explicitly selected
candidate caselist; never promote a new test to the default regression.

### `add-coverage-skeleton`

Read `add-coverage-skeleton/INSTRUCTIONS.md`. Generate a coverage-model class
from a reviewed JSON contract containing exact coverpoint expressions, bins,
crosses, and plan references. Do not infer coverage semantics from names.

### `add-assertion-skeleton`

Read `add-assertion-skeleton/INSTRUCTIONS.md`. Generate an SVA checker and
optional bind statement from reviewed properties. An empty property remains a
TODO comment and must not be represented as an implemented assertion.

### `add-refmodel-bridge`

Read `add-refmodel-bridge/INSTRUCTIONS.md`. Generate a structural Syscan wrapper
or DPI-C import package from a reviewed backend contract. Leave alignment,
masking, numeric behavior, compare policy, and engagement proof project-specific.

### `add-ci-hook`

Read `add-ci-hook/INSTRUCTIONS.md`. Generate a GitLab CI or Jenkins fragment
from explicit commands and artifact paths. Never edit live CI settings, embed
secrets, or issue mutating Git commands.

### `add-performance-gate`

Read `add-performance-gate/INSTRUCTIONS.md`. Evaluate marked log records using
a reviewed JSON contract with fixed operands and comparison operators. Do not
invent metrics, formulas, thresholds, expected counts, or waivers.

### `audit-traceability`

Read `audit-traceability/INSTRUCTIONS.md`, then run
`audit-traceability/scripts/audit_traceability.py`. This mode is read-only by
default. Audit default-manifest entries, UVM test classes, testcase document
references, and verification IDs. It may emit a report but must not change the
plans or promote tests automatically.

### `stage-gate-review <completed-stage>`

Read `stage-gate-review/INSTRUCTIONS.md`, then run
`stage-gate-review/scripts/build_stage_gate.py`. Generate a Draft gate packet
from repository evidence, due Provisional decisions, open questions, change
requests, and roadmap exit criteria. Never check approval boxes, edit source
decisions, or mark the gate Approved.

### `signoff-audit <stage>`

Read `signoff-audit/INSTRUCTIONS.md`, then run
`signoff-audit/scripts/audit_signoff.py`. Audit sign-off packet structure,
regression-manifest uniqueness, evidence topics, approval metadata, and Git RTL
scope. `APPROVED_RECORDED` reports existing metadata; it is not a new approval.

### `oss-readiness`

Read `oss-readiness/INSTRUCTIONS.md`, then run
`oss-readiness/scripts/audit_oss_readiness.py`. Check community files,
reproducible examples, CI, sensitive identifiers, absolute paths, and optional
Git history. A clean result is evidence for Human review, not publication
authorization or a confidentiality guarantee.

## Pattern lookup

### `patterns [topic]`

Read `references/stage1-patterns.md` and answer the question with section
references. For regression and lifecycle questions, also read
`references/regression-patterns.md` or `references/lifecycle-patterns.md`. For
Stage 2+ implementation and evidence contracts, read
`references/implementation-patterns.md`.

## Resource map

- `references/stage1-patterns.md`: compile order, layering, bind, and M1.1
  conventions.
- `references/regression-patterns.md`: result contract, seed policy,
  isolation, rerun, and evidence rules.
- `references/lifecycle-patterns.md`: traceability and stage-gate rules.
- `references/implementation-patterns.md`: explicit-contract rules for tests,
  coverage, assertions, reference models, CI, performance, and sign-off.
- `oss-readiness/`: public-release structure and sensitive-data audit.
- `assets/`: Stage 0 governance assets and templates copied into projects.
- Each write mode has one `INSTRUCTIONS.md`; read it completely before acting.

## Scope boundary

The skill implements Stage 0 and Stage 1 M1.1 scaffolding, additive Stage 2+
control skeletons, explicit-contract generators/evaluators, regression
infrastructure, structural audits, and gate-packet generation. Meaningful
stimulus and all project semantics remain Human-reviewed project inputs.
Generated structure, a clean audit, or recorded approval metadata never proves
functional correctness and never grants approval.
