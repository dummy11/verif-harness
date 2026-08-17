
## verif-harness RTL Verification Principles

### DUT immutability

The configured DUT RTL is an external, read-only asset. Specifications, plans,
tasks, generated verification code, and tool invocations MUST NOT modify it.

### One specification authority

`specs/` is the sole editable source of verification requirements. Generated
documentation views, evidence indexes, reports, and review packets MUST link
back to it and MUST NOT become competing specification authorities.

### Traceable execution

Every executable task MUST identify its requirement, verification feature,
stage, verif-harness mode, expected artifact, evidence contract, and owner.
The canonical chain is `REQ -> VF -> PLAN -> TASK -> MODE -> ARTIFACT ->
EVIDENCE -> GATE`.

### Evidence and authority separation

Spec Kit and verif-harness command success is not functional verification
evidence. xverif, WavePeek, simulators, coverage tools, and assertion tools
produce bounded evidence, not approval. Human Decisions, waivers, stage gates,
sign-off, freeze, publication safety, and ambiguous specification semantics
remain Human authority.

### Frozen baseline control

Approved Human Decisions and Approval Decisions MUST remain immutable without
an approved change request. An existing approved project imported into Spec Kit
MUST be represented as an immutable baseline and MUST NOT be rewritten as if it
had originally been developed through Spec Kit.
