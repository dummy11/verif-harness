# 用户指南：从 Stage 0 到 Verification Freeze

本文是 `verif-harness` 的完整操作手册，包含：

- RTL 验证项目从 0 到 freeze 的推荐顺序；
- 31 个模式各自的用途、输入、输出、用法和适用场景；
- 每个阶段必须由人工完成的决策；
- 各模式的能力边界和不能据此得出的结论。

项目自身的 `AGENTS.md`、roadmap、verification plan 和 architecture 优先于
本文。调用任何写模式前，必须先读取项目规则；DUT RTL 始终只读。

当前角色模型是：`verif-harness` 为最上层控制面，GitHub Spec Kit 为规格面，
现有 Skill modes 为执行能力面，xverif/WavePeek/EDA 为证据面，Human 为权限面。
新项目以 `specs/` 为唯一可编辑规格事实源，不再让 `specs/` 与 `sim/docs/`
同时维护可编辑需求。

## 1. 基本调用方式

在 RTL 验证项目根目录中调用：

```text
$verif-harness <mode> [arguments]  # 调用指定 verif-harness Skill mode
```

例如：

```text
$verif-harness doctor                       # 只读检查项目状态并推荐下一步
$verif-harness add-uvc-skeleton data_in     # 为 data_in 生成 UVC class 骨架
$verif-harness stage-gate-review 4          # 生成 Stage 4 Draft gate packet
```

这些语法也用于 workflow 外的诊断、recovery 和 legacy import。若当前 Spec Kit
`tasks.md` 已声明某个 mode，execution gate 批准后应由 `speckit.implement` 自动
调度；不要因为本文展示了直接调用语法，就在成功路径中再手动执行一次。

未指定 mode 时：

- 存在 `.harness-config.json`：默认执行只读 `doctor`；
- 不存在 `.harness-config.json` 且不存在 `.specify/`：先进入
  `spec-kit bootstrap`；Stage 0 task set 评审并获得执行授权后，由
  `speckit.implement` 自动调度 `init`，不在 workflow 外重复手动调用；
- 项目状态冲突或 stage 不明确：停止写入并报告冲突。

所有写模式默认只增不覆盖。Markdown 发生变化后，执行项目 `AGENTS.md`
规定的 Markdown workflow，并 review 自动修复产生的 diff。

## 2. Stage 0→freeze 总流程

### 2.1 四层职责

```text
verif-harness：Stage policy、能力选择、任务分发、traceability、权限护栏
  -> Spec Kit：constitution、specify、clarify、plan、checklist、tasks、analyze、converge
  -> modes/tools：生成 TB、运行审计、调用 xverif/WavePeek/EDA、保留 evidence
  -> Human：规格语义、Human Decisions、waiver、gate、sign-off、freeze
```

Spec Kit 把“文档优先”变成可执行工作流，但它是 agentic framework，不是
deterministic tool。`specify`、`checklist`、`workflow gate` 或 `implement` 成功
都不能替代 compile、simulation、regression、coverage、assertion 或人工审批。

规格层级不要按每条 shell command 建一个完整 spec，而应保持：

```text
项目 constitution
  -> verification program spec（spec of specs）
  -> Stage / feature spec
  -> plan + tasks + evidence contracts
```

统一追踪链为：

```text
REQ -> VF -> PLAN -> TASK -> MODE -> ARTIFACT -> EVIDENCE -> GATE
```

已完成或已批准的存量项目不重写历史：把现有批准文档、日期、证据和 decision
作为 immutable imported baseline 链接到 Spec Kit；后续变更才走新的 spec-driven
流程。`sim/docs/` 可继续保存治理、生成视图、证据索引和 review packet，但不得
成为第二个可编辑需求权威。

### 2.2 全流程

```text
Spec Kit bootstrap：安装 Codex integration 与 RTL verification preset
  -> Stage 0 workflow：建立 constitution 与 verification program specification
  -> Stage 0：文档与治理基线
  -> Human 批准范围、规格来源和 Human Decisions
  -> Stage 1：可编译、可运行的最小 harness/UVM 环境
  -> Human Stage 1 gate
  -> Stage 2：Golden/reference-model 功能对拍
  -> Human Stage 2 gate
  -> Stage 3：coverage model 与 assertion fleet
  -> Human Stage 3 gate
  -> Stage 4：随机回归、边界场景与 CI
  -> Human Stage 4 gate
  -> Stage 5：coverage/assertion/performance/stability closure
  -> Human Stage 5 sign-off
  -> freeze-baseline                  # Skill：生成 hash 锚定的 freeze candidate
  -> Human freeze approval
  -> 单独授权的 tag/push/release
```

`doctor` 在每个 stage 入口和每次 session 恢复时重复使用；
`regression-triage` 在任何非全绿 regression 后使用；`change-control` 在任何
approved/frozen baseline 发生变化时立即使用。

`xverif` 与 WavePeek 都不是独立 stage，而是贯穿 Stage 0～5 的确定性工具委派
通道。只在存在具体问题、明确输入和有限查询范围时调用；工具 `PASS` 只说明本次
命令成功，不代表 testcase PASS、stage gate 通过或 verification closure。

`spec-kit` 在每个 Stage 的开始和实现后使用：开始时执行 specify/clarify/plan/
checklist/tasks/analyze；获得执行授权后把 task 分发给对应 verif-harness mode；
完成后 converge 并记录 specification drift。Spec Kit review gate 只是文档或任务
审阅点，真正的 Stage gate 仍由 `stage-gate-review` 生成 packet 后由 Human 批准。

所有被 reviewed task 声明的 mode 都使用同一分发合同，不只 `init`：execution gate
批准后，`speckit.implement` 自动调用对应 mode 一次，并检查 owned outputs、evidence
paths 和 validation command。正常路径不要求用户再逐个手动调用；缺少产物时 task
保持 incomplete，由 `converge` 记录 deviation。只有显式批准并留痕的 recovery、
legacy import，或者不属于 task set 的 workflow control/Human boundary 命令才单独
调用，例如 `bootstrap`、`status/resume`、`stage-gate-review` 和最终 freeze 授权流。
如果某个 mode 还需要独立 EDA、commit、push、waiver 或其他权限，implement 必须
停在该权限边界；获得授权后由同一 task 继续分发，而不是把正常执行责任转给用户
手动重复调用。

`xverif` 用于 VCS/VDB/FSDB/SVA/日志相关事实：`xbit` 计算 bit、slice、mask 和
signedness，`xloc` 恢复日志位置，`xsva` 分析 assertion，`xcov` 查询 coverage
database，`xdebug` 查询设计或 FSDB，`xentry` 解码结构化 entry，`xwaveform`
渲染已导出的波形 manifest。`verif-harness` 先选择验证任务，再经 CLI adapter
调用对应 xverif native tool。

WavePeek 用于有限范围的 VCD/FST 查询：检查层次和信号、读取指定时刻的值、查找
变化、验证 property 或抽取协议传输。默认托管集成不读取 FSDB；只有 FSDB 时优先
使用 `xverif xdebug`。如需启用 WavePeek FSDB extension，必须由人工明确批准
Verdi SDK 许可和本地隔离策略。

## 3. 分阶段推荐顺序

### 3.1 Stage 0：文档基线

```text
doctor                                # Skill：只读检查初始项目状态
  -> spec-kit bootstrap               # Skill：初始化 Spec Kit Codex integration 与 RTL preset
  -> spec-kit stage --stage 0         # Skill：生成并审阅 Stage 0 spec/plan/tasks
       -> speckit.implement            # Skill：自动调度以下已授权 task mode
          -> init                      # Skill：生成 harness 治理资产及规格派生视图
          -> audit-traceability        # Skill：审计计划与实现的结构追踪关系
       -> speckit.converge             # Skill：校验 task outputs/evidence/validation
  -> stage-gate-review 0              # Skill：生成 Stage 0 Draft gate packet
  -> Human Stage 0 baseline approval
```

人工必须确认验证范围、规格权威来源、sign-off 标准、Human Decisions、
Provisional 和 open questions。Stage 0 不允许生成 TB 源码。

### 3.2 Stage 1：最小可运行环境

```text
doctor                                # Skill：确认 Stage 1 入口状态
  -> spec-kit stage --stage 1         # Skill：审阅 Stage 1 spec/plan/tasks 并授权执行
       -> speckit.implement            # Skill：自动调度以下已授权 task modes
          -> add-interface             # Skill：生成协议 interface 与 modport
          -> add-shared-pkg            # Skill：生成公共类型及 pack/unpack helper
          -> add-uvc-skeleton          # Skill：生成 driver/monitor/agent class 骨架
          -> add-harness-layer         # Skill：生成 DUT/TB harness、SVA 与 bind 骨架
          -> add-env-layer             # Skill：生成 env、base test 与 thin tb_top
          -> finalize-filelist-and-make # Skill：固化编译顺序与 compile target
          -> add-simulator-profile     # Skill：生成已评审的 simulator 配置
          -> complete-uvc              # Skill：实现显式 ready/valid UVC 合约
          -> add-testcase              # Skill：生成 candidate testcase 骨架
          -> add-regression-runner     # Skill：生成隔离、可复现的 regression runner
          -> xverif                    # Skill：按任务授权查日志、位宽、SVA 或 FSDB
          -> wavepeek                  # Skill：按任务授权查询有限 VCD/FST 波形
          -> audit-traceability        # Skill：审计 feature/test/plan 结构映射
       -> speckit.converge             # Skill：校验 task outputs/evidence/validation
  -> stage-gate-review 1              # Skill：生成 Stage 1 Draft gate packet
  -> Human Stage 1 approval
```

人工提供并确认 clock/reset、协议、SRAM、timeout、DUT port 和 simulator
语义；在真实 EDA 环境检查 compile、elaboration、waveform 和 sanity test。
`xverif xloc/xbit/xsva/xdebug` 用于定位编译或运行日志、核对位宽/掩码、解释协议
property，以及查询 scope、driver、X/Z 和 FSDB 值。WavePeek 的
`info/scope/signal/change/property` 用于受限时窗内确认 clock/reset、首次握手、
latency、hang、残留数据和 X/Z 传播。信号、时窗、预期事件和最终 sanity verdict
仍由人工确认。

### 3.3 Stage 2：Reference model 与功能对拍

```text
doctor                                # Skill：确认 Stage 2 入口状态
  -> spec-kit stage --stage 2         # Skill：审阅 Stage 2 spec/plan/tasks 并授权执行
       -> speckit.implement            # Skill：自动调度以下已授权 task modes
          -> add-refmodel-bridge       # Skill：生成 Golden/Syscan/DPI 结构适配层
          -> complete-scoreboard       # Skill：仅为明确 FIFO alignment 生成比较器
          -> add-testcase              # Skill：生成 Golden engagement/compare 测试
          -> xverif                    # Skill：按任务授权算 mask/slice 或查 FSDB
          -> wavepeek                  # Skill：按任务授权查询首个分歧时窗
          -> regression-triage         # Skill：失败时归一化 signature 并核对重跑
          -> audit-traceability        # Skill：审计 Golden/test/plan 结构映射
       -> speckit.converge             # Skill：校验 task outputs/evidence/validation
  -> stage-gate-review 2              # Skill：生成 Stage 2 Draft gate packet
  -> Human Stage 2 approval
```

人工确认 numeric representation、mask、alignment、residual、unsupported
configuration 和 Golden engagement。Port-level compare 或项目专用 wrapper
不能由通用 FIFO scoreboard 替换。
`xverif xbit/xentry/xdebug` 用于复算 mismatch 的 mask/slice/signedness、解码多拍
entry，并检查 FSDB 中 DUT/Golden 的第一个不同值。WavePeek 的
`value/change/extract` 用于从 VCD/FST 截取 mismatch 前后的握手和 payload 事实。
两者都不能自行决定 numeric、alignment、mask 或 Golden 语义。

### 3.4 Stage 3：Coverage 与 Assertion

```text
doctor                                # Skill：确认 Stage 3 入口状态
  -> spec-kit stage --stage 3         # Skill：审阅 Stage 3 spec/plan/tasks 并授权执行
       -> speckit.implement            # Skill：自动调度以下已授权 task modes
          -> add-coverage-skeleton     # Skill：从已评审合约生成 coverage model
          -> add-assertion-skeleton    # Skill：从已评审 property 生成 SVA/bind
          -> add-testcase              # Skill：生成 coverage/assertion focused 测试
          -> xverif                    # Skill：按任务授权分析原生 SVA/VDB
          -> wavepeek                  # Skill：按任务授权查询反例或 hole 场景
          -> regression-triage         # Skill：失败时核对 same-seed 重跑
          -> audit-traceability        # Skill：审计 bin/assertion/test/plan 映射
       -> speckit.converge             # Skill：校验 task outputs/evidence/validation
  -> stage-gate-review 3              # Skill：生成 Stage 3 Draft gate packet
  -> Human Stage 3 approval
```

人工批准 coverage denominator、cross、property、sampling clock、reset disable、
vacuity 处理和逐对象 unreachable waiver。
`xverif xsva` 用于 list/scan/lint/parse/explain，`xverif xcov` 用于读取 VDB summary、
hole、scope 和 source evidence，`xdebug` 可补充 FSDB 反例事实。WavePeek 用于在
VCD/FST 中检查 assertion 触发窗口或 hole 对应场景是否发生；它不能证明 coverage
bin 已命中。coverage denominator、property 意图、vacuity 和 waiver 仍需人工批准。

### 3.5 Stage 4：Regression 与 CI

```text
doctor                                # Skill：确认 Stage 4 入口状态
  -> spec-kit stage --stage 4         # Skill：审阅 Stage 4 spec/plan/tasks 并授权执行
       -> speckit.implement            # Skill：自动调度以下已授权 task modes
          -> add-testcase              # Skill：补随机、边界和稳定性 candidate 测试
          -> add-regression-runner     # Skill：已有完整 runner 时只复用、不覆盖
          -> add-ci-hook               # Skill：生成待人工合并的 CI job fragment
          -> xverif                    # Skill：按任务授权查询失败证据
          -> wavepeek                  # Skill：按任务授权查询失败 seed 波形
          -> regression-triage         # Skill：每次非全绿时分类候选 root cause
          -> audit-traceability        # Skill：审计默认 regression 与计划映射
          -> change-control            # Skill：baseline 变化时审计 change request
       -> speckit.converge             # Skill：校验 task outputs/evidence/validation
  -> stage-gate-review 4              # Skill：生成 Stage 4 Draft gate packet
  -> Human Stage 4 approval
```

人工或获授权基础设施提供 simulator license、scheduler、secret 和 CI runner；
test 从 candidate 晋级 default regression 必须有已评审的动态 PASS 证据。
每个失败先保留 seed、命令、日志和原始数据库，再用 xverif 取得稳定的日志位置、
FSDB/VDB/SVA/entry 事实，或用 WavePeek 在对应 VCD/FST 中查找首个分歧。查询结果随
same-seed rerun 一起交给 `regression-triage`；root cause 分类和 testcase 晋级仍由
人工评审。

### 3.6 Stage 5：闭合、签核与 freeze

```text
doctor                                # Skill：确认 Stage 5 入口与剩余 blocker
  -> spec-kit stage --stage 5         # Skill：审阅 Stage 5 closure spec/plan/tasks
       -> speckit.implement            # Skill：自动调度以下已授权 task modes
          -> add-performance-gate      # Skill：按已评审公式/阈值检查性能合同
          -> add-testcase              # Skill：只补剩余 hole/corner/closure case
          -> required regression rounds # 项目动作：需独立 EDA 权限
          -> regression-triage         # Skill：持续审计失败直到全部关闭
          -> xverif                    # Skill：按任务授权生成补充证据
          -> wavepeek                  # Skill：按任务授权抽查波形
          -> coverage-closure          # Skill：审计 coverage evidence 完整性
          -> assertion-closure         # Skill：审计 assertion evidence 完整性
          -> audit-traceability        # Skill：执行最终结构追踪审计
          -> change-control            # Skill：确认 baseline 变更均有已审 CR
       -> speckit.converge             # Skill：校验 task outputs/evidence/validation
  -> stage-gate-review 5              # Skill：生成 Stage 5 Draft gate packet
  -> Human Stage 5 approval
  -> signoff-audit 5                  # Skill：审计已记录 sign-off 元数据与证据
  -> freeze-baseline                  # Skill：生成 SHA-256 freeze candidate
  -> Human freeze approval
  -> separately authorized tag/push
```

`coverage-closure` 和 `assertion-closure` 的 JSON 只是 tool-neutral adapter，
不能替代原始 coverage database、compile/elaboration report 和 assertion report。
Stage 5 中，`xverif xcov/xsva/xdebug` 提供 VDB、SVA 和 FSDB 的原生补充证据；
WavePeek 对代表性的 VCD/FST hole、waiver 或 corner window 做可重放抽查。两类工具
证据必须映射回 verification plan、coverage/assertion plan 和 closure adapter，
不能直接产生 waiver、Stage 5 approval 或 freeze verdict。

### 3.7 xverif 与 WavePeek 选择规则

| 当前输入或问题 | 首选通道 | 说明 |
| --- | --- | --- |
| VCS 日志、`L_XXXXXXXX` 位置 | `xverif xloc` | 恢复稳定源码位置并保留日志证据 |
| bit/slice/mask/signedness | `xverif xbit` | 产生可复算的 SystemVerilog 数值结果 |
| SVA source/property | `xverif xsva` | 用于 list、lint、parse 和 explain |
| VDB coverage database | `xverif xcov` | 原生读取 summary、hole、scope 和 source evidence |
| FSDB、driver/load/value | `xverif xdebug` | WavePeek 默认不启用专有 FSDB feature |
| entry/descriptor/header | `xverif xentry` | 解码多拍结构化字段 |
| 已导出的 waveform manifest | `xverif xwaveform` | 渲染图像或统计，不替代原始波形 |
| VCD/FST 层次、值、变化、property | `wavepeek` | 适合明确 signal/scope/time 的有限查询 |
| VCD/FST 协议传输抽取 | `wavepeek` | mapping 和协议语义必须先由人工确认 |

Stage 0 只允许安装、`probe` 和把工具证据要求写入计划，不使用工具输出批准文档
基线。Stage 1～5 的具体调用方法与输入输出分别见 §5.13 和 §5.14。

## 4. Bootstrap 与 Stage 1 结构模式

### 4.1 `init`

**用途**：把已有 reviewed Spec Kit Stage 0 specification 的 RTL 项目 bootstrap
成 harness-style 项目，并生成治理与规格派生视图。

**适用场景**：项目根目录没有 `.harness-config.json`，但已有 `.specify/` 和通过
文档 review gate 的 Stage 0 spec/plan/tasks/checklist；或已批准存量项目已登记为
immutable imported baseline。

新项目的正常路径中，Stage 0 `tasks.md` 必须声明一次 `verif-harness mode: init`；
execution gate 批准后由 `speckit.implement` 自动调度。下方直接调用只用于有记录的
recovery 或 legacy import，不是 workflow 成功后的重复步骤。

**输入**：

- 项目根目录及其中的 `.v/.sv` 文件；
- 项目名、RTL root、verification root；
- DUT top file/module；
- 可选 design-doc root；
- 可选 reference-model spec；
- Spec Kit constitution、Stage 0 spec/plan/tasks/checklist/analyze 结果；
- 通过 discovery 和 Human 回答形成的初始配置。

**用法**：

```text
$verif-harness init  # 仅 recovery/legacy 路径直接调用；正常路径由 implement 调度
```

**输出**：

- `.harness-config.json`；
- `AGENTS.md`；
- `.harness/` workflow assets；
- `.codex/agents/` 辅助 agent 配置；
- 链接 `specs/` 的 verification/governance 派生视图和 Stage 0 review packet；
- Stage 1 M1.1 空目录骨架与 `.gitkeep`。

**人工参与**：确认所有 discovery 结果，评审整个 Stage 0 文档集，批准或修改
Human Decisions/Provisional/open questions。

**边界**：已有配置时不得重新覆盖；Stage 0 不生成 TB 代码；不得在 `sim/docs/`
重新定义 requirement 或建立第二个可编辑规格权威；生成文档不是 Stage 0 approval。

### 4.2 `add-interface`

**用途**：根据明确的 interface contract 生成 protocol interface 和对应 UVC
落点目录。

**适用场景**：Stage 0 已批准，准备建立 ctrl/data/SRAM 等接口。

**输入**：

- `.harness-config.json`；
- `harness-spec.yaml` 中的 interface name、parameters、input args、signals；
- 每个 signal 的 `to-dut`、`from-dut` 或 `clkrst` 角色；
- 可选 modport name override 和 parameterized instances；
- `tb_architecture.md` 的 modport/接口约束。

**用法**：

```text
$verif-harness add-interface  # 根据已评审 interface contract 生成接口
```

**输出**：

- `<verif_root>/testbench/top/if/<prefix>_<name>.sv`；
- 每个接口对应的 `uvc/<agent>_agent/seq/` 目录；
- driver、monitor、DUT 和 clock/reset modport。

**人工参与**：确认 signal direction、clocking ownership、参数宽度和接口分组。

**边界**：不生成 UVC class；不能只凭端口名前缀确认协议语义；缺少完整 spec
时不能继续。

### 4.3 `add-shared-pkg`

**用途**：生成 UVM 无关的公共类型、参数以及宽总线 pack/unpack helper。

**适用场景**：interface 已存在，多个 UVC/Golden/monitor 需要一致的数据布局。

**输入**：

- `.harness-config.json`；
- `harness-spec.yaml` 的 parameters、local parameters、enums；
- 可选 `pack_pattern`：packed signal、二维 dimensions、element width；
- architecture 中已批准的位打包顺序。

**用法**：

```text
$verif-harness add-shared-pkg  # 生成公共类型、参数及 pack/unpack helper
```

**输出**：

- `<prefix>_tb_pkg.sv`：parameter、enum、lane typedef；
- `<prefix>_pack_pkg.sv`：pack/unpack function，或无 pattern 时的明确 stub；
- 必要时向 `tb.f` 添加 package 条目。

**人工参与**：确认 lane 顺序、signedness、dimension 和 enum 编码。

**边界**：当前 pack generator 只直接支持二维 pattern；不导入 UVM/UVC；不同
来源的同名参数值冲突时必须停止。

### 4.4 `add-uvc-skeleton [name]`

**用途**：为一个或全部 interface 生成分层 UVC class 骨架。

**适用场景**：interface 和 shared packages 已完成，但 driver/monitor 行为尚未实现。

**输入**：

- 可选 `<name>`，省略时处理全部 interfaces；
- `harness-spec.yaml` 的 interface、instances、parameters、item/sequence names；
- 已存在的 shared package 和 interface；
- `tb_architecture.md` 的 agent 分层定义。

**用法**：

```text
$verif-harness add-uvc-skeleton          # 为所有已定义接口生成 UVC 骨架
$verif-harness add-uvc-skeleton data_in  # 仅为 data_in 生成 UVC 骨架
```

**输出**：

- agent config、item、sequencer、driver、monitor、coverage subscriber；
- agent 或 parameterized top-agent/sub-agent；
- default sequence 和 UVC package；
- 必要的 `tb.f` incdir/package 条目。

**人工参与**：确认 active/passive ownership、parameterized instances、item 字段
和 sequence 职责。

**边界**：run/build phase 仅为空骨架；骨架 compile visibility 不代表协议完成。

### 4.5 `add-harness-layer`

**用途**：建立 DUT 与验证环境之间唯一的结构集成层。

**适用场景**：interfaces 已生成，准备连接 DUT、clock/reset、straps、status
probes、SVA 和 bind。

**输入**：

- `.harness-config.json`；
- `harness-spec.yaml` 的接口 port map、straps、status probes、variants；
- 只读解析得到的 DUT top port list；
- architecture/verification plan 中已批准的 harness ownership。

**用法**：

```text
$verif-harness add-harness-layer  # 生成 DUT/TB harness、SVA 与 bind 骨架
```

**输出**：

- DUT-side `rtl_wrap`、`dut_select`、`dut_harness`；
- TB-side harness interface、API package、reset/status/strap API、clock/reset
  generator；
- SVA checker stubs 和 filelist snippet。

**人工参与**：逐端口 review 映射、tie-off、variant、probe 层级和 reset/strap
语义，并在真实编译器确认 elaboration。

**边界**：不修改 RTL；不根据端口名静默猜测 mapping；缺少 interface 或完整
port spec 时停止。

### 4.6 `add-env-layer`

**用途**：生成 env/test 层及轻薄 `tb_top`，把 harness 和 UVC 组合成可编译环境。

**适用场景**：UVC packages 和 harness API 已存在。

**输入**：

- `.harness-config.json` 和 `harness-spec.yaml`；
- UVC package/agent 类型；
- harness aggregate API；
- env knobs、interface instances 和 architecture ownership。

**用法**：

```text
$verif-harness add-env-layer  # 生成 env、base test、packages 与 thin tb_top
```

**输出**：

- env config、virtual sequencer、env；
- scoreboard/coverage collector shell；
- env package、base test、test package；
- thin `tb_top`；
- 必要的 filelist 条目。

**人工参与**：确认 virtual interface 分发、agent enable、analysis connection
计划和 `tb_top` 只承担结构职责。

**边界**：初始 scoreboard/coverage write body 无功能；不加入 test-specific
logic 或默认 `UVM_TESTNAME`。

### 4.7 `finalize-filelist-and-make`

**用途**：按规范依赖顺序生成完整 filelist 和首次 compile/elaboration target。

**适用场景**：Stage 1 M1.1 所有结构源文件已落地。

**输入**：

- `.harness-config.json`；
- 实际存在的 RTL、interface、package、UVC、env/test、harness、SVA、top 文件；
- 可选 RTL exclude list；
- architecture 中的 compile-order contract。

**用法**：

```text
$verif-harness finalize-filelist-and-make  # 固化 filelist、编译顺序和 Makefile
```

**输出**：

- `<verif_root>/filelist/rtl.f`；
- `<verif_root>/filelist/tb.f`；
- `<verif_root>/filelist/sim.f`；
- `<verif_root>/regress/Makefile`，提供 `help/compile/clean`。

**人工参与**：已有 filelist/Makefile 时选择 merge/diff/approved overwrite；在
VCS 等真实环境 review warning 和 elaboration。

**边界**：不把不存在的文件写入 filelist；该阶段不自动增加完整 regress/cov
target；compile error 不会被解释为通过。

## 5. 实现、执行与集成模式

### 5.1 `doctor`

**用途**：只读判断项目健康度、阶段状态和下一安全动作。

**适用场景**：接手项目、恢复 session、进入新 stage、升级 skill 或不知道下一步。

**输入**：项目根目录、可选 `AGENTS.md`、`.harness-config.json`、docs/TB/Git 状态。

**用法**：

```text
$verif-harness doctor  # 只读检查健康度、阶段状态和下一安全动作
```

底层命令可加 `--json`：

```bash
# doctor Skill：输出机器可读的只读健康检查结果
python3 <skill-dir>/doctor/scripts/doctor.py --project-root . --json
```

**输出**：ERROR、WARNING、INFO、推断出的 stage state、legacy Claude artifact、
RTL dirtiness 和 recommended next mode。

**人工参与**：决定是否执行建议的写模式，解释 ambiguous stage state。

**边界**：不修复文件；clean audit 不证明 simulation PASS 或 stage approval。

### 5.2 `add-simulator-profile`

**用途**：把 simulator 命令、能力和 evidence path 固化成可 review 配置。

**适用场景**：增加 VCS、Questa、Xcelium、Verilator 或 custom simulator profile。

**输入**：`simulator-profile.json`，包含 name、provider、version、compile/run token
arrays、environment variable names、capabilities、evidence paths。支持
`{filelist}`、`{top}`、`{binary}`、`{seed}`、`{test}` placeholder。

**用法**：

```bash
# add-simulator-profile Skill：从显式合约生成 simulator profile 与 Makefile fragment
python3 <skill-dir>/add-simulator-profile/scripts/generate_profile.py \
  --spec simulator-profile.json \
  --profile-out sim/config/simulator-profile.json \
  --make-out sim/config/simulator-profile.mk
```

**输出**：normalized JSON profile 和 Makefile fragment。

**人工参与**：提供真实 tool/version，审查命令，在真实 EDA 环境运行并归档日志。

**边界**：环境只记录变量名，不记录 license/secret value；输出状态仅
`CONFIGURED`，不是 `TESTED` 或 `SUPPORTED`。

### 5.3 `complete-uvc`

**用途**：根据显式协议合约生成具体 driver/monitor 行为。

**适用场景**：ready/valid source UVC 已有 item/interface 骨架，需要实现 drive、
handshake timeout 和 monitor publish。

**输入**：`uvc-contract.json`，包含 item/class/base/vif types、config-db vif key、
driver/monitor clocking block、valid/ready signal、payload mapping、timeout 和
plan references。

**用法**：

```bash
# complete-uvc Skill：从显式 ready/valid 合约生成 driver 与 monitor
python3 <skill-dir>/complete-uvc/scripts/generate_uvc.py \
  --spec uvc-contract.json --driver-out <driver.svh> \
  --monitor-out <monitor.svh>
```

**输出**：具体 driver 和 monitor class，包含 vif 获取、ready timeout、transaction
capture 和 analysis-port publish。

**人工参与**：确认协议确实是 ready/valid source，review reset ownership、
clocking region、payload timing，并运行 protocol tests。

**边界**：不支持的控制/SRAM/credit/乱序协议必须另行实现；生成代码不是协议
正确性证明。

### 5.4 `complete-scoreboard`

**用途**：根据显式 compare contract 生成 FIFO-aligned UVM scoreboard。

**适用场景**：expected/actual transaction 一一按顺序到达，比较策略已评审。

**输入**：`scoreboard-contract.json`，包含 class/base、expected/actual type、
`alignment: fifo`、字段表达式、`exact/masked/abs_tolerance` 策略和 plan refs。

**用法**：

```bash
# complete-scoreboard Skill：从 FIFO compare 合约生成 scoreboard
python3 <skill-dir>/complete-scoreboard/scripts/generate_scoreboard.py \
  --spec scoreboard-contract.json --out <scoreboard.svh>
```

**输出**：两个 analysis FIFO、pair compare、compare/mismatch counter、no-compare
和 residual check。

**人工参与**：批准 alignment、mask、numeric/tolerance、reset flush 和 end-of-test
policy；运行 mismatch/residual/no-compare focused tests。

**边界**：不支持 tag matching、乱序或 port-level compare；不能从字段名推断
mask/tolerance。

### 5.5 `add-testcase`

**用途**：创建一个 compile-safe UVM test/vseq，并注册 package include。

**适用场景**：testcase list 中已有批准的 testcase ID、feature mapping 和预期结果。

**输入**：project root、test name、base test、base vseq；可选 candidate caselist。

**用法**：

```bash
# add-testcase Skill：先 dry-run 预览 testcase/vseq/package 变更
python3 <skill-dir>/add-testcase/scripts/add_testcase.py \
  --project-root . --test-name <prefix>_<name>_test \
  --base-test <prefix>_base_test --base-vseq <prefix>_job_vseq_base \
  --dry-run
```

Review 后去掉 `--dry-run`；只有明确的 focused list 才使用：

```text
--candidate-caselist <path>  # add-testcase Skill：仅登记到指定 candidate list
```

**输出**：test `.svh`、vseq `.svh`、package include；可选 candidate caselist 条目。

**人工参与**：实现并审阅 stimulus/expected behavior，确认动态 PASS 后决定是否
晋级 default regression。

**边界**：不会自动加入 default regression；骨架不证明 stimulus/checking 完成。

### 5.6 `add-coverage-skeleton`

**用途**：从已评审 JSON 合约生成 coverage class。

**适用场景**：coverage plan 已给出确切表达式、bins、cross 和 plan ID。

**输入**：coverage spec 的 class/base、sample fields、covergroups、coverpoints、raw
bin clauses、cross items 和 `plan_refs`。

**用法**：

```bash
# add-coverage-skeleton Skill：从已评审 bin/cross 合约生成 coverage class
python3 <skill-dir>/add-coverage-skeleton/scripts/generate_coverage.py \
  --spec coverage-spec.json --out <collector-fragment.svh>
```

**输出**：可编译 coverage class/fragment。

**人工参与**：批准 denominator、bin boundary、ignore/illegal bin、sampling event
和 cross 价值；查看真实 coverage report。

**边界**：不从自然语言或 signal name 猜 coverage；拒绝缺 plan ref、重复 name
和 output overwrite。

### 5.7 `add-assertion-skeleton`

**用途**：从已评审 property contract 生成 checker 和可选 bind。

**适用场景**：assertion plan 已给出 clock/reset、property 和 failure message。

**输入**：assertion spec 的 checker ports、clock/reset、assertion IDs、property
expressions、messages、plan refs 和可选 bind mapping。

**用法**：

```bash
# add-assertion-skeleton Skill：从已评审 property 合约生成 checker 与 bind
python3 <skill-dir>/add-assertion-skeleton/scripts/generate_assertions.py \
  --spec assertion-spec.json --checker-out <checker.sv> \
  --bind-out <bind.sv>
```

**输出**：checker module 和可选 bind statement。

**人工参与**：review sampling region、reset disable、vacuity、X behavior、width、
hierarchy；执行正向和故障注入 focused tests。

**边界**：缺 property 时只输出 TODO，不伪装成已实现 assertion；不把自然语言
静默翻译成 property。

### 5.8 `add-refmodel-bridge`

**用途**：生成 Syscan HDL shell wrapper 或 DPI-C import package 的结构适配层。

**适用场景**：reference-model backend/API 已批准，准备连接 verification harness。

**输入**：local/upstream reference-model spec，以及 `bridge-spec.json` 中的 backend、
guard、HDL ports 或 DPI signatures、disabled assignments 和 plan refs。

**用法**：

```bash
# add-refmodel-bridge Skill：生成 Syscan wrapper 或 DPI import package
python3 <skill-dir>/add-refmodel-bridge/scripts/generate_bridge.py \
  --spec bridge-spec.json --out <bridge.sv>
```

**输出**：Syscan structural wrapper 或 DPI import package。

**人工参与**：批准 backend、numeric semantics、alignment、mask、unsupported policy、
residual handling、compare ownership 和 Golden engagement test。

**边界**：adapter 只建立连接；零 mismatch 且 Golden 未 engaged 不能 PASS。

### 5.9 `add-regression-runner`

**用途**：添加 simulator-neutral、隔离、可复现的 regression launcher 和严格
result collector。

**适用场景**：已有 runnable test 和稳定的 end-of-test result contract。

**输入**：

- caselist；
- run directory；
- numeric seed 或 seed file；
- jobs/timeout/log name；
- argv-style simulator command，必须包含 `{test}` 和 `{seed}`；
- collector 的 result prefix/regex 和是否 require Golden。

**用法**：复制 mode scripts 和 Makefile fragment 后，例如：

```bash
# add-regression-runner Skill：按 caselist/seed 启动隔离 regression
python3 run_regression.py --caselist tests.caselist --runs-dir runs \
  --seed 123 --jobs 4 -- simulator +UVM_TESTNAME={test} +ntb_random_seed={seed}

# add-regression-runner Skill：按严格结果合约汇总每个 testcase
python3 collect_results.py --runs-dir runs --caselist tests.caselist \
  --result-prefix PROJECT_RESULT --require-golden
```

**输出**：每 testcase 独立 run dir、`command.json`、log、`batch_seed.txt`、
`batch.json`、`report.md/json`、`failed.caselist` 和 `seed.txt`。

**人工参与**：定义 result/Golden contract，提供 simulator 环境，审阅 crash、
timeout、no-compare 和 rerun 结果。

**边界**：不替换已有项目专用 runner；不使用 shell interpolation；缺结束 banner
不能 PASS。

### 5.10 `add-ci-hook`

**用途**：从显式合约生成 GitLab CI 或 Jenkins 验证 job fragment。

**适用场景**：本地 compile/smoke/regression 稳定，准备接入 CI。

**输入**：`ci-spec.json` 的 provider、commands、runner tags/agent、timeout、公开
variables 和 artifact paths。

**用法**：

```bash
# add-ci-hook Skill：从显式 CI 合约生成待人工合并的 job fragment
python3 <skill-dir>/add-ci-hook/scripts/generate_ci.py \
  --spec ci-spec.json --out <ci-fragment>
```

**输出**：可人工 merge 的 `.gitlab-ci.yml` 或 Jenkins fragment。

**人工参与**：配置 runner、license、secret、scheduler、timeout/cleanup，merge
fragment，并在真实 pipeline 验证 commit 与结果。

**边界**：不修改 live CI、不 trigger pipeline、不配置 credential、不执行内部
`git pull`。

### 5.11 `add-performance-gate`

**用途**：按已评审的固定算术和 predicate 检查结构化性能记录。

**适用场景**：需要 gate latency、bubble、utilization、cadence、count 或场景完整性。

**输入**：performance contract 的 marker、required/key fields、constant/field/ratio
operands、`eq/ne/lt/le/gt/ge` predicates、completeness rules；一个或多个 log。

**用法**：

```bash
# add-performance-gate Skill：按固定公式与阈值评估结构化性能记录
python3 <skill-dir>/add-performance-gate/scripts/evaluate_performance.py \
  --contract performance-contract.json --log run-a.log --log run-b.log
```

按脚本 help 可加 JSON/report output 参数。

**输出**：逐 record predicate 结果、completeness failures、Markdown/JSON summary
和非零失败退出码。

**人工参与**：定义指标、公式、threshold、expected count 和 waiver；确认 producer
与 contract 使用同一语义。

**边界**：只执行白名单算术；不发明公式/threshold，不因历史表现放宽 gate。

### 5.12 `regression-triage`

**用途**：对失败日志形成稳定 signature、候选分类和同 seed 重跑审计。

**适用场景**：regression 不是全绿，需要保留证据地缩小问题域。

**输入**：primary `report.json`、same-seed rerun `report.json`、包含 regex 和
candidate classification 的 `triage-rules.json`。

**用法**：

```bash
# regression-triage Skill：结合 primary/same-seed rerun 生成候选分类
python3 <skill-dir>/regression-triage/scripts/triage_regression.py \
  --report runs/report.json --rerun-report rerun/report.json \
  --rules triage-rules.json --out runs/triage.json
```

**输出**：每个失败的 normalized signature、matched rule、candidate classification、
primary/rerun log、seed consistency、blockers 和整体 state。

**人工参与**：判断真实 root cause，以及属于 RTL、TB、Golden、spec 还是 infra。

**边界**：regex match 不是 root-cause 结论；不改 test verdict、不创建 waiver、
不修改源码。

### 5.13 `xverif`

**用途**：在不削弱 `verif-harness` stage/framework 治理的前提下，把一个已评审
的底层确定性操作委派给 `BLANK2077/xverif` 工具族，并生成可追溯 evidence。

**适用场景**：任一 Stage 需要以下事实或计算时：

- `xbit`：SystemVerilog literal、signed/unsigned、slice、mask、表达式；
- `xdebug`：daidir/FSDB 的 scope、driver/load、value、protocol、active driver；
- `xcov`：VDB coverage summary、hole、scope、source evidence 和 export；
- `xentry`：多拍 entry/descriptor/header 的 raw field 解码；
- `xloc`：从 `L_XXXXXXXX` 恢复 UVM 日志源码位置；
- `xsva`：SVA list/scan/lint/parse/explain；
- `xwaveform`：从已导出 manifest 渲染波形 JPG/stats。

**输入**：

- 完整仓库的 `deps/xverif.lock.json`，固定
  `https://github.com/BLANK2077/xverif.git`、完整 commit、MIT License hash
  和七个 wrapper；独立 Skill 部署则提供等价的已批准 checkout root；
- `xverif-request.json`：`tool`、evidence 分类用 `operation`、native `arguments`、
  可选项目相对 `stdin_path`、working directory、环境变量名、timeout、
  `json/xout/text`、接受退出码和 expected artifacts；
- selected tool 的 upstream reference/action schema；
- 项目 `AGENTS.md`、verification plan 和当前 stage 的证据要求。

**用法**：在完整 verif-harness 仓库一次性安装并验证固定版本：

```bash
# xverif Skill：安装并验证 commit-pinned managed dependency
./scripts/setup.sh --with-xverif
# 或：make setup-xverif check-xverif
```

安装器只在 `.deps/xverif` 不存在时执行 temporary clone、detached checkout、
完整校验和 atomic publish；已有目录只验证，不 pull、不 checkout、不覆盖。

然后确认 selected wrapper 和上游身份：

```bash
# xverif Skill：确认指定 native wrapper 与上游身份
python3 <skill-dir>/xverif/scripts/xverif_adapter.py probe \
  --tool xbit \
  --out /tmp/xverif-xbit-probe.json
```

复制并修改 `xverif/xverif-request.example.json`，然后运行：

```bash
# xverif Skill：执行已评审 request，并把证据写入全新目录
python3 <skill-dir>/xverif/scripts/xverif_adapter.py run \
  --project-root . --request xverif-request.json \
  --out-dir artifacts/xverif/xbit-conv-001
```

也可经开源项目根 CLI 进入同一 adapter：

```bash
python3 scripts/verif_harness.py xverif probe --tool xbit  # 经项目根 CLI probe xbit
```

adapter 按显式 `--xverif-root` → `XVERIF_HOME` → project/current/repository
`.deps/xverif` 的固定顺序查找；正常托管使用无需传路径。

`xbit` JSON 示例 request 的核心字段为：

```json
{
  "schema_version": 1,
  "tool": "xbit",
  "operation": "conv",
  "arguments": ["conv", "8'shff", "--json"],
  "stdin_path": null,
  "working_directory": ".",
  "environment_keys": [],
  "timeout_seconds": 60,
  "output_format": "json",
  "acceptable_exit_codes": [0],
  "expected_artifacts": []
}
```

对于 xdebug/xcov/xentry 的 native JSON envelope，优先把请求写入项目内文件，
在 `stdin_path` 指定该文件并让 native arguments 从 `-` 读取。adapter 只在结果中
记录 stdin 的路径、大小和 SHA-256，不复制正文。

**输出**：唯一新 evidence directory，其中包含：

- `result.json`：adapter state、tool/operation、argv、cwd、允许的 environment key、
  request/stdin hash、xverif Git commit/remote/dirty、wrapper hash、exit code、
  native output format、parsed JSON（仅 JSON 模式）、artifact hashes 和 blockers；
- `stdout.log`：native stdout 原样字节，XOUT 不反解析、不重排、不加 marker；
- `stderr.log`：native stderr 原样字节；
- 状态 `PASS/FAIL/TIMEOUT/TOOL_NOT_FOUND/PROTOCOL_ERROR/MISSING_ARTIFACT`。

**人工参与**：选择正确的 native tool/action 和 CLI/MCP surface；评审 JSON schema、
argument、环境、EDA/NPI/license/LSF 条件、output completeness、result semantics 与
项目 stage evidence 的映射；决定失败后的下一动作，不允许自动 fallback。

**边界**：xverif 是可选、单独许可和维护的工具仓库，而不是统一 executable；
`.deps/xverif` 不进入 verif-harness Git/source archive/release；不得直接 pull 或
vendor 上游源码。adapter 只允许七个 one-shot
wrapper，不调用 MCP/loop/admin；不把 MCP 参数壳写进 CLI；不自动切 CLI/MCP、
JSON/XOUT、local/LSF、backend 或 data source；adapter `PASS` 不是 testcase PASS、
coverage/assertion closure、waiver、Stage approval 或 freeze。

### 5.14 `wavepeek`

**用途**：把显式、有限范围的 VCD/FST 波形查询交给固定 commit 的
`kleverhq/wavepeek` CLI，并归档可重放的工具身份、argv、stdout/stderr 和 hash
证据。典型操作包括 `info`、`scope`、`signal`、`value`、`change`、`property`
和各类 `extract`。

**适用场景**：回归失败后定位首个变化；检查某个时窗内握手或 payload；抽取
APB/AHB/AXI/AXI-Stream 传输；在 coverage/assertion triage 中取得确定性波形
事实；CI 中执行不依赖 GUI 的 VCD/FST 查询。不用于猜测信号、无限制导出整份
波形或自动宣布 root cause。

**输入**：固定上游 URL/tag/commit/version/Apache-2.0 License hash/Cargo.lock
hash/空 feature 集/四个平台官方 release archive SHA-256 的
`deps/wavepeek.lock.json`；含 `operation`、native
`arguments`、项目内 working directory、environment-key names、timeout、
`json/jsonl/text`、accepted exit codes 和 expected artifacts 的 request；以及已
授权的 VCD/FST、明确 scope/signal/time/property/protocol mapping。参数以固定
版本的 `wavepeek help/docs/schema` 为准。

**用法**：先安装并执行真实 schema smoke：

```bash
# wavepeek Skill：安装固定版本、验证 schema，并确认 adapter 可用
./scripts/setup.sh --with-wavepeek
# 或：make setup-wavepeek check-wavepeek
python3 scripts/verif_harness.py wavepeek probe  # 只执行身份/schema smoke
```

安装器只在 source 和 binary 都不存在时工作：clone exact tagged commit，校验
origin/HEAD/clean/License/Cargo.lock，下载当前平台官方 VCD/FST release archive，
校验 lock 中 SHA-256，然后原子发布 `.deps/wavepeek` 和
`.deps/wavepeek-bin/wavepeek`。已有、partial、dirty 或 mismatched 状态只返回
`BLOCKED`，不 pull、不覆盖。安装不需要 Rust 或 crates.io。

复制 `wavepeek/wavepeek-request.example.json` 后执行：

```bash
# wavepeek Skill：执行有限 VCD/FST request 并归档可重放证据
python3 scripts/verif_harness.py wavepeek run \
  --project-root . --request wavepeek-request.json \
  --out-dir artifacts/wavepeek/query-001
```

例如查询 request 的 `operation` 为 `info` 时，`arguments` 可为
`["info", "--waves", "waves/failure.vcd", "--json"]`，`output_format` 必须
为 `json`。JSONL request 必须使用 native `--jsonl`。

**输出**：安装器发布 Git-ignored `.deps/wavepeek` source 和
`.deps/wavepeek-bin/wavepeek` executable；adapter 在全新 out-dir 生成
`result.json`、`stdout.log`、`stderr.log`，记录 source Git identity、binary/
request/output/artifact hashes、argv、cwd、exit code、parsed JSON/JSONL 和
blockers。timeout、非预期 exit、非法 JSON、残缺 JSONL、缺 artifact 都 fail
closed。

**人工参与**：选择有意义的信号、时窗、采样事件、mapping、property 和 expected
value；判断结果能否支持 root cause、bug/waiver/closure；审阅 lock upgrade 与
Apache-2.0 边界。需要 FSDB 时还必须确认 Verdi SDK 许可和本地隔离策略。

**边界**：WavePeek 保持独立源码所有权和发布边界；source、binary、Cargo target
和 waveform 不进入 verif-harness Git/release。默认不启用需要专有 Verdi SDK
的 `fsdb` feature。adapter 不使用 shell、不转存 environment values、不自动
扩大查询，也不把 PASS 解释为 RTL 正确、root cause 确认或 freeze 完成。

### 5.15 `spec-kit`

**用途**：在 `verif-harness` 顶层控制面下，用固定版本 GitHub Spec Kit 管理
constitution、program/stage specification、clarification、plan、checklist、tasks、
analysis、implementation dispatch 和 convergence。它解决“每个 Stage 的执行任务
从哪份已评审规格产生、结果回写到哪条 requirement”的问题，不替代验证工具。

**适用场景**：新 RTL 验证项目从零建立规格单一事实源；每个 Stage 进入实现前
建立可审阅 spec/plan/tasks；实现后检查规格漂移；已有 approved 项目导入为不可变
baseline 后管理新 change request。不要为每条 CLI command 单独建立完整 spec；
使用 constitution → verification program → Stage/feature → task/evidence 的层级。

**输入**：

- 操作：`probe`、`bootstrap`、`stage`、`status` 或 `resume`；
- 完整 verif-harness 仓库及 `deps/spec-kit.lock.json`；
- Python 3.11 或更新版本；
- `bootstrap` 的项目根目录；
- `stage` 的 Stage `0`～`5` 和已评审 objective；
- 项目 `AGENTS.md`、只读 RTL 边界、规格来源及已有 baseline；
- Human Decisions、Provisional、open questions 和 evidence contracts。

**用法**：

```bash
./scripts/setup.sh --with-spec-kit
python3 scripts/verif_harness.py spec-kit probe
python3 scripts/verif_harness.py spec-kit bootstrap --project-root <project>
python3 scripts/verif_harness.py spec-kit stage \
  --project-root <project> \
  --stage 2 \
  --objective "接入 reference model 并建立可追踪功能对拍"
python3 scripts/verif_harness.py spec-kit status --project-root <project>
python3 scripts/verif_harness.py spec-kit resume \
  --project-root <project> <run-id>
```

对应 Codex 调用：

```text
$verif-harness spec-kit probe                                      # Skill：校验固定版本 Spec Kit
$verif-harness spec-kit bootstrap --project-root <project>         # Skill：初始化 Codex Spec Kit 项目与 preset
$verif-harness spec-kit stage --stage 2 --objective "..."          # Skill：运行一个 Stage 的规格驱动 workflow
$verif-harness spec-kit status [run-id]                            # Skill：查看 Spec Kit workflow 状态
$verif-harness spec-kit resume <run-id>                            # Skill：review 后恢复 paused workflow
```

`bootstrap` 拒绝覆盖已有 `.specify/`。`stage` 使用不含 shell step 的
`verif-stage-lifecycle.yml`，顺序为：

```text
Stage 0 only: constitution -> review
  -> specify -> review -> clarify -> review -> plan -> review
  -> checklist -> tasks -> analyze -> authorize execution
  -> implement through verif-harness modes -> converge -> review
```

`tasks.md` 中每个 task 必须声明 mode、input contract、owned output、evidence、
validation 和 Human gate。execution gate 批准后，`speckit.implement` 自动调度每个
task 对应的 mode 一次；用户不需要按照 task list 再手动逐个调用。该规则覆盖全部
被 task 声明的生成、工具委派、回归、审计和 closure modes。

dispatch 是 agentic，但完成判定不是“命令返回过”：只有 owned outputs/evidence
paths 存在且 approved validation command 通过，task 才能进入 complete。
`converge` 必须把缺失产物记录为 incomplete/deviation；恢复重试要关联原 task/run
并保留旧 evidence，不能用未追踪的重复手动调用掩盖问题。

`bootstrap`、`status/resume`、workflow review gate、独立 `stage-gate-review`、
Human approval、sign-off/freeze 授权不属于普通 implementation task 自动分发，仍按
各自权限边界执行。

每个 review gate 都会暂停 workflow。先用 `status` 定位 run、当前 gate 和对应工件；
完成该工件的实际 review 后再用 `resume` 继续。`resume` 只是恢复同一个 run，不能
跳过 review，也不会把 gate verdict 提升成 Stage approval。

preset 会把以下字段追加到标准 Spec Kit 工件：DUT 只读边界、规格权威、
REQ/VF/TC/COV/ASRT ID、verif-harness mode、owned artifact、validation、evidence、
Human gate。推荐追踪链是：

```text
REQ -> VF -> PLAN -> TASK -> MODE -> ARTIFACT -> EVIDENCE -> GATE
```

**输出**：固定版本/commit probe；`.specify/` 和 Codex Spec Kit skills；`specs/`
下的 constitution/spec/plan/tasks/checklist；workflow run state；映射到
verif-harness modes 的任务；每个已分发 task 的 output/evidence/validation
postcondition；规格漂移和 unresolved questions。`sim/docs/` 只保存
治理、生成视图、证据索引和 review packet，不是第二个可编辑 requirement source。

**不能得出的结论**：Spec Kit 命令成功、checklist 全勾选或 workflow review gate
通过，不能证明 compile/elaboration/simulation/regression/coverage/assertion/
performance PASS，也不能批准 Human Decision、waiver、Stage gate、sign-off、freeze、
commit、push 或公开发布。上游源码固定不等于 Python 传递依赖完全 artifact-pinned；
高保证或离线环境仍需维护者生成并审阅 wheel/hash lock。

## 6. 治理、闭合与发布模式

### 6.1 `audit-traceability`

**用途**：审计 feature/test/manifest/coverage/assertion ID 的结构追踪关系。

**适用场景**：计划、test、caselist 发生变化后，以及每个 stage gate 前。

**输入**：`.harness-config.json`、verification docs、TB tree；可选 manifest。

**用法**：

```bash
# audit-traceability Skill：审计 feature/test/manifest/plan 的结构映射
python3 <skill-dir>/audit-traceability/scripts/audit_traceability.py \
  --project-root . [--manifest <path>] [--json] [--out <path>] [--strict]
```

**输出**：duplicate、missing implementation、manifest mismatch、verification ID
统计、warnings/errors 和可选 JSON/report。

**人工参与**：判断 focused/retired/planned test 是否合理，并修复真正的 semantic
traceability gap。

**边界**：name/ID match 只证明结构 linkage，不证明 stimulus/checking/coverage
语义闭合；不自动修改文档或 caselist。

### 6.2 `coverage-closure`

**用途**：审计 functional coverage freeze evidence。

**适用场景**：Stage 5，coverage plan 已全部实现并完成 coverage merge。

**输入**：`coverage-evidence.json`，包含 tool/version、database IDs、每个 plan item
的 id/status/hits/plan ref、可选 approved waiver，以及 reported totals。

**用法**：

```bash
# coverage-closure Skill：审计 tool-neutral coverage evidence 与 totals
python3 <skill-dir>/coverage-closure/scripts/audit_coverage_closure.py \
  --evidence coverage-evidence.json --json \
  --out artifacts/coverage-closure.json
```

**输出**：audited covered/excluded/uncovered totals、closure percentage、blockers、
database IDs 和 `READY_FOR_HUMAN_FREEZE_REVIEW`/`BLOCKED`。

**人工参与**：对照 native VDB/UCDB/URG report，批准 denominator 和逐对象 waiver，
决定是否接受 evidence limitation。

**边界**：不解析 proprietary database、不 merge coverage、不创建 waiver；100%
reported percentage 本身不等于 closure。

### 6.3 `assertion-closure`

**用途**：审计 assertion 是否真正 compile、bind、attempt 且无未处理 failure/vacuity。

**适用场景**：Stage 5 assertion freeze review。

**输入**：`assertion-evidence.json`，包含 tool、compile/elaboration logs，以及每个
assertion 的 id、compiled、bound、attempts、passes、failures、vacuous、plan ref
和可选 approved waiver。

**用法**：

```bash
# assertion-closure Skill：审计 compile/bind/attempt/failure/vacuity 证据
python3 <skill-dir>/assertion-closure/scripts/audit_assertion_closure.py \
  --evidence assertion-evidence.json --json \
  --out artifacts/assertion-closure.json
```

**输出**：assertion/attempt/pass/failure totals、logs、blockers 和
`READY_FOR_HUMAN_FREEZE_REVIEW`/`BLOCKED`。

**人工参与**：确认 property 语义、clock/reset、vacuity、native report 和 waiver。

**边界**：source presence 或 failure=0 不足以证明 closure；不修改 checker/bind。

### 6.4 `change-control`

**用途**：审计 approved baseline 之后的 change request 和 Git diff 覆盖。

**适用场景**：frozen decision、验证架构、RTL 行为或 sign-off baseline 发生变化。

**输入**：`changes.json` 的 baseline ref，以及每个 CR 的 id/status/description/files、
reviewer/date/rationale、tests/coverage/assertions/docs/regressions impact；可选 Git
project root。

**用法**：

```bash
# change-control Skill：审计 baseline 后的 CR 与 Git diff 覆盖
python3 <skill-dir>/change-control/scripts/audit_change_control.py \
  --contract changes.json --project-root . --audit-git --json \
  --out artifacts/change-control.json
```

**输出**：CR/file counts、Git changed files、undeclared/missing/open/incomplete
blockers 和 `READY_FOR_HUMAN_REVIEW`/`BLOCKED`。

**人工参与**：批准/拒绝 CR，决定 frozen decision 是否变更，批准 RTL owner 的
修复和 rebaseline。

**边界**：输入中的 `approved` 只能记录已有 Human decision；工具不会创建批准。

### 6.5 `stage-gate-review <completed-stage>`

**用途**：从当前仓库证据生成某个 stage 的 Draft review packet。

**适用场景**：Stage N deliverables/exit criteria 已完成，准备进入 Stage N+1；
terminal Stage 使用 `--final`。

**输入**：completed stage、项目 governance/roadmap/plans、Provisional、open
questions、CR、动态 evidence 和 artifact limitations。

**用法**：

```bash
# stage-gate-review Skill：生成保持所有决定未勾选的 Draft gate packet
python3 <skill-dir>/stage-gate-review/scripts/build_stage_gate.py \
  --project-root . --completed-stage <N> \
  --out <docs-root>/stage<N>_gate_re_review.md
```

最终 stage 可加 `--final`；已有 draft 只有在批准 exact replacement 后才用
`--force`。

**输出**：所有判定保持未勾选的 Draft packet，列出 exit criteria、证据、
Provisional disposition 候选、open question 和 CR。

**人工参与**：逐项判断 PASS/FAIL/accepted limitation，处理 Provisional，填写
reviewer/date/Approval Decision。

**边界**：不能自行勾选 criterion、关闭问题、修改 frozen source decision 或批准 gate。

### 6.6 `signoff-audit <stage>`

**用途**：只读复核最终 sign-off packet 的结构和已记录批准元数据。

**适用场景**：请求 Human sign-off 前，或批准后确认仓库记录内部一致。

**输入**：project root、stage；可选 packet、authoritative manifest、strict mode。

**用法**：

```bash
# signoff-audit Skill：只读复核 sign-off packet、manifest 与批准记录
python3 <skill-dir>/signoff-audit/scripts/audit_signoff.py \
  --project-root . --stage <N> [--packet <path>] [--manifest <path>] \
  [--json] [--out <path>] [--strict]
```

**输出**：审计 findings、可选 JSON/report，以及以下状态之一：

- `INCOMPLETE`：结构 blocker；
- `READY_FOR_HUMAN_REVIEW`：结构齐全但尚无批准；
- `APPROVED_RECORDED`：packet 中已有 Human approval record。

**人工参与**：对照 regression、coverage、assertion、CI、performance、CR 和 waiver
原始证据，执行最终 sign-off。

**边界**：`APPROVED_RECORDED` 是读取结果，不是 skill 新批准；无法验证不可访问
的原始 EDA artifact。

### 6.7 `freeze-baseline`

**用途**：在 clean Git commit 上生成证据状态校验和 SHA-256 freeze manifest。

**适用场景**：Stage 5 已获得 Human approval，准备锚定最终验证基线。

**输入**：`freeze-contract.json`，包含 freeze name、baseline ref、RTL root/policy、
required evidence、JSON state checks、include files、tool versions，以及可选已存在的
Human approval record。

**用法**：

```bash
# freeze-baseline Skill：在 clean commit 上生成 SHA-256 freeze candidate
python3 <skill-dir>/freeze-baseline/scripts/build_freeze_manifest.py \
  --project-root . --contract freeze-contract.json \
  --out /tmp/freeze-candidate.json
```

**输出**：commit、branch、baseline、clean flag、RTL diff、tool versions、state
checks、每个文件的 SHA-256/size，以及：

- `READY_FOR_HUMAN_FREEZE_REVIEW`；或
- 输入已包含有效 Human approval evidence 时的 `APPROVED_RECORDED`。

**人工参与**：review commit、hash、state、RTL diff、证据限制并批准 freeze；另行
授权 tag/push/release。

**边界**：dirty tree、missing evidence、failed state 或 disallowed RTL change
直接阻塞；不修改 Git、不 tag、不 push、不批准、不公开。

### 6.8 `oss-readiness`

**用途**：检查准备公开的干净 export 是否具备社区文件、可复现 example，并扫描
敏感标识、绝对路径和 Git history。

**适用场景**：把通用 verification infrastructure 发布到公共仓库之前；不属于
内部 DUT functional freeze 主线。

**输入**：待公开 project root、community files、denylist、example/CI；可选 history。

**用法**：

```bash
# oss-readiness Skill：扫描 public export、community files 与 Git history
python3 <skill-dir>/oss-readiness/scripts/audit_oss_readiness.py \
  --project-root . --require-community --history
```

**输出**：敏感 pattern/path、缺失社区文件、example/CI 问题和整体 readiness。

**人工参与**：确认代码权属和公开权限，运行组织批准的 secret scanner，人工 review
每个 finding，并做 fresh-clone reproduction。

**边界**：零 finding 不证明无保密信息、不授予 license/publication rights，也不
执行发布。

### 6.9 `patterns [topic]`

**用途**：查询 harness、compile order、regression、lifecycle 或 Stage 2+ 合约模式。

**适用场景**：需要方法说明、设计 review 或问题解释，但不准备修改项目。

**输入**：可选 topic，例如 `stage1`、`regression`、`coverage`、`signoff`、`freeze`。

**用法**：

```text
$verif-harness patterns regression  # 查询 regression 设计与证据模式
$verif-harness patterns freeze      # 查询 sign-off/freeze 治理模式
```

**输出**：基于 `references/*.md` 的说明、约束和推荐做法。

**人工参与**：把通用 pattern 与项目 spec/architecture 对齐。

**边界**：只读说明；不会自动应用 pattern 或修改任何文件。

## 7. 人工参与清单

| 人工职责 | 主要阶段 |
| --- | --- |
| 确认规格来源、验证范围和 sign-off 标准 | Stage 0 |
| 批准 Human Decisions 和每个 Stage gate | Stage 0～5 |
| 解释有歧义的协议、位切片、数值、mask、时序和 reset 语义 | 全阶段 |
| 提供 VCS/Questa/Xcelium、Syscan、license、scheduler 和 CI runner | Stage 1～5 |
| 审阅 compile/elaboration、waveform 和原始 EDA evidence | Stage 1～5 |
| 判断 mismatch 属于 RTL、TB、Golden、spec 还是 infra | Stage 2～5 |
| 修改或批准修改 DUT RTL | 出现 RTL bug 时 |
| 批准 testcase 从 candidate 晋级 default regression | Stage 2～5 |
| 批准 coverage denominator、unreachable item 和 waiver | Stage 3～5 |
| 审阅 assertion property、attempt 和 vacuity | Stage 3～5 |
| 批准 change request 和 frozen decision 变更 | 全阶段 |
| 接受无法归档等 evidence limitation | Stage gate/sign-off |
| 最终 Stage 5 sign-off 与 verification freeze | Stage 5 |
| 授权 Git tag、push、release 或公开发布 | Freeze 后 |

## 8. 最终判定原则

以下结果都不能单独代表项目已经验证完成：

- 代码生成成功；
- compile/elaboration 成功；
- regression 进程 exit code 为 0；
- Golden mismatch 为 0 但没有 engagement proof；
- coverage 报告显示 100%，但 denominator/waiver 未审查；
- assertion failure 为 0，但 attempt 为 0 或 vacuous；
- audit 返回 `READY_FOR_HUMAN_REVIEW`；
- manifest 已生成 SHA-256。

真正的 freeze 需要动态证据、结构审计、change-control、Human Stage 5 sign-off、
clean commit freeze manifest，以及单独授权的版本控制动作共同闭合。
