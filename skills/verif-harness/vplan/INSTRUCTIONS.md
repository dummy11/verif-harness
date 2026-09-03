# Verification Planner

Design or revise one re-entrant Workstream. Start with its built-in detailed
template and current Verification Knowledge Model/project context. Auto-fill known facts, propose a
candidate desired state, and ask only genuine open decisions in the live Agent
conversation. Persist accepted answers as revisioned structured state and a
Markdown projection.

```text
$verif-harness plan VDOC|VSTIM|VCHK|VCOV|VCASE|VREG \
  [--objective "..."] [--desired "..."] [--exit "..."] [--decision "..."]
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
