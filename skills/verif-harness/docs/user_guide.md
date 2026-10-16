# verif-harness 用户指南

本指南面向使用 verif-harness 推进具体 DUT 验证工作的负责人。正常使用时，负责人通过
Codex/Kimi 对话和 Dashboard 提供输入、审批方案、验收交付与回答工程问题；底层 CLI
主要由 Agent 调用。

项目定位见仓库 [README](../../../README.md)，状态与证据边界见
[架构说明](../../../ARCHITECTURE.md)，名词见[术语表](glossary.md)。需要查看底层入口时，
使用 [Agent/CI 命令索引](command_reference.md)，不必先记忆全部命令参数。

本文中的“负责人”对应控制协议中的 `Human` 角色。正式 schema、数据库和审计记录可以保留
`Human`、`Agent`、`Engine` 等协议名称；面向用户的状态必须写清楚“谁要对什么做什么”，
不能只显示“等待评审”“空闲”或内部状态码。

## 使用顺序

第一次使用通常按以下顺序进行：

1. 运行 **setup**，准备工具、runtime 和 Agent 工作环境。
2. 通过 Agent 完成 **bootstrap**，登记当前 DUT、只读输入和验证输出目录。
3. 先完成 **VDOC** 验证文档，再按依赖形成并执行其余工作流方案。
4. 在 Dashboard 审批方案、回答问题、验收交付；Agent 登记当前版本的验证证据。
5. 断线或故障后读取原项目状态继续，不把进程恢复误当成工作流重启。

`setup` 和 `bootstrap` 的区别是：

> setup 准备工具和 Agent；bootstrap 登记当前 DUT 和验证项目。

## 1. setup：准备工具和进入项目

### 1.1 首次 setup

从已审核的 verif-harness checkout 执行：

```text
./scripts/setup --runtime codex --workspace-root /path/to/project
# 或
./scripts/setup --runtime kimi --workspace-root /path/to/project
```

setup 会完成以下工作：

1. 在 verif-harness 自身 Git-ignored 的 `.deps/` 下准备受管 Python 和锁定依赖。
2. 安装并检查 xverif、WavePeek 等可选受管工具，但不据此声称仿真器已经验证可用。
3. 在目标 workspace 安装项目级 Skill、Agent 角色和中文交互配置。
4. 为所选 Codex 或 Kimi runtime 配置项目级 MCP。
5. 切换到 workspace；已有项目先恢复并核对 Dashboard，再启动交互 Main Agent。

项目一次只选择一个受管 runtime。`--runtime codex|kimi` 不是 Codex 与 Kimi 的混合调度配置。
setup 只证明框架和依赖已经配置；本机 CLI 探测、项目选择和端到端运行证据仍要分别检查。

常用 setup 参数：

| 参数 | 用途 |
| --- | --- |
| `--workspace-root PATH` | 指定要管理并进入的项目目录 |
| `--runtime codex\|kimi` | 选择当前项目使用的 Agent runtime |
| `--install-verilator` | 缺少 Verilator 时尝试安装；安装成功不等于项目仿真通过 |
| `--no-agent` | 只安装和配置，不启动交互 Agent，也不启动 Dashboard |
| `--interactive` | 兼容旧调用；交互启动已经是默认行为 |

### 1.2 setup 后怎样开始工作

正常 setup 会进入交互 Main Agent，并自动提交一次接续任务：

- Codex 使用 `$verif-harness`；
- Kimi 使用 `/skill:verif-harness`。

Main Agent 重新读取当前 project、revision、节点、审批、问题、Activity 和证据，再选择当前允许的
下一项动作。已有项目不会仅列出工具后等待，也不会根据旧 Dashboard 记录假装仍在执行。

Kimi 首次进入可信目录时可能显示 `Trust this folder?`，是否信任必须由负责人选择。setup 不得
代替负责人确认，也不能覆盖负责人已经在输入框中输入的文字。

### 1.3 交互 Agent 与后台接续服务

交互 Main Agent 和后台 `agent-service` 共用项目写锁，不能同时写入同一项目：

```text
verif-harness agent-service status
verif-harness agent-service start --runtime codex
verif-harness agent-service stop
verif-harness agent-service retry
```

要从后台服务切回交互模式，先执行 `stop` 并确认状态已经是 `STOPPED`，再重新运行 setup。
后台服务只处理 Closure 明确允许的动作，不会自动审批、回答负责人问题、接受例外、冻结、发布或
运行 EDA。没有新事实时不应重复执行同一动作。

Dashboard 的“Agent 工作状态”只有在当前 revision 存在受管任务并具有新鲜 heartbeat 或有效
assignment lease 时，才表示实际正在执行。工作流为 `ACTIVE`、历史 Activity 为 `RUNNING`、
服务进程存在或者浏览器仍打开，都不能单独证明 Agent 正在工作。

### 1.4 已有项目再次运行 setup

关闭终端、退出 Codex/Kimi、SSH 断线或电脑重启后，仍使用原 `--workspace-root` 重新运行 setup。
setup 会读取 `.verif-harness/` 中的项目事实继续，不需要重新 bootstrap，也不会删除审批和证据历史。

工具升级同样复用原 workspace：先受管停止 Dashboard，更新 verif-harness，再用相同 workspace
重新运行 setup。只有 bootstrap 管理的输入路径发生变化时，才进入 `bootstrap --refresh`。

## 2. bootstrap：登记当前 DUT 和项目输入

### 2.1 什么时候需要 bootstrap

以下情况需要 bootstrap：

- 该 workspace 从未建立 verif-harness 项目状态；
- `.verif-harness/project.json` 不存在，且确认不是选错项目目录；
- RTL、spec、testbench、参考模型或验证脚本等 bootstrap 输入需要变更，此时使用
  `bootstrap --refresh`。

以下情况不需要 bootstrap：

- Agent、终端或 SSH 断线；
- Dashboard 停止或浏览器关闭；
- 工具升级后继续使用同一 workspace；
- 某个工作流需要修改方案或重新启动；
- 已登记的代码或验证证据发生变化。

### 2.2 首次 bootstrap 的对话顺序

负责人在 Agent 对话中提出 bootstrap。Agent 必须一次只问一个字段；当前字段得到明确回答并完成
只读校验后，才能进入下一题：

| 顺序 | 输入 | 是否必填 | 含义 |
| --- | --- | --- | --- |
| 1 | `rtl root` | 必填 | 一个或多个只读 RTL 根目录 |
| 2 | `dut top` | 必填 | DUT 顶层模块名 |
| 3 | `dut top file` | 必填 | DUT 顶层源文件，必须位于已声明 RTL root 内 |
| 4 | `verification output root` | 必填 | 项目内保存验证资产和产物的目录 |
| 5 | `spec` | 可选 | 只读规格文件或目录；也可以明确回答“跳过” |
| 6 | `testbench` | 可选 | 一个已有 testbench 根目录 |
| 7 | `reference/golden model` | 可选 | 一个已有参考模型文件或目录 |
| 8 | `verification scripts` | 可选 | 已有编译、仿真或回归入口脚本，可提供多个 |

每个可选项也必须明确选择“提供路径”或“跳过”，不能把沉默当成跳过。Agent 不搜索候选目录，
不猜测 DUT，也不把“文件存在”解释成“已经接入”或“验证通过”。八项处理完后，Agent 汇总答案并
请负责人最后确认一次；确认前不写入项目状态。

负责人通常只需在对话中输入：

```text
$verif-harness bootstrap
# Kimi：/skill:verif-harness bootstrap
```

确认后由 Agent 调用类似下面的底层命令，负责人不需要手工拼接参数：

```text
verif-harness bootstrap \
  --rtl-root rtl \
  --docs-root specs \
  --verif-root verification \
  --testbench-root tb \
  --reference-model models/reference.py \
  --verification-script scripts/run_sim.sh \
  --dut-top dut \
  --dut-top-file rtl/dut.sv \
  --dashboard
```

### 2.3 bootstrap 写入什么

bootstrap 只登记已经明确提供的事实，并创建或更新：

- `.verif-harness/model.sqlite3`：Dashboard、CLI、节点、审批、问题和证据的唯一事实源；
- `.verif-harness/project.json` 与 `inventory.json`：项目身份和只读输入清单；
- `.harness-config.json`：项目路径和 runtime 配置；
- 项目根 `AGENTS.md` 中唯一的 verif-harness managed block；
- 验证输出根目录。

RTL、RTL spec、已有 testbench 和外部参考输入保持只读。项目状态、正式验证文档和新生成的验证资产
必须位于 project root 内。bootstrap 不生成完整 testbench，不审批验证方案，也不建立验证结论。

### 2.4 bootstrap 与 Dashboard

Main Agent 为负责人执行实时 bootstrap 时必须显式使用 `--dashboard`。只有负责人明确要求不启动时，
才使用 `--no-dashboard`；SSH、无图形界面或非交互 Agent 本身不是关闭理由。

bootstrap 完成后会为当前系统账号启动或复用 loopback Dashboard，并注册当前项目。只有 `STARTED` 和 `REUSED`
表示 Dashboard 可用；`SKIPPED`、`DISABLED`、`FAILED` 和
`PORT_CONFLICT` 都不能说成已经启动。

远端使用时，Agent 必须在当前对话逐项完整打印：实际远端端口、单跳或双跳 SSH 配置/命令，以及
包含当前 `project` 和 `token` 参数的完整浏览器 URL。Dashboard 只监听服务器的 `127.0.0.1`，
不得为方便访问而暴露到 `0.0.0.0`。

### 2.5 bootstrap --refresh

输入路径或 DUT 身份需要更新时，负责人在 Agent 对话中提出 `bootstrap --refresh`。Agent 按首次
bootstrap 的同一顺序逐题显示当前值，让负责人对当前字段选择保留、替换或移除，最后再次汇总确认。

refresh 只更新 bootstrap 管理的项目事实。已有工作流、文档、审批、问题、证据和历史不会被删除；
受输入变化影响的结论必须按依赖关系重新检查，旧审批或旧证据不能自动继承到新摘要。

## 3. 七个验证工作流

### 3.1 总体生命周期和依赖顺序

七个工作流都服务于当前 DUT，不是通用项目任务。公开工作节点必须对应接口、功能、验证点、场景、
检查机制、覆盖目标或验证证据。

总体顺序是：

```text
VDOC 文档撰写方案审批
  → Agent 撰写并同步正文
  → 负责人验收正文，Main Agent 完成检查
  → 形成当前 cap.doc
  → 负责人选择“并行形成方案”或“按依赖顺序形成方案”
  → VENV
  → VREG 回归执行器
  → VSTIM
  → VCHK
  → VCASE
  → VCOV
  → VREG 最终回归结果
```

“并行形成方案”只表示可以并行分析和提交方案；实现与交付仍然等待所需的当前 `cap.*` 能力。
选择结果绑定当前 VDOC revision 和 capability 摘要，文档能力变化后必须重新确认。

除 VDOC 外，方案与交付的公共闭环是：

1. Agent 根据当前 DUT、文档和上游能力形成方案节点。
2. 负责人对方案提出新增、删除或修改意见，或者批准当前版本全部内容。
3. 方案批准后形成不可变计划产物，并建立对应交付节点。
4. Agent 在交付节点中实现、构建、运行和分析，登记当前代码与结构化验证报告。
5. 全部必需验证通过后，负责人验收交付；验收是最后一道人工作业。
6. Engine 重新核对版本、摘要、依赖和证据，派生内部产物与能力。
7. 输入、方案、输出或证据变化时，只让受影响范围重新规划或重新验证，保留历史记录。

Dashboard 的每条工作流主页面只保留“当前项目状态”“工作节点列表”以及“添加节点”“删除节点”
“重新启动工作流”三个工作流级入口。添加和删除只登记下一版方案要求，不直接改变当前节点；重启
必须由负责人再次确认，并保存操作人、原因和新旧 revision。

### 3.2 VDOC：验证文档

#### 验证什么和公开节点

VDOC 确保当前 DUT 所需的验证文档已经先规划写法，再形成 Markdown 正文并完成内容验收。
Markdown 是唯一可编辑正文；Dashboard 只把同一份 Markdown 安全渲染成只读 HTML。

VDOC 只有两种公开节点：

- `document-writing-plan`：一份文档的撰写方案；
- `document-deliverable`：同一份文档当前 Markdown 正文的验收节点。

本轮纳入 N 份文档时，默认先建立 N 个撰写方案节点，方案全部批准后再建立 N 个正文验收节点。
固定 document catalog 只负责组织文档，不是公开节点，也不计入进度。

#### 详细工作顺序

1. Agent 根据 DUT、规格、接口、验证点、场景、检查、覆盖率和已有文档，形成只包含
   `document-writing-plan` 的 proposal。
2. Engine 检查每个节点都有明确 `document_key`、输入依据、计划内容、检查方法和交付条件。
3. 负责人逐节点审阅方案。没有待处理意见时，可以直接“批准全部内容”。
4. 所有必需撰写方案批准后，VDOC 才进入 `ACTIVE`，并形成不可变 `art.doc_plan` 版本。
5. Agent 按批准范围撰写或修改正式 Markdown 正文，然后执行 `docs sync`。
6. Agent 提交另一份只包含 `document-deliverable` 的 proposal；两类节点不得混在同一 proposal。
7. 负责人阅读 Dashboard 渲染的当前正文，提出意见或批准当前内容。
8. Main Agent 检查负责人审批、当前正文、manifest 清单和依赖影响；需要确认时建立绑定节点的
   `agent-question`。
9. 当前审批、Main Agent 检查和全部问题都完成后，形成 `art.doc`，Engine 再派生 `cap.doc`。

方案批准前，Agent 不得生成或修改正式正文、执行 `docs sync`、建立可验收正文节点或要求负责人
同时审批方案和正文。只有负责人明确要求提前试写时，才能生成显著标记的“未批准预览草稿”；它不
进入证据、正文验收、下游授权或完成度。

#### 工作节点依赖

```text
document-writing-plan 当前版本批准
  → art.doc_plan:<document_key>
  → Agent 撰写并同步正文
  → document-deliverable
  → 负责人正文审批 + Main Agent 检查 + 无开放问题
  → art.doc:<document_key>
  → cap.doc:<document_key>
  → 下游工作流方案
```

下游只能依赖当前 `cap.doc`，不能用方案批准、模板存在、目录状态或 `PROVISIONAL` 代替正文可用。

#### 反馈闭环和完成条件

负责人登记一条或多条新增、删除、修改意见后，“批准全部内容”立即禁用；“提交当前 N 条审批意见
给 Agent”一次提交本批全部意见。Agent 逐条分析并修改方案/正文，或登记无影响结论。全部意见处理
完成后，负责人重新查看当前版本并审批。新的意见形成下一批，不覆盖历史。

审批前可在节点详情查看“本版内容变化”：相对上一版同一节点变化的栏目会标为橙色，
修改、新增或删除的内容可展开与旧版对照。从节点列表直接点击“批准全部内容”时，
确认弹窗也会显示对照。首次提交没有旧版可比；版本核对失败时需刷新节点后再审批。
此对照仅比较节点定义，文档正文、代码交付和验证证据仍需通过当前受控预览及验收条件核对。

正文批准后仍可继续提意见。后续意见、正文变化、输入变化或开放问题会使旧完成结论失效，但不会
删除旧正文、审批和检查记录。VDOC 只有在当前 revision 的全部必需方案、正文验收、Main Agent
检查、问题和 Engine closure 都满足时才完成。

### 3.3 VENV：验证环境

#### 验证什么和公开节点

VENV 负责 DUT 接口连接、时钟复位、验证组件结构、构建入口、最小运行入口和观测路径。一个 DUT
工作包使用：

- `code-plan`：环境实现方案；
- `code-deliverable`：对应代码、构建和最小运行证明的交付。

#### 详细工作顺序

1. Agent 从当前 `cap.doc` 形成接口、clock/reset、harness、agent/env、构建和观测方案。
2. 负责人审阅工作范围、实现方式、验证方法、输出和交付条件。
3. 方案批准后形成 `art.code_plan`，建立相同 `implementation_key` 的交付节点。
4. Agent 只读分析 DUT，完成验证侧 interface、harness、环境结构和构建入口。
5. Agent 完成编译/elaboration 和 reset/idle 级最小 smoke，确认时钟、复位、启动、结束和观测路径。
6. Main Agent 提交覆盖全部验收条件的 `CodeValidation/1`。
7. 验证通过后由负责人验收交付；Engine 派生当前 `cap.venv`。

#### 工作节点依赖

VENV 方案依赖当前 `cap.doc`；交付依赖同工作包的 `art.code_plan`。VENV smoke 不等待完整激励、
检查器、用例、覆盖率或最终回归结果，因此不会形成 VENV 与 VREG 的循环依赖。

#### 反馈闭环和完成条件

接口或 reset 语义不清时，Agent 建立节点问题，由负责人确认后修订方案。构建或 smoke 失败时，
Agent 分析是环境实现、配置、工具入口还是 DUT 输入问题；不得修改 DUT RTL。方案范围变化需要重新
审批；仅交付代码或验证报告变化时，未变化的方案可以保留，但交付必须重新验证和验收。

只有当前方案、代码、构建/运行报告、上游能力和负责人验收全部匹配时，VENV 才形成可供下游使用的
能力。

### 3.4 VREG：回归基础设施与回归结果

#### 验证什么和公开节点

VREG 分为两条串联但职责不同的交付链：

- `regression-infrastructure-plan`：回归基础设施方案；
- `regression-infrastructure-deliverable`：回归规则和 executor 交付；
- `regression-results-plan`：一个 regression group 的结果方案；
- `regression-results-deliverable`：该 group 当前执行轮次的结果交付。

batch、case、seed、repeat 和执行轮次是节点内部受控数据，不增加公开节点。

#### 详细工作顺序

1. Agent 根据当前文档和 VENV，形成回归规则、runner/collector、submit profile 接入方案。
2. 负责人审批基础设施方案；Agent 实现并验证 `regression-policy` 和 `executor-ready`。
3. 负责人验收基础设施交付，形成 `cap.vreg:executor-ready`。
4. 对每个 regression group，Agent 形成一份结果方案。一个 group 等于一组 case 加一个 testbench
   submit profile。
5. 负责人审批 case 版本、profile 引用、seed 模式/指定值和 `repeat`。
6. testbench 工具生成 `RegressionBatchManifest/2`、caselist 并执行批准的轮次。随机模式保存每次
   实际 seed；指定模式各次使用同一 seed。
7. Agent 按 batch、case、seed、iteration 核对结果，对每个失败进行分类；失败原 seed 重跑用于
   分析，不计入计划 repeat。
8. 当前 `execution-evidence`、`triage-evidence` 和 `fresh-evidence` 全部有效后，负责人验收结果交付。

#### 工作节点依赖

基础设施交付只依赖当前文档和验证环境，不能反向等待 VSTIM、VCHK、VCASE、VCOV 或最终结果。
结果交付依赖当前 executor，以及当前有效的文档、环境、激励、检查、用例和覆盖率能力。

#### 反馈闭环和完成条件

回归失败必须与分类记录精确对应。Main Agent 判断责任属于环境、激励、检查、用例、覆盖实现、
回归基础设施还是 DUT，再向对应工作流登记重规划/重验证要求；finding 不自动修改或关闭上游节点。
已知失败只有绑定当前 VREG revision 的负责人例外批准才可接受。

“按已批准方案重新回归”只出现在结果交付节点。负责人再次确认后创建新执行轮次，并撤销旧结果作为
当前交付的验证、验收和能力；方案、基础设施和历史记录保留。若旧任务已经派发、仍在运行或中断后
状态未知，必须先核对原轮次，不能通过重新审批、重新规划或工作流重启绕过。

VREG 只有基础设施交付和全部必需结果交付都完成验收时才完成。

#### 进度怎样理解

Dashboard 的“节点完成度”按当前版本有效的必需方案审批和交付验收结论计算，不累计历史轮次。
分母包含已登记必需节点，以及已登记方案尚未建立的对应必需交付；批准方案不等于交付完成。
回归结果方案缺失、某项必需基础设施尚未关联结果范围时，整体范围不完整：卡片显示“待完善”，
仅展示已登记节点计数，不显示整体百分比，也不虚构尚未确定的 group 或公开节点。
节点计数已全部完成但仍有工作流变更等未处理动作时，显示“待处理”和具体原因，不显示整体 100%。

基础设施、回归结果的节点计数分别展示；结果交付还展示当前轮次及登记状态。同一批准方案开启
新轮次后，未变化方案和基础设施可以保留，旧结果不计入当前交付完成度。新一轮验证通过但未验收
仍不计为完成，负责人验收后才恢复。覆盖率反馈或其他输入变化使相关结论失效时，完成度可以回退。

节点完成度不是仿真执行进度或覆盖率。当前界面不推测实时 case 执行百分比；执行请求、工具调用、
实际结果、证据验证和负责人验收分别说明。按本轮 case 数乘批准 repeat 得到计划执行次数；失败原
seed 重跑只用于分析，不能增加计划完成次数。历史报告只供审计，不能并入新轮次。
VCOV 同样区分覆盖率实现与收敛：收敛方案缺失或实现范围未纳入收敛时，不显示整体百分比。

### 3.5 VSTIM：验证激励

#### 验证什么和公开节点

VSTIM 负责事务规则、激励实现、边界/并发/反压等场景，以及激励是否真正到达 DUT、能否按策略复现。
每个 DUT 工作包使用 `code-plan` 和 `code-deliverable`。

#### 详细工作顺序

1. Agent 基于当前文档和 VENV 能力形成 transaction、sequence、driver、constraint 和场景方案。
2. 负责人确认字段、握手、合法/非法输入、边界、并发、反压和随机策略。
3. 方案批准后建立交付节点；Agent 实现并构建激励组件。
4. Agent 运行场景探针，记录 stimulus producer、DUT 接收边界和实际 seed。
5. 需要确定性证明时，按批准策略复跑并比较激励事实。
6. Main Agent 提交当前代码、reachability/determinism 报告和动态分析依据。
7. 全部验证通过后由负责人验收，形成当前 `cap.vstim`。

#### 工作节点依赖

VSTIM 方案依赖 `cap.doc` 和 `cap.venv`；交付依赖自己的 `art.code_plan`。运行可达性还必须使用
当前有效的环境和回归 executor，不能用 sequence 文件存在或仿真退出码代替 DUT 已接收场景。

#### 反馈闭环和完成条件

不可达场景需要区分激励实现、环境连接、场景约束、用例配置和规格歧义。规格歧义返回 VDOC/负责人；
实现问题留在 VSTIM 修复；环境问题登记 VENV 变更要求。修改方案范围或场景集合需要重新审批，按已
批准随机策略产生新的实际 seed 不属于方案变化。

当前代码、场景范围、可达性/确定性证据和负责人验收全部有效时，VSTIM 才完成。

### 3.6 VCHK：结果检查

#### 验证什么和公开节点

VCHK 负责比较规则、参考模型接入、scoreboard/checker、assertion，以及它们在真实仿真中确实参与
检查。每个 DUT 工作包使用 `code-plan` 和 `code-deliverable`。

#### 详细工作顺序

1. Agent 基于当前文档、环境和激励形成比较、对齐、容差、异常和 reset/flush 方案。
2. 负责人确认正确结果含义、数值容差、时序/顺序、异常处理和 mismatch 策略。
3. 方案批准后，Agent 实现 reference-model adapter、scoreboard/checker 和 assertion。
4. Agent 完成构建，并使用已到达 DUT 的目标场景运行检查器。
5. 报告必须证明 checker 已启用，例如 comparison/attempt 数大于零，不能用“零失败但从未触发”通过。
6. Main Agent 提交当前代码和 typed validation；负责人最后验收交付。

#### 工作节点依赖

VCHK 方案依赖 `cap.doc`、`cap.venv` 和 `cap.vstim`；交付依赖自己的 `art.code_plan`。实际运行证据
必须使用当前环境和可达激励。参考模型或 assertion 文件存在、编译成功，都不能单独证明检查闭环。

#### 反馈闭环和完成条件

mismatch 发生后，Agent 先判断是 checker、参考模型、激励/用例、环境连接、规格歧义还是 DUT 行为。
检查实现问题在 VCHK 修复；其他问题登记到责任工作流。需要负责人决定正确行为时建立 Agent question，
不得让多个 Agent 投票代替工程决定。

当前规则、实现、engagement 证据、零未处理 mismatch、依赖和负责人验收全部有效时，VCHK 才完成。

### 3.7 VCASE：测试用例

#### 验证什么和公开节点

VCASE 负责验证点到 testcase/可执行 virtual sequence 的映射、完整 case 定义及定向运行结果。
每个 DUT 工作包使用 `code-plan` 和 `code-deliverable`。

#### 详细工作顺序

1. Agent 从当前文档、激励和检查能力形成 case matrix、优先级、组合场景和预期检查方案。
2. 负责人确认 testcase 范围、submit profile 和每个验证点的检查方式。
3. 方案批准后，Agent 实现 testcase 或可执行 virtual sequence。
4. testbench 生成 `CaseManifest/1`；完整 case 由可执行入口和 testbench 自己维护的 submit profile
   共同确定。
5. Agent 按 profile 运行定向测试，保存 case、seed、iteration、代码和证据摘要。
6. Main Agent 提交全部批准 case 的 typed validation；负责人验收交付。

增加补洞用例包时，未变化的已有用例包保留原节点版本和验收记录。新工作流范围只为
新增或修改的工作包建立新节点；原批准仍按当前代码、证据和实际依赖版本检查，不能因
新增其他用例而要求重复验收。显式重启或改变工作流目标、决策时重新审批。

#### 工作节点依赖

VCASE 依赖 `cap.doc`、`cap.venv`、`cap.vstim` 和 `cap.vchk`，不以 VCOV 完成为自身交付条件。
同一 case 绑定不同 submit profile 时形成不同 manifest/batch；verif-harness 只保存项目内路径、
profile ID 和摘要，不复制或拼装 VCS、LSF、license 或站点 wrapper 配置。

#### 反馈闭环和完成条件

定向运行失败后，Agent 按环境、激励、检查、case 实现或 DUT 行为分类，并把修改要求登记到责任工作流。
case 集合、profile、可执行入口或摘要变化后，对应运行证据必须重做。只有当前批准范围内的 case 都有
有效实现、检查和定向结果，并完成负责人验收，VCASE 才完成。

### 3.8 VCOV：覆盖率实现与收敛

#### 验证什么和公开节点

VCOV 有四种直接公开节点：

- `coverage-implementation-plan`：覆盖率实现方案；
- `coverage-implementation-deliverable`：coverage model/collection 交付；
- `coverage-convergence-plan`：覆盖率收敛方案；
- `coverage-convergence-deliverable`：覆盖率采集、缺口分析和排除结果交付。

`CoverageScope/1`、工具生成的对象清单、数据库和 hole 明细是节点内部受控数据，不增加公开节点。

#### 详细工作顺序

1. Agent 从当前 coverage plan 形成 `CoverageScope/1`：code coverage 只统计 DUT，并登记 metric 与层次范围，
   functional coverage 登记 covergroup 选择规则与必需对象类型。
2. 负责人审批采样条件、bin/cross 和稳定覆盖范围；不逐条审批 simulator 的 line、toggle、bin/cross。
3. Agent 实现 coverage model 和 collection/export，提交 `coverage-model`、
   `coverage-collection` 验证；负责人验收实现交付。
4. Agent 选择当前已验收实现能力，形成覆盖率收敛方案，并明确要使用的环境、激励、检查、用例和
   回归 executor。
5. 负责人审批收敛范围；方案只引用已批准的 VREG `regression_config`，此时不要求回归已经跑完。
   Agent 用 xverif 按当前范围、计划和模型生成 `CoverageObjectInventory/2`，再按交付阶段的实际
   VREG 执行轮次采集/合并覆盖率数据库。
6. Agent 报告必需、已覆盖、排除、未覆盖对象计数，只逐项登记 excluded/uncovered 缺口；
   全部已覆盖对象留在受控清单和数据库，不复制进 ProjectStore。
7. 存在 excluded 项时，由负责人提供一份 exclude 文件。提供动作本身表示批准该文件范围；Agent
   只检查文件、revision、节点、路径和摘要一致性，不再逐项建立 WAIVE 审批。
8. `coverage-collection-evidence` 和 `hole-analysis-evidence` 全部有效后，负责人验收收敛交付。

VDB 是否可合并由 DUT-only 构建指纹决定：DUT RTL、parameter、宏定义和 DUT 级 elaboration
必须一致，其中任何一项不同都禁止 merge。不同 testbench、不同 submit profile 或不同 DUT
实例路径不构成不兼容，因此它们在 DUT 指纹相同时可以合并；每个来源仍须独立登记 VREG
方案、执行轮次、batch、case、seed 和 iteration，merge 工具错误仍是阻塞项。
每个覆盖率收敛方案及其对应交付只处理一个 DUT 指纹分区。项目有多个 DUT 参数/宏/elaboration
变体时，工作节点列表会出现多个覆盖率收敛方案，批准后分别建立多个收敛交付；不会为每个 VDB、
case 或 seed 建立公开节点。

#### 工作节点依赖

实现方案以当前 `cap.doc` 的覆盖目标为输入。收敛交付依赖明确选择的当前覆盖实现能力，以及当前
有效的 VENV、VSTIM、VCHK、VCASE 和 `cap.vreg:executor-ready`。全部必需实现范围都必须被必需
收敛范围消费；实现交付完成不等于 VCOV 已完成。

#### 反馈闭环和完成条件

coverage hole 不能由 VCOV 自己改成“已覆盖”。Main Agent 分析责任：缺场景返回 VSTIM，缺定向
用例返回 VCASE，检查不充分返回 VCHK，采样/bin 错误留在 VCOV，规格歧义返回 VDOC/负责人。
上游完成修改和重验后，VCOV 使用新一轮当前证据重新采集和分析。

exclude 文件被替换、内容变化或节点范围变化后，文件级批准和相关收敛结论失效。只有工具清单中的所有必需对象都
命中或具有当前有效的文件级排除依据，并完成收敛交付验收，VCOV 才完成。

<a id="证据与完成判断"></a>
### 3.9 共用的反馈、证据和完成判断

Dashboard 和 Agent CLI 必须写回同一个 SQLite 问题记录。负责人可以在 Dashboard 或对话中回答，
Main Agent 读取同一答案继续；保存答案不等于恢复一个已经退出的 CLI turn。

Activity、assignment、工具 `PASS`、多个 Agent 一致或子 Agent 完成都不自动产生 `VALID`、审批、
freeze 或工作流完成。Main Agent 必须按节点合同登记当前版本的证据，再重新读取同一 project、
revision 和 digest 的状态。若 CLI 与 Dashboard 对必需节点、待办或完成状态矛盾，必须 fail closed，
先刷新或重新计算，不能挑选其中一个结论继续。

负责人通过“添加节点”或“删除节点”提出下一版范围要求；Agent 分析依赖后提交新 revision。历史节点、
文件、审批、验收和证据保留。每条工作流完成只表示当前必需节点和交付已经闭环，不代表 final freeze、
签核、仿真器支持或公开发布授权。

## 4. 断线、故障与恢复

恢复时先判断丢失的是进程、Dashboard 连接、项目注册、输入配置，还是工作流语义。不要把所有问题
都处理成重新 bootstrap 或重新启动工作流。

### 4.1 快速决策表

| 情况 | 恢复操作 | 是否需要 bootstrap |
| --- | --- | --- |
| Codex/Kimi、终端或 SSH 退出 | 使用相同 workspace 重跑 setup，读取当前状态继续 | 否 |
| 后台 Agent 失败 | 查看 status/log，停止并确认后再 retry/start | 否 |
| Dashboard 服务停止 | `dashboard --status` 后重新启动/注册 | 否 |
| 浏览器关闭或 SSH 隧道断开 | 重新打开完整 URL 或重建隧道 | 否 |
| verif-harness 工具升级 | 停止 Dashboard、更新工具、同 workspace 重跑 setup | 通常否 |
| bootstrap 管理的输入路径变化 | 逐项执行 `bootstrap --refresh` | 是，refresh |
| 项目从未初始化或状态确实不存在 | 首次 bootstrap | 是 |
| 当前方案范围需要重做 | 添加/删除节点，或负责人确认“重新启动工作流” | 否 |
| 回归或外部 EDA 任务状态未知 | 先核对调度器、日志、manifest 和原执行轮次 | 否 |

### 4.2 Agent 中断

交互会话中断后重新运行 setup。Main Agent 必须读取 `status`、`closure`、开放问题、审批意见批次、
Activity 和实际外部任务状态，再决定下一步。不能把历史 `RUNNING` 直接当成当前执行。

后台服务失败时：

1. `agent-service status` 查看状态；
2. 检查 `.verif-harness/agent-service/` 中的运行日志；
3. `agent-service stop` 并等待确认停止；
4. 对可安全重试的失败执行 `retry`，再执行 `start`。

如果 Dashboard 已保存负责人答案，但 Kimi/Codex 已回到普通输入提示符，旧 turn 不会自动恢复。
负责人发起新的“继续”消息，Main Agent 读取已持久化答案后继续；不得创建重复问题或假装旧进程仍在等。

### 4.3 Dashboard 恢复

```text
verif-harness dashboard --status
verif-harness dashboard
verif-harness dashboard --open-browser
verif-harness dashboard --stop
```

`dashboard --stop` 只注销当前项目；同一账号仍有其他项目时共享服务继续运行，最后一个项目注销后才
停止。它不删除项目文件、SQLite、文档、审批和证据。重新运行 `dashboard` 会注册/复用服务，不需要
重新 bootstrap。

Dashboard 可用必须同时核对：服务进程、实际监听端口、当前项目注册和授权请求。SSH 隧道存在不
代表远端服务可访问；Dashboard 服务存在也不代表当前项目已经注册。

<a id="从本地浏览器访问远端-dashboard"></a>
#### 从本地浏览器访问远端 Dashboard

Dashboard 始终监听远端服务器的 loopback 地址。远端先运行 `dashboard --status`，必要时运行
`dashboard` 恢复服务，再在本地建立 SSH `LocalForward`。转发右侧端口必须使用当前返回的实际
远端端口，不应假定一定是 8765。

本地用 `/healthz` 确认隧道确实到达远端服务，然后打开 CLI 返回的完整 URL。URL 中的 `project`
和 `token` 都必须保留；403 时重新取得当前完整 URL，不复制其他账号的 token，也不把服务改为
监听 `0.0.0.0`。详细故障分类见[故障排查](troubleshooting.md#dashboard-无法从本地浏览器打开)。

### 4.4 工具升级

工具升级的推荐顺序是：

1. 在当前项目执行受管 `dashboard --stop`；
2. 更新 verif-harness checkout；
3. 使用原 runtime、原 `--workspace-root` 重新运行 setup；
4. 检查 Dashboard 注册、项目选择、revision 和 pending actions；
5. 从 Closure 当前允许的动作继续。

不要仅因为升级工具而执行 bootstrap、重启 VDOC 或清空 `.verif-harness/`。只有输入路径或 DUT 身份
变化时才使用 `bootstrap --refresh`。

### 4.5 工作流重新启动不是进程恢复

“重新启动工作流”只在负责人希望放弃当前生命周期版本、让 Agent 重新形成方案时使用。它需要二次
确认，并记录操作人、原因和新旧 revision。旧审批不继承到新版本，但文件、节点、证据、审批、验收
和问题历史都保留。

它不会重启 Dashboard、CLI、Agent runtime、SSH、仿真器或调度器。Agent/浏览器断线、工具升级、
Dashboard 故障和外部任务状态未知都不能用工作流重启绕过。

### 4.6 外部仿真或回归中断

对已经派发、已经登记工具调用或中断后状态未知的任务，先检查实际调度器状态、日志是否完整、输出
manifest、batch/seed/iteration 和 Activity。只有确认原任务已结束、失败或不可恢复后，才能按当前
节点合同决定重试、重新验证或由负责人发起新的回归轮次。

失效方案下的旧任务即使后来结束，也只能解除“状态未知”，不能自动生成当前可验收交付、能力或新的
执行授权。

## 5. 命令参考：保留最小命令地图

用户指南需要一份最小命令地图，但不需要把所有底层参数放在正文。正常负责人通过自然语言和 Dashboard
操作；Agent/CI 使用 CLI，并以当前 checkout 的 `--help` 为准。

### 5.1 负责人常见入口

| 目标 | 入口 |
| --- | --- |
| 安装、升级后恢复、重新进入项目 | `./scripts/setup ...` |
| 首次登记 DUT | 在 Agent 对话中提出 `bootstrap` |
| 更新 bootstrap 输入 | 在 Agent 对话中提出 `bootstrap --refresh` |
| 查看负责人待办 | Dashboard“需要你处理” |
| 审批方案或验收交付 | 对应工作节点详情 |
| 回答工程问题 | Dashboard 或当前 Main Agent 对话 |
| 恢复 Dashboard | `verif-harness dashboard --status` / `dashboard` |
| 查看后台 Agent | `verif-harness agent-service status` |

### 5.2 Agent/CI 常用只读入口

```text
verif-harness status
verif-harness closure
verif-harness inspect NODE
verif-harness trace NODE
verif-harness impact NODE
verif-harness doctor
verif-harness runtime status
```

写入类命令必须遵守当前 revision、摘要、审批和证据合同，不能把 CLI 的默认值当作负责人决定。
完整命令分组、调用者和风险边界见 [Agent/CI 命令索引](command_reference.md)。精确参数使用：

```text
verif-harness --help
verif-harness COMMAND --help
```

## 6. 状态、文件与治理边界

项目状态数据库和 `ProjectStore` 是 Dashboard、CLI、工作流、工作节点、问题、Activity、审批和证据的
唯一事实源。`model.md`、`plan.md`、Dashboard snapshot 和事件流只是投影，不能单独推进状态。
Dashboard 事件流以数据库事务版本识别审批、Agent 问题、节点和证据变化，之后重读
当前项目快照；不把文件时间戳或事件本身当成权威状态。因此在远程或共享文件系统上，
新的负责人待办和 Agent 问题也应无需手动刷新即可显示。
仅更新时间戳的 Agent heartbeat 不使快照失效；Activity 进度、任务状态、审批、问题、
证据和租约失效等可见变化仍会触发重读。首次打开或已有页面遇到连续写入、暂时无法得到
稳定版本时，页面显示“连接正常 · 状态同步重试中”；事件流保持连接并自动重读，稳定后
应用最新快照。负责人不需要刷新浏览器或重复提交审批；若连接真正中断，页面才显示最后
一次已确认的状态。写操作已保存但整页状态暂未稳定时，页面保留保存回执并继续自动同步，
不得把状态刷新失败解释为写入失败。

```text
.verif-harness/
├── model.sqlite3
├── project.json
├── inventory.json
├── dashboard-runtime.json
├── agent-service/
└── workstreams/

<verif-root>/docs/verification/
└── *.md                      # 正式验证文档的 Markdown 事实源
```

不要直接编辑数据库投影来改变状态。文档变化由 Agent 执行 `docs sync`，验证代码或输入变化通过受控
入口登记，结构化报告按节点合同进入 evidence/code validation。旧记录保留供审计，但只有当前
project、revision、definition/document digest 和依赖一致的证据才能支持当前结论。

`ACTIVE`、`PROVISIONAL`、dry-run、clean audit、Activity 完成、子 Agent 完成或
`READY_FOR_HUMAN_REVIEW` 都不等于验证闭环、freeze、签核、仿真器支持或公开发布授权。
