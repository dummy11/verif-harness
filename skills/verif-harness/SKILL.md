---
name: verif-harness
description: Govern spec-driven harness-style RTL verification projects from Stage 0 through sign-off and public-release readiness. Use for GitHub Spec Kit specification workflows, UVM/harness scaffolding, test registration, coverage and assertion skeletons, reference-model adapters, deterministic regression, xverif CLI delegation, WavePeek waveform inspection, CI fragments, performance contracts, diagnostics, traceability, stage gates, structural sign-off, and open-source readiness audits. Never modify DUT RTL, approve Human Decisions, or declare confidential material safe to publish.
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
- `spec-kit`
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
- `stage-gate-review <completed-stage>`
- `signoff-audit <stage>`
- `freeze-baseline`
- `oss-readiness`
- `patterns [topic]`

With no mode, run `doctor` when `.harness-config.json` exists. If it does not
exist, require a Spec Kit project and reviewed Stage 0 specification first:
dispatch to `spec-kit bootstrap` when `.specify/` is absent. When `.specify/`
exists, inspect the Stage 0 run and task set: dispatch `init` only from the
approved `speckit.implement` task; otherwise report the pending review gate or
missing task instead of bypassing the workflow. After `doctor`, recommend the
next mode but do not perform a write mode automatically. Stage state becomes
ambiguous after the M1.1 scaffold and requires human judgment.

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

Use only when `.harness-config.json` is absent and a reviewed Spec Kit Stage 0
specification exists. Read `stage0/INSTRUCTIONS.md` completely. Generate Stage
0 operational governance views linked to the authoritative `specs/` artifacts,
workflow assets, `AGENTS.md`, and the M1.1 directory scaffold. Stop for Human
review; do not start TB implementation or create a competing requirements
authority. For a new project, Stage 0 `tasks.md` must name this mode explicitly;
after the execution gate approves that task, `speckit.implement` dispatches it
automatically. Do not require or perform a second manual `init` invocation after
successful dispatch. Manual invocation is a recovery/import path only.

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

### `spec-kit`

Read `spec-kit/INSTRUCTIONS.md` and the complete repository's
`integrations/spec-kit/README.md`. Keep verif-harness as the top-level control
plane and use the commit-pinned GitHub Spec Kit dependency for constitution,
specification, clarification, planning, checklist, task, analysis,
implementation-dispatch, and convergence documents. New projects use `specs/`
as the sole editable specification authority; import approved legacy projects
as immutable baselines. Spec Kit is agentic, not deterministic evidence, and
its workflow gates are never Stage, sign-off, freeze, or publication approval.
When an approved task names a verif-harness mode, `speckit.implement` owns the
dispatch exactly once. This applies to every mode, including generators,
adapters, audits, closure checks, and `init`. After dispatch, require every
owned output path, evidence path, and validation command from the task contract;
missing artifacts mean the task is incomplete, not that the user should
silently invoke the same mode again.

### `doctor`

Read `doctor/INSTRUCTIONS.md`, then run `doctor/scripts/doctor.py` against the
project root. This mode is read-only. Report errors, warnings, discovered
stage state, legacy Claude artifacts, RTL dirtiness, and a recommended next
mode. Do not repair findings unless the user asks.

### `xverif`

Read `xverif/INSTRUCTIONS.md`, the request schema, and
`references/xverif-adapter-contract.md`. Route one reviewed operation to the
allowlisted CLI wrapper under the commit-pinned managed `BLANK2077/xverif`
checkout. The same pinned checkout includes the optional `xverif_mcp` server;
use `xverif mcp install|configure|status|probe` for its explicit source/profile
lifecycle. When operating in the verif-harness repository, use
`scripts/setup_xverif.py` and `deps/xverif.lock.json`; do not clone a moving
branch, vendor upstream source, or silently update an existing checkout. Preserve
native argv and JSON/XOUT/text semantics, capture tool Git identity and hashes,
and fail closed on protocol, timeout, or artifact errors. MCP runtime
registration remains host-managed and must not write credentials to the
repository. Do not invent a single `xverif` executable, auto-switch
surfaces/backends, or interpret adapter PASS as verification approval.

### `wavepeek`

Read `wavepeek/INSTRUCTIONS.md`, the request schema, and
`references/wavepeek-adapter-contract.md`. Route one reviewed, bounded waveform
query to the commit-pinned `kleverhq/wavepeek` CLI. In this repository use
`scripts/setup_wavepeek.py` and `deps/wavepeek.lock.json`; never track the
managed checkout or binary, build a moving branch, or enable FSDB implicitly.
Preserve WavePeek JSON/JSONL/text semantics and capture source/binary/output
hashes. Adapter PASS proves query execution only, not the correctness of an
RTL interpretation or verification closure.

### `add-regression-runner`

Read `add-regression-runner/INSTRUCTIONS.md`. Add a simulator-neutral isolated
regression launcher, result collector, same-seed failed-only rerun support, and
unit tests. Integrate with an existing Makefile only after inspecting its
targets; do not replace a working project-specific launcher.

### `add-simulator-profile`

Read `add-simulator-profile/INSTRUCTIONS.md`. Generate a normalized simulator
profile and Makefile fragment from reviewed command-token, capability,
environment-key, and evidence contracts. A generated profile is configured,
not tested or supported.

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

### `complete-uvc`

Read `complete-uvc/INSTRUCTIONS.md`. Generate concrete ready/valid source driver
and monitor behavior from explicit clocking-block, handshake, payload-mapping,
timeout, and plan-reference inputs. Do not infer protocol semantics or apply
this mode to unsupported protocols.

### `complete-scoreboard`

Read `complete-scoreboard/INSTRUCTIONS.md`. Generate a FIFO-aligned scoreboard
with exact, masked, and absolute-tolerance comparisons from a reviewed contract.
Alignment, masking, numeric policy, and reset flushing remain explicit project
decisions.

### `add-ci-hook`

Read `add-ci-hook/INSTRUCTIONS.md`. Generate a GitLab CI or Jenkins fragment
from explicit commands and artifact paths. Never edit live CI settings, embed
secrets, or issue mutating Git commands.

### `add-performance-gate`

Read `add-performance-gate/INSTRUCTIONS.md`. Evaluate marked log records using
a reviewed JSON contract with fixed operands and comparison operators. Do not
invent metrics, formulas, thresholds, expected counts, or waivers.

### `regression-triage`

Read `regression-triage/INSTRUCTIONS.md`, then run
`regression-triage/scripts/triage_regression.py`. Group failures with reviewed
regex signatures and require same-seed rerun evidence. Classifications are
candidates for Human triage, not automatic root causes or waivers.

### `coverage-closure`

Read `coverage-closure/INSTRUCTIONS.md`, then run
`coverage-closure/scripts/audit_coverage_closure.py`. Audit a tool-neutral
coverage export for plan completeness, hits, exclusions, waiver metadata,
database identity, and total consistency. Readiness is not freeze approval.

### `assertion-closure`

Read `assertion-closure/INSTRUCTIONS.md`, then run
`assertion-closure/scripts/audit_assertion_closure.py`. Audit compile,
bind/elaboration, attempts, failures, vacuity, and waiver metadata. Zero
failures with zero attempts is never closure.

### `audit-traceability`

Read `audit-traceability/INSTRUCTIONS.md`, then run
`audit-traceability/scripts/audit_traceability.py`. This mode is read-only by
default. Audit default-manifest entries, UVM test classes, testcase document
references, and verification IDs. It may emit a report but must not change the
plans or promote tests automatically.

### `change-control`

Read `change-control/INSTRUCTIONS.md`, then run
`change-control/scripts/audit_change_control.py`. Audit structured post-baseline
change requests, impact evidence, recorded decisions, and optional Git-diff
coverage. Never approve a request or modify a frozen decision.

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

### `freeze-baseline`

Read `freeze-baseline/INSTRUCTIONS.md`, then run
`freeze-baseline/scripts/build_freeze_manifest.py`. On a clean Git commit,
validate required evidence states and produce a SHA-256 manifest outside the
repository for Human review. Never tag, push, approve, or publish.

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

- `README.md`: 中文模式目录、快速用法和权限边界。
- `docs/user_guide.md`: 中文 Stage 0→freeze 流程，以及 31 个模式的输入、
  输出、用法、用途、场景和人工检查点。
- `docs/architecture.md`: 中文模式分层、数据流、证据状态和权限架构。
- `docs/troubleshooting.md`: 中文常见故障、false-green 风险和恢复方法。
- `references/stage1-patterns.md`: compile order, layering, bind, and M1.1
  conventions.
- `references/regression-patterns.md`: result contract, seed policy,
  isolation, rerun, and evidence rules.
- `references/lifecycle-patterns.md`: traceability and stage-gate rules.
- `references/implementation-patterns.md`: explicit-contract rules for tests,
  coverage, assertions, reference models, CI, performance, and sign-off.
- `references/xverif-adapter-contract.md`: xverif 工具族、request/result、
  JSON/XOUT、provenance 和权限合同。
- `xverif/`: request schema、example 和 deterministic CLI adapter。
- `references/wavepeek-adapter-contract.md`: WavePeek request/result、JSONL
  完整性、provenance 与权限边界。
- `wavepeek/`: request schema、example 和 deterministic waveform CLI adapter。
- Repository `deps/xverif.lock.json` and `scripts/setup_xverif.py`: optional
  managed dependency identity, installation, and validation.
- Repository `deps/wavepeek.lock.json` and `scripts/setup_wavepeek.py`: optional
  managed WavePeek source/release identity, installation, and validation.
- `spec-kit/`: Spec Kit 规格事实源、Stage workflow 和权限边界。
- Repository `deps/spec-kit.lock.json`, `scripts/setup_spec_kit.py`, and
  `integrations/spec-kit/`: optional managed specification subsystem, RTL
  preset, workflow, and bundle authoring assets.
- `oss-readiness/`: public-release structure and sensitive-data audit.
- `assets/`: Stage 0 governance assets and templates copied into projects.
- Each write mode has one `INSTRUCTIONS.md`; read it completely before acting.

## Scope boundary

The 31 modes cover specification lifecycle, Stage 0 and Stage 1 M1.1
scaffolding, additive Stage 2+
control skeletons, simulator/UVC/scoreboard completion, deterministic
regression and triage, coverage/assertion/change closure, structural audits,
gate packets, and a hash-anchored freeze candidate. Meaningful stimulus and all
project semantics remain Human-reviewed project inputs. Generated structure, a
clean audit, or recorded approval metadata never proves functional correctness
and never grants approval.
