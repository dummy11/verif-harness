# 用例清单

> 本文保存工程语义。状态、修订、评审和 evidence 通过 `verif-harness docs status/render`
> 从 Verification Knowledge Model 按需查看，不在正文重复维护。

## 用例组织与优先级

定义 smoke、directed、boundary、random、stress 等分类，以及本项目优先级含义。
用例定义与执行结果分别记录，历史运行只引用 evidence。

## 用例定义

| Test ID | 目标/Feature ID | 优先级 | 配置与触发场景 | 预期检查 | Coverage/Assertion ID |
| --- | --- | --- | --- | --- | --- |

## 可执行映射

| Test ID | 实现入口 | seed/复现方式 | 超时与结束条件 | 回归集合 | Evidence 引用 |
| --- | --- | --- | --- | --- | --- |

尚未实现的用例标为待实现，不虚构测试类名或通过记录。运行 manifest 负责选择执行项，
本表负责目标和可追溯关系，两者需核对一致。

## 缺口与依赖

| Test ID/Feature ID | stimulus/checker/环境依赖 | 本轮可执行范围 | 待解决项 |
| --- | --- | --- | --- |

## 一致性要求

核对用例有明确 oracle、能复现、能终止且关联验证点；避免仅“运行不报错”即通过。
评审状态与证据由 SQLite 按需投影。
