# verif-harness v1

verif-harness 是持续闭环的 RTL 验证工程控制面。它把验证计划、实现事实、
变更失效、证据和 Human review 放进同一个可追溯模型，而不是执行一份冻结的
大型任务文档。

```text
VPlan -> VModel -> VCheck -> VClosure -> act / verify / review
   ^                                           |
   +-------------------------------------------+
                         VReason 仅处理歧义
```

## 快速开始

```bash
./scripts/setup --runtime codex --workspace-root /path/to/project
```

进入项目后：

```text
$verif-harness bootstrap --rtl-root rtl --docs-root docs
$verif-harness plan design --workstream VDOC
$verif-harness plan review --workstream VDOC --verdict approve \
  --reviewer alice --reason "文档 desired state 已评审"
$verif-harness closure evaluate --workstream VDOC
```

CLI 默认输出结构化 JSON；`.verif-harness/model.md` 与各 Workstream 的 `plan.md`
用于人工阅读，SQLite 数据库是机器事实源。

## 五个核心子系统

- **VPlan**：以详细通用模板、当前 VModel 和人工交互设计/修订 Workstream desired state。
- **VModel**：保存 typed node、relation、provenance、confidence、evidence 与 validity。
- **VCheck**：检测结构问题，并沿关系传播 `STALE` 与
  `REVALIDATION_REQUIRED`。
- **VClosure**：比较 desired state 与当前事实，只返回最小下一动作集。
- **VReason**：为无法确定性解决的歧义生成后端无关结构化请求。

`VDOC/VSTIM/VCHK/VCOV/VCASE/VREG` 是可并行、可重入的工作上下文，不是
DOC→激励→对比→覆盖→case→回归的流水线。每个 Workstream 内部也会反复
plan/act/observe/replan；VClosure 根据实时 gap 在它们之间跳转。

机器规划真相只有 VModel 与 revisioned desired state；Markdown 是投影，避免
同时维护另一套规划真相。

## 底层能力

xverif、WavePeek、RTL/UVM 生成器、回归、覆盖率、断言、traceability 和发布审计
仍作为可复用能力存在。VClosure 推荐何时调用它们，但不会静默执行写操作。

DUT RTL 永远只读；工具成功不等于验证通过；Agent 不得代替 Human 审批。

详细用法见 [用户指南](skills/verif-harness/docs/user_guide.md) 和
[架构说明](ARCHITECTURE.md)。

## 开发检查

```bash
make check
make release-check
```

`make release-check` 只用于公开发布候选。不要把 proprietary RTL、规格、日志、
波形、license 配置或调度器配置提交到本仓库。
