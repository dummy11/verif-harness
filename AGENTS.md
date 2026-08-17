# Repository instructions

## Scope

This repository contains public, reusable verification infrastructure.

- Keep `examples/*/rtl/` small, license-free, and self-contained.
- Never import proprietary DUT RTL, specifications, logs, vectors, URLs,
  license configuration, or scheduler settings.
- Keep harness, interfaces, assertions, bind, UVM, and test responsibilities
  layered as described in `ARCHITECTURE.md`.
- Treat generated files as review candidates, not approved semantics.
- Do not claim simulator support without reproducible evidence.
- Keep optional xverif source under Git-ignored `.deps/`; never vendor it or
  publish proprietary EDA dependencies. Treat its lock changes as reviewed
  dependency upgrades and preserve separate licensing/ownership.
- Keep optional WavePeek source and binaries under Git-ignored `.deps/`; pin
  source, Cargo.lock, license, and version, keep FSDB disabled by default, and
  preserve WavePeek's separate Apache-2.0 ownership and release boundary.
- Keep optional GitHub Spec Kit source and its Python environment under
  Git-ignored `.deps/`; pin its tag, full commit, and reviewed file hashes,
  and preserve separate MIT ownership. verif-harness remains the top-level
  control plane; Spec Kit owns specification artifacts, not verification
  evidence or Human approval.

## Required checks

Before committing, run:

```bash
make check
```

Before a public release candidate, run:

```bash
make release-check
```

Do not weaken the denylist or exclusion rules merely to make an audit pass.
