# coverage-closure — audit functional coverage freeze evidence

Audit a simulator-exported, tool-neutral coverage evidence file against an
explicit closure contract. The tool checks inventory completeness, exclusions,
waiver metadata, database identity, and reported totals. It does not parse
proprietary databases or approve exclusions.

## Preconditions

- Read project `AGENTS.md`, coverage plan, feature matrix, testcase list,
  regression evidence, and waiver policy.
- Read `../references/implementation-patterns.md` completely.
- Export evidence from the simulator database into the documented JSON schema;
  retain the native database and merge logs as artifacts.

## Procedure

1. Copy `coverage-evidence.example.json`. Keep the complete native-object universe in a
   tool-generated `CoverageObjectInventory/2`; report complete counts and list only
   excluded/uncovered holes. Bind the one merged database digest used by the report.
2. Run:

   ```bash
   python3 scripts/audit_coverage_closure.py \
     --evidence coverage-evidence.json \
     --inventory coverage-object-inventory.json --json \
     --out artifacts/coverage-closure.json
   ```

3. Resolve every blocker. If there are exclusions, the owner supplies and approves one
   exclusion file. Record that file-level approval once and make every excluded hole
   reference its identifier; do not create a separate waiver record per coverage object.
4. Human reviewers compare the JSON export with native tool reports before
   recording freeze approval.

## Boundaries

- `READY_FOR_HUMAN_FREEZE_REVIEW` is not approval.
- Uncovered objects, incomplete totals, holes outside the inventory, duplicate
  object keys, a changed exclusion file, or a missing file-level approval are blockers.
- The tool never edits coverage plans, creates waivers, or merges databases.
