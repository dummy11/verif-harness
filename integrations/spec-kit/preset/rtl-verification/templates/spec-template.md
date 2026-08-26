<!--
  文档语言合同：面向项目评审的叙述、标题、表格说明和待填写提示默认使用简体中文。
  代码、命令、路径、配置键、协议名、标准标识符和原始引用保持原文。
-->

# 验证规格：[FEATURE NAME]

**规格分支**：`[###-feature-name]`

**创建日期**：[DATE]

**状态**：Draft

**输入**：用户描述：“$ARGUMENTS”

## 验证目标与范围（必填）

- **Program/Stage ID**：[验证项目与 Stage 0-5]
- **目标**：[本阶段要建立或闭合的可观察验证能力]
- **权威输入**：[规格路径、版本和上游 owner]
- **DUT 边界**：[top、interface、clock、reset、memory；RTL 只读]
- **非目标**：[明确排除的行为、接口或证据]
- **基线状态**：[new / imported immutable baseline / approved change]

## 验证场景与验收（必填）

<!--
  场景按 P1、P2、P3 排序。每个场景必须能独立观察和验收，不得把生成结构或工具
  返回 PASS 直接当成功能正确。
-->

### 场景 1：[简短标题]（优先级：P1）

[使用自然语言描述激励、可观察行为和价值。]

**优先级理由**：[说明为何属于该优先级。]

**独立验证方式**：[说明所需 testcase、assertion、coverage、reference model 或日志证据。]

**验收场景**：

1. **给定** [初始状态]，**当** [激励或事件]，**则** [可观察结果]
2. **给定** [初始状态]，**当** [异常或边界条件]，**则** [可观察结果]

### 场景 2：[简短标题]（优先级：P2）

[按需增加可独立验证的场景。]

## 边界与异常场景

- [reset、backpressure、overflow、underflow、timeout 或非法输入等边界]
- [并发、顺序、数据完整性或恢复路径]

## 需求（必填）

### 功能需求

- **REQ-001**：DUT 必须 [可观察且无歧义的行为]
- **REQ-002**：验证环境必须 [可复现的激励、检查或采集能力]
- **REQ-003**：[NEEDS CLARIFICATION: 需要 Human 决策的问题]

### Verification Features

- **VF-001**：[映射到 REQ、场景、mode、产物和证据]
- **VF-002**：[映射到 REQ、场景、mode、产物和证据]

### 关键接口与对象（适用时填写）

- **[接口/对象 1]**：[信号、transaction、约束和关系；不推断未给出的语义]
- **[接口/对象 2]**：[用途与可观察边界]

## 成功标准（必填）

<!-- 成功标准必须可度量、可复现，并区分工具证据与 Human approval。 -->

- **SC-001**：[明确的编译、仿真、回归、coverage、assertion 或性能标准]
- **SC-002**：[证据路径、seed、数据库、波形摘录或 hash 保留要求]
- **SC-003**：[独立的 Human review/gate 条件]

## 证据合同

- **验收证据**：[test、assertion、coverage、performance、regression]
- **证据保留**：[log、seed、database、waveform excerpt、hash]
- **禁止替代**：生成结构、确定性工具 PASS、Agent 结论和 Human approval 必须分开记录。

## 决策、假设与开放问题

### Human Decisions

- [已批准的语义决策；不得由 Agent 推断]

### Provisional Decisions

- [决策、owner、到期 review gate]

### 假设

- [有依据且可复核的默认假设]

### 开放问题

- [问题、owner、阻塞的 Stage]
