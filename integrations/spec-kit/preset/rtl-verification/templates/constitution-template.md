<!--
  文档语言合同：面向项目评审的叙述、标题、表格说明和待填写提示默认使用简体中文。
  代码、命令、路径、配置键、协议名、标准标识符和原始引用保持原文。
-->

# [PROJECT_NAME] 宪章

## 核心原则

### [PRINCIPLE_1_NAME]

[PRINCIPLE_1_DESCRIPTION]

### [PRINCIPLE_2_NAME]

[PRINCIPLE_2_DESCRIPTION]

### [PRINCIPLE_3_NAME]

[PRINCIPLE_3_DESCRIPTION]

### [PRINCIPLE_4_NAME]

[PRINCIPLE_4_DESCRIPTION]

### [PRINCIPLE_5_NAME]

[PRINCIPLE_5_DESCRIPTION]

## verif-harness RTL 验证原则

### DUT 不可变

已配置的 DUT RTL 是外部只读资产。规格、计划、任务、生成的验证代码和工具调用
不得修改 DUT RTL。

### 单一规格权威

`specs/` 是验证需求唯一可编辑的事实源。生成的文档视图、证据索引、报告和评审包
必须链接回该事实源，不得形成相互竞争的规格权威。

### 可追踪执行

每个可执行任务必须标明 requirement、verification feature、Stage、
`verif-harness mode`、预期产物、证据合同和 owner。规范链路为：
`REQ -> VF -> PLAN -> TASK -> MODE -> ARTIFACT -> EVIDENCE -> GATE`。

### 证据与权限分离

Spec Kit 或 verif-harness 命令成功不等于功能验证证据。xverif、WavePeek、
simulator、coverage 和 assertion 工具只产生有边界的证据，不产生审批。
Human Decisions、waiver、Stage gate、sign-off、freeze、发布安全性和歧义规格语义
始终属于 Human authority；工具输出不得表示为 Human approval。

### 冻结基线控制

已批准的 Human Decisions 和 Approval Decisions 在没有获批 change request 时必须
保持不可变。导入已有批准项目时，必须表示为 immutable baseline，不得改写成仿佛
最初就是通过 Spec Kit 开发的历史。

## [SECTION_2_NAME]

[SECTION_2_CONTENT]

## [SECTION_3_NAME]

[SECTION_3_CONTENT]

## 治理

[GOVERNANCE_RULES]

**版本**：[CONSTITUTION_VERSION] | **批准日期**：[RATIFICATION_DATE] |
**最近修订**：[LAST_AMENDED_DATE]
