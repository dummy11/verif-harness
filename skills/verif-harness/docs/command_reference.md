# verif-harness Agent/CI 命令索引

本页是底层 CLI 的导航，不是要求负责人手工执行的操作清单。负责人通常通过 Main Agent 和
Dashboard 完成输入、审批、验收与问题回答；Main Agent 根据当前 revision、节点摘要和权限边界调用
CLI。

精确参数以当前 checkout 为准：

```text
verif-harness --help
verif-harness COMMAND --help
```

setup 创建的 launcher 通常位于：

```text
.agents/skills/verif-harness/scripts/verif-harness      # Codex workspace
.kimi-code/skills/verif-harness/scripts/verif-harness  # Kimi workspace
```

在 verif-harness 源码仓开发时使用：

```text
scripts/managed-python scripts/verif_harness.py COMMAND
```

## 安装与项目登记

| 入口 | 主要调用者 | 用途与边界 |
| --- | --- | --- |
| `./scripts/setup` | 负责人/安装者 | 安装依赖、配置 runtime、进入项目；不登记 DUT |
| `bootstrap` | Main Agent | 登记明确提供的 DUT 和只读输入；不生成验证结论 |
| `runtime status` | Main Agent/诊断 | 查看项目选择的 runtime 和本机探测结果 |
| `doctor` | Main Agent/CI | 只读审计当前项目，不自动修复 |

Main Agent 实时 bootstrap 时显式使用 `--dashboard`。`--no-dashboard` 只有负责人明确要求关闭时使用。
`bootstrap --refresh` 必须逐项向负责人显示当前输入并重新确认，不能静默沿用、删除或猜测路径。

## 状态、依赖和下一步

| 命令 | 用途 |
| --- | --- |
| `status [WORKSTREAM]` | 查看项目或单条工作流的当前权威状态投影 |
| `closure` | 查看当前缺口、依赖、负责人待办和允许的下一项动作 |
| `inspect [NODE]` | 查看节点或项目知识详情 |
| `trace NODE` | 查看节点的依赖、finding 和 evidence |
| `impact NODE` | 查看节点变化会影响的下游范围 |
| `check` | 显式执行确定性一致性检查；写操作后也会自动运行 |

这些命令不会启动隐藏 worker。`executor` 和 `suggested_mode` 是下一步建议，不是已执行事实。

## Dashboard 与 Agent 服务

```text
verif-harness dashboard
verif-harness dashboard --status
verif-harness dashboard --open-browser
verif-harness dashboard --ensure-ready
verif-harness dashboard --stop

verif-harness agent-service status
verif-harness agent-service start --runtime codex|kimi
verif-harness agent-service stop
verif-harness agent-service retry
```

`dashboard --stop` 注销当前项目，最后一个项目注销后才停止账号级共享服务；不删除项目数据。
`agent-service` 是单写者接续服务，不代替负责人审批、回答问题、接受例外或运行 EDA。

## 工作流方案与启动策略

| 命令组 | 用途与边界 |
| --- | --- |
| `plan` | 形成或修订当前工作流 proposal；不能自行批准 |
| `workflow-launch` | 在当前 `cap.doc` 形成后查看/选择其他工作流的方案形成方式 |
| `human-action` | 记录负责人提出的下一版添加、删除、修改或重启要求 |

方案形成、节点审批和交付验收是不同动作。CLI 不得把自然语言默认值、旧 revision 审批或 Activity
完成当作当前批准。

## 文档与代码交付

| 命令组 | 用途与边界 |
| --- | --- |
| `docs` | 查看文档状态、同步 Markdown 摘要、读取 manifest/artifact；方案批准前不得同步正式正文 |
| `code` | 查看代码/覆盖率/回归方案，登记 Main Agent validation，查询验收产物 |
| `agent-review-feedback` | 领取并完成负责人提交的方案或正文意见批次 |
| `agent-review-check` | 检查负责人正文验收，并决定是否需要继续提问 |

VDOC 正文验收提交后，Main Agent 必须检查当前正文和依赖。VENV/VSTIM/VCHK/VCASE/VCOV/VREG
则要求 Agent validation 先通过，再由负责人执行最后验收。

## 证据、变化与例外

| 命令组 | 用途与边界 |
| --- | --- |
| `evidence` | 按节点所属工作流校验 typed report 并推导 verdict |
| `reachability` | 校验 VSTIM 可达性/确定性专用报告 |
| `prove` | 仅用于没有专用合同的自定义节点，不能绕过标准 evidence |
| `changed` | 登记文件已经变化并传播重新验证要求；不授权修改只读输入 |
| `waive` | 记录负责人接受例外的明确结论；Agent 不得自行调用形成决定 |
| `record` | 结构化事实入口；只能按已定义合同使用，不能直接伪造 `VALID/WAIVED` |

原始日志、波形、VDB/UCDB、manifest 和工具退出码是分析输入，不会自动成为当前节点的通过证据。

## Activity、subagent 和负责人问题

| 命令组 | 用途与边界 |
| --- | --- |
| `activity` | 登记 Main Agent 或工具当前有边界的工作；不改变节点有效性 |
| `agent-work` | Main Agent claim、heartbeat、完成 runtime-native subagent assignment |
| `agent-question` | 登记、等待和回答绑定当前节点/revision 的负责人问题 |
| `await-human` | 等待当前节点审批、交付验收或已提交给 Agent 的意见批次 |

`await-human WORKSTREAM --node NODE_ID ...` 可以只等待当前工作流、当前版本内指定的公开方案或交付
节点。当前节点方案批准或交付验收返回决定后，下一步仍是重新读取 Closure；它不表示整条工作流已经
完成。VDOC 正文验收会进入 Main Agent 检查；提交意见批次会进入反馈处理。超时不取消待办，已经退出
的 Agent 也不会因为 Dashboard 保存了决定而自动恢复执行。

subagent 只能领取 Main Agent 明确划定、写入范围不重叠并绑定当前 revision 的工作。assignment
完成、租约过期或 runtime 返回成功，都不能自动产生 evidence、批准或节点完成。

## 工具适配器

| 命令组 | 用途与边界 |
| --- | --- |
| `xverif` | 调用允许列表内的 deterministic xverif adapter |
| `wavepeek` | 执行有边界的 WavePeek 波形查询 |
| `reason` | 建立 Role × Backend 的推理请求边界 |

适配器 PASS 只证明工具请求成功执行，不证明 RTL 功能正确、节点关闭、仿真器受支持或验证签核。

## 查看局部帮助

命令会继续演进，因此不要从旧文档复制参数。使用两级帮助确认当前参数和子命令：

```text
verif-harness code --help
verif-harness docs --help
verif-harness agent-question --help
verif-harness await-human --help
verif-harness xverif --help
verif-harness wavepeek --help
```
