---
description: Execute reviewed RTL verification tasks through verif-harness capabilities
strategy: prepend
---

## verif-harness execution guard

Before implementing any task:

1. Treat verif-harness as the top-level control plane and dispatch the reviewed
   task to the matching `$verif-harness` mode.
2. Read the repository `AGENTS.md`, `.harness-config.json`, stage documents,
   architecture, coding rules, and affected plans before writing.
3. Never modify DUT RTL or bypass verif-harness component ownership.
4. Preserve explicit REQ/VF/TASK/MODE/ARTIFACT/EVIDENCE traceability.
5. Use xverif, WavePeek, or an EDA tool only for the bounded evidence contract
   authorized by the task.
6. Stop at unresolved specification semantics and Human authority boundaries.
7. Never convert generated output, tool PASS, or a review gate interaction into
   Human approval, waiver, sign-off, freeze, publication, commit, or push.
