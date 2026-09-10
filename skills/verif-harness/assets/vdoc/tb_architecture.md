# 验证环境架构

状态：Draft · 文档修订：待填 · 关联 desired ID：待填

## 分层与职责

画出实际组件关系和 stimulus/observation/expected-result 数据流；未知组件标为提案。
说明 tb_top、harness、interface、agent、env、checker、coverage、test 的边界。
所有 RTL/spec 保持只读；验证组件放在独立输出目录。

| 组件 | 职责 | 输入/输出 | 所属层 | 实现路径或待实现 |
| --- | --- | --- | --- | --- |

## 接口与时序接入

| 接口 | 规格来源 | 驱动方 | 观察方 | clock/reset 域 | 采样与握手规则 |
| --- | --- | --- | --- | --- | --- |

## 数据流与控制流

说明事务创建、配置下发、驱动、监测、reference model、比较、覆盖采样之间的交接。
写明 reset/flush、事务结束、超时、反压、并发与残留数据的处理责任。

## 目录、构建与诊断

| 事项 | 方案 | 依赖/约束 | 待确认问题 |
| --- | --- | --- | --- |

涵盖 package/filelist 顺序、配置入口、seed、日志与波形边界。
示意代码只保留说明接口必需的短片段；完整实现留在代码文件。

## 设计决定与评审

关联 feature、reference model 合同和已记录的 Human Decisions。
列出未解决的组件责任冲突及阻塞范围；评审记录与证据：待登记。
