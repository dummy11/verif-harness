# coverage-closure — audit functional coverage freeze evidence

Audit a simulator-exported, tool-neutral coverage evidence file against an
explicit closure contract. The tool checks completeness, hits, exclusions,
waiver metadata, database identity, and reported totals. It does not parse
proprietary databases or approve exclusions.

## Preconditions

- Read project `AGENTS.md`, coverage plan, feature matrix, testcase list,
  regression evidence, and waiver policy.
- Read `../references/implementation-patterns.md` completely.
- Export evidence from the simulator database into the documented JSON schema;
  retain the native database and merge logs as artifacts.

## Procedure

1. Copy `coverage-evidence.example.json` and populate every planned item.
2. Run:

   ```bash
   python3 scripts/audit_coverage_closure.py \
     --evidence coverage-evidence.json --json \
     --out artifacts/coverage-closure.json
   ```

3. Resolve every blocker. Exclusions require an already approved waiver with
   identifier, reviewer, decision date, and rationale.
4. Human reviewers compare the JSON export with native tool reports before
   recording freeze approval.

## Boundaries

- `READY_FOR_HUMAN_FREEZE_REVIEW` is not approval.
- Zero-hit covered items, uncovered items, incomplete totals, duplicate IDs,
  or incomplete waiver metadata are blockers.
- The tool never edits coverage plans, creates waivers, or merges databases.
