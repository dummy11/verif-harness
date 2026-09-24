# 验证计划示例

> 公开测试样例，仅用于检查文档阅读视图。

## DUT 范围

检查 **ready/valid** 握手、*复位* 和 `payload`。~~旧策略~~已经替换。

| Feature ID | 预期结果 | 检查方法 |
| --- | --- | --- |
| FEAT-001 | 仅在握手时采样 | `valid && ready` |
| FEAT-002 | 数据保持 a\|b | checker |

- 正常传输
  - 连续事务
- 反压

1. 施加复位
2. 检查输出

```systemverilog
assert property (@(posedge clk) valid && !ready |=> $stable(payload));
```

[当前章节](#dut-范围)
[专题断言](assertion_plan.md#范围与类别)
[失效章节](assertion_plan.md#missing-section)
[未登记文档](missing.md)
[越界文档](../../../../outside.md)
[外部说明](https://example.com/verification)
![示例图片](https://example.com/tracker.png)

<script>globalThis.markdownInjection = true;</script>
<img src="x" onerror="globalThis.markdownInjection = true">
<form id="delivery-review-form"><input name="reviewer"></form>
[危险地址](javascript:alert%281%29)
[编码地址](jav&#x61;script:alert%281%29)
[文件地址](file:///etc/passwd)

## DUT 范围

重复标题保留独立的章节锚点。
