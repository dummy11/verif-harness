# Authoring contract review checklist

Use this checklist before registering a `DesiredStateProposal/1`.

## Grounding and non-fabrication

- The project, DUT top, RTL/spec roots, VDOC revision, source paths and SHA-256
  values are from the current project.
- RTL observations and specification requirements are visibly distinct.
- Interfaces, clock/reset, latency, CSR, state/FSM/FIFO/pipeline/resource,
  error/interrupt and protocol facts have source IDs and anchors.
- Every missing, ambiguous, conflicting, template-only or unobservable input is
  a `source_gap`; no generic ASIC text is presented as a DUT fact.

## Authoring completeness

- The selected profile matches the registry document key, filename, node key and
  profile digest.
- Required sections have section-level inputs and instructions.
- Required tables have columns sufficient for traceability and engineering
  review, not merely headings.
- Domain rules cover the actual document discipline: architecture, reference
  model/compare, coverage, assertion/property or testcase/regression as relevant.
- Review roles/criteria, freeze criteria and change-invalidation rules are
  explicit and do not grant approval.

## Cross-document closure

- Dependencies form the profile DAG and do not create a cycle.
- Requirement -> Feature -> Test/Assertion/Coverage/Reference Model/Regression ->
  Evidence/Traceability uses stable project IDs.
- TB timing/observation, compare policy, property responsibility, coverage
  sampling and testcase expected checks share one current DUT interpretation.
- The proposal contains only `document-writing-plan`; no final Markdown body,
  `document-deliverable`, PASS evidence, waiver or freeze conclusion is present.
