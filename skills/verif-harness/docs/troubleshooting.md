# v1 troubleshooting

## Workstream 不能 freeze

运行 `$verif-harness closure evaluate --workstream NAME`，逐条检查 action。
Human review 未 approve、required desired node 非 `VALID/WAIVED`、开放 finding
都会 fail closed。确定性结果必须通过 `record evidence` 进入模型。

## 修改后状态没有变化

不要编辑 `model.md`、`plan.md` 或 `desired-state.json`。使用 `record change`、
`record evidence` 等结构化入口；它们会自动运行 VCheck/VClosure。

## 工作看起来“跳阶段”

这是预期行为。Workstream 不是线性 Stage。VClosure 可以因 coverage hole 跳到
VSTIM，也可以因 checker ambiguity 跳到 VDOC/VCHK。用 `model impact NODE`
查看跨 Workstream 因果路径。

## VReason 没有执行

`reason request` 默认只建立后端无关请求边界。先检查 `reason capabilities`，明确
Role、Backend、权限和期望 evidence，再由受控 adapter 执行。模型回答不是 evidence。
