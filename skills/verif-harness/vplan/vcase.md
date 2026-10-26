# VCASE：测试用例代码方案与交付验收

VCASE 把已确认的验证点和场景组织成可重复运行的 testcase 工作包。按可独立注册、
执行、定位和失效的用例集合建立稳定 `implementation_key`；每包只有 `code-plan`
和 `code-deliverable` 两种公开节点。

方案使用 `plan VCASE --desired-file proposal.json`，至少依赖已验收的 `cap.doc`、
`cap.venv`、`cap.vstim` 和 `cap.vchk`。同工作流包之间使用
`cap.vcase:<implementation_key>`，需要时可显式依赖 `cap.vreg:executor-ready`。
VCASE 自身交付不依赖 VCOV：用例先实现并定向运行，之后 VCOV 再消费这些结果判断
覆盖率收敛。

每个包必须同时交付 `case-implementation` 和 `targeted-evidence`。实现证据通过
`CaseManifest/2` 证明 testcase 或可执行 virtual sequence 已注册、可构建，并绑定
testbench submit file 中当前 submit profile 的 ID 与摘要；verif-harness 不复制或执行
submit 配置。定向证据证明批准范围内的新增用例在当前工程 revision
实际执行，结果通过、无超时且检查机制确实参与。只有测试名或 PASS 文本、没有原始
仿真与分析材料，不能形成可验收交付。

Main Agent 使用 `TestcaseEvidence/2` 和 `code validate` 核对全部交付条件后再请负责
人验收；验收后派生 `art.code`、包级 `cap.vcase` 和 claim 汇总 CAP，供 VCOV/VREG
等下游使用。

新增覆盖率补洞用例包时，保留未变化用例包的原方案、交付节点、节点版本和验收记录。
工作流范围可以形成新 revision，但不能因此重建全部已有用例节点。原验收仍须匹配当前
代码、证据和实际依赖版本；发生实质变化的工作包重新验证和验收，显式重启不保留旧批准。

## 每个 case 的来源与预期依据

`CaseManifest/2.traceability` 复用用例清单，逐 case 绑定验证点、本清单的文件版本和位置、
规格、RTL、未覆盖项、缺陷、参考模型或工程决定等来源。每项来源包含编号、类型、受控文件、
SHA-256、版本标识和具体位置。预期结果单独记录描述、检查方法、依据来源编号及确认状态。
未覆盖项等规划反馈引用受控归档快照；更新当前覆盖报告不得覆盖历史来源文件。

`specified` 要求预期依据含规格或参考模型；仅从 RTL 推导的预期必须标为
`rtl-derived-unconfirmed`，验证会保存具体阻塞并禁止交付验收，不能仅改状态字段绕过。
需要负责人确认时，Main Agent 在本方案或对应交付节点使用已有 `agent-question`：
问题正文用中文说明 case、推导来源和建议预期；`context` 保存 `CaseBehaviorConfirmation/1`，
其 `case_id` 和 `behavior_digest` 由 `case_traceability.confirmation_context` 生成。
选项 `confirm` 表示确认这一工程行为，另一选项要求澄清或修改；这不是方案或交付批准。
回答后将预期状态改为 `confirmed` 并引用 `confirmation_question_id`。控制面核对本节点的问题、
负责人实际回答和预期依据来源及行为摘要；回答否定、未回答、引用其他节点或行为版本变化均不得通过。
负责人仍在原交付节点验收代码与证据，不新增节点或审批入口。

旧 CaseManifest/1 和 TestcaseExecution/2 验证回执保留历史，不能代替当前追溯要求；
必须按真实来源补齐清单和 CaseManifest/2 并重新验证，不自动猜测规格依据或确认结论。
