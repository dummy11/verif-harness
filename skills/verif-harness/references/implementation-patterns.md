# Verification capability implementation patterns

## Explicit contracts

Use machine-readable contracts only after the corresponding verification-plan
content has been reviewed. A generator may validate and render declared names,
expressions, properties, ports, commands, fields, formulas, and thresholds. It
must not derive them from prose, RTL signal names, or previous project habits.

Contracts should be:

- complete enough that omitted semantics fail validation;
- versioned with the generated artifact;
- traceable to testcase, coverage, assertion, reference-model, CI, or
  performance-plan entries;
- additive by default and protected from accidental overwrite.

## Test registration and promotion

Creating a UVM test and registering package includes establishes compile
visibility only. Candidate-list membership establishes review scope. Default
regression membership is a separate promotion decision and requires evidence
that the test is implemented, deterministic, documented, and passing.

## Coverage and assertions

Coverage-bin expressions and assertion properties are executable
specification. Require stable IDs or plan references. Generate TODO comments
for missing approved semantics; never generate vacuous or always-passing logic
to fill a hole.

## Reference-model adapters

An adapter declares connectivity. The project must separately define
transaction alignment, masking, residual behavior, numeric representation,
unsupported configurations, and proof that the Golden actually engaged.

## CI and performance evidence

CI generation produces a reviewable fragment, not a live pipeline mutation.
Keep secrets outside generated content. Performance evaluation accepts only
fixed operand forms and comparison operators; do not execute arbitrary formula
text. Archive reports with commit, seed, simulator, manifest, and source-log
identity.

## Sign-off boundary

A structural audit may report missing evidence, internal inconsistencies, or
that a Human approval is already recorded. It cannot validate unavailable raw
artifacts, approve waivers, resolve open questions, or sign off a stage.

## Completion modes

Completing a UVC or scoreboard means replacing structural TODOs with behavior
that is fully declared in a reviewed contract. For ready/valid source drivers,
declare clocking blocks, handshake signals, payload mappings, and timeout. For
scoreboards, declare alignment, expected/actual expressions, masking,
tolerance, residual policy, and no-compare behavior. An unsupported protocol or
alignment scheme is an open design item, not a reason to generate guessed code.

## Regression triage

Preserve the primary log, original seed, same-seed rerun log, normalized failure
signature, and matched classification rule. Regex-based classifications are
triage candidates. Missing logs, missing reruns, mismatched seeds, and unknown
signatures must stay visible blockers.

## Coverage and assertion closure

Tool-neutral JSON is an adapter contract, not a replacement for native
simulator evidence. Coverage closure requires database identity, one status per
planned item, nonzero hits for covered items, and complete approved-waiver
metadata for exclusions. Assertion closure requires compile and bind evidence,
nonzero attempts, failure counts, and vacuity handling. `READY_FOR_*_REVIEW`
never means approved.

## Change control and freeze manifests

Every post-baseline changed file should map to a structured change request with
explicit test, coverage, assertion, documentation, and regression impact. A
freeze manifest should be created only from a clean Git commit, record the
baseline and RTL diff policy, validate machine-readable evidence states, and
hash every required artifact. Creating a manifest must not create a Git tag,
push a branch, approve a gate, or authorize publication.
