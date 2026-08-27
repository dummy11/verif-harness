# Agent Skill modes

The bundled `verif-harness` Skill provides 31 explicit modes. Invoke one from a
verification project root with the runtime-native syntax, for example:

```text
$verif-harness doctor
```

Kimi Code uses `/skill:verif-harness doctor`. The `$verif-harness` notation in
the catalog below is the Codex spelling of the same runtime-neutral mode.

Write modes read repository instructions and refuse to modify the configured
DUT RTL root. Review and approval remain Human responsibilities.

Use short aliases for interactive work; canonical names remain stable for
existing specifications and automation. Common examples are `test` →
`add-testcase`, `coverage` → `add-coverage-skeleton`, `trace` →
`audit-traceability`, `gate 4` → `stage-gate-review 4`, and `signoff 5` →
`signoff-audit 5`. Workflow control uses `status`, `resume`, `recover`, and
`docs`; the older `workflow-*` spellings remain compatible. Run
`$verif-harness help [name]` for the exact mapping and authority boundary.

<!-- markdownlint-disable MD013 -->

| Mode | Purpose | Typical use | Example |
| --- | --- | --- | --- |
| `init` | Create Stage 0 governance documents and the M1.1 directory scaffold | An approved Stage 0 task is dispatched or recovery is authorized | `$verif-harness init` |
| `add-interface` | Generate reviewed protocol interfaces and UVC landing directories | Interface semantics are approved | `$verif-harness add-interface` |
| `add-shared-pkg` | Generate shared types and packing packages | Multiple UVCs need common transaction types | `$verif-harness add-shared-pkg` |
| `add-uvc-skeleton [name]` | Generate layered UVC class skeletons | Start a new interface agent | `$verif-harness add-uvc-skeleton input` |
| `add-harness-layer` | Generate DUT/TB harness and SVA stubs | Connect read-only DUT ports structurally | `$verif-harness add-harness-layer` |
| `add-env-layer` | Generate env, scoreboard/coverage shells, tests, and thin `tb_top` | Assemble the first UVM environment | `$verif-harness add-env-layer` |
| `finalize-filelist-and-make` | Generate compile-order filelists and a compile-only target | Close the M1.1 compile loop | `$verif-harness finalize-filelist-and-make` |
| `doctor` | Audit config, documents, stage state, legacy files, and RTL dirtiness | Resume or diagnose a project | `$verif-harness doctor` |
| `spec-kit` | Manage the single specification source below the verif-harness control plane | Bootstrap or advance a reviewed Stage specification workflow | `$verif-harness bootstrap` |
| `xverif` | Delegate one reviewed request to the commit-pinned managed xverif CLI or manage its MCP source/profile/project-registration lifecycle | Need deterministic bit/debug/coverage/entry/log/SVA/waveform evidence or Codex/Kimi MCP access | `$verif-harness evidence probe --tool xbit` |
| `wavepeek` | Delegate one bounded query to commit-pinned WavePeek and capture provenance | Need deterministic VCD/FST hierarchy, value, change, property, or transfer evidence | `$verif-harness waveform probe` |
| `add-regression-runner` | Add isolated seeded regression and strict result collection | Move from single tests to repeatable batches | `$verif-harness add-regression-runner` |
| `add-simulator-profile` | Generate a normalized command/capability profile | Add a reviewed simulator configuration without claiming support | `$verif-harness add-simulator-profile` |
| `add-testcase` | Add a test/vseq skeleton to a candidate list | Implement a planned scenario | `$verif-harness add-testcase` |
| `add-coverage-skeleton` | Generate covergroups from exact expressions and plan references | Implement approved functional coverage | `$verif-harness add-coverage-skeleton` |
| `add-assertion-skeleton` | Generate checker/bind skeletons from reviewed properties | Implement an approved assertion plan | `$verif-harness add-assertion-skeleton` |
| `add-refmodel-bridge` | Generate a Syscan or DPI-C structural adapter | Connect an approved Golden model backend | `$verif-harness add-refmodel-bridge` |
| `complete-uvc` | Generate ready/valid driver and monitor behavior from a contract | Replace UVC TODOs after protocol review | `$verif-harness complete-uvc` |
| `complete-scoreboard` | Generate FIFO-aligned exact/masked/tolerance comparisons | Replace scoreboard TODOs after compare-policy review | `$verif-harness complete-scoreboard` |
| `add-ci-hook` | Generate a reviewable GitLab CI or Jenkins fragment | Connect stable local checks to CI | `$verif-harness add-ci-hook` |
| `add-performance-gate` | Evaluate fixed performance contracts from marked logs | Gate bubble, cadence, utilization, or count metrics | `$verif-harness add-performance-gate` |
| `regression-triage` | Group failures and verify same-seed reruns | Diagnose a non-green regression without losing evidence | `$verif-harness regression-triage` |
| `coverage-closure` | Audit functional coverage items, hits, exclusions, and totals | Prepare coverage evidence for freeze review | `$verif-harness coverage-closure` |
| `assertion-closure` | Audit compile/bind/attempt/failure/vacuity evidence | Prepare assertion evidence for freeze review | `$verif-harness assertion-closure` |
| `audit-traceability` | Reconcile tests, manifests, plans, and verification IDs | Check feature-to-evidence closure before a gate | `$verif-harness audit-traceability` |
| `change-control` | Audit post-baseline requests, impact evidence, and Git coverage | Control changes after a reviewed baseline | `$verif-harness change-control` |
| `stage-gate-review <stage>` | Build a Draft stage-gate packet from repository evidence | Present a completed stage for Human review | `$verif-harness stage-gate-review 4` |
| `signoff-audit <stage>` | Audit packet structure and recorded approval metadata | Validate sign-off evidence without granting approval | `$verif-harness signoff-audit 5` |
| `freeze-baseline` | Build a clean-commit SHA-256 freeze candidate manifest | Anchor final reviewed evidence before an authorized tag | `$verif-harness freeze-baseline` |
| `oss-readiness` | Audit community files, examples, CI, paths, and sensitive strings | Prepare a sanitized public repository candidate | `$verif-harness oss-readiness` |
| `patterns [topic]` | Explain implementation and lifecycle patterns | Get guidance without changing files | `$verif-harness patterns regression` |

<!-- markdownlint-enable MD013 -->

## Recommended Stage 0-to-freeze sequence

```text
spec-kit bootstrap
  -> Stage 0 specification / tasks / execution authorization
  -> persistent task runner dispatches reviewed modes, including init
  -> Human Stage 0 review
  -> each Stage specification / tasks / execution authorization
  -> persistent task runner dispatches all reviewed generation/tool/audit modes
  -> speckit.converge verifies owned outputs, evidence, and validation
  -> separate stage-gate-review / signoff-audit / freeze authorization flow
  -> Human freeze approval and separately authorized tag/push
```

At every Stage, the Spec Kit lifecycle creates and reviews the specification,
plan, checklist, and tasks before verif-harness dispatches implementation modes;
The persistent task runner dispatches only the approved `current_task_id`,
records `READY/RUNNING/DONE/BLOCKED`, and never replays `DONE` tasks.
It then converges artifacts and evidence back to the specification. New
projects keep `specs/` as the sole editable requirements authority. Spec Kit is
agentic: its command and review-gate success is not simulation evidence or
Human Stage approval. Workflow-control commands and Human authority boundaries
remain separate from ordinary implementation-task dispatch.

Run `doctor` whenever the current state is unclear. Use `oss-readiness` as a
separate branch when preparing a public export; it does not authorize release.

For the normal user surface, the tool namespaces can be shortened:

```text
$verif-harness probe                         # spec-kit probe
$verif-harness bootstrap                     # spec-kit bootstrap
$verif-harness stage --stage 0 --objective "..."  # spec-kit stage
$verif-harness status [run-id]                     # spec-kit status
$verif-harness resume <run-id> --verdict approve  # spec-kit resume
$verif-harness resume <run-id> --answer "..."     # resume current BLOCKED task only
$verif-harness recover <run-id> --confirm-stale   # confirmed stale run only
$verif-harness docs                                # refresh Chinese mirror
$verif-harness evidence probe --tool xbit     # xverif probe
$verif-harness waveform probe                # wavepeek probe
```

The explicit `spec-kit`, `xverif`, and `wavepeek` forms remain available for
advanced diagnostics and preserve exactly the same contracts.
