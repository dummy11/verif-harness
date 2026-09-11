# 验证总计划

> 本文保存工程语义。状态、修订、评审和 evidence 通过 `verif-harness docs status/render`
> 从 Verification Knowledge Model 按需查看，不在正文重复维护。

## 范围与输入依据

记录 DUT 身份、只读 RTL/spec 来源及版本。区分规格明确事实、RTL 观察和待确认假设。

| 范围 | 验证目标 | 优先级 | 来源 | 纳入/暂缓/不适用及理由 |
| --- | --- | --- | --- | --- |

## 总体验证策略

说明验证层次、激励方法、checking/reference model、覆盖率、用例和回归如何配合。
每项只写策略与边界，细节链接到专题文档。

| 策略 | 本轮目标 | 依赖 | 对应专题文档 |
| --- | --- | --- | --- |

## 验收条件

| 条件 ID | 可检查的完成条件 | required desired ID | 所需证据 | 决策引用 |
| --- | --- | --- | --- | --- |

阈值必须有用户确认或来源依据；不预填通过状态、覆盖率目标或 simulator 支持声明。
自然语言条件须落实为模型中的 required 目标，才能参与 closure。

## 风险与待决定事项

| 问题 ID | 问题/假设 | 影响目标 | 需要用户决定什么 | 决策记录链接 |
| --- | --- | --- | --- | --- |

## 文档导航与评审依据

- [验证点](feature_matrix.md)、[TB 架构](tb_architecture.md)、[参考模型合同](reference_model_spec.md)
- [覆盖率计划](coverage_plan.md)、[断言计划](assertion_plan.md)、[用例清单](testcase_list.md)
- 治理状态由 SQLite 按需投影；不要在此复制历史或伪填 Approved。
