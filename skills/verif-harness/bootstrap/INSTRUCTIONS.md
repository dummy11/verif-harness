# bootstrap mode

Use this once when onboarding a project, and later with `--refresh` only to
refresh non-semantic inventory/capabilities.

1. Confirm the workspace root and repository instructions.
2. Identify candidate RTL and documentation roots without reading proprietary
   content into the public verif-harness repository.
3. Run `$verif-harness bootstrap [--rtl-root PATH] [--docs-root PATH]
   [--verif-root PATH] [--dut-top NAME --dut-top-file PATH]`.
4. Review `.verif-harness/project.json` and `inventory.json`.
5. Continue with `plan WORKSTREAM`; bootstrap must not decide coverage, tests, interfaces,
   reference models, acceptance criteria, or Human Decisions.

When DUT identity is complete, bootstrap also writes the lower-level capability
projection `.harness-config.json` without overwriting an existing file.
Never overwrite existing state implicitly. Use `--refresh` only after checking
that the project identity and root are unchanged.
