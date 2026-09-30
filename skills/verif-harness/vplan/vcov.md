# VCOV：覆盖率实现、采集与缺口收敛

VCOV 分成两类有明确边界的工作包，避免把覆盖率代码和一次测量结论混成同一个完成状态。
每包使用稳定 `implementation_key`，公开节点仍只有 `code-plan` 和
`code-deliverable`；界面面向负责人显示为覆盖率方案与交付验收。

覆盖率缺口处理统一称为“收敛”，流程中的方案和交付分别称为“覆盖率收敛方案”和
“覆盖率收敛交付”。

覆盖率实现包必须同时交付 `coverage-model` 和 `coverage-collection`。它依据已验收的
`cap.doc`、验证环境 `cap.venv` 和已经自检的回归执行器 `cap.vreg`，完成 covergroup、
coverpoint、bin、cross、采样时机、收集和导出链路。它不以达到覆盖率目标作为代码实现
完成条件。

覆盖率收敛包必须同时交付 `coverage-collection-evidence` 和
`hole-analysis-evidence`。它依赖同工作流已验收的覆盖率实现包，以及当前有效的
`cap.vstim`、`cap.vchk`、`cap.vcase`、`cap.venv` 和 `cap.vreg`。采集证据要绑定当前
代码版本、数据库分片和合并结果；缺口分析要逐项给出 covered、excluded 或 uncovered。
excluded 必须引用负责人批准的例外；uncovered 必须明确责任工作流和下一步动作。

coverage hole 不会自动把上游改成失败或直接创建代码。Main Agent 先核对根因，再向
VENV、VSTIM、VCHK、VCASE、VCOV 或 VREG 登记下一版变更/重验证要求；如果根因指向
DUT，只登记设计问题并等待负责人决定。上游产物摘要实际变化后，Engine 再沿依赖图使
受影响的下游证据进入 `REVALIDATION_REQUIRED`。
