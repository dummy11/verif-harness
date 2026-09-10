# bootstrap mode

Use this once when onboarding a project, and later with `--refresh` only to
refresh non-semantic inventory/capabilities.

1. Use the workspace selected by setup and read its repository instructions.
2. Require the user to explicitly provide DUT identity in the live conversation:
   `rtl root`, `dut top`, and `dut top file` are mandatory; `spec` (RTL
   specification file or directory) is optional. Ask for missing fields together.
   Values explicitly supplied by the user in this conversation count as answers.
   Do not discover candidate directories, guess a top module, or silently use
   existing configuration as the user's answer. Do not run bootstrap until all
   three mandatory fields have been provided. Omitting spec must not block setup.
3. Validate only the supplied paths read-only. If a path is missing, ambiguous,
   or unsupported by the CLI, explain the issue and ask the user to correct it;
   do not search for substitutes or copy inputs into the public repository.
   Run the Skill launcher with `bootstrap --rtl-root PATH --dut-top NAME
   --dut-top-file PATH`. If spec was supplied, pass its exact path through the
   existing `--docs-root PATH` input; do not infer another documentation root.
4. Review `.verif-harness/project.json` and `inventory.json`.
5. Continue with `plan WORKSTREAM`; bootstrap must not decide coverage, tests, interfaces,
   reference models, acceptance criteria, or Human Decisions.

When DUT identity is complete, bootstrap also writes the lower-level capability
projection `.harness-config.json` without overwriting an existing file.
Never overwrite existing state implicitly. Use `--refresh` only after checking
that the project identity and root are unchanged.

All RTL and RTL specifications are read-only inputs, including files outside
the declared top file. Never edit, create, overwrite, delete, rename, format,
or apply generated changes to them, directly or through tools/subprocesses.
Report input defects and let the user correct them. Verification outputs must
be kept separate from RTL and RTL specification inputs.
