# 验证环境架构

> 本文保存工程师需要直接阅读和修改的验证环境设计。文件版本、评审状态和证据通过
> `verif-harness docs status/render` 查看，不在正文重复维护。

## 分层与职责

画出实际组件关系和 stimulus/observation/expected-result 数据流；未知组件标为提案。
说明 tb_top、harness、interface、agent、env、checker、coverage、test 的边界。
所有 RTL/spec 保持只读；验证组件放在独立输出目录。

工作域职责要明确：VENV 维护 DUT 接口连接、clock/reset、组件结构、构建、最小运行入口和
观测点；VSTIM 维护 driver/sequence/constraint 以及目标场景能否到达 DUT；VREG 维护批量
运行、结果收集和失败处理。不要把 VSTIM 场景或完整回归当成 VENV 最小 smoke 的前置条件。

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

## 工作域依赖

列出项目特有的节点级依赖及原因。至少说明哪些 VENV 节点被 VSTIM、VCHK、VCOV、VCASE、
VREG 使用，以及接口、组件结构、构建、运行入口或观测路径发生变化时需要重新执行哪些检查。
不得使用“整个工作域完成”作为依赖；只引用实际需要的能力或运行证据节点。

## 设计决定与开放问题

关联验证点、参考模型规则和已记录的人工决定。
列出尚未解决的组件责任冲突，以及它会阻止哪些目标继续。事项状态保存在 SQLite 中，
通过 `verif-harness docs status/render` 查看。
