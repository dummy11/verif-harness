# audit-traceability — read-only verification mapping audit

Use this mode after tests or plans change and before a stage gate.

## Preconditions

- `.harness-config.json` exists.
- The verification plan documents and TB tree exist.
- Read project `AGENTS.md` and the testcase, feature, coverage, and assertion
  plans before interpreting findings.

## Procedure

Run:

```bash
python3 <skill-dir>/audit-traceability/scripts/audit_traceability.py \
  --project-root .
```

Options:

- `--manifest <path>` selects a non-default caselist.
- `--json` emits machine-readable output.
- `--out <path>` writes the report instead of stdout.
- `--strict` returns nonzero for warnings as well as errors.

## Finding policy

- Duplicate manifest entries and manifest entries with no UVM test class are
  errors.
- Implemented tests absent from the default manifest are warnings because
  smoke-only, focused, or intentionally retired tests may exist.
- Test names documented without an implementation are warnings; planned tests
  are legitimate.
- Verification IDs are counted and mapped heuristically. Never infer semantic
  coverage from a filename or identifier match.

Do not edit plans, caselists, or SV files automatically. Present gaps to the
user and let the affected project workflow determine the fix.
