# verif-harness

verif-harness 是面向 RTL/ASIC 验证项目的持续验证控制面。它把验证目标、工程事实、
变更影响、验证证据和人工决策放进同一个可追溯模型，让项目能够持续回答：

- 当前想证明什么？
- 现在已经实现和证明了什么？
- 哪些结论因 RTL、规格或验证环境变化而失效？
- 下一步应执行工具、调用推理，还是等待人工决策？
- 依据什么证据可以冻结 Workstream 或最终验证基线？

它不是新的仿真器，也不是一份从头跑到尾的 `tasks.md`。它位于工程师、Agent、
xverif、WavePeek、仿真器、回归系统和验证代码之上，负责持续规划、治理和追溯。

## 给谁使用

- **验证工程师**：规划验证目标，组织激励、检查器、覆盖率、用例和回归工作。
- **验证负责人/Reviewer**：评审 desired state、处理风险与豁免、冻结可审计基线。
- **验证基础设施工程师**：把编译、仿真、波形、回归和生成器接入统一控制面。
- **Codex/Kimi Agent**：依据当前模型执行有边界的工程动作，而不是凭聊天历史猜测状态。

它适合验证工作反复迭代、并行推进的项目。文档、激励、检查器、覆盖率、用例和回归
都可以随新发现重新打开，不要求按固定 Stage 顺序一次做完。

## 能做什么

verif-harness 将验证工程划分为六个可并行、可重入的 Workstream：

| Workstream | 负责内容 |
| --- | --- |
| `VDOC` | 验证定义、feature、架构、策略、风险和决策 |
| `VSTIM` | driver、sequence、constraint 和场景激励 |
| `VCHK` | reference model、scoreboard、checker 和 assertion |
| `VCOV` | coverage model、目标、采集和 hole closure |
| `VCASE` | testcase、virtual sequence 和场景组合 |
| `VREG` | compile、simulation、regression、rerun 和 triage |

围绕这些 Workstream，它提供：

- 详细通用模板与当前项目事实驱动的 desired-state 规划；
- typed node、relation、provenance、validity、finding 和 evidence 模型；
- RTL、规格及验证资产变化后的跨 Workstream 失效传播；
- 基于当前 gap 动态计算的最小下一动作，而非冻结的大型任务列表；
- xverif、WavePeek、回归及代码生成能力的受控接入；
- Human review、waiver、Workstream baseline 和 final freeze 审计链；
- Codex/Kimi 运行环境、受管 Python 依赖和项目级 xverif MCP 配置。

## 运行逻辑

全局闭环以 Verification Knowledge Model 为中心：

```text
Human intent
    |
    v
Verification Planner ---- Human review ----> desired state
    |                                |
    v                                v
Verification Knowledge Model <--- evidence --- tools / simulators
    |
    +----> Verification Consistency Engine ----> validity + causal findings
    |                         |
    +----> Verification Closure Engine <--------+
                 |
                 +---- deterministic action
                 +---- Verification Reasoning Engine request
                 +---- Human decision
```

一次工具成功不等于验证通过。结果必须作为 evidence 绑定到明确目标；Verification
Consistency Engine 再判断有效性，Verification Closure Engine 再判断 closure。任何新的 change 或 finding 都可以使既有结论变为
`STALE`、`REVALIDATION_REQUIRED` 或 `INVALID`，并把工作路由回任意 Workstream。

## 五个核心子系统

用户不需要先理解内部实现才能使用，但理解下面的职责边界有助于判断“谁应做什么”：

| 子系统 | 唯一职责 | 不负责 |
| --- | --- | --- |
| **Verification Planner** | 根据模板、当前知识模型和人工判断形成/修订 desired state | 不生成一次性大任务流水线 |
| **Verification Knowledge Model** | 保存事实、关系、来源、状态、证据和历史 | 不推断工程结论，不替代文档评审 |
| **Verification Consistency Engine** | 执行确定性检查和失效传播 | 不修代码，不处理语义歧义 |
| **Verification Closure Engine** | 比较 desired/current state，选择最小下一动作 | 不静默执行写操作，不批准 gate |
| **Verification Reasoning Engine** | 为语义不确定问题生成结构化分析与建议 | 不制造 evidence，不代替 Human 决策 |

Capability tools 负责实际工程动作；Human 负责语义批准、拒绝、修改、豁免和冻结。

## 治理原则

- `.verif-harness/model.sqlite3` 是机器事实源；Markdown/JSON 是可评审投影。
- desired state 是“需要成立的状态”，不是必须顺序执行的 task 清单。
- `VDOC/VSTIM/VCHK/VCOV/VCASE/VREG` 是工作上下文，不是线性生命周期。
- 确定性工作交给工具；只有语义歧义进入 Verification Reasoning Engine。
- `VALID` 必须由真实 evidence 建立；`WAIVED` 必须由 Human 明确给出理由。
- Workstream freeze 和 final freeze 生成不可覆盖的内容寻址基线。
- DUT RTL 始终只读；Agent 不得代替 Human 审批，也不得把工具退出码冒充 sign-off。
- proprietary RTL、规格、日志、向量、URL、license 和调度器配置不得进入公共仓库。

## 文档入口

- [用户指南](skills/verif-harness/docs/user_guide.md)：安装、从 bootstrap 到 final freeze
  的完整步骤、全部命令及参数、常见闭环场景。
- [架构说明](ARCHITECTURE.md)：控制环、状态模型、子系统与 RTL 分层边界。
- [故障排查](skills/verif-harness/docs/troubleshooting.md)：运行环境与工具问题。
- [Skill 入口](skills/verif-harness/SKILL.md)：Codex/Kimi 使用 verif-harness 时的行为边界。

## 项目状态

v1 当前使用可重入 Workstream 和持续 closure 模型。xverif、WavePeek 等可选能力
保持独立许可和发布边界；v1 主控制流程不依赖外部 specification workflow。

提交前运行 `make check`；公开发布候选运行 `make release-check`。测试通过只说明
结构和契约满足，不代表任何外部仿真器已得到验证或项目已经 sign-off。
