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
  推进。在当前必需 `document-writing-plan` 节点未经负责人完成审批、
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
- 对本轮实际纳入的 N 份文档，VDOC 默认建立 N 个公开的
  `document-writing-plan` 节点和 N 个公开的 `document-deliverable` 节点，
  每份文档各一个。章节、审批变更项和依赖影响必须映射为负责人不可见的内部
  工作子节点；这些子节点与其他工作节点使用同一状态、依赖、Activity、Agent
  assignment、问题、支持材料、失效传播和 closure 机制，只是不单独形成负责人
  待办或审批结论。只有确有不同负责人或独立 gate 时才拆分更多公开节点。
- `document-writing-plan` 节点详情只展示本节点的文档撰写方案、节点审批和
  审批历史；“审批完成”必须紧邻可展开的审批入口，并且只改变当前工作节点
  状态。审批完成后仍允许继续提交审批意见；任何后续意见都必须使旧的完成
  结论重新计算，不得锁定审批入口或隐藏历史。
  审批区只有一套表单；审批类型仅为“新增、删除、修改”，填写“审批内容”，
  不增加二级变更动作、影响范围、分区审批或说明横幅。
- 负责人提交正文验收结论后，Main Agent 必须检查该审批、当前正文和依赖影响，
  并自行判断是否需要通过节点绑定的 `agent-question` 继续向负责人提问。
  文档交付节点只有在当前版本已由负责人审批通过、Main Agent 检查已完成且
  该节点全部 Agent questions 已解决时，才能显示为“已验收通过”。
- VDOC 工作流主页面只提供“当前项目状态”“工作节点列表”以及“添加节点”
  “删除节点”“重新启动工作流”三个工作流级入口。方案审批、正文验收、问题
  确认和支持材料判断都属于具体工作节点，不得再在 VDOC 主页面增加一套整条
  工作流审批入口或与节点重复的汇总操作。
- “添加节点”和“删除节点”只登记负责人对下一版方案的变更要求，不得由
  Dashboard 或 Agent 直接创建、删除当前节点；删除表示从下一版方案移出，旧
  节点、正文、审批、验收和审计历史必须保留。Agent 必须分析变更影响并提交
  新 revision，之后仍按节点审批。
- “重新启动工作流”必须由负责人点击后再次确认，并记录操作人、原因和新旧
  revision。它只重启 VDOC 生命周期：旧节点审批不继承到新版本，流程回到
  Agent 形成文档撰写方案；不得删除或覆盖已有文档、节点历史、审批、验收、
  支持材料，也不得重启 Dashboard、CLI 或整个验证项目。

## Current-project issue guardrails

### 状态、证据和项目边界

- 回答“当前阶段/状态”、展示 Dashboard 状态或诊断问题前，必须核对本次实际
  使用的项目根目录、Dashboard 注册项目、Git branch/commit、Workstream
  revision、状态数据库和证据时间。不得把本地与远端、`verif_v0` 与
  `verif_v1`、不同账号、不同数据库或不同 revision 的结果拼成同一结论。
- 状态说明必须分开写明正式生命周期状态和实际实现进度，并标注依据属于本地
  实测、负责人确认、工具报告还是尚未核实的远端信息。`ACTIVE`、
  `PROVISIONAL`、dry-run、clean audit、子 Agent/Activity 完成或
  `READY_FOR_HUMAN_REVIEW` 均不等于验证闭环、freeze、签核、模拟器支持或
  公开发布授权。
- 方案、节点、审批、进度、问题和证据都必须绑定当前 revision 和内容摘要。
  revision 或正文摘要变化后，旧审批、旧进度和旧 closure 结论不得自动继承；
  必须重新检查受影响的依赖和完成条件。
- Dashboard 可用性必须同时核对服务进程、监听端口、目标项目注册和实际请求。
  SSH tunnel 存在不代表服务可访问；直接启动 Dashboard 与 `bootstrap` 必须
  使用一致的后台 start-or-reuse 语义。共享端口上的项目、账号、数据库和写入
  token 必须严格隔离，注销项目不得删除项目文件或验证历史。

### 控制面状态一致性

- 项目状态数据库和 `ProjectStore` 是 Dashboard、Workflow、工作节点和 Agent
  CLI 的唯一事实源。Dashboard snapshot、工作流页面、节点详情、CLI
  `status`/`closure`、Agent question/activity 等只能是同一份持久化状态的投影；
  不得在前端、CLI 或 Agent 层维护另一套可独立推进的权威状态。
- 任何一侧完成写操作后，都必须以同一 project、revision、definition/document
  digest 重新读取状态。Dashboard 与 Agent CLI 对 lifecycle、节点 status、
  closure ready/actions、审批和验收状态、负责人待办、Agent 等待状态及进度的
  结论必须一致；event stream 只负责通知刷新，不能替代重新读取权威 snapshot。
- Workflow 汇总状态必须能由当前 revision 的必需工作节点、依赖、证据、开放
  问题和 closure 结果确定性解释。若出现“工作流已完成但必需节点未完成”、
  “CLI 等待负责人但 Dashboard 无待办”或同类矛盾，必须 fail closed，显示冲突
  来源并要求重新计算/刷新，不得选择其中一个状态继续推进。
- 状态一致性必须做双向合同测试：CLI 写入后检查 Dashboard、Workflow 和节点；
  Dashboard 写入后检查 CLI `status`/`closure`、模型投影和节点。测试至少覆盖
  project 切换、revision/digest 过期、审批、Agent question、Activity、证据登记、
  节点关闭和 Workstream 汇总，不能只比较页面文案或单一 happy path。

### VDOC 分解、审批和进度

- 固定的 `document-catalog` 只负责组织正式文档，不是公开工作节点，不计入
  撰写方案数、正文交付数或节点进度。不得把固定目录数量当成 DUT-specific
  文档工作的节点上限。
- VDOC 必须使用两个独立 proposal 阶段：方案阶段只能包含
  `document-writing-plan`，方案全部批准且当前 revision 为 `ACTIVE` 后，正文
  阶段只能登记 `document-deliverable`。正文 proposal 中每个必需撰写方案必须
  至少有一个同 `document_key` 的必需交付后代，每个必需交付节点必须能回溯到
  对应的必需撰写方案；不完整或孤立的分解必须返回 Agent 修订，不得暴露为可
  审批或可验收状态。
- 文档撰写方案通过只授权 Agent 按批准范围撰写正文；`PROVISIONAL`、方案
  `ACTIVE`、正文已同步或交付节点已登记都不表示正文验收通过。方案审批、正文
  验收和 Main Agent 验收后检查必须分别记录，不得由一个操作或状态代替。
- 进度条只表示当前 revision 的节点完成条件或审批进展：优先使用数值观测，
  撰写方案按当前节点审批完成结论，正文交付按当前验收结论，其他节点按已满足的
  acceptance conditions；没有可量化数据时只能显示 0%/100% 结论条。不得把
  进度条解释成 Agent 运行时间、主观完成度或验证质量。

### Agent 交互和多 Agent 边界

- 必须区分 runtime 原生 subagent 与 verif-harness 控制面。Engine 的
  `closure` 只选择下一项显式节点动作，不会自动启动隐藏 worker；Dashboard
  只展示已登记的 Activity、assignment、问题和结果，不得推断未登记的 Agent
  工作。
- Project Main Agent 是负责人交互和控制面写入入口。子 Agent 只能领取边界
  明确、写入范围不重叠且绑定 revision 的工作，通过 lease/heartbeat 保持任务
  有效，并把结果或阻塞返回 Main Agent；不得绕过 Main Agent 直接要求负责人
  作出工程决定。closure 或 revision 变化后，过期 assignment 必须失效。
- 子 Agent 完成、多个 Agent 一致、Activity 完成或 runtime 返回成功，都不能
  自动生成 evidence、`VALID`、审批、freeze 或关闭节点。Main Agent 必须按节点
  合同登记证据并重新执行 closure 判断。
- Dashboard、CLI 和对话中的负责人回答必须写入同一 `agent-question` 记录。
  阻塞问题必须配套持久化 await/checkpoint；仅保存回答不能声称已恢复一个已经
  回到普通命令提示符的 CLI。回答、任务 steering、权限授予、方案审批和证据
  验收是不同操作，不得互相替代。
- “需要你处理”只作为跨工作流待办汇总入口。每项必须显示操作类型、对应工作
  节点、所属文档和本次具体处理内容，点击后直接打开该工作节点；不得为同一
  节点在待办汇总中再建立一套重复的待办详情或审批入口。
- Agent 交互页固定按“当前需要处理 → Agent 工作状态 → 交互历史”组织；负责人
  当前动作必须最突出，运行细节和原始日志保持次要或折叠。项目级交互不得在
  Workstream 页面重复一套面板；节点页只显示与该节点直接相关的待处理动作和
  跳转入口。已完成的子 Agent 工作不得显示成 Main Agent 当前仍在执行的工作。

### Dashboard 链接和操作有效性

- Dashboard 中每个可见链接、按钮、表单和可点击卡片都必须绑定真实处理函数；
  写入的路由参数必须被目标页面读取，引用的 API 必须由服务端实现并执行权限
  校验，目标 Workflow、节点、问题、文档或审批记录必须存在于当前选中的项目和
  revision。不得保留占位链接、静默无响应入口或跳到默认/其他项目的链接。
- 所有页面跳转必须保留正确的项目和授权上下文，并打开与入口一致的 Workflow、
  节点或操作页面；新标签页、浏览器刷新、直接访问带参数 URL 和 project 切换后
  都必须得到相同目标。过期、缺失、无权限或已被新 revision 取代的目标必须显示
  可理解的失效原因和返回路径，不得自动改指向相似对象。
- 链接有效性不能只做 HTML 字符串或 handler 存在性检查。必须按入口类型执行
  浏览器点击或等价的 DOM 路由测试，并对对应 HTTP/API 请求做集成验证：确认
  页面确实打开、读取对象正确、写操作产生预期状态变化且刷新后仍可复现。文档
  和证据入口必须通过受控 API 校验项目归属与文件存在性，不得直接暴露任意路径。
- 首页、项目切换、Workflow、工作节点、Agent 交互、待处理、风险与变更、方案
  审批、正文验收、文档查看、工作流重启和项目注销等全部入口必须纳入链接清单
  和回归测试。新增、删除或改名任何入口时必须同步更新清单、正向点击测试、失效
  目标测试和服务端路由测试；任一可见入口无真实目标时，Dashboard 检查必须失败。

### Runtime、bootstrap 和界面验证

- 说明 runtime 能力时必须分别给出框架支持、项目已选配置、本机 CLI/依赖探测
  和端到端执行证据。项目一次只选择一个受管 runtime，不得把 `codex|kimi`
  配置项描述成自动混合调度。运行检查应优先使用 `.deps/runtime/venv/bin/python`
  和可写的 `XVERIF_MCP_LOG_DIR`；系统 Python 缺少 `mcp` 或默认日志目录无权限
  不能直接得出 runtime 不支持的结论。
- `bootstrap` 必须把 testbench、golden/reference model 和验证脚本作为三个
  独立的可选输入，集中提出仍需负责人回答的问题；在结构化问答尚未端到端执行
  前，不得宣称输入收集体验已经实现或完成。
- Dashboard 主要信息必须是当前验证对象、结论、依据、缺口和负责人下一步；
  “负责人需要处理”优先于 Agent 状态、历史和审计信息。关系码、内部 ID、路径、
  digest 和 raw log 默认隐藏或折叠；`CHILD_OF`、`DEPENDS_ON` 等关系必须转成
  可理解的验证语义。深色为首次打开默认主题，但必须尊重已保存的浅色设置。
- Dashboard/CLI 文案、状态或交互层级发生变化时，必须同步更新用户文档和聚焦
  断言；删除界面元素时同时删除旧断言并增加新的不存在断言。至少运行受影响的
  Dashboard/控制面测试、前端脚本语法检查、`git diff --check` 和 `make check`。
  不得为通过测试而放宽 VDOC、证据、审批、项目隔离或公开发布规则。
- 浏览器或事件流验证出现 SQLite `disk I/O error` 时，先停止残留 Dashboard/
  event-stream 进程并改用隔离临时数据库；自动化节点失效时刷新页面状态后重新
  定位。此类测试环境故障不得被报告成产品规则已失败，也不得通过修改正式数据
  或降低约束绕过。

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
