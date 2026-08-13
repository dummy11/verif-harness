# regression-triage — evidence-preserving failure grouping

Group failed regression results by reviewed log signatures and verify that a
same-seed rerun exists. Classification is a triage candidate, never an
automatic root-cause decision or waiver.

## Preconditions

- Read project `AGENTS.md`, regression procedure, result contract, and failure
  escalation policy.
- Read `../references/regression-patterns.md` and
  `../references/implementation-patterns.md` completely.
- Produce the primary `report.json` with `add-regression-runner` or an
  equivalent schema containing `test`, `verdict`, `seed`, and `log`.

## Procedure

1. Copy `triage-rules.example.json`. Replace patterns with reviewed,
   project-specific signatures and classifications.
2. Rerun failed cases with the original seed and collect a second report.
3. Run:

   ```bash
   python3 scripts/triage_regression.py --report runs/report.json \
     --rerun-report rerun/report.json --rules triage-rules.json \
     --out runs/triage.json
   ```

4. Review each candidate classification and retain links to both logs.
5. Escalate `UNCLASSIFIED` or missing/mismatched-seed reruns.

## Boundaries

- A regex match is only `candidate_classification`.
- The tool never changes test status, files a waiver, or edits source code.
- A missing log, unknown verdict, missing rerun, or seed mismatch blocks triage
  readiness.
