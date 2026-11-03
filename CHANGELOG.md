# Changelog

All notable changes follow Keep a Changelog conventions. Versions use Semantic
Versioning.

## [Unreleased]

### Documentation

- Clarified the v3 install/bootstrap/restart/switch lifecycle, old setup project
  migration, published artifacts, shared installation paths, and release checks.

## [3.0.0] - 2026-11-02

### Added

- Versioned user/system installations with a standalone installer, wheel,
  source distribution, release manifest, checksums, and core offline bundles.
- Fixed NSIM 0.1.0 artifacts per verif-harness release; projects select the
  verif-harness version and reuse the installed NSIM dependency.
- Project bootstrap with required read-only RTL filelist input, NSIM project
  configuration, and project-local Agent/Skill/MCP setup.
- Restart from a project or subdirectory, paired version switching, compatible
  database checks, switch recovery, and installation/profile tests.

### Changed

- Existing projects use restart to continue work; source setup remains a
  developer compatibility entry. Old setup projects migrate through explicit
  bootstrap refresh without deleting verification history.
- Dashboard services are separated by account, release version and program
  identity. Shared dependency checks use command-scoped Git trust without
  changing users' global configuration.

See the [release notes](docs/releases/3.0.0.md) and
[installation guide](docs/installation.md) for evidence and migration details.

## Pre-v3 development notes

These historical notes were previously listed as unreleased. Current workflow
and approval behavior is documented in the user guide and repository instructions.

### Added

- Added single-runtime Codex/Kimi subagent collaboration with revision-bound
  atomic claims, heartbeat leases, registered non-overlapping verification write scopes,
  Main-Agent-only Human interaction, and per-subagent Dashboard visibility.
- Added project-scoped explorer, worker, and reviewer profiles for Codex and Kimi.
- Protected control-plane/runtime metadata from declared subagent write scopes,
  superseded assignments when their Closure action changes, and preserved local
  runtime profiles by emitting managed updates as `.new` files.

### Changed

- Document-writing-plan node details now contain only the writing plan, inline
  section review, review history, and an adjacent node-level approval-completion
  action. Completing the approval changes node validity without locking later
  review; any later section review invalidates the earlier completion state.
- Dashboard navigation now defaults to the current tab, with native links,
  browser back/forward, node quick-view drawers and explicit new-tab comparison.
  Revision-scoped, tab-local drafts preserve unfinished reviews across refresh
  events and navigation without carrying old input into new approval versions.
- Added state-driven breathing indicators to Dashboard planning, Workstream status
  and progress rings, and work-node status and progress bars. Motion preserves
  recorded progress, stops for terminal states, and respects reduced-motion settings.
- Dashboard services are now scoped to the current OS account. Automatic startup
  begins at port `8765`, skips occupied and foreign-account ports instead of
  falsely reusing them, protects the page and data APIs with a mode-`0600` account token,
  and returns single-hop and double-hop SSH forwarding templates using the actual
  selected port.
- VDOC now rejects structured proposals whose required writing plans lack
  independently reviewable delivery nodes, and routes already-stored incomplete
  revisions back to Agent refinement instead of requesting Human approval.
- Blocking `agent-question ask` now keeps a bounded runtime checkpoint by
  default, and the managed Kimi Main Agent profile prevents an open Dashboard
  question from being abandoned at an idle CLI prompt.
- Kimi Human questions now use a paired foreground registration and background
  checkpoint, keeping the normal CLI input available while Dashboard and the
  Main Agent conversation answer the same persisted question.
- Dashboard Agent interaction, project overview, pending-item lists, and VDOC
  review pages now derive Human-facing state from the same typed pending set,
  distinguishing Agent questions, plan approvals, delivery acceptance, and
  document confirmations.
- Work-node rows now always show a progress bar: numeric observations take
  precedence, with review sections, delivery acceptance, or completion
  criteria used as explicit non-numeric fallbacks.
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
