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
./scripts/setup.sh --with-spec-kit
make check-spec-kit
```

上游要求 Python 3.11 或更新版本。安装器固定上游源码，但 Python 的传递依赖由
锁定版本的 `pyproject.toml` 解析；需要完全离线或供应链可复现时，维护者还应在
受控环境生成并审阅 wheel/hash lock。

## 项目初始化与 Stage 工作流

```bash
python3 scripts/verif_harness.py spec-kit bootstrap --project-root /path/to/project
python3 scripts/verif_harness.py spec-kit stage \
  --project-root /path/to/project \
  --stage 1 \
  --objective "建立可编译、可运行的最小验证环境"
python3 scripts/verif_harness.py spec-kit status --project-root /path/to/project
python3 scripts/verif_harness.py spec-kit resume \
  --project-root /path/to/project <run-id>
```

`bootstrap` 初始化 Codex integration，并安装本目录的本地 RTL verification
preset。它拒绝覆盖已有 `.specify/`。已有 Spec Kit 项目应由人工审阅后单独添加
preset，避免覆盖已有 constitution 或命令层。

工作流位于 `workflows/verif-stage-lifecycle.yml`，只包含 Spec Kit command、
Stage 0 constitution conditional 和 review gate，不包含 shell step。preset 位于
`preset/rtl-verification/`，将
verif-harness 治理约束追加到标准模板，并在 implement 命令前加入执行护栏。

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
