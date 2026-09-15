# v1 troubleshooting

## Workstream 不能 freeze

让 Agent 运行 `verif-harness closure evaluate --workstream NAME`，查看输出中的每一条
`action` 和 `reason`。常见原因是：当前计划还没由 Human 批准；某个必需目标还没有通过证据；
仍有未处理问题；或者相关证据互相对不上。标准 Workstream 的结果必须通过 `evidence` 或
VENV/VCHK/VCOV/VCASE/VREG 和 VSTIM capability 使用 `evidence` 登记，VSTIM 运行可达性使用
`reachability` 登记；VDOC 正文使用 `docs review`。

## 修改后状态没有变化

不要编辑 `model.md`、`plan.md` 或 `desired-state.json`，这些文件只是从 SQLite 生成的阅读
副本。文件变化用 `changed` 登记，标准证据用 `evidence` 或 `reachability` 登记；命令完成后
系统会重新检查哪些结论需要重验，并列出未完成项。

如果修改的是工程师直接维护的 VDOC Markdown，运行 `verif-harness docs sync [DOCUMENT]`。
Engine 根据正文 SHA-256 创建新的文档内容版本，保留旧评审，并把依赖旧内容的目标标为需要
重验。使用 `docs status` 或 `docs render` 查看状态；不要把 Revision Log 或 Review Trace
手工写回正文。

## VDOC 文档丢失或恢复后仍不能 freeze

`docs sync` 会将丢失文档标为 `INVALID`，且重复扫描不会制造重复 delete 事件。恢复文件后
再次运行 `docs sync`，状态会转为 `REVIEW_REQUIRED`；Human 检查恢复后的实际内容后，
Agent 才能调用 `docs review DOCUMENT`。未重新评审前 VDOC freeze 会 fail closed。

## 连续修改同一文档后 closure 报 action ID 冲突

同一问题可能因为连续保存文件而产生多个变化事件，但待办列表中只应显示一次。Engine 会在
`changed`/`docs sync` 时避免再次创建内容完全相同的未处理问题，也会在计算 `closure` 时合并
旧数据库里的重复项。历史事件不会删除；完成文档评审或登记新证据后，对应问题会正常关闭。

## 工作看起来“跳阶段”

这是预期行为。Workstream 不是线性 Stage。Verification Closure Engine 可以因 coverage hole 跳到
VSTIM，也可以因 checker ambiguity 跳到 VDOC/VCHK。用 `impact NODE`
查看跨 Workstream 因果路径。

## Verification Reasoning Engine 没有执行

`reason ROLE OBJECTIVE` 默认只建立后端无关请求边界。明确
Role、Backend、权限和期望 evidence，再由受控 adapter 执行。模型回答不是 evidence。
