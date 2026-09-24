# Architecture

## Purpose

For an implementation-grounded walkthrough in Chinese, read
[工作机制](skills/verif-harness/docs/mechanism.md) and
[术语表](skills/verif-harness/docs/glossary.md).

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

Project VDOC Markdown is the source for verification engineering semantics:
scope, feature definitions, architecture, compare policy, coverage, assertions,
and testcase contracts remain directly readable and Git-reviewable.
The Dashboard renders this same Markdown into a read-only HTML view using a
pinned local parser, with escaped raw HTML and project-scoped document links.
Generated HTML is neither persisted nor used as an approval identity; source
digests and revisions remain authoritative. Each view also exposes the source.

`.verif-harness/model.sqlite3` is the machine source of truth for governance
state. In addition to the core model, it stores:

- typed nodes for intent, desired state, implementation, artifacts, and evidence;
- capability and closure-evidence nodes linked by revision-aware planner-default dependencies;
- executable cross-evidence exit predicates and Planner-derived fresh-evidence membership;
- typed edges with `explicit`, `inferred`, or `runtime` origin and confidence;
- Workstream revisions and Human review records;
- semantic-document paths, content digests, revisions, reviews, governance-item
  lifecycle and links to desired state;
- change events, causal findings, validity, and closure actions.
- bounded Agent/tool Activity records and Human comments or requested changes
  used by the local real-time Dashboard; these records do not establish node validity.
- revision-bound native-subagent assignments with an exclusive node claim,
  optional non-overlapping verification write scope, heartbeat lease, parent Agent,
  runtime identity, and linked Activity. Assignment state does not establish validity.

`plan VDOC` creates missing Markdown templates but never overwrites existing
semantic documents. `docs sync` detects content changes by digest; `docs status`
and `docs render` project lifecycle, Review Trace, Human Review Notes and Revision
Log on demand without writing them into semantic bodies. VDOC freeze snapshots
reviewed Markdown beside the immutable manifest.
The VDOC bundle also contains an on-demand governance Markdown snapshot rendered
from the same database state.

`project.json` stores project configuration consumed by the CLI; `inventory.json`
records the bootstrap inventory. `model.md` and Workstream `plan.md` are reading
projections. Editing a reading projection does not update the database. Use the
CLI to change state rather than editing configuration or projections manually.
Explicit RTL roots, DUT top files, and specification inputs may live outside the
project root and are stored as absolute read-only identities. Control state,
verification outputs, and generated projections remain inside the project root.

The local Dashboard is a view and controlled Human-input surface over this same
model. It uses server-sent events to refresh Workstream/node/evidence/activity
views, binds only to loopback, and routes reviews, waivers, and freezes through
the existing store APIs. It is not another verification engine and does not infer
progress from unregistered terminal processes.

Every current desired-state node also exposes a deterministic
`NodeClosureAssessment/1`. It binds the current Workstream revision, node status,
definition, prerequisites, evidence, findings, per-criterion support, rule
version, and a content digest. Dashboard node-closure reviews are bound to that
digest. Approval records that the Human accepts the explanation; it never creates
evidence or changes validity. Modify, clarify, or reject moves the node to
`REVIEW_REQUIRED` and opens a finding. A changed assessment invalidates stale
review submissions.

VDOC uses each governed Markdown document as a top-level Dashboard node. The
document body remains the engineering-semantic authority; its tracked open
questions and decisions are displayed as nested governance items rather than
flattened into arbitrary SQLite prose fields. Pending `human-decision` and
`external-open-question` items contribute to the Dashboard's Human-attention
count. The loopback Dashboard may preview the registered UTF-8 Markdown body
and submit a revision-bound document review through the existing store API.
Pending Human decisions or external open questions prevent an APPROVE document
review at both the Dashboard and store boundaries. This makes the document node
the default Human review surface without moving engineering semantics out of
the Markdown body.

The Dashboard hub is scoped to one operating-system account. Its health record
includes an opaque owner identity derived from the account-local credential.
Automatic startup first reuses the current account's hub, then scans
from port 8765 while recording and skipping occupied, old, or foreign-account ports. It never registers a
project in one account's registry while routing requests through another
account's process. An explicit port remains strict and reports a conflict rather
than switching. A persistent account-local token stored with mode `0600` gates
the HTML page and every read/write API; unauthenticated health checks expose no
project path, name, verification fact, or document content. Successful remote
launches return single-hop and double-hop SSH
forwarding templates plus the token-bearing project URL bound to the actual
selected port.

`await-human` is a bounded, revision-aware checkpoint over formal Workstream
reviews. It can move a registered Activity between `WAITING_FOR_HUMAN` and
`RUNNING`, but comments cannot release it and it never injects arbitrary text
into an Agent session.

A blocking `agent-question ask` is likewise a runtime checkpoint: it registers
the question and waits up to 300 seconds by default. A runtime with reliable
background completion notification may split this into an atomic interaction
bridge: foreground `ask --no-wait`, render the returned structured question in
the Agent conversation, then run `agent-question await` as a background task.
Kimi uses this split form so its normal input box remains available while the
Dashboard and CLI conversation resolve the same SQLite record. A bare no-wait
registration is invalid; every open blocking question must have a live watcher.
An answer persisted by the Main Agent changes the next Dashboard snapshot and
is pushed to an open Dashboard through its event stream. An answer persisted by
the Dashboard completes that same CLI watcher, which lets the runtime resume
from the recorded choice. These are two views of one state transition, not two
independent question lifecycles.
While the question remains open, a timed-out watcher is renewed without creating
a duplicate question. The Dashboard only persists the answer and releases the
checkpoint; it never writes directly into a Codex/Kimi terminal. If no checkpoint
is active because an older runtime session is already idle, the Human must start
another turn so Main can read the persisted question state and continue.

Multi-agent execution remains a single-runtime, parent-owned control loop.
Codex or Kimi owns native child contexts and scheduling; verif-harness does not
launch or inspect runtime threads. The Project Main Agent is the only Human-facing
actor and the only writer of governance state. Before native dispatch it atomically
claims one current Closure action, which creates a linked Activity and binds the
child to the current Workstream revision and node-definition digest. Subagents
return results to Main. `WAITING_FOR_PARENT` is internal coordination and never
enters the Human queue. Only Main may register an `agent-question`, apply a result,
record evidence, or request a gate. Lease expiry or assignment completion does not
mark a node failed or valid; revision drift supersedes the assignment.

The question API accepts only the `Project Main Agent` actor and rejects any
Activity owned by a subagent assignment. Declared write scopes also reject DUT/spec,
`.verif-harness`, `.harness-config.json`, `.deps`, VCS metadata, runtime
configuration, and `AGENTS.md` (using conservative case-insensitive matching).
These are workflow guards for cooperating runtime agents, not a hostile-process security
boundary: agents sharing one OS identity can still address the same files. Main
must inspect the actual diff before accepting a result; untrusted execution needs
an isolated worktree or a stricter runtime sandbox.

Bootstrap also creates or refreshes only a marked verif-harness block in the
project-root `AGENTS.md`. The block is a routing and authority projection, not a
fact database: bootstrap writes DUT/read-only boundaries, and VDOC planning adds
the confirmed document root and contract routes. Existing project instructions
outside the markers are preserved. Stage and Spec Kit workflow state are not
reintroduced through this projection.

Refresh also synchronizes bootstrap-managed fields in `.harness-config.json`
from the confirmed project manifest. Optional project sections and customized
verification/governance subdirectory names are retained; Workstream, evidence,
review, and document-governance records are not reset.

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

VENV owns the shared environment foundation: interface/clock/reset connection,
component topology, build/elaboration, the minimal run entry, and observation
points. VSTIM owns stimulus behavior and reachability; VREG owns batch policy,
execution, collection, and triage. Planner dependencies connect concrete nodes,
not whole Workstreams. VENV smoke is intentionally independent of completed
business stimulus, checking, coverage, testcase, and regression evidence, so
the graph has no VENV↔VREG completion cycle.

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

Compiler/simulation logs, regression manifests, waveform files, and VDB/UCDB
databases are raw artifacts rather than evidence verdicts. Project adapters or
collectors convert them into typed JSON reports that bind the current project
revision and native-artifact SHA-256 values. The control plane validates schema,
claim-specific artifact/analyzer admission policy, dependencies, and
cross-evidence exit predicates before it derives PASS/FAIL. Runtime claims bind
the raw simulation/coverage data and a stored xverif or WavePeek analysis report;
an `analyzed_by` label without the required analysis-report artifact cannot close
the node. v1 does not yet ship one universal extractor for every EDA vendor format.
