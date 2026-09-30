# VCASE：测试用例代码方案与交付验收

VCASE 把已确认的验证点和场景组织成可重复运行的 testcase 工作包。按可独立注册、
执行、定位和失效的用例集合建立稳定 `implementation_key`；每包只有 `code-plan`
和 `code-deliverable` 两种公开节点。

方案使用 `plan VCASE --desired-file proposal.json`，至少依赖已验收的 `cap.doc`、
`cap.venv`、`cap.vstim` 和 `cap.vchk`。同工作流包之间使用
`cap.vcase:<implementation_key>`，需要时可显式依赖 `cap.vreg:executor-ready`。
VCASE 自身交付不依赖 VCOV：用例先实现并定向运行，之后 VCOV 再消费这些结果判断
覆盖闭环。

每个包必须同时交付 `case-implementation` 和 `targeted-evidence`。实现证据证明用例
已注册、可构建并绑定当前代码；定向证据证明批准范围内的新增用例在当前工程 revision
实际执行，结果通过、无超时且检查机制确实参与。只有测试名或 PASS 文本、没有原始
仿真与分析材料，不能形成可验收交付。

Main Agent 使用 `TestcaseEvidence/1` 和 `code validate` 核对全部交付条件后再请负责
人验收；验收后派生 `art.code`、包级 `cap.vcase` 和 claim 汇总 CAP，供 VCOV/VREG
等下游使用。

