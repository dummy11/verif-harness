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
   and one or more compile/simulation/regression scripts. Ask for missing mandatory
   fields together; present optional inputs as skippable choices rather than blockers.
   Values explicitly supplied by the user in this conversation count as answers.
   Do not discover candidate directories, guess a top module, or silently use
   existing configuration as the user's answer. For refresh, read current values
   only so they can be shown as defaults; ask the Human to confirm, replace, or
   remove them. Reconfirm `rtl root`, `dut top`, `dut top file`, optional `spec`,
   optional testbench/reference-model/script inputs, and the verification output
   root. Do not run bootstrap until all three mandatory fields have been provided.
   Omitting any optional input must not block setup.
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
6. Continue with `plan WORKSTREAM`; recording an existing reference-model path does
   not decide that the project will use it. Bootstrap must not decide coverage,
   tests, interfaces, checking strategy, acceptance criteria, or Human Decisions.

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
