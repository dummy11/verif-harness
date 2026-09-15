# 验证文档治理流程

> 本文说明项目验证文档应写什么、由谁评审、修改后怎样重新确认；它不是 RTL 规格。
> 文件版本、评审记录、证据索引和待处理事项保存在 `.verif-harness/model.sqlite3` 中，
> 通过 `verif-harness docs status/render` 查看。

## 目的与适用范围

说明本项目如何起草、评审、维护、失效和冻结验证文档，以及 Human、Agent 和
verif-harness Engine 的责任边界。VDOC、VSTIM、VCHK、VCOV、VCASE、VREG 可以同时推进，
发现新问题后也可以重新打开。本项目不定义 Stage，也不采用 Spec Kit 的 `spec → plan → tasks`
流程；不得把工作域改造成必须顺序完成的阶段。

## 事实源与文档职责

| 信息 | 权威来源 | 文档用途 |
| --- | --- | --- |
| DUT 行为 | 只读 RTL/RTL spec | 引用，不改写来源语义 |
| 工程师直接维护的验证设计 | VDOC Markdown 文档 | 保存策略、接口规则、检查方法、覆盖目标和用例设计 |
| 目标、依赖、文件版本和评审状态 | `.verif-harness/model.sqlite3` | 通过 `docs status/render` 查看 |
| 工程决定 | Markdown 中的完整依据 + SQLite 状态索引 | 使用稳定 ID、文档锚点和影响范围关联 |
| 工具结果 | 带原始文件路径、SHA-256、项目版本和 PASS/FAIL 的 evidence | 不粘贴长日志冒充结论 |

## 三种角色分别做什么

- **Human（项目工程师或负责人）**：决定验证范围和工程取舍；判断文档内容是否可以接受；
  决定是否接受未满足项（waiver）以及是否保存当前基线（freeze）。
- **Agent（当前 Codex/Kimi 会话）**：只读分析 RTL 和规格、提出问题、生成初稿、运行工程工具；
  只有在 Human 已明确作出上述决定后，才调用相应 CLI 记录决定。
- **Engine**：保存 Agent 已登记的信息；检查文件版本和证据格式；一个输入修改后，列出哪些目标
  需要重新验证；再列出当前还缺什么。它不判断规格含义，也不决定验证方案。

CLI 默认值不表示 Human 已经同意。文件存在、模板已复制、Agent 自检或工具成功退出，都不等于
内容已批准或目标已经满足。

## 文档集、路由与同步

列出本项目的验证文档路径、对应目标节点、由哪个 Workstream 维护，以及哪些工作会读取它。
新增验证点、用例、覆盖项、断言或参考模型规则时，必须同步相应文档和数据库中的依赖关系。

| 文档 | 对应目标节点 | 维护者 | 哪些工作会读取它 |
| --- | --- | --- | --- |
| verification_plan.md | `<VDOC-NODE>` | VDOC | 全部 Workstream |
| feature_matrix.md | `<VDOC-NODE>` | 全部 Workstream | VSTIM/VCHK/VCOV/VCASE/VREG |
| tb_architecture.md | `<VDOC-NODE>` | VDOC/VSTIM/VCHK/VREG | 实现类 capability |

## 决策分类

| 类型 | 含义 | 处理方式 |
| --- | --- | --- |
| Human Decision | Human 已明确批准的工程基线 | 修改时记录原因、影响并重新评审 |
| Provisional（暂定方案） | 已选方向但以后需要重新确认 | 写明依据、影响，以及什么事件发生后必须重审 |
| Assumption | 应由 Human 决定、当前尚未确认 | 不得写成确定事实；进入 `questions_for_human` |
| External Open Question | 依赖项目外部输入 | 写明 owner、依赖、阻塞目标和跟踪状态 |

暂定方案必须写明可以明确判断的重审条件，例如某个 Workstream 已满足当前目标、取得新的
证据、RTL/spec 修改或到达指定日期。

## 起草、评审与基线

```text
Agent 形成待评审方案和文档初稿
  → Human 确认本轮目标和完成条件
  → Agent 完善正文并登记关系
  → Engine 检查文件版本、证据格式和已登记关系
  → Human 评审实际内容
  → Agent 登记这次评审及其对应的文件 SHA-256
  → Human 明确同意保存当前基线
```

确认“本轮准备做什么”和确认“实际文档内容可以接受”是两个不同决定。部分文档仍是初稿时，
其他 Workstream 可以继续不依赖这些内容的工作；如果当前工作需要的接口规则或比较规则尚未
明确，则必须停止这项工作，回到 VDOC 补全文档并再次检查未完成项。

## 变更、失效与重新评审

验证文档正文变化后执行 `docs sync`；RTL、spec 或其他验证资产变化时使用 `changed`
明确登记具体修改过的文件。Engine 比较文件 SHA-256，并按照数据库中已经登记的依赖关系，
把受影响目标标为 `STALE` 或 `REVALIDATION_REQUIRED`。只修订受影响的内容，不因一个文件修改
而覆盖重建整套文档；旧证据、评审记录和基线保留，便于以后查明当时依据的是哪个版本。

涉及已批准人工决定的内容修改，必须由 Human 重新确认。允许持续更新的普通内容可以逐步修改，
但仍要记录新的文件版本、受影响目标和重新取得的验证证据。

## 一致性与完成条件

- 文档引用的项目路径存在，且不指向可写的 RTL/spec 输出位置。
- Feature/VF、checker、coverage、case 和 evidence 使用稳定 ID 并可追踪。
- 尚未确认的假设或问题明确关联受影响目标。
- Human 明确接受当前文档内容后，才登记通过评审的证据。
- `status`/`closure` 显示本轮所有必需目标已满足后，才可请求保存基线（freeze）。

## 文档治理相关决策与开放问题

- 在正文写明问题、选项、依据和工程影响，并使用稳定 ID。
- 使用 `verif-harness docs track` 登记类型、owner、状态、复审触发器和受影响节点。
- Review Trace、Human Review Notes 与 Revision Log 不在本文手工维护；需要时使用
  `verif-harness docs render verification_workflow.md` 查看。
