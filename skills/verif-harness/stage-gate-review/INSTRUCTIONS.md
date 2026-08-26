# stage-gate-review — generate a Draft gate packet

Use after Stage N implementation/evidence work and before Human approval to
enter Stage N+1.

## Preconditions

- Pass `<completed-stage>` explicitly.
- Read project `AGENTS.md`, workflow, roadmap, methodology, verification plan,
  and all verification planning documents.
- Treat run logs and machine-generated reports as stronger evidence than
  prose. Label user-confirmed evidence when raw artifacts are unavailable.

## Procedure

1. Generate a draft without overwriting an existing packet:

   ```bash
   python3 <skill-dir>/stage-gate-review/scripts/build_stage_gate.py \
     --completed-stage <N> \
     --out <docs-root>/stage<N>_gate_re_review.md
   ```

   Add `--final` when Stage N is the approved terminal stage and there is no
   Stage N+1 entry.

2. If the output already exists, stop and review it. Use `--force` only after
   the user approves replacing that exact draft.
3. Fill evidence fields from repository artifacts. Keep unavailable evidence
   explicit; do not infer PASS.
4. Run the repository Markdown workflow check and review its diff.
5. Present the Draft to the Human reviewer.

## Authority boundary

The generator must not:

- select a Provisional verdict;
- change a source plan or frozen section;
- close an open question;
- mark an exit criterion PASS;
- fill reviewer/date/approval fields;
- commit, push, or mutate CI.

Human decisions made during review must be applied separately under the
project's change-request and Markdown workflow rules.
