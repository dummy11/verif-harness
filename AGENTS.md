# Repository instructions

## Scope

This repository contains public, reusable verification infrastructure.

- Keep `examples/*/rtl/` small, license-free, and self-contained.
- Never import proprietary DUT RTL, specifications, logs, vectors, URLs,
  license configuration, or scheduler settings.
- Keep harness, interfaces, assertions, bind, UVM, and test responsibilities
  layered as described in `ARCHITECTURE.md`.
- Treat generated files as review candidates, not approved semantics.
- Do not claim simulator support without reproducible evidence.
- Keep optional xverif source under Git-ignored `.deps/`; never vendor it or
  publish proprietary EDA dependencies. Treat its lock changes as reviewed
  dependency upgrades and preserve separate licensing/ownership.
- Keep optional WavePeek source and binaries under Git-ignored `.deps/`; pin
  source, Cargo.lock, license, and version, keep FSDB disabled by default, and
  preserve WavePeek's separate Apache-2.0 ownership and release boundary.

## Product and interaction principles

- verif-harness 是面向 ASIC 验证工程师的验证控制面，不是通用项目管理、
  任务管理或审批系统。这里可复用的是 ASIC 验证控制能力，不是与验证对象
  无关的通用工作流模板。
- 工作流、工作节点、状态、进度、操作和退出条件必须对应当前被验证设计
  （DUT）、接口、功能、验证点、测试场景、检查机制、覆盖目标或验证证据。
  不同 DUT 可以具有不同的工作流结构、节点类型、节点数量、依赖和完成条件；
  不得默认套用固定的通用项目模板。
- 面向用户的文字应优先说明“验证什么、当前结论、依据是什么、还缺什么、
  谁需要处理”。使用已有的 ASIC 验证术语，不机械翻译英文，不自行创造术语；
  没有通行中文名称时保留标准英文，并在首次出现时说明含义。
- 主要页面和操作必须让不是 ASIC 验证工程师的用户也能理解当前对象、状态、
  依据和下一步。内部编号、schema、digest、数据库状态码和工具字段放在详情或
  审计信息中，不作为主要界面语言。
- 上述用词规则同样适用于 Dashboard、CLI 的帮助/标准输出/错误信息，以及
  Agent 面向用户的提问、选项、状态摘要和结果说明。面向用户时使用“你”或
  “负责人”，不要直接显示协议角色名 `Human`；使用“验证文档”“正文内容”
  等可理解名称，不以“语义文档集”“语义交付”等内部抽象代替实际对象。
  状态必须同时说明谁要对什么做什么，例如“等待负责人审批文档撰写方案”，
  不得只显示“等待计划评审”“空闲”“未登记活动”等缺少对象或行动的信息。
  CLI 命令名、JSON/schema 字段、数据库值和审计记录中的正式协议名称可以保留，
  但首次展示时必须给出面向用户的解释，且不能直接作为主要交互文案。
- VDOC 必须按“文档撰写方案审批 → Agent 撰写正文 → 正文内容验收”串行
  推进。在当前 `document-writing-plan` 的所有必需区块未经负责人批准、
  VDOC 未进入 `ACTIVE` 前，Agent 不得自行生成或修改正式正文，不得通过
  `docs sync` 建立新的正文语义版本，不得激活可验收的
  `document-deliverable` 节点，也不得要求负责人同时审批撰写方案和
  验收正文内容。
- 初次 VDOC proposal 只能包含 `document-writing-plan`。所有必需方案批准后，
  Agent 才可撰写正式正文、执行 `docs sync`，并通过另一份只包含
  `document-deliverable` 的 proposal 登记正文验收范围；两种节点不得在
  同一 proposal 或同一次负责人审批请求中出现。`plan VDOC` 在方案审批前
  只能创建缺失模板并登记路径和摘要。
- 只有用户明确要求提前试写时，Agent 才可在方案批准前生成正文草稿；必须
  显著标记为“未批准预览草稿”，不得作为验证证据、文档通过、VDOC 完成或
  下游实现授权。方案进入 `ACTIVE` 后，Agent 才按已批准范围撰写和同步正文，
  再单独登记对应内容节点供负责人验收。

## Required checks

Before committing, run:

```bash
make check
```

Before a public release candidate, run:

```bash
make release-check
```

Do not weaken the denylist or exclusion rules merely to make an audit pass.

## Default delivery

- 用户要求修改或实现本仓库内容时，相关检查通过后默认提交并推送到当前分支
  已配置的 upstream；不需要用户再次说明“上传”。
- 如果检查失败、远端存在非 fast-forward 冲突、工作区包含范围不明的改动、
  可能包含敏感或专有内容，或者用户明确要求不要上传，则停止在提交或推送前，
  说明具体阻塞并等待用户处理。
- 默认交付不包含创建或合并 PR、打 tag、创建 release，也不代表负责人批准
  验证结论或授权公开发布。
