
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

After the execution gate approves the task set, `speckit.implement` MUST
dispatch every task to its declared `verif-harness mode` exactly once. The
successful path never asks the user to repeat those mode calls manually. Each
dispatch remains incomplete until all declared owned outputs and evidence paths
exist and the approved validation command passes. Recovery reruns must be
explicitly recorded against the same task and preserve prior evidence.

For a new Stage 0 project without `.harness-config.json`, the task set MUST
contain exactly one task with `verif-harness mode: init`. Its owned outputs MUST
include the harness configuration, project instructions, harness assets,
derived governance views, Stage 0 review packet, and required directory
scaffold. After execution authorization, `speckit.implement` dispatches this
task automatically; a second manual `init` call is not part of the successful
path. Missing outputs or failed validation keep the task incomplete.
