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
  每份文档各一个。章节、来源和验收要求作为文档产物内部清单，不再机械生成
  隐藏工作节点。Activity、assignment、问题和审批意见绑定对应公开文档节点；
  Main Agent 的验收后检查必须覆盖当前版本的全部清单。只有确有不同负责人或
  独立 gate 时才拆分更多公开节点。
- v2 中，方案批准形成 `art.doc_plan` 的不可变版本；正文由负责人批准、Main
  Agent 检查完成且没有阻塞后形成 `art.doc` 版本，Engine 再派生 `cap.doc`。
  三者是产物与可用状态，不增加公开工作节点、审批入口或进度。下游依赖
  `cap.doc`，不得用方案批准、模板存在、目录状态或 `PROVISIONAL` 代替正文可用。
  旧内部节点与检查历史保留；迁移后仍需重新核对未完成检查，不能自动批准。
- `document-writing-plan` 节点详情只展示本节点的文档撰写方案、节点审批和
  审批历史；“审批完成”必须紧邻可展开的审批入口，并且只改变当前工作节点
  状态。“审批完成”表示批准当前方案节点的全部内容，无需先提交审批意见，
  不得以分区审批数量或逐项批准作为按钮启用条件。批准说明选填，不得强制填写；
  当前节点没有审批意见时，“批准全部内容”必须可以直接使用。负责人登记一条或
  多条新增、删除、修改意见后，“批准全部内容”必须立即禁用，并显示独立的
  “提交当前 N 条审批意见给 Agent”；该操作一次提交本节点当前尚未处理的全部
  意见并形成 Main Agent 动作，不得同时写入批准结论。Agent 必须逐条保留意见，
  分析影响并修改方案或登记无影响结论；全部意见处理完成后，“批准全部内容”
  才能重新启用。新的意见进入下一批，不覆盖已提交或已处理的历史意见。
  点击确认后必须立即显示提交状态并防止重复提交。审批保存结果不应等待整个
  项目页面数据生成；保存后重新读取权威状态，刷新失败不能显示成审批失败。
  未收到保存结果时不得假定未写入或自动重试。审批完成后仍允许继续提交
  审批意见；任何后续意见都必须使旧的完成结论失效并等待重新审批，
  不得锁定审批入口或隐藏历史。
  审批区只有一套表单；审批类型仅为“新增、删除、修改”，填写“审批内容”，
  不增加二级变更动作、影响范围、分区审批或说明横幅。
- 所有文档撰写方案都要用完整、具体的中文说明写什么、依据什么、怎样检查；
  不得把内部字段名、英文关键词或斜杠分隔的术语串拼成面向负责人的句子。
  必要的专业术语首次出现时说明含义。节点不展示“预计正文交付”和“方案质量检查”
  两块内容；“输入依据”默认折叠，RTL、验证环境、参考模型和脚本等代码输入
  只列去重后的目录，文档可逐一列出；逐文件来源记录仍保留在内部审计信息中。
  工作节点列表的每一行文档撰写方案节点提供“批准全部内容”入口，与节点详情
  使用同一审批流程和版本校验；已批准时显示禁用的“已批准全部内容”。审批成功
  后只收起节点详情或返回当前工作流节点列表，不关闭浏览器标签页。
  逐文件来源、摘要和内部检查要求仍保留用于审计与变更检查，不因简化展示而删除。
- 负责人提交正文验收结论后，Main Agent 必须检查该审批、当前正文和依赖影响，
  并自行判断是否需要通过节点绑定的 `agent-question` 继续向负责人提问。
  文档交付节点只有在当前版本已由负责人审批通过、Main Agent 检查已完成且
  该节点全部 Agent questions 已解决时，才能显示为“已验收通过”。
- 文档内容验收节点与文档撰写方案节点采用相同的详情布局和审批交互，只将方案
  内容替换为当前版本 Markdown 渲染后的正文。抽屉、完整节点页及旧验收链接
  使用同一展示，不再增加通用状态卡、重复验收入口或另一套验收表单。
  保留“新增、删除、修改”意见、批准全部内容（说明选填）和审批历史；后续意见
  使旧批准失效并等待 Agent 检查。正文未读出、缺失、版本变化或仍有待确认问题时，
  不得通过简化界面绕过审批条件；只有负责人批准和 Agent 检查均完成才算验收通过。
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

### VENV、VSTIM、VCHK、VCASE、VCOV、VREG 方案与交付

- VENV、VSTIM、VCHK、VCASE、VCOV、VREG 均按 DUT 工作包使用 `code-plan` 和
  `code-deliverable` 两种公开工作节点；
  稳定的 `implementation_key` 将同一工作包的方案、交付、产物与能力关联起来。
  代码方案正文固定为目标、工作范围、具体工作、实现方式、如何验证、输出、交付条件；
  不列“待确认问题”。需要负责人决定的问题由 Main Agent 通过节点关联提问处理。
- 每个方案只批准当前版本。批准后建立对应交付节点；Agent 在交付节点中实现、
  构建、验证并分析结果，全部必需验证通过后才提交负责人验收。负责人批准是最后
  一道人工作业，批准后只重新核对版本与证据有效性，不再增加常规 Agent 验收后检查。
- VENV 方案依赖 `cap.doc`；VSTIM 还依赖 `cap.venv`；VCHK 还依赖
  `cap.venv` 和 `cap.vstim`；VCASE 还依赖 `cap.venv`、`cap.vstim` 和
  `cap.vchk`，不以 VCOV 完成为自身交付条件。交付依赖同一工作包的
  `art.code_plan`；跨工作包和下游依赖验收后派生的 `cap.<workstream>`。不得用旧 capability 工作节点、方案批准或工具
  PASS 代替代码交付可用。相关输入变化使方案、交付及能力失效；仅输出代码或验证
  证据变化时保留未变化方案。新版本不得继承旧批准或旧证据。
- VCOV 必须把 `coverage-model` + `coverage-collection` 实现包与
  `coverage-collection-evidence` + `hole-analysis-evidence` 收敛包分开；后者依赖
  当前有效的环境、激励、检查、用例、回归执行器和同工作流实现能力。VREG 必须把
  `regression-policy` + `executor-ready` 基础设施包与 `execution-evidence` +
  `triage-evidence` + `fresh-evidence` 闭环包分开，防止执行器等待最终回归结果的循环依赖。
  未覆盖项和未关闭回归失败必须记录责任工作流及下一步动作；Main Agent 分析后登记
  上游重规划/重验证要求，不得由 finding 自动修改、批准或关闭上游节点。
- 六类验证工作流页面均参照 VDOC，仅提供当前项目状态、工作节点列表及添加、删除、重启入口。
  添加和删除仅记录下一版方案要求；重启需要再次确认，保存新旧版本和操作人、原因，
  不删除文件、证据和审批历史。详情和列表共用节点审批，批准说明选填，意见批次未
  处理完成前禁用批准。交付正文区域展示验证报告、对应代码版本和受控证据查看入口。
- 全部必需 VDOC 正文形成当前有效的 `art.doc` 和 `cap.doc` 后，负责人必须选择其余
  工作流“并行形成方案”或“按依赖顺序形成方案”。选择绑定当前 VDOC revision 和
  capability 摘要并写入 ProjectStore。并行只并行形成方案，实施仍按 `cap.*` 解锁；
  依赖顺序为 VENV → VREG 执行器 → VSTIM → VCHK → VCASE → VCOV，VREG 最终闭环包
  仍等待其他工作流和 VCOV 的当前能力。Dashboard 不得直接创建已完成节点或代替审批。

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
- setup 进入交互 Agent CLI 前必须检查已有项目的 Dashboard，优先保留原端口，
  启动或复用独立后台服务、补齐项目注册，并实际验证授权访问。检查不得加载整份
  大方案或重新计算审批；端口冲突、权限或数据异常时明确阻止启动，不抢占其他服务。
  新项目由 bootstrap 首次注册，`--no-agent` 不启动 Dashboard；远端服务可用与
  本机 SSH 端口转发连通必须分开说明。

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
- “风险与变更”只作为负责人查看影响的只读页面，必须按当前公开工作节点聚合，
  每行只显示“相关节点、节点状态、风险或变更内容”。同一节点的内部 finding、
  依赖传播和重复记录合并在该节点下，侧栏数量按相关节点计数；内部节点、原始
  记录数、ID 和时间戳默认不展示。需要负责人审批、验收、回答或接受例外的事项
  仍统一进入“需要你处理”，不得把风险记录数量表现成人工待办数量。
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
