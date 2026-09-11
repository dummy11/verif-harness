# 验证文档治理流程

> 本文是项目验证文档的工程语义合同，不是 RTL 规格。状态、修订、评审、
> evidence 和事项生命周期由 `.verif-harness/model.sqlite3` 按需投影。

## 目的与适用范围

说明本项目如何起草、评审、维护、失效和冻结验证文档，以及 Human、Agent 和
verif-harness Engine 的责任边界。VDOC、VSTIM、VCHK、VCOV、VCASE、VREG 是可并行、
可重入的 Workstream。本项目不定义 Stage，也不采用 Spec Kit 的 `spec → plan → tasks`
流程；不得把工作域改造成必须顺序完成的阶段。

## 事实源与文档职责

| 信息 | 权威来源 | 文档用途 |
| --- | --- | --- |
| DUT 行为 | 只读 RTL/RTL spec | 引用，不改写来源语义 |
| 验证工程语义 | VDOC Markdown 文档 | 保存策略、接口、检查、覆盖和用例合同 |
| 结构化目标、关系和治理状态 | `.verif-harness/model.sqlite3` | 通过 `docs status/render` 按需投影 |
| 工程决定 | Markdown 中的完整依据 + SQLite 状态索引 | 使用稳定 ID、文档锚点和影响范围关联 |
| 工具结果 | 带来源、摘要、revision、verdict 的 evidence | 不粘贴长日志冒充结论 |

## 角色与授权

- **Human**：决定验证范围、工程取舍、内容批准、waiver 和 freeze。
- **Agent**：只读分析输入、提出问题、生成 Draft，并在取得授权后调用 CLI。
- **Engine**：持久化事实、检查一致性、传播失效、计算 closure；不作工程判断。

CLI 默认值不是 Human 授权。文件存在、模板已复制、Agent 自检或工具成功退出，都不等于
内容已批准或目标已经满足。

## 文档集、路由与同步

列出本项目的验证文档路径、对应 desired node、维护 Workstream 和主要消费者。新增
feature、testcase、coverage、assertion 或 reference-model 语义时，必须同步相应文档与
Knowledge Model 关系。

| 文档 | Desired node | 维护者 | 主要消费者 |
| --- | --- | --- | --- |
| verification_plan.md | `<VDOC-NODE>` | VDOC | 全部 Workstream |
| feature_matrix.md | `<VDOC-NODE>` | 全部 Workstream | VSTIM/VCHK/VCOV/VCASE/VREG |
| tb_architecture.md | `<VDOC-NODE>` | VDOC/VSTIM/VCHK/VREG | 实现类 capability |

## 决策分类

| 类型 | 含义 | 处理方式 |
| --- | --- | --- |
| Human Decision | Human 已明确批准的工程基线 | 修改时记录原因、影响并重新评审 |
| Provisional | 已选方向但保留复审触发条件 | 写明依据、影响和 evidence/milestone 触发器 |
| Assumption | 应由 Human 决定、当前尚未确认 | 不得写成确定事实；进入 `questions_for_human` |
| External Open Question | 依赖项目外部输入 | 写明 owner、依赖、阻塞目标和跟踪状态 |

Provisional 必须使用可观察的复审触发器，例如某个 Workstream 进入 closure、获得新的
evidence、RTL/spec 变化或指定日期。

## 起草、评审与基线

```text
Agent 形成 proposal/Draft
  → Human 审批 desired scope
  → Agent 完善正文并登记关系
  → Engine 检查一致性
  → Human 评审实际内容
  → Agent 登记真实 review evidence
  → Human 明确授权 freeze
```

规划审批与内容审批是两个独立 Human gate。允许相关 Workstream 在部分文档仍为 Draft
时并行推进，但缺少当前动作所需合同的 capability 必须停止并返回 VDOC/closure。

## 变更、失效与重新评审

验证文档正文变化后执行 `docs sync`；RTL、spec 或其他验证资产变化时使用 `changed`
登记真实变更。Engine 比较内容摘要并沿显式关系传播 `STALE` 或
`REVALIDATION_REQUIRED`。只修订受影响的内容，不因单点变化覆盖重建整套文档；旧
evidence、review 和 baseline 保留用于审计。

涉及已批准 Human Decision 的变化必须重新取得 Human 结论。普通 Living 内容可以增量
维护，但仍需记录 revision、影响范围和新的验证证据。

## 一致性与完成条件

- 文档引用的项目路径存在，且不指向可写的 RTL/spec 输出位置。
- Feature/VF、checker、coverage、case 和 evidence 使用稳定 ID 并可追踪。
- unresolved assumption/open question 明确关联受影响目标。
- 文档内容通过 Human review 后才登记 passing review evidence。
- `status`/`closure` 显示本轮 required desired node 已满足后，才可请求 freeze。

## 文档治理相关决策与开放问题

- 在正文写明问题、选项、依据和工程影响，并使用稳定 ID。
- 使用 `verif-harness docs track` 登记类型、owner、状态、复审触发器和受影响节点。
- Review Trace、Human Review Notes 与 Revision Log 不在本文手工维护；需要时使用
  `verif-harness docs render verification_workflow.md` 查看。
