# VDOC document delivery

Read this for VDOC planning or when another Workstream revises a verification
document. Template paths are relative to the installed Skill root.

## Deliverables and ownership

| Document | Template | Continued maintenance |
| --- | --- | --- |
| verification_plan.md | [template](../assets/vdoc/verification_plan.md) | VDOC; project-wide scope/acceptance |
| feature_matrix.md | [template](../assets/vdoc/feature_matrix.md) | all Workstreams; stable trace IDs |
| tb_architecture.md | [template](../assets/vdoc/tb_architecture.md) | VSTIM/VCHK/VREG |
| reference_model_spec.md | [template](../assets/vdoc/reference_model_spec.md) | VCHK |
| coverage_plan.md | [template](../assets/vdoc/coverage_plan.md) | VCOV |
| assertion_plan.md | [template](../assets/vdoc/assertion_plan.md) | VCHK/VCOV |
| testcase_list.md | [template](../assets/vdoc/testcase_list.md) | VCASE/VREG |
| code_coverage_waiver_manifest.md | [template](../assets/vdoc/code_coverage_waiver_manifest.md) | VCOV; only for an actual waiver candidate |

The CLI's default VDOC desired nodes contain document contracts (filename,
template, maintained_by). `plan.md` under `.verif-harness/workstreams/vdoc/`
remains the planning projection; the seven deliverables are separate engineering
documents. The CLI does not materialize them or approve their content.

## Dialogue and writing

1. Read current desired state and user-provided read-only inputs. Choose a
   verification-document output directory from the existing project layout,
   or propose `<verif-root>/docs/verification`. Confirm if the destination is
   ambiguous. Never write into RTL/spec inputs, overwrite an input specification,
   or copy private project material into the public Skill package.
2. Read the relevant template before filling that document. Reuse existing
   verification documents and their stable IDs; inspect and edit them in place
   only within authorized verification output paths, never blindly overwrite.
   A template named reference_model_spec.md does not make an existing read-only
   input of the same name writable; choose a separate output path in that case.
3. Start with scope and feature decomposition, then fill the relevant topical
   drafts as the user needs them. Ask only unresolved engineering decisions in
   the live conversation. Persist explicit answers with decision references;
   leave unresolved items visible with their affected goals. No guessed thresholds,
   fake source references, pre-approved waivers, or invented simulator evidence.
4. Populate useful current content and label drafts. Do not demand that all seven
   documents be complete before other Workstreams can start. An inapplicable topic
   needs a reason and an agreed alternative, not silently omitted requirements.
   The optional waiver manifest is not a default required VDOC deliverable.
5. Keep each document concise: current design, source references, tables and open
   questions. Use the knowledge model for decisions and review/evidence history;
   link their IDs and evidence paths instead of duplicating long logs in every file.
   Do not put implementation code dumps or past run diaries in the main text.

## Model links and review

For each output, register or reuse its project-relative file node, and record an
`AFFECTS` edge from that file node to the corresponding current VDOC desired node.
Custom `--desired` plans replace the default catalog: establish explicit mappings
for their actual goals, rather than guessing which custom node a document satisfies.
Cross-workstream consumers need explicit dependency edges as applicable.

The initial file/draft remains UNKNOWN or REVIEW_REQUIRED. Human approval of the
plan authorizes desired scope; it does not certify document content. Review the
document's sources, resolved scope, remaining questions and cross-document IDs.
Only after the user explicitly accepts that content may the Agent record the
actual review evidence against the desired node. Do not use file existence or a
bare template as passing evidence. CLI does not semantically enforce this rule.

On a later document revision, record `changed` for the verification output so its
consumers require revalidation. Preserve existing review evidence, re-review affected
content and re-prove the relevant goals. If desired scope changes, replan and bind
the document edges to the new desired revision. Never regenerate all documents
merely because a single Workstream was reopened.
