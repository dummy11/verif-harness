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
testcases, and unresolved engineering decisions. Let N be the number of documents
actually in scope. By default, create N public writing-plan nodes first and, after
approval and authoring, N public delivery nodes: one plan and one delivery per
document. Split one document into multiple public nodes only when it genuinely has
different owners or independent approval gates. N varies with the verification
object and is not fixed at eight.
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
- `document-deliverable`: the public content-acceptance node for exactly one
  Markdown document. Every node has an explicit `document_key`; the default is
  one delivery node per in-scope document. It records actual semantic content,
  document anchors/sources, acceptance criteria, Agent
  analysis, and any items that still require Human confirmation. Delivery nodes
  exist only after all required writing plans have been approved and the formal
  body has been written and synchronized.

The fixed `document-catalog` rows are internal containers and dependency
anchors, not a third public VDOC node type. A writing-plan node says what and how
the Agent proposes to write. A delivery node says which already-written semantic
content the Human is accepting. Never reuse one content template for both.
Within either public node, the Engine records hidden, digest-bound semantic units for
sections, review change items, source anchors, and dependency impact. These units
support fine-grained invalidation but are not separate Human tasks or approval
targets; acceptance is always aggregated at the public node.

VDOC is a serial two-phase lifecycle. The initial DUT-specific proposal contains
only writing-plan nodes and is the only object presented for plan approval. It
is invalid to mix writing-plan and delivery nodes in one proposal. Before every
required plan section is approved and VDOC becomes `ACTIVE`, the Agent must not
write or modify the formal document body, run `docs sync`, create delivery
nodes, or ask the responsible person to accept body content. After approval,
the Agent writes the formal body, runs `docs sync`, and submits a separate
delivery-only proposal without changing the approved plan revision. At that
point every required writing plan must own at least one required delivery
descendant, and every required delivery must trace back to a required writing
plan for the same document. An early preview draft is permitted only on an
explicit user request and must remain outside formal synchronization, evidence,
and delivery-node registration until plan approval.

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
3. Start with scope and feature decomposition and create only the DUT-specific
   writing-plan proposal. Ask only unresolved engineering decisions in the live
   conversation. Persist explicit answers with decision references; leave
   unresolved items visible with their affected goals. No guessed thresholds,
   fake source references, pre-approved waivers, or invented simulator evidence.
   Wait for all required plan sections to be approved before formal body work.
4. After VDOC becomes `ACTIVE`, populate the approved formal content, run
   `docs sync`, and register delivery-only nodes for independent body review.
   Base document governance on `verification_workflow.md`: document-first work,
   separate plan/content Human reviews, explicit decision types,
   evidence-backed validity, and incremental invalidation. Do not introduce
   Stage gates, Spec Kit authority, monolithic tasks, or a detached worker. Do
   not demand that all eight documents be complete before other Workstreams can
   start. An inapplicable topic needs a reason and an agreed alternative, not
   silently omitted requirements. The optional waiver manifest is not a default
   required VDOC deliverable.
5. Keep each document concise: current design, source references, tables and open
   questions. Markdown is authoritative for engineering semantics. Use the
   knowledge model for document digest/revision, decision lifecycle,
   review/evidence history and invalidation; link stable IDs instead of duplicating
   status logs in every file.
   Do not put implementation code dumps or past run diaries in the main text.

## Model links and review

The Engine registers each default output and its digest against an internal
document catalog. Public writing-plan and delivery nodes both carry an explicit
`document_key`. Only after plan approval, edit semantic content and run `docs
sync [DOCUMENT]`; the Engine increments the semantic revision when the digest
changes and propagates invalidation through the registered relations. Then
submit the separate delivery-only proposal. Registering those delivery nodes is
an in-revision expansion of the approved plan, not a new plan revision.
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
Plan approval authorizes the Agent to write the desired scope; it does not
certify document content. Until the delivery-only proposal is registered, the
Dashboard reports that the Agent is authoring content and exposes no content
review targets.
Each delivery node is reviewed against the current document digest and semantic
revision. Submitting the Human review creates a mandatory Main-Agent inspection
checkpoint; it does not immediately mark the node accepted. The Main Agent reads
`agent-review-check list --status PENDING`, checks the review, body, and dependency
impact, and decides whether a node-bound `agent-question` is needed. After all
questions are answered, the Agent re-analyses before completing the checkpoint
with `agent-review-check complete`. A delivery node is approved only when the
current body has a Human approval, its Agent checkpoint is complete, and it has
no open Agent question. Only then may the Engine mark the document approved. Do
not use file existence or a bare template as passing evidence.

## Human-Agent-Engine review loop and convergence

VDOC review is an iterative, revision-bound loop rather than a one-time approval:

1. The Agent analyses the current DUT, specifications, existing documents, and
   unresolved feedback, then proposes or updates writing-plan nodes only.
2. The Engine validates the plan proposal and document mapping, records the
   workstream revision and node-definition digests, and exposes only the plan
   review targets. This registration is not an engineering approval.
3. The Human independently reviews every required writing-plan section. The
   Human may approve, request modification, request clarification, or reject it.
4. Only after all required plans are approved, the Agent writes or revises the
   formal body, synchronizes its digest, and registers a separate delivery-only
   proposal. The Human then reviews the semantic content represented by each
   delivery node and may approve, request modification, request clarification,
   reject, or provisionally accept it under the rules below. The Engine then
   holds the node in Agent-checking state.
5. The Main Agent always inspects the submitted review. If it needs responsible-
   person confirmation, it creates a node-bound Agent question and the node enters
   waiting-for-Human state. After the answer, the Agent rechecks. If no question is
   needed, or all questions are resolved, it records the check as complete.
6. A modification, clarification, rejection, changed DUT/specification, changed
   node definition, or changed document body returns the affected scope to the
   Agent. The Agent re-analyses the feedback and submits a new proposal or
   document revision; the Engine invalidates review conclusions that no longer
   match the current digests.
7. The Human reviews the new revision. Steps 3-7 repeat until the current
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
- every required `document-deliverable` node has a Human approval against the
  current node-definition digest and current document digest, its corresponding
  Main-Agent review check is complete, and it has no open Agent question;
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
