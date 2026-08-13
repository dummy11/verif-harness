# add-testcase — add one compile-safe test and virtual sequence

Use after a testcase is approved in the testcase plan. This mode creates one
test/vseq pair and package registrations, but never promotes the test into the
default passed regression.

## Preconditions

- Read project `AGENTS.md`, roadmap, verification plan, testcase list,
  feature matrix, architecture, and coding guide.
- Confirm the testcase ID, mapped feature IDs, expected result, and owning
  stage are documented.
- Identify an existing base test and base virtual sequence with the intended
  semantics.

## Procedure

Run a dry-run first:

```bash
python3 <skill-dir>/add-testcase/scripts/add_testcase.py \
  --project-root . --test-name <prefix>_<name>_test \
  --base-test <prefix>_base_test --base-vseq <prefix>_job_vseq_base \
  --dry-run
```

Then rerun without `--dry-run`. The script:

- creates `<verif_root>/testbench/test/<test-name>.svh`;
- creates `<verif_root>/testbench/env/vseq/<vseq-name>.svh`;
- inserts vseq/test includes before the corresponding package `endpackage`;
- refuses existing files, duplicate includes, unsafe identifiers, and
  ambiguous package discovery.

Use `--candidate-caselist <path>` only for a focused, explicitly selected
candidate list. Never pass the default regression caselist before dynamic PASS
and the project's add-only promotion review.

## After generation

1. Replace the vseq TODO body with approved stimulus.
2. Add traceability comments with testcase and feature IDs.
3. Run compile, focused simulation, Golden, assertion, and coverage checks as
   required by the stage.
4. Update testcase/feature/coverage/assertion documents when behavior changes.
5. Run the Markdown workflow after documentation edits.

Generated code is a compile-safe control skeleton, not proof that stimulus,
checking, or coverage semantics are complete.
