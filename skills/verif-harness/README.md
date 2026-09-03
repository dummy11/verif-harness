# verif-harness Skill v1

该 Skill 通过 Verification Planner、Verification Knowledge Model、Verification
Consistency Engine、Verification Closure Engine 和 Verification Reasoning Engine
管理持续验证闭环。

人只需在 Codex 中输入 `$verif-harness`，或在 Kimi 中输入
`/skill:verif-harness`，再描述当前目标。底层 CLI 的常用形式是：

```text
verif-harness bootstrap
verif-harness plan VDOC
verif-harness review
verif-harness status
verif-harness prove NODE results/evidence.json
verif-harness freeze VDOC
```

交互问题直接在当前 Agent 会话中提出；CLI 不启动后台 worker，也不把大型 Markdown
任务清单当成执行状态。所有事实、变更、证据和 Human review 都写入项目内
`.verif-harness/`。Agent 不得修改 DUT RTL、代替 Human review/waiver/freeze，或把工具
退出码冒充验证结论。

完整操作与参数见[用户指南](docs/user_guide.md)，系统边界见
[Skill 架构](docs/architecture.md)。
