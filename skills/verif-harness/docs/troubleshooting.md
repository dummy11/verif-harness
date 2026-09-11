# v1 troubleshooting

## Workstream 不能 freeze

运行 `$verif-harness closure evaluate --workstream NAME`，逐条检查 action。
Human review 未 approve、required desired node 非 `VALID/WAIVED`、开放 finding
都会 fail closed。确定性结果必须通过 `record evidence` 进入模型。

## 修改后状态没有变化

不要编辑 `model.md`、`plan.md` 或 `desired-state.json`。使用 `record change`、
`record evidence` 等结构化入口；它们会自动运行 Verification Consistency Engine
和 Verification Closure Engine。

如果修改的是 VDOC 工程语义 Markdown，运行 `verif-harness docs sync [DOCUMENT]`。
Engine 根据正文摘要增加 semantic revision、保留旧评审并传播失效。使用 `docs status`
或 `docs render` 查看治理状态；不要把状态、Revision Log 或 Review Trace 手工写回正文。

## VDOC 文档丢失或恢复后仍不能 freeze

`docs sync` 会将丢失文档标为 `INVALID`，且重复扫描不会制造重复 delete 事件。恢复文件后
再次运行 `docs sync`，状态会转为 `REVIEW_REQUIRED`；Human 检查恢复后的实际内容后，
Agent 才能调用 `docs review DOCUMENT`。未重新评审前 VDOC freeze 会 fail closed。

## 工作看起来“跳阶段”

这是预期行为。Workstream 不是线性 Stage。Verification Closure Engine 可以因 coverage hole 跳到
VSTIM，也可以因 checker ambiguity 跳到 VDOC/VCHK。用 `model impact NODE`
查看跨 Workstream 因果路径。

## Verification Reasoning Engine 没有执行

`reason request` 默认只建立后端无关请求边界。先检查 `reason capabilities`，明确
Role、Backend、权限和期望 evidence，再由受控 adapter 执行。模型回答不是 evidence。
