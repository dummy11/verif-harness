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

上游要求 Python 3.11 或更新版本。顶层 setup 会安装全部受管集成；安装器固定上游源码，
但 Python 的传递依赖由
锁定版本的 `pyproject.toml` 解析；需要完全离线或供应链可复现时，维护者还应在
受控环境生成并审阅 wheel/hash lock。

## 项目初始化与 Stage 工作流

```text
# Codex
$verif-harness bootstrap --project-root . --integration codex
$verif-harness stage --project-root . --stage 1 --objective "建立可编译、可运行的最小验证环境"
$verif-harness workflow-status --project-root .
$verif-harness workflow-resume --project-root . <run-id>

# Kimi Code
/skill:verif-harness bootstrap --project-root . --integration kimi
/skill:verif-harness stage --project-root . --stage 1 --objective "建立可编译、可运行的最小验证环境"
/skill:verif-harness workflow-status --project-root .
/skill:verif-harness workflow-resume --project-root . <run-id>
```

`python3 scripts/verif_harness.py spec-kit ...` 仅用于 CI、脚本自动化和高级诊断。

`bootstrap --integration auto|codex|kimi` 解析 Codex 或 Kimi Code runtime，
初始化对应 integration，并安装本目录的本地 RTL verification preset。`auto`
只在项目中存在唯一 runtime marker 时成功；歧义或没有 marker 时要求显式选择。
Spec Kit 生成的 `.specify/integration.json` 是 runtime 唯一事实源。bootstrap
拒绝覆盖已有 `.specify/`；已有项目应通过受管 runtime switch 或人工审阅后单独
添加 preset，避免覆盖已有 constitution 或命令层。

工作流位于 `workflows/verif-stage-lifecycle.yml`，只包含 Spec Kit command、
Stage 0 constitution conditional 和 review gate，不包含 shell step。preset 位于
`preset/rtl-verification/`，将
verif-harness 治理约束追加到标准模板，并在 implement 命令前加入执行护栏。

每个 task 必须声明一个 verif-harness mode、owned outputs、evidence 和 validation
command。Codex 使用 `$verif-harness`，Kimi Code 使用
`/skill:verif-harness`；二者分发同一个 mode 合同。execution gate 批准 task set
后，`speckit.implement` 自动把每个 task 分发给对应 mode 一次；正常路径不再要求
用户逐个手动重复调用。Stage 0 的 `init` 与 Stage 1～5 的生成、工具、审计和
closure modes 都遵循同一规则。只有明确记录的失败恢复或 legacy import 才允许
直接手动调用。

切换 Agent 内部模型不改变 integration。Codex 与 Kimi Code 之间的 runtime
切换必须在稳定 review gate 执行：先检查 workflow status，再运行
`python3 scripts/verif_harness.py runtime switch --project-root <project> --to
<codex|kimi>`。该 wrapper 不会自动传 `--force`，并在切换后重新验证
`.specify/integration.json`。完整流程见 `docs/runtime_switching.md`。

一次 dispatch 只有在 task 声明的输出和证据路径全部存在、validation command
通过后才算完成。缺少任何产物时，`converge` 必须把它记录为 incomplete task 或
change request；不能用未追踪的手动重复调用掩盖缺口。

task 自动分发不会扩大权限。需要 EDA、commit、push、waiver、Stage approval 或
freeze authority 时，implement 在边界处暂停；取得独立授权后继续同一个 task，
而不是让用户在 workflow 外重新调用该 mode。

每个 gate 会让 run 进入 paused 状态。先用 `status` 确认 gate 和工件，完成对应
review 后再用 `resume` 继续；这里的 verdict 只属于该文档/执行授权 gate，不是
Stage approval。

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
