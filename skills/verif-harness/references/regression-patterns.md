# Regression patterns

## Contents

1. Result contract
2. Isolation and seeds
3. Golden engagement
4. Failed-only rerun
5. Evidence boundaries
6. Integration rules

## 1. Result contract

Require a test-owned end-of-test banner and a successful command receipt;
neither a banner nor an exit code alone proves PASS. Nonzero exits, timeouts,
and UVM errors/fatals reject a PASS banner. A missing banner means the test did not prove
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

Give every case/iteration its own run directory. Simulator side effects such as keys,
waves, coverage shards, and temporary files must not collide across parallel
jobs.

Use the approved seed mode and a positive total repeat count per case, default 1.
Random mode resolves a fresh positive seed for each iteration, unique per case
within the round; fixed mode reuses the specified seed. Record all resolved
seeds before launching jobs. The portable runner supports positive 31-bit seeds;
project adapters must check their own supported range. Never label a batch
reproducible when tests silently choose unrecorded seeds. Claim the output
directory exclusively so parallel invocations cannot overwrite each other.

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
- `failed-runs.json`: original resolved seeds and iteration identities for failures.
- `seed.txt`: a legacy fixed-seed summary, not the replay source for random/repeat runs.

Replay failed runs into a separate directory with the same seed and iteration.
Preserve the source report and logs; never replace initial failures or count
failure-analysis attempts as planned repeats. An empty failed caselist is a
successful no-op. A whole-group new round is a separate owner-confirmed action
on the result delivery node; it retains the approved plan but needs new evidence
and acceptance. Random new rounds resolve fresh seeds; exact replay does not.

## 5. Evidence boundaries

A generated report is evidence only for logs it actually parsed. Record:

- commit when available;
- seed mode, repeat count, and each resolved case/seed/iteration;
- manifest path and unique test count;
- result-contract version;
- whether Golden was required;
- artifact availability limitations.

For current VREG result delivery, the testbench adapter supplies
`RegressionBatchManifest/2` and `RegressionEvidence/3`, bound to the approved
group/profile/case versions and execution round. The generic portable launcher
manifest alone does not satisfy this control-plane evidence contract.

Human-confirmed screenshots or summaries may close a project criterion when
the Human reviewer accepts them, but label them as Human-confirmed and do not
invent missing per-test fields.

## 6. Integration rules

Keep the launcher simulator-neutral. Put VCS, Xcelium, Questa, LSF, Slurm, or
site-specific command construction in the testbench-owned submit file and its
project wrapper.

Do not overwrite a mature collector with the generic scaffold. Compare
contracts and migrate additively. Keep coverage merging separate from the
functional verdict unless the project's sign-off workflow explicitly combines
them.
