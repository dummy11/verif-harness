---
description: Execute reviewed RTL verification tasks through verif-harness capabilities
strategy: prepend
---

## verif-harness execution guard

Before implementing any task:

1. Treat verif-harness as the top-level control plane and dispatch the reviewed
   task to the matching runtime-native Skill mode: `$verif-harness` on Codex or
   `/skill:verif-harness` on Kimi Code.
2. Read the repository `AGENTS.md`, `.harness-config.json`, stage documents,
   architecture, coding rules, and affected plans before writing.
3. Never modify DUT RTL or bypass verif-harness component ownership.
4. Preserve explicit REQ/VF/TASK/MODE/ARTIFACT/EVIDENCE traceability.
5. Use xverif, WavePeek, or an EDA tool only for the bounded evidence contract
   authorized by the task.
6. Stop at unresolved specification semantics and Human authority boundaries.
7. Never convert generated output, tool PASS, or a review gate interaction into
   Human approval, waiver, sign-off, freeze, publication, commit, or push.
8. Dispatch every approved task to its named verif-harness mode exactly once.
   Do not require the user to repeat a mode manually after successful dispatch.
9. After dispatching a mode, verify every task-declared owned output and evidence
   path and run its approved validation command. Missing output or failed
   validation leaves the task incomplete and must be reported to convergence;
   an untracked duplicate manual call is not a valid repair.
10. For a new Stage 0 project, dispatch an approved
   `verif-harness mode: init` task exactly once. Do not tell the user to invoke
   `init` again after its outputs and validation pass. A direct manual call is
   only an explicitly recorded recovery or legacy-import path.
