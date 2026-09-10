# 断言计划

状态：Draft · 文档修订：待填 · 关联 desired ID：待填

## 范围与类别

说明 protocol、timing、safety 等不变量及来源。区分环境假设、DUT obligation 和 TB sanity。

## Property 合同

| Assertion ID | Feature/规格来源 | 前提与预期性质 | clock/reset/disable | immediate/concurrent |
| --- | --- | --- | --- | --- |

## 挂接与失败处理

| Assertion ID | 观察点/挂接位置 | 验证侧实现路径 | 失败级别与诊断 | 开关约束 |
| --- | --- | --- | --- | --- |

通过独立 checker/interface/bind 等方式接入，禁止修改 RTL。不能为了回归变绿而静默禁用性质。

## 非空洞与覆盖证据

| Assertion ID | 前提可达性测试 | 观察窗口 | attempt/触发证据 | 失败/通过证据 |
| --- | --- | --- | --- | --- |

零 failure 不等于断言生效；确认前提发生、reset 禁用窗口合理，且检查路径真实接通。

## 待决定项与评审

明确规格未定义行为及环境约束，不由 Agent 猜测预期反应。
评审记录与必要的例外决定：待登记。
