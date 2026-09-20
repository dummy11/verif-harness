# bootstrap mode

Use this once when onboarding a project. A later Human request containing only
`bootstrap --refresh` reopens the same conversational configuration flow; it is
not permission to silently reuse the old paths.
The low-level CLI also fails closed: bare `bootstrap --refresh` returns a
`BootstrapReconfiguration/1` `ACTION_REQUIRED` payload containing current values
and questions, and does not write project state.

1. Use the workspace selected by setup and read its repository instructions.
2. Require the user to explicitly provide DUT identity in the live conversation:
   `rtl root`, `dut top`, and `dut top file` are mandatory. The following inputs
   are independent and optional: `spec` (RTL specification file or directory),
   one existing `testbench` directory, one reference/golden model file or directory,
   and one or more compile/simulation/regression scripts. Run the conversation in
   this fixed order: (1) `rtl root`, (2) `dut top`, (3) `dut top file`,
   (4) verification output root, (5) optional `spec`, (6) optional `testbench`,
   (7) optional reference/golden model, and (8) optional verification scripts.
   Ask exactly one unanswered field per Agent turn. Wait for the Human's answer,
   validate that field read-only, and remain on the same field if correction is
   required; only then ask the next field. Never batch several unanswered fields
   into one prompt. For every optional field, require an explicit supplied value
   or an explicit `skip`/`none`; silence does not mean omission. Values explicitly
   supplied by the user in this conversation count as answers and must not be
   asked twice.
   Do not discover candidate directories, guess a top module, or silently use
   existing configuration as the user's answer. For refresh, read current values
   only so each one can be shown as the default when its turn arrives; ask the
   Human to keep, replace, or remove that one value before advancing. Reconfirm
   all eight fields in the same order. After the last answer, show one consolidated
   summary of all resolved values and ask for final confirmation. Invoke the
   low-level CLI only after that confirmation. Do not run bootstrap until all
   three mandatory fields have been provided. Explicitly skipping optional inputs
   must not block setup.
3. Validate only the supplied paths read-only. If a path is missing, ambiguous,
   or unsupported by the CLI, explain the issue and ask the user to correct it;
   do not search for substitutes or copy inputs into the public repository.
   RTL roots, the top file, and optional specification inputs may be outside the
   project root when explicitly supplied. The top file must belong to one of the
   declared RTL roots. Keep external paths as read-only absolute input identities;
   Existing testbench, reference-model, and script paths may also be outside the
   project when explicitly supplied. Bootstrap may inventory them read-only but
   must not execute, edit, copy, or treat them as integrated verification evidence.
   All generated verification output and control state remain inside the project.
   Run the Skill launcher with `bootstrap --refresh --rtl-root PATH --dut-top NAME
   --dut-top-file PATH --verif-root PATH` for refresh. If spec was supplied, pass
   its exact path through `--docs-root PATH`; if the Human explicitly removes the
   previous optional spec, pass `--clear-docs-root`. Use `--testbench-root PATH`,
   `--reference-model PATH`, and repeatable `--verification-script PATH` only for
   paths the Human supplied. Use the matching `--clear-*` option when the Human
   explicitly removes a previous value. Do not infer another path or ask for
   separate testcase, assertion, coverage, or UVM paths inside the testbench.
4. Create or refresh the marked verif-harness managed block in the project-root
   `AGENTS.md`. Preserve all content outside the markers. The block records DUT
   identity, read-only input boundaries, the governance-state source,
   Human/Agent/Engine authority, and a fail-closed route to VDOC while document
   contracts are pending. Engineering semantics remain in project VDOC Markdown.
5. Review `.verif-harness/project.json`, `inventory.json`, and the generated
   `AGENTS.md` block.
6. For a live Human/Agent bootstrap, invoke the low-level CLI with `--dashboard`.
   This guarantees that the project Dashboard is started or reused in the background
   after bootstrap. Never add `--no-dashboard` unless the Human explicitly asked to
   disable the Dashboard in the current conversation. Running over SSH, on a headless
   server, or from a non-interactive Agent is not a reason to disable it. On SSH, do
   not try to open a remote browser; return the `access.command` and `access.url`
   from the CLI result. CI may omit both flags and use the CLI's automatic skip.
   Check the returned `dashboard.status`: only `STARTED` and `REUSED` mean the
   Dashboard is available. Report `SKIPPED`, `DISABLED`, `FAILED`, or
   `PORT_CONFLICT` truthfully and do not claim that the Dashboard is running.
   If it must be started or recovered later, use plain `verif-harness dashboard`;
   this invokes the same detached start-or-reuse action as bootstrap. Verify with
   `verif-harness dashboard --status`. Do not run a foreground Dashboard through
   a pipe such as `| head`, because closing the pipe stops the service.
7. Continue with `plan WORKSTREAM`; recording an existing reference-model path does
   not decide that the project will use it. Bootstrap must not decide coverage,
   tests, interfaces, checking strategy, acceptance criteria, or Human Decisions.
   After bootstrap has successfully created the control state and started the
   Dashboard, never leave a follow-up blocking prompt such as "start plan VDOC?"
   only in a native Agent terminal selector. If the Human's original request did
   not already authorize the next step, start a project-level Activity, register a
   project-level `agent-question`, and let the Human answer from either Dashboard
   or `verif-harness agent-question answer`; both entries share the same persisted
   question. Pre-bootstrap field collection remains in the current Agent conversation
   because the Dashboard and its project state do not exist yet.

When DUT identity is complete, initial bootstrap also writes the lower-level capability
projection `.harness-config.json`. Refresh synchronizes its bootstrap-managed
`project_name`, `rtl.*`, `verif.root`, `verif.docs_root`, and
`verification_inputs.*` fields with the newly confirmed manifest while preserving
optional project-owned sections and customized verification/governance subdirectory
names. VDOC later
refreshes the same managed `AGENTS.md` block with its actual document root and
document routes; it must not create a competing instruction file.
Never overwrite existing state implicitly. Refresh preserves Workstream, evidence,
review, and document-governance state; it changes only the confirmed project
identity/path projection and rebuilt inventory/capability information.

All RTL and RTL specifications are read-only inputs, including files outside
the declared top file. Never edit, create, overwrite, delete, rename, format,
or apply generated changes to them, directly or through tools/subprocesses.
Report input defects and let the user correct them. Verification outputs must
be kept separate from RTL and RTL specification inputs.
