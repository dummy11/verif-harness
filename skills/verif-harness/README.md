# verif-harness 使用指南

`verif-harness` 是面向 RTL module-level verification 的 Codex skill，覆盖
Stage 0 文档基线、UVM/harness 实现、Golden 对拍、coverage/assertion、回归、
CI、sign-off 和 verification freeze candidate。

它包含 28 个模式。所有写模式默认只增不覆盖；DUT RTL、Human Decisions、
waiver、stage gate 和最终 freeze approval 始终在 Human 权限边界内。

## 基本使用

在验证项目根目录调用：

```text
$verif-harness doctor
$verif-harness add-testcase
$verif-harness stage-gate-review 4
```

未指定模式时：

- 存在 `.harness-config.json`：执行只读 `doctor`。
- 不存在 `.harness-config.json`：从 `init` 开始。
- 状态不明确时只报告冲突，不自动执行写模式。

## 28 个模式

<!-- markdownlint-disable MD013 -->

| 模式 | 用途 | 使用场景 | 示例 |
| --- | --- | --- | --- |
| `init` | 建立 Stage 0 文档、治理和目录骨架 | 新项目尚无 harness 配置 | `$verif-harness init` |
| `add-interface` | 生成协议 interface 和 UVC 目录 | 接口规格已评审 | `$verif-harness add-interface` |
| `add-shared-pkg` | 生成共享 typedef/enum 和打包 package | 多个 UVC 需要公共类型 | `$verif-harness add-shared-pkg` |
| `add-uvc-skeleton [name]` | 生成 driver/monitor/sequencer/agent 骨架 | 建立一个新 UVC | `$verif-harness add-uvc-skeleton input` |
| `add-harness-layer` | 生成 DUT/TB harness 和 SVA stub | 连接 DUT、interface 和 checker | `$verif-harness add-harness-layer` |
| `add-env-layer` | 生成 env、scoreboard/coverage shell、base test 和 `tb_top` | 建立最小 UVM 顶层 | `$verif-harness add-env-layer` |
| `finalize-filelist-and-make` | 生成规范 filelist 和 compile-only target | 闭合首次编译 | `$verif-harness finalize-filelist-and-make` |
| `doctor` | 只读检查配置、阶段、文档和 RTL dirtiness | 接手、恢复或诊断项目 | `$verif-harness doctor` |
| `add-regression-runner` | 添加隔离回归、seed、结果收集和失败重跑 | 从单测扩展到批量回归 | `$verif-harness add-regression-runner` |
| `add-simulator-profile` | 生成 simulator command/capability profile | 增加一个评审后的 simulator 配置 | `$verif-harness add-simulator-profile` |
| `add-testcase` | 生成 test/vseq 并加入 candidate list | 实现一个计划内场景 | `$verif-harness add-testcase` |
| `add-coverage-skeleton` | 从显式合约生成 covergroup/bin/cross | coverage plan 已明确 | `$verif-harness add-coverage-skeleton` |
| `add-assertion-skeleton` | 从显式 property 生成 checker/bind | assertion plan 已明确 | `$verif-harness add-assertion-skeleton` |
| `add-refmodel-bridge` | 生成 Syscan 或 DPI-C 结构适配层 | 接入 Golden/reference model | `$verif-harness add-refmodel-bridge` |
| `complete-uvc` | 生成 ready/valid source driver 和 monitor 行为 | UVC 骨架需要具体握手实现 | `$verif-harness complete-uvc` |
| `complete-scoreboard` | 生成 FIFO 对齐和 exact/masked/tolerance compare | compare policy 已评审 | `$verif-harness complete-scoreboard` |
| `add-ci-hook` | 生成 GitLab CI 或 Jenkins fragment | 本地回归稳定后接 CI | `$verif-harness add-ci-hook` |
| `add-performance-gate` | 按固定合约检查性能记录 | 检查 bubble、cadence、utilization 和 timing | `$verif-harness add-performance-gate` |
| `regression-triage` | 聚类失败并验证同 seed 重跑 | regression 非全绿 | `$verif-harness regression-triage` |
| `coverage-closure` | 审计 coverage hit、exclusion、waiver 和 totals | coverage freeze review 前 | `$verif-harness coverage-closure` |
| `assertion-closure` | 审计 compile/bind/attempt/failure/vacuity | assertion freeze review 前 | `$verif-harness assertion-closure` |
| `audit-traceability` | 审计 feature、test、manifest、coverage/assertion ID | stage gate 前检查追踪闭环 | `$verif-harness audit-traceability` |
| `change-control` | 审计 baseline 后 CR、影响和 Git diff | frozen baseline 后发生变更 | `$verif-harness change-control` |
| `stage-gate-review <stage>` | 生成 Draft stage-gate packet | Stage N 完成后交 Human review | `$verif-harness stage-gate-review 4` |
| `signoff-audit <stage>` | 审计 sign-off packet 和已记录审批 | 最终签核复核 | `$verif-harness signoff-audit 5` |
| `freeze-baseline` | 生成 clean-commit SHA-256 freeze manifest | 最终 Human freeze review 前 | `$verif-harness freeze-baseline` |
| `oss-readiness` | 审计公开仓库文件、CI、路径和敏感信息 | 准备脱敏后的公开 export | `$verif-harness oss-readiness` |
| `patterns [topic]` | 查询实现和生命周期模式 | 只需要指导、不修改项目 | `$verif-harness patterns regression` |

<!-- markdownlint-enable MD013 -->

## 推荐入口

- 完整 0→freeze 操作顺序：[docs/user_guide.md](docs/user_guide.md)
- 模式分层和证据流：[docs/architecture.md](docs/architecture.md)
- 常见失败与恢复方法：[docs/troubleshooting.md](docs/troubleshooting.md)
- Codex 执行规则：[SKILL.md](SKILL.md)

## 权限边界

- 不修改 DUT RTL。
- 不推断未评审的协议、数值、mask、alignment 或 coverage 语义。
- 不自动批准 Human Decision、waiver、change request、stage gate 或 freeze。
- 不把生成成功、零 failure、结构审计通过或哈希生成解释成功能正确。
- 不把 `READY_FOR_HUMAN_*_REVIEW` 解释成 `Approved`。
- 不自动 tag、push、发布或公开任何项目资产。
