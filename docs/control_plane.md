# V1 control plane

The v1 control plane uses five cooperating subsystems: VPlan, VModel, VCheck,
VClosure, and VReason. See the [mode catalog](skill_modes.md) for commands and
the [architecture summary](architecture.md) for authority boundaries.

There is no long-lived workflow worker. The Agent remains in the foreground for
questions; deterministic commands are short-lived and persist their result
before returning.

## 文档撰写方案审批

在工作节点列表的对应行，或文档撰写方案详情中点击“批准全部内容”，确认审批人
后即可提交，批准说明选填。两个入口使用同一节点、版本和审批记录。
这表示批准当前节点的全部方案内容，不要求先提交新增、删除或修改意见。

输入依据默认折叠。RTL、验证环境、参考模型和验证脚本只列目录；规格和其他文档
保留完整文件列表。代码的逐文件版本记录仍保留在折叠的审计详情中。
审批成功并刷新状态后自动收起侧边详情；完整节点页面则返回工作节点列表，不关闭
浏览器标签页。已通过的节点显示禁用的“已批准全部内容”，不会重复提交。

提交时立即显示“正在提交”，同一表单不能重复提交。服务端保存审批并更新当前
工作流后，先返回保存结果，再单独读取项目状态；页面不再等待整个项目的数据
生成后才提示审批已保存。此操作不批准正文内容，也不改变其他工作流的审批。

如果审批已经保存但页面刷新失败，会明确显示“审批已保存”，可点击“刷新审批
状态”重新读取，不会重复提交审批。请求超过 30 秒或连接中断时，可能已经写入，
请先刷新并检查该节点的审批历史，不要反复点击确认。审批人仍为必填，过期方案、
无权限或存在待处理问题时仍拒绝审批。
