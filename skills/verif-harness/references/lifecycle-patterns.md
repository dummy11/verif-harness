# Verification lifecycle patterns

## Contents

1. Authority boundaries
2. Stage-gate input
3. Traceability
4. Evidence strength
5. Gate output

## 1. Authority boundaries

Agents may collect evidence, find inconsistencies, draft change requests, and
generate review packets. Only the designated Human reviewer may approve a gate,
freeze a decision, accept an evidence limitation, or close an open question.

Do not modify frozen Human Decisions or Approval Decisions without the
project's change-request process.

## 2. Stage-gate input

At Stage N exit, review:

- roadmap Stage N goals, deliverables, and exit criteria;
- Provisional decisions whose target is Stage N or earlier;
- all still-open questions that can affect the next stage;
- change requests opened or closed during Stage N;
- regression, Golden, coverage, assertion, performance, and CI evidence as
  applicable;
- RTL dirtiness and evidence/artifact limitations.

The scan must include all governed planning documents, not only roadmap.md.

## 3. Traceability

Maintain mappings among:

- DUT capability and feature ID;
- testcase ID and concrete UVM test class;
- coverage ID/bin and sampling implementation;
- assertion ID/property/checker;
- default or focused regression manifest;
- dynamic evidence.

Name matching proves only structural linkage. Semantic closure requires review
of stimulus, sampling, expected behavior, and dynamic results.

## 4. Evidence strength

Use this order when sources disagree:

1. Archived machine-readable logs/reports tied to commit and seed.
2. CI job result tied to commit.
3. Human-provided report or screenshot with visible scope.
4. Human verbal confirmation.
5. Repository static inference.
6. Plan or intention.

Lower-ranked evidence can still be accepted by the Human reviewer. State its
boundary instead of upgrading it silently.

## 5. Gate output

A Draft packet leaves every criterion and verdict unchecked. It lists the
source decision verbatim, evidence location or absence, and three permitted
Provisional dispositions: keep, upgrade through Human workflow, or downgrade to
an open question.

Approval metadata remains TBD until the Human decision occurs. Apply approved
source-document updates separately, run the Markdown workflow gate, and review
the resulting diff.
