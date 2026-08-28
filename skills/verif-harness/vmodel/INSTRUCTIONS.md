# VModel mode

Treat VModel as the typed verification knowledge source. Keep its Human CLI
surface read-only: `model show`, `model trace`, and `model impact`.

Preferred trace chain:

```text
REQ -> VF -> DESIRED -> ACTION -> MODE -> ARTIFACT -> EVIDENCE -> REVIEW
```

Record changes through `record node|edge|status|evidence|change|waive`; every
structured write automatically triggers VCheck/VClosure. Explicit relations
represent reviewed knowledge, inferred relations require confidence, and
runtime relations represent observed evidence. Never mark a desired state
`VALID` because an Agent said it completed. A waiver requires a named Human
reviewer and reason. Never edit `model.md` or Workstream projections as
authority.
