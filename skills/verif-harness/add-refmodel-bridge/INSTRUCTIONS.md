# add-refmodel-bridge — generate a backend adapter scaffold

Generate a structural adapter for a reviewed Syscan HDL shell or DPI-C API.
The mode does not decide compare ordering, masking, unsupported-configuration
policy, residual handling, or numeric semantics.

## Procedure

1. Read the local and upstream reference-model specifications, architecture,
   coding guide, DUT interface, and existing scoreboard/wrapper code.
2. Copy `bridge-spec.example.json` and select `backend: syscan` or
   `backend: dpi-c`.
3. Record every port or DPI function exactly as exposed by the approved
   backend. For Syscan, declare `disabled_assignments` for wrapper outputs so
   the guard-off build is deterministic while still warning that compare is
   unavailable. Keep semantic decisions in the reference-model spec or open
   questions.
4. Generate:

   ```bash
   python3 <skill-dir>/add-refmodel-bridge/scripts/generate_bridge.py \
     --spec <bridge-spec.json> --out <bridge.sv>
   ```

5. Integrate the generated adapter without moving compare responsibility
   across architecture layers.
6. Add a positive supported case and a negative unsupported/no-compare case.
7. Require end-of-test proof that the Golden engaged; zero mismatches without
   engagement is not PASS.

The generated Syscan wrapper only instantiates the declared HDL shell. The DPI
package only declares reviewed imports. Both deliberately leave transaction
alignment and value comparison to project-specific implementation.
