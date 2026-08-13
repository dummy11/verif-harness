# add-assertion-skeleton — generate checker and bind code from a contract

Generate assertion code only from an explicit, reviewed JSON contract. Never
translate natural-language timing requirements into properties silently.

## Procedure

1. Read the assertion plan, architecture, interface definitions, RTL behavior
   relevant to each property, and coding guide.
2. Copy `assertion-spec.example.json` into the verification docs area.
3. Fill checker ports, clock/reset, assertion IDs, property expressions,
   messages, and optional bind mapping. Record at least one `plan_ref` for each
   assertion.
4. Generate:

   ```bash
   python3 <skill-dir>/add-assertion-skeleton/scripts/generate_assertions.py \
     --spec <assertion-spec.json> --checker-out <checker.sv> \
     --bind-out <bind.sv>
   ```

5. Review sampling regions, reset disable conditions, vacuity, X behavior,
   parameter widths, and bind target hierarchy.
6. Compile and run positive and negative focused tests. Inspect assertion
   coverage as well as failure count.
7. Synchronize assertion IDs and final property text into the assertion plan.

The generator refuses output overwrite. Missing property text creates an
explicit TODO comment instead of an assertion, so a skeleton cannot
masquerade as implemented coverage.
