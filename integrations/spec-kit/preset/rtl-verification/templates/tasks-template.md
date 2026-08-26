---
description: "RTL 验证 Stage 可执行任务清单模板"
---

<!--
  文档语言合同：面向项目评审的叙述、标题、表格说明和待填写提示默认使用简体中文。
  代码、命令、路径、配置键、协议名、标准标识符和原始引用保持原文。
-->

# 验证任务：[FEATURE NAME]

**输入**：`/specs/[###-feature-name]/` 下的设计文档

**前置条件**：`spec.md`、`plan.md`，以及适用的 `research.md`、`contracts/`

**组织原则**：任务按规格、生成、确定性验证、动态 EDA 验证、审计和 Human gate 分组。

## 任务格式

每个任务使用以下 checklist 格式：

```text
- [ ] T001 [P?] [REQ/VF/TC/COV/ASRT ID] 任务描述和精确文件路径
```

- **[P]**：与其他任务使用不同文件且没有未声明依赖，可并行执行。
- **[REQ/VF/TC/COV/ASRT ID]**：任务对应的稳定追踪标识符。
- 描述必须包含精确路径；不允许使用“相关文件”等模糊范围。

每个任务还必须明确记录：

```text
Task ID:
REQ / VF / TC / COV / ASRT IDs:
Stage:
verif-harness mode:
Input contract:
Owned output paths:
Validation command:
Expected evidence and retention path:
Human decision or gate (if any):
Dependencies:
```

## Phase 1：规格与前置条件

- [ ] T001 [REQ/VF] 确认规格、计划、决策和开放问题已完成文档评审
- [ ] T002 [REQ/VF] 确认 DUT RTL 路径和只读边界
- [ ] T003 [REQ/VF] 确认 simulator/tool capability 状态与证据合同

---

## Phase 2：验证结构或能力生成

<!--
  根据已评审计划填写真实任务。生成文件只是 review candidate，不是已批准语义。
-->

- [ ] T004 [VF-001] 通过 `[verif-harness mode]` 生成 `[owned output path]`
- [ ] T005 [P] [VF-002] 通过 `[verif-harness mode]` 生成 `[owned output path]`

### Stage 0 特殊规则

新 Stage 0 项目且没有 `.harness-config.json` 时，任务集必须恰好包含一个
`verif-harness mode: init` 任务。其 owned outputs 必须包括 harness config、
项目指令、harness assets、派生治理视图、Stage 0 review packet 和必需目录骨架。

---

## Phase 3：确定性验证

- [ ] T006 [VF-001] 运行 `[validation command]` 并保存 `[evidence path/hash]`
- [ ] T007 [P] [VF-002] 审计结构、traceability 或配置一致性

---

## Phase 4：动态 EDA 验证（仅在单独授权后）

- [ ] T008 [TC/COV/ASRT] 使用已评审 simulator profile 和 seed 运行 `[command]`
- [ ] T009 [TC/COV/ASRT] 保存 log、database、waveform、seed 和 tool identity
- [ ] T010 [TC/COV/ASRT] 对失败执行 same-seed rerun 并保留原始证据

---

## Phase 5：收敛与 Human gate

- [ ] T011 [REQ/VF] 核对所有 owned outputs 和 validation postconditions
- [ ] T012 [REQ/VF] 记录缺失产物、规格漂移、开放问题和 change request
- [ ] T013 [REQ/VF] 准备独立的 Stage gate review packet，等待 Human review

## 依赖与执行顺序

- Phase 1 阻塞所有写操作。
- Phase 2 只执行 reviewed task 指定的 mode。
- Phase 3 必须验证 Phase 2 的实际产物。
- Phase 4 需要独立 EDA 授权，不得由 execution gate 隐式获得。
- Phase 5 依赖前序证据完整，但不得自动批准 Stage。

## 并行机会

- 只有标记 `[P]`、owned paths 不重叠且依赖已满足的任务可以并行。
- 不同 Agent 或工具产生的证据必须分别记录 provenance，不得合并成无来源结论。

## 执行与恢复规则

execution gate 批准任务集后，`speckit.implement` 必须把每个任务分发到声明的
`verif-harness mode`，且正常路径只分发一次。任务只有在全部 owned outputs 和
evidence paths 存在、validation command 通过后才完成。失败恢复必须记录到原任务，
不得用未追踪的重复调用掩盖缺口。

## 备注

- 不得修改 DUT RTL。
- Spec Kit、Agent、adapter 或工具返回 PASS 均不构成 Human approval。
- commit、push、waiver、Stage approval、sign-off 和 freeze 需要独立授权。
