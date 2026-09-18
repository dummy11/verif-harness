# Verification Planner

Design or revise one re-entrant Workstream. Start with its built-in detailed
template and current Verification Knowledge Model/project context. Auto-fill known facts, propose a
candidate desired state, and ask only genuine open decisions in the live Agent
conversation. Persist accepted answers as revisioned structured state and a
Markdown projection.

For VDOC, read [document delivery instructions](vdoc.md) and the templates for
the documents being drafted. Default VDOC goals name eight engineering documents;
the Engine creates only missing templates in the project's verification output
directory, then the Agent fills engineering semantics through Human dialogue.
Existing documents are never overwritten. The CLI's desired-state/plan projections
are not those deliverables; document governance state is rendered on demand from SQLite.
Treat each governed document as a top-level delivery node. Its engineering topics,
open questions, and decisions are nested review content, not proof that the whole
subject is complete and not one node per paragraph. The document body remains the
editable semantic authority.

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
