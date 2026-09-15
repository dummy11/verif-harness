# verif-harness 术语表

配合[工作机制](mechanism.md)阅读；命令与参数见[用户指南](user_guide.md)。

<a id="control-plane"></a>
## 控制面、Agent、Skill

**Control plane（控制面）**不是仿真器。它保存“准备证明什么、已经有哪些证据、哪些文件变了”，
然后列出当前还缺什么。实际编译、仿真和波形处理由工程工具执行。

**Agent** 是当前 Codex/Kimi 会话中的执行者：理解用户目标、调用工具、读取结果、提问。
**Skill** 是 Agent 遵守的工作指令，包括输入收集和权限边界；不是常驻服务。
**CLI（命令行工具）**按固定的命令和参数执行操作，一次调用完成一项操作并返回结果。
**Human（用户）**是当前项目的工程师或负责人。只有 Human 能决定规格含义、验证范围、是否
接受文档、是否接受未满足项，以及是否保存基线。
**Engine** 是 CLI 中按固定规则工作的代码。例如 Agent 登记 `rtl/dut.sv` 已修改后，Engine
根据数据库中已有依赖列出哪些检查需要重跑；它不会自己判断 RTL 修改是否正确，也不会自己
选择验证方案。

<a id="subsystems"></a>
## 五个子系统

| 正式名称 | 中文含义 | 对应用户入口 |
| --- | --- | --- |
| Verification Planner | 读取模板和项目现状，生成一份待 Human 确认的目标和退出条件 | plan、review |
| Verification Knowledge Model | 用 SQLite 保存已确认的目标、文件、证据、依赖和评审记录；不是 DUT/reference model | inspect、trace、impact；写入用 evidence、changed 等 |
| Verification Consistency Engine | `changed PATH` 根据调用方明确登记的文件查找下游影响；`docs sync` 比较文档 SHA-256；`evidence` 检查报告格式和引用文件 SHA-256 | check、changed |
| Verification Closure Engine | 回答“当前还缺什么、为什么不能 freeze”，只列动作、不执行 | closure、status |
| Verification Reasoning Engine | 固定规则无法判断时，整理与问题直接相关的文件、日志和已知事实，准备分析请求 | reason |

这些名字表示职责，不要求用户启动五个进程。

<a id="project-setup"></a>
## 项目路径和启动相关词

| 英文词 | 直白解释 |
| --- | --- |
| Setup | 安装 verif-harness、准备受管 Python 环境、配置 Skill/MCP，并按选项启动 Agent |
| Checkout | 从 Git 取得的一份仓库工作副本 |
| Workspace / Project root | 用户当前要管理的项目目录；项目状态和 `AGENTS.md` 位于这里 |
| RTL root | RTL 文件所在的只读根目录，可以在 workspace 外 |
| DUT top | 被验证设计最上层 module 的名字 |
| DUT top file | 定义 DUT top 的具体 RTL 文件，必须位于某个 RTL root 中 |
| Spec | 用户明确提供的 RTL 规格文件或目录，只读且可以在 workspace 外 |
| Verification root / verif root | 项目内允许 Agent 写入验证代码和结果的根目录 |
| Bootstrap | 第一次登记上述项目身份和路径，创建最小状态库和 `AGENTS.md` 说明；不生成完整验证环境 |
| Inventory | Bootstrap 记录的输入文件、工具和路径清单 |
| Managed block | `AGENTS.md` 中由 verif-harness 更新的带标记区块；标记外的用户内容保持不变 |
| Project revision | Bootstrap 记录的项目版本标识；evidence 用它确认报告是否对应当前项目版本 |

<a id="workstream"></a>
## Workstream、Stage、Lifecycle

**Workstream（工作域）**把同一类验证工作放在一起管理。例如 VSTIM 保存激励目标和证据，
VCHK 保存检查器目标和证据；每个工作域都可以多次修改和重新验证。
VDOC 管文档，VENV 管验证环境基础，VSTIM 管激励，VCHK 管检查，VCOV 管覆盖率，VCASE 管用例，
VREG 管回归。
例如 checker 还没完善时，也可以先实现 stimulus；两者可同时活跃。

| 缩写 | 英文 | 中文职责 |
| --- | --- | --- |
| VDOC | Verification Documentation | 验证定义、规划和验证文档 |
| VENV | Verification Environment | DUT 接口连接、clock/reset、验证组件结构、构建、最小运行入口和观测点 |
| VSTIM | Verification Stimulus | 激励规则、生成、驱动、能否到达 DUT 和能否稳定复现 |
| VCHK | Verification Checking | 参考模型、scoreboard、checker 和 assertion |
| VCOV | Verification Coverage | 覆盖率模型、采集、合并和未覆盖项处理 |
| VCASE | Verification Testcase | testcase、virtual sequence 和定向运行 |
| VREG | Verification Regression | 回归策略、执行、重跑、问题分类，以及证据是否仍适用于当前版本 |

**Stage（阶段）**通常表示线性里程碑。v1 不用 Stage 0–5 控制七个工作域的执行顺序。
**Lifecycle（工作域状态）**表示工作域处在待评审、计划已批准、条件已满足或已冻结等状态；
它与单个节点是否有效是两件事。

Workstream lifecycle 的常见值：

| 状态 | 实际含义 |
| --- | --- |
| `REVIEW` | Planner 已提出目标，正在等 Human 确认 |
| `REVISE` | Human 要求修改当前目标或退出条件 |
| `ACTIVE` | 当前计划已经批准，可以继续实现和收集证据；**不表示后台有程序正在运行** |
| `SATISFIED` | 当前必需目标和自动退出检查均已满足，但尚未冻结 |
| `PARTIALLY_STALE` | Agent 已用 `changed` 登记输入修改，或 `docs sync` 发现文档 SHA-256 不同；部分结论需要重新验证 |
| `BASELINED` | Human 明确同意后，当前工作域已保存为不能覆盖的基线 |

文档问题/决定也可以使用 `ACTIVE`，此时表示“这个问题或暂定方案目前仍有效、尚未关闭”，
同样不表示正在运行任务。

<a id="desired-current"></a>
## Objective、Desired state、Current state、Exit criteria

- **Objective（总体目标）**：为什么做这项工作，例如“建立可信的输出比较”。
- **Desired state（期望状态）**：需要成立的具体条件，例如“backpressure 场景无丢失或重复比较”。
- **Current state（当前状态）**：模型中现有节点的有效性、证据和 finding；不是 Agent 的完成感受。
- **Required（必需）**：该目标必须被满足，或者由 Human 明确接受未满足，工作域才可能完成。
- **Exit criteria（退出条件）**：工作域允许进入 `SATISFIED` 的条件。模板中的文字说明供
  Human 评审；真正需要阻止流程继续的条件必须落实为 required node、依赖或自动退出检查，
  不能只写一句说明。

**Proposal（待评审方案）**是 Planner 根据模板和当前项目状态提出的候选目标；
**Draft（初稿）**是尚未经过正式评审的文档内容。二者都不能当作已批准事实。

Desired 描述结果，action 描述下一步做什么。一个 desired 可以经过多轮 action 才满足。

<a id="knowledge"></a>
## Node、Relation、Dependency、Trace、Impact

**Node（节点）**是有 ID、类型、标题和 validity 的对象，例如 requirement、desired、
文件或 evidence。**Subject/Target** 是一次证据登记或动作所针对的节点 ID。

<a id="node-role"></a>
**Node role（节点用途）**说明标准目标节点要证明什么。**Capability node（能力节点）**
证明接口规则、实现或运行工具已经准备好；**Closure-evidence node（运行证据节点）**证明该能力在
当前 revision 的真实运行中达到了目标。只有实现文件或编译成功不能替代运行证据。

**Relation/Edge（关系/边）**连接两个节点。**Dependency（依赖）**表达影响关系，
例如 RTL 行为变化会使 checker 结论需要重新验证。实际传播沿已登记的出边进行。

标准依赖落在具体节点上，不把整个工作域当成一道门。例如 VSTIM 的激励实现依赖 VENV 的
接口、组件结构和构建节点，但不要求 VENV 先冻结。VENV 的最小环境运行也不等待完整业务激励
或回归结果。具体关系见[工作流之间怎样依赖](mechanism.md#workstream-dependencies)。

**Trace（追溯）**查看节点直接连接的入边、出边、证据和发现。
**Impact（影响分析）**从指定节点开始，列出所有通过已登记关系能够到达的下游节点；
它不代表系统能够自动理解所有源代码依赖。

**REQ（需求）**描述 DUT 应有行为；**VF（验证点/Verification Feature）**将需求转为
可验证关注点；**Mode/Capability** 是处理动作所需的能力，例如仿真或 coverage 分析。
`REQ → VF → DESIRED → ACTION → ARTIFACT → EVIDENCE → REVIEW` 是建议追溯关系，
并非 CLI 自动创建且完整校验的一条固定流程。

<a id="gap-action"></a>
## Gap、Finding、Action、Closure

**Gap（未完成项）**是当前状态与必需目标之间的差距，例如一个目标仍是 UNKNOWN。
**Finding（待处理问题）**是需要跟踪并说明原因的问题，例如某次 RTL 修改使一个旧结论
不再适用。Finding 的 OPEN/RESOLVED/WAIVED 表示未处理、已解决或 Human 已接受例外。

**Action（动作）**是完成条件检查当前给出的下一步建议，包含目标、原因、优先级、executor 和
suggested mode。目标或证据改变后，这份建议会重新计算；它不等于已经运行的任务。
**Executor（建议处理者）**表示下一项工作适合交给谁：

- `deterministic`：交给按固定规则运行的脚本、编译器、仿真器或检查工具；
- `reasoning`：需要 Agent 查看与问题相关的文件、日志和已知事实，提出候选解释，结果还要验证；
- `human`：需要在当前对话中询问 Human，收到回答后才能继续。

它只是一条建议，不表示程序已启动，也不表示 Human 已经同意某个需要确认的操作。
**Suggested mode（建议工具）**是可能完成该动作的命令或能力名称，不是强制调度。

**Worker（任务进程）**是独立执行长时间任务的进程。v1 主控制流程不会自动创建隐藏 worker，
也不会让 worker 在后台等用户输入。长时间仿真可以由项目运行系统执行，但结果必须回到当前
Agent 会话，由 Agent 展示状态并登记证据。

**Closure（完成条件检查）**比较本轮目标和现有证据，列出当前还缺什么。
**Reconcile（重新计算）**是读取最新状态并更新这份未完成项列表。
`ready=true` 表示该工作域按当前规则没有剩余动作；不代表模型外没有漏验。

<a id="evidence"></a>
## Artifact、Evidence、Verdict、Digest、Provenance

**Artifact（产物）**是文档、checker、testcase 或报告等工程文件。
**Evidence（证据）**是与某个目标明确关联、且通过规定检查的结果记录。记录中会保存结果
文件路径、类型、PASS/FAIL 和 SHA-256。有一个结果文件不等于它已经证明某个目标。

<a id="evidence-source"></a>
**Raw artifact（工具原始输出）**是编译日志、仿真日志、回归清单、波形或覆盖率数据库等
工具直接生成的文件。**Native artifact（报告引用的原始文件）**是 evidence report 声明为
事实来源的项目文件；报告必须记录它的项目相对路径和 SHA-256。工具输出是 evidence 的基础，
但未经解析、关联和检查时还不能证明目标已经满足。

**Evidence extractor（结果提取程序）**或 **adapter（格式适配程序）**把仿真器、回归器和
覆盖率工具的输出转换成字段固定的 JSON 报告。当前控制面没有内置通用的 log/VDB/UCDB
解析程序，由项目工具或 adapter 生成 JSON。应优先使用工具原生 JSON、XML、JUnit 或正式
导出格式；自由文本日志解析只是兼容方案，LLM 的文字总结不能代替按固定规则提取字段的程序。

<a id="evidence-format"></a>
**Evidence schema（JSON 格式规范）**定义报告必须有哪些字段、字段类型和格式版本，例如
`CheckingEvidence/1`。**Claim（要证明的内容）**表示报告对应哪个标准节点，例如
`scoreboard-evidence`；标准 node 的 claim 由 Planner 固定，报告生产程序不能自行改成别的
内容。**Validator（自动校验程序）**检查 JSON 格式、该 claim 的规则、文件 SHA-256、项目
revision、前置依赖和相关证据是否一致，再根据检查结果生成 verdict。

**Verdict（判定）**是 pass/fail 等结论。标准 Workstream 的 `evidence` 命令由专用 validator
从报告内容推导 verdict；只有没有标准证据格式的自定义目标，才使用通用 `prove`
并接受调用方给出的结果。
VSTIM 的 **Reachability evidence（可达性证据）**由工作域自身的 probe 在 DUT 输入接受边界
记录 generated/driven/accepted/hits，并由 `reachability` 命令推导 verdict。Functional
coverage、cover property 和波形是旁证，不能单独证明 VSTIM closure。
**Digest（文件指纹）**是文件内容的 SHA-256，用于确认登记后文件是否变化；它本身不能证明
功能正确。**Provenance（来源信息）**说明信息来自哪个工具或文件、何时记录、对应哪个对象。

**Compile log（编译日志）**证明某项 capability 能否编译、挂接或注册，通常不能证明运行时
功能正确。**Simulation log（仿真日志）**记录 testcase、seed、错误数、比较、assertion 和
运行 verdict；只有提取出规定字段，并记录原始日志的 SHA-256 后，才能用于完成条件检查。

**Environment smoke（最小环境运行）**只验证环境基础：clock 有边沿，reset 完成拉起与释放，
最小测试能启动和正常结束，错误能反映到命令退出状态，并且验证侧至少产生一条观测记录。
它不证明业务激励、检查器、覆盖率或完整回归已经正确。VENV 报告中的
`environment_digest` 是当前环境实现的 SHA-256；最小环境运行与构建证据必须引用同一个值。

**Coverage database（覆盖率数据库）**是 VDB、UCDB 等仿真器生成的覆盖率数据库。VCOV
使用从数据库导出的数据库标识、合并结果、覆盖项、命中次数和排除项；只有数据库文件或
总体百分比达标，都不能直接说明 VCOV 已完成。

**Observation boundary（观测边界）**是 probe 声称看到事件发生的位置。VSTIM 默认接受
`dut-input-accepted` 或 `driver-monitor-boundary`，用来区分“generator 生成了事务”和
“事务已被 DUT 接受”。**Probe（探针）**是在该位置记录 generated、driven、accepted、hits
等固定字段计数的验证组件。

<a id="runtime-evidence"></a>
**Engagement（实际参与运行）**表示 reference model、scoreboard 或 checker 在本次运行中确实
被调用。**Comparison（比较）**是一次 expected/actual 对比；**Mismatch（不匹配）**是比较
失败；**Residual transaction（未处理完的事务）**是运行结束后仍未配对或未处理的事务。
**Assertion attempt（断言触发次数）**表示 property 的触发条件实际发生；
**Vacuity（断言未真正触发）**表示断言表面无失败，但测试并没有触发它要检查的情况，因此
不能用来证明目标完成。

常见 evidence report 字段：

| 字段/值 | 含义 |
| --- | --- |
| `schema` | JSON 报告格式及版本 |
| `claim` | 本报告要证明的固定内容 |
| `revision` | 报告对应的 bootstrap project revision |
| `tool` / `producer` | 报告生产工具、探针及版本 |
| `artifacts` | 报告引用的原始文件路径和 SHA-256 |
| `result` | Workstream 专用的观测事实 |
| `blocker` | 阻止报告 PASS 或阻止 Workstream 退出的明确原因 |
| `prerequisite` | 当前节点依赖且必须先达到 `VALID/WAIVED` 的节点 |
| `generated/driven/accepted/hits` | 场景被生成、送出、边界接受和探针命中的次数 |
| `config_digest/stimulus_digest` | 配置和激励序列的 SHA-256，用于判断两次运行是否使用相同输入 |
| `compiled/registered/bound` | 已编译、已加入执行体系、assertion 已完成 bind/elaboration |
| `clock_edges/reset_assertions/reset_deassertions` | 最小环境运行中观察到的时钟边沿数、reset 拉起和释放次数 |
| `clean_exit/failure_propagated` | 测试能正常结束；发生仿真错误时命令会返回失败状态 |
| `environment_digest` | 产生本次运行结果的验证环境实现 SHA-256，必须与当前 VENV 构建证据一致 |
| `database_ids/merge_errors/stale_shards` | coverage 数据库身份、合并错误数、过期分片数 |
| `classification/disposition` | 回归失败类别和最终处理结果 |
| `snapshot_revision` | VREG “当前版本证据”对应的项目版本 |

关系的 **origin（来源）**说明这条关系怎样进入数据库：explicit 表示 Agent 或项目工具明确登记，
inferred 表示工具根据规则推断，runtime 表示运行时建立，planner-default 表示 Planner 根据当前
目标版本和模板建立。
**Confidence（置信度）**只记录一条推断有多大把握，不能代替真实 evidence 或 Human 明确同意。
**DEPENDS_ON（依赖）**按“当前目标 → 它需要先满足的目标”保存；`closure` 只等待这个具体的
前置目标，不等待其整个 Workstream。系统会拒绝形成循环的依赖关系。
**Executable exit predicate（跨报告自动检查）**用于检查单个节点状态无法表达的关系。例如
VCHK 的运行报告所引用的 checker SHA-256 必须等于当前 checker 能力节点记录的 SHA-256。
检查失败时，`closure` 返回 `EXIT_CRITERION_BLOCKED` 并列出具体原因。

<a id="validity"></a>
## Validity、Stale、Invalidation、Revalidation

**Validity（节点状态）**属于节点：UNKNOWN 尚未证明，VALID 已登记通过证据，INVALID
失败或已知不满足，STALE 已过期，REVALIDATION_REQUIRED 需要重新验证，
REVIEW_REQUIRED 需要评审，BLOCKED 无法继续，WAIVED 已被人工豁免。

**Invalidation（把旧结论标为需要重验）**发生在 Agent 调用 `changed PATH` 登记具体输入，
或 `docs sync` 发现文档 SHA-256 与数据库记录不同之后。系统不会后台监控任意文件。STALE
只表示旧证据可能不再适用，不一定意味着设计有 bug。
**Revalidation（重新验证）**是在输入文件修改后重新运行相应检查，取得适用于新内容的证据。
**Fresh evidence（当前版本证据）**是与当前输入文件、配置和项目版本一致的证据；当前 CLI 不会持续监控并
自动重验所有证据文件。修改 VDOC 文档后要调用 `docs sync`；修改 RTL、规格或验证文件后，
Agent 要调用 `changed PATH` 明确登记。VREG 中名为 `fresh-evidence` 的节点所需检查的目标由
Planner 根据当前所有必需的运行证据节点生成，报告生产程序不能自行删减。

**Snapshot revision（快照版本）**是 `fresh-evidence` 报告声明的项目版本标识，必须与报告及当前
bootstrap revision 一致。**Stale shard（过期分片）**是与当前配置、revision 或 merge 集合
不一致的 coverage 数据分片；存在 stale shard 时 VCOV collection 不能退出。

<a id="human-gate"></a>
## Open question、Decision、Review、Waiver、Gate

文档治理把决策内容区分为四类：

- **Human Decision（人工决策）**：用户已明确批准的工程基线；Agent 可提出选项和记录回答；
- **Provisional（暂定决策）**：已有可执行方向，但保留基于日期、milestone、新 evidence
  或 closure 状态的复审触发器；
- **Assumption（待 Human Review 的假设）**：应由 Human 决定但尚未确认，不得写成事实；
- **External Open Question（外部开放问题）**：依赖项目外输入，需记录 owner、依赖、
  阻塞目标和状态。

v1 不使用 Stage gate 管理问题和决定。一般的 **Open question（待明确问题）** 可以是
缺少事实或项目含义尚未确定，例如数值容差；Agent 应按上述四类进一步归类。
**Review（评审）**对当前 desired revision 作 approve/reject/modify/clarify 判定。
批准目标与证明实现是两个步骤。

**Waiver（豁免）**是 Human 有理由接受某个目标未满足，必须记录理由和 reviewer；
它不表示验证通过。**Gate（门禁）**是必须满足条件或获得人工决定才能推进的边界。
**Fail closed** 表示条件不足时拒绝继续，例如 closure 还有动作时拒绝 freeze。
Human gate 的权限规则由 Agent/Skill 遵守；自动填入 reviewer 不等于认证该人确实批准。

<a id="triage"></a>
**Triage（失败分析）**是对回归失败逐项分类、使用相同 seed 重跑并决定怎样处理。
**Disposition（处理结果）**是 `fixed`、`rerun-pass` 或 `accepted-known-fail`；最后一种必须
引用数据库中真实的 Human `WAIVE` review。**Seed（随机种子）**标识随机测试序列，同 seed
重跑用于区分可复现失败和偶发执行问题。

<a id="baseline"></a>
## Revision、Baseline、Freeze、Sign-off

**Revision（版本）**可能指某个 Workstream 的目标版本，也可能指文档内容 SHA-256 改变后
产生的文档版本；两者都与 Git commit 编号不同。
**Baseline（基线）**是保存后不能覆盖的一份状态清单，记录目标、项目状态、证据引用和评审信息。
**Freeze（冻结）**创建该快照。Workstream freeze 封存一个工作域，final freeze 汇总
七个已冻结工作域。VDOC freeze 会保存已评审 Markdown 的版本和 SHA-256；其他输入和报告
以文件引用和 SHA-256 写入清单，不会锁定整个工作区。

**Sign-off（签核）**是负责人对验证范围、证据和剩余风险的工程认可；CLI freeze
只能提供记录支持，不能代替该判断。

<a id="authority"></a>
## Source of truth、Projection、Manifest

**Source of truth（应当编辑或信任的原始位置）**按内容划分：项目 VDOC Markdown 保存验证
设计；`model.sqlite3` 保存节点、文件 SHA-256、文档内容版本、问题/决定状态、关系、评审和
evidence；`project.json` 保存项目身份与 runtime 等配置。
**Projection（从数据库生成的阅读文件）**包括 `model.md` 和工作域 `plan.md`。
`docs render` 也能按需生成文档状态，但不会修改验证文档正文。编辑这类阅读文件不会更新数据库。
**Manifest（清单文件）**是项目身份或基线内容列表；状态变更应走 CLI，不要手工修改清单来
伪造状态。

**Golden regression（黄金回归）**要求结果只使用正式 `PASS` 或失败状态，不能用
`PASS-LIVE` 代替可复现通过。**PASS-LIVE** 表示非 golden 运行中的即时通过事实，仅用于允许
该状态的执行场景。**Targeted run（定向运行）**是为一个明确 testcase/scenario 执行的验证，
VCASE 要求每个当前已实现 case 都有绑定 test、seed 和 log digest 的定向 PASS。

<a id="dv-terms"></a>
## RTL 验证常用词

| 英文词 | 直白解释 |
| --- | --- |
| RTL | 寄存器传输级设计代码，是当前项目要验证且 Agent 不得修改的输入 |
| DUT (Design Under Test) | 被验证的设计 |
| Verification feature / VF | 从需求中拆出的一个可单独设计检查方法和收集证据的验证点 |
| Transaction | 接口上传递的一笔完整数据或操作，而不是单个时钟周期的一根信号 |
| Scenario | 希望测试的一种运行情况，例如持续 backpressure 后恢复 |
| Backpressure | 接收端暂时不接收数据，迫使发送端等待 |
| Driver | 把 transaction 转成 DUT 接口信号的验证组件 |
| Sequence | 按一定顺序产生 transaction 或场景的验证程序 |
| Constraint | 限制随机输入范围和组合关系的规则 |
| Generator | 产生 transaction、数据或场景的组件 |
| Monitor | 只观察接口并还原 transaction、不驱动 DUT 的组件 |
| Reference model | 根据输入计算预期结果的参考实现 |
| Checker | 检查实际行为是否满足某条规则的组件统称 |
| Scoreboard | 保存并配对 expected/actual transaction，再执行比较的检查组件 |
| Assertion / SVA | 对时序或协议规则进行自动检查的断言；SVA 是 SystemVerilog Assertions |
| Testcase / Test | 可独立运行、带明确目标和通过条件的一项测试 |
| Virtual sequence | 协调多个接口或多个 sequence 的高层场景控制程序 |
| Coverage model | 定义需要统计哪些功能情况是否出现的模型 |
| Coverpoint / Bin / Cross | 一个采样目标、它的取值分组，以及多个采样目标的组合 |
| Coverage hole | 计划要求但当前没有命中，或无法证明已处理的覆盖项 |
| Compile | 将 HDL/验证代码编译进仿真环境 |
| Elaboration | 解析参数、层次、bind 和连接，形成可运行的仿真实例 |
| Simulation | 使用仿真器运行 DUT 与验证环境 |
| Regression | 按清单批量运行多个 testcase/seed，并汇总结果 |
| Rerun | 重新运行原 testcase；失败分析通常要求使用同一个 seed |
| Waveform | 仿真过程中信号随时间变化的记录，主要用于定位问题 |
| UVM | SystemVerilog 验证方法库，用于组织 driver、monitor、sequence、scoreboard 和 testcase |

**Code generator（代码生成工具）**与表中的 stimulus Generator 不同：前者根据已经确认的
输入创建接口、UVM 骨架或配置文件；后者在仿真中产生 transaction 和场景。
**Runner（运行程序）**按 manifest 启动一个或多个测试；**Collector（结果收集程序）**读取
各次运行的退出状态和报告，生成汇总结果。runner/collector 成功只证明工具能工作，具体测试
是否通过仍由 evidence validator 判断。

<a id="runtime"></a>
## Runtime、Backend、MCP、Reference model

**Agent runtime** 是交互宿主 Codex/Kimi；**managed runtime** 是受管 Python/依赖环境。
**Backend（执行后端）**是承担执行或推理的具体方式，如 direct、本地/集群调度器或
Codex/Kimi。它与启动 Agent 的 runtime 不是同一个设置。
**MCP server** 向 Agent 暴露工具；configured 表示配置存在，connected 表示已连接，
tools available 表示当前会话可调用。它不因配置存在就自动运行验证。

**Reference model（参考模型）**给出预期 DUT 行为，用于比较；与保存知识和依赖的
Verification Knowledge Model 不同。**DUT** 是被验证设计；所有 RTL 与 RTL spec
均为当前 Agent 的只读输入。
