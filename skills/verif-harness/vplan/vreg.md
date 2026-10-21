# VREG：回归基础设施与结果验收

VREG 直接使用四种公开工作节点类型。根据 DUT 的测试范围、执行配置和结果验收边界，
可以建立多个同类型节点；方案与对应交付通过内部标识关联。

结果方案按回归 group 分解：一个 group 是一组 case 与一个 testbench submit profile
（执行配置）的绑定。每个 group 一个结果方案，批准后一个对应结果交付；同一 case 集合
使用两个 profile 就是两个 group。基础设施不按 group 重复建设，多个 group 可以引用
同一已验收基础设施。seed、repeat、执行批次和失败重跑都留在节点内部，不增加工作包
层级、公开工作节点或额外审批入口。

| 工作节点类型 | 内部角色 | 输入依据 | 完成内容 |
| --- | --- | --- | --- |
| 回归基础设施方案 | `regression-infrastructure-plan` | 已验收文档 `cap.doc` 和可运行的环境 `cap.venv` | 明确测试集合、seed、timeout、重跑、已知失败和结果保留规则，等待负责人批准 |
| 回归基础设施交付 | `regression-infrastructure-deliverable` | 对应已批准方案 `art.code_plan` | 实现并自检 runner/collector，等待负责人验收 |
| 回归结果方案 | `regression-results-plan` | 当前有效的 `cap.doc`、`cap.venv`、`cap.vstim`、`cap.vchk`、`cap.vcase`、`cap.vcov:coverage-collection`，以及明确关联的基础设施能力 | 明确本组 case、执行配置、seed 模式、repeat、结果准入和失败分析要求，等待负责人批准 |
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

新增、删除或修改回归结果 group 时，未变化的基础设施保留原方案和交付节点、节点版本、
批准与验证记录，执行器能力版本保持不变。只为变化的结果范围形成新版本；结果方案、
批次和执行轮次继续绑定当前结果范围，不能据此复用旧轮次证据。基础设施范围、输入、
代码或原始证据变化仍须重新核对，工作流目标、决策变化或显式重启不保留旧节点。

结果交付必须同时验证 `execution-evidence`、`triage-evidence` 和 `fresh-evidence`。
结果方案的覆盖率执行前置只使用覆盖率实现交付产生的 `cap.vcov:coverage-collection`，不能等待
覆盖率收敛结果；因此本轮执行与证据验证完成后，VDB 可以先交给 VCOV 收敛。回归结果交付的
最终负责人验收再要求当前 `cap.vcov:coverage-collection-evidence` 和
`cap.vcov:hole-analysis-evidence` 均有效。执行就绪、结果验证和最终验收是三个不同结论，不能
互相代替，也不会形成 VREG 等 VCOV、VCOV 又等 VREG 的依赖环。
testbench submit 工具按 submit profile 生成 `RegressionBatchManifest/2` 和 caselist；
同一组 case 绑定不同 profile 时必须形成不同 batch。执行证据绑定 batch、caselist、
submit file/profile 摘要、seed、日志和代码版本；相同 case 可出现在不同 batch，逐项
结果使用 batch、case、seed 和 iteration 联合标识。失败分类使用同 seed 重跑，失败原因及处理
结论必须可追溯。执行失败的 test/seed 与分类记录必须精确一致，不得遗漏、增加或重复；
接受已知失败时，必须引用同项目、当前 VREG revision 的负责人例外批准。
当前版本验证证据的 `snapshot_revision` 必须等于报告 revision。Engine 派生当前全部
必需上游交付及证据摘要，不信任报告自行填写的清单；读取和验收时重新核对，范围或证据
变化即撤销旧结果。结果交付自身及其他结果交付的验收不作为 fresh 检查前置，避免互相等待；
它们仍由 VREG 整体完成条件逐一检查。基础设施验收只说明
回归执行器可用；当前必需的基础设施与结果两部分都完成验收后，VREG 才满足完成条件。
每项批准和证据均绑定当前 revision 和内容摘要，新版本不继承旧批准或旧证据。

## 批准的回归范围和参数

结果方案的 `regression_config` 包含 `regression_group`、带版本摘要的 `cases`、
完整 `SubmitProfileRef/1` 引用、`seed_mode` 和 `repeat`。指定模式还必须提供 `seed`。
submit 文件必须实际存在且摘要一致，并作为方案输入监控；控制面不解析它的站点配置。

| seed 模式 | 每个 case 的 repeat=N | 默认次数 |
| --- | --- | --- |
| `random`：每次随机生成 | 执行 N 次，每次由回归脚本生成并在启动前保存实际 seed；同 case 本轮内去重 | 1 |
| `fixed`：指定 seed | 使用批准的同一个 seed 执行 N 次，不表示 N 个不同随机场景 | 1 |

repeat 必须为正整数，表示计划总次数而非追加次数。基础设施交付应实际验证所支持的
seed 模式、重复执行、保存和复现机制；已有项目脚本满足要求时直接复用。能力不支持时
先完善基础设施，不能静默改模式或少跑。结果方案仅选择本轮参数，不重新实现这些机制。
case 集合、submit 配置、seed 模式/指定值或 repeat 改变后重新审批方案；按原随机策略
生成实际 seed 不改变批准方案。

批次与 `RegressionEvidence/3` 的执行、失败分类和版本检查报告携带同一
`execution_binding`：`round_id`、`plan_node_id`、`plan_revision`、`plan_digest`。
批次 `runs` 记录实际 case、seed 和 iteration。控制面核对全部计划执行次数、批准的
case/profile 版本和当前轮次，拒绝混 group、漏跑、重复记录及旧轮次报告。

## 按已批准方案重新回归

仅结果交付节点提供“按已批准方案重新回归”，不在方案节点重复设置，不与“批准全部
内容”混用。负责人确认后登记新执行轮次，沿用仍有效的批准方案；不会重启 VREG、
重新建设基础设施或新增公开节点。方案/依赖失效、存在阻塞问题或有在途执行时禁止启动。

```text
负责人确认重新回归 → 请求已保存 → Agent 接续并调用现有回归入口
    → 提交本轮真实运行证据 → Agent 验证通过 → 等待负责人验收本轮结果
```

请求保存、Agent 接续或登记工具调用不等于已经完成仿真。新轮次开始前，旧结果不再作为
当前交付的验收和能力依据；方案与基础设施保持，历史报告、证据和批准记录保留可查。
新结果仍须验证和负责人验收。同 seed 的失败重跑属于失败分析，不建立整组新轮次，
不增加计划 repeat，也不得覆盖首次失败记录。

Agent 中断不代表外部任务已经结束。状态待核对时，重新审批、重新规划或重启工作流
都不得绕过旧任务保护；Main Agent 必须沿原轮次提交真实结束事实。若原方案已经失效，
该记录只用于核对旧任务是否结束，不能用于交付验收或新执行授权。

CLI：`code rerun NODE --revision N --definition-digest DIGEST --reviewer NAME --request-key KEY --confirm`
登记同一执行请求；参数不得在此命令中覆盖。保存后读取 `code status NODE` 核对当前
执行轮次；Main Agent 通过 `code execution-start` 登记现有工具调用，仍须提交真实证据。

尚未关闭的失败必须写明责任工作流和下一步动作。Main Agent 只依据当前有效的分类证据向相应上游登记
重规划或重验证要求；不会因 regression FAIL 自动批准修改、自动关闭节点或修改 DUT。
修复或证据更新后，版本摘要和依赖图负责使受影响节点重新验证，最终由新的 VREG 结果
确认问题是否真正关闭。

旧 VREG 的 `code-plan` / `code-deliverable` 记录继续可读，界面根据其完整能力要求显示为
基础设施或结果类型；历史节点、审批和证据不被改写。旧结果验证记录缺少当前
`RegressionResults/4`、批准配置或轮次绑定时必须重新验证，不可继续作为当前验收依据。
新方案使用上述四种明确角色，稳定的
`implementation_key` 仅用于内部关联同一范围的方案、交付、产物与能力。
