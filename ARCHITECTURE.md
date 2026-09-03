# Architecture

## Purpose

verif-harness v1 is an AI-native verification engineering control plane. Its
unit of control is a live desired-state model, not a one-shot workflow run.

## Control loop

```text
Human intent
    |
    v
 Verification Planner ----review----> Workstream desired state
    |                         |
    v                         v
 Verification Knowledge Model <----evidence---- capability tools / simulators
    |
    +----> Verification Consistency Engine ----> validity + causal findings
    |                         |
    +----> Verification Closure Engine <---------+
               |
               +---- deterministic next actions
               +---- Verification Reasoning Engine request when ambiguity remains
```

The global loop is `Verification Knowledge Model -> Verification Consistency
Engine -> Verification Closure Engine -> selected gap -> local Workstream loop
-> evidence -> Verification Knowledge Model`. Each local loop is `DESIRED -> PLAN ->
ACT -> OBSERVE -> EVALUATE -> REPLAN`. Workstreams can be active concurrently
and may route to one another; they are not lifecycle states.

## Project state

`.verif-harness/model.sqlite3` is the machine source of truth. It stores:

- typed nodes for intent, desired state, implementation, artifacts, and evidence;
- typed edges with `explicit`, `inferred`, or `runtime` origin and confidence;
- Workstream revisions and Human review records;
- change events, causal findings, validity, and closure actions.

`project.json`, `inventory.json`, `model.md`, and Workstream `plan.md` files are
review projections. Editing a projection does not mutate authority.

Validity is explicit: `VALID`, `STALE`, `INVALID`, `REVIEW_REQUIRED`,
`REVALIDATION_REQUIRED`, `BLOCKED`, `WAIVED`, or `UNKNOWN`.

## Subsystem boundaries

- Verification Planner owns Workstream templates, desired state, and review revisions.
- Verification Knowledge Model owns persisted facts and provenance.
- Verification Consistency Engine owns deterministic reconciliation and invalidation propagation.
- Verification Closure Engine owns global gap calculation, Workstream routing, and minimum next-action selection.
- Verification Reasoning Engine owns structured proposals for ambiguous cases, not execution or approval.
- Capability tools own bounded implementation/evidence operations.
- Human reviewers own semantic approval, modification, waiver, and freeze.

## RTL architecture boundary

`tb_top` owns elaboration and test startup. The harness owns clock/reset,
interfaces, DUT instantiation, tie-offs/adapters, bind, and virtual-interface
publication. UVM owns stimulus, monitors, scoreboards, coverage, and test
control. DUT RTL remains external and read-only.

```text
tests -> env -> agents -> virtual interfaces
                           |
                           v
                       harness -> DUT (read-only)
                           |
                           +-> SVA / bind
```

## Tool boundary

xverif, WavePeek, simulators, waveform viewers, regression systems, and EDA
providers are capability adapters. The core depends on declared capabilities
and recorded evidence, not vendor command syntax. Tool success is provenance,
not Human approval or semantic sign-off.
