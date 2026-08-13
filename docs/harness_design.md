# Harness design

## Thin top

`tb_top` should elaborate the harness and start the verification framework. It
should not contain DUT port mapping, protocol behavior, test intent, or hidden
tie-offs.

## Structural ownership

The harness owns interface instances, clocks, resets, DUT construction,
tie-offs, adapters, bind targets, and virtual-interface publication. This
centralizes integration review and keeps reusable UVCs independent of DUT
hierarchy.

## Behavioral ownership

Drivers own pin-level stimulus. Monitors own observation and transaction
reconstruction. Scoreboards own comparisons. Coverage components own sampling.
Tests own scenario selection. Moving any of these into the harness creates a
layering violation.

## Review rules

- Map every DUT port explicitly.
- Preserve DUT port order where practical.
- Document every constant tie-off.
- Keep adapters deterministic and free of test policy.
- Bind assertions without modifying DUT RTL.
- Treat generated code as unapproved until reviewed against the specification.
