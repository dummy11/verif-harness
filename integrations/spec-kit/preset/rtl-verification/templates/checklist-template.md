<!--
  文档语言合同：面向项目评审的叙述、标题、表格说明和待填写提示默认使用简体中文。
  代码、命令、路径、配置键、协议名、标准标识符和原始引用保持原文。
-->

# [CHECKLIST TYPE] 检查表：[FEATURE NAME]

**用途**：[说明本检查表覆盖的规格质量范围]

**创建日期**：[DATE]

**关联规格**：[链接到 spec.md 或其他权威文档]

**Review ownership**：这是 reviewer-owned 的需求质量评审工件。只有 reviewer
确认质量标准满足后才能标记 `[x]`；`[x]` 不表示实现工作已完成。

## RTL 验证规格质量

- [ ] CHK-VH-001 已命名唯一可编辑规格权威。
- [ ] CHK-VH-002 DUT RTL 路径明确且标记为只读。
- [ ] CHK-VH-003 每条需求均可观察，并具有明确证据合同。
- [ ] CHK-VH-004 适用的 REQ/VF/TC/COV/ASRT 标识符可以追踪。
- [ ] CHK-VH-005 生成结构与动态验证证据明确区分。
- [ ] CHK-VH-006 Human Decisions、provisional decisions 和开放问题明确区分。
- [ ] CHK-VH-007 Stage entry、exit、review、waiver 和 freeze 权限明确。
- [ ] CHK-VH-008 tool version、seed、log、database、waveform 和 hash 有保留规则。
- [ ] CHK-VH-009 imported baseline 保留历史批准信息且没有虚构 provenance。
- [ ] CHK-VH-010 没有验收标准仅依赖 Agent 或 adapter 返回 PASS。

## [质量类别 1]

- [ ] CHK001 [针对需求完整性、清晰度或一致性的具体问题]
- [ ] CHK002 [针对边界、异常或恢复路径的具体问题]

## [质量类别 2]

- [ ] CHK003 [针对可度量验收标准和证据合同的具体问题]
- [ ] CHK004 [针对 traceability 和 owner 的具体问题]

## 备注

- 未完成 reviewer 评估的项目保持 `[ ]`。
- 本检查表检查需求写作质量，不检查 DUT 或验证实现是否正确。
- task runner 可以读取本 checklist 作为只读 gate，但不得修改 reviewer-owned 标记；
  它只在 task postconditions 通过后更新 `tasks.md` 的对应 `[x]`。
- `checklists/requirements.md` 由 `speckit.specify` 与 `speckit.clarify` 单独维护。
- 发现的问题应链接到权威规格、owner 和对应 review gate。
