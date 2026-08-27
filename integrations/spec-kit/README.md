# Spec Kit 集成

本目录把 GitHub Spec Kit 作为 `verif-harness` 的可选规格子系统：

```text
verif-harness（顶层控制面）
  -> Spec Kit（规格面：constitution/spec/plan/tasks/checklist）
  -> verif-harness modes（执行能力面）
  -> xverif / WavePeek / simulator（证据面）
  -> Human（审批与语义决策面）
```

Spec Kit 生成和维护规格工件，但不拥有 DUT RTL、验证证据或审批权。命令成功只
说明 agentic workflow 已执行，不能替代编译、仿真、coverage、assertion、性能或
签核证据。

## 本地安装

Spec Kit 被固定到 `deps/spec-kit.lock.json` 中的 release tag、完整 commit 和文件
哈希，并安装到 Git 忽略的 `.deps/`：

```bash
cd /path/to/verif-harness
./scripts/setup --no-agent
make check-spec-kit
```

This installs the pinned Spec Kit environment below the verif-harness package
checkout. To configure a separate RTL project, pass its path and runtime to
`setup.sh`; the subsequent Skill bootstrap commands run from that target
project.

The target project contains a runtime-native Skill link, not a second package
copy. When the Agent dispatches a package command from that workspace, it must
use `.agents/skills/verif-harness/scripts/verif-harness` for Codex or
`.kimi-code/skills/verif-harness/scripts/verif-harness` for Kimi Code. The
launcher resolves the link back to this complete checkout before accessing
`scripts/`, `deps/`, or `integrations/`; their absence below the target project
root is expected and must not be reported as a missing installation.

上游要求 Python 3.11 或更新版本。顶层 setup 会安装全部受管集成；安装器固定上游源码，
但 Python 的传递依赖由
锁定版本的 `pyproject.toml` 解析；需要完全离线或供应链可复现时，维护者还应在
受控环境生成并审阅 wheel/hash lock。

## 项目初始化与 Stage 工作流

```text
# Codex
$verif-harness bootstrap
$verif-harness stage --stage 1 --objective "建立可编译、可运行的最小验证环境"
$verif-harness status
$verif-harness resume <run-id> --verdict approve

# Kimi Code
/skill:verif-harness bootstrap
/skill:verif-harness stage --stage 1 --objective "建立可编译、可运行的最小验证环境"
/skill:verif-harness status
/skill:verif-harness resume <run-id> --verdict approve
```

These normal Agent commands inherit the setup-selected workspace and runtime.
Use explicit `--project-root` or `--integration` only from automation, outside
the workspace, or when runtime markers are ambiguous.

`python3 scripts/verif_harness.py spec-kit ...` 仅用于 CI、脚本自动化和高级诊断。

runtime-native launcher 会把 `stage` 和 `resume` 启动为独立 worker，立即返回
run ID、PID 和 `.specify/workflows/runs/<run-id>/verif-harness-worker.log`。Agent 应使用
`status <run-id>` 轮询，不要再用 600 秒或其他固定时限的 bash 后台任务包裹
这两个命令，也不要在 worker 存活时重复启动同一 Stage。底层 Python wrapper 默认仍
以前台方式运行；自动化需要后台行为时可显式传 `--detach`。

`bootstrap --integration auto|codex|kimi` 解析 Codex 或 Kimi Code runtime，
初始化对应 integration，并安装本目录的本地 RTL verification preset。`auto`
只在项目中存在唯一 runtime marker 时成功；歧义或没有 marker 时要求显式选择。
Spec Kit 生成的 `.specify/integration.json` 是 runtime 唯一事实源。bootstrap
拒绝覆盖已有 `.specify/`；已有项目应通过受管 runtime switch 或人工审阅后单独
添加 preset，避免覆盖已有 constitution 或命令层。

工作流位于 `workflows/verif-stage-lifecycle.yml`，只包含 Spec Kit command、
Stage 0 constitution conditional 和 review gate，不包含 shell step。preset 位于
`preset/rtl-verification/`，以完整的 RTL 专用中文模板替换五个标准项目工件模板，
并在 implement 命令前加入执行护栏。`specs/`、constitution、plan、tasks、checklist
等面向项目评审的 Markdown 默认使用简体中文；代码、命令、路径、配置键、协议名、
标准标识符和原始引用保持原文。`.specify/` 中的上游内部命令和运行文件继续保留其
发行语言，不作为项目规格交付物翻译。
bootstrap 随后启用上游自带的 `constitution-sync`，把尚未人工编辑的初始
constitution 安全同步为当前中文模板；已有人工内容不会被静默覆盖。

bootstrap 最后生成 `.specify/docs/zh-CN/` 中文阅读镜像。它按英文源文件相对路径
保存中文模板、已有中文文件或中文导读，并在 `manifest.json` 中记录双方 SHA-256
以及 `full|source-is-chinese|summary|pending` 状态。该目录不参与 template
resolution、command discovery 或 workflow，也不是规格、证据或审批事实源。已有项目
可通过 `$verif-harness spec-kit docs-zh` 刷新；Stage workflow 和 resume 成功后也会
自动刷新。

`tasks.md` 采用一行摘要加三行紧凑合同。每个 `T###` 必须声明一个
verif-harness mode、owned outputs、evidence、validation、dependencies，且
`interaction: none`。人工回答、额外 authority 和规格决策必须写成 `OPEN B###`，
不得伪装成 executable task；存在 OPEN blocker 时 wrapper 会拒绝批准
`review-tasks` 或 `authorize-execution`。
`review-tasks` 批准时 wrapper 记录不含 checkbox 的 contract SHA-256；analyze 或其他
步骤若改动 mode/outputs/evidence/validation/dependencies，execution authorization
会失败并要求重新评审。

execution gate 批准后，wrapper 的独立 task runner 持久化
`READY/RUNNING/DONE/BLOCKED`，每次只把 `current_task_id` 分发给 Codex 的
`$verif-harness` 或 Kimi Code 的 `/skill:verif-harness`。outputs/evidence 存在且
validation 返回 0 后才写 `[x]`，已完成 task 永不重跑。Stage 0 的 `init` 与
Stage 1～5 的生成、工具、审计和 closure modes 都遵循同一规则。

切换 Agent 内部模型不改变 integration。Codex 与 Kimi Code 之间的 runtime
切换必须在稳定 review gate 执行：先检查 workflow status，再运行
`python3 scripts/verif_harness.py runtime switch --project-root <project> --to
<codex|kimi>`。该 wrapper 不会自动传 `--force`，并在切换后重新验证
`.specify/integration.json`。完整流程见 `docs/runtime_switching.md`。

一次 dispatch 只有在 task 声明的输出和证据路径全部存在、validation command
通过后才算完成。缺少任何产物时，`converge` 必须把它记录为 incomplete task 或
change request；不能用未追踪的手动重复调用掩盖缺口。

task 自动分发不会扩大权限。当前 task 遇到未预先授权的人工作业、EDA、commit、
push、waiver、Stage approval、freeze authority 或规格歧义时，Agent 必须调用
`block <run-id> <task-id> --kind ... --question ...`。wrapper 观察到持久化
`BLOCKED` 后会终止当前子 Agent；`status` 显示问题，取得回答后用
`resume <run-id> --answer "..."` 只重试该 task。

每个 gate 会让 run 进入 paused 状态。wrapper 对 workflow 子进程关闭交互 stdin，
因此即使 Agent 使用 PTY，也不会用一次数字输入穿过当前 gate 后在下一 gate 因 EOF
默认拒绝。先用 `status` 确认 gate 和工件，完成对应 review 后再用
`resume <run-id> --verdict approve|reject` 继续。每次 resume 只绑定当前 gate；下一
gate 会再次暂停。这里的 verdict 只属于该文档/执行授权 gate，不是 Stage approval。
工作流在 checklist、tasks、analyze、task execution 和 converge 之间设置独立边界。
task execution 不再调用上游 monolithic `speckit.implement`；preset 将该命令替换为
fail-closed 说明，防止脱离 run identity 后执行整份 task set。

如果旧版本被外层 timeout 杀死且状态残留为 `running`，先查看 worker log 并确认 PID
和关联 workflow 进程均已退出，再由用户显式执行
`recover <run-id> --confirm-stale`。该命令保留当前 step 与已有结果，把 run
改为可恢复的 `failed`，随后用 `resume <run-id>` 重试当前 step；检测到活进程
时会拒绝恢复，也不会自动创建替代 run。

若中断发生在 task runner，recover 会先重新检查 current task 的 outputs、evidence 和
validation：postconditions 已满足则直接记为 `DONE`，不重复副作用；否则转为明确
`BLOCKED`，随后只恢复该 task。检测到记录的 task PID 仍存活时同样拒绝恢复。

## 单一事实源

- 新项目：`specs/` 是规格的唯一可编辑事实源。
- `sim/docs/` 或其他文档树只能保存治理说明、生成视图、证据索引和 review packet，
  不得与 `specs/` 同时成为可编辑规格权威。
- 已完成项目：先把现有批准文档作为不可变 baseline 导入和链接；不要为迁移而
  重写历史审批或伪造 Spec Kit 开发轨迹。
- 推荐追踪链为
  `REQ -> VF -> PLAN -> TASK -> MODE -> ARTIFACT -> EVIDENCE -> GATE`。

`bundle/` 是供未来 catalog 发布使用的组合 manifest。在它进入受信任 catalog 前，
本地使用应直接安装 preset 并通过本仓库工作流路径运行。
