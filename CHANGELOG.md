# Changelog

All notable changes follow Keep a Changelog conventions. Versions use Semantic
Versioning.

## [Unreleased]

### Added

- Commit-pinned optional xverif dependency management with one-command setup,
  lock/schema validation, default discovery, provenance checks, real xbit CI
  smoke, and third-party notices without vendoring xverif source.

- Eight contract-driven lifecycle modes: simulator profiles, UVC completion,
  scoreboard completion, regression triage, coverage closure, assertion
  closure, change control, and freeze-baseline manifests.
- A 29-mode skill catalog and end-to-end Stage 0-to-freeze workflow.
- Unit tests for all new generators and evidence auditors.
- A Chinese skill documentation set with a 29-mode README, detailed
  Stage 0-to-freeze user guide, architecture, and troubleshooting guide.
- A 29th `xverif` mode with a schema-validated, fail-closed CLI adapter for the
  `BLANK2077/xverif` tool suite, native JSON/XOUT/text evidence, and Git/hash
  provenance.

## [0.1.0] - 2026-08-13

### Added

- Core harness architecture and compile-order contract.
- Additive DUT integration generator and templates.
- Standalone `simple_fifo` Verilator example.
- Simulator-independent structure, test, and public-release checks.
- GitHub CI, Pages documentation, issue templates, and release automation.
- Bundled `verif-harness` Codex skill with open-source readiness auditing.
