# Verification Knowledge Model

Treat the Verification Knowledge Model as the typed verification knowledge
source. Keep its Human CLI surface read-only: `inspect [NODE]`, `trace NODE`,
and `impact NODE`.

Preferred trace chain:

```text
REQ -> VF -> DESIRED -> ACTION -> MODE -> ARTIFACT -> EVIDENCE -> REVIEW
```

For standard VENV/VSTIM/VCHK/VCOV/VCASE/VREG desired nodes use `evidence NODE FILE`;
use generic `prove NODE FILE` only when no typed contract is declared. Use
`changed PATH` and `waive NODE --reason ...` for changes and Human waivers.
Adapters and automation may use `record node|edge|change|waive` for advanced
facts, but standard Workstream evidence must still enter through `evidence` or
`reachability`; do not bypass its validator with low-level `record evidence`.
Every accepted structured write automatically
triggers the Verification Consistency Engine and Verification Closure Engine. Explicit relations
represent reviewed knowledge, inferred relations require confidence, and
runtime relations represent observed evidence. Never mark a desired state
`VALID` because an Agent said it completed. A waiver requires a named Human
reviewer and reason. Never edit `model.md` or Workstream projections as
authority.
