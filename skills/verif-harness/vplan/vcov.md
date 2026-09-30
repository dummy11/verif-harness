# VCOV：覆盖率实现、采集与缺口收敛

VCOV 直接使用四种公开工作节点类型。根据 DUT 的接口、功能和覆盖范围可以建立多个同类型
节点；界面不增加“工作包”层级。

| 工作节点类型 | 内部角色 | 输入依据 | 完成内容 |
| --- | --- | --- | --- |
| 覆盖率实现方案 | `coverage-implementation-plan` | 已验收文档 `cap.doc`、环境 `cap.venv`、回归执行器 `cap.vreg` | 明确覆盖目标、模型、采样和采集方式、验证方法，等待负责人批准 |
| 覆盖率实现交付 | `coverage-implementation-deliverable` | 对应已批准方案 `art.code_plan` | 实现并验证覆盖模型和采集链路，等待负责人验收 |
| 覆盖率收敛方案 | `coverage-convergence-plan` | 当前有效的覆盖实现能力，以及 `cap.doc`、`cap.venv`、`cap.vstim`、`cap.vchk`、`cap.vcase` 和 `cap.vreg` | 明确本轮采集范围、覆盖目标、合并和缺口处理方法，等待负责人批准 |
| 覆盖率收敛交付 | `coverage-convergence-deliverable` | 对应已批准方案 `art.code_plan` 和当前运行结果 | 交付覆盖数据库、采集报告、完整缺口分析及补洞结果，等待负责人验收 |

```text
覆盖率实现方案 → 负责人批准 → 覆盖率实现交付
    → Agent 验证通过 → 负责人验收 → 覆盖实现能力有效
    → 覆盖率收敛方案 → 负责人批准 → 覆盖率收敛交付
    → 完整覆盖范围已检查、缺口已处理 → 负责人验收 → 覆盖收敛能力有效
```

实现交付必须同时验证 `coverage-model` 和 `coverage-collection`：完成 covergroup、
coverpoint、bin、cross、采样时机、收集和导出链路。它不以达到覆盖率目标作为实现完成
条件。验收后形成 `art.code`，Engine 派生有效的 `cap.vcov:coverage-model` 和
`cap.vcov:coverage-collection` 汇总能力。收敛方案必须明确关联对应实现的
`cap.vcov:<implementation_key>`，不能只引用汇总能力代替具体实现范围。产物和能力不增加公开
工作节点、人工审批入口或进度。

实现方案在 `coverage_item_ids` 中列出本节点的必需覆盖项，连同范围一起由负责人批准；
收敛方案通过 `cap.vcov:<implementation_key>` 明确关联一个或多个实现范围，不另行缩小清单。
两类方案都必须依赖具体的 `cap.vreg:executor-ready`，不能用最终回归结果代替执行能力。

收敛交付必须同时验证 `coverage-collection-evidence` 和 `hole-analysis-evidence`。
采集证据绑定当前版本、数据库分片和合并结果；数据库不得有合并错误或过期分片。缺口分析
逐项给出 covered（已命中）、excluded（已批准排除）或 uncovered（未覆盖）。excluded
必须引用当前版本中可核对的负责人例外批准记录，不能仅凭报告自写的 Approved 字样；
未有该记录时仍阻止验收。uncovered 必须明确责任工作流和下一步动作，并阻止收敛验收。

实现与收敛共用受控覆盖项清单 `CoverageItemManifest/1`。清单记录覆盖计划摘要
`plan_digest`、覆盖模型摘要 `model_digest`、计划必需覆盖项全集 `planned_item_ids` 和模型
实现项 `mapped_item_ids`；两份名单都必须精确匹配已批准的 `coverage_item_ids`。
计划摘要必须对应方案 `input_files` 的当前文件，模型及采集配置摘要必须对应当前交付文件。
模型证据、采集证据和缺口分析
通过 `coverage_manifest_digest` 绑定同一份当前清单，清单文件必须作为 xverif 分析的受控
产物登记。缺口分析项必须逐一对应清单全集，遗漏、重复或额外项均不能满足收敛条件。
作为 `analysis-report` 的清单还须保留标准 adapter 回执信息，不能只自行标记工具名称。
清单、计划或模型版本变化后，旧证据必须重新验证。

VCOV 完成要求当前必需的实现和收敛两部分都已登记并验收通过。只验收实现交付不能完成
VCOV；缺少收敛方案时由 Main Agent 补齐当前 DUT 的方案，收敛交付仅在对应方案批准后建立。
每项批准和验证证据都绑定当前版本；历史批准和证据不自动继承。
旧验证回执未包含当前收敛合同信息时，只保留历史，不恢复下游可用状态。

coverage hole 不会自动把上游改成失败或直接创建代码。Main Agent 先核对根因，再向
VENV、VSTIM、VCHK、VCASE、VCOV 或 VREG 登记下一版变更/重验证要求；如果根因指向
DUT，只登记设计问题并等待负责人决定。上游产物摘要实际变化后，Engine 再沿依赖图使
受影响的下游证据进入 `REVALIDATION_REQUIRED`。

旧 VCOV 的 `code-plan` / `code-deliverable` 记录继续可读，界面按其能力要求显示对应的
实现或收敛类型；历史节点、审批和证据不被改写。新方案使用上述四种明确角色，稳定的
`implementation_key` 仅用于内部关联同一范围的方案、交付、产物与能力。
