# evidence — typed Workstream evidence

User-facing definitions for schema, claim, validator, raw artifact, and native
artifact are in the [glossary](../docs/glossary.md#evidence-format).

Use `verif-harness evidence NODE REPORT.json` for VCHK, VCOV, VCASE, and VREG
desired nodes. Standard template nodes infer their claim; custom nodes require
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
evidence. Every native log/database entry must provide a project-relative path
and SHA-256; missing or changed artifacts are rejected and later changes
invalidate the bound node. Every implementation, policy, manifest, or log
digest asserted by a claim must match one of those artifact digests. Evidence
revision must match the bootstrap project
revision when that revision is available. Planner-default prerequisites are
checked at ingestion too. A structurally and semantically valid report is
retained as FAIL while a required current-revision prerequisite is missing or
not VALID/WAIVED; rerun the producer after satisfying the prerequisite. Never
promote the old FAIL record automatically.

Schemas and starting examples are in this directory:

- `stimulus-capability-evidence.schema.json` / `stimulus-capability-evidence.example.json`
- `checking-evidence.schema.json` / `checking-evidence.example.json`
- `coverage-evidence.schema.json` / `coverage-evidence.example.json`
- `testcase-evidence.schema.json` / `testcase-evidence.example.json`
- `regression-evidence.schema.json` / `regression-evidence.example.json`

Standard claims:

| Workstream | Claims |
| --- | --- |
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
  "artifacts": [{"path": "project/relative/path", "sha256": "<sha256>"}],
  "result": {"...": "claim-specific facts"}
}
```

Compilation artifacts normally prove capability readiness only. Runtime
closure requires observations such as accepted stimulus, non-zero checker
engagement, assertion attempts without failures or vacuity, targeted test
PASS, coverage item disposition, and regression execution/triage. A waveform
may corroborate a result but is not a default substitute for typed evidence.

`fresh-evidence` reports provide only `result.snapshot_revision`; the engine
derives required closure-evidence nodes from the current Planner graph and
stores the resulting node/evidence-digest set. Do not let a producer choose a
smaller required-node list. Regression execution records raw failures as valid
execution facts; triage closes them only when every failed test/seed has a
matching same-seed rerun verdict/log digest and disposition. An accepted known
failure must reference a Human `WAIVE` review stored in the project database.
