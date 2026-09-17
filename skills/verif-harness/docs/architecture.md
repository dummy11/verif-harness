# v1 control-plane architecture

verif-harness v1 stores typed project facts in one Verification Knowledge Model and runs
a continuous global loop:

```text
change/evidence -> Verification Knowledge Model
  -> Verification Consistency Engine -> Verification Closure Engine
  -> tool/Verification Reasoning Engine/Human -> Verification Knowledge Model
```

Verification Planner combines a detailed template, current model, project context, and Human
dialogue to create revisioned desired state. `VDOC`, `VENV`, `VSTIM`, `VCHK`, `VCOV`,
`VCASE`, and `VREG` are parallel, re-entrant Workstreams. Each has its own
`desired -> plan -> act -> observe -> evaluate -> replan` loop. They are not a
fixed lifecycle or prerequisite chain.

Implementation Workstream templates split desired state into capability nodes
and closure-evidence nodes. Planner-default dependencies connect node keys, not
whole Workstreams, and are rebound to the current revision after every plan.
Typed evidence validators derive verdicts for standard nodes; arbitrary PASS
files cannot satisfy those contracts.
Closure additionally evaluates cross-evidence predicates and derives VREG
fresh-evidence membership from the current required closure-evidence nodes;
evidence producers cannot shrink that set.

VENV owns interface/clock/reset connection, environment topology, build,
minimal run, and observation readiness. VSTIM owns generated behavior and DUT
input reachability; VREG owns batch execution and triage. Dependencies join
only the required nodes. In particular, VENV smoke does not require completed
VSTIM/VCHK/VCOV/VCASE/VREG evidence, while VREG executor readiness reuses the
VENV minimal run capability. This prevents a whole-Workstream dependency cycle.

`.verif-harness/model.sqlite3` is authority. JSON and Markdown are review
projections. Verification Knowledge Model is read-only to Human-facing callers;
structured `evidence`, `reachability`, document-governance, change, and advanced
`record` ingress supply mutations and trigger the consistency and closure engines.

The local Dashboard is a presentation and Human-control surface over that same
database, not another source of truth or a sixth engine. It exposes a versioned
snapshot and server-sent updates for Workstreams, nodes, closure, evidence,
activities, and Human actions. Writes use a per-process token, bind only to the
loopback interface, and call the same ProjectStore review/waiver/freeze APIs.
Activity records communicate current Agent/tool progress but never mutate node
validity; evidence validators and explicit Human gates remain authoritative.

Each planned desired node stores its evidence claim and admission policy. The
policy separates compile-time capability proof from runtime closure proof and
names the required raw artifact classes and analyzers. Runtime proof also binds
a stored xverif or WavePeek analysis report; a free-form PASS file cannot satisfy
the policy. The full Workstream closes only after both capability and required
runtime evidence nodes satisfy their own contracts.

- Verification Consistency Engine judges validity and propagates causal invalidation; it does not act.
- Verification Closure Engine selects/routes actions; it does not write code.
- Verification Reasoning Engine handles semantic uncertainty through independent Role × Backend.
- Tools produce raw compiler/simulation/coverage/regression artifacts; project
  adapters or collectors convert them to typed reports with provenance. v1
  validates those reports but does not provide a universal vendor log/VDB/UCDB
  extractor.
- Human reviewers own approval, waiver, Workstream baseline, and final freeze.

Workstream and final baselines are immutable snapshots. The workspace can keep
evolving; new facts create revalidation/replanning rather than rewriting old
snapshots. DUT RTL remains external and read-only.
