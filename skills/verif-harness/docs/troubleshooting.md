# v1 troubleshooting

<a id="dashboard-无法从本地浏览器打开"></a>
## Dashboard 无法从本地浏览器打开

先区分两个端口：Dashboard 默认监听**远端服务器**的 `127.0.0.1:8765`；浏览器访问的是
**本地电脑**的转发端口。两者可以使用不同数字，但 SSH `LocalForward` 的右侧必须等于
Dashboard 启动日志中的实际远端端口。不要把 Dashboard 改为监听 `0.0.0.0`。

按以下顺序检查：

1. 如果 Dashboard 由 bootstrap 自动启动，先检查 `.verif-harness/dashboard-runtime.json` 和
   `.verif-harness/dashboard.log`；手动启动时确认 `verif-harness dashboard` 仍在运行，并记下端口。
2. 在本地电脑保持 `ssh -N ...` 隧道进程运行；该命令没有 shell 提示符是正常现象。
3. 本地执行 `curl http://127.0.0.1:<local-port>/healthz`。返回 `status: ok` 才说明隧道完整。
4. 浏览器打开同一个本地端口，而不是远端私网 IP。

常见 SSH 错误：

- `connect to host <jump> port 22: Operation timed out`：本地到跳板机尚未建立；检查 VPN，或把
  跳板机实际端口写入 `ProxyJump` 主机配置。命令行 `-p` 默认控制最终服务器，不控制跳板机。
- 跳板机 `Permission denied (publickey,...)`：跳板机没有使用正确密钥。为跳板机单独配置
  `IdentityFile` 和 `IdentitiesOnly yes`；不要假设最终服务器的 `-i` 会自动传给 ProxyJump。
- `Connection closed by UNKNOWN port 65535`：通常是前面的跳板机连接或认证失败引发的附带信息，
  先处理上一条真正错误。
- `bind ... Address already in use`：本地端口被占用。把本地端口改成其他值，例如
  `LocalForward 18765 127.0.0.1:8765`，浏览器相应访问 `127.0.0.1:18765`。
- `/healthz` 连接失败：Dashboard 已停止、隧道未运行，或转发右侧端口与远端 Dashboard 不一致。
- bootstrap 返回 `PORT_CONFLICT`：固定端口已属于另一项目或其他服务。停止冲突服务，或重新运行
  bootstrap 并显式指定 `--dashboard-port PORT`；系统不会静默切换到另一个端口。
- bootstrap 返回 `SKIPPED`：当前是 CI 或普通非交互调用；需要启动时显式使用 `--dashboard`。

完整的单跳和双跳配置见[从本地浏览器访问远端 Dashboard](user_guide.md#从本地浏览器访问远端-dashboard)。

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
