# change-control — audit post-baseline change declarations

Audit structured change requests and optionally reconcile them with Git changes
since a declared baseline. This mode records whether change-control evidence is
ready for Human review; it never approves a change request.

## Preconditions

- Read project `AGENTS.md`, governance workflow, frozen Human Decisions,
  roadmap, verification plan, and change-request policy.
- Read `../references/lifecycle-patterns.md` and
  `../references/implementation-patterns.md` completely.
- Identify the immutable Git baseline from existing approved evidence.

## Procedure

1. Copy `change-control.example.json` and list every post-baseline changed file
   under an approved/rejected/open change request.
2. Record verification impact for tests, coverage, assertions, documentation,
   and regressions. Empty lists are explicit and reviewable.
3. Run:

   ```bash
   python3 scripts/audit_change_control.py --contract changes.json \
     --project-root . --audit-git --json --out artifacts/change-control.json
   ```

4. Resolve undeclared Git changes, open requests, incomplete approval metadata,
   and missing impact evidence.
5. Human reviewers decide each request through the project governance process.

## Boundaries

- The tool is read-only except for its optional report output.
- `approved` means an existing Human decision is recorded in the input; the
  tool does not create that decision.
- Frozen decisions, RTL, plans, and CI are never modified.
