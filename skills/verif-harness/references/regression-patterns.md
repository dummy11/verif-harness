# Regression patterns

## Contents

1. Result contract
2. Isolation and seeds
3. Golden engagement
4. Failed-only rerun
5. Evidence boundaries
6. Integration rules

## 1. Result contract

Judge completion from a test-owned end-of-test banner, not from simulator exit
code or arbitrary log text. A missing banner means the test did not prove
completion and is `CRASH` or `NOLOG`, never PASS.

Keep verdicts distinct:

- `PASS`: completed and required Golden comparison engaged with zero mismatch
  and residual.
- `PASS-LIVE`: completed without a required Golden model; proves liveness only.
- `NO-COMPARE`: completed but a required Golden model did not engage.
- `FAIL`: completed with test/UVM/Golden failure.
- `CRASH`: log exists but no completion banner.
- `NOLOG`: no log exists.

## 2. Isolation and seeds

Give every test its own run directory. Simulator side effects such as keys,
waves, coverage shards, and temporary files must not collide across parallel
jobs.

Choose one positive 31-bit batch seed and pass it explicitly to every test in
the batch. Record it before launching jobs. Do not label a batch reproducible
when individual tests silently choose random seeds.

Pass simulator commands as an argv array. Do not concatenate an untrusted shell
string. Persist the resolved argv for each job.

## 3. Golden engagement

Golden presence is insufficient. Require an end-of-test summary proving that a
supported configuration was actually compared. A zero mismatch count with
`supported_seen=0` is vacuous and must fail a required-Golden gate.

Keep value comparison, residual-output checking, and protocol/UVM error counts
visible in the report.

## 4. Failed-only rerun

Publish rerun inputs only from the final authoritative collector pass:

- `failed.caselist`: every non-acceptable verdict, one test per line.
- `seed.txt`: the original batch seed.

Rerun into a separate directory with the same seed. Preserve the source report
and logs. An empty failed caselist is a successful no-op.

## 5. Evidence boundaries

A generated report is evidence only for logs it actually parsed. Record:

- commit when available;
- batch seed;
- manifest path and unique test count;
- result-contract version;
- whether Golden was required;
- artifact availability limitations.

Human-confirmed screenshots or summaries may close a project criterion when
the Human reviewer accepts them, but label them as Human-confirmed and do not
invent missing per-test fields.

## 6. Integration rules

Keep the launcher simulator-neutral. Put VCS, Xcelium, Questa, LSF, Slurm, or
site-specific command construction in the project Makefile or wrapper.

Do not overwrite a mature collector with the generic scaffold. Compare
contracts and migrate additively. Keep coverage merging separate from the
functional verdict unless the project's sign-off workflow explicitly combines
them.
