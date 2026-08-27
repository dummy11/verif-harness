---
description: "精简、可阻塞恢复的 RTL 验证 Stage 任务清单"
---

<!--
  面向项目评审的叙述默认使用简体中文；代码、命令、路径、配置键、协议名、
  稳定标识符和原始引用保持原文。
-->

# 验证任务：[FEATURE NAME]

**目标**：[一句话说明本 task set 交付什么]
**输入**：`spec.md`、`plan.md` 与已评审合同

## 阅读规则

- `T###` 是可以非交互执行的工作；`[x]` 只由 task runner 在 postconditions
  全部通过后更新。
- `[P]` 只表示 owned paths 不重叠且 dependencies 已满足时可以并行；当前 runner
  仍按确定性顺序逐项执行。
- `B###` 是人工回答、额外 authority 或规格决策，绝不是 executable task。
- 全局边界：DUT RTL 只读；EDA、commit、push、waiver、Stage approval、sign-off、
  freeze 均需独立 authority。

## 阻塞项

<!-- 所有 B### 必须 RESOLVED 后，review-tasks/authorize-execution 才能批准。 -->

```text
- B### [OPEN|RESOLVED] [具体问题；RESOLVED 时保留决定或 authority 引用]
```

## 可执行任务

每个任务只保留一行摘要和三行执行合同。字段名保持英文以便 runner 确定性解析：

```text
- [ ] T### [VF-###] 生成接口和对应结构
  - mode: `interface`
  - outputs: `tb/interfaces/dut_if.sv`; evidence: `evidence/T001.json`
  - validate: `make compile`; needs: `none`; interaction: `none`
```

<!-- 实际任务：只保留适用的 REQ/VF/TC/COV/ASRT IDs，不复制 plan.md 的大段说明。 -->

- [ ] T001 [VF-001] [清晰动作与交付结果]
  - mode: `[verif-harness mode and reviewed arguments]`
  - outputs: `[exact owned path]`; evidence: `[exact evidence path]`
  - validate: `[reviewed noninteractive command]`; needs: `none`; interaction: `none`

- [ ] T002 [P] [VF-002] [清晰动作与交付结果]
  - mode: `[verif-harness mode and reviewed arguments]`
  - outputs: `[exact owned path]`; evidence: `[exact evidence path]`
  - validate: `[reviewed noninteractive command]`; needs: `T001`; interaction: `none`

### Stage 0 规则

新 Stage 0 项目且没有 `.harness-config.json` 时，task set 必须恰好包含一个
`mode: init` task。其 outputs 必须覆盖 harness config、`AGENTS.md`、harness assets、
派生治理视图、Stage 0 review packet 和必需目录骨架。

## 完成条件

task runner 每次只执行 `current_task_id`，并持久化
`READY -> RUNNING -> DONE|BLOCKED`。只有 outputs 与 evidence 全部存在且 validation
返回 0，runner 才将对应 checkbox 改为 `[x]`。`BLOCKED` 必须显示具体问题；
`resume <run-id> --answer "..."` 只重试同一 task，已完成 task 不重跑。
