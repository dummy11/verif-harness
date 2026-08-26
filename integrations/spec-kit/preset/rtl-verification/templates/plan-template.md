<!--
  文档语言合同：面向项目评审的叙述、标题、表格说明和待填写提示默认使用简体中文。
  代码、命令、路径、配置键、协议名、标准标识符和原始引用保持原文。
-->

# 验证执行计划：[FEATURE]

**分支**：`[###-feature-name]` | **日期**：[DATE] | **规格**：[link]

**输入**：`/specs/[###-feature-name]/spec.md`

## 摘要

[从规格提取主要验证目标、Stage 范围、技术路径和预期证据。]

## 技术上下文

- **HDL/UVM 版本**：[例如 SystemVerilog/UVM 版本，或 NEEDS CLARIFICATION]
- **DUT 边界**：[只读 RTL root、top、接口、clock/reset]
- **Simulator profile**：[配置名、能力状态和版本证据]
- **测试平台架构**：[interface/UVC/harness/env/scoreboard/coverage/assertion 分层]
- **Reference model**：[backend、数据对齐、mask、数值和 compare policy]
- **测试与回归**：[testcase、seed、失败重跑和隔离策略]
- **Coverage/Assertion**：[计划映射、数据库和 closure 合同]
- **目标平台**：[OS、scheduler 或 container 边界；不得记录私有站点值]
- **性能目标**：[明确公式、阈值、操作数和证据来源]
- **约束**：[license、资源、timeout、只读路径或 NEEDS CLARIFICATION]
- **规模范围**：[interface/test/seed/coverage/assertion 数量]

## 宪章检查

*GATE：开始规划前必须满足，并在设计完成后复查。*

- [ ] DUT RTL 保持只读。
- [ ] `specs/` 是唯一可编辑规格权威。
- [ ] 每个任务都能映射到 mode、产物、证据和 Human gate。
- [ ] 工具证据与 Human approval 明确分离。
- [ ] 冻结决策的修改都有获批 change request。

## REQ/VF 执行映射

| REQ/VF | Stage | verif-harness mode | Owned artifact | Evidence contract | Human gate |
| --- | --- | --- | --- | --- | --- |
| [REQ/VF] | [0-5] | [mode] | [path] | [command/output/hash] | [review] |

计划必须定义组件 owner、compile order、simulator profile、reference-model 语义、
证据存储、失败重跑策略和 Stage entry/exit criteria，并指出不可委派给 Agent 或
确定性工具的决策。

## 项目结构

### 本 Stage 文档

```text
specs/[###-feature]/
├── spec.md
├── plan.md
├── research.md           # 适用时
├── data-model.md         # 适用时
├── quickstart.md         # 适用时
├── contracts/            # 适用时
├── checklists/
└── tasks.md
```

### 验证代码与证据

```text
[按 .harness-config.json 和已评审架构填写真实目录，不得修改 DUT RTL]
```

**结构决策**：[说明选择的真实目录、compile order 和 ownership。]

## 复杂度与偏差跟踪

> 仅记录需要评审的宪章偏差或额外复杂度；没有偏差时写“无”。

| 偏差 | 必要性 | 被拒绝的更简单方案 | Review owner |
| --- | --- | --- | --- |
| [偏差] | [原因] | [原因] | [owner] |
