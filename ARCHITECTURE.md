# Architecture

## Purpose

verif-harness v1 is an AI-native verification engineering control plane. Its
unit of control is a live desired-state model, not a one-shot workflow run.

## Control loop

```text
Human intent
    |
    v
 VPlan ----review----> Workstream desired state
    |                         |
    v                         v
 VModel <----evidence---- capability tools / simulators
    |
    +----> VCheck ----> validity + causal findings
    |                         |
    +----> VClosure <---------+
               |
               +---- deterministic next actions
               +---- VReason request when ambiguity remains
```

The global loop is `VModel -> VCheck -> VClosure -> selected gap -> local
Workstream loop -> evidence -> VModel`. Each local loop is `DESIRED -> PLAN ->
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

- VPlan owns Workstream templates, desired state, and review revisions.
- VModel owns persisted facts and provenance.
- VCheck owns deterministic reconciliation and invalidation propagation.
- VClosure owns global gap calculation, Workstream routing, and minimum next-action selection.
- VReason owns structured proposals for ambiguous cases, not execution or approval.
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
