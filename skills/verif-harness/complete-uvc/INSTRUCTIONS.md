# complete-uvc — finish ready/valid driver and monitor behavior

Generate concrete UVM driver and monitor implementations from a reviewed
ready/valid protocol contract. This mode deliberately supports one protocol
shape; unsupported protocols remain an open design question.

## Preconditions

- Read project `AGENTS.md`, roadmap stage, verification plan, architecture,
  interface specification, testcase list, and all coding-guide rules.
- Read `../references/implementation-patterns.md` completely.
- Confirm the existing sequence item and interface modports match the contract.

## Procedure

1. Copy `uvc-contract.example.json` and set explicit class names, virtual
   interface types, clocking block names, handshake signals, payload mappings,
   timeout, and plan references.
2. Run:

   ```bash
   python3 scripts/generate_uvc.py --spec uvc-contract.json \
     --driver-out sim/testbench/uvc/demo_driver.svh \
     --monitor-out sim/testbench/uvc/demo_monitor.svh
   ```

3. Review reset ownership and phase-objection behavior in the surrounding
   agent. The generated classes do not own reset and do not raise objections.
4. Register the generated files additively, compile, and run protocol tests.
5. Update testcase/feature/coverage documentation required by project policy.

## Boundaries

- Only `ready_valid_source` is implemented. Do not coerce another protocol into
  this contract.
- Payload and handshake semantics are never inferred from signal names.
- Existing outputs are never overwritten; partial output is prevented.
- Generated code is a reviewed implementation candidate, not proof of protocol
  correctness.
