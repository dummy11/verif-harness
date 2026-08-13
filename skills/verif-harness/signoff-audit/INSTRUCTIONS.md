# signoff-audit — read-only final verification closure audit

Use before requesting final Human sign-off or to verify that an approved packet
is internally complete. This mode audits recorded repository state; it does not
validate unavailable EDA artifacts and cannot approve the project.

## Procedure

Run:

```bash
python3 <skill-dir>/signoff-audit/scripts/audit_signoff.py \
  --project-root . --stage <N>
```

Options:

- `--packet <path>` selects a nonstandard sign-off packet.
- `--manifest <path>` selects the authoritative regression manifest.
- `--json` emits machine-readable output.
- `--out <path>` writes the report.
- `--strict` treats warnings as a failing audit.

Review findings against raw regression, coverage, assertion, CI, performance,
change-request, and waiver evidence. Label Human-confirmed evidence when raw
artifacts are unavailable. Run `audit-traceability` and `doctor` alongside this
mode.

Statuses mean:

- `INCOMPLETE`: structural blockers remain.
- `READY_FOR_HUMAN_REVIEW`: required structure is present but no approval is
  recorded.
- `APPROVED_RECORDED`: the packet records a Human approval. This reports the
  document state only and is not a new approval by the skill.
