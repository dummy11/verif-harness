# doctor — read-only project health audit

Run this mode before choosing a write mode or when project state is unclear.

## Preconditions

- Start at the project root.
- Do not require EDA tools.
- Do not modify project files.

## Procedure

1. Read `AGENTS.md` when present.
2. Run:

   ```bash
   python3 <skill-dir>/doctor/scripts/doctor.py --project-root .
   ```

3. If machine-readable output is useful, add `--json`.
4. Report every ERROR and WARNING. Do not silently repair findings.
5. Recommend the next explicit mode printed by the tool. Ask before invoking a
   write mode.

## Interpretation

- ERROR means the harness state is structurally unsafe or incomplete.
- WARNING means migration debt, ambiguous state, or a non-blocking gap.
- INFO records discovered state.
- A clean exit does not prove simulation correctness or Stage approval.

The audit intentionally reports legacy `.claude/` and `CLAUDE.md` artifacts
when Codex `AGENTS.md` is also present. Legacy files may remain for
compatibility, but they must not be the active source of truth.
