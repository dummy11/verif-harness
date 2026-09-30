# VCHK：检查代码方案与交付验收

VCHK 按参考模型、scoreboard 或 assertion group 的实际职责划分工作包。不同负责人、
写入范围或独立失效边界应拆包；否则不要把一个检查器机械拆成多个公开节点。每包
只有 `code-plan` 和 `code-deliverable` 两种公开节点。

方案使用 `plan VCHK --desired-file proposal.json`，至少依赖已验收的 `cap.doc`、
`cap.venv` 和 `cap.vstim`。同工作流包之间使用 `cap.vchk:<implementation_key>`；
不得依赖 VCOV 或直接依赖方案、交付工作节点。

实现 claim 与运行 claim 必须成对出现：

| 实现 | 当前版本运行证据 |
| --- | --- |
| `reference-model` | `reference-model-evidence` |
| `scoreboard` | `scoreboard-evidence` |
| `assertions` | `assertion-evidence` |

编译或 bind 成功只证明实现已接入，不能证明检查机制在运行时有效。运行证据必须有
非零的比较或触发次数，没有未解释 mismatch、残留队列、失败或 vacuity，并绑定当前
实现摘要和工程 revision。Main Agent 使用 `CheckingEvidence/1` 和 `code validate`
核对全部交付条件后再请负责人验收；验收后派生 `cap.vchk`。

