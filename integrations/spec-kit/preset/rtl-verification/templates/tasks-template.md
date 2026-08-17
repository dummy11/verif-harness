
## RTL Verification Task Fields

Every task MUST carry the following reviewable fields:

```text
Task ID:
REQ / VF / TC / COV / ASRT IDs:
Stage:
verif-harness mode:
Input contract:
Owned output paths:
Validation command:
Expected evidence and retention path:
Human decision or gate (if any):
```

Separate specification, generation, deterministic validation, dynamic EDA
validation, audit, and Human gate work. No task may edit the DUT RTL or promote
a generated result to approval.
