# Changelog

All notable changes follow Keep a Changelog conventions. Versions use Semantic
Versioning.

## [Unreleased]

### Changed

- Rebuilt the control plane around VPlan, VModel, VCheck, VClosure, and VReason.
- Replaced frozen task execution and background workflow workers with a live
  Agent conversation plus short-lived deterministic commands.
- Added a typed SQLite project model, readable projections, re-entrant
  Workstream revisions, Human review records, evidence provenance, causal
  invalidation, immutable baselines, and globally ranked closure actions.
- Kept xverif, WavePeek, generators, regressions, and audits as lower-level
  capabilities with explicit authority boundaries.

## [0.1.0] - 2026-08-13

### Added

- Core harness architecture and compile-order contract.
- Additive DUT integration templates and standalone `simple_fifo` example.
- Simulator-independent structure, test, and public-release checks.
- GitHub CI, Pages documentation, issue templates, and release automation.
