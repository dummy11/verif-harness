# Skill 架构

`verif-harness` 把项目语义、结构生成、动态证据和人工权限分开处理。
生成器只接受已评审的显式合约；审计器只读取仓库或 EDA 工具导出的证据。

```text
项目 AGENTS.md + 计划文档 + 已评审合约
                       |
                       v
          verif-harness 模式分发入口
             /          |          \
          生成器       执行器       审计器
             |           |           |
         TB/文档/CI    日志/报告    findings/packet
             \           |          /
                  Human review
                       |
                 approved baseline
                       |
                  freeze manifest
```

## 模式分层

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

Regression 记录 argv、seed、隔离运行目录、日志和严格结果。CI 模式只生成
可评审 fragment；triage 只输出候选分类，并保留同 seed 重跑证据。

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
README.md                      28 模式快速目录
docs/                          用户指南、架构和故障处理
<mode>/INSTRUCTIONS.md         前置条件、流程与权限边界
<mode>/*.example.json          合约示例
<mode>/scripts/                确定性生成器和审计器
references/                    实现、回归和生命周期模式
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
