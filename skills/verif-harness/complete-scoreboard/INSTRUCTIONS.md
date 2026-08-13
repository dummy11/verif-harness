# complete-scoreboard — explicit FIFO-aligned comparison behavior

Generate a concrete UVM scoreboard from a reviewed comparison contract. The
mode supports FIFO alignment and exact, masked, or absolute-tolerance field
comparisons. More complex ordering and matching policies require a separate
project design decision.

## Preconditions

- Read project `AGENTS.md`, roadmap stage, verification plan, architecture,
  reference-model specification, testcase list, and coding guide.
- Read `../references/implementation-patterns.md` completely.
- Resolve transaction alignment, masking, numeric interpretation, tolerance,
  reset flushing, and end-of-test policy with Human review.

## Procedure

1. Copy `scoreboard-contract.example.json` and provide exact reviewed
   transaction expressions and plan references.
2. Run:

   ```bash
   python3 scripts/generate_scoreboard.py --spec scoreboard-contract.json \
     --out sim/testbench/env/demo_scoreboard.svh
   ```

3. Connect the two analysis FIFOs in the environment.
4. Compile and run directed mismatch, residual, no-compare, and reset tests.
5. Update reference-model, feature, testcase, and coverage documentation.

## Boundaries

- Only FIFO alignment is generated.
- Exact comparison uses four-state case inequality. Mask and tolerance values
  come only from the contract.
- No comparison policy is inferred from field names or widths.
- Existing output is never overwritten.
