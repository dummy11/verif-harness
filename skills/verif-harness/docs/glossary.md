# verif-harness 术语表

配合[工作机制](mechanism.md)阅读；命令与参数见[用户指南](user_guide.md)。

<a id="control-plane"></a>
## 控制面、Agent、Skill

**Control plane（控制面）**保存目标和工程状态，计算缺口，记录评审与证据。
实际编译、仿真和波形处理由工程工具执行。

**Agent** 是当前 Codex/Kimi 会话中的执行者：理解用户目标、调用工具、读取结果、提问。
**Skill** 是 Agent 遵守的工作指令，包括输入收集和权限边界；不是常驻服务。
**CLI** 是结构化操作入口，一次调用完成一项操作并返回结果。

<a id="subsystems"></a>
## 五个子系统

| 正式名称 | 中文含义 | 对应用户入口 |
| --- | --- | --- |
| Verification Planner | 验证规划器：组织模板、项目上下文和目标 revision | plan、review |
| Verification Knowledge Model | 验证知识模型：保存事实与关系；不是 DUT/reference model | inspect、trace、impact；写入用 record 等 |
| Verification Consistency Engine | 验证一致性引擎：确定性检查与变更失效传播 | check、changed |
| Verification Closure Engine | 验证收敛引擎：比较当前状态与目标并列出动作 | closure、status |
| Verification Reasoning Engine | 验证推理引擎：组织语义分析请求 | reason |

这些名字表示职责，不要求用户启动五个进程。

<a id="workstream"></a>
## Workstream、Stage、Lifecycle

**Workstream（工作域）**是围绕一类验证能力维护目标、证据和修订的上下文。
VDOC 管文档，VSTIM 管激励，VCHK 管检查，VCOV 管覆盖率，VCASE 管用例，VREG 管回归。
例如 checker 还没完善时，也可以先实现 stimulus；两者可同时活跃。

**Stage（阶段）**通常表示线性里程碑。v1 不用 Stage 0–5 控制六个工作域的执行顺序。
**Lifecycle（生命周期状态）**表示工作域处在待评审、执行中、满足或已冻结等状态；
它与单个节点是否有效是两件事。

<a id="desired-current"></a>
## Objective、Desired state、Current state、Exit criteria

- **Objective（总体目标）**：为什么做这项工作，例如“建立可信的输出比较”。
- **Desired state（期望状态）**：需要成立的具体条件，例如“backpressure 场景无丢失或重复比较”。
- **Current state（当前状态）**：模型中现有节点的有效性、证据和 finding；不是 Agent 的完成感受。
- **Required（必需）**：该目标必须被满足或由 Human waiver，才能局部 closure ready。
- **Exit criteria（退出标准）**：供评审使用的完成条件；当前自然语言文本不自动成为可执行 gate。

Desired 描述结果，action 描述下一步做什么。一个 desired 可以经过多轮 action 才满足。

<a id="knowledge"></a>
## Node、Relation、Dependency、Trace、Impact

**Node（节点）**是有 ID、类型、标题和 validity 的对象，例如 requirement、desired、
文件或 evidence。**Subject/Target** 是一次证据登记或动作所针对的节点 ID。

**Relation/Edge（关系/边）**连接两个节点。**Dependency（依赖）**表达影响关系，
例如 RTL 行为变化会使 checker 结论需要重新验证。实际传播沿已登记的出边进行。

**Trace（追溯）**查看节点直接连接的入边、出边、证据和发现。
**Impact（影响分析）**查看沿出边可达的下游节点，即影响闭包；不代表自动理解所有源代码依赖。

**REQ（需求）**描述 DUT 应有行为；**VF（验证点/Verification Feature）**将需求转为
可验证关注点；**Mode/Capability** 是处理动作所需的能力，例如仿真或 coverage 分析。
`REQ → VF → DESIRED → ACTION → ARTIFACT → EVIDENCE → REVIEW` 是建议追溯关系，
并非 CLI 自动创建且完整校验的一条固定流程。

<a id="gap-action"></a>
## Gap、Finding、Action、Closure

**Gap（缺口）**是当前状态与 required desired 的差距，如目标仍 UNKNOWN。
**Finding（发现项）**是需要处置且能记录原因的问题，如某次 RTL change 使一个结论失效。
Finding 的 OPEN/RESOLVED/WAIVED 是问题处置状态。

**Action（动作）**是 closure 当前推导的建议，包含目标、原因、优先级、executor 和
suggested mode。动作会随状态变化重算，不等于已运行的 task。
**Executor** 表示建议交给确定性工具、推理还是 Human；它不是授权凭证。

**Closure（收敛）**表示在模型登记的目标范围内处理缺口。
**Reconcile（重新计算）**是读取最新状态、刷新 closure 动作的过程。
`ready=true` 表示该工作域按当前规则没有剩余动作；不代表模型外没有漏验。

<a id="evidence"></a>
## Artifact、Evidence、Verdict、Digest、Provenance

**Artifact（产物）**是文档、checker、testcase 或报告等工程文件。
**Evidence（证据）**是明确绑定 subject 并登记 source/kind/verdict/digest 的结果记录。
有一个结果文件不等于它已经支持某个目标，需要检查结果并建立绑定。

**Verdict（判定）**是 pass/fail 等结论；`prove` 接受调用方给出的结果，不自动理解报告语义。
**Digest（摘要）**是文件内容的 SHA-256 指纹，用于标识登记时内容；不是功能正确性证明。
**Provenance（来源记录）**说明信息从哪里来、何时记录、针对哪个对象，便于审计。

Relation 的 **origin** 分为 explicit（明确登记）、inferred（推断）、runtime（运行时建立）。
**Confidence（置信度）**是推断可信程度的记录，不能代替真实 evidence 或 Human approval。

<a id="validity"></a>
## Validity、Stale、Invalidation、Revalidation

**Validity（有效性）**属于节点：UNKNOWN 尚未证明，VALID 已登记通过证据，INVALID
失败或已知不满足，STALE 已过期，REVALIDATION_REQUIRED 需要重新验证，
REVIEW_REQUIRED 需要评审，BLOCKED 无法继续，WAIVED 已被人工豁免。

**Invalidation（失效传播）**指因变化撤销旧结论的可依赖性；STALE 不一定意味着设计有 bug。
**Revalidation（重新验证）**是针对变化重新获得依据。
**Fresh evidence（新鲜证据）**在工程上应对应当前输入和环境；当前 CLI 不会持续监控并
自动重验所有证据文件，变化仍需主动登记。

<a id="human-gate"></a>
## Open question、Decision、Review、Waiver、Gate

文档治理把决策内容区分为四类：

- **Human Decision（人工决策）**：用户已明确批准的工程基线；Agent 可提出选项和记录回答；
- **Provisional（暂定决策）**：已有可执行方向，但保留基于日期、milestone、新 evidence
  或 closure 状态的复审触发器；
- **Assumption（待 Human Review 的假设）**：应由 Human 决定但尚未确认，不得写成事实；
- **External Open Question（外部开放问题）**：依赖项目外输入，需记录 owner、依赖、
  阻塞目标和状态。

v1 不使用 Stage gate 作为决策生命周期。一般的 **Open question（待明确问题）** 可以是
缺少事实或尚未确定的工程语义，例如数值容差；Agent 应按上述四类进一步归属。
**Review（评审）**对当前 desired revision 作 approve/reject/modify/clarify 判定。
批准目标与证明实现是两个步骤。

**Waiver（豁免）**是 Human 有理由接受某个目标未满足，必须记录理由和 reviewer；
它不表示验证通过。**Gate（门禁）**是必须满足条件或获得人工决定才能推进的边界。
**Fail closed** 表示条件不足时拒绝继续，例如 closure 还有动作时拒绝 freeze。
Human gate 的权限规则由 Agent/Skill 遵守；自动填入 reviewer 不等于认证该人确实批准。

<a id="baseline"></a>
## Revision、Baseline、Freeze、Sign-off

**Revision（修订）**可以指 Workstream desired revision，也可以指由文档内容摘要变化产生的
semantic revision；两者都与 Git commit 编号不同。
**Baseline（基线）**是封存的状态 manifest，关联目标、模型、证据引用和评审信息。
**Freeze（冻结）**创建该快照。Workstream freeze 封存一个工作域，final freeze 汇总
六个已冻结工作域。VDOC freeze 会快照已评审的工程语义 Markdown；其他输入和报告仍以
摘要/引用进入 manifest，不会锁定整个工作区。

**Sign-off（签核）**是负责人对验证范围、证据和剩余风险的工程认可；CLI freeze
只能提供记录支持，不能代替该判断。

<a id="authority"></a>
## Source of truth、Projection、Manifest

**Source of truth（权威数据源）**按职责划分：项目 VDOC Markdown 保存验证工程语义；
节点、文档摘要、semantic revision、事项状态、关系、评审和 evidence 存在
`model.sqlite3`；项目身份与 runtime 等还会从 `project.json` 读取。
**Projection（投影）**是供人阅读的派生表示，例如 `model.md` 和工作域 `plan.md`。
`docs render` 还可按需投影文档治理状态，但不会修改语义正文。编辑投影不会更新数据库。
**Manifest（清单）**是结构化身份或快照描述文件；不要把所有 JSON 都当成可随意编辑的
阅读副本，状态变更应走 CLI。

<a id="runtime"></a>
## Runtime、Backend、MCP、Reference model

**Agent runtime** 是交互宿主 Codex/Kimi；**managed runtime** 是受管 Python/依赖环境。
**Backend** 是承担执行或推理的后端，如 direct/调度器或 Codex/Kimi。
**MCP server** 向 Agent 暴露工具；configured 表示配置存在，connected 表示已连接，
tools available 表示当前会话可调用。它不因配置存在就自动运行验证。

**Reference model（参考模型）**给出预期 DUT 行为，用于比较；与保存知识和依赖的
Verification Knowledge Model 不同。**DUT** 是被验证设计；所有 RTL 与 RTL spec
均为当前 Agent 的只读输入。
