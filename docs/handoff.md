# Session handoff

更新日期：2026-09-07

## 当前状态

- 当前分支是 `v1`；已推送的实现提交是
  `7c06e1d8203c5ab16537a481beccc76ef35c063d`，当时与 `origin/v1` 一致。
- `v0` 与 `v1` 是两套独立流程：`v0` 保留旧 Stage/workflow 设计；`v1` 使用持续
  Verification Knowledge Model、可重入 Workstream 和动态 closure。
- v1 不使用 Spec Kit 的 `spec -> plan -> tasks -> implement` 作为主控制流程。
- 六个 Workstream 是 `VDOC`、`VSTIM`、`VCHK`、`VCOV`、`VCASE`、`VREG`；它们可
  并行、回跳和重新规划，不是线性 Stage。
- 五个架构子系统已统一命名为：
  - Verification Planner
  - Verification Knowledge Model
  - Verification Consistency Engine
  - Verification Closure Engine
  - Verification Reasoning Engine
- 人用查询命令是 `inspect [NODE]`、`trace NODE`、`impact NODE`；旧 `model` 和 `v*`
  拼写只保留兼容解析，不在主要用户界面展示。
- 常用写入/治理命令已精简为 `plan`、`review`、`prove`、`changed`、`waive`、
  `freeze`。低层 `record` 接口继续供 Agent、adapter 和 CI 精确控制。
- 仓库 `README.md` 只介绍是什么、给谁用、能做什么和治理逻辑；setup、从空项目到
  final freeze 的完整步骤及所有参数集中在
  `skills/verif-harness/docs/user_guide.md`。

## 已验证

- 2026-09-07 在 `v1` 上完整执行 `make check`：
  - structure check PASS；
  - text format PASS（233 files）；
  - 主测试 97 项 PASS；
  - regression tool 测试 5 项 PASS；
  - capability tool 测试 6 项 PASS；
  - freeze tool 测试 9 项 PASS；
  - OSS readiness 为 `READY_FOR_HUMAN_REVIEW`，0 errors。
- CLI 专项测试包含一条完整短命令路径：`bootstrap -> 六个 Workstream 的
  plan/review/prove/freeze -> final freeze`。
- 实现提交已推送；本 handoff 的提交按 session-handoff 规则默认不自动 push。

## 卡点

- 当前没有已知代码或测试卡点。
- 尚未收到新的 v1 功能需求；下一步由用户决定。

## 下一步

1. 新 session 中说“继续”或“resume”，先读取本文件并与真实 Git 状态核对。
2. 若继续 v1，保持当前长名称与短命令边界，不重新暴露 `VPlan/VModel/...` 名称。
3. 任何新改动提交前运行 `make check`；公开发布候选再运行 `make release-check`。

## 不可破坏的约束

- DUT RTL 始终只读；不得自动批准 Human Decision、review、waiver 或 freeze。
- `VALID` 必须由真实 evidence 建立，工具成功或 Agent 文本本身不构成验证结论。
- `.verif-harness/model.sqlite3` 是机器事实源；Markdown/JSON 是阅读投影。
- 不得把 proprietary RTL、规格、日志、向量、URL、license 或调度器配置提交到公共仓库。
- 可选依赖放在 Git-ignored `.deps/`，保持独立许可和发布边界。
