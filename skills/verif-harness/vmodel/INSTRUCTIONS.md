# Verification Knowledge Model

Treat the Verification Knowledge Model as the typed verification knowledge
source. Keep its Human CLI surface read-only: `inspect [NODE]`, `trace NODE`,
and `impact NODE`.

Preferred trace chain:

```text
REQ -> VF -> DESIRED -> ACTION -> MODE -> ARTIFACT -> EVIDENCE -> REVIEW
```

For common operations use `prove NODE FILE`, `changed PATH`, and `waive NODE
--reason ...`. Adapters and automation may use `record
node|edge|status|evidence|change|waive`; every structured write automatically
triggers the Verification Consistency Engine and Verification Closure Engine. Explicit relations
represent reviewed knowledge, inferred relations require confidence, and
runtime relations represent observed evidence. Never mark a desired state
`VALID` because an Agent said it completed. A waiver requires a named Human
reviewer and reason. Never edit `model.md` or Workstream projections as
authority.
