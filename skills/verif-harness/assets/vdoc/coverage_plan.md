# 覆盖率计划

> 本文保存工程师需要直接阅读和修改的覆盖率设计。文件版本、评审状态和证据通过
> `verif-harness docs status/render` 查看，不在正文重复维护。

## 覆盖目标与口径

分别定义 functional、code、assertion coverage 的用途与分母。
阈值、排除原则和适用工具由项目依据或 Human Decision 确认，不预设全部为 100%。

## 功能采样设计

| Coverage ID | Feature ID | 采样对象/事件/有效条件 | bins 与边界 | 预期激励 |
| --- | --- | --- | --- | --- |

## Cross 与可达性

| Cross ID | 参与维度 | 合法组合 | 非法/不可达依据 | 控制规模的方法 |
| --- | --- | --- | --- | --- |

不能只在产生 stimulus 时采样就宣称 DUT 已执行该行为；说明观察点与成功条件。
避免没有工程目的的全笛卡尔积；未证明不可达的项保持开放。

## 收集、补洞与验收

说明报告与源码/配置版本的关联、合并规则、目标测试与回归的分工。

| 目标 ID | 检查方式 | Evidence 引用 | 缺口处置工作域 | 问题/决策引用 |
| --- | --- | --- | --- | --- |

只有出现具体 code coverage 豁免候选时才创建 waiver manifest；不能预填审批或大范围 exclusion。

## 一致性要求

核对统计范围、采样含义、feature 映射、场景能否到达 DUT，以及证据是否对应当前文件和配置。
评审状态保存在 SQLite 中，通过 `verif-harness docs status/render` 查看。
