# verif-harness 使用指南

`verif-harness` 是面向 RTL module-level verification 的 Agent Skill，支持
Codex 与 Kimi Code，覆盖
Stage 0 文档基线、UVM/harness 实现、Golden 对拍、coverage/assertion、回归、
CI、sign-off 和 verification freeze candidate。

它包含 31 个模式。所有写模式默认只增不覆盖；DUT RTL、Human Decisions、
waiver、stage gate 和最终 freeze approval 始终在 Human 权限边界内。

## 基本使用

在验证项目根目录调用：

```text
$verif-harness doctor
$verif-harness probe
$verif-harness bootstrap
$verif-harness stage --stage 0 --objective "建立 Stage 0 规格基线"
$verif-harness evidence probe --tool xbit
$verif-harness waveform probe
$verif-harness add-testcase
$verif-harness stage-gate-review 4
```

上面是 Codex 语法；Kimi Code 使用 `/skill:verif-harness <mode>`。两者调用
同一份模式合同，不因 Kimi Code 内选择 K3 或其他模型而改变规格与证据语义。

对 Spec Kit 工作流，推荐使用短命令，不必记住实现域名：

```text
$verif-harness bootstrap          # 内部：spec-kit bootstrap
$verif-harness probe              # 内部：spec-kit probe
$verif-harness stage --stage 0   # 内部：spec-kit stage
$verif-harness workflow-status    # 内部：spec-kit status
$verif-harness workflow-resume <run-id> --verdict approve  # 每次只恢复当前 gate
$verif-harness evidence probe --tool xbit  # 内部：xverif probe
$verif-harness waveform probe             # 内部：wavepeek probe
```

显式 `spec-kit` 形式仍保留给高级诊断和底层调试。

未指定模式时：

- 存在 `.harness-config.json`：执行只读 `doctor`。
- 不存在 `.harness-config.json` 且无 `.specify/`：从 `spec-kit bootstrap` 开始。
- 已有 `.specify/`：由 reviewed Stage 0 task 在 `speckit.implement` 中自动调度
  `init`；不要绕过 gate 直接开始。
- 状态不明确时只报告冲突，不自动执行写模式。

## 31 个模式

<!-- markdownlint-disable MD013 -->

| 模式 | 用途 | 使用场景 | 示例 |
| --- | --- | --- | --- |
| `init` | 建立 Stage 0 文档、治理和目录骨架 | Stage 0 task 已授权分发或 recovery 已批准 | `$verif-harness init` |
| `add-interface` | 生成协议 interface 和 UVC 目录 | 接口规格已评审 | `$verif-harness add-interface` |
| `add-shared-pkg` | 生成共享 typedef/enum 和打包 package | 多个 UVC 需要公共类型 | `$verif-harness add-shared-pkg` |
| `add-uvc-skeleton [name]` | 生成 driver/monitor/sequencer/agent 骨架 | 建立一个新 UVC | `$verif-harness add-uvc-skeleton input` |
| `add-harness-layer` | 生成 DUT/TB harness 和 SVA stub | 连接 DUT、interface 和 checker | `$verif-harness add-harness-layer` |
| `add-env-layer` | 生成 env、scoreboard/coverage shell、base test 和 `tb_top` | 建立最小 UVM 顶层 | `$verif-harness add-env-layer` |
| `finalize-filelist-and-make` | 生成规范 filelist 和 compile-only target | 闭合首次编译 | `$verif-harness finalize-filelist-and-make` |
| `doctor` | 只读检查配置、阶段、文档和 RTL dirtiness | 接手、恢复或诊断项目 | `$verif-harness doctor` |
| `spec-kit` | 在 verif-harness 顶层控制面下管理规格生命周期 | 建立或推进 Stage 规格驱动流程 | `$verif-harness bootstrap` |
| `xverif` | 通过受控 CLI adapter 或 MCP profile 调用固定版本 xverif | bit/debug/coverage/SVA/日志等事实查询 | `$verif-harness evidence probe --tool xbit` |
| `wavepeek` | 通过受控 CLI adapter 调用固定版本 WavePeek | 对 VCD/FST 做有界、可复现的波形查询 | `$verif-harness waveform probe` |
| `add-regression-runner` | 添加隔离回归、seed、结果收集和失败重跑 | 从单测扩展到批量回归 | `$verif-harness add-regression-runner` |
| `add-simulator-profile` | 生成 simulator command/capability profile | 增加一个评审后的 simulator 配置 | `$verif-harness add-simulator-profile` |
| `add-testcase` | 生成 test/vseq 并加入 candidate list | 实现一个计划内场景 | `$verif-harness add-testcase` |
| `add-coverage-skeleton` | 从显式合约生成 covergroup/bin/cross | coverage plan 已明确 | `$verif-harness add-coverage-skeleton` |
| `add-assertion-skeleton` | 从显式 property 生成 checker/bind | assertion plan 已明确 | `$verif-harness add-assertion-skeleton` |
| `add-refmodel-bridge` | 生成 Syscan 或 DPI-C 结构适配层 | 接入 Golden/reference model | `$verif-harness add-refmodel-bridge` |
| `complete-uvc` | 生成 ready/valid source driver 和 monitor 行为 | UVC 骨架需要具体握手实现 | `$verif-harness complete-uvc` |
| `complete-scoreboard` | 生成 FIFO 对齐和 exact/masked/tolerance compare | compare policy 已评审 | `$verif-harness complete-scoreboard` |
| `add-ci-hook` | 生成 GitLab CI 或 Jenkins fragment | 本地回归稳定后接 CI | `$verif-harness add-ci-hook` |
| `add-performance-gate` | 按固定合约检查性能记录 | 检查 bubble、cadence、utilization 和 timing | `$verif-harness add-performance-gate` |
| `regression-triage` | 聚类失败并验证同 seed 重跑 | regression 非全绿 | `$verif-harness regression-triage` |
| `coverage-closure` | 审计 coverage hit、exclusion、waiver 和 totals | coverage freeze review 前 | `$verif-harness coverage-closure` |
| `assertion-closure` | 审计 compile/bind/attempt/failure/vacuity | assertion freeze review 前 | `$verif-harness assertion-closure` |
| `audit-traceability` | 审计 feature、test、manifest、coverage/assertion ID | stage gate 前检查追踪闭环 | `$verif-harness audit-traceability` |
| `change-control` | 审计 baseline 后 CR、影响和 Git diff | frozen baseline 后发生变更 | `$verif-harness change-control` |
| `stage-gate-review <stage>` | 生成 Draft stage-gate packet | Stage N 完成后交 Human review | `$verif-harness stage-gate-review 4` |
| `signoff-audit <stage>` | 审计 sign-off packet 和已记录审批 | 最终签核复核 | `$verif-harness signoff-audit 5` |
| `freeze-baseline` | 生成 clean-commit SHA-256 freeze manifest | 最终 Human freeze review 前 | `$verif-harness freeze-baseline` |
| `oss-readiness` | 审计公开仓库文件、CI、路径和敏感信息 | 准备脱敏后的公开 export | `$verif-harness oss-readiness` |
| `patterns [topic]` | 查询实现和生命周期模式 | 只需要指导、不修改项目 | `$verif-harness patterns regression` |

<!-- markdownlint-enable MD013 -->

## 推荐入口

- 完整 0→freeze 操作顺序：[docs/user_guide.md](docs/user_guide.md)
- 模式分层和证据流：[docs/architecture.md](docs/architecture.md)
- 常见失败与恢复方法：[docs/troubleshooting.md](docs/troubleshooting.md)
- Agent 执行规则：[SKILL.md](SKILL.md)

## Spec Kit 集成

```text
verif-harness 顶层控制面
   ↓
Spec Kit 规格面
   ↓
verif-harness modes 执行能力面
   ↓
xverif / WavePeek / EDA 证据面
   ↓
Human 权限面
```

Spec Kit 管理 constitution、spec、plan、checklist、tasks、analyze、implement
dispatch 和 converge；verif-harness 仍负责 Stage policy、能力选择、traceability
和权限边界。新项目以 `specs/` 为唯一可编辑规格事实源；已批准项目作为不可变
baseline 导入。Spec Kit workflow success 不是仿真证据或审批。

reviewed task 必须声明 verif-harness mode、owned outputs、evidence 和
validation。Codex 以 `$verif-harness` 调用，Kimi Code 以
`/skill:verif-harness` 调用。execution gate 后，`speckit.implement` 自动分发
每个 task mode 一次；
正常路径不需要用户重复手动调用。缺少产物或 validation 失败时，task 保持
incomplete 并由 `converge` 记录偏差。该规则适用于所有被 task 声明的 mode，不只
适用于 `init`；workflow control 和 Human authority 命令仍遵守各自独立边界。

完整仓库中使用固定版本：

```bash
./scripts/setup.sh --isolation managed --runtime codex
```

`setup.sh --isolation managed --runtime codex|kimi` 默认先安装固定归档哈希的
CPython 和完整 artifact-hash lock 的 `mcp[cli]` 环境，再安装 Spec Kit、xverif CLI/MCP
和 WavePeek，然后创建 runtime-native Skill 入口并直接启动对应 Agent CLI。
Codex 中调用 `$verif-harness <mode>`，Kimi Code 中调用
`/skill:verif-harness <mode>`。自动化或只做依赖安装时使用
`./scripts/setup.sh --no-agent`。

setup 同时把面向用户的回复语言默认设为简体中文：Codex 使用项目级
`developer_instructions`，Kimi Code 使用 `.kimi-code/AGENTS.md`，无需执行会阻塞 TUI
的启动 prompt。代码、标识符、命令、路径、配置键、协议名和原始日志保持原文；用户
明确指定其他语言时，以用户要求为准。Stage 0 仍独占根目录 `AGENTS.md` 的生成。

setup 在启动 Agent 前打印 required/current/status 版本清单；也可独立运行
`./scripts/runtime-versions`，用 `--verbose` 显示路径或用 `--json` 供 CI 采集。

进入 CLI 后，正常入口是 Skill 调用：

```text
# Codex
$verif-harness probe
$verif-harness bootstrap
$verif-harness stage --stage 1 --objective "最小可运行环境"

# Kimi Code
/skill:verif-harness probe
/skill:verif-harness bootstrap
/skill:verif-harness stage --stage 1 --objective "最小可运行环境"
```

正常 setup 流程已选择 workspace 与 runtime，Skill 命令继承当前目录并自动解析唯一
runtime marker；仅跨项目自动化、恢复或 marker 歧义时才增加显式覆盖参数。

`python3 scripts/verif_harness.py ...` 仅作为 CI、脚本自动化或没有 Agent CLI 时的
底层 wrapper 入口，不是 setup 后的默认交互方式。

## xverif 集成

```text
Codex / Kimi Code Agent
   ↓
verif-harness Skill / framework
   ↓
CLI adapter or MCP runtime profile
   ↓
xverif tools/* or xverif_mcp
```

`verif-harness` 决定验证阶段、任务语义和人工边界；adapter 只执行严格 JSON
request 并归档 argv、Git commit、wrapper hash、stdout/stderr 与 artifact hash；
xverif CLI 和 xverif_mcp 执行底层确定性操作。权威上游是
`https://github.com/BLANK2077/xverif.git`。xverif 是工具族，不假设存在名为
`xverif` 的统一 executable。

在完整 `verif-harness` 仓库中，一次性安装固定版本：

```bash
./scripts/setup.sh --isolation managed --runtime codex
```

安装器读取 `deps/xverif.lock.json`，把独立 checkout 原子安装到 Git 忽略的
`.deps/xverif`，并校验 origin、完整 commit、clean 状态、MIT License hash、
七个 wrapper、MCP package layout、`tools/xverif-mcp` launcher 和真实 `xbit`
smoke。之后可省略 `--xverif-root`：

```text
$verif-harness evidence probe --tool xbit
```

MCP source/profile 生命周期：

```bash
python3 scripts/verif_harness.py xverif mcp install
python3 scripts/verif_harness.py xverif mcp configure \
  --runtime codex --backend direct
python3 scripts/verif_harness.py xverif mcp status
```

`configure` 写 `.harness/mcp/xverif.json`、生成项目 launcher，并注册到 Codex
或 Kimi 的项目级 MCP 配置；不修改用户级配置，不覆盖冲突注册。setup 在 runtime
明确时自动执行。注册后先调用 `xverif_ping` 和 `xverif_tools`；source install
或静态 profile 不能证明 MCP 已可用。

xverif 仍是可选、单独许可、单独维护的底层工具；checkout 不进入
verif-harness source archive 或 release。

## WavePeek 集成

```text
Codex / Kimi Code Agent
   ↓
verif-harness Skill / framework
   ↓
WavePeek CLI adapter
   ↓
kleverhq/wavepeek
```

一次性安装固定 commit、Apache-2.0 License 和 Cargo.lock 对应的 VCD/FST-only
版本：

```bash
./scripts/setup.sh --isolation managed --runtime codex
```

```text
$verif-harness waveform probe
```

源码位于 `.deps/wavepeek`，编译后的 CLI 位于
`.deps/wavepeek-bin/wavepeek`；两者都不进入 Git 或 release。默认不启用需要
Verdi SDK 的 FSDB feature。Linux host glibc 低于 2.34 时，setup 使用隔离在
`.deps/glibc-2.34` 的固定 GNU runtime，仅通过 private loader 启动 WavePeek，
不修改系统 libc 或全局 `LD_LIBRARY_PATH`。adapter 只执行显式 request 并保存 provenance，
不能把命令 PASS 解释为验证签核。

## 权限边界

- 不修改 DUT RTL。
- 不推断未评审的协议、数值、mask、alignment 或 coverage 语义。
- 不自动批准 Human Decision、waiver、change request、stage gate 或 freeze。
- 不把生成成功、零 failure、结构审计通过或哈希生成解释成功能正确。
- 不把 `READY_FOR_HUMAN_*_REVIEW` 解释成 `Approved`。
- 不自动 tag、push、发布或公开任何项目资产。
