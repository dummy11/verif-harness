# Skill 架构

`verif-harness` 是最上层控制面，把规格、执行能力、动态证据和人工权限分开处理。
Spec Kit 管理规格生命周期；生成器只接受已评审的显式合约；审计器只读取仓库
或 EDA 工具导出的证据。

```text
verif-harness 顶层控制面（policy / stage / dispatch / traceability）
             |                 |                    |
             v                 v                    v
      Spec Kit 规格面     verif-harness 模式     Human 权限面
 constitution/spec/plan   生成器/执行器/审计器   决策/waiver/gate
 checklist/tasks/analyze        |
             \                 v
              \        xverif/WavePeek/EDA 证据面
               \               |
                +-------- traceability --------+
```

## 模式分层

### 规格与顶层编排层

- `spec-kit`

verif-harness 决定 Stage、策略、能力分发和追踪规则；Spec Kit 负责
constitution、program/stage spec、clarify、plan、checklist、tasks、analyze、
implement-dispatch 与 converge。新项目以 `specs/` 为唯一可编辑规格事实源；其他
文档树只保存治理、生成视图、证据索引和 review packet。已批准的存量项目以不可变
baseline 导入，不重写历史审批。

规范追踪链为：

```text
REQ -> VF -> PLAN -> TASK -> MODE -> ARTIFACT -> EVIDENCE -> GATE
```

Spec Kit 是 agentic 规格框架，不是确定性验证工具。它的 command、checklist 和
workflow gate 成功不能作为仿真证据或 Human approval。

### Task 到 mode 的分发合同

每个 reviewed task 都必须声明 `MODE -> ARTIFACT -> EVIDENCE`。execution gate
批准 task set 后，`speckit.implement` 自动把每个 task 分发给对应
`$verif-harness` mode 一次；`init`、结构生成、行为实现、xverif/WavePeek、审计和
closure mode 没有例外。正常路径不要求用户在 workflow 外重复调用这些 mode。

分发是 agentic，完成判定必须依赖 task postcondition：owned output 和 evidence
路径存在、approved validation command 通过。任一条件缺失都进入 `converge` 的
incomplete/deviation 路径。直接手动重跑只允许作为有记录的 recovery，不得覆盖或
丢失前一次证据。

### Bootstrap 与结构层

- `init`
- `add-interface`
- `add-shared-pkg`
- `add-uvc-skeleton`
- `add-harness-layer`
- `add-env-layer`
- `finalize-filelist-and-make`

这一层建立目录、职责和编译顺序。Harness 独占 DUT 实例化、interface、
clock/reset 连接、tie-off、bind、adapter 和 virtual-interface 发布；`tb_top`
保持轻薄。

### 行为实现层

- `add-simulator-profile`
- `complete-uvc`
- `complete-scoreboard`
- `add-testcase`
- `add-coverage-skeleton`
- `add-assertion-skeleton`
- `add-refmodel-bridge`
- `add-performance-gate`

所有可执行行为都来自带版本的显式合约。不支持的协议、alignment、mask、
数值和性能语义必须保留为 open question，不能由名称猜测。

### 执行与集成层

- `add-regression-runner`
- `add-ci-hook`
- `regression-triage`
- `xverif`
- `wavepeek`

Regression 记录 argv、seed、隔离运行目录、日志和严格结果。CI 模式只生成
可评审 fragment；triage 只输出候选分类，并保留同 seed 重跑证据。

`xverif` 模式不重新实现 bit/debug/coverage/SVA 等确定性能力，而是把显式 JSON
request 交给 CLI adapter。adapter 只允许权威 xverif checkout 的白名单 wrapper，
固定环境与 timeout，并保存 native JSON/XOUT/text 和 Git/hash provenance。

```text
Codex Agent
   |
   v
verif-harness Skill/framework
   |  项目计划、stage policy、Human 决策边界
   v
xverif CLI adapter
   |  schema、argv、环境 key、timeout、stdout/stderr、SHA-256
   v
BLANK2077/xverif tools/<selected-tool>
   |  xbit / xdebug / xcov / xentry / xloc / xsva / xwaveform
   v
deterministic native evidence
```

默认工具根来自 `deps/xverif.lock.json` 管理的 `.deps/xverif` checkout：

```text
deps/xverif.lock.json
  -> scripts/setup_xverif.py
  -> temporary clone + exact detached commit
  -> origin/commit/clean/license/wrapper validation
  -> atomic publish .deps/xverif
  -> CLI adapter discovery
```

`.deps/xverif` 被 Git 忽略，不属于 verif-harness 源码或 release；xverif 的源码
所有权、MIT License、release 和 issue 仍归上游项目。显式 `--xverif-root` 与
`XVERIF_HOME` 只用于受控开发/部署 override，不允许失败后自动切换。

该路径不会自动从 CLI 切换 MCP、从 local 切换 LSF、从 JSON 切换 XOUT，
也不会把工具 `PASS` 提升为 Stage approval。

WavePeek 使用平行但独立的 managed 路径：

```text
deps/wavepeek.lock.json
  -> scripts/setup_wavepeek.py
  -> exact tagged source + platform release archive SHA-256
  -> .deps/wavepeek + .deps/wavepeek-bin/wavepeek
  -> WavePeek CLI adapter
  -> result.json + stdout/stderr + hashes
```

默认 build 不启用 Cargo feature，只覆盖可公开重现的 VCD/FST；需要专有 Verdi
SDK 的 FSDB 不属于 public CI。adapter 校验 JSON/JSONL 完整性并保存 provenance，
但不替代波形语义、root cause、waiver 或 closure 的人工判断。

### 治理与闭合层

- `doctor`
- `audit-traceability`
- `coverage-closure`
- `assertion-closure`
- `change-control`
- `stage-gate-review`
- `signoff-audit`
- `freeze-baseline`
- `oss-readiness`

审计器对缺失证据 fail closed。它可以报告“待人工 review”或“已记录人工批准”，
但不能批准 waiver、stage gate、freeze、公开发布，也不能修改 DUT RTL。

## 证据状态模型

```text
generated / configured
  -> dynamically tested
  -> structurally audited
  -> READY_FOR_HUMAN_*_REVIEW
  -> Human decision recorded
  -> APPROVED_RECORDED
  -> separately authorized external action
```

任何前一状态都不能静默升级成后一状态。SHA-256 只能证明文件身份，不能证明
功能正确。

## Harness 项目数据流

```text
RTL/spec（只读）
      |
      v
harness-spec + verification plans
      |
      +--> interface / shared package / UVC
      +--> DUT harness / TB harness / SVA bind
      +--> env / test / scoreboard / coverage
      |
      v
filelist + simulator profile
      |
      v
compile / simulation / regression / CI
      |
      v
traceability + coverage + assertion + performance evidence
      |
      v
stage packet -> Human sign-off -> freeze manifest
```

## Skill 资源布局

```text
SKILL.md                       模式分发与全局约束
README.md                      31 模式快速目录
docs/                          用户指南、架构和故障处理
<mode>/INSTRUCTIONS.md         前置条件、流程与权限边界
<mode>/*.example.json          合约示例
<mode>/scripts/                确定性生成器和审计器
references/                    实现、回归和生命周期模式
xverif/                        CLI request schema、example 和 adapter
wavepeek/                      波形 request schema、example 和 adapter
spec-kit/                      Spec Kit 顶层编排、规格事实源和权限边界
assets/                        Stage 0 治理资产
tests/                         合约、拒绝覆盖和 false-green 测试
```

## 人工权限边界

以下操作不属于 skill 权限：

- 修改或批准修改 DUT RTL；
- 冻结规格解释；
- 批准 Human Decision、change request 或 waiver；
- 把 testcase 晋级为 default passed regression；
- 接受缺失的原始 EDA evidence；
- 签署 stage gate 或最终 sign-off；
- 创建 release tag、push、公开发布或声明无保密风险。
