# freeze-baseline — build a hash-anchored verification freeze candidate

Build a deterministic manifest for a clean Git commit after checking required
evidence files and their machine-readable states. This mode creates a freeze
candidate; it does not approve, tag, push, publish, or alter source files.

## Preconditions

- Read project `AGENTS.md`, governance workflow, roadmap exit criteria,
  verification/sign-off plans, stage packet, open questions, change requests,
  and all required evidence.
- Read `../references/lifecycle-patterns.md` and
  `../references/implementation-patterns.md` completely.
- Run regression, performance, traceability, coverage, assertion, sign-off, and
  change-control audits first.
- Use a clean Git worktree. Put the candidate manifest outside the repository
  until Human review is complete.

## Procedure

1. Copy `freeze-contract.example.json`. List each required evidence file,
   machine-readable state check, baselined file, tool version, Git baseline,
   and RTL policy explicitly.
2. Run:

   ```bash
   python3 scripts/build_freeze_manifest.py --project-root . \
     --contract freeze-contract.json --out /tmp/freeze-candidate.json
   ```

3. Review the commit, branch, RTL diff, state checks, and every SHA-256 entry.
4. If an existing Human approval record is supplied, the manifest may report
   `APPROVED_RECORDED`; this only reflects the supplied evidence.
5. After Human approval, copy the reviewed manifest into the project and use
   the normal authorized release/tag workflow.

## Boundaries

- Dirty worktrees, failed state checks, missing evidence, unsafe paths, or
  disallowed RTL changes block manifest creation.
- The tool never changes Git state, creates a tag, pushes, approves a gate, or
  declares confidential material publishable.
- Hashes prove file identity, not semantic correctness.
