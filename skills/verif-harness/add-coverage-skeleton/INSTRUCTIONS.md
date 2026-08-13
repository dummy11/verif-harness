# add-coverage-skeleton — generate coverage code from an explicit contract

Generate compile-oriented coverage code from a reviewed JSON implementation
contract. Do not infer coverpoint expressions or bin boundaries from prose.

## Procedure

1. Read the coverage plan, feature matrix, testcase list, architecture, and
   coding guide.
2. Copy `coverage-spec.example.json` to the project verification docs area and
   fill every `plan_refs`, field type, expression, bin, and cross axis.
3. Have the contract reviewed when it resolves an ambiguity in the plan.
4. Generate additively:

   ```bash
   python3 <skill-dir>/add-coverage-skeleton/scripts/generate_coverage.py \
     --spec <coverage-spec.json> --out <collector-fragment.svh>
   ```

5. Integrate the generated class or adapt the fragment to the architecture.
6. Compile and run a focused sample test. Confirm denominator and illegal-bin
   behavior in the coverage report.
7. Update the coverage plan when implementation names or bins differ.

The generator refuses unknown keys, unsafe identifiers, missing plan
references, duplicate names, and output overwrite. Raw bin clauses are copied
from the reviewed contract; they are not generated from guesses.
