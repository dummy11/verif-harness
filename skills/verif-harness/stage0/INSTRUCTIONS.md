# init — Stage 0 verification bootstrap

**Mode**: `/verif-harness init`

**Dispatch contract**: For a new Spec Kit project, Stage 0 `tasks.md` names this
mode and its owned outputs explicitly. Once the execution gate approves that
task, `speckit.implement` auto-dispatches this mode. Do not ask the user to invoke
`init` again after a successful dispatch. Direct manual invocation is limited to
an approved recovery path or an immutable legacy-baseline import.

**Purpose**: Bootstrap the current project with harness-style verification discipline
below the verif-harness control plane. For new projects, Spec Kit `specs/` is the
sole editable specification authority. This mode produces operational governance
views and evidence/review structures; it does not create a second requirements source.
Produces: `.harness-config.json` + `.harness/` + `AGENTS.md` + 11 Stage 0
derived/governance docs + Stage 0 review packet. Codex projects also receive
the optional `.codex/agents/` helper configurations; Kimi Code projects do not
receive Codex-only TOML assets.

## Pre-conditions

Before starting:

- Current directory is the project root.
- There is some form of RTL under the project (verify with
  `find . -maxdepth 4 -type f \( -name '*.v' -o -name '*.sv' \) | head`).
- `.harness-config.json` does NOT already exist. If it does, stop and ask
  the user whether to re-bootstrap (destructive) or exit.
- For a new project, `.specify/` exists and the Stage 0 Spec Kit specification,
  plan, tasks, checklist, and analysis have passed their document review gates.
- `.specify/integration.json` records `codex` or `kimi` as the active runtime.
  Missing, corrupt, unsupported, or ambiguous runtime state is a blocking open
  question; do not infer it from the model name.
- For a new project running inside the Stage workflow, the approved task names
  `verif-harness mode: init`, declares the owned output paths listed below, and
  provides the workflow check as its validation command.
- For an already approved project, the existing documentation and approvals are
  explicitly classified as an immutable imported baseline. Do not rewrite dates,
  decisions, evidence, or provenance to imitate a historical Spec Kit workflow.

If pre-conditions fail, stop and report to the user. Do not proceed.

## Execution plan

Follow these steps IN ORDER. Do not skip. Do not merge steps.

### Step 1 — Discovery (silent, ~30 sec)

Run these probes and remember the results. Use them to populate defaults in
Step 2's questions. Do NOT hardcode any project-specific defaults.

```bash
# Project name default
basename "$PWD"

# Active Agent runtime (authoritative after Spec Kit bootstrap)
python3 <verif-harness-root>/scripts/verif_harness.py runtime status \
  --project-root .

# Candidate RTL roots (dirs containing .v/.sv, sorted by file count desc)
find . -maxdepth 3 -type d \( -name rtl -o -name hdl -o -name design -o -name src \) 2>/dev/null

# Top-module candidates: modules that no other module instantiates
# (heuristic: modules whose name doesn't appear in any .v/.sv file except its own)
find . -maxdepth 4 -type f \( -name '*.v' -o -name '*.sv' \) | head -30

# Candidate verification roots
ls -d sim verif dv tb 2>/dev/null

# Candidate design-docs roots
find . -maxdepth 5 -type d -iname 'design' 2>/dev/null | grep -iE 'doc|spec'

# Reference model spec candidates (upstream projects nearby)
ls -d ~/workspace/*SystemC* ~/workspace/*SystemCModel 2>/dev/null
```

Do not overthink discovery. If a probe returns nothing, present sensible
default text (e.g., `sim/`, `rtl/`) as an option in Step 2 anyway.

### Step 2 — Interactive Q&A

Batch 1 — ask these four together using the available user-input mechanism:

1. **Project name** — options: `<basename>` (default), Other
2. **RTL root directory** — options: detected candidates (up to 3), Other
3. **Verification root directory** — options: detected + `sim/`, Other
4. **DUT top file** — options: top 3 file candidates from discovery, Other

Batch 2 — ask these two:

5. **Design docs directory** — options: detected candidate, `None`, Other
6. **Reference model spec** — options: detected upstream `.md` path, `None`, Other

If the user picks "Other" for the DUT top file, ALSO ask for the module
name (a third batch or a follow-up), because file name ≠ module name.

If the user picks a top file where the module name equals the file basename
(no extension), auto-populate `rtl.top_module` and skip the extra question.
Otherwise, run `grep -E '^\s*module\s+\w+' <top_file>` to detect the module
name and confirm with the user.

### Step 3 — Write `.harness-config.json`

Assemble the config from Q&A answers. Structure:

```json
{
  "project_name": "<answer 1>",
  "rtl": {
    "root": "<answer 2, ensuring trailing slash>",
    "top_module": "<detected or answered>",
    "top_file": "<answer 4>"
  },
  "verif": {
    "root": "<answer 3, ensuring trailing slash>",
    "docs_root": "<answer 3>/docs/",
    "verification_subdir": "verification",
    "governance_subdir": "governance"
  },
  "design_docs": {
    "root": "<answer 5 or null if None>"
  },
  "reference_model": {
    "enabled": <true if answer 6 != None else false>,
    "spec_path": "<answer 6 or null>"
  }
}
```

Write to `.harness-config.json` at project root. Then validate against
`<skill-dir>/assets/harness-config.schema.json` if
`jsonschema` CLI is available; otherwise skip validation.

### Step 4 — Install harness assets

Copy files from the skill's `assets/` directory into the project:

```bash
mkdir -p .harness

cp <skill-dir>/assets/check_ai_workflow.py \
   .harness/check_ai_workflow.py
chmod +x .harness/check_ai_workflow.py

cp <skill-dir>/assets/batch_upgrade_stage.py \
   .harness/batch_upgrade_stage.py
chmod +x .harness/batch_upgrade_stage.py

cp <skill-dir>/assets/review-block.md \
   .harness/review-block.md

cp <skill-dir>/assets/doc-conventions.md \
   .harness/doc-conventions.md

cp <skill-dir>/assets/stage_gate_re_review_template.md \
   .harness/stage_gate_re_review_template.md

```

If the active runtime is `codex`, also install the optional Codex-only helper
agents:

```bash
mkdir -p .codex/agents
cp <skill-dir>/assets/codex-agents/*.toml .codex/agents/
```

If an agent TOML already exists, compare it and preserve the project version.
Do not install these TOML files for Kimi Code and do not invent a Kimi mapping
for them. Do not overwrite or generate `.codex/config.toml`; repository policy
and user configuration may already define sandbox, model, MCP, or hook behavior.

Note: `stage_review_packet_template.md` is NOT copied to `.harness/` —
it stays in the skill as a reference. The project's actual
`stage<N>_review_packet.md` is generated fresh per Stage (see Step 8).

### Step 4b — Create Stage 1 M1.1 directory scaffold

Create the fixed M1.1 TB directory tree so subsequent modes
(`add-interface`, `add-harness-layer`) and manual work (UVC bodies /
env / test / tb_top) all have a landing place.

The tree is fixed by `tb_architecture.md § LD11 目录布局` and is
DUT-agnostic (same layout for every harness-style project).

```bash
mkdir -p <verif_root>/testbench/top/if
mkdir -p <verif_root>/testbench/top/sva
mkdir -p <verif_root>/testbench/top/harness/dut_harness
mkdir -p <verif_root>/testbench/top/harness/tb_harness
mkdir -p <verif_root>/testbench/uvc
mkdir -p <verif_root>/testbench/env/vseq
mkdir -p <verif_root>/testbench/test
mkdir -p <verif_root>/testbench/pkg
mkdir -p <verif_root>/filelist
mkdir -p <verif_root>/regress
```

Then place a `.gitkeep` file in each empty leaf directory so git tracks
them:

```bash
touch <verif_root>/testbench/top/if/.gitkeep
touch <verif_root>/testbench/top/sva/.gitkeep
touch <verif_root>/testbench/top/harness/dut_harness/.gitkeep
touch <verif_root>/testbench/top/harness/tb_harness/.gitkeep
touch <verif_root>/testbench/uvc/.gitkeep
touch <verif_root>/testbench/env/vseq/.gitkeep
touch <verif_root>/testbench/env/.gitkeep
touch <verif_root>/testbench/test/.gitkeep
touch <verif_root>/testbench/pkg/.gitkeep
touch <verif_root>/filelist/.gitkeep
touch <verif_root>/regress/.gitkeep
```

Notes:

- UVC subdirectories (`uvc/<name>_agent/seq/`) are NOT created here —
  they're created by `/verif-harness add-interface` per interface,
  because each UVC corresponds to a protocol interface.
- If any target directory already exists (user pre-created), skip
  silently — do not overwrite existing content.
- This step is intentionally minimal: no source files, no filelist
  content, no Makefile. Those come in later modes and manual work.

### Step 5 — Render `AGENTS.md` from template

Read `<skill-dir>/assets/AGENTS.md.tmpl` and substitute:

Placeholder table (compute values from `.harness-config.json`):

| Placeholder | Value |
|-------------|-------|
| `{{PROJECT_NAME}}` | config.project_name |
| `{{RTL_ROOT}}` | config.rtl.root |
| `{{DUT_TOP_MODULE}}` | config.rtl.top_module |
| `{{DUT_TOP_FILE}}` | config.rtl.top_file |
| `{{VERIF_ROOT}}` | config.verif.root |
| `{{DOCS_ROOT}}` | config.verif.docs_root |
| `{{PLAN_PATH}}` | docs_root + "plan.md" |
| `{{ROADMAP_PATH}}` | docs_root + "roadmap.md" |
| `{{METHODOLOGY_PATH}}` | docs_root + "harness_style_methodology.md" |
| `{{WORKFLOW_PATH}}` | docs_root + "governance/verification_workflow.md" |
| `{{VERIF_PLAN_PATH}}` | docs_root + "verification/verification_plan.md" |
| `{{FEATURE_MATRIX_PATH}}` | docs_root + "verification/feature_matrix.md" |
| `{{TESTCASE_LIST_PATH}}` | docs_root + "verification/testcase_list.md" |
| `{{TB_ARCHITECTURE_PATH}}` | docs_root + "verification/tb_architecture.md" |
| `{{ASSERTION_PLAN_PATH}}` | docs_root + "verification/assertion_plan.md" |
| `{{COVERAGE_PLAN_PATH}}` | docs_root + "verification/coverage_plan.md" |
| `{{REFMODEL_SPEC_LOCAL_PATH}}` | docs_root + "verification/reference_model_spec.md" |
| `{{REFMODEL_UPSTREAM_PATH}}` | config.reference_model.spec_path |
| `{{DESIGN_DOCS_ROOT}}` | config.design_docs.root (if set) |
| `{{DATE_TODAY}}` | today's date, format YYYY-MM-DD |

Conditional blocks:

- `{{#IF_REFMODEL}}...{{/IF_REFMODEL}}` — keep contents (strip markers) if
  `config.reference_model.enabled == true`; else delete the entire block
  including markers.
- `{{#IF_DESIGN_DOCS}}...{{/IF_DESIGN_DOCS}}` — keep if
  `config.design_docs.root` is non-null; else delete.

Write the rendered result to `AGENTS.md` at project root.

### Step 6 — Generate Stage 0 operational views

Read the authoritative Spec Kit Stage 0 artifacts first, then read
`<skill-dir>/assets/doc-conventions.md`. Follow it strictly. For each doc listed
there, generate content that:

1. Fits the doc's stated purpose.
2. Cites RTL at `<file>:<line>` for every DUT-behavior claim.
3. Puts uncertainty into `## 待 Human Review 的假设` or `## 开放问题`;
   already-decided directions with revisit window go to
   `## 暂定决策 (Provisional)` (see `doc-conventions.md § 决策生命周期约定`
   for the 4-decision-type classification and Provisional format).
4. Includes **all 4 decision sections** (even if empty as `- None`):
   `## 暂定决策 (Provisional)`, `## 开放问题` (top-level), plus
   `### Human Decisions` inside File-Level Human Review.
5. Ends with the Draft/Pending review block from `.harness/review-block.md`
   Template 1, with paths in `### Project-Level References` filled in to
   reflect this doc's related docs.
6. Starts with a provenance note naming the authoritative Spec Kit spec and
   stating that the file is an operational/governance view, not an independently
   editable requirements source.
7. Preserves `REQ -> VF -> PLAN -> TASK -> MODE -> ARTIFACT -> EVIDENCE -> GATE`
   identifiers and links. Do not create a second ID or requirement definition.

When a required operational detail is absent from the authoritative spec, add
an open question to Spec Kit and link it here. Do not silently define it only in
the derived document.

Docs to generate (order matters — later docs may cite earlier ones):

1. `<docs_root>/governance/verification_workflow.md`
2. `<docs_root>/plan.md`
3. `<docs_root>/roadmap.md`
4. `<docs_root>/harness_style_methodology.md`
5. `<docs_root>/verification/verification_plan.md`
6. `<docs_root>/verification/feature_matrix.md`
7. `<docs_root>/verification/tb_architecture.md`
8. `<docs_root>/verification/assertion_plan.md`
9. `<docs_root>/verification/coverage_plan.md`
10. `<docs_root>/verification/testcase_list.md`
11. `<docs_root>/verification/reference_model_spec.md` (only if
    `reference_model.enabled` is true)

Before writing #5-#11, read the DUT top file at `config.rtl.top_file` and
grep its submodule dependencies to build feature/interface understanding.
If `design_docs.root` is non-null, read those design docs for
supplementary context.

For #11 (reference_model_spec.md): read `config.reference_model.spec_path`,
copy its technical body sections into the local file, then WRAP with a
fresh Draft/Pending review block referencing this project's paths. The
first entry of the Revision Log must record the upstream source path.

### Step 7 — Run the check

```bash
python3 .harness/check_ai_workflow.py --fix --skip-markdownlint
```

Must exit 0. If it reports ERRORs:

- Fix the specific issues it lists (usually: missing review block heading,
  status inconsistency, reference to non-existent path).
- Re-run.
- Loop until exit 0 or you cannot resolve — in which case report to user.


Do NOT run with markdownlint yet — `npx markdownlint-cli2` may not be
installed in the environment. The user can run it manually later:

```bash
python3 .harness/check_ai_workflow.py --fix
```

### Step 8 — Generate Stage 0 Review Packet

Create `<docs_root>/stage0_review_packet.md` following
`<skill-dir>/assets/stage_review_packet_template.md`.
The packet aggregates all Human Decisions + Provisional decisions + open
questions across the 11 docs into a single reviewer-friendly checklist.

Content overview (see template for full structure):

- **Part 1: Human Decisions** — enumerate HD-1 ... HD-N with priority
  classification (P0 / P1 / P2), each with Approve / Changes / Reject
  checkboxes
- **Part 2: Provisional decisions** — grouped by target revisit Stage,
  each with Accept / Escalate to HD / Reject checkboxes
- **Part 3: Open Questions** — with Owner + Target-update-date fields
- **Part 4: Batch Upgrade Template** — instructions for
  `batch_upgrade_stage.py` usage
- **Part 5: Post-Review Checklist** — 10 verification items

### Step 9 — Report and stop

Emit a Stage 0 bootstrap summary:

```text
verif-harness bootstrap complete.

Config written:
  .harness-config.json

Installed:
  .harness/check_ai_workflow.py
  .harness/review-block.md
  .harness/doc-conventions.md
  .harness/batch_upgrade_stage.py
  .codex/agents/{verification-planner,coverage-auditor,rtl-spec-diff}.toml
    # Codex runtime only; omit this line for Kimi Code
  AGENTS.md

Docs generated (all in Draft / Pending status):
  <list of 10 or 11 docs>

Review packet generated:
  <docs_root>/stage0_review_packet.md
  - Human Decisions: <count> (P0: <n>, P1: <n>, P2: <n>)
  - Provisional decisions: <count> (grouped by Stage 1-5)
  - Open questions: <count>

Open questions raised (per doc):
  - <doc>: <one-line question>
  - ...

Cross-doc inconsistencies noted:
  - ...

Workflow check: passed

Task postcondition:
  - Every owned output declared by the approved init task exists.
  - The task validation command passed and its evidence path is recorded.
  - If either check fails, report TASK INCOMPLETE and return control to
    speckit.converge; do not request a duplicate manual init invocation.

Next steps for the user:
  1. Review stage0_review_packet.md systematically (2-3 hours).
  2. Fill checkboxes for HD / Provisional / OQ decisions.
  3. Run: python3 .harness/batch_upgrade_stage.py --stage 0 --date <today>
     to lift all docs from Draft/Pending to Approved / Living.
  4. Re-run python3 .harness/check_ai_workflow.py to confirm consistency.
  5. Git commit "freeze Stage <N> baseline: <count> docs approved".
  6. Then invoke Stage 1 (TB skeleton) via /verif-harness add-harness-layer
     (or continue manually) in a new session.

Do NOT proceed to Stage 1 in this session.
```

**Stop.** Do not implement TB code. Do not modify RTL. Do not mark any doc
as Approved or Frozen — that's a human decision.

## Failure modes

- **Config file already exists.** Ask user: overwrite (re-bootstrap) or exit.
- **No RTL found.** Stop with error; the skill requires an existing DUT.
- **Discovery finds no top-module candidate.** Ask user for the top file
  path directly (skip the options list).
- **check_ai_workflow.py fails after 3 fix attempts.** Report to user with
  the remaining errors; do not silently proceed.
- **Reference model spec path unreadable.** Ask user whether to disable
  reference model or provide an alternate path. Update `.harness-config.json`
  accordingly.
