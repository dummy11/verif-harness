# Verification Closure Engine

The Verification Closure Engine runs automatically after plan review, evidence
updates, and consistency events. Use bare `closure`, or `closure evaluate
--workstream NAME`, to
inspect/recompute actions for CI or debugging. It compares desired/current
state globally and may route directly to any Workstream; it never imposes a
DOC→stimulus→checker→coverage→case→regression order.

Standard templates distinguish `capability` from `closure-evidence` nodes.
Planner-default `DEPENDS_ON` edges are rebuilt against current Workstream
revisions. If a prerequisite Workstream has not been planned, closure returns
`PLAN_PREREQUISITE`; if its node exists but is not VALID/WAIVED, closure returns
`WAIT_FOR_DEPENDENCY`. Never replace this node graph with a whole-Workstream gate.

Also enforce executable cross-evidence exit predicates. Emit
`EXIT_CRITERION_BLOCKED` for unresolved VDOC Human Decisions/Open Questions,
capability/evidence digest mismatch, incomplete VCASE mappings, unmatched VREG
failure triage, or an incomplete Planner-derived fresh-evidence set. Natural
language exit prose is review context, not a substitute for these predicates.
For VENV, require the environment smoke report to bind the same environment
implementation digest as the current `build-ready` evidence. The smoke is a
minimal clock/reset/run/observe proof and must not depend on completed VSTIM,
VCHK, VCOV, VCASE, or VREG execution evidence.

A Workstream is closure-ready only when all current required nodes are
VALID/WAIVED, all planner-default prerequisites are planned and VALID/WAIVED,
cross-evidence predicates have no blocker, there is no OPEN finding on its
nodes, and the current plan revision has Human approval. `SATISFIED` is not
`BASELINED`: freeze remains a separate Human-authorized operation.

An action declares executor `deterministic`, `reasoning`, or `human` and a
suggested capability. The closure engine decides what is needed but does not write code,
run a monolithic task list, or pretend to pause. Ask Human questions in the
live Agent conversation, then record evidence or decisions through structured
ingress.
