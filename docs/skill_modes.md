# Agent Skill modes

## Core control modes

| Mode | CLI | Responsibility |
| --- | --- | --- |
| `bootstrap` | `bootstrap` | Project identity, inventory, capabilities, baseline revision |
| `vplan` | `plan` | Interactive Workstream desired state and Human review |
| `vmodel` | `model` | Read-only typed facts, relations, validity, evidence |
| `record` | `record` | Structured mutation ingress and automatic reconciliation |
| `vcheck` | `check` | Structural reconciliation and change invalidation |
| `vclosure` | `closure` | Minimum next actions across Workstreams |
| `vreason` | `reason` | Backend-neutral reasoning request for ambiguity |

Exact aliases include `review` → `plan review` and `freeze` → `plan freeze`.

## Capability modes

Lower-level generators and evidence tools remain independently reviewable:
`add-interface`, `add-shared-pkg`, `add-uvc-skeleton`, `add-harness-layer`,
`add-env-layer`, `finalize-filelist-and-make`, `xverif`, `wavepeek`, regression,
simulator, testcase, coverage, assertion, reference-model, CI, performance,
triage, traceability, change-control, sign-off, freeze-manifest, and public
release audits.

VClosure recommends capabilities; it does not execute them without Agent/User
authority. Generated files are candidates for review and DUT RTL stays read-only.
