# VCOV：覆盖率实现、采集与未覆盖项收敛

VCOV 直接使用四种公开工作节点类型。根据 DUT 的接口、功能和覆盖范围可以建立多个同类型
节点；界面不增加“工作包”层级。

| 工作节点类型 | 内部角色 | 输入依据 | 完成内容 |
| --- | --- | --- | --- |
| 覆盖率实现方案 | `coverage-implementation-plan` | 已验收文档 `cap.doc`、环境 `cap.venv`、回归执行器 `cap.vreg` | 明确覆盖目标、模型、采样和采集方式、验证方法，等待负责人批准 |
| 覆盖率实现交付 | `coverage-implementation-deliverable` | 对应已批准方案 `art.code_plan` | 实现并验证覆盖模型和采集链路，等待负责人验收 |
| 覆盖率收敛方案 | `coverage-convergence-plan` | 当前有效的覆盖实现能力，以及 `cap.doc`、`cap.venv`、`cap.vstim`、`cap.vchk`、`cap.vcase` 和 `cap.vreg` | 明确本轮采集范围、覆盖目标、合并和未覆盖项的处理方法，等待负责人批准 |
| 覆盖率收敛交付 | `coverage-convergence-deliverable` | 对应已批准方案 `art.code_plan` 和当前运行结果 | 交付覆盖数据库、采集报告、完整的未覆盖项分析及处理结果，等待负责人验收 |

```text
覆盖率实现方案 → 负责人批准 → 覆盖率实现交付
    → Agent 验证通过 → 负责人验收 → 覆盖实现能力有效
    → 覆盖率收敛方案 → 负责人批准 → 覆盖率收敛交付
    → 完整覆盖范围已检查、未覆盖项已处理 → 负责人验收 → 覆盖收敛能力有效
```

实现交付必须同时验证 `coverage-model` 和 `coverage-collection`：完成 covergroup、
coverpoint、bin、cross、采样时机、收集和导出链路。它不以达到覆盖率目标作为实现完成
条件。验收后形成 `art.code`，Engine 派生有效的 `cap.vcov:coverage-model` 和
`cap.vcov:coverage-collection` 汇总能力。收敛方案必须明确关联对应实现的
`cap.vcov:<implementation_key>`，不能只引用汇总能力代替具体实现范围。产物和能力不增加公开
工作节点、人工审批入口或进度。

增加、删除或修改收敛方案时，内容未变化的覆盖率实现方案及实现交付保留原节点 ID、
节点版本、批准和验证记录。工作流范围版本可以更新，已有覆盖实现能力不随之重新生成。
原批准仍须匹配当前输入、实际依赖版本、代码和证据；真实变化继续触发对应的审批或验证。
收敛节点与排除文件、执行轮次和数据库证据仍按当前范围核对；工作流目标、决策变化或
负责人显式重启时，原节点不保留。

实现方案用 `CoverageScope/1` 登记负责人需要批准的稳定范围。code coverage 记录 metric、
层次选择或 `cm.hier` 类配置，以及范围内使用的排除配置；functional coverage 记录 covergroup
选择规则和必需对象类型。语义覆盖目标 ID 可以作为少量、稳定的追溯标识，但不得把 simulator
中的每个 line、toggle、bin 或 cross 都登记成方案 item、公开节点或 ProjectStore 记录。
收敛方案通过 `cap.vcov:<implementation_key>` 明确关联一个或多个实现范围，不另行缩小范围。
两类方案都必须依赖具体的 `cap.vreg:executor-ready`，不能用最终回归结果代替执行能力。

收敛交付必须同时验证 `coverage-collection-evidence` 和 `hole-analysis-evidence`。
采集证据绑定当前版本、数据库分片和合并结果；数据库不得有合并错误或过期分片。未覆盖项分析
给出必需、已命中、已排除和未覆盖对象的完整计数，只逐项列出 excluded（已批准排除）和
uncovered（未覆盖）对象；已命中对象保留在工具生成的全集与数据库中，不复制进控制状态。excluded
由负责人提供当前 exclude 文件；提供动作本身表示负责人已经批准文件中的排除范围，不再逐项
建立 WAIVE 审批。ProjectStore 保存文件路径、SHA-256、负责人、说明、VCOV revision 和收敛节点
范围。Agent 只验证文件合法性，并要求 `hole-analysis-evidence` 把该文件作为 xverif 分析过的
`configuration` 原始产物引用；每个 excluded 项都必须引用同一个文件级审批记录，不能仅凭报告
自写 Approved 字样。文件缺失、内容或范围变化、报告引用不一致都会阻止验收。uncovered 必须
明确责任工作流和下一步动作，并阻止收敛验收。最后仍由负责人验收完整收敛结果。

负责人可以在 Dashboard 的覆盖率收敛交付节点提供文件，或使用：

```text
verif-harness code provide-exclusions NODE path/to/exclusions.el \
  --reviewer NAME --reason "已核对不可达范围" --confirm
```

Agent 随后重新生成未覆盖项分析报告并执行 `code validate NODE report.json`。这一步只检查合法性和一致性，
不会再次批准排除范围，也不会代替最终交付验收。

实现方案同时登记 `CoverageImplementationConfig/1`，固定覆盖率插桩、elaboration、采集、
导出和分析配置、工具版本以及兼容 submit profile 摘要。code coverage 的目标必须是 DUT，
不得把 testbench 代码计入 code coverage。实现与收敛共用工具生成的受控对象清单
`CoverageObjectInventory/2`。xverif 按批准的 `CoverageScope/1`、当前实现配置、覆盖计划和
覆盖模型展开必需原生对象全集；清单记录 `scope_digest`、`implementation_config_digest`、
`plan_digest`、`model_digest`，以及每个对象的工具身份、类别、类型和原生路径。对象身份只存在于
受控清单和未覆盖项分析报告，不成为人工审批 item。计划摘要必须对应方案 `input_files` 的当前文件，模型
及采集配置摘要必须对应当前交付文件。模型证据、采集证据和未覆盖项分析通过
`coverage_inventory_digest` 绑定同一份当前清单。

收敛方案登记 `CoverageCollectionConfig/1`，其中只读引用一个或多个当前 VREG
`regression_config` 的节点、版本和摘要，并固定 merge profile。它不得复制 case、submit
profile、seed 模式和值或 repeat。负责人审批收敛方案时，只要求这些 VREG 结果方案及其
`regression_config` 已批准；VDB 尚未产生不阻止方案审批。收敛交付验证时才要求每条引用都
具有已经结束的当前执行轮次。VREG 执行产生一个或多个 VDB；每份
`CoverageDatabaseShardManifest/1` 必须把分片完整绑定到当前执行轮次、
`RegressionBatchManifest/2` 及其 case/seed/iteration，不能漏跑、重复或混入其他轮次。
`CoverageMergeManifest/1` 必须精确列出全部输入 VDB 摘要、当前 merge profile 和唯一输出
数据库摘要；采集与未覆盖项分析必须引用该同一合并输出。每份 shard manifest 还必须携带
`DutBuildFingerprint/1`：只由 DUT 标识、RTL 摘要、parameter 摘要、宏摘要和 DUT 级
elaboration 摘要构成。上述任一项不同都禁止 merge。testbench 身份、submit profile 和 DUT
实例路径不进入该指纹，所以不同 testbench/profile 的 VDB 在 DUT 指纹相同时允许合并；每个
来源仍是独立 VREG source/batch，功能覆盖对象不一致或原生 merge 工具报错仍会阻止验收。
`dut_elaboration_digest` 必须从去除 testbench 层次、wrapper 和绝对实例路径后的 DUT elaborated
design 计算，不能直接对整个仿真顶层 elaboration 取摘要。
`CoverageCollectionConfig/1` 将该预期 `DutBuildFingerprint/1` 一并纳入方案审批。每个收敛方案
及批准后建立的唯一交付只管理一个指纹分区；若预期或实际存在多个指纹，proposal 必须按指纹
拆成多个 `coverage-convergence-plan`，随后分别产生多个 `coverage-convergence-deliverable`。
VDB、batch、case、seed 和 iteration 仍只是各交付内部的受控清单，不增加公开节点或逐项审批。
`scope_digest` 使用规范化 `CoverageScope/1`（字符串数组排序、JSON key 排序、UTF-8、无额外空白）
计算 SHA-256，工具不得对同一范围使用自定义摘要算法。
未覆盖项分析报告的 `required_objects` 必须等于 `covered_objects + excluded_objects + uncovered_objects`，
且 `holes` 必须完整列出 excluded/uncovered 对象并属于清单全集。作为 `analysis-report` 的清单还须
保留标准 adapter 回执信息，不能只自行标记工具名称。范围、清单、计划、模型或数据库版本变化后，
旧证据必须重新验证。

VCOV 完成要求当前必需的实现和收敛两部分都已登记并验收通过。只验收实现交付不能完成
VCOV；缺少收敛方案时由 Main Agent 补齐当前 DUT 的方案，收敛交付仅在对应方案批准后建立。
每项批准和验证证据都绑定当前版本；历史批准和证据不自动继承。
旧 `CoverageEvidence/1`、`CoverageEvidence/2`、`CoverageObjectInventory/1` 与
`CoverageItemManifest/1` 继续可读，但只保留历史；未按当前 `CoverageEvidence/3` /
`CoverageConvergence/5` 合同重新验证时，不恢复下游可用状态。

coverage hole 不会自动把上游改成失败或直接创建代码。Main Agent 先核对根因，再向
VENV、VSTIM、VCHK、VCASE、VCOV 或 VREG 登记下一版变更/重验证要求；如果根因指向
DUT，只登记设计问题并等待负责人决定。上游产物摘要实际变化后，Engine 再沿依赖图使
受影响的下游证据进入 `REVALIDATION_REQUIRED`。

旧 VCOV 的 `code-plan` / `code-deliverable` 记录继续可读，界面按其能力要求显示对应的
实现或收敛类型；历史节点、审批和证据不被改写。新方案使用上述四种明确角色，稳定的
`implementation_key` 仅用于内部关联同一范围的方案、交付、产物与能力。
