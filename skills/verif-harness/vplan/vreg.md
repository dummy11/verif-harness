# VREG：回归执行基础设施与结果闭环

VREG 使用两类工作包，以避免“运行器尚未建立就等待整轮回归完成”的循环依赖。每包使用
稳定 `implementation_key`，公开节点仍只有 `code-plan` 和 `code-deliverable`；负责人
分别审批方案并验收当前版本的实现与证据。

回归基础设施包必须同时交付 `regression-policy` 和 `executor-ready`。它只依赖已验收的
`cap.doc` 和可运行的 `cap.venv`，定义测试集合、seed、timeout、重跑和已知失败规则，
并证明 runner/collector 自检通过。验收后形成 `cap.vreg:executor-ready`，供 VSTIM、
VCASE 和 VCOV 的实际运行使用。

回归闭环包必须同时交付 `execution-evidence`、`triage-evidence` 和 `fresh-evidence`。
它依赖同工作流已验收的基础设施包，以及当前有效的 `cap.venv`、`cap.vstim`、
`cap.vchk`、`cap.vcase` 和 `cap.vcov`。执行证据绑定 manifest、seed、日志和代码版本；
失败分类使用同 seed 重跑；新鲜度证据证明必需验证项都关联当前版本结果。

尚未关闭的失败必须写明责任工作流和下一步动作。Main Agent 依据分类向相应上游登记
重规划或重验证要求；不会因 regression FAIL 自动批准修改、自动关闭节点或修改 DUT。
修复或证据更新后，版本摘要和依赖图负责使受影响节点重新验证，最终由新的 VREG 结果
确认问题是否真正关闭。
