# v1 troubleshooting

<a id="dashboard-无法从本地浏览器打开"></a>
## Dashboard 无法从本地浏览器打开

先区分两个端口：Dashboard 默认监听**远端服务器**的 `127.0.0.1:8765`；浏览器访问的是
**本地电脑**的转发端口。两者可以使用不同数字，但 SSH `LocalForward` 的右侧必须等于
Dashboard 启动日志中的实际远端端口。不要把 Dashboard 改为监听 `0.0.0.0`。

按以下顺序检查：

1. 运行 `verif-harness dashboard --status`。bootstrap 和直接运行 `verif-harness dashboard`
   都使用同一个后台注册/启动/复用动作；`RUNNING` 才表示服务正在监听且当前项目已经注册。
   `NOT_REGISTERED` 表示共享服务还在、但当前项目尚未加入，直接运行 `verif-harness dashboard`
   即可注册。需要恢复时再次运行
   `verif-harness dashboard`，并检查当前项目的 `.verif-harness/dashboard-runtime.json` 和共享服务的
   `~/.verif-harness/dashboard/dashboard.log`。不要使用 `verif-harness dashboard --foreground | head`，管道关闭会使
   前台调试服务退出。
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
- `channel ... open failed: connect failed: Connection refused`：SSH 隧道仍在，但远端转发目标没有
  服务监听。先在远端运行 `verif-harness dashboard --status`，若不是 `RUNNING`，再运行
  `verif-harness dashboard` 恢复后台服务；不必重建项目状态。
- 多个项目依次 bootstrap：不会冲突。第一个项目启动 `8765` 上的共享服务，后续项目注册独立入口并
  复用它；顶部项目选择器只切换请求路由，不会合并项目的 SQLite、节点、问题、审批或证据。
- bootstrap 返回 `PORT_CONFLICT`：固定端口属于非 verif-harness 服务，或仍在运行升级前的旧版
  单项目 Dashboard。先停止该旧服务后重新运行 bootstrap；也可以显式指定
  `--dashboard-port PORT`，但系统不会静默换端口。
- 不再需要某个项目入口：在 Dashboard 顶部选择它并点击“注销项目”，或在该项目根目录运行
  `verif-harness dashboard --stop`。两种方式都不删除项目数据；有其他项目时共享服务继续运行，
  最后一个项目注销后才停止服务。
- bootstrap 返回 `SKIPPED`：当前是 CI 或普通非交互调用；需要启动时显式使用 `--dashboard`。

完整的单跳和双跳配置见[从本地浏览器访问远端 Dashboard](user_guide.md#从本地浏览器访问远端-dashboard)。

## Dashboard 已回答，但 Kimi CLI 没有继续

先看 Kimi 是否已经回到原生 `>` 提示符。如果是，说明当前 turn 已结束，没有正在等待 Dashboard
答案的 runtime checkpoint。Dashboard 会把答案可靠写入项目 SQLite，但不会向 idle 的 Kimi 会话
注入 prompt，因此旧会话不会自行“被唤醒”。

当前会话的恢复方法是在 Kimi 的 `>` 输入：`继续，读取并处理 question:QUESTION_ID 的已回答结果`。
Main Agent 应先读取该问题的持久化状态，再继续后续 plan、document、evidence 或 review 流程。

新安装或刷新后的受管 Kimi Main Agent 会遵守新的 checkpoint 规则：阻塞型
`verif-harness agent-question ask` 默认登记问题后等待最多 300 秒；Human 在 Dashboard 回答时，命令
返回 `AgentQuestionCheckpoint/1` 并在同一个 turn 中继续。若返回 `TIMEOUT` 且问题仍为 `OPEN`，Main
Agent 必须立即运行 `verif-harness agent-question await QUESTION_ID --timeout 300`。交互式 Main Agent
不得使用 `--no-wait`，也不得在开放问题仍存在时先结束 turn。已有 Kimi 会话需重启后才会加载新的
项目 Main Agent profile。Kimi 的前台 Bash 默认等待较短；如果等待命令被自动转成后台任务，受管
profile 会要求 Main Agent 用 `WaitFor` 继续等待该任务，而不是把转后台误认为问题已经处理完成。

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
