# evidence — typed Workstream evidence

User-facing definitions for schema, claim, validator, raw artifact, and native
artifact are in the [glossary](../docs/glossary.md#evidence-format).

Modern implementation and convergence deliveries use `verif-harness code validate
NODE REPORT.json`: `CodeValidation/1` wraps the typed reports below and binds the
current delivery, revision, inputs and outputs. In particular, VCOV and VREG's
four direct public node types never use `evidence` to bypass plan approval or
delivery acceptance. VREG results also bind execution to complete triage and an
Engine-derived current required evidence set under `RegressionResults/4`.

Use `verif-harness evidence NODE REPORT.json` only for historical non-code-model
VENV, VCHK, VCOV, VCASE, and VREG desired nodes. Standard template nodes infer their claim; custom nodes require
`--claim`. VSTIM is dispatched to its stricter reachability validator. VDOC
semantic approval remains `docs review` and is not accepted here.

Compiler logs, simulation logs, regression manifests, waveform files, and
VDB/UCDB coverage databases are raw artifacts, not verdicts. A deterministic
project adapter or extractor must convert their relevant facts into one of the
typed JSON reports below. The control plane does not yet include a universal
vendor log/VDB/UCDB extractor. Prefer native JSON/XML/JUnit or formal coverage
exports to free-form text parsing; an Agent/LLM summary is not a deterministic
extractor.

The command validates the Workstream schema and claim-specific invariants,
then derives PASS or FAIL from the content. A malformed report is rejected
without creating evidence. A valid report with blockers is retained as FAIL
evidence. Every native log/database entry must provide a project-relative path,
SHA-256, explicit artifact `kind`, and deterministic analyzer in `analyzed_by`;
missing or changed artifacts are rejected and later changes
invalidate the bound node. Every implementation, policy, manifest, or log
digest asserted by a claim must match one of those artifact digests. Evidence
revision must match the bootstrap project
revision when that revision is available. Planner-default prerequisites are
checked at ingestion too. A structurally and semantically valid report is
retained as FAIL while a required current-revision prerequisite is missing or
not VALID/WAIVED; rerun the producer after satisfying the prerequisite. Never
promote the old FAIL record automatically.

Schemas and starting examples are in this directory:

- `environment-evidence.schema.json` / `environment-evidence.example.json`
- `stimulus-capability-evidence.schema.json` / `stimulus-capability-evidence.example.json`
- `checking-evidence.schema.json` / `checking-evidence.example.json`
- `coverage-evidence-v3.schema.json` / `coverage-evidence-v3.example.json`（当前 VCOV）
- `coverage-scope.schema.json` / `coverage-scope.example.json`
- `coverage-implementation-config.schema.json` / `coverage-implementation-config.example.json`
- `coverage-collection-config.schema.json` / `coverage-collection-config.example.json`
- `coverage-object-inventory-v2.schema.json` / `coverage-object-inventory-v2.example.json`
- `coverage-database-shard-manifest.schema.json` / `coverage-database-shard-manifest.example.json`
- `coverage-merge-manifest.schema.json` / `coverage-merge-manifest.example.json`
- `coverage-evidence.schema.json` / `coverage-evidence.example.json`（`CoverageEvidence/2`，仅历史审计）
- `coverage-object-inventory.schema.json` / `coverage-object-inventory.example.json`（`CoverageObjectInventory/1`，仅历史审计）
- `coverage-item-manifest.schema.json` / `coverage-item-manifest.example.json`（仅历史审计）
- `submit-profile-ref.schema.json` / `submit-profile-ref.example.json`
- `case-manifest.schema.json` / `case-manifest.example.json`
- `regression-batch-manifest.schema.json` / `regression-batch-manifest.example.json`
- `testcase-evidence.schema.json` / `testcase-evidence.example.json`
- `regression-evidence.schema.json` / `regression-evidence.example.json`

Standard claims:

| Workstream | Claims |
| --- | --- |
| VENV | capability: `interface-ready`, `clock-reset-ready`, `topology-ready`, `build-ready`, `run-ready`, `observation-ready`; closure: `environment-smoke-evidence` |
| VSTIM | capability: `transaction-contract`, `stimulus-implementation`, `corner-scenarios`; closure remains `StimulusReachabilityEvidence/1` |
| VCHK | capability: `compare-policy`, `reference-model`, `scoreboard`, `assertions`; closure: `reference-model-evidence`, `scoreboard-evidence`, `assertion-evidence` |
| VCOV | capability: `coverage-model`, `coverage-collection`; closure: `coverage-collection-evidence`, `hole-analysis-evidence` |
| VCASE | `case-matrix`, `case-implementation`, `targeted-evidence` |
| VREG | capability: `regression-policy`, `executor-ready`; closure: `execution-evidence`, `triage-evidence`, `fresh-evidence` |

Do not use generic `prove` or low-level `record evidence` to bypass these
contracts. Human approval and waiver are separate authorities.

Every report except the separate VSTIM reachability format uses this common
envelope:

```json
{
  "schema": "<WorkstreamEvidence/1>",
  "claim": "<fixed node claim>",
  "revision": "<bootstrap project revision>",
  "tool": "<producer/version>",
  "artifacts": [{
    "path": "project/relative/path",
    "sha256": "<sha256>",
    "kind": "simulation-log",
    "analyzed_by": ["xverif"]
  }],
  "result": {"...": "claim-specific facts"}
}
```

The Planner writes the exact admission policy into every desired node and the
Workstream `plan.md`. Runtime claims normally require an xverif-analyzed
`simulation-log` plus either a WavePeek-analyzed `waveform` or an
xverif-analyzed `transaction-trace`, and a stored `analysis-report` produced by
xverif or WavePeek. Coverage closure requires a `coverage-database` plus an
xverif `analysis-report`; regression execution requires a `regression-manifest`,
simulation logs, and an xverif `analysis-report`. Source capability claims require
`source` plus `build-log`. A report that omits one of these classes is retained
as FAIL even if its result body says PASS.

An `analysis-report` is not an arbitrary project summary. At ingestion the
control plane opens the referenced JSON and requires an adapter run receipt with
`adapter_schema_version=1`, `state=PASS`, an empty `blockers` list, a valid
`request_sha256`, a non-empty `operation`, and a PASS `tool_identity`. xverif
receipts also name the executed tool; WavePeek receipts bind the executable
SHA-256. A forged free-form file carrying only `{"state":"PASS"}` is rejected.

Compilation artifacts normally prove capability readiness only. Runtime
closure requires observations such as accepted stimulus, non-zero checker
engagement, assertion attempts without failures or vacuity, targeted test
PASS, complete coverage-object counts plus every excluded/uncovered hole, and
regression execution/triage. A waveform
or transaction trace is an analysis input, not a substitute for the typed
counters and semantic checks in the report result.

`fresh-evidence` reports provide only `result.snapshot_revision`; the engine
derives required closure-evidence nodes from the current Planner graph and
stores the resulting node/evidence-digest set. Do not let a producer choose a
smaller required-node list. Regression execution records raw failures as valid
execution facts; triage closes them only when every failed test/seed has a
matching same-seed rerun verdict/log digest and disposition. An accepted known
failure must reference a Human `WAIVE` review stored in the project database.

`SubmitProfileRef/1` is emitted by the testbench submit adapter. Its source
submit file remains the project authority for compile, simulation, scheduler,
license, and site wrapper settings; the control plane validates only the
project-relative file reference and digests. `CaseManifest/2` binds one
testcase or executable virtual sequence to one submit profile. The same logical
case may have multiple manifests for different profiles. `traceability` binds its
existing testcase-list entry, verification points, versioned specification/RTL/
coverage-hole/defect/model/decision sources, and the expected result/checking basis.
Every source reference must match a native artifact's path, SHA-256 and kind.
RTL-only unconfirmed expectations are recorded but block delivery. A claimed owner
confirmation must be verified against the existing current-node question and exact
behavior digest by ProjectStore; report text is not approval. Old CaseManifest/1
and TestcaseExecution/2 receipts are audit history, not current traceability evidence.

The testbench submit flow also emits one `RegressionBatchManifest/2` and one
caselist for each regression group/profile binding. A batch cannot mix submit
profiles. The same case set under two profiles is therefore two batches and two
caselists. `RegressionEvidence/3` identifies each result and triage record by
batch, case, seed, and iteration. These manifests are internal artifacts and do
not create WorkNodes or approval gates.

Modern result plans approve `regression_config`: one group/case set/profile,
random or fixed seed mode, and positive per-case repeat (default one). The
testbench resolves every seed and writes the batch's `runs` before launch.
Random mode uses a fresh seed per planned iteration; fixed mode uses the approved
seed. Reports and batches bind the same `execution_binding` (round ID, plan node,
revision and approval digest). The engine checks scope/config identity and all
planned iterations; a report cannot reduce repeat or replace the current round.
Failure reruns use original seeds, preserve original failures and remain separate
from planned repeat. A new whole-group run is owner-authorized on the existing
result delivery, not a new WorkNode or workflow restart. Old formats remain
readable as historical contracts but cannot satisfy current result acceptance.

VCOV excluded coverage uses a different gate. The owner provides one exclusion
file on the current coverage-convergence delivery, and that provision is the
approval of the file's exclusion scope. `hole-analysis-evidence` must include the
exact path and SHA-256 as an xverif-analyzed `configuration`, and every excluded
item must reference that single file-level approval. Agent validation checks
legality and consistency only; it must not create or infer the approval. A new
file, changed digest, new VCOV revision, or changed convergence scope requires
revalidation. Per-item `WAIVE` reviews are not required for this VCOV flow.

Current VCOV reports use `CoverageEvidence/3`. The owner approves one stable
`CoverageScope/1` plus `CoverageImplementationConfig/1` per implementation plan;
code coverage targets only the DUT. xverif expands them against the current plan
and model into `CoverageObjectInventory/2`. Do not copy every native code coverage
object or functional bin into ProjectStore. A convergence plan's
`CoverageCollectionConfig/1` references approved VREG configs and approves exactly
one DUT-only build-fingerprint partition. Its delivery binds every VDB shard to a
VREG round/batch/run and binds the exact shard set to one merged database. Different
testbenches or submit profiles may merge when DUT RTL, parameters, macros, and
DUT-level elaboration match; different DUT fingerprints require separate convergence
plan/delivery pairs. `coverage-model`, collection, and hole-analysis reports bind the
inventory digest. Hole analysis reports complete required/covered/excluded/uncovered
counts and enumerate only excluded or uncovered objects. `CoverageEvidence/1`,
`CoverageEvidence/2`, `CoverageObjectInventory/1`, and `CoverageItemManifest/1`
remain readable historical formats but cannot satisfy current delivery acceptance.
