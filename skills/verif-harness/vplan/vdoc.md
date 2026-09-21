# VDOC document delivery

Read this for VDOC planning or when another Workstream revises a verification
document. Template paths are relative to the installed Skill root.

## Deliverables and ownership

| Document | Template | Continued maintenance |
| --- | --- | --- |
| verification_workflow.md | [template](../assets/vdoc/verification_workflow.md) | VDOC; document governance and Human gates |
| verification_plan.md | [template](../assets/vdoc/verification_plan.md) | VDOC; project-wide scope/acceptance |
| feature_matrix.md | [template](../assets/vdoc/feature_matrix.md) | all Workstreams; stable trace IDs |
| tb_architecture.md | [template](../assets/vdoc/tb_architecture.md) | VENV/VSTIM/VCHK/VREG |
| reference_model_spec.md | [template](../assets/vdoc/reference_model_spec.md) | VCHK |
| coverage_plan.md | [template](../assets/vdoc/coverage_plan.md) | VCOV |
| assertion_plan.md | [template](../assets/vdoc/assertion_plan.md) | VCHK/VCOV |
| testcase_list.md | [template](../assets/vdoc/testcase_list.md) | VCASE/VREG |
| code_coverage_waiver_manifest.md | [template](../assets/vdoc/code_coverage_waiver_manifest.md) | VCOV; only for an actual waiver candidate |

The CLI's default VDOC rows contain document contracts (filename, template,
maintained_by). They are eight internal document catalogs, not eight fixed
implementation-plan nodes, and they do not determine the project node count.
Before plan approval, the Agent must derive a `DesiredStateProposal/1` from the
current DUT, specification, interfaces, features, scenarios, checkers, coverage,
testcases, and unresolved engineering decisions. Those project nodes are the
VDOC implementation plan, so their count varies with the verification object.
`plan.md` under `.verif-harness/workstreams/vdoc/` remains the planning
projection; the eight deliverables are separate engineering documents. `plan
VDOC` creates only missing templates and registers their paths and digests; it
never overwrites an existing semantic document or approves content.

VDOC has exactly two public node types:

- `document-writing-plan`: a DUT-specific document-writing plan. Every node has
  an explicit `document_key` naming exactly one document. Its objective
  and scope, planned content, Human engineering decisions,
  input/scope/deliverable contract, and dependency impact are reviewable
  sections inside the node, not additional node types;
- `document-deliverable`: one independently reviewable semantic acceptance unit
  inside exactly one Markdown document. Every node has an explicit
  `document_key`; one document normally has multiple delivery nodes. It records
  actual semantic content, document anchors/sources, acceptance criteria, Agent
  analysis, and any items that still require Human confirmation.

The fixed `document-catalog` rows are internal containers and dependency
anchors, not a third public VDOC node type. A writing-plan node says what and how
the Agent proposes to write. A delivery node says which already-written semantic
content the Human is accepting. Never reuse one content template for both.

A structured DUT-specific proposal is incomplete when it contains writing-plan
nodes but no independently reviewable delivery nodes. Every required writing
plan must own at least one required delivery descendant, and every required
delivery must trace back to a required writing plan for the same document. The
Engine rejects new incomplete proposals and routes already-stored incomplete
revisions back to Agent refinement; it must not ask the responsible person to
approve the writing-plan nodes in such a revision.

Do not create VDOC nodes with `project-goal`, `capability`,
`closure-evidence`, `document-goal`, `document-section`, or
`engineering-decision` roles. Document content review bound to the delivery
digest is VDOC's completion evidence; it is not a separate VDOC
closure-evidence node.

## Dialogue and writing

1. Read current desired state and user-provided read-only inputs. Choose a
   verification-document output directory from the existing project layout,
   or propose `<verif-root>/docs/verification`. Confirm if the destination is
   ambiguous. Never write into RTL/spec inputs, overwrite an input specification,
   or copy private project material into the public Skill package.
   Pass the confirmed project-relative directory as `--document-root` when it
   differs from the recorded/default path. VDOC planning then refreshes only the
   marked verif-harness block in project-root `AGENTS.md` with the eight routes.
2. `plan VDOC` materializes missing templates in the selected output directory.
   Read the relevant template before filling that document. Reuse existing
   verification documents and their stable IDs; inspect and edit them in place
   only within authorized verification output paths, never blindly overwrite.
   A template named reference_model_spec.md does not make an existing read-only
   input of the same name writable; choose a separate output path in that case.
3. Start with scope and feature decomposition, then fill the relevant topical
   drafts as the user needs them. Ask only unresolved engineering decisions in
   the live conversation. Persist explicit answers with decision references;
   leave unresolved items visible with their affected goals. No guessed thresholds,
   fake source references, pre-approved waivers, or invented simulator evidence.
4. Populate useful current content and label drafts. Base document governance on
   `verification_workflow.md`: document-first work, separate plan/content Human
   reviews, explicit decision types, evidence-backed validity, and incremental
   invalidation. Do not introduce Stage gates, Spec Kit authority, monolithic
   tasks, or a detached worker. Do not demand that all eight
   documents be complete before other Workstreams can start. An inapplicable topic
   needs a reason and an agreed alternative, not silently omitted requirements.
   The optional waiver manifest is not a default required VDOC deliverable.
5. Keep each document concise: current design, source references, tables and open
   questions. Markdown is authoritative for engineering semantics. Use the
   knowledge model for document digest/revision, decision lifecycle,
   review/evidence history and invalidation; link stable IDs instead of duplicating
   status logs in every file.
   Do not put implementation code dumps or past run diaries in the main text.

## Model links and review

The Engine registers each default output and its digest against an internal
document catalog. Public writing-plan and delivery nodes both carry an explicit
`document_key`. After editing semantic content, run `docs sync [DOCUMENT]`; the
Engine increments the semantic revision when the digest changes and propagates
invalidation through the registered relations.
Custom `--desired` plans replace the default catalog: establish explicit mappings
for their actual goals, rather than guessing which custom node a document satisfies.
Cross-workstream consumers need explicit dependency edges as applicable.

The initial file/draft remains UNKNOWN or REVIEW_REQUIRED. In the Dashboard,
each required DUT-specific VDOC plan node opens its review in a new tab. Human
Decisions, planned ASIC-verification content, input/scope/deliverable, and any
actual dependency/impact block are reviewed independently and bound to the
current node-plan digest. All required sections of all required project nodes
must be approved before the VDOC plan becomes ACTIVE. The eight document
catalogs remain available for navigation, but are not plan or delivery nodes. A
pure-CLI `review VDOC` is only a batch recording surface after the Human has
explicitly reviewed those sections.
Plan approval authorizes desired scope; it does not certify document content.
Each delivery node is reviewed independently against the current document digest
and semantic revision. Agent-analysis questions, assumptions, risks, and
engineering decisions targeted at that delivery node must be resolved first.
Only when every required delivery node of a document is approved does the Engine
mark that document approved. Reviewing every required VDOC delivery node is
therefore equivalent to reviewing all required document semantics. Do not use
file existence or a bare template as passing evidence.

## Human-Agent-Engine review loop and convergence

VDOC review is an iterative, revision-bound loop rather than a one-time approval:

1. The Agent analyses the current DUT, specifications, existing documents, and
   unresolved feedback, then proposes or updates writing-plan nodes or document
   delivery content.
2. The Engine validates the proposal schema and document mapping, records the
   workstream revision, node-definition digest, document semantic revision, and
   document digest, and exposes the current review targets. This registration is
   not an engineering approval.
3. The Human independently reviews the required writing-plan sections or the
   semantic content represented by each delivery node. The Human may approve,
   request modification, request clarification, reject, or provisionally accept
   a delivery node under the rules below.
4. A modification, clarification, rejection, changed DUT/specification, changed
   node definition, or changed document body returns the affected scope to the
   Agent. The Agent re-analyses the feedback and submits a new proposal or
   document revision; the Engine invalidates review conclusions that no longer
   match the current digests.
5. The Human reviews the new revision. Steps 3-5 repeat until the current
   revision satisfies every convergence condition.

The Agent does not iterate unconditionally after an approval, and the Dashboard
does not run a background Agent. A new Agent iteration begins when Human feedback
or an input/content change creates actionable work and the Agent reaches a
checkpoint that reads it. The Engine is not a third engineering voter: it
enforces structure, provenance, version binding, dependency rules, and the
deterministic aggregation of recorded conclusions.

VDOC is converged only when all of the following are true for the current
revision:

- every required `document-writing-plan` node has all required sections approved
  by the Human;
- every required `document-deliverable` node is approved against the current
  node-definition digest and current document digest;
- every required document's delivery-node set covers all semantic content that
  must be accepted, and all those delivery nodes are approved;
- no open Human confirmation, modification request, clarification request,
  blocking finding, external open question, or unresolved engineering decision
  affects the required VDOC nodes;
- no required delivery node or document remains `PROVISIONAL`, stale, changed,
  invalid, or awaiting re-review;
- the Engine's current closure evaluation reports that the VDOC exit conditions
  are satisfied. Human approval remains the source of engineering acceptance;
  Engine closure only confirms that the recorded, current-version approvals are
  complete and internally consistent.

An approval bound to an older workstream revision, node-definition digest,
document semantic revision, or document digest never contributes to current
convergence. A later edit preserves the historical review record but reopens the
affected current target.

A Human may mark a delivery node `PROVISIONAL` only with a named owner and a
concrete re-review trigger. This makes the document usable as a conditional
prerequisite so downstream implementation may start, but it never counts as an
approved delivery, document completion, Workstream closure, or freeze evidence.
Downstream work must remain traceable to that provisional dependency and be
revalidated if the provisional semantics change.

When the Human wants to add, change, or remove VDOC scope, use the Dashboard's
**调整文档** entry, then select the document, public node type, and add/modify/
remove operation. The request must store its `document_key`; modify/remove also
identify the existing node. The Agent then creates a new proposal revision and a
node-level diff. Do not ask the Human to manipulate stored nodes directly;
removal means absent/retired in the next revision, not deletion of history.

Use `docs track` for the state index of Human Decision, Provisional, Assumption and
External Open Question entries whose full engineering rationale remains in the
Markdown. Use `docs status` for JSON and `docs render` for a Markdown state view;
rendering defaults to stdout and never updates semantic documents.

On a later document revision, run `docs sync`, preserve existing review evidence,
and re-review affected content. If desired scope changes, replan and bind the
document edges to the new desired revision. Never regenerate all documents merely
because a single Workstream was reopened. VDOC freeze snapshots the reviewed
semantic documents beside the immutable manifest.
