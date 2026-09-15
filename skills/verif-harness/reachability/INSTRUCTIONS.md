# reachability — VSTIM-owned scenario evidence

Use `verif-harness reachability NODE REPORT.json` after a reviewed VSTIM probe
has exported `StimulusReachabilityEvidence/1`. The probe must observe generated,
driven, accepted, and scenario-hit counts at the DUT input acceptance boundary.
The machine-readable contract is `stimulus-reachability.schema.json`; start
from `stimulus-reachability.example.json`.

This command derives PASS/FAIL from the report; callers do not supply a verdict.
It accepts only `producer.kind=vstim-probe`. Functional coverage, SVA cover
properties, waveforms, and checker results may corroborate the result, but none
is the sole authority for VSTIM closure. This keeps VSTIM independent from the
completion of VCOV or VCHK.

The report records its project revision and every native probe artifact as
`{path, sha256}`. Registration verifies project-local existence and digest;
artifact changes later invalidate the VSTIM target.

For the standard `reachability-evidence` and `determinism-evidence` desired
nodes, the claim is inferred. For a project-specific VSTIM node, pass
`--claim reachability` or `--claim determinism` explicitly. Determinism requires
at least two clean runs with identical test, seed, configuration digest, and
stimulus digest for every required scenario.

If a goal truly needs another capability, record a node-scoped dependency:

```text
verif-harness record dependency DEPENDENT_NODE PREREQUISITE_NODE
```

`DEPENDS_ON` is stored as dependent → prerequisite. Closure waits only for the
named prerequisite and rejects dependency cycles; it never waits for the whole
prerequisite Workstream.
