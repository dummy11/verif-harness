---
name: verification-doc-authoring
description: Generate DUT-grounded document-writing-plan nodes for the eight verification documents registered by verif-harness. Use during VDOC planning to analyze current RTL, Design/Micro-architecture/Interface/Register specifications, existing verification artifacts, source gaps, cross-document dependencies, review, freeze, and invalidation rules. Do not use it to write final document bodies or create document-deliverable nodes.
---

# Verification Document Authoring

Generate project-specific `document-writing-plan` nodes, not final verification
documents. The structured `VerificationDocumentAuthoringContract/1` stored on
each node is the source of truth for how that document must later be written.

## Boundary

- Use the eight profiles under `profiles/`; do not invent document names or
  create one copied Skill per document.
- Keep RTL and design specifications read-only. Never manufacture an interface,
  timing/latency rule, register, FSM, protocol constraint, feature, checker,
  threshold, waiver, evidence, or approval.
- Record unavailable, ambiguous, conflicting, template-only, or unobservable
  information in `source_gaps` with its impact and required review.
- Emit only `document-writing-plan` nodes. Do not edit a governed Markdown body,
  run `docs sync`, create `document-deliverable`, implement RTL/SVA/UVM, or grant
  approval/freeze.

## Workflow

1. Read the current project `AGENTS.md`, `.verif-harness/project.json`, current
   VDOC state, open questions/decisions, and registered RTL/spec inputs.
2. Generate the candidate proposal with the integrated engine:

   ```text
   verif-harness plan authoring --output .verif-harness/proposals/vdoc-authoring.json
   ```

   Use `--document <document-key>` only with all of that profile's declared
   dependencies. The engine snapshots real source paths and SHA-256 values,
   extracts the declared DUT top and parseable RTL ports, preserves explicit
   source statements, and creates gaps rather than guessed facts.
3. Read [the contract checklist](references/checklist.md), the selected profile
   files, and any available project sources in depth. Refine the candidate with
   source-anchored project facts when deterministic extraction is incomplete.
   Preserve the profile identity/digest and common industrial rules.
4. Validate and register the candidate through the existing planner:

   ```text
   verif-harness plan VDOC --desired-file .verif-harness/proposals/vdoc-authoring.json
   ```

   Planner acceptance creates review candidates only. The responsible person
   still approves the plans. Formal body authoring starts only after VDOC is
   `ACTIVE`; body acceptance uses a later delivery-only proposal.

## Contract quality

Every node must contain real source requirements/snapshots/gaps, DUT scope,
RTL/spec analysis method, document structure, section-level instructions,
required tables, domain rules, cross-document consistency, traceability,
review roles/criteria, freeze criteria, and change-invalidation rules.

The dependency graph is profile-driven: governance and total plan establish the
baseline; the feature matrix and TB architecture bind the DUT; reference-model,
coverage, and assertion plans specialize checking; testcase planning closes the
loop into regression and evidence. A final document delivery depends on its
corresponding authoring node remaining current and valid.
