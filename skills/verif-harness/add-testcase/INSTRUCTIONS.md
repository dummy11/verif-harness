# add-testcase — add one compile-safe test and virtual sequence

Use after a testcase is approved in the testcase plan. This mode creates one
test/vseq pair, package registrations, and a CaseManifest bound to a
testbench-owned SubmitProfileRef. It never promotes the test into a regression
caselist; the testbench submit flow owns batch and caselist generation.

## Preconditions

- Read project `AGENTS.md`, roadmap, verification plan, testcase list,
  feature matrix, architecture, and coding guide.
- Confirm the testcase ID, mapped feature IDs, expected result, and owning
  stage are documented.
- Identify an existing base test and base virtual sequence with the intended
  semantics.
- Obtain a `SubmitProfileRef/1` emitted by the testbench submit flow. The ref
  records only the project-relative submit-file path and digests; verif-harness
  never copies or interprets site-specific commands, queues, licenses, or URLs.

## Procedure

Run a dry-run first:

```bash
python3 <skill-dir>/add-testcase/scripts/add_testcase.py \
  --test-name <prefix>_<name>_test \
  --base-test <prefix>_base_test --base-vseq <prefix>_job_vseq_base \
  --submit-profile-ref <verif_root>/regress/submit-profile-ref.json \
  --traceability case-traceability.json \
  --dry-run
```

Then rerun without `--dry-run`. The script:

- creates `<verif_root>/testbench/test/<test-name>.svh`;
- creates `<verif_root>/testbench/env/vseq/<vseq-name>.svh`;
- inserts vseq/test includes before the corresponding package `endpackage`;
- creates a `CaseManifest/2` under `<verif_root>/regress/cases/` by default;
- refuses existing files, duplicate includes, unsafe identifiers, and
  ambiguous package discovery.

Select `--entry-kind testcase|sequence`. A sequence entry records the generated
test as its launcher. The manifest binds the entry and source digests to the
SubmitProfileRef. Caselist generation remains a separate, testbench-owned
promotion decision after dynamic evidence is available.

Provide `--traceability` with the `CaseTraceability/1` object documented in
`evidence/case-manifest.schema.json`. Reference the existing testcase-list row,
verification points and concrete source files, SHA-256 values, version labels
and locations. Expected results name their basis source IDs and checking method.
The generator verifies all referenced files before writing any output.
`rtl-derived-unconfirmed` remains an explicitly marked draft and cannot satisfy
VCASE acceptance. `confirmed` references an existing node question; only the
control plane checks the actual owner answer, not the generator.

## After generation

1. Replace the vseq TODO body with approved stimulus.
2. Add traceability comments with testcase and feature IDs.
3. Run compile, focused simulation, Golden, assertion, and coverage checks as
   required by the stage.
4. Update testcase/feature/coverage/assertion documents when behavior changes.
5. Run the Markdown workflow after documentation edits.

Generated code is a compile-safe control skeleton, not proof that stimulus,
checking, or coverage semantics are complete.
