# Coding style

## SystemVerilog

- Use `logic`, `always_ff`, and explicit port directions.
- Prefer one module, interface, package, or class per file.
- Keep names lowercase with underscores; suffix interfaces with `_if`.
- Avoid implicit nets, wildcard port connections, and hidden global macros.
- Comment why a tie-off or exception is valid.
- Keep test behavior outside harness modules.

## Python

- Support Python 3.9 or newer.
- Use `pathlib`, typed functions, deterministic output, and standard-library
  dependencies where practical.
- Validate inputs before writing and refuse partial overwrites.

## Documentation

State tested scope precisely. Keep Human decisions and unresolved assumptions
visible. Never paste private project evidence into public examples.
