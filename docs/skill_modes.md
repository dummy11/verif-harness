# Codex skill modes

The bundled `verif-harness` skill provides 31 explicit modes. Invoke one from a
verification project root, for example:

```text
$verif-harness doctor
```

Write modes read repository instructions and refuse to modify the configured
DUT RTL root. Review and approval remain Human responsibilities.

<!-- markdownlint-disable MD013 -->

| Mode | Purpose | Typical use | Example |
| --- | --- | --- | --- |
| `init` | Create Stage 0 governance documents and the M1.1 directory scaffold | A new project has no harness configuration | `$verif-harness init` |
| `add-interface` | Generate reviewed protocol interfaces and UVC landing directories | Interface semantics are approved | `$verif-harness add-interface` |
| `add-shared-pkg` | Generate shared types and packing packages | Multiple UVCs need common transaction types | `$verif-harness add-shared-pkg` |
| `add-uvc-skeleton [name]` | Generate layered UVC class skeletons | Start a new interface agent | `$verif-harness add-uvc-skeleton input` |
| `add-harness-layer` | Generate DUT/TB harness and SVA stubs | Connect read-only DUT ports structurally | `$verif-harness add-harness-layer` |
| `add-env-layer` | Generate env, scoreboard/coverage shells, tests, and thin `tb_top` | Assemble the first UVM environment | `$verif-harness add-env-layer` |
| `finalize-filelist-and-make` | Generate compile-order filelists and a compile-only target | Close the M1.1 compile loop | `$verif-harness finalize-filelist-and-make` |
| `doctor` | Audit config, documents, stage state, legacy files, and RTL dirtiness | Resume or diagnose a project | `$verif-harness doctor` |
| `spec-kit` | Manage the single specification source below the verif-harness control plane | Bootstrap or advance a reviewed Stage specification workflow | `$verif-harness spec-kit stage` |
| `xverif` | Delegate one reviewed request to the commit-pinned managed xverif CLI tool and capture provenance | Need deterministic bit/debug/coverage/entry/log/SVA/waveform evidence | `$verif-harness xverif probe --tool xbit` |
| `wavepeek` | Delegate one bounded query to commit-pinned WavePeek and capture provenance | Need deterministic VCD/FST hierarchy, value, change, property, or transfer evidence | `$verif-harness wavepeek probe` |
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
spec-kit bootstrap / Stage 0 specification workflow
  -> init
  -> Human Stage 0 review
  -> add-interface / add-shared-pkg / add-uvc-skeleton
  -> add-harness-layer / add-env-layer / finalize-filelist-and-make
  -> add-simulator-profile / complete-uvc / complete-scoreboard
  -> add-testcase / add-coverage-skeleton / add-assertion-skeleton
  -> add-refmodel-bridge / add-regression-runner
  -> xverif as needed for deterministic native evidence
  -> wavepeek as needed for bounded VCD/FST evidence
  -> add-ci-hook / add-performance-gate
  -> regression-triage
  -> audit-traceability / coverage-closure / assertion-closure
  -> change-control / stage-gate-review / signoff-audit
  -> freeze-baseline
  -> Human freeze approval and separately authorized tag/push
```

At every Stage, the Spec Kit lifecycle creates and reviews the specification,
plan, checklist, and tasks before verif-harness dispatches implementation modes;
it then converges artifacts and evidence back to the specification. New
projects keep `specs/` as the sole editable requirements authority. Spec Kit is
agentic: its command and review-gate success is not simulation evidence or
Human Stage approval.

Run `doctor` whenever the current state is unclear. Use `oss-readiness` as a
separate branch when preparing a public export; it does not authorize release.
