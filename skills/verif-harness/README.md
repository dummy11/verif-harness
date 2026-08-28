# verif-harness Skill v1

该 Skill 通过 `bootstrap`、`VPlan`、`VModel`、`VCheck`、`VClosure` 和
`VReason` 管理持续验证闭环。

```text
$verif-harness bootstrap --rtl-root rtl --docs-root docs
$verif-harness vplan design --workstream VDOC
$verif-harness vplan review --workstream VDOC --verdict approve \
  --reviewer NAME --reason "已评审"
$verif-harness vclosure evaluate --workstream VDOC
```

交互问题直接在当前 Agent 会话中提出；CLI 不启动后台 worker，也不把大型 Markdown
任务清单当成执行状态。所有事实、变更、证据和 Human review 都写入项目内
`.verif-harness/`。

详细说明见 [用户指南](docs/user_guide.md) 与 [Skill 架构](docs/architecture.md)。
