# VREG：回归基础设施与结果验收

VREG 直接使用四种公开工作节点类型。根据 DUT 的测试范围、执行配置和结果验收边界，
可以建立多个同类型节点；方案与对应交付通过内部标识关联。

| 工作节点类型 | 内部角色 | 输入依据 | 完成内容 |
| --- | --- | --- | --- |
| 回归基础设施方案 | `regression-infrastructure-plan` | 已验收文档 `cap.doc` 和可运行的环境 `cap.venv` | 明确测试集合、seed、timeout、重跑、已知失败和结果保留规则，等待负责人批准 |
| 回归基础设施交付 | `regression-infrastructure-deliverable` | 对应已批准方案 `art.code_plan` | 实现并自检 runner/collector，等待负责人验收 |
| 回归结果方案 | `regression-results-plan` | 当前有效的 `cap.doc`、`cap.venv`、`cap.vstim`、`cap.vchk`、`cap.vcase`、`cap.vcov`，以及明确关联的基础设施能力 | 明确本轮执行范围、结果准入、失败分析和版本检查方法，等待负责人批准 |
| 回归结果交付 | `regression-results-deliverable` | 对应已批准方案 `art.code_plan` 和当前运行结果 | 交付回归测试清单、执行报告、失败处理记录与当前版本验证证据，等待负责人验收 |

```text
回归基础设施方案 → 负责人批准 → 回归基础设施交付
    → Agent 自检通过 → 负责人验收 → 回归执行能力有效
    → 回归结果方案 → 负责人批准 → 回归结果交付
    → 执行、失败分类及版本检查通过 → 负责人验收 → 当前回归结果可用
```

基础设施交付必须同时验证 `regression-policy` 和 `executor-ready`。基础设施不等待本轮
最终回归结果；验收后形成 `art.code`，Engine 派生具体的 `cap.vreg:<implementation_key>`
以及 `cap.vreg:executor-ready` 汇总能力。后续回归结果方案必须通过具体能力关联当前方案中
已验收的基础设施范围，不能只依赖执行器汇总状态。产物和能力是内部派生状态，不增加公开
工作节点、人工审批入口或进度。

结果交付必须同时验证 `execution-evidence`、`triage-evidence` 和 `fresh-evidence`。
执行证据绑定测试清单、seed、日志和代码版本；失败分类使用同 seed 重跑，失败原因及处理
结论必须可追溯。执行失败的 test/seed 与分类记录必须精确一致，不得遗漏、增加或重复；
接受已知失败时，必须引用同项目、当前 VREG revision 的负责人例外批准。
当前版本验证证据的 `snapshot_revision` 必须等于报告 revision。Engine 派生当前全部
必需上游交付及证据摘要，不信任报告自行填写的清单；读取和验收时重新核对，范围或证据
变化即撤销旧结果。结果交付自身及其他结果交付的验收不作为 fresh 检查前置，避免互相等待；
它们仍由 VREG 整体完成条件逐一检查。基础设施验收只说明
回归执行器可用；当前必需的基础设施与结果两部分都完成验收后，VREG 才满足完成条件。
每项批准和证据均绑定当前 revision 和内容摘要，新版本不继承旧批准或旧证据。

尚未关闭的失败必须写明责任工作流和下一步动作。Main Agent 只依据当前有效的分类证据向相应上游登记
重规划或重验证要求；不会因 regression FAIL 自动批准修改、自动关闭节点或修改 DUT。
修复或证据更新后，版本摘要和依赖图负责使受影响节点重新验证，最终由新的 VREG 结果
确认问题是否真正关闭。

旧 VREG 的 `code-plan` / `code-deliverable` 记录继续可读，界面根据其完整能力要求显示为
基础设施或结果类型；历史节点、审批和证据不被改写。旧结果验证记录缺少当前
`RegressionResults/2` 合同时必须重新验证，不可继续作为当前验收依据。
新方案使用上述四种明确角色，稳定的
`implementation_key` 仅用于内部关联同一范围的方案、交付、产物与能力。
