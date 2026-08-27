---
description: Monolithic implementation is disabled; use the persistent verif-harness task runner
---

# verif-harness task runner boundary

Do not execute `tasks.md` from this command. The Stage workflow deliberately does not invoke
`speckit.implement`: after `authorize-execution`, the deterministic verif-harness wrapper owns
task selection, state persistence, Agent dispatch, postcondition validation, and checkbox updates.

Use `status <run-id>` to inspect the exact `current_task_id`. If it is `BLOCKED`, obtain the named
Human answer or authority and run `resume <run-id> --answer "..."`. The wrapper retries only that
task and never replays tasks already marked `DONE`.

This replacement is fail-closed. A direct invocation has no workflow run identity and therefore
must not write project files, run EDA, dispatch a mode, or mark a task complete. Return to the
reviewed Stage workflow instead.
