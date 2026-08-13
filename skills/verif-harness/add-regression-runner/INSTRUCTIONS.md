# add-regression-runner — isolated deterministic regression infrastructure

Add a simulator-neutral launcher and a result-contract collector. This mode
generates infrastructure; it does not run EDA simulations unless the user asks.

## Preconditions

- Stage 1 runnable TB and a base test/report-phase result banner exist.
- Read project `AGENTS.md`, roadmap, verification plan, testcase list,
  architecture, coding guide, and the existing regression Makefile/scripts.
- Read `../references/regression-patterns.md` completely.

## Required project contract

Each completed test must emit exactly one banner:

```text
<RESULT_PREFIX> <uvm_test_name> : PASSED|FAILED
  (UVM_ERROR=<n>  UVM_FATAL=<n>)
```

When a Golden model is enabled, emit:

```text
SUMMARY: cfg_events=<n> supported_seen=<0|1> mismatch_lanes=<n> residual_beats=<n>
```

If a project uses a different stable contract, pass `--result-regex` to the
collector and document the equivalent Golden engagement rule. Never classify
a missing end-of-test banner as PASS.

## Procedure

1. Inspect the existing regression directory. If it already provides isolated
   runs, seed capture, failed-only rerun, and false-green protection, stop and
   recommend reuse instead of replacement.
2. Copy these scripts additively into `<verif_root>/regress/`:
   - `scripts/run_regression.py`
   - `scripts/collect_results.py`
   - `scripts/test_regression_tools.py`
3. Render `templates/harness_regress.mk.tmpl` as
   `<verif_root>/regress/harness_regress.mk`. Replace:
   - `{{RESULT_PREFIX}}` with the uppercase project result token.
   - `{{DEFAULT_CASELIST}}` with the project-relative default caselist.
4. Include `harness_regress.mk` from the existing Makefile only when target
   names do not conflict. If they conflict, leave the include file unhooked and
   report the required manual merge.
5. Require the project to provide `SIM_CMD` as an argv-style command template
   containing `{test}` and `{seed}`. Do not use shell interpolation in the
   Python launcher.
6. Run:

   ```bash
   python3 -m unittest <verif_root>/regress/test_regression_tools.py
   ```

7. Run `python3 -m py_compile` on both scripts.
8. If Markdown was changed, run the project Markdown workflow check.

## Non-overwrite rule

Never replace a working project collector or Makefile automatically. When
files already exist, compare contracts and offer a migration plan. The ACC
collector contains project-specific performance and evidence behavior that a
generic scaffold must not erase.
