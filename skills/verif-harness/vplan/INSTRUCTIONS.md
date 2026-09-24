# Verification Planner

Design or revise one re-entrant Workstream. Start with its built-in detailed
template and current Verification Knowledge Model/project context. Auto-fill known facts, propose a
candidate desired state, and ask only genuine open decisions in the live Agent
conversation. Persist accepted answers as revisioned structured state and a
Markdown projection.

For VDOC, read [document delivery instructions](vdoc.md) and the templates for
the documents being drafted. Running default `plan VDOC` registers eight internal
document catalogs and creates only missing templates in the project's verification
output directory. Those catalogs are navigation and dependency anchors, not a
default eight-node proposal, and “eight documents, all required” is never a
substitute for analysing the current DUT. Before asking the Human to approve a
VDOC plan, derive a `DesiredStateProposal/1` from the DUT,
specification, interfaces, verification points, checking, coverage, scenarios,
and unresolved decisions. For N documents actually in scope, default to N public
`document-writing-plan` nodes and, after authoring, N public
`document-deliverable` nodes. Materialize semantic sections and dependency units as
internal work nodes with the same execution, dependency, evidence, invalidation,
question, Activity, assignment, and closure capabilities as other work nodes;
split one document into multiple public nodes only for genuinely independent owners
or approval gates. The initial proposal must contain only DUT-specific
`document-writing-plan` nodes. Do not create or show `document-deliverable`
nodes, write or modify formal document bodies, or run `docs sync` until every
required writing-plan section has been approved and VDOC is `ACTIVE`.
Use the sibling `verification-doc-authoring` Skill and the integrated
`plan authoring` engine for every in-scope registry document. Preserve each
`VerificationDocumentAuthoringContract/1` under `authoring_contract`; its
source snapshot must bind the current project/RTL/spec/document digests, and
missing or conflicting facts must remain explicit source gaps. Keep the eight
document-specific profiles and their dependency DAG; do not replace them with
generic VDOC prose and do not generate final Markdown bodies at this stage.
After approval, write the formal content, run `docs sync`, and submit a separate
delivery-only `DesiredStateProposal/1` whose independently reviewable
`document-deliverable` nodes trace to the approved plans. Never combine the two
phases in one proposal or one Human review request. If closure returns
`REFINE_DESIRED_STATE` or `REFINE_DOCUMENT_DELIVERIES`, continue Agent analysis
and proposal construction; do not present fixed catalogs or structurally
invalid nodes for Human approval.

Existing documents are never overwritten. The CLI's desired-state/plan projections
are not those deliverables; document governance state is rendered on demand from SQLite.
The document body remains the editable semantic authority. Engineering topics,
open questions, sections, and dependency units remain nested internal review
content rather than one public node per paragraph.
An early preview draft is allowed only when the user explicitly requests one;
keep it outside formal document synchronization, evidence, and delivery nodes
until the writing plan is approved.

```text
$verif-harness plan VDOC|VENV|VSTIM|VCHK|VCOV|VCASE|VREG \
  [--objective "..."] [--desired-file DesiredStateProposal.json]
$verif-harness review [NAME] [--verdict approve|reject|modify|clarify] \
  [--reviewer NAME] [--reason "..."]
```

Each redesign creates a new revision and returns the Workstream to `REVIEW`.
Omit the review target only when exactly one candidate exists. Approval defaults
are convenience for an explicit Human review command, not authorization for an
Agent to approve. Reject/modify/clarify always require a reason. Never approve
on the user's behalf. Workstreams may be incomplete,
simultaneous, reopened, and entered in any order. Do not create a frozen large
task document; the Verification Closure Engine derives current actions from live facts.

The built-in nodes are reusable summary/checkpoint nodes, not a sufficient
project breakdown. For every non-VDOC Workstream, read the reviewed VDOC documents
and current model, then prepare a `DesiredStateProposal/1` using
`desired-state-proposal.schema.json` and `desired-state-proposal.example.json`.
Discuss genuine engineering choices with the Human before passing the reviewed
candidate through `--desired-file`. Create project nodes at the level a reviewer
needs to understand goal, work content, implementation approach, deliverables,
measured progress, and quality. Examples include one interface/environment
component, stimulus feature/scenario, checking goal/checker, coverage goal,
testcase mapping, or regression profile. Keep raw logs, wave databases, coverage
databases, and individual transactions as evidence; do not turn every artifact
into a planning node. Parent every project node under a template or project node
and never create parent cycles.

After evidence changes, use the Dashboard node view to inspect the current
`NodeClosureAssessment/1`. Its conclusion must remain traceable to the current
revision, prerequisites, evidence, findings, and criterion checks. A Human node
review confirms or disputes that explanation only; it must never substitute for
required evidence.
