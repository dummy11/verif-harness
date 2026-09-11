# 验证点矩阵

> 本文保存工程语义。状态、修订、评审和 evidence 通过 `verif-harness docs status/render`
> 从 Verification Knowledge Model 按需查看，不在正文重复维护。

## 分解规则

从只读规格和用户确认的行为分解稳定的 feature ID。RTL 观察不能自动升级为规格要求。
将正常、边界、异常、并发、reset 等场景分开；不适用的场景说明依据。

## 验证点

| Feature ID | 行为与预期结果 | 来源/版本/章节 | 场景 | 优先级 | 本轮范围 |
| --- | --- | --- | --- | --- | --- |

## 检查与覆盖映射

| Feature ID | Checker/Assertion ID | Coverage ID | Test ID | Desired ID | Evidence 引用 |
| --- | --- | --- | --- | --- | --- |

尚未设计或实现的引用标为待定，不用占位 ID 表示已覆盖。来源、实现、运行证据分别链接，
不要在每个单元格重复长篇调试过程。

## 未闭合关系

| Feature ID | 缺少的策略/实现/证据 | 影响工作域 | 问题或决策引用 |
| --- | --- | --- | --- |

## 一致性要求

检查来源可追溯、验证点可判定、ID 唯一和跨文档引用一致。
评审记录与证据由 SQLite 按需投影。
