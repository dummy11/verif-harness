# assertion-closure — audit assertion activation and failure evidence

Audit tool-neutral assertion evidence for compile, bind/elaboration, attempts,
failures, and vacuity. The tool consumes an explicit JSON export and never
claims assertion correctness from source presence alone.

## Preconditions

- Read project `AGENTS.md`, assertion plan, bind architecture, regression
  evidence, reset policy, and waiver policy.
- Read `../references/implementation-patterns.md` completely.
- Retain native compile/elaboration/assertion reports as immutable artifacts.

## Procedure

1. Copy `assertion-evidence.example.json` and populate it from the simulator
   reports for every planned assertion.
2. Run:

   ```bash
   python3 scripts/audit_assertion_closure.py \
     --evidence assertion-evidence.json --json \
     --out artifacts/assertion-closure.json
   ```

3. Resolve assertions that did not compile, bind, or attempt.
4. Treat failures and vacuous results as blockers unless an already approved
   waiver is recorded with complete metadata.
5. Human reviewers compare the export to native evidence before freeze.

## Boundaries

- `READY_FOR_HUMAN_FREEZE_REVIEW` is not approval.
- Source presence, compilation alone, or zero failures with zero attempts is
  never assertion closure.
- The tool never authors assertions, changes bind scope, or creates waivers.
