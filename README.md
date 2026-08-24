# verif-harness

**verif-harness is an agent-neutral RTL verification control plane and a
reusable SystemVerilog/UVM DUT integration framework. Codex and Kimi Code are
its supported agent runtimes; the deterministic core remains usable through
CLI and CI workflows without an agent.**

It keeps structural integration in one place: clocks and resets, protocol
interfaces, DUT instantiation, tie-offs, adapters, assertions, bind targets,
and virtual-interface publication. Tests and UVM environments stay above that
boundary; DUT RTL stays read-only.

## Why?

Verification projects often scatter DUT wiring across `tb_top`, tests,
packages, and simulator scripts. That makes compile order fragile and creates
hidden dependencies. verif-harness defines a narrow, reviewable integration
layer and provides templates, checks, an executable FIFO example, and an Agent
Skill that applies the same rules consistently.

## Architecture

```text
                     +-------------------+
                     |      UVM Test     |
                     +---------+---------+
                               |
                     +---------v---------+
                     |      UVM Env      |
                     +---------+---------+
                               |
                    config_db / virtual IF
                               |
+------------------------------------------------+
|                verif-harness                   |
|                                                |
|  clock/reset       protocol interfaces         |
|  DUT instance      tie-offs and adapters       |
|  SVA / bind        config_db publishing        |
+-----------------------+------------------------+
                        |
                 +------v------+
                 |     DUT     |
                 +-------------+
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for ownership and compile-order rules.

## Agent and runtime model

verif-harness is not a standalone AI agent. It supplies the verification
policy, staged workflow, mode contracts, generators, checks, and tool adapters
that an agent or a Human operator executes. Codex and Kimi Code use the same
Skill and verification contracts through runtime-specific invocation syntax.

The agent-neutral core includes contracts, generators, validation scripts, CLI
adapters, and CI workflows. These components can be invoked manually or by
automation without an Agent. Spec Kit artifacts are portable files, while the
current reviewed-task-to-mode automatic dispatch is implemented by the
verif-harness Skill. Another agent runtime can integrate through an adapter
that preserves the same mode inputs, outputs, evidence, and Human approval
boundaries, but no other runtime is claimed as supported until that adapter is
implemented and validated.

```text
Human authority
      |
      v
Codex or Kimi Code Agent
      |
      v
verif-harness Skill / control plane
      |
      +--> Spec Kit specification and task workflow
      +--> deterministic CLI, generators, checks, and CI
      +--> xverif / WavePeek / simulators / EDA tools
```

## Features

- Thin `tb_top` and explicit harness ownership.
- Reusable DUT-integration templates and an additive generator.
- Interface, SVA, bind, filelist, and smoke-test patterns.
- A license-free `simple_fifo` example for Verilator.
- Simulator-independent Python structure and public-release checks.
- A bundled 31-mode Agent Skill for Stage 0 through verification freeze.
- A pinned GitHub Spec Kit specification plane governed by the verif-harness
  top-level control plane.
- A fail-closed CLI adapter for deterministic tools from
  `https://github.com/BLANK2077/xverif.git`.
- Commit-pinned WavePeek integration for bounded VCD/FST inspection.
- GitHub CI, documentation deployment, and tagged-release automation.

## Requirements

- Python 3.11 or newer (the default setup installs Spec Kit and xverif MCP).
- GNU Make.
- Verilator 5.x for the open-source example.
- A UVM-capable commercial simulator for full UVM regressions.

Commercial simulator licenses, scheduler configuration, and private wrappers
are intentionally not included.

## Quick start

```bash
git clone https://github.com/dummy11/verif-harness.git
cd verif-harness
./scripts/setup.sh --runtime codex
```

选择 Kimi Code 时使用：

```bash
./scripts/setup.sh --runtime kimi
```

`setup.sh` 会安装全部默认依赖（Spec Kit、xverif CLI、xverif MCP 和
WavePeek），创建当前 runtime 的 Skill 入口，然后直接启动对应的 Agent CLI。
进入 Codex 后调用 `$verif-harness`；进入 Kimi Code 后调用
`/skill:verif-harness`。

如果只需要安装并运行开源 smoke example，不启动 Agent：

```bash
./scripts/setup.sh --no-agent
./scripts/run_example.sh
```

Expected result with Verilator installed:

```text
SIMPLE_FIFO_SMOKE PASS
```

## Install in the current working directory

```bash
git clone https://github.com/dummy11/verif-harness.git .
./scripts/setup.sh --runtime codex
```

Kimi Code 使用：

```bash
./scripts/setup.sh --runtime kimi
```

`setup.sh` 默认安装所有 commit-pinned integrations。依赖保留在 Git 忽略的
`.deps/` 下，仍然属于独立的上游项目，不会被 vendored 进 verif-harness。
安装包括：

- Spec Kit 规格工作流；
- xverif CLI 和 `xverif_mcp` 源码/launcher；
- Python `mcp[cli]` SDK；
- VCD/FST-only WavePeek binary。

默认 setup 不覆盖已有的受管 checkout；如果检测到 dirty、错误 commit 或错误
license，会 fail closed。只安装依赖而不启动 Agent 时使用 `--no-agent`。

安装完成后，setup 已经进入所选 Agent CLI。不要退出 CLI 回到 shell 执行下面的
Python wrapper；在 CLI 内调用对应的 Skill：

```text
# Codex CLI
$verif-harness spec-kit probe
$verif-harness spec-kit bootstrap --project-root . --integration codex

# Kimi Code CLI
/skill:verif-harness spec-kit probe
/skill:verif-harness spec-kit bootstrap --project-root . --integration kimi
```

Python wrapper 仍可用于 CI 或无 Agent 的自动化路径；这不是 setup 后的正常交互
入口。

verif-harness remains the top-level policy, Stage, dispatch, and traceability
control plane. Spec Kit manages constitution/spec/plan/tasks/checklist artifacts;
xverif, WavePeek, and simulators produce bounded evidence. After execution
authorization, `speckit.implement` dispatches each reviewed task's named mode
exactly once; convergence requires its owned outputs, evidence paths, and
validation command, so successful workflows need no duplicate manual calls.
Human reviewers keep
semantic decisions, waivers, gates, sign-off, and freeze authority. See
[integrations/spec-kit/README.md](integrations/spec-kit/README.md).

## Generate a DUT integration skeleton

```bash
python3 scripts/verif_harness.py init my_dut --output ./work
```

The command creates additive, non-overwriting files under `interfaces/`,
`sva/`, `bind/`, `tb/`, and `filelists/`. It does not parse or modify DUT RTL.
Review and replace every TODO against the approved DUT specification.

## Delegate to xverif

`verif-harness` remains the planning and governance framework. Its CLI adapter
can execute one reviewed operation from the managed xverif checkout while
capturing argv, Git identity, wrapper and artifact hashes, and native output:

```bash
python3 scripts/verif_harness.py xverif probe \
  --tool xbit
```

xverif is a tool suite (`xbit`, `xdebug`, `xcov`, `xentry`, `xloc`, `xsva`, and
`xwaveform`), not a single `xverif` executable. See
[docs/xverif_integration.md](docs/xverif_integration.md).
The pinned checkout is a managed dependency, not vendored verif-harness
source; attribution and proprietary-EDA boundaries are recorded in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The same checkout provides the managed FastMCP server. The default setup already
installs its source and `mcp[cli]`; create a non-secret profile:

```bash
python3 scripts/verif_harness.py xverif mcp install --project-root .
python3 scripts/verif_harness.py xverif mcp configure \
  --project-root . --runtime codex --backend direct
python3 scripts/verif_harness.py xverif mcp status --project-root .
```

Use `--runtime kimi` for Kimi Code. Runtime registration remains host-managed;
after registering the stdio server, call `xverif_ping` and then `xverif_tools`.

## Inspect a waveform with WavePeek

WavePeek is a separate deterministic CLI for bounded VCD/FST queries. After
managed setup, probe it or execute a reviewed request:

```bash
python3 scripts/verif_harness.py wavepeek probe
python3 scripts/verif_harness.py wavepeek run \
  --project-root . \
  --request skills/verif-harness/wavepeek/wavepeek-request.example.json \
  --out-dir artifacts/wavepeek/schema-smoke
```

The adapter captures Git and binary identity plus stdout/stderr hashes. Its
PASS is execution evidence, not a waveform interpretation or sign-off. See
[docs/wavepeek_integration.md](docs/wavepeek_integration.md).

## Adding a new DUT

1. Generate or create `tb/harness/<dut>_tb_harness.sv`.
2. Instantiate protocol interfaces in the harness.
3. Instantiate the DUT and preserve its original port order.
4. Connect clock/reset and document tie-offs.
5. Add checker and bind targets.
6. Publish virtual interfaces through `uvm_config_db` when UVM is enabled.
7. Add an explicit compile-order filelist.
8. Keep `<dut>_tb_top.sv` thin.
9. Add and run a deterministic smoke test.

See [docs/dut_integration.md](docs/dut_integration.md) for the complete review
checklist.

## Simulator support

| Simulator | Scope | Status |
| --- | --- | --- |
| Verilator 5.x | Non-UVM example, lint, assertions | Open CI target |
| Synopsys VCS | Full SystemVerilog/UVM flow | Local/commercial integration |
| Questa | Full SystemVerilog/UVM flow | Community validation wanted |
| Xcelium | Full SystemVerilog/UVM flow | Community validation wanted |

CI success proves the open-source checks and example only. It does not claim a
commercial-simulator regression passed. See
[docs/simulator_support.md](docs/simulator_support.md).

## Repository structure

```text
docs/                    Design and integration documentation
examples/simple_fifo/    License-free executable example
filelists/               Shared simulator option guidance
scripts/                 Generator, checks, and runner wrappers
skills/verif-harness/    Reusable Codex/Kimi Code Skill
templates/dut/           Standalone DUT integration templates
tests/                   Python and structural tests
.github/                 CI, Pages, release, issue, and PR automation
deps/                    Reviewed optional-dependency locks and schemas
.deps/                   Git-ignored managed dependency checkouts
```

## Supported agent runtimes

The reusable Skill is under `skills/verif-harness/`. Follow
[Install in the current working directory](#install-in-the-current-working-directory)
to expose it at the runtime-native project path.

Codex:

```text
$verif-harness Integrate this DUT into a verification environment.
```

Kimi Code:

```text
/skill:verif-harness Integrate this DUT into a verification environment.
```

The Skill reads repository instructions and RTL ports, but preserves the rule
that DUT RTL and Human approval decisions are outside agent authority. Codex
and Kimi Code are supported Agent runtimes, not dependencies of the
deterministic CLI and CI core. Integrations for additional Agent runtimes must
retain the same contracts and authority boundaries.
The bundled Chinese [skill README](skills/verif-harness/README.md) provides the
quick-start catalog, while its
[complete user guide](skills/verif-harness/docs/user_guide.md) documents every
mode's inputs, outputs, usage, scenarios, and Human review points.
See [docs/skill_modes.md](docs/skill_modes.md) for every mode, its purpose,
usage, and recommended lifecycle position.

## Documentation

Start at the [documentation home](docs/index.md). The MkDocs configuration
builds the published `docs/` content as a documentation site. The catalog below
links every maintained Markdown document in the repository except this README.

### Architecture, integration, and operation

| Document | Contents |
| --- | --- |
| [Canonical architecture](ARCHITECTURE.md) | Ownership boundaries, compile order, lifecycle planes, and public project structure. |
| [Architecture summary](docs/architecture.md) | Short introduction to harness ownership and the read-only DUT boundary. |
| [Harness design](docs/harness_design.md) | Thin-top rule and structural versus behavioral responsibilities. |
| [DUT integration](docs/dut_integration.md) | Required DUT inputs, additive generation, review checklist, and smoke validation. |
| [Interface guidelines](docs/interface_guidelines.md) | Interface declaration, modport, naming, sampling, and layering rules. |
| [Bind and SVA](docs/bind_and_sva.md) | Assertion identity, clocks, reset semantics, bind order, engagement, and closure evidence. |
| [UVM integration](docs/uvm_integration.md) | Virtual interfaces, UVM component layering, config publication, and full-simulator boundary. |
| [Compile flow](docs/compile_flow.md) | Canonical dependency order and repository-relative filelist expectations. |
| [Simulator support](docs/simulator_support.md) | Tested public scope and commercial/community simulator status. |
| [Tool versions](docs/tool_versions.md) | Supported tool baselines and installation guidance. |
| [Agent runtime and model switching](docs/runtime_switching.md) | Bootstrap detection, Codex/Kimi Code selection, K3 model changes, and runtime migration. |
| [Coding style](docs/coding_style.md) | SystemVerilog, Python, shell, and documentation conventions. |
| [Troubleshooting](docs/troubleshooting.md) | Setup, dependency, simulator, example, and public-audit recovery. |
| [Roadmap](docs/roadmap.md) | Planned framework releases and capability evolution. |
| [Public release checklist](docs/public_release_checklist.md) | Human-reviewed security, licensing, reproducibility, and release requirements. |

### Skill, lifecycle, tools, and examples

| Document | Contents |
| --- | --- |
| [Skill mode catalog](docs/skill_modes.md) | All 31 public modes, purposes, lifecycle positions, and example invocations. |
| [Chinese Skill quick start](skills/verif-harness/README.md) | 中文模式目录、快速用法和权限边界。 |
| [Chinese complete user guide](skills/verif-harness/docs/user_guide.md) | 中文 Stage 0→freeze 流程及每个模式的输入、输出、用法、场景和人工检查点。 |
| [Chinese Skill architecture](skills/verif-harness/docs/architecture.md) | 中文控制面、规格面、能力面、证据面和人工权限模型。 |
| [Chinese Skill troubleshooting](skills/verif-harness/docs/troubleshooting.md) | 中文 false-green 风险、常见故障和恢复方式。 |
| [Spec Kit integration](integrations/spec-kit/README.md) | Spec authority, bootstrap/stage/resume/status commands, task dispatch, convergence, and Human gates. |
| [Spec Kit bundle](integrations/spec-kit/bundle/README.md) | Local RTL bundle composition and pre-catalog publication boundary. |
| [xverif integration](docs/xverif_integration.md) | Managed CLI/MCP dependency, install/configure/use contract, provenance, evidence, and ownership split. |
| [WavePeek integration](docs/wavepeek_integration.md) | Managed VCD/FST CLI, bounded query contract, provenance, and FSDB boundary. |
| [simple_fifo example](examples/simple_fifo/README.md) | License-free executable harness example and expected smoke result. |

### Project governance and community

| Document | Contents |
| --- | --- |
| [Repository Agent instructions](AGENTS.md) | Public-data restrictions, architecture rules, optional-dependency boundaries, and required checks. |
| [Contributing](CONTRIBUTING.md) | Contribution workflow, validation, dependency-upgrade rules, and PR expectations. |
| [Governance](GOVERNANCE.md) | Maintainer authority and decisions requiring explicit review. |
| [Code of Conduct](CODE_OF_CONDUCT.md) | Expected community behavior and enforcement process. |
| [Security policy](SECURITY.md) | Supported versions and private vulnerability/disclosure reporting. |
| [Support](SUPPORT.md) | Supported public channels and out-of-scope commercial EDA support. |
| [Changelog](CHANGELOG.md) | Released and unreleased user-visible changes. |
| [Third-party notices](THIRD_PARTY_NOTICES.md) | Spec Kit, xverif, WavePeek, toolchain, license, and ownership notices. |
| [Apache-2.0 License](LICENSE) | Project copyright and redistribution terms. |
| [Pull request template](.github/pull_request_template.md) | Required change summary, validation, security, and review-boundary checklist. |

### Skill implementation contracts

The [top-level Skill contract](skills/verif-harness/SKILL.md) defines dispatch,
global invariants, resources, and the complete authority boundary. Each mode
with specialized behavior has its own mandatory implementation contract:

| Mode contract | Contents |
| --- | --- |
| [`init`](skills/verif-harness/stage0/INSTRUCTIONS.md) | Stage 0 governance bootstrap and M1.1 scaffold. |
| [`add-interface`](skills/verif-harness/add-interface/INSTRUCTIONS.md) | Protocol interface and UVC landing-directory generation. |
| [`add-shared-pkg`](skills/verif-harness/add-shared-pkg/INSTRUCTIONS.md) | Shared typedef, enum, and pack/unpack packages. |
| [`add-uvc-skeleton`](skills/verif-harness/add-uvc-skeleton/INSTRUCTIONS.md) | Layered UVC class skeletons. |
| [`add-harness-layer`](skills/verif-harness/add-harness-layer/INSTRUCTIONS.md) | DUT/TB harness and SVA structural stubs. |
| [`add-env-layer`](skills/verif-harness/add-env-layer/INSTRUCTIONS.md) | Environment, scoreboard, coverage, base test, and top skeletons. |
| [`finalize-filelist-and-make`](skills/verif-harness/finalize-filelist-and-make/INSTRUCTIONS.md) | Canonical filelists and compile-only target. |
| [`doctor`](skills/verif-harness/doctor/INSTRUCTIONS.md) | Read-only project health audit. |
| [`spec-kit`](skills/verif-harness/spec-kit/INSTRUCTIONS.md) | Specification workflow, task dispatch, convergence, and authority rules. |
| [`xverif`](skills/verif-harness/xverif/INSTRUCTIONS.md) | Allowlisted deterministic xverif CLI plus MCP source/profile lifecycle. |
| [`wavepeek`](skills/verif-harness/wavepeek/INSTRUCTIONS.md) | Bounded deterministic waveform query execution. |
| [`add-regression-runner`](skills/verif-harness/add-regression-runner/INSTRUCTIONS.md) | Isolated regression launch, collection, and same-seed rerun. |
| [`add-simulator-profile`](skills/verif-harness/add-simulator-profile/INSTRUCTIONS.md) | Reviewed simulator profile generation. |
| [`add-testcase`](skills/verif-harness/add-testcase/INSTRUCTIONS.md) | Additive test/vseq skeleton and candidate registration. |
| [`add-coverage-skeleton`](skills/verif-harness/add-coverage-skeleton/INSTRUCTIONS.md) | Explicit-contract coverpoints, bins, and crosses. |
| [`add-assertion-skeleton`](skills/verif-harness/add-assertion-skeleton/INSTRUCTIONS.md) | Explicit-contract SVA checker and optional bind. |
| [`add-refmodel-bridge`](skills/verif-harness/add-refmodel-bridge/INSTRUCTIONS.md) | Structural Syscan or DPI-C reference-model bridge. |
| [`complete-uvc`](skills/verif-harness/complete-uvc/INSTRUCTIONS.md) | Reviewed ready/valid driver and monitor behavior. |
| [`complete-scoreboard`](skills/verif-harness/complete-scoreboard/INSTRUCTIONS.md) | FIFO alignment and explicit comparison policies. |
| [`add-ci-hook`](skills/verif-harness/add-ci-hook/INSTRUCTIONS.md) | GitLab CI or Jenkins fragment generation. |
| [`add-performance-gate`](skills/verif-harness/add-performance-gate/INSTRUCTIONS.md) | Deterministic performance-contract evaluation. |
| [`regression-triage`](skills/verif-harness/regression-triage/INSTRUCTIONS.md) | Signature grouping and same-seed failure evidence. |
| [`coverage-closure`](skills/verif-harness/coverage-closure/INSTRUCTIONS.md) | Coverage-plan, hit, exclusion, waiver, and database audit. |
| [`assertion-closure`](skills/verif-harness/assertion-closure/INSTRUCTIONS.md) | Compile, bind, attempt, failure, vacuity, and waiver audit. |
| [`audit-traceability`](skills/verif-harness/audit-traceability/INSTRUCTIONS.md) | Manifest, test, plan-ID, and feature traceability audit. |
| [`change-control`](skills/verif-harness/change-control/INSTRUCTIONS.md) | Post-baseline change-request evidence audit. |
| [`stage-gate-review`](skills/verif-harness/stage-gate-review/INSTRUCTIONS.md) | Draft Stage gate packet construction. |
| [`signoff-audit`](skills/verif-harness/signoff-audit/INSTRUCTIONS.md) | Sign-off packet, manifest, approval metadata, and RTL-scope audit. |
| [`freeze-baseline`](skills/verif-harness/freeze-baseline/INSTRUCTIONS.md) | Clean-commit, hash-anchored freeze candidate manifest. |
| [`oss-readiness`](skills/verif-harness/oss-readiness/INSTRUCTIONS.md) | Public structure, reproducibility, and sensitive-data audit. |

### Skill reference and template documents

| Document | Contents |
| --- | --- |
| [Stage 1 patterns](skills/verif-harness/references/stage1-patterns.md) | Compile order, layering, bind, packaging, and M1.1 conventions. |
| [Implementation patterns](skills/verif-harness/references/implementation-patterns.md) | Explicit contracts for Stage 2+ generation and evidence. |
| [Regression patterns](skills/verif-harness/references/regression-patterns.md) | Result records, seeds, isolation, reruns, and evidence rules. |
| [Lifecycle patterns](skills/verif-harness/references/lifecycle-patterns.md) | Traceability, change control, gates, sign-off, and freeze rules. |
| [xverif adapter contract](skills/verif-harness/references/xverif-adapter-contract.md) | Request/result schema, native outputs, provenance, and fail-closed behavior. |
| [WavePeek adapter contract](skills/verif-harness/references/wavepeek-adapter-contract.md) | JSON/JSONL integrity, provenance, bounded paths, and authority boundary. |
| [Document conventions](skills/verif-harness/assets/doc-conventions.md) | Lifecycle headings and review-block conventions for generated documents. |
| [Review block](skills/verif-harness/assets/review-block.md) | Reusable Human review metadata template. |
| [Stage gate re-review template](skills/verif-harness/assets/stage_gate_re_review_template.md) | Provisional-decision and open-question re-review structure. |
| [Stage review packet template](skills/verif-harness/assets/stage_review_packet_template.md) | Stage deliverable, evidence, finding, and approval packet structure. |

### Spec Kit command and authoring templates

| Document | Contents |
| --- | --- |
| [`speckit.implement` command](integrations/spec-kit/preset/rtl-verification/commands/speckit.implement.md) | Reviewed task dispatch and convergence command contract. |
| [Constitution template](integrations/spec-kit/preset/rtl-verification/templates/constitution-template.md) | Verification governance and immutable authority principles. |
| [Specification template](integrations/spec-kit/preset/rtl-verification/templates/spec-template.md) | Stage-scoped requirements, decisions, risks, and evidence expectations. |
| [Plan template](integrations/spec-kit/preset/rtl-verification/templates/plan-template.md) | Technical context, design structure, and validation planning. |
| [Tasks template](integrations/spec-kit/preset/rtl-verification/templates/tasks-template.md) | Mode-owned tasks, outputs, validation commands, and evidence paths. |
| [Checklist template](integrations/spec-kit/preset/rtl-verification/templates/checklist-template.md) | Requirement-quality checks before implementation dispatch. |

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). Contributions must use neutral example
names and pass the public-release audit; never submit proprietary RTL, logs,
URLs, license configuration, or specifications.

## License

Licensed under Apache License 2.0. See [LICENSE](LICENSE).
