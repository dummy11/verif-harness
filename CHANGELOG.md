# Changelog

All notable changes follow Keep a Changelog conventions. Versions use Semantic
Versioning.

## [Unreleased]

### Added

- Pinned xverif MCP source/launcher validation and `xverif mcp` install,
  configure, status, and fail-closed runtime-probe commands, with Codex/Kimi
  installation and usage documentation that keeps host credentials outside the
  repository.

- Codex/Kimi Code runtime abstraction backed by Spec Kit integration state,
  deterministic bootstrap detection, runtime status/switch commands, dual
  workflow dispatch, and documented model/runtime switching procedures.

- A 31st `spec-kit` mode, pinned GitHub Spec Kit v0.16.4 dependency, RTL
  verification preset, Stage 0-to-5 workflow, specification authority model,
  and control/capability/evidence/Human boundary documentation.

- Commit-pinned optional WavePeek 2.2.3 source/release management, fail-closed
  waveform adapter, real schema smoke, CI, and VCD/FST-only public boundary.
- A 30th `wavepeek` Skill mode for deterministic, bounded waveform evidence.

- Commit-pinned optional xverif dependency management with one-command setup,
  lock/schema validation, default discovery, provenance checks, real xbit CI
  smoke, and third-party notices without vendoring xverif source.

- Eight contract-driven lifecycle modes: simulator profiles, UVC completion,
  scoreboard completion, regression triage, coverage closure, assertion
  closure, change control, and freeze-baseline manifests.
- A 31-mode skill catalog and end-to-end Stage 0-to-freeze workflow.
- Unit tests for all new generators and evidence auditors.
- A Chinese skill documentation set with a 31-mode README, detailed
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
