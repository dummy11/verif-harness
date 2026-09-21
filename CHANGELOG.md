# Changelog

All notable changes follow Keep a Changelog conventions. Versions use Semantic
Versioning.

## [Unreleased]

### Added

- Added single-runtime Codex/Kimi subagent collaboration with revision-bound
  atomic claims, heartbeat leases, registered non-overlapping verification write scopes,
  Main-Agent-only Human interaction, and per-subagent Dashboard visibility.
- Added project-scoped explorer, worker, and reviewer profiles for Codex and Kimi.
- Protected control-plane/runtime metadata from declared subagent write scopes,
  superseded assignments when their Closure action changes, and preserved local
  runtime profiles by emitting managed updates as `.new` files.

### Changed

- Blocking `agent-question ask` now keeps a bounded runtime checkpoint by
  default, and the managed Kimi Main Agent profile prevents an open Dashboard
  question from being abandoned at an idle CLI prompt.
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
