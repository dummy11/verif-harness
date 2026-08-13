# add-performance-gate

Evaluate machine-readable performance records against an explicitly reviewed
JSON contract. This mode never invents latency, utilization, cadence, or bubble
formulas from signal names.

## Preconditions

1. Read the project `AGENTS.md`, workflow, roadmap, verification plan, and the
   approved performance or coverage plan.
2. Confirm the producer log format and every predicate with the project owner.
3. Copy `performance-contract.example.json` and replace all example fields with
   project-specific, reviewed definitions.

## Contract and record format

- Each record is one log line beginning with the configured `marker`.
- The remaining payload is `key=value` tokens separated by `|`.
- `required_fields` defines record completeness; `key_fields` defines identity.
- Operands are constants, fields, or ratios. Division by zero is a failure.
- Supported operators are `eq`, `ne`, `lt`, `le`, `gt`, and `ge`.
- `completeness` rules verify that required values were observed across all
  records; they do not fabricate missing cases.

## Procedure

1. Validate the reviewed contract as JSON.
2. Run `scripts/evaluate_performance.py --contract <json> --log <log>...`.
3. Archive the Markdown report and optional JSON output with the same commit,
   seed, simulator, and case-manifest evidence as the source logs.
4. Treat exit status 1, malformed records, duplicate identities, missing
   completeness values, or predicate failures as a gate failure.

## Safety boundary

This mode evaluates declared arithmetic only. It does not decide which metrics
matter, set thresholds, approve waivers, infer expected counts, or declare a
stage complete.
