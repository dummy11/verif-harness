# verif-harness v1 用户指南

本文只讲安装和操作。项目定位、适用对象与治理理念见仓库
[README](../../../README.md)，内部边界见[架构说明](../../../ARCHITECTURE.md)。
理解一次操作如何推动状态变化，请先读[工作机制](mechanism.md)；不熟悉的名词可查
[术语表](glossary.md)。

## 面向用户的用词

本指南在解释控制协议时保留 `Human`、`Agent`、`Engine` 等正式角色名；其中 `Human`
就是对验证范围、工程取舍和评审结论负责的人。Dashboard、CLI 的可读信息以及 Agent
直接向用户提问时，不应把这些协议名当作主要界面文字：统一称“你”或“负责人”，并写清
需要对哪个 DUT、工作流、节点或验证文档执行什么操作。例如显示“等待负责人审批文档撰写方案”，
而不是“等待计划评审”；显示“验证文档”“正文内容”，而不是“语义文档集”“语义交付”。
命令名、JSON/schema 字段、数据库状态码和审计记录可以保留内部名称，但必须与可理解的说明
一起出现。

## 1. 两种入口

### 1.1 在 Agent 会话中使用（推荐）

[setup 和 workspace](glossary.md#project-setup) 准备完成后，setup 会自动切换到指定 workspace，
并启动选定的
[Agent](glossary.md#control-plane)，无需再次手动启动。进入会话后，[Human（用户）](glossary.md#control-plane)只需激活
[Skill](glossary.md#control-plane) 并用自然语言说明目标：

- Codex：对话中输入 `$verif-harness`，再说明目标；
- Kimi：对话中输入 `/skill:verif-harness`，再说明目标。

Human 不需要直接运行 `verif-harness plan/review/evidence/freeze` 等底层命令，也不需要记忆
它们的参数。Skill 激活后，Agent 先读取当前状态、提出需要 Human 回答的问题；Human
通过对话给出目标、工程决定或审批结论；Agent 再自行调用底层
[CLI](glossary.md#control-plane)，将结果保存到
[Verification Knowledge Model](glossary.md#subsystems)。标准交互关系是：

```text
Human：激活 Skill，并用自然语言说明目标
  ↓
Agent：读取状态，调用 CLI，生成待评审方案或文档初稿
  ↓
Human：回答问题，作出 approve/modify/clarify/reject 等决定
  ↓
Agent：根据明确回答继续调用 CLI 并报告结果
```

首次使用时，Human 可输入“`$verif-harness 为当前项目开始验证治理`”（Codex）或
“`/skill:verif-harness 为当前项目开始验证治理`”（Kimi）。Agent 发现项目尚未
bootstrap 后，会询问必填 [DUT 信息](glossary.md#project-setup)，并自行调用
[`bootstrap`](glossary.md#project-setup) 建立项目知识模型。
只有传入 `--no-agent` 时 setup 才跳过启动；之后重新运行不带该参数的 setup 即可进入会话。

例如：“`$verif-harness 规划 VDOC，并只询问模型无法确定的决策`”。Agent 会读取
Skill 约束，再调用项目级 CLI。[Human review、waiver](glossary.md#human-gate) 和
[freeze](glossary.md#baseline) 必须由用户明确要求，
Agent 不得自行批准。

### 1.2 底层 CLI（Agent/CI 接口）

下文命令统一写成：

```text
verif-harness COMMAND
```

它代表 setup 创建的 Skill launcher：

```text
# Codex workspace
.agents/skills/verif-harness/scripts/verif-harness COMMAND

# Kimi workspace
.kimi-code/skills/verif-harness/scripts/verif-harness COMMAND
```

在 verif-harness 源码仓内开发时也可以运行：

```text
scripts/managed-python scripts/verif_harness.py COMMAND
```

CLI 输出字段固定的 JSON，便于 Agent 和 CI 读取；负责人通常只需关注 `status`、`actions`、
`questions_for_human`、`findings`、`evidence` 与 `baseline`。用户指南保留命令块是为了
解释 Agent 实际执行了什么，以及方便 CI/高级诊断；它们不是要求 Human 在正常对话流程中
手工输入。Human 也可以在终端直接调用 CLI，但直接调用表示调用者自行承担参数、项目范围
和操作责任，不能让 Agent 把 CLI 的默认值当作 Human 决定。

## 2. 安装、runtime、依赖与 MCP

本节涉及的 [runtime、backend 和 MCP](glossary.md#runtime) 含义见术语表。

从已审核的 verif-harness [checkout（Git 工作副本）](glossary.md#project-setup)执行一次：

```text
./scripts/setup --runtime codex --workspace-root /path/to/project
# 或
./scripts/setup --runtime kimi --workspace-root /path/to/project
```

setup 会：

1. 在 verif-harness 自身的 `.deps/` 下建立受管 Python 环境；
2. 安装并校验 Python、xverif、WavePeek 等锁定依赖；
3. 向目标 workspace 安装项目级 Skill 链接与中文响应配置；
4. 为选定的 Codex/Kimi runtime 配置项目级 xverif MCP；
5. 切换到 workspace 后启动选定 Agent。

[`runtime`、`dependency`、`backend`](glossary.md#runtime) 是三个不同概念：

| 概念 | 含义 |
| --- | --- |
| Agent runtime | 当前交互宿主：Codex 或 Kimi |
| managed dependency runtime | verif-harness 管理的 Python 与隔离依赖，位于 Git-ignored `.deps/` |
| execution backend | xverif 的 direct/调度器执行方式，或 Verification Reasoning Engine 选择的 Codex/Kimi/Claude 推理后端 |

setup 参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--workspace-root PATH` | verif-harness 源码根目录 | 要管理并启动 Agent 的项目目录；旧拼写 `--project-root` 仍兼容 |
| `--runtime codex\|kimi` | `auto` | 选择 Agent；两者同时安装且要启动时必须明确选择 |
| `--install-verilator` | 关闭 | 缺少 Verilator 时尝试通过 Homebrew/apt 安装 |
| `--isolation managed` | `managed` | 依赖隔离实现；当前只支持 managed |
| `--no-agent` | 关闭 | 只安装/配置，不启动 Agent |

setup 已经知道 workspace 和 runtime，所以后续在项目根目录执行 CLI 时不需要重复传
`--project-root` 或 `--runtime`。xverif MCP 注册也由 setup 完成；Agent 刚启动、MCP
握手尚未结束时可能显示 `configured, connection pending`，不能据此判断未安装。

只读确认：

```text
verif-harness runtime status
verif-harness xverif mcp status --project-root .
verif-harness doctor
```

### 2.1 一个 runtime 下的多 Agent 协作

setup 会为选定 runtime 安装三种项目级执行角色：只读探索、限定范围实现和独立只读复核。
Codex 从 `.codex/agents/` 发现角色，Kimi 从 `.kimi-code/agents/` 发现角色。项目始终只选择
一个 runtime；不会由 Codex 再启动 Kimi，或反向启动。

```text
Human
  ↕
Project Main Agent（唯一交互入口和控制面写者）
  ├─ verification-explorer（只读）
  ├─ verification-worker（限定 write scope）
  └─ verification-reviewer（只读）
          ↓
      结果返回 Main Agent，由 Main 复核并登记
```

Main Agent 先从当前 Closure Engine 结果中读取可分派动作，再建立绑定当前节点定义和计划版本的
assignment。领取操作会原子创建 Activity，因此不需要为同一 child 再执行一次 `activity start`。
租约用于发现丢失的同步和阻止重复领取；runtime 自己仍负责 subagent 的线程、上下文与结果返回。

subagent 不直接向 Human 提问，也不执行 review、waiver、freeze 或 evidence 登记。缺少工程输入时，
它只向 Main Agent 返回 `NEEDS_HUMAN`；Main 先尝试内部协调，确实需要 Human 时再统一登记
`agent-question`。Dashboard 会显示每个 subagent 的节点、角色、状态和 heartbeat，但没有直接回复
subagent 的入口。assignment 完成、多个 Agent 达成一致或命令成功都不等于 evidence/PASS。

## 3. 从空项目到保存最终基线（final freeze）

下面是第一次使用时最容易理解的顺序，不是强制流水线。任何 Workstream 都可以并行、
跳转、修订或重新打开。

### 步骤 0：建立项目模型

这一步就是[Bootstrap](glossary.md#project-setup)：登记用户明确提供的 RTL/DUT/spec 路径，
创建项目状态库和 `AGENTS.md` 说明，不生成完整 testbench。

setup 已自动进入 workspace 并启动 Agent。在会话中发起 bootstrap：

```text
# Human：在 Codex/Kimi 对话中输入；这不是 shell 命令
$verif-harness bootstrap
# Kimi 使用 /skill:verif-harness bootstrap
```

Agent 必须通过对话要求用户明确提供以下输入，不搜索候选目录、不猜测或自行选择 DUT。问题按表中
顺序进行，一次只问一个字段；Human 回答且只读校验通过后，Agent 才进入下一题：

| 顺序 | 对话输入 | 是否必填 | 含义 |
| --- | --- | --- | --- |
| 1 | `rtl root` | 必填 | RTL 根目录；可以明确提供多个 |
| 2 | `dut top` | 必填 | DUT 顶层模块名 |
| 3 | `dut top file` | 必填 | DUT 顶层源文件路径 |
| 4 | `verification output root` | 必填 | 项目内保存验证资产和产物的目录 |
| 5 | `spec` | 可选 | RTL 规格文件或目录；可以明确回答“跳过” |
| 6 | `testbench` | 可选 | 一个已有 testbench 根目录；不再分别填写 UVM、testcase、assertion 或 coverage 路径 |
| 7 | `reference/golden model` | 可选 | 一个已有参考模型文件或目录；登记不表示决定采用该模型 |
| 8 | `verification scripts` | 可选 | 已有编译、仿真或回归入口脚本；可以提供多个，也可以明确回答“跳过” |

每个可选项也必须得到明确的“提供路径”或“跳过”回答，不能把沉默当成跳过。本次对话已经明确
提供的字段视为已回答，不重复询问；输入不合法时停留在当前题，修正后再继续。全部八项完成后，
Agent 汇总所有答案，请 Human 最后确认一次；确认前不执行初始化。底层 CLI 仍是非交互参数接口，
顺序问答由 Agent 负责。以下是 Agent 最终确认后的执行示例，
用户无需手动拼接参数；可选 spec 使用现有 `--docs-root` 接口传入：

```text
# Agent：根据 Human 已明确提供的信息调用 CLI；Human 无需手工拼接参数
verif-harness bootstrap \
  --rtl-root rtl --docs-root docs --verif-root verification \
  --testbench-root tb --reference-model models/reference.py \
  --verification-script scripts/run_sim.sh \
  --dut-top dut --dut-top-file rtl/dut.sv
```

上例中的三个验证输入只是示例；没有现成资产时全部省略。bootstrap 只登记并只读检查这些路径，
不执行、不修改，也不把文件存在当成已经接入或通过验证。提供 testbench 根目录后，Agent 在后续
工作流中按需识别其中的环境、testcase、assertion 和 coverage 内容；Human 不需要逐类填写路径。

RTL root、DUT top file、spec、已有 testbench、参考模型和验证脚本不要求位于 workspace/project root；用户显式给出的项目外
路径会以绝对路径记录。DUT top file 必须位于至少一个已声明 RTL root 内。这些路径名的
含义见[项目路径和启动相关词](glossary.md#project-setup)。
`verif-root`、`.verif-harness/`、`AGENTS.md` 和所有生成产物则必须留在 project root 内。
因此可以让独立 verification workspace 引用另一个 RTL 仓库，而不会把 RTL 复制进来。

所有 RTL 和 RTL spec 均为当前 Agent 的只读输入，不允许编辑、生成覆盖、删除、移动或
格式化，也不得通过工具间接更改。发现输入问题时报告用户处理；验证产物必须放在独立路径。
bootstrap 同时创建或增量更新项目根目录 `AGENTS.md` 的 verif-harness managed block，
写入 DUT 身份、哪些文件只读、Human/Agent/Engine 的分工，以及“验证文档未就绪时先返回
VDOC”的规则。已有项目说明保留在 verif-harness 标记之外，不会被覆盖。该区块还说明：
验证设计写在 Markdown，文件版本、评审和证据状态保存在 SQLite。初始化后可用 `status`
和 `doctor` 检查项目状态。

bootstrap 成功后，交互式 Codex/Kimi/Claude 或终端会默认在 `127.0.0.1` 上为当前系统账号启动
（或复用）后台 Dashboard，bootstrap 自身随即返回，不会被 Web 服务阻塞。自动端口从 `8765`
开始选择；同机其他系统账号已经运行的 Dashboard 会被识别并跳过，不会跨账号复用。Agent 为 Human
执行实时 bootstrap
时必须显式使用 `--dashboard`，避免运行入口差异使 Dashboard 被跳过。只有 Human 在当前对话中明确
要求关闭时，Agent 才能使用 `--no-dashboard`；SSH、无图形界面或非交互执行都不是关闭理由。
本机桌面环境会尝试打开浏览器；SSH 远端不会启动远端浏览器，而会在成功结果中给出使用实际端口的
单跳命令、双跳 `~/.ssh/config` 模板、连接命令和浏览器地址。CI 可以省略两个选项并使用默认跳过
策略。同一系统账号的第一个项目启动共享 Dashboard，后续项目只注册自己的项目入口并复用同一服务。
项目选择器只是请求路由：每个项目仍只读写自己项目目录内的 SQLite、文档、节点、问题、审批和证据，
不存在跨项目汇总、依赖或状态传播。显式指定端口时不会自动改用其他端口；该端口属于其他账号、
非 verif-harness 服务或旧版 Dashboard 时会报告 `PORT_CONFLICT`。自动选择会跳过已占用、旧版或
其他账号的端口，在 `skipped_ports` 中说明原因；只有整个自动范围耗尽时才报告冲突。Agent 必须检查
返回的 `dashboard.status`；
只有 `STARTED` 和 `REUSED` 表示 Dashboard 可用，不能把 `SKIPPED`、`DISABLED`、`FAILED` 或
`PORT_CONFLICT` 说成已经启动。

路径填错或项目输入发生变化时，Human 只需在对话中输入 `bootstrap --refresh`。这不是让 CLI
静默沿用旧路径：Agent 按首次 bootstrap 的相同顺序逐题显示当前值，每次只让 Human 对当前字段
选择保留、替换或移除；全部问题回答后再汇总确认。确认后，Agent 才使用完整参数调用底层 CLI。刷新会同步
`project.json`、`inventory.json`、`AGENTS.md` 和 `.harness-config.json` 中由 bootstrap 管理的
路径字段；已有 Workstream、证据、评审和文档治理状态保持不变。

这一步的角色边界是：

- **Human**：明确提供 workspace、RTL root、DUT top、DUT top file，以及可选 spec、testbench、
  参考模型和验证脚本；决定输入错误
  应如何处理。Human 不需要手工创建 SQLite 或 `AGENTS.md`。
- **Agent**：在当前对话收集必填信息，只读检查路径和 DUT 身份，然后调用 `bootstrap`；不得搜索
  候选 DUT，也不得修改 RTL 或 RTL spec。
- **Engine**：检查参数和路径约束，创建项目状态库、工作目录及 `AGENTS.md` managed block；只保存
  已明确提供的项目事实，不猜测 DUT 含义。

### 步骤 1：确定 VDOC 本轮要完成的文档目标

```text
# Agent：调用 CLI 建立并查看 VDOC 待评审方案；Human 无需手工输入
verif-harness plan VDOC
verif-harness status VDOC
```

Verification Planner 读取 VDOC 通用模板、项目已经登记的信息和现有文件，生成一份
[待评审方案](glossary.md#desired-current)和 `questions_for_human`。方案会列出本轮要完成的
文档、每份文档需要达到什么状态、哪些问题必须由 Human 回答。Agent 在当前会话解释这些
问题并收集回答；CLI 不会自己理解规格含义。需要修改方案时再次运行 `plan VDOC`，创建新版本。

Agent 展示 proposal 后，Human 在对话中明确表达评审结论，例如：

```text
# Human：在当前 Agent 对话中表达；这不是 CLI 命令
批准当前 VDOC 范围。
```

Agent 收到 Human 的明确同意后，才自行执行底层命令并保存结论：

```text
# Agent：仅在收到上面的 Human 明确同意后调用 CLI
verif-harness review VDOC --verdict approve
```

当且仅当只有一个 Workstream 等待评审时，Agent 才可以在底层调用中省略目标；默认
verdict 是 `approve`，reviewer 从 `git user.name` 推导。CLI 默认值不代表 Human 已经同意，
Agent 仍必须先取得明确结论。Human 拒绝或要求修改时，在对话中说明原因；例如 Human 说
“需要修改，接口 reset 语义仍不清楚”，Agent 转换为：

```text
# Agent：把 Human 在对话中的“修改”结论转换为 CLI 调用
verif-harness review VDOC --verdict modify --reason "接口 reset 语义仍不清楚"
```

### VDOC 正式文档产出

默认 `plan VDOC` 登记八份正式文档目录。它们是输出路径、维护责任和依赖锚点的内部固定分类，不是八个固定的
实施方案节点，也不计入工作节点数量。Agent 必须同时根据当前 DUT、规格和验证目标形成
`DesiredStateProposal/1`：例如某个接口范围、功能验证策略或尚待确认的错误响应决定。Engine 在
独立验证文档目录中创建缺失模板，并登记文件路径、SHA-256 和目标关系，但绝不覆盖已有文档。
初始 proposal 只能包含文档撰写方案；负责人批准所有必需方案后，Agent 才结合只读输入和用户对话
完成正式正文、同步版本并另行登记正文验收节点。模板创建不表示内容已完成或批准。

| 正式文档 | 内容 | 后续维护 |
| --- | --- | --- |
| `verification_workflow.md` | 文档修改规则、角色分工、哪些操作需要 Human 同意、决策分类、评审和重新建立基线 | VDOC |
| `verification_plan.md` | 范围、总体策略、风险和验收条件 | VDOC，面向整个验证工程 |
| `feature_matrix.md` | 验证点、来源、场景与检查/覆盖/用例映射 | 全部工作域 |
| `tb_architecture.md` | 接口、组件分层、数据流、构建与诊断 | VENV/VSTIM/VCHK/VREG |
| `reference_model_spec.md` | 验证侧模型接入、支持范围、比较规则或替代方案 | VCHK |
| `coverage_plan.md` | 采样、[bin/cross](glossary.md#dv-terms)、可达条件和完成标准 | VCOV |
| `assertion_plan.md` | [assertion/property](glossary.md#dv-terms)、挂接、失败处理和必须真正触发的要求 | VCHK/VCOV |
| `testcase_list.md` | 用例目标、优先级、检查方式、实现与证据映射 | VCASE/VREG |

`code_coverage_waiver_manifest.md` 仅出现具体豁免候选时按需建立，由 VCOV 维护，
不是初始 VDOC 的必需产物。所有模板见[VDOC 产出与模板索引](../vplan/vdoc.md)。

“一份文档一个分类”只适合作为 VDOC 的交付目录，不表示一份文档就是一个实施方案节点。
Dashboard 的文档交付分类还会展示正文版本、内容是否变化、开放问题、工程决定和评审记录。
真正需要审批的 VDOC 方案节点来自当前 DUT 的文档工作分解，因此可能少于、等于或多于八个。
VDOC 对外只有两种节点类型：`document-writing-plan`（文档撰写方案）和
`document-deliverable`（文档交付）。两者都必须用 `document_key` 明确归属一份文档；一份文档可以有多个方案节点和多个交付节点。方案节点描述准备怎样写，交付节点描述已经写出的、可独立验收的正文语义，二者不能复用同一内容模板。目标与范围、计划写入内容、待确认工程决定、输入依据、
交付对象及依赖影响都是撰写方案节点内部可独立审批的区块，不再拆成其他节点类型。
两种节点按阶段登记，不能出现在同一个 proposal 或同一次审批请求中。方案批准前不得编写或修改正式
正文、执行 `docs sync` 或创建交付节点。方案全部批准、VDOC 进入 `ACTIVE` 后，Agent 才编写正文并
提交单独的 delivery-only proposal；每个必需撰写方案此时至少要有一个必需文档交付后代，每个必需
交付节点也必须可回溯到同一文档的必需撰写方案。只有用户明确要求时才可提前提供预览草稿；预览不得
同步、作为证据或登记为交付节点。
文档交付节点支持“暂定接受”，但必须填写责任人和重新评审触发条件。暂定内容允许下游带风险开始工作，
不计入文档通过、工作域完成或最终冻结；暂定语义变化后，依赖它的工作必须重新检查。
工程语义继续写在 Markdown 正文中，不复制到 SQLite，也不会为每个标题或段落建立节点。只有需要
Human 明确回答、决定或持续跟踪的事项才使用 `docs track`；这些事项未处理时会计入“需要你处理”。

#### VDOC 怎样迭代并收敛

VDOC 不是一次审批后直接完成，而是按当前版本反复执行以下闭环：Agent 先根据 DUT、规格和 Human
意见提出纯方案 proposal；Engine 校验节点结构与文档映射并登记工作流 revision 和节点定义摘要；
Human 审批撰写方案区块。全部方案通过后，Agent 才完成正文、同步摘要并登记纯交付 proposal，Human
再验收交付节点语义。Human 要求修改、说明或拒绝，
或者 DUT、规格、节点定义、文档正文发生变化时，Agent 重新分析并提交下一版本，Engine 使不再匹配
当前摘要的旧审批失效，Human 再评审新版本。Human 已批准且输入和内容没有变化时，Agent 不会为了
制造新版本而无条件再迭代；Dashboard 也不会在后台自行启动 Agent。

当前 VDOC 只有同时满足以下条件才算收敛：所有必需文档撰写方案节点的必需区块均已批准；所有必需
文档交付节点均针对当前节点定义和当前正文批准；一份文档的全部必需语义验收内容已由其多个交付
节点覆盖；Human 确认项、修改/说明请求、阻塞问题和开放工程决定均已关闭；没有暂定、过期、内容
已变化或等待复审的必需节点与文档；Engine 的当前 closure 检查通过。`PROVISIONAL` 只允许下游带
风险推进，不计入收敛或冻结。完整规范见
[VDOC Human-Agent-Engine 评审闭环与收敛条件](../vplan/vdoc.md#human-agent-engine-review-loop-and-convergence)。

Dashboard 的 VDOC 工作流页只展示这套规则的当前投影：当前 revision、当前轮到 Human、Agent 还是
Engine、触发重新评审的原因，以及各项收敛条件是否满足。规范事实源仍是上面的 VDOC 文档；页面
状态不能替代版本化规则或 Human 的工程判断。

`verification_workflow.md` 只借鉴既有项目中可复用的文档优先、Human review、决策分类、
变更影响和交叉文档同步机制。v1 不生成或引用 Stage 0–5、Spec Kit `spec/plan/tasks`、
Stage gate review packet 或后台 task runner；现在由 Workstream 目标、SQLite 状态、`check`、
`closure` 和 Human freeze 完成相应检查。

VDOC 规划时，Agent 将对话确认的输出目录通过内部参数 `--document-root` 传给 CLI；Engine
随后创建缺失模板、登记 SQLite 文档索引，并补全同一个 `AGENTS.md` managed block 中的
八份文档与目标之间的对应关系。Human 无需手工输入该参数。
如果某项[能力节点](glossary.md#node-role)依赖的文档尚不存在或未经评审，Agent 必须先返回
VDOC 处理文档，不能自行猜测项目含义后继续实现。

`.verif-harness/workstreams/vdoc/plan.md` 表达“本轮准备完成哪些文档目标”，上表文件
承载实际验证设计，不能相互替代。输出目录优先沿用项目验证文档布局，否则采用
`<verif-root>/docs/verification`；与 RTL/spec 输入重叠时必须选择独立位置。
验证侧 `reference_model_spec.md` 的命名不会使同名原始 spec 变成可写文件。

VDOC 先形成可讨论的初稿，允许其他工作域在其尚未全部完成时推进。Markdown 正文保存范围、
架构、比较规则、coverage/test/assertion 等验证设计。SQLite 保存文件指纹、文档内容版本、
待处理问题和决定的状态、评审记录、证据关联，以及哪些结论需要重新检查。用户需要查看这些
状态时运行 `docs status/render`；Revision Log、Review Trace 和 Human Review Notes 不会反复
写进正文。

Engine 将每份输出的文件和 document node 关联对应 desired 节点。正文修改后使用
`docs sync` 计算新文件指纹、增加文档内容版本，并把依赖该文档的结论标为需要重新验证。
计划批准不等于
文档内容批准；文件存在、模板已复制也不等于目标通过。Human 确认正文后，Agent 使用
`docs review` 记录这次评审对应的文件 SHA-256，避免正文再次修改后沿用旧评审。
`--desired` 自定义目标仍替代默认八项，需要 Agent 显式关联实际文档。

### VDOC 完整执行步骤与角色

先用一个具体场景说明三种角色。假设 `verification_plan.md` 需要决定 latency 是否属于
正确性要求：Human 根据项目目标作决定；Agent 读取只读规格和 RTL、说明影响并修改验证文档；
Engine 在 Agent 调用 `docs sync` 后记录文件的新 SHA-256，把依赖旧内容的结论标为需要重验，
并在 `closure` 中列出未完成项。Engine 不会自己判断 latency 应不应该纳入正确性。

下表中的角色都遵循这个分工：

- **Human**：决定验证范围和工程取舍，批准具体文档，决定是否接受例外，以及是否冻结当前版本；
- **Agent**：当前 Codex/Kimi 会话。它读取项目、提出问题、起草验证文档或代码、调用 CLI
  和工程工具，并把结果解释给 Human；
- **Engine**：verif-harness CLI 中按固定规则工作的部分。它保存已确认的信息，检查文件是否
  变化：VDOC 文档由 `docs sync` 比较 SHA-256，其他文件由 Agent 调用 `changed PATH` 明确登记。
  然后 Engine 判断哪些结论需要重新验证，列出下一步还缺什么，并检查是否满足冻结条件。
  Engine 不作工程判断，也不在后台监控任意文件。

| 步骤 | 责任主体 | 操作与结果 |
| --- | --- | --- |
| 0. 建立项目事实 | Human + Agent + Engine | Human 提供 DUT 信息；Agent 只读校验；Engine 通过 `bootstrap` 建立最小项目记录 |
| 1. 读取当前状态 | Agent + Engine | 首次规划前 Agent 调用全局 `status` 和 `inspect`；VDOC 已存在时再用 `status VDOC` 读取其 revision 与缺口 |
| 2. 建立待评审方案 | Agent + Engine | Agent 根据当前 DUT 形成只包含 `document-writing-plan` 的 `DesiredStateProposal/1` 并调用 `plan VDOC --desired-file ...`；Engine 创建数量可变的方案节点，同时登记八类文档目录、缺失模板、退出条件和待答问题，不创建正文交付节点 |
| 3. 确认输出目录 | Agent；有歧义时 Human | Agent 沿用已有验证文档目录或提议 `<verif-root>/docs/verification`；与只读输入重叠或有多个候选时由 Human 选择 |
| 4. 读取输入与模板 | Agent | 只读分析 RTL、spec、已有验证文档、Knowledge Model 和本轮所需模板，不搜索或替换用户未指定的 DUT 输入 |
| 5. 形成方案草案 | Agent | 先提出 scope 和 Feature/VF 分解，再说明计划写入的策略、架构、reference model、coverage、assertion 和 testcase 内容；此时不写正式正文 |
| 6. 解决开放决策 | Human + Agent | Agent 只询问事实无法确定的问题；Human 作出工程选择；Agent 将答案及其影响目标写入新 revision |
| 7. 逐节点审批实施方案 | Human | Human 在 Dashboard 新标签页中逐项检查由当前 DUT 分解出的 VDOC 方案节点；“待确认工程问题”“计划写入内容”“输入依据、范围和交付对象”分别作出批准、修改、澄清或拒绝决定；存在实际依赖时还需单独审批“依赖和影响” |
| 8. 聚合规划审批 | Human + Engine | Engine 将每个区块评审绑定到当前节点方案摘要；所有必需节点的必审区块均通过后，VDOC 自动进入 [`ACTIVE`（可以开始工作）](glossary.md#workstream)，任一区块要求修改、澄清或拒绝则保持 `REVISE` |
| 9. 完成文档初稿 | Agent | 仅在 VDOC 已进入 `ACTIVE` 后，Agent 按批准方案增量填写 Engine 已创建的缺失模板；已有文档和所有 RTL/spec 均不被覆盖 |
| 10. 同步并登记正文验收范围 | Agent + Engine | Agent 调用 `docs sync`，再提交只包含 `document-deliverable` 的 proposal；Engine 登记路径、文件指纹、文档内容版本和可独立验收的正文节点，不改变已批准的方案 revision |
| 11. 登记问题和决定 | Agent + Engine | 完整工程依据写入正文；Agent 用 `docs track` 登记人工决定、暂定方案、待确认假设和外部待答问题的状态 |
| 12. 检查一致性 | Engine + Agent | Engine 通过 `check` 检查文件和已登记信息，并标记需要重新验证的结论；Agent 解释冲突、缺失链接和开放问题 |
| 13. 评审文档内容 | Human + Agent | 默认在 Dashboard 打开 VDOC 正文验收节点；页面展示当前正文、内容版本、待回答问题、工程决定和历史评审，Human 判断该独立语义范围能否作为当前验证基线 |
| 14. 登记正文评审 | Human + Engine | Human 在正文验收节点选择“认可当前正文 / 要求修改 / 要求说明 / 不同意”并填写理由；Engine 将结论绑定到节点定义摘要、文件 SHA-256 和版本。使用纯 CLI 时才由 Agent 登记同一结果 |
| 15. 列出未完成项 | Engine + Agent | Engine 通过 `closure` 列出当前还缺的最小动作；Agent 向 Human 解释，不静默执行写操作 |
| 16. 冻结 VDOC | Human + Agent + Engine | Human 明确同意冻结；Agent 调用 `freeze VDOC`；Engine 检查文件指纹，并保存已评审正文和文件清单的快照 |
| 17. 后续修订 | Agent + Engine + Human | Agent 修改受影响正文后调用 `docs sync`；Engine 把相关结论标为需要重新验证；Human 重新评审 |

VDOC 的典型命令顺序如下。命令由 Agent 在当前会话执行；表中标为 Human 的决定必须先
由用户明确给出：

```text
# Agent：调用 CLI 建立待评审方案
# Engine：创建 VDOC revision、目标和待答问题
verif-harness status
verif-harness plan VDOC --desired-file <dut-specific-vdoc-plan.json>

# Human：优先在 Dashboard 的独立标签页逐节点、逐区块审批实施方案
# 纯 CLI 工作流中，Agent 只有在 Human 明确逐项确认后才能批量登记同一结论
# Engine：保存各节点区块评审并聚合 VDOC 计划状态
verif-harness review VDOC --verdict approve --reviewer <human-name>

# 只有上一步使 VDOC 进入 ACTIVE 后，Agent 才填写正式正文；已有文档不会被覆盖
# Agent：调用 CLI 同步文件指纹并登记问题/决定
# Engine：保存文件版本和状态
verif-harness docs sync
verif-harness docs track verification_plan.md --id D-001 \
  --kind provisional --title "当前工程方向" --status ACTIVE

# Agent：另行登记正文验收节点；该 proposal 只能含 document-deliverable
# Engine：保留已批准的方案 revision，并将当前正文节点开放给 Human 验收
verif-harness plan VDOC --desired-file <dut-specific-vdoc-deliveries.json>

# Agent：调用以下 CLI
# Engine：检查文件和状态，列出未完成项
verif-harness check
verif-harness status VDOC
verif-harness closure

# Human：在当前对话评审具体文档内容
# Agent：仅在 Human 明确接受后调用 CLI
# Engine：把评审绑定到当前正文 SHA-256
verif-harness docs review verification_plan.md --reviewer <human-name> \
  --notes "正文及未决事项已检查"
# 对本轮其余 required 文档逐份执行相同评审

# Human：在当前对话明确同意冻结
# Agent：收到同意后调用 CLI
# Engine：检查条件并保存当前版本的基线
verif-harness freeze VDOC --reviewer <human-name> \
  --reason "VDOC revision reviewed and accepted"
```

这里存在两个不能合并的 Human gate：

1. **规划审批**：Dashboard 对每个 DUT-specific VDOC 方案节点的区块独立审批；全部必审区块通过后才允许
   Agent 按此开展文档工作。纯 CLI 的 `review VDOC` 是 Human 已逐项确认后的批量登记入口；
2. **内容审批**：方案通过后，Agent 写正文、执行 `docs sync` 并另行登记交付节点；Human 再逐节点检查
   实际正文。文档存在、模板已复制或 Agent 自检通过都不是内容批准。

即使由 Agent 在终端输入了 `review`、`docs review` 或 `freeze`，也必须先得到当前 Human 的
明确同意。
Agent 生成八份 Markdown 也不表示 VDOC 完成；只有 DUT-specific 方案节点和对应正文获得真实评审证据，
并满足本轮退出条件后，VDOC 才能进入 baseline。

### 步骤 2：确定其他 Workstream 本轮要达到的目标

根据项目情况规划所需工作域：

```text
# Agent：调用 CLI 生成六份待评审方案；Human 无需手工输入
verif-harness plan VSTIM
verif-harness plan VENV
verif-harness plan VCHK
verif-harness plan VCASE
verif-harness plan VCOV
verif-harness plan VREG
```

可以先规划 VCHK 再规划 VSTIM，也可以同时推进。若多个 Workstream 都在 `REVIEW`，
审批时必须指明目标：

```text
# Human：先在当前对话中分别给出结论
# Agent：收到明确结论后调用以下 CLI 保存评审
verif-harness review VSTIM
verif-harness review VCHK
```

七个通用模板的关注点：

| Workstream | 典型输入 | 典型产物/证据 | 常见回跳原因 |
| --- | --- | --- | --- |
| `VDOC` | 规格、RTL 文件清单、历史决定 | 验证点、验证策略、架构和退出条件文档 | 实现时发现规格含糊或原计划不可行 |
| `VENV` | 环境架构、DUT 接口、clock/reset 和构建配置 | 接口连接、组件结构、基础构建、最小运行入口、观测点和环境 smoke 结果 | 接口或结构变化、环境无法启动/退出、观测路径失效 |
| `VSTIM` | 接口事务定义和需要产生的场景 | driver/sequence/constraint，实现是否编译注册，以及事务是否被 DUT 接受的计数 | 场景无法到达 DUT，或覆盖率分析发现缺少输入组合 |
| `VCHK` | 比较规则和预期行为 | reference model、scoreboard、assertion，以及实际比较/触发/失败统计 | mismatch 无法判断来自 DUT、检查器还是规格 |
| `VCOV` | 验证点、用例和检查器之间的对应关系 | coverage model、覆盖率数据库导出结果、未覆盖项及处理结果 | 缺少对应激励、用例或检查器 |
| `VCASE` | 验证点和场景 | testcase/virtual sequence、每个用例的定向仿真结果 | 用例无法稳定复现问题或没有证明目标场景 |
| `VREG` | 可运行的用例和工具配置 | 批量运行结果、失败重跑和分析、证据版本检查 | RTL/TB 变化，或失败还没有逐项处理 |

表中的 RTL 验证英文词可在[RTL 验证常用词](glossary.md#dv-terms)中逐项查看。

除 VDOC 外，标准模板将节点分为两类：

- [`capability`](glossary.md#node-role)：证明接口定义、实现或执行工具已经准备好；
- [`closure-evidence`](glossary.md#node-role)：证明这些能力在当前项目版本中实际运行并达到目标。

这些内置节点是通用汇总，不足以单独说明一个真实项目做了哪些功能、场景、checker、覆盖项、
testcase 和回归。Agent 必须在规划每个 Workstream（包括 VDOC）时，根据当前 DUT、已评审文档与
工程事实形成
`DesiredStateProposal/1`，和 Human 确认后再交给 Planner：

```text
# Human：在对话中确认项目级目标、范围、实现方式、量化指标和质量要求
# Agent：基于 schema/example 起草 JSON；Human 不需要手写此命令
verif-harness plan VCOV --desired-file <reviewed-desired-state.json>
# Engine：校验格式、父子关系和证据类型，在通用汇总节点下创建项目级子节点
```

模板和示例见 [`desired-state-proposal.schema.json`](../vplan/desired-state-proposal.schema.json) 与
[`desired-state-proposal.example.json`](../vplan/desired-state-proposal.example.json)。一个工作节点必须让
Human 看出六件事：要达到什么、具体做什么、怎样实现、交付什么、怎样量化进度、怎样检查质量。
适合建节点的对象包括接口/环境组件、激励 feature/scenario、checking goal/checker、coverage goal、
testcase mapping 和 regression profile。原始编译日志、仿真日志、波形、VDB/UCDB 与单笔 transaction
作为[证据](glossary.md#evidence)挂在节点下，不要把每个文件或 transaction 都变成计划节点。

Planner 在每次 plan/replan 后，按 node key 将默认 `DEPENDS_ON` 关系重新绑定到各
Workstream 当前 revision。前置 Workstream 尚未规划时，closure 返回
`PLAN_PREREQUISITE`；前置 node 尚未满足时返回 `WAIT_FOR_DEPENDENCY`。用户不需要手工
登记标准依赖，自定义关系才使用 `record dependency`。

默认依赖的主干如下；箭头表示“右侧依赖左侧”，不是整个 Workstream gate：

```text
VDOC 的验证计划/环境架构 -> VENV interface/clock-reset/topology
VENV 基础节点 -> build-ready -> run-ready -> environment-smoke-evidence
VENV run-ready + VDOC 回归规则 -> VREG executor-ready
VDOC 事务规则 + VENV interface/topology/build -> VSTIM 实现
VENV smoke/observation + VSTIM 实现 + VREG executor -> VSTIM 运行证据
VDOC 比较规则 + VENV build + VSTIM reachability -> VCHK 能力和运行证据
VDOC 用例规则 + VENV build + VSTIM/VCHK -> VCASE 能力和运行证据
VDOC 覆盖率规则 + VENV build + VSTIM/VCASE -> VCOV 能力和运行证据
VENV smoke + VSTIM/VCHK/VCASE/VCOV 运行证据 + VREG executor -> VREG 最终证据
```

VENV 的基础节点可以分批完成，其他工作域只等待自己实际使用的节点，不等待整个 VENV
冻结。VENV 的最小 smoke 不依赖业务激励、完整检查器或回归结果；VREG 的运行入口则复用
VENV 已证明的最小运行能力，因此不会形成相互等待。完整节点图和依赖原因见
[工作流之间怎样依赖](mechanism.md#workstream-dependencies)。

这一步只负责形成并批准六份计划，不执行实现、仿真、证据登记或冻结：

| 责任主体 | 在步骤 2 中负责什么 |
| --- | --- |
| **Human** | 确认各 Workstream 本轮目标、优先级、暂不纳入范围的内容和关键工程规则；分别给出 `approve/reject/modify/clarify` 结论 |
| **Agent** | 读取 VDOC 和当前项目状态，调用六次 `plan`，合并展示跨工作域问题，解释依赖与影响；Human 明确决定后调用对应的 `review` |
| **Engine** | 为每个 Workstream 创建独立 revision、目标节点、退出条件和默认依赖；保存评审记录，并把批准的计划置为 `ACTIVE` |

步骤 2 的完整顺序是：

1. Agent 调用 `status`、`inspect` 和 `closure` 读取全局状态。
2. Agent 分别调用 `plan VENV/VSTIM/VCHK/VCOV/VCASE/VREG`。
3. Engine 建立六份相互独立的待评审方案及当前 revision 的依赖图。
4. Agent 合并展示重复或相互影响的问题，避免 Human 重复回答。
5. Human 分别确认目标、工程规则、优先级和退出条件。
6. Human 对每份计划明确给出批准、拒绝、修改或继续澄清的结论。
7. Agent 调用对应的 `review WORKSTREAM`；Engine 保存结论。批准只表示同意“本轮准备达到
   什么状态”，不表示代码、仿真或测试已经完成。

### 步骤 3：查看并完成系统建议的下一项工作

这里的“并行”表示六个 Workstream 可以同时处于 `ACTIVE`、交错推进，并且只等待自己实际
依赖的节点；它不表示 Engine 启动六个后台进程。当前 Agent 依据 `closure` 返回的最小动作，
在六条工作线之间切换。每次 CLI 调用仍是一次有边界的短操作。

三种角色在并行执行中保持以下边界：

- **Human**：回答执行过程中出现的工程问题，例如接口行为、数值容差、场景范围和失败处理方法；
  决定是否修改步骤 2 已批准的计划。Human 不需要在后台任务的 stdin 中等待问题。
- **Agent**：读取只读 RTL/spec、VDOC 和当前状态；调用 `closure` 选择一个当前可以执行的动作；
  编写验证代码，运行编译、仿真、回归或覆盖率工具，并检查工具原始输出。
- **Engine**：根据当前计划、节点依赖和已有状态列出下一项动作；阻止前置条件尚未满足的动作。
  Engine 在本步骤不解释规格、不编写代码，也不会把工具退出码直接当成通过证据。

#### 共同执行流程

| 步骤 | 责任主体 | 操作与结果 |
| --- | --- | --- |
| 1. 读取当前状态 | Agent + Engine | Agent 调用 `status`、`inspect` 和 `closure`；Engine 返回当前 revision、未完成目标、前置依赖和开放问题 |
| 2. 选择一个可执行动作 | Agent + Engine | Engine 返回目标、原因和建议执行者；Agent 一次只选择一个边界清楚、前置条件已满足的动作，不启动覆盖六个工作域的大型 task |
| 3. 处理工程问题 | Human + Agent | 出现接口语义、容差、范围或风险取舍时，Agent 说明影响，并把问题、选项和推荐项登记到 Dashboard 的“需要你处理”后等待 Human 回答；不受该问题影响的其他工作可以继续 |
| 4. 完成实现或工具运行 | Agent | Agent 编写或修改验证环境、激励、检查器、覆盖率、用例或回归工具，运行编译、自检、仿真、回归或覆盖率工具，产生 log、manifest、VDB/UCDB、波形等原始文件 |
| 5. 检查原始结果 | Agent | Agent 检查命令退出状态、错误和输出完整性；工具退出码本身不改变节点状态，也不能替代步骤 4 的证据登记 |
| 6. 转入证据步骤 | Agent + Engine | 有可用工程结果时进入步骤 4；步骤 4 登记后由 Engine 更新节点状态，Agent 再回到本步骤调用 `closure` 选择下一项动作 |

步骤 3 只执行工程动作并产生原始结果。固定格式报告、PASS/FAIL 和退出条件统一由步骤 4
处理；文件变化统一由步骤 5 处理；冻结只在步骤 6、7 处理。

#### 六条工作线各自怎样执行

| Workstream | Human 参与 | Agent 执行 | Engine 在步骤 3 中负责什么 | 主要等待点 |
| --- | --- | --- | --- | --- |
| `VENV` | 确认接口接入、clock/reset、组件职责、配置传递和观测边界；决定最小 smoke 范围 | 只读分析 DUT；实现 interface、harness、agent/env 结构、构建和最小运行入口；运行 compile/elaboration 和 reset/idle smoke | 只在相关 VDOC 与前置节点满足时建议对应实现或运行动作；保存动作指向的目标节点 | 开始需要相关 VDOC；内部按 interface/clock-reset/topology → build → run/observation → smoke 推进，不等待完整 VSTIM/VCHK/VCOV/VCASE/VREG |
| `VSTIM` | 确认 transaction 字段、握手、合法/非法输入、边界、并发和反压场景 | 实现 driver、sequence、constraint 和场景生成组件；运行场景探针和同 seed 复跑 | 根据 VENV 当前状态判断实现、探针运行或复跑动作是否已解锁 | 设计可与 VENV 并行；实现依赖 VENV interface/topology/build；可达性证据等待 VENV smoke/observation 和 VREG executor |
| `VCHK` | 确认数值容差、时序对齐、顺序、异常、reset/flush 及 mismatch 处理原则 | 实现 reference-model adapter、scoreboard/checker 和 assertion；运行包含目标场景的比较和断言 | 根据 VENV 与 VSTIM 当前状态列出可以开展的实现或运行动作 | compare policy 可较早完成；实现等待 VENV build；运行证据等待 VSTIM reachability 和 VENV smoke |
| `VCOV` | 确认 coverage goal、采样条件、bin/cross、不可达判断和豁免理由 | 实现 coverage model 和导出程序；采集/合并覆盖率数据库；分析 hole，必要时返回 VSTIM/VCASE 补场景 | 根据依赖图指出当前可以实现、采集还是分析，不判断覆盖率内容是否合理 | coverage model 可较早完成；收集等待 VENV build 和 VREG executor；正式 hole 分析使用 VSTIM reachability、VCASE targeted evidence 和 VENV smoke |
| `VCASE` | 确认 testcase 范围、优先级、场景组合和每个验证点需要的检查方式 | 建立 feature/scenario 到 testcase 的矩阵；实现 testcase/virtual sequence；注册并运行定向测试 | 根据 VENV、VSTIM、VCHK 状态列出当前可执行的用例实现或定向运行 | 矩阵可较早完成；实现等待 VSTIM implementation、VENV build 和 VREG executor；运行证据等待 VSTIM reachability、VCHK scoreboard 和 VENV smoke |
| `VREG` | 确认 smoke/nightly/full 集合、seed、timeout、重跑、known-fail 和正式回归标准 | 建立运行清单、runner、collector 和失败重跑；执行批量回归；对每个失败做 same-seed 重跑和分类 | 根据 VENV 运行入口及其他工作域状态决定 runner 自检、批量执行或失败分析何时可开始 | policy 可较早完成；executor 等待 VENV run-ready；完整 execution/triage/fresh evidence 位于其他工作域运行证据之后 |

#### 实际并行节拍

六个 Workstream 不应被理解成“全部同时开始、全部同时结束”。比较实用的并行节拍如下：

| 批次 | 可以并行开展的工作 | 本批次结束后解锁的工作 |
| --- | --- | --- |
| A. 公共运行基础 | VENV 构建、最小运行入口和观测点；同时继续编写不依赖运行结果的 VSTIM/VCHK/VCOV/VCASE 代码；VREG 完成 runner/collector | 产生构建、自检和环境 smoke 的原始结果；经步骤 4 登记后，相关运行节点才可能解锁 |
| B. 定向验证 | VSTIM 场景探针与同 seed 复跑；VCHK 比较/断言、VCASE 定向运行可交错进行；VCOV 开始采集 | 产生激励、检查器、用例和覆盖率原始结果；统一交给步骤 4 提取并登记证据 |
| C. 汇合与收敛 | VREG 执行正式集合并逐项分析失败；VCOV 根据结果补洞；发现问题时只返回受影响的工作域 | 产生回归、失败分析和覆盖率收敛结果；是否满足退出条件由步骤 4 登记后确定 |

一个批次不要求前一批次所有工作域整体完成。Engine 只依据具体节点判断能否推进。例如
VCHK 的 compare policy 可以在 VENV 尚未 build 时完成，但 scoreboard 运行证据必须等待
VENV smoke 和 VSTIM reachability。

#### 并行执行中的人工问题

当 `closure` 返回 `executor=human` 时：

1. Engine 只报告目标、缺失信息和受影响节点，不自行选择答案；
2. Agent 解释问题，并把问题、选项、推荐项和工程影响登记到项目控制状态及 Dashboard 的“需要你处理”；
3. Human 在 Dashboard 或通过 `agent-question answer` 在 Agent CLI 作出决定，或要求保留为开放问题；
4. Agent 将决定写入相应文档/plan，并调用结构化命令登记；
5. Engine 重新计算依赖和未完成项；
6. 当前没有依赖该决定的其他工作可以继续，不需要暂停六个 Workstream。

不存在后台 worker 在终端中显示未登记问题并等待 stdin 的机制。需要 Human 的动作必须进入持久化的
Agent question；当前对话可以补充解释，但不能替代登记。Dashboard 与 Agent CLI 都从同一个 SQLite
检查点读写答案，因此 Human 可以选择网页或 `agent-question answer`，使用网页时无需 SSH。如果 Agent 会话中断，重新启动后可从
`status`、`inspect`、`closure` 和 `agent-question list` 恢复磁盘状态。

#### 并行执行的典型命令顺序

以下命令是 Agent 的底层操作示例，不是要求 Human 逐条手工执行：

```text
# Agent：调用以下 CLI 读取状态并选择一个当前可执行的动作
# Engine：返回缺口、依赖和建议执行者
verif-harness status
verif-harness closure
verif-harness status VENV
verif-harness status VSTIM

# Human：仅在动作涉及工程判断时，在 Dashboard 的“需要你处理”中给出决定
# Agent：执行一个边界清楚的实现、编译、仿真、回归或覆盖率动作
# 产生原始结果后进入步骤 4，不在步骤 3 直接宣告 PASS 或冻结
```

步骤 2 的 `plan/review`、步骤 4 的 `evidence`、步骤 5 的 `changed` 和步骤 6、7 的 `freeze`
不在这里重复。步骤 3 在每次步骤 4 或步骤 5 更新状态后再次运行，直到没有可执行缺口或需要
Human 作出新的工程决定。

#### `closure` 如何指出下一项工作

```text
# Agent：调用 CLI；Human 无需手工输入
# Engine：返回当前缺口、依赖和建议执行者
verif-harness status
verif-harness closure
```

Verification Closure Engine 为每个 gap 返回：

- `target`：要满足的 node；
- [`executor`](glossary.md#gap-action)：建议由固定规则工具、Agent 分析还是 Human 处理，值为
  `deterministic`、`reasoning` 或 `human`；
- `suggested_mode`：建议使用的工具/能力；
- `reason`：产生动作的原因。

例如 `target=VCHK:scoreboard-evidence`、`executor=deterministic` 表示当前缺的是 scoreboard
真实运行后的比较结果，应由仿真和结果收集工具产生，而不是等 Human 决定。如果
`executor=human`，Agent 必须登记 Agent question，并在 Dashboard 等待回答；当前对话可展示相同说明，
但不能成为唯一入口。

按 action 调用[代码生成工具或激励生成组件](glossary.md#dv-terms)、xverif、WavePeek、仿真，
或者与 Human 讨论。CLI 不启动隐藏 [worker（任务进程）](glossary.md#gap-action)，
也不会把一个大型 task 放进后台等待 stdin。需要人工输入时，问题统一在 Dashboard 的
“需要你处理”页面完成；回答后记录决策或重新 plan。

这里四个容易混淆的词有明确边界：

- [`ACTIVE`](glossary.md#workstream) 只表示本轮计划已经确认、可以开展工作，不表示有进程正在运行；
- [`executor`](glossary.md#gap-action) 只是建议下一项工作交给固定规则工具、Agent 或 Human，
  不会自动启动程序；
- [`worker`](glossary.md#gap-action) 是项目运行系统可能启动的长任务进程，v1 不会创建隐藏 worker
  等待用户输入；
- [`generator`](glossary.md#dv-terms) 可能指生成验证代码的工具，也可能指仿真中产生激励的组件，
  文档会明确写“代码生成工具”或“激励生成组件”。

### 步骤 4：把工程结果登记为证据

这一步只把步骤 3 已经产生的工程结果转换成可检查的证据，不负责规划工作、修改实现或冻结：

| 责任主体 | 在步骤 4 中负责什么 |
| --- | --- |
| **Human** | 回答报告无法自动判断的工程语义；决定是否接受例外。Human 不手工指定标准节点为 PASS |
| **Agent** | 检查步骤 3 的原始结果，调用项目结果提取程序生成固定格式 JSON；调用 `evidence` 或 `reachability`，并向 Human 解释失败和缺失项 |
| **Engine** | 检查 JSON 格式、项目 revision、文件路径与 SHA-256、前置节点及专用工程规则；生成 PASS/FAIL，更新节点状态并重新计算 `closure` |

标准 VENV/VSTIM/VCHK/VCOV/VCASE/VREG [desired node](glossary.md#knowledge) 使用统一的专用
[evidence](glossary.md#evidence) 入口：

```text
# Agent：把步骤 3 的原始结果转换为固定格式 JSON 后调用 CLI
# Engine：检查并生成 PASS/FAIL；Human 不手工指定标准节点的判定结果
verif-harness evidence NODE results/workstream-evidence.json
```

`NODE` 来自 `status`/`closure`。命令根据 node 所属 Workstream 和标准 key 确定
[claim（要证明的内容）](glossary.md#evidence-format)，按专用
[schema（JSON 格式规范）](glossary.md#evidence-format)检查字段和工程规则，再从内容生成
PASS/FAIL；调用方不能传入 [verdict（判定结果）](glossary.md#evidence)。格式错误时不登记，
格式正确但未通过工程规则时登记 FAIL。格式说明和示例见
`evidence/INSTRUCTIONS.md` 与 `evidence/*.schema.json`。
报告引用的[原始文件（native artifact）](glossary.md#evidence-source)必须包含项目相对
`path` 与 `sha256`；CLI 检查文件存在、文件指纹一致以及可用时的项目 revision。claim 中引用的
implementation、policy、manifest、log 等字段中记录的 SHA-256 还必须对应这些文件。报告或原始文件
以后被修改时，Agent 必须调用 `changed PATH` 登记，系统才会标记受影响目标。即使报告自身
通过格式和内容校验，只要 Planner 为该节点建立的当前
[prerequisite（前置依赖）](glossary.md#knowledge)
尚未规划或未达到 `VALID/WAIVED`，该次证据仍会以 FAIL 保留；前置条件满足后必须重新生成并
登记证据，系统不会把旧 FAIL 自动翻转成 PASS。

#### 工具原始输出、固定格式报告和可登记证据

编译 log、仿真 log、回归 manifest、波形和 VDB/UCDB 是
[raw artifact（工具原始输出）](glossary.md#evidence-source)，
不是可直接登记的工程结论。当前证据链是：

```text
编译 / 仿真 / 回归 / 覆盖率工具
        ↓
raw artifact: log / manifest / VDB / UCDB / waveform
        ↓
xverif / WavePeek + 项目 adapter / extractor（结果提取程序）
        ↓
字段固定的 evidence JSON
        ↓
JSON 格式 + 要证明的内容 + 原始产物类型 + 分析器 + 项目版本 + 文件指纹 + 依赖检查
        ↓
PASS/FAIL evidence → node VALID/INVALID → closure（检查还缺什么）
```

当前控制面已经实现固定格式 JSON 入口、专用自动校验、原始文件 SHA-256 绑定、revision 检查、
默认依赖和相关证据的自动退出检查；**尚未内置覆盖 VCS/Xcelium/Questa 等所有工具格式的通用
log/VDB/UCDB 解析程序**。现阶段由项目脚本、仿真器结果收集程序或 adapter 生成 JSON。
应优先消费工具原生 JSON/XML/JUnit 或正式 coverage export；Agent 对自由文本的自然语言总结
不能代替按固定规则提取字段的程序。

编译成功主要证明[能力节点](glossary.md#node-role)已经准备好，不足以关闭运行目标。仿真日志
必须提取 testcase、[seed](glossary.md#triage)、错误、比较、assertion 或场景计数；
[coverage database（覆盖率数据库）](glossary.md#evidence-source)必须导出数据库标识、合并结果、
覆盖项、命中次数和排除项。运行类节点通常还必须提供 WavePeek 分析的波形，或 xverif 分析的
结构化事务轨迹，并保存 xverif 或 WavePeek 实际生成的结构化分析结果文件；这些文件都不能
单独关闭工作域。

因此 `stimulus-implementation`、`corner-scenarios` 或 `case-implementation` 可以在其“源码存在、
注册关系完整、能够编译”的证据合同通过后显示 `VALID`；这里的 `VALID` 只表示该能力节点自身成立，
不是功能已经验证通过。对应的 `reachability-evidence`、`determinism-evidence` 或
`targeted-evidence` 仍是必需节点。任何一个运行证据节点缺少仿真、波形/事务轨迹或分析结果时，
整个 Workstream 都不能进入 `SATISFIED`。不把能力节点降成 `REVIEW_REQUIRED`，是为了让状态准确
表达“实现已准备但尚未运行”，而不是把两类事实混成一个状态。

除独立的 VSTIM reachability 格式外，标准报告使用以下[公共 JSON 字段](glossary.md#evidence-format)：

```json
{
  "schema": "CheckingEvidence/1",
  "claim": "scoreboard-evidence",
  "revision": "<bootstrap project revision>",
  "tool": "<producer/version>",
  "artifacts": [
    {
      "path": "results/checker/run.log",
      "sha256": "<64 位小写 SHA-256>",
      "kind": "simulation-log",
      "analyzed_by": ["xverif"]
    },
    {
      "path": "results/checker/wavepeek-analysis.json",
      "sha256": "<64 位小写 SHA-256>",
      "kind": "analysis-report",
      "analyzed_by": ["wavepeek"]
    }
  ],
  "result": {"...": "该 claim 对应的事实"}
}
```

SQLite 保存报告索引、文件指纹、提取后的字段、状态和[来源信息](glossary.md#evidence)，
不保存整份 VDB/UCDB。原始数据库和日志仍由项目管理；报告用路径和 SHA-256 引用它们。
`analysis-report` 必须直接引用 xverif 或 WavePeek adapter 生成的运行回执。Engine 会打开该
JSON，检查格式版本、请求 SHA-256、操作、工具身份、`state=PASS` 和空 blocker；只写一个
`{"state":"PASS"}` 或只填写 `analyzed_by` 会被拒绝。

#### 各 Workstream 的证据形式与退出条件

下表先写中文含义，再在括号中保留系统实际使用的节点名。相关 RTL 验证词见
[RTL 验证常用词](glossary.md#dv-terms)。

| [Workstream](glossary.md#workstream) | [能力节点](glossary.md#node-role)：证明“已经具备” | [运行证据节点](glossary.md#node-role)：证明“实际有效” | 主要原始来源 |
| --- | --- | --- | --- |
| `VDOC` | 八份正式验证文档的当前文件版本和 SHA-256 | 无独立运行证据；使用 Human `docs review` | Markdown、评审记录 |
| `VENV` | 接口连接（`interface-ready`）、时钟复位（`clock-reset-ready`）、组件结构（`topology-ready`）、构建（`build-ready`）、最小运行入口（`run-ready`）和观测点（`observation-ready`） | clock/reset、启动、结束和观测路径实际工作的最小环境运行（`environment-smoke-evidence`） | 源码与构建日志由 xverif 检查；动态节点还要求 xverif 仿真日志、WavePeek 波形或 xverif 事务轨迹，以及保存的分析结果 |
| `VSTIM` | 接口事务规则（`transaction-contract`）、激励实现（`stimulus-implementation`）、边界场景清单（`corner-scenarios`） | 场景确实到达 DUT（`reachability-evidence`）、同样输入可重复产生同样激励（`determinism-evidence`） | 源码和构建日志；运行节点必须有 xverif 仿真日志、WavePeek 波形或 xverif DUT 输入边界事务轨迹，以及保存的分析结果 |
| `VCHK` | 比较规则（`compare-policy`）、参考模型（`reference-model`）、计分板（`scoreboard`）、断言（`assertions`） | 参考模型、计分板和断言在真实仿真中实际参与工作且没有失败 | 实现源码和构建日志；运行节点必须有 xverif 仿真日志、WavePeek 波形或 xverif 事务轨迹，以及保存的分析结果 |
| `VCOV` | 覆盖率模型（`coverage-model`）、覆盖率收集工具（`coverage-collection`） | 覆盖数据成功收集（`coverage-collection-evidence`）、每个未覆盖项都有处理结果（`hole-analysis-evidence`） | VDB/UCDB 等覆盖率数据库和 xverif 结构化分析报告，二者都必须登记 |
| `VCASE` | 用例与验证点对应表（`case-matrix`）、用例实现（`case-implementation`） | 每个已实现用例的定向运行结果（`targeted-evidence`） | 源码和构建日志；定向运行必须有 xverif 仿真日志、WavePeek 波形或 xverif 事务轨迹，以及保存的分析结果 |
| `VREG` | 回归运行规则（`regression-policy`）、运行和收集工具已可用（`executor-ready`） | 批量执行结果（`execution-evidence`）、每个失败的分析结果（`triage-evidence`）、全部必需证据都对应当前项目版本（`fresh-evidence`） | xverif 检查的运行清单、批量仿真日志、重跑日志和结构化分析报告 |

各工作域的自动[退出条件](glossary.md#desired-current)如下。这里的“退出”是进入
`SATISFIED`，不是最终[签核（sign-off）](glossary.md#baseline)：

- **VDOC**：八份必需文档均为 `VALID/WAIVED`；每份当前正文和 SHA-256 已由 Human 评审；
  没有仍在等待回答或仍在讨论的人工决定和外部问题。
- **VENV 能力准备完成**：DUT 接口和 virtual interface 已连接；clock/reset 已配置；harness、
  agent、env、monitor 已构建并连接；环境能够编译和 elaboration，且没有构建错误；最小运行入口
  自检通过、能正常退出，也能把仿真失败传递给命令退出状态；DUT 输入、输出或关键状态至少有一个
  已连接的验证侧观测点。
- **VENV 运行证明完成**：最小 smoke 实际观察到 clock edge、reset assert/deassert 和验证侧
  观测记录；没有 error/fatal/timeout，命令正常结束；报告中的环境实现 SHA-256 与当前
  `build-ready` 节点记录一致。这个 smoke 只证明环境基础，不证明业务场景、检查器或覆盖率。
- **VSTIM 能力准备完成**：接口事务的方向、字段和握手规则合法；每个必需验证点都有已经注册、
  能够编译的 driver、sequence、constraint 或 generator；每个必需边界场景都对应当前代码中
  真实存在的激励生成组件。
- **VSTIM 运行证明完成**：每个必需场景至少一次在无 error/timeout 的运行中满足
  `generated > 0`、`driven > 0`、`accepted > 0`、`hits > 0`；观测边界必须是
  `dut-input-accepted` 或 `driver-monitor-boundary`。可重复性还要求同一个 test、seed 和配置
  SHA-256 至少运行两次，而且激励序列 SHA-256 和场景结果一致。
- **VCHK 能力准备完成**：比较规则已经评审；参考模型和计分板已经配置并能编译；计划的断言、
  编译成功的断言和完成 bind 的断言数量相同，并且至少有一条。
- **VCHK 运行证明完成**：reference model/scoreboard `engaged=true`、`comparisons > 0`、
  `mismatches=0`、`residual=0`，这些[运行字段的含义](glossary.md#runtime-evidence)见术语表；
  运行报告中记录的实现 SHA-256 等于当前能力节点记录的 SHA-256；每条 assertion 已编译、已 bind、
  `attempts > 0`、`failures=0`、`vacuous=false`，数量与计划一致。
- **VCOV 能力准备完成**：覆盖率计划、模型和导出工具的 SHA-256 已登记；模型已编译且
  `mapped_items == planned_items >= 1`。
- **VCOV 运行证明完成**：至少登记一个覆盖率数据库 ID 和一次运行；数据库合并没有错误，
  也没有来自旧项目版本或旧配置的数据；每个计划项要么 `covered` 且 `hits > 0`，要么
  `excluded` 且有 Human 已明确同意的完整豁免记录；
  不允许保留 `uncovered` 项。
- **VCASE 能力准备完成**：每个必需验证点至少对应一个 testcase；表中的每个 case 都只有一个
  实现，已登记源码 SHA-256，并且已经注册和编译。
- **VCASE 运行证明完成**：每个当前已实现 case 都有至少一次定向 `PASS`，报告记录 case、seed
  和日志 SHA-256，
  且 `uvm_error=0`、`uvm_fatal=0`。
- **VREG 能力准备完成**：回归规则、运行清单、runner 和 collector 的 SHA-256 已登记；seed、
  timeout 和 rerun 规则非空；运行和收集工具的自检通过。
- **VREG 执行和[失败分析](glossary.md#triage)完成**：批量执行报告保存 `PASS`、`FAIL`、
  `ERROR`、`TIMEOUT` 原始结果；`PASS-LIVE` 只能用于非黄金回归。每个失败的 `(test, seed)`
  必须恰好有一条使用相同 seed 的分析记录，包含失败类别、重跑结果、重跑日志 SHA-256 和处理结果；
  `accepted-known-fail` 必须引用 SQLite 中真实的 Human `WAIVE` 评审记录。
- **VREG 当前版本证据**：报告只提供与当前项目版本相同的 `snapshot_revision`；Engine 根据
  Planner 当前依赖图列出所有必需的运行证据节点，逐项要求 `VALID/WAIVED`，且
  `VALID` 项具有当前 revision 的 PASS evidence。报告生产者不能缩小这个集合。

所有 Workstream 还共同要求：当前所有必需节点均为 `VALID/WAIVED`；Planner 建立的前置目标
已经规划并满足；跨报告检查没有发现矛盾；没有仍未处理的问题；本轮计划已由 Human 明确接受。
满足后才能进入 `SATISFIED`；Human 再明确同意冻结，Engine 才能建立
`BASELINED` 快照。

VSTIM 使用更严格的可达性证据格式；统一 `evidence` 会根据节点类型选择相应检查，也可使用兼容命令：

VSTIM 的接口事务规则、激励实现和边界场景这三个能力节点使用
`StimulusCapabilityEvidence/1`；它分别检查 transaction 的字段、方向和握手规则，检查每个必需
验证点是否对应已注册且可编译的激励组件，并检查每个必需边界场景是否对应已登记的 generator。

```text
# Agent：为 VSTIM 可达性结果调用专用入口
# Engine：按固定字段检查；Human 不手工指定 PASS/FAIL
verif-harness reachability VSTIM_NODE results/stimulus-reachability.json
```

报告必须符合 `StimulusReachabilityEvidence/1`，由 `vstim-probe` 在 DUT 输入接受边界记录
每个必需场景的生成次数、送出次数、DUT 接受次数、探针命中次数，以及 test、seed、配置 SHA-256
和激励序列 SHA-256。命令根据这些字段生成 PASS/FAIL。同一 test、seed 和配置至少有两次无错误
运行，且激励序列 SHA-256 一致，才满足“可以稳定复现”这个目标。模板见
`reachability/stimulus-reachability.example.json`。Functional coverage、SVA cover property
不能作为关闭 VSTIM 的唯一证据。报告还必须引用 xverif 分析过的仿真日志，并引用 WavePeek
分析过的波形或 xverif 分析过的事务轨迹，并保存对应工具的结构化分析结果；这些原始产物仍不能
替代 probe 计数和复跑一致性。
VSTIM 因此不需要等待完整 VCOV/VCHK。

VDOC 正文使用 `docs review`。Planner 创建的 VENV/VSTIM/VCHK/VCOV/VCASE/VREG 自定义目标也必须
在规划时指定一个现有专用 evidence claim，不能用通用 `prove`：

```text
# Agent：一个 --desired 对应一个 --evidence-claim；Human 无需手工拼接
verif-harness plan VCHK \
  --desired "backpressure 下 scoreboard 无遗漏比较" \
  --evidence-claim scoreboard-evidence
```

只有用底层 `record node` 创建、且确实没有标准证据格式的扩展节点才允许通用 `prove`：

```text
# Agent：仅对没有标准证据格式的自定义目标调用 CLI
# Human：如涉及工程结论，先在当前对话中确认含义和范围
verif-harness prove CUSTOM_NODE results/custom-audit.json
verif-harness prove CUSTOM_NODE results/custom-failure.json --fail --kind custom-audit
```

通用 `prove` 接受调用方 verdict，因此不能用于 Planner 创建的实现类 Workstream desired node。

若自定义目标确实依赖其他工作域的一项能力，才手工登记 node 级依赖：

```text
# Agent：仅在项目确有自定义依赖时调用 CLI
# Engine：保存关系并拒绝循环依赖；Human 无需手工登记标准模板依赖
verif-harness record dependency DEPENDENT_NODE PREREQUISITE_NODE
```

`closure` 只会把这个具体目标标为 `WAIT_FOR_DEPENDENCY`，并在 `blocked_by` 中列出尚未满足的
前置目标；它不会等待前置目标所属的整个 Workstream。CLI 拒绝循环依赖。

项目自己的产物和关系可以通过底层 `record` 命令登记，见[命令参考](#6-完整命令参考)。
登记证据或文件修改后，系统会更新相关节点状态并重新列出未完成项；这不意味着每次都扫描
全部文件。已登记文件检查使用 `check`；“一个文件修改后哪些目标要重验”的规则见
[工作机制](mechanism.md#5-一个文件修改后系统怎样找出需要重新验证的目标)。

### 步骤 5：文件变化后标记需要重新验证的结论

这一步只处理“输入已经变化”造成的影响，不执行修复、重跑或冻结：

| 责任主体 | 在步骤 5 中负责什么 |
| --- | --- |
| **Human** | 当变化涉及规格含义、验证范围或已接受例外时，决定是否修改原有工程结论和计划 |
| **Agent** | 发现 RTL、spec、验证代码、配置或结果文件变化后调用 `changed PATH`；VDOC 正文变化时调用 `docs sync`，并解释哪些工作需要返回步骤 2、3 或 4 |
| **Engine** | 根据已登记的文件依赖，标记文件和受影响节点需要重新验证；保留旧证据与旧 baseline，不自动修改工程文件或启动重跑 |

RTL、规格或验证资产变化时：

```text
# Agent：发现输入文件变化后调用 CLI；Human 无需手工登记路径
# Human：变化涉及规格含义或范围时，在当前对话中决定是否修改计划
verif-harness changed rtl/dut.sv
verif-harness changed docs/spec.md
verif-harness status
```

常见 RTL/文档后缀会自动分类为 `rtl-change`/`spec-change`；其他文件默认为
`modify`。Verification Consistency Engine 查找哪些目标依赖这个文件：文件本身标为
`STALE`，相关下游目标标为 `REVALIDATION_REQUIRED`。Verification Closure Engine 随后
重新列出需要执行的检查或测试。旧 evidence 和 baseline 保留，便于回看历史。

### 步骤 6：保存单个 Workstream 的已评审基线

这一步只保存一个已经满足退出条件的 Workstream，不继续执行该 Workstream 的工程任务：

| 责任主体 | 在步骤 6 中负责什么 |
| --- | --- |
| **Human** | 查看该 Workstream 的目标、证据、例外和遗留问题，明确决定是否保存当前基线 |
| **Agent** | 展示当前状态；只有收到 Human 明确同意后才调用 `freeze WORKSTREAM`，并解释成功结果或拒绝原因 |
| **Engine** | 再次检查必需节点、前置依赖、评审、证据和文件指纹；条件满足时生成不能覆盖旧版本的 baseline 清单，否则拒绝冻结 |

当 Workstream 计划已经由 Human 批准，而且所有必需目标都有通过证据或 Human 明确接受的
例外时：

```text
# Human：先在当前对话中明确同意保存该 Workstream 基线
# Agent：收到明确同意后调用 CLI；Engine 再次检查条件并生成 baseline
verif-harness freeze <WORKSTREAM>
```

只有一个满足条件的 Workstream 时也可直接运行 `verif-harness freeze`。系统生成一份用
SHA-256 标识、不能覆盖旧版本的 baseline 清单。如果还有未完成项，freeze 会拒绝执行并列出原因。

### 步骤 7：保存全项目的最终基线

这一步只汇总已经分别冻结的七个 Workstream，不补做步骤 2～6 中缺失的工作：

| 责任主体 | 在步骤 7 中负责什么 |
| --- | --- |
| **Human** | 检查项目级状态和未处理问题，明确决定是否保存最终基线；最终签核责任仍属于项目负责人 |
| **Agent** | 汇总并展示七个 Workstream 的 baseline 和检查结果；收到 Human 明确同意后调用 `freeze final` |
| **Engine** | 确认七个 Workstream 均已冻结、文件存在且没有未处理问题；生成不可覆盖的项目级 baseline，不能代替 Human 宣布最终签核 |

七个 Workstream 都已存在并分别冻结，而且检查结果中没有未处理问题或缺失文件后：

```text
# Human：先在当前对话中明确同意保存全项目最终基线
# Agent：收到明确同意后调用 CLI；Engine 检查七个 Workstream 后生成 baseline
verif-harness freeze final
```

final freeze 只保存当前已审核状态，不表示工具替项目负责人完成最终签核。项目之后有变化时，
应创建新版本和新 baseline，不能改写旧清单。

## 4. 日常闭环场景

本章把步骤 2～7放进实际工作循环。图中的角色固定为：

- **Human**：在当前对话中作工程判断、批准计划、接受例外或同意冻结；不手工操作 SQLite，
  通常也不直接输入底层 CLI。
- **Agent**：当前 Codex/Kimi 会话，负责提问、修改验证资产、调用 CLI 和工程工具、检查输出并
  向 Human 解释结果。
- **Engine**：verif-harness CLI 中按固定规则工作的部分，负责保存状态、检查证据和依赖、列出
  下一项工作；不理解规格含义，不代替 Human 作决定。

除图中特别标明的 Human 对话外，所有 `verif-harness ...` 命令都由 Agent 调用。这里的循环不会
启动隐藏的 [worker（任务进程）](glossary.md#gap-action)等待 stdin；需要人工回答时，Agent 必须
登记结构化 Agent question，让 Human 在 Dashboard 回答。当前对话只用于同步解释，不替代持久化问题。

### 4.1 从查看状态到完成一个目标

这是最常见的日常循环。步骤 3 产生工程结果，步骤 4 登记证据；Engine 更新状态后，Agent
再次查询下一个 [gap（尚未满足的目标）](glossary.md#gap-action)。

```mermaid
sequenceDiagram
    participant H as Human
    participant A as Agent（Codex/Kimi）
    participant E as Engine（verif-harness CLI）
    participant T as 工程工具

    A->>E: 调用 status / closure
    E-->>A: 返回 target、原因、前置依赖和建议执行者
    alt 尚无已批准计划
        A->>E: 调用 plan WORKSTREAM
        E-->>A: 返回待评审方案和人工问题
        A->>H: 解释方案、问题和影响
        H-->>A: 批准、修改、拒绝或继续澄清
        A->>E: 调用 review，保存 Human 的明确结论
        E-->>A: ACTIVE 或 REVISE
    else 当前动作需要 Human 判断
        A->>H: 展示问题、已有证据和受影响目标
        H-->>A: 给出工程决定或保留开放问题
        A->>E: 登记决定，必要时重新 plan
        E-->>A: 重新计算 gap 和依赖
    else 当前动作可以执行
        A->>T: 修改验证资产并运行编译、仿真、回归或覆盖率工具
        T-->>A: 返回 log、manifest、数据库、波形等原始结果
        A->>A: 用项目结果提取程序生成固定格式 JSON
        A->>E: 调用 evidence / reachability
        E->>E: 检查格式、文件指纹、版本、依赖和专用规则
        E-->>A: PASS/FAIL、节点状态和新的 gap
    end
    A->>E: 再次调用 closure
```

一次循环只处理一个边界清楚的目标。出现 `FAIL` 不表示整个项目终止：Agent 根据新 gap 修复、
重跑或请求 Human 判断，然后再次登记新证据。只有该 Workstream 的所有必需节点满足后，Engine
才把它置为 `SATISFIED`；冻结仍需走 4.6 的人工确认。

### 4.2 需要人工判断时怎样暂停和继续

人工干预不是后台进程等待 stdin。Engine 只把问题标为需要 Human；Agent 解释问题并登记到
Dashboard。Human 在 Dashboard 提交后答案立即持久化，Agent 读取答案再继续分析和保存正式结论。

```mermaid
flowchart TD
    E1["Engine：closure 返回 executor=human"] --> A1["Agent：说明问题、已有事实、选项和影响"]
    A1 --> H1{"Human：作出什么决定？"}
    H1 -->|批准当前方案| A2["Agent：调用 review 或登记决定"]
    H1 -->|要求修改范围或退出条件| A3["Agent：修改文档并重新 plan"]
    H1 -->|信息仍不足| A4["Agent：保留开放问题；继续不受影响的工作"]
    H1 -->|有依据地接受例外| A5["Agent：确认理由和影响后调用 waive"]
    A2 --> E2["Engine：保存结论并重新计算依赖"]
    A3 --> E3["Engine：创建新 revision，状态回到 REVIEW"]
    A4 --> E4["Engine：相关目标保持 REVIEW_REQUIRED/BLOCKED"]
    A5 --> E5["Engine：记录 WAIVED；保留理由和评审人"]
    E2 --> A6["Agent：调用 closure 继续"]
    E3 --> A1
    E4 --> A6
    E5 --> A6
```

四种结果的含义不同：

- “批准”只批准当前计划或决定，不证明实现已经完成；
- “修改”创建新 revision，旧方案保留为历史；
- “继续澄清”不会伪造默认答案，相关目标仍未完成；
- [`waiver（有理由接受例外）`](glossary.md#validity)得到 `WAIVED`，不是 `VALID`，也不是工具测试通过。

### 4.3 覆盖率发现未覆盖项后，返回激励或用例工作

覆盖率缺口不应直接由 VCOV 自己“补成已覆盖”。Agent 先判断缺的是场景、用例、检查器还是
覆盖率模型；无法从事实确定时由 Human 决定目标是否仍然必需。

```mermaid
flowchart LR
    A1["Agent：运行覆盖率工具并导出结果"] --> E1["Engine：登记 VCOV 证据"]
    E1 --> E2{"Engine：是否存在 uncovered item？"}
    E2 -->|否| E3["Engine：VCOV 当前目标继续收敛"]
    E2 -->|是| A2["Agent：读取验证点、场景、用例和采样条件"]
    A2 --> H1{"Human：该目标是否仍为必需？"}
    H1 -->|必需；缺少输入场景| A3["Agent：重新 plan VSTIM，补激励"]
    H1 -->|必需；缺少定向用例| A4["Agent：重新 plan VCASE，补 testcase"]
    H1 -->|必需；采样或 bin 有误| A5["Agent：重新 plan VCOV，修正模型"]
    H1 -->|有充分依据且可以接受| A6["Agent：按 Human 决定登记 waiver"]
    A3 --> A7["Agent：运行定向仿真并生成新原始结果"]
    A4 --> A7
    A5 --> A7
    A7 --> E4["Engine：检查新证据及其版本、依赖和文件指纹"]
    E4 --> E2
    A6 --> E5["Engine：保存 WAIVED 和理由，再重新计算 closure"]
```

典型底层调用如下；Human 只在对话中作决定：

```text
# Agent：查询缺口和影响范围
verif-harness closure
verif-harness impact file:verification/coverage/model.sv

# Agent：仅在 Human 确认需要补该场景后创建新的 VSTIM 方案
verif-harness plan VSTIM --decision "补充 backpressure × error 组合"
```

### 4.4 检查结果不一致时怎样定位并回跳

仿真出现 [mismatch（实际结果与预期不一致）](glossary.md#runtime-evidence)时，固定规则只能确认
“不一致确实发生”，不能自动断言是 DUT、检查器还是规格错误。

```mermaid
flowchart TD
    A1["Agent：运行定向仿真"] --> A2["Agent：提取 mismatch、test、seed、log 和波形引用"]
    A2 --> E1["Engine：登记 FAIL evidence；VCHK 节点变为 INVALID"]
    E1 --> A3["Agent：比较输入、DUT 输出、参考结果、时序和 reset 状态"]
    A3 --> D1{"事实是否足以定位？"}
    D1 -->|检查器实现错误| A4["Agent：修复 VCHK；保持 DUT RTL 只读"]
    D1 -->|激励或用例错误| A5["Agent：修复 VSTIM/VCASE"]
    D1 -->|环境连接错误| A6["Agent：修复 VENV"]
    D1 -->|可能是 DUT 问题| H1["Human：确认问题归属和后续处理；Agent 不修改 DUT"]
    D1 -->|规格含义不清| H2["Human：决定正确行为；Agent 更新 VDOC 并重新 plan"]
    D1 -->|仍无法判断| A7["Agent：调用 reason 形成候选原因和下一步检查"]
    A7 --> H3["Human：选择补充检查或保留开放问题"]
    H1 --> A8["Agent：等待 DUT 侧修复或登记外部问题"]
    H2 --> A9["Agent：docs sync，并让受影响目标重新验证"]
    H3 --> A10["Agent：执行补充实验"]
    A4 --> A11["Agent：同 test/seed 重跑"]
    A5 --> A11
    A6 --> A11
    A8 --> A11
    A9 --> A11
    A10 --> A11
    A11 --> E2["Engine：检查新的当前版本证据"]
    E2 --> D2{"结果是否满足规则？"}
    D2 -->|否| A3
    D2 -->|是| A12["Agent：调用 closure 继续下一个目标"]
```

分析辅助命令由 Agent 调用；它只产生候选原因和建议，不能替代重新运行和标准证据：

```text
# Agent：在已有日志和波形仍不足以定位时调用
verif-harness reason DebugEngineer "分析 mismatch 的候选根因" \
  --context results/mismatch.json --context waves/failing.vcd
```

### 4.5 文件变化后怎样重新验证

RTL、spec、验证实现、配置或结果提取程序发生变化后，旧证据仍保留供回看，但不能继续证明
当前版本。Agent 明确登记变化，Engine 只让真正依赖该文件的节点失效。

```mermaid
flowchart LR
    H1["Human：提供新的规格决定或 DUT 版本"] --> A1["Agent：发现文件 SHA-256 已变化"]
    A0["Agent：修改验证代码或文档"] --> A1
    A1 --> E1["Agent 调用 changed PATH；VDOC 使用 docs sync"]
    E1 --> E2["Engine：文件标为 STALE"]
    E2 --> E3["Engine：依赖该文件的节点标为 REVALIDATION_REQUIRED"]
    E3 --> A2["Agent：调用 impact / closure 查看受影响目标"]
    A2 --> H2{"Human：工程语义或范围是否变化？"}
    H2 -->|是| A3["Agent：更新 VDOC 或重新 plan；等待 Human 评审"]
    H2 -->|否| A4["Agent：按原计划重跑受影响检查"]
    A3 --> A4
    A4 --> E4["Engine：登记新证据；旧证据和旧 baseline 保留"]
    E4 --> E5{"受影响目标是否重新满足？"}
    E5 -->|否| A2
    E5 -->|是| A5["Agent：继续 closure；需要时创建新 baseline"]
```

```text
# Agent：登记变化并查询影响；Human 无需手工输入路径
verif-harness changed verification/scoreboard.sv
verif-harness impact file:verification/scoreboard.sv
verif-harness closure
```

### 4.6 waiver、单 Workstream 冻结和最终冻结

waiver 和 freeze 都必须由 Human 明确决定，但含义不同：waiver 接受一个仍未满足的目标；
freeze 保存已经评审的状态。Engine 只检查并记录，不能自行批准。

```mermaid
flowchart TD
    E1["Engine：closure 返回未满足目标"] --> A1["Agent：展示证据、原因、影响和可选处理"]
    A1 --> H1{"Human：修复还是接受例外？"}
    H1 -->|继续修复| A2["Agent：返回步骤 3 执行和重验"]
    H1 -->|接受例外并给出依据| A3["Agent：调用 waive NODE --reason ..."]
    A3 --> E2["Engine：验证目标已规划、理由非空；记录 WAIVED"]
    A2 --> E3["Engine：登记新证据并重新计算 closure"]
    E2 --> E4{"Workstream 所有退出条件是否满足？"}
    E3 --> E4
    E4 -->|否| A1
    E4 -->|是| A4["Agent：向 Human 展示 SATISFIED 状态、证据和例外"]
    A4 --> H2{"Human：是否同意冻结该 Workstream？"}
    H2 -->|否| A2
    H2 -->|是| A5["Agent：调用 freeze WORKSTREAM"]
    A5 --> E5["Engine：复查条件并生成不可覆盖的 baseline"]
    E5 --> E6{"七个 Workstream 是否都已 BASELINED？"}
    E6 -->|否| A6["Agent：继续其他 Workstream"]
    E6 -->|是| A7["Agent：展示项目级状态和未处理问题"]
    A7 --> H3{"Human：是否同意保存最终基线？"}
    H3 -->|否| A6
    H3 -->|是| A8["Agent：调用 freeze final"]
    A8 --> E7["Engine：生成项目级 baseline；不代替最终签核"]
```

```text
# Human：先在当前对话说明接受例外的理由
# Agent：收到明确决定后调用 CLI
verif-harness waive NODE --reason "该场景在当前产品配置中不可达，依据 DEC-017"

# Human：分别明确同意单 Workstream 和最终基线
# Agent：分别在收到同意后调用 CLI
verif-harness freeze VSTIM
verif-harness freeze final
```

waiver 只允许用于已规划 Workstream node，必须提供理由；Agent 不得根据“暂时跑不过”自行
waive。单 Workstream baseline 和 final baseline 都保留旧版本，后续变化必须重新验证并创建
新 baseline，不能改写历史。

### 4.7 在完成条件检查之前实时查看和参与

Human 不需要等到某个 Workstream 满足全部[完成条件](glossary.md#gap-action)才参与。启动本机
[Dashboard](glossary.md#dashboard) 后，可以随时查看七个 Workstream、每个目标节点、当前活动、
证据历史、待处理问题、依赖和按节点数量计算的进度。这里的节点数量只统计按当前 DUT 分解出的
工作节点，不统计固定分类或文档交付目录；因此不同 DUT、接口数量、时钟域、功能、场景、checker、
覆盖目标、testcase 和回归配置会得到不同节点数。界面中的进度只说明当前必需工作节点已有多少
达到 `VALID/WAIVED`，不代表仿真覆盖率，也不代替工程判断。

Dashboard 的主页面不要求使用者具有 ASIC 验证背景。它优先回答四个问题：当前在做
什么、已经完成什么、还缺什么、谁需要处理。页面用“工作流”、“工作节点”、“支持材料”和
“完成条件”描述项目状态。数据库状态码、内部编号、内容摘要、规则版本和工具字段只放在
“查看内部信息”中，不应出现在主判断或操作按钮上。页面同时给出 VDOC、VENV 等简写的中文名称；
简写用于准确定位，不是理解页面的前提。

Dashboard 首页不再使用“验证项目总览”或“当前验证状态”作为页面级标题，而是直接用一张
“当前项目状态”卡片描述项目选择器中当前选中的验证项目及其 DUT 验证对象。卡片说明当前工作对象、
状态、完成进度和下一步，并明确区分“方案已批准”和“正文已通过”等不同结论。顶部项目选择器只负责
在独立项目之间切换；切换后所有读取、事件流和 Human 写操作都重新绑定到所选项目自己的
`.verif-harness/model.sqlite3`。工作流列表是主区域；“需要你处理”是右侧唯一的回答、审批、验收和确认
入口。项目与验证对象默认折叠，风险与变更作为次要入口。从审计记录取得的 Human reviewer 和 Agent actor、
固定的 verif-harness Engine 身份、完整项目根目录、只读 RTL 输入、规格/文档输入和验证输出目录
只放在“项目详细信息、责任身份与路径”的折叠区域中。Engine 只负责校验、版本绑定和状态聚合，
不代替 Human 审批；页面不建立额外人员档案，也不会猜测尚未登记的项目负责人。进入任一工作流后
仍可展开同一上下文，避免 Human 在错误 DUT 或错误代码基线上评审。

首页不提供无目标的“提交意见”。项目级通用意见无法可靠映射到当前数据模型，默认挂到
第一条工作流会造成错误归属。Human 应进入对应工作流、工作节点或文档后提交意见；涉及 VDOC
范围增减时使用“调整文档”，从而让每条输入都有明确的处理对象和审计记录。

```text
# bootstrap 通常已经在交互环境中启动或复用了 Dashboard；以下命令用于手动启动或恢复
# Human：在当前 Agent 对话中提出“打开 Dashboard”；通常不直接输入 shell 命令
# Agent：确认项目已 bootstrap 后，以与 bootstrap 相同的后台动作启动或复用服务并展示地址
# Engine：从同一个 model.sqlite3 读取状态，状态变化时通过浏览器连接推送新快照
verif-harness dashboard --open-browser
verif-harness dashboard --status
# 仅注销当前项目；还有其他项目时共享服务继续运行
verif-harness dashboard --stop
```

#### 从本地浏览器访问远端 Dashboard

Dashboard 始终只监听它所在服务器的 `127.0.0.1`。不指定 `--port` 时，从 `8765` 起为当前系统账号
自动选择端口，并优先复用该账号已经运行的服务；同机其他账号的 Dashboard 会被跳过。同一账号下的
多个验证项目注册到这个服务，浏览器在顶部切换项目；项目之间除共享这个 HTTP 服务和只含项目名称、
DUT、根目录的本机路由注册外没有关系。`STARTED`/`REUSED` 结果中的 `url` 和
`access.remote_dashboard_port` 是本次实际端口，不能假定一定是 `8765`。

SSH 场景的成功结果会直接给出 `access.single_hop`、`access.double_hop` 和 `access.url`；用实际值
替换尖括号中的主机、账号、SSH 端口和私钥即可。Agent 必须在当前对话逐项完整打印单跳 SSH 配置及
启动命令、双跳 SSH 配置及启动命令，以及本地浏览器访问远端 Dashboard 的完整 URL；不能只打印
其中一项、只说配置位于 bootstrap 结果中，或省略 URL 的 `project`/`token` 参数。CLI 同时返回可直接
展示的 `access.required_agent_output.message`。远端服务器、跳板机和本地电脑的 `127.0.0.1` 分别
代表不同机器，因此不能依赖远端 `--open-browser`，必须先建立 SSH 本地端口转发。

单跳 SSH，即本地电脑可以直接登录远端服务器：

```sshconfig
Host verification-server-direct
    HostName <remote-host>
    User <remote-user>
    Port <remote-ssh-port>
    IdentityFile ~/.ssh/<remote-private-key>
    IdentitiesOnly yes
    LocalForward <dashboard-port> 127.0.0.1:<dashboard-port>
```

```bash
# 本地电脑执行；也可以直接使用 access.single_hop.command；保持该进程运行
ssh -N verification-server-direct
```

双跳 SSH 推荐把 CLI 返回的 `access.double_hop.ssh_config` 写入本地电脑的 `~/.ssh/config`。
例如，本地电脑先通过端口 `7822` 登录公网跳板机 `111.198.53.109`，再由跳板机访问内网验证服务器
`192.168.50.92`；两台服务器都使用账号 `ai_eda05` 和本地私钥 `~/.ssh/id_rsa_ai_eda05`，本次
Dashboard 实际端口为 `8765`。跳板机使用非标准端口或专用密钥时，必须把参数写在跳板机自己的
`Host` 条目里；命令行最外层的 `-p` 只控制最终服务器端口：

```sshconfig
Host ai-jump
    HostName 111.198.53.109
    User ai_eda05
    Port 7822
    IdentityFile ~/.ssh/id_rsa_ai_eda05
    IdentitiesOnly yes

Host ai-verif
    HostName 192.168.50.92
    User ai_eda05
    IdentityFile ~/.ssh/id_rsa_ai_eda05
    IdentitiesOnly yes
    ProxyJump ai-jump
    LocalForward 8765 127.0.0.1:8765
```

先在远端服务器启动 Dashboard，再在本地电脑建立隧道。直接运行 `dashboard` 与 bootstrap 使用同一个
后台启动/复用动作，命令返回后服务仍继续运行：

```bash
# 远端服务器：结果会显示实际选择的端口和以下两套 SSH 配置
verif-harness dashboard
verif-harness dashboard --status

# 本地电脑：保持运行，不会出现新的 shell 提示符
ssh -N ai-verif

# 另一个本地终端：确认请求确实到达远端 Dashboard
curl http://127.0.0.1:8765/healthz
```

健康检查应返回 `schema: DashboardHubHealth/2`、`status: ok`、当前账号的不透明 `owner_id` 和已注册
项目数量。随后打开 CLI 返回的 `access.url`。如果该本地端口已占用，只改变 `-L` 或
`LocalForward` 左侧，例如远端实际端口为 `8766` 时使用
`LocalForward 18766 127.0.0.1:8766`，浏览器访问 `http://127.0.0.1:18766/`；右侧必须始终等于
CLI 返回的远端实际端口。

CLI 返回的项目 URL 含有当前账号的 Dashboard 访问令牌，不要把完整 URL、访问令牌文件或 SSH 配置中的
私钥路径发给无权访问项目的人。页面、读取 API 和写操作都校验该令牌；`/healthz` 只暴露服务归属、
存活信息和不透明项目 ID，不暴露项目路径、名称、验证事实或文档正文。不要为了省略 SSH 转发而把
Dashboard 暴露到 `0.0.0.0`。当前设计只允许 loopback。常见连接问题见
[Dashboard 无法从本地浏览器打开](troubleshooting.md#dashboard-无法从本地浏览器打开)。

实时显示需要 Agent 或项目工具把正在做的工作登记为
[Activity（当前活动）](glossary.md#dashboard)。登记活动不会把目标改成 `VALID`；最终结论仍必须来自
规定格式的证据或 Human 明确作出的评审、豁免和冻结决定。`当前 Activity` 只统计已经登记且尚未
结束的具体实现、编译、仿真或分析动作，不是 Workstream 完成百分比。Agent 开始任何非简单工程动作
前必须登记 Activity；计划建立前登记到项目级 `project`，已有计划后登记到最具体的目标节点。否则
Dashboard 无法从另一个终端的普通进程或对话文字中猜出它正在做什么。

首页按下面的层级组织，不在首页单列 Agent：

1. **当前项目状态**：一张卡片说明当前工作对象、状态、完成进度、下一步和结论边界；
2. **验证工作流**：显示每条 Workstream 的工作节点进度和状态；用缓慢呼吸的进度圈表达可量化完成度，
   点击后在新标签页打开；节点列表为了横向比较仍使用进度条；
3. **需要你处理**：右侧唯一的行动区域，按对象归并当前需要负责人回答、审批、验收或确认的事项；
4. **辅助信息**：项目与验证对象默认折叠；风险与变更只作为次要入口显示数量。

首页不重复显示“等待负责人处理”的横幅、状态卡和工作流计数。工作流或工作节点本身表达等待状态，
右侧只列出实际可处理的事项。正式方案审批、文档交付验收、文档工程决定和 Agent questions 都进入
“需要你处理”。Human 已经提交、等待 Agent 执行的修改请求不重复算作 Human 待办。
风险页只收集 `INVALID`、`BLOCKED`、`STALE`、`REVALIDATION_REQUIRED`、
`PROVISIONAL`、正文变化及开放 finding，不把普通进度冒充风险。

同一层级也适用于首页之外的界面。工作流页只用一张“当前工作流状态”卡片说明状态、工作节点进度和
下一步；工作节点抽屉只用一张“当前工作节点状态”卡片说明目标、当前判断、实际进度、主要问题和下一步。
Agent 当前工作默认折叠，方案审批页和文档验收页直接说明审批或验收的对象、内容、结论边界和下一步。
内部编号、文档路径、规则版本和内容摘要只放在“查看内部信息”中。需要负责人操作的入口仍统一放在
“需要你处理”，各详情页只提供与当前对象直接相关的审批、验收、评论或确认操作。

首页右侧按类型归并待办；打开“需要你处理”页面后，开放的 Agent question 放在首位，直接展示影响范围、
选项和推荐项，审批、验收和确认紧随其后。首页右侧和待办页底部都只保留一个默认折叠的
“Agent 运行详情”，其中再按需查看主 Agent 当前工作、子 Agent 状态以及运行与回答记录。子 Agent 完成
只表示分派工作结束，不代表验证通过，也不会自动确认工作节点。

Human 可以直接在网页回答，也可以在当前主 Agent 对话回答。主 Agent 必须先在对话中显示同一个
question ID、正文、全部选项和推荐项，收到回答后立即用
`verif-harness agent-question answer` 写回同一个 SQLite 问题记录。写回后 Dashboard 的实时事件流会把
该问题更新为“已回答”；反方向从 Dashboard 回答时，同一 ID 的 CLI 后台 `await` 会结束并通知主 Agent。
任一入口的回答都只用于继续当前工作，不会自动批准工作流、确认工作节点或改变验证结论。
任一入口提交后，另一个入口立即看到相同答案。使用网页时不需要进入服务器终端。远端 Dashboard 仍须按上一节建立
安全的 SSH 端口转发。快速闪烁会造成干扰，因此等待状态只使用约 2 秒周期的缓慢呼吸状态灯，并遵守浏览器的
`prefers-reduced-motion` 设置。

原生 Codex/Kimi 终端选择器不会被网页自动截获，Dashboard 也不会向没有活动 checkpoint、已经
回到原生提示符的 idle 会话注入新 prompt。Agent 必须登记结构化问题。默认 CLI 提供前台阻塞
checkpoint；Kimi 交互会话使用“前台登记 + 后台等待”的 bridge，使普通输入框仍可回答：

```text
# Agent：VDOC 计划尚未建立时，先登记项目级 Activity 和项目级问题
verif-harness activity start project \
  --operation analyze-dut-for-vdoc \
  --actor Agent \
  --message "分析 DUT 规格与 RTL"
verif-harness agent-question ask project \
  --prompt "VDOC 验证文档输出到哪个目录？" \
  --context "当前尚未创建 VDOC 工作流或工作节点" \
  --option default "使用默认目录" "verif/docs/verification" \
  --option custom "指定其他目录" "由 Human 填写目录" \
  --recommended default \
  --activity ACTIVITY_ID \
  --no-wait

# Agent：已有工作节点时，绑定最具体的节点 Activity 和问题
verif-harness agent-question ask NODE \
  --prompt "参考模型策略选哪个？" \
  --context "说明规格约束、已知事实和受影响节点" \
  --option dpi "DPI 直连 cmodel" "逐事务调用现有只读模型" \
  --option sv "按规格重写" "在验证环境中独立实现" \
  --recommended dpi \
  --activity ACTIVITY_ID \
  --no-wait

# Kimi Main Agent：先把 ask 返回的 ID、正文、选项、推荐项和影响显示在对话中；
# 然后把下面命令作为 Bash 后台任务启动，不要在前台运行或立即 WaitFor
verif-harness agent-question await QUESTION_ID --timeout 300

# Human：也可从另一个 shell 直接回答；当前 Main Agent 对话中的普通回复
# 由 Main Agent 转成同一条 answer 命令
verif-harness agent-question answer QUESTION_ID --option OPTION_ID --reviewer NAME
```

登记阻塞问题会把绑定 Activity 置为 `WAITING_FOR_HUMAN`。默认阻塞型 `ask` 最多等待 300 秒；Kimi 的
受管 profile 则用 `ask --no-wait` 先取得并展示问题，再立即把同一 ID 的 `await` 启动为后台任务。
这时 Human 可在 Kimi 普通输入框回答，Main Agent 将答案写回；也可在 Dashboard 回答，后台任务完成后
通知 Main Agent。Kimi 等待 Human 时不得前台运行 `await`，也不得调用 `WaitFor` 占用普通输入框。
`--no-wait` 只有与这个后台 checkpoint 成对使用才有效，不能单独留下开放问题。如果后台等待返回
`TIMEOUT` 且问题仍为 `OPEN`，Main Agent 重新启动同一 ID 的后台 `await`，不得创建重复问题。
答案只是一项工程输入：不会把节点改成
`VALID`，不会批准实施方案或文档交付，也不会生成证据、豁免或冻结结论。Agent 必须分析答案并通过
相应的 plan、document、evidence 或 review 流程记录后续结果。

Dashboard 的 Human 输入会立即保存并刷新页面。普通评论不会作为聊天消息直接打断正在运行的
Codex/Kimi；Agent 必须在开始、恢复和结束 Activity 时读取尚未处理的输入：

```text
# Agent：在工作边界读取；Human 通常不直接输入此命令
verif-harness human-action list --status OPEN
```

如果 Closure 要求正式 Workstream Review，Agent 使用
[Human checkpoint（人工检查点）](glossary.md#dashboard)等待 Dashboard 决定：

```text
# Agent：CURRENT_REVISION 来自刚刚展示给 Human 的当前 plan
# ACTIVITY_ID 是这次工作已登记的 Activity
verif-harness await-human VDOC \
  --revision CURRENT_REVISION \
  --activity ACTIVITY_ID \
  --timeout 60
```

等待时 Activity 自动显示为 `WAITING_FOR_HUMAN`，Workstream 卡片明确显示当前正在等待负责人处理
什么。VDOC 由 Human 在 Dashboard 的“审批文档撰写方案”中逐个打开与当前 DUT 对应的方案工作节点，
分别审批各部分内容；所有计划要求完成的方案都通过后聚合为正式 Review。其他 Workstream 仍在独立
方案页提交正式 Review。`approve` 使 Activity 恢复 `RUNNING` 并允许 Agent 继续，`modify/clarify/reject`
分别要求修改、说明或停止。
普通“提交意见”不会解除等待。60 秒内没有决定时命令返回 `TIMEOUT`，Agent 可以继续进行有界等待，
不会丢失检查点。

如果 Agent 正阻塞在外部编译或仿真进程里，Review 不能强制中断该进程；输入会安全地留在 SQLite，
等 Agent 到达检查点再处理。需要立即停止工具时，Human 仍应在 Agent 对话或终端中明确要求停止。

```text
# Agent：开始一个有边界的实现、编译、仿真或分析动作时登记
verif-harness activity start NODE \
  --operation "compile environment" --actor codex --total 3

# Agent：工具产生新进展时更新；WAITING_FOR_HUMAN 表示问题已显示，当前动作先不继续
verif-harness activity update ACTIVITY_ID \
  --status RUNNING --current 2 --message "elaboration completed"
verif-harness activity update ACTIVITY_ID \
  --status WAITING_FOR_HUMAN --message "需要确认 reset 释放规则"

# Agent：工作真正结束后登记结果；这仍不是验证证据
verif-harness activity update ACTIVITY_ID --status COMPLETED --current 3
```

Human 可以从界面选择 Workstream 或节点，提交评论、要求修改、要求说明或调整优先级。
这些输入进入[人工操作记录](glossary.md#dashboard)，立即出现在 Dashboard 和后续 Agent 会话中；
它们不会绕过 `evidence` 直接修改节点状态。Human 也可在界面中提交 Workstream 评审、豁免；
豁免必须再次确认并填写 reviewer 与 reason。页面、读取 API 和写操作都要求当前系统账号的本机
访问令牌；服务只监听 `127.0.0.1` 或 `localhost`，不提供网络账号登录或远程共享。各 Workstream 页面的
方案操作会打开独立审批页；页面直接显示当前结果检查、验证环境、激励、覆盖率、用例或回归方案。
VDOC 再从该页逐个打开按当前 DUT 分解出的文档撰写方案，不使用弹窗；待确认工程问题、计划写入内容、
输入依据、范围、交付对象以及实际存在的依赖影响分别审批。批准只授权开始工作，不表示文档正文、实现、证据或节点完成状态
已经通过验收。

VDOC 文档节点还提供“评审文档正文”。Dashboard 从已经登记的安全路径读取当前 UTF-8 Markdown
正文，同时显示正文版本、内容变化、文档中的开放问题和工程决定。Human 阅读后可以选择认可当前
正文、要求修改、要求说明或不同意，并填写评审说明。评审仍调用与 `docs review` 相同的底层接口，
不会因为页面上存在文件就自动认可文档。`docs track` 登记且处于 `PENDING/ACTIVE` 的人工决定和
外部开放问题会进入首页右侧的“需要你处理”；点击后在新标签页打开对应文档节点。
只要这些问题或工程决定尚未处理，Dashboard 就不提供“认可当前正文”选项，底层接口也会拒绝绕过该检查。

因此，Human 可以把 Dashboard 作为 VDOC 的默认审阅界面，不需要直接输入 `docs review` 命令。
Dashboard 用于阅读、提意见和登记结论；工程语义仍保存在 Markdown 正文中，正文修改由 Agent 根据 Human 意见完成后再次同步。

不同工作域可以共享页面骨架，但不能共享通用项目管理节点内容。节点必须绑定当前 DUT、规格、RTL
接口和已评审验证点；Agent 无法从只读输入确定的信号、协议、时序、数值规则、场景或目标值必须
保留为待 Human 确认，不能用“完成工作、收集材料”之类空泛文字代替。节点内容按验证类型区分：

| 工作流 | 工作节点应当具体到 |
| --- | --- |
| VDOC | `document-writing-plan` 表示归属于一份文档的 DUT 相关撰写方案；`document-deliverable` 表示该文档中的一个独立语义验收单元。一份文档对应多个交付节点；所有必需交付节点通过后该文档才通过。Agent 分析后提出的假设、风险和工程问题必须先由 Human 逐项处理 |
| VENV | 一个接口、时钟复位域、环境组件、构建入口或观测路径 |
| VSTIM | 一个激励功能或具体场景，以及生成、驱动、DUT 接收和重复运行情况 |
| VCHK | 一个检查目标、结果检查模块、参考结果路径或断言组，以及实际启用情况 |
| VCOV | 一个可判断是否完成的覆盖目标或覆盖范围，以及命中、排除和数据版本 |
| VCASE | 一组功能与用例的对应关系，或一个具体测试用例及定向运行结果 |
| VREG | 一份回归配置、一个回归批次或一组同类失败及其处理状态 |

原始日志、波形、覆盖率数据库和单笔事务继续作为节点证据，不作为工作节点。

#### Human 怎样评审节点的完成判断

打开任一当前目标节点后，`完成条件与当前依据` 区域显示
[节点完成结论](glossary.md#node-closure-assessment)，包括：

- 系统的当前判断及原因；
- 结论绑定的工作域计划版本、规则版本和摘要；
- 每条满足条件是已由结构化证据支持、尚未支持，还是必须由 Human 判断；
- 本次读取的证据、未满足的前置节点、开放问题；
- 以往 Human 对该节点结论的评审记录。

Human 可以点击“确认节点完成判断”，选择认可、要求修改、要求说明或拒绝。认可不会把 `UNKNOWN`
节点改成 `VALID`，也不会补造缺失证据；它只保存“Human 认为系统对现有材料的解释正确”。要求
修改、要求说明或拒绝会把该节点置为 `REVIEW_REQUIRED`，并登记一个开放问题，Agent 后续从
Dashboard、`inspect` 或 `closure` 看到它后继续处理。如果证据、前置节点、问题或状态已经变化，
Dashboard 会拒绝基于旧摘要提交的评审，Human 必须刷新并查看新的结论。

这类节点评审随时可做，不要求 Agent 在每个节点停止。只有流程明确设置了
[人工检查点](glossary.md#dashboard)时，Agent 才会显示 `WAITING_FOR_HUMAN` 并等待正式 Workstream
Review；普通节点完成判断评审用于实时监督和纠错。

三种角色在实时查看中的边界：

| 角色 | 实际工作 |
| --- | --- |
| **Human** | 随时查看状态、证据和当前活动；提出评论/修改/澄清/优先级；在看清影响后作出评审、豁免或冻结决定 |
| **Agent** | 启动 Dashboard；在开始、等待和结束工程动作时更新 Activity；解释证据和 Human 输入并执行后续工作；通过节点展示结论，不得伪造进度 |
| **Engine** | 从 SQLite 生成结构化快照和节点完成结论；列明规则、证据、依赖、问题和逐项核对结果；保存 Human Review；在人工检查点把匹配当前 revision 的决定返回给 Agent；不自行运行编译、仿真或选择工程语义 |

Dashboard 停止或 Agent 断线不会丢失已经保存的节点、证据、Activity 和人工操作记录。新会话进入
项目后可再次运行 `dashboard --open-browser`；未登记到 CLI 的终端输出或进程内部百分比无法恢复。
如果工具长时间运行，应持续登记 Activity 或由项目执行系统保留日志，再由新 Agent 根据真实状态更新。

## 5. 状态、文件与治理边界

这里的状态来自 [Verification Knowledge Model](glossary.md#subsystems)。
[Desired/current state](glossary.md#desired-current) 的差距形成
[gap、finding 和 action](glossary.md#gap-action)；动作产生的
[artifact/evidence](glossary.md#evidence) 经登记后改变节点
[validity](glossary.md#validity)。工作域达到条件后，经过
[Human gate](glossary.md#human-gate) 创建 [baseline](glossary.md#baseline)。
完整事件示例见[从工程动作到证据](mechanism.md#4-工程动作怎样成为证据)。

### 5.1 节点状态（Validity）

| 状态 | 含义 |
| --- | --- |
| `UNKNOWN` | 尚无足够事实 |
| `VALID` | 有通过 evidence 支持 |
| `STALE` | `changed` 已登记该输入修改，或 `docs sync` 已发现文档 SHA-256 不同 |
| `REVALIDATION_REQUIRED` | 这个目标依赖已修改的输入，需要重新验证 |
| `INVALID` | 失败 evidence 或按固定规则执行的检查失败 |
| `REVIEW_REQUIRED` | 需要人工评审 |
| `BLOCKED` | 当前无法推进 |
| `WAIVED` | Human 有理由接受该 gap |

不能用 `record status ... VALID/WAIVED` 绕过治理：`VALID` 只能由 evidence 建立，
`WAIVED` 只能由 Human waiver 建立。

### 5.2 Workstream 当前进度状态

各状态的直白说明见 [Workstream lifecycle](glossary.md#workstream)。常见路径是
`REVIEW → ACTIVE → SATISFIED → BASELINED`；其中 `ACTIVE` 只表示计划已经批准、可以开展工作，
**不表示 worker 或后台程序正在执行**。replan 可回到 `REVIEW`，change 可进入
`PARTIALLY_STALE`，reject/modify/clarify 可进入 `REVISE`。

### 5.3 项目文件

```text
.verif-harness/
├── model.sqlite3                 # 文件指纹、版本、评审、问题/决定、关系和 evidence 状态
├── project.json                  # bootstrap manifest
├── inventory.json                # 从数据库生成、供人查看的文件清单
├── model.md                      # 从数据库生成、供人查看的项目状态
├── model.sqlite3                 # 也保存 Dashboard Activity 与人工操作记录
├── workstreams/<name>/
│   ├── desired-state.json        # 从数据库生成的当前目标版本
│   └── plan.md                   # 从数据库生成的简洁阅读文件
└── baselines/
    ├── vdoc/<id>/
    │   ├── manifest.json         # 文档状态和文件指纹快照
    │   ├── document-governance.md # 从 SQLite 生成的文档状态记录
    │   └── documents/*.md        # 已评审验证文档快照
    ├── <workstream>/<id>/manifest.json
    └── final/<id>/manifest.json

<verif-root>/docs/verification/
└── *.md                          # 工程师直接编辑和 Git review 的正式验证文档
```

不要编辑这些由数据库生成的阅读文件来改变状态；要更新状态必须调用 CLI。
`project.json` 由 CLI 用来读取项目身份和 runtime，属于配置清单；它与只供人查看的生成文件
的区别见[Source of truth、Projection、Manifest](glossary.md#authority)。

## 6. 完整命令参考

所有项目命令都支持 `--project-root PATH`，默认当前目录。正常使用不需要传；只有从项目
外部运行 CI/脚本时才需要。`-h/--help` 显示局部帮助。

### `bootstrap`

```text
verif-harness bootstrap [OPTIONS]
```

| 参数 | 说明 |
| --- | --- |
| `--project-name NAME` | 覆盖默认目录名 |
| `--runtime auto\|codex\|kimi\|claude\|none` | 记录项目推理 runtime；setup 后通常无需指定 |
| `--rtl-root PATH` | 声明只读 RTL 根目录；可重复；允许显式项目外路径 |
| `--docs-root PATH` | 声明只读 RTL spec 文件或目录；可重复；允许显式项目外路径 |
| `--clear-docs-root` | refresh 时明确移除以前登记的可选 RTL spec 输入；不能与 `--docs-root` 同时使用 |
| `--verif-root PATH` | 声明项目内验证资产输出根目录，不允许位于项目外 |
| `--testbench-root PATH` | 可选的已有 testbench 根目录；其内部资产由后续工作流识别 |
| `--reference-model PATH`、`--gold-model PATH` | 可选的 reference/golden model 文件或目录；两个参数名含义相同 |
| `--verification-script PATH` | 可选的编译、仿真或回归入口脚本；可重复 |
| `--clear-testbench-root` | refresh 时明确移除以前登记的 testbench 目录 |
| `--clear-reference-model` | refresh 时明确移除以前登记的参考模型 |
| `--clear-verification-scripts` | refresh 时明确移除以前登记的全部验证脚本 |
| `--dut-top MODULE` | 明确 DUT top；不会自动猜测 |
| `--dut-top-file PATH` | 明确 DUT top 文件；必须属于某个 `--rtl-root`，允许位于项目外 |
| `--refresh` | 重新配置并读取文件/工具清单；同步 `.harness-config.json` 管理字段，保留已有目标、证据和评审状态 |
| `--dashboard` | 即使在 CI/非交互调用中，也在 bootstrap 成功后启动或复用后台 Dashboard |
| `--no-dashboard` | 本次 bootstrap 不自动启动 Dashboard |
| `--dashboard-port PORT` | 显式指定 loopback 端口；未指定时优先复用当前账号的服务，否则从 `8765` 起自动选择；只接受 `1..65535` |

已 bootstrap 的项目再次运行必须加 `--refresh`，防止意外覆盖。对话中只需提出
`bootstrap --refresh`；Agent 必须按固定顺序一次确认一个字段，最后汇总确认，再展开成底层完整命令。
如果底层 CLI 在没有其他参数的情况下收到裸 `bootstrap --refresh`，它只返回
`BootstrapReconfiguration/1` 的当前值与待确认问题，不修改任何文件；这是防止 Agent 跳过对话的
保护措施，也不会启动 Dashboard。返回值中的 `interaction.mode=SEQUENTIAL`、题号和
`current_question_id` 要求 Agent 一次只展示当前一题，不能把整个问题数组同时交给 Human。
上述参数属于底层自动化接口；Skill 首次初始化必须先按顺序完成全部 bootstrap 问题，其中三个 DUT
身份字段和验证输出目录必须提供，可选项必须明确回答提供或跳过。
用户提供的可选 spec 路径映射到 `--docs-root`，未提供时不推导或补填。

首次 bootstrap 的字段在当前 Agent 对话中逐项收集，因为此时项目控制状态和 Dashboard 还没有建立。
bootstrap 成功并启动 Dashboard 后，后续会阻塞 Agent 的问题（例如“是否开始规划 VDOC”）必须先登记为
项目级 Activity 和项目级 Agent question，不能只留在原生终端选择器。Human 随后既可在 Dashboard 回答，
也可通过 `agent-question answer` 在 Agent CLI 回答；若初始请求已经明确授权下一步，则不重复询问。

每个项目的后台注册指针写入自己的 `.verif-harness/dashboard-runtime.json`；当前系统账号的共享服务
输出日志默认写入 `~/.verif-harness/dashboard/dashboard.log`，访问令牌保存在权限为 `0600` 的
`~/.verif-harness/dashboard/access-token`。账号级注册目录只保存项目入口所需的路由/显示信息和
本机访问凭据，不保存验证结论。项目内的 `dashboard-runtime.json` 不保存访问令牌；完整访问 URL 只在
启动结果和账号私有的 Dashboard 日志中出现。以上内容用于运行诊断，不是验证证据或项目语义事实源。

### `status [WORKSTREAM]`

当用户询问“当前做到哪里、还缺什么”时，Agent 先运行这个命令。
无参数显示全局模型、Workstream 和 ranked actions；指定 Workstream 只显示其 plan 与
只读 closure。WORKSTREAM 为 `VDOC/VENV/VSTIM/VCHK/VCOV/VCASE/VREG`。

### `dashboard`

在当前系统账号自动选择的端口注册项目，并启动或复用供 Human 实时查看和参与的本机 Web 界面。
同账号多个项目共享服务，同机不同账号不会互相复用；每次请求只访问明确选中的项目 SQLite，页面
不建立项目间关系。这一默认动作与 bootstrap 自动打开
Dashboard 完全相同，命令返回不会停止服务。顶部可切换项目，也可经二次确认注销当前项目。

```text
verif-harness dashboard [--host 127.0.0.1|localhost] [--port PORT] [--open-browser]
verif-harness dashboard --status
verif-harness dashboard --stop
verif-harness dashboard --snapshot
verif-harness dashboard --foreground
```

| 参数 | 说明 |
| --- | --- |
| `--host` | 监听地址；只接受 `127.0.0.1` 或 `localhost`，默认 `127.0.0.1` |
| `--port` | 显式指定 Dashboard 监听端口；未指定时复用当前账号的服务或从 `8765` 起自动选择；后台模式不接受 `0` |
| `--open-browser` | 仅当浏览器与 Dashboard 位于同一台机器时使用；SSH 场景应建立端口转发 |
| `--status` | 检查共享服务是否运行，以及当前项目是否已经注册；不启动服务 |
| `--stop` | 注销当前项目且不影响其他项目；仅当它是最后一个注册项目时停止共享服务 |
| `--snapshot` | 只输出一次完整 JSON 快照后退出，适合 CI 或自定义前端 |
| `--foreground` | 前台运行服务，仅用于调试和后台启动器内部；正常使用不要搭配管道或 `head` |

页面通过按项目隔离的本机事件流接收状态更新，不轮询外部服务。切换或注销项目不会停止仿真，
也不会清除任何项目的 SQLite 状态。Dashboard 不是证据生产工具；它只展示或提交受控的 Human 输入。

### `await-human WORKSTREAM`

Agent 在 Closure 明确要求 `HUMAN_REVIEW` 时使用。Human 通常不直接调用。

```text
verif-harness await-human WORKSTREAM [--revision N] [--after-review REVIEW_ID] \
  [--timeout SECONDS] [--activity ACTIVITY_ID]
```

| 参数 | 说明 |
| --- | --- |
| `WORKSTREAM` | 当前等待正式评审的 Workstream |
| `--revision` | 绑定待评审版本；省略时在命令开始时锁定当前 revision；旧版本会被拒绝 |
| `--after-review` | 同一 revision 需要再次评审时，忽略指定 Review 及更早决定 |
| `--timeout` | 单次等待秒数，默认 60；超时返回结构化 `TIMEOUT`，可安全重试 |
| `--activity` | 等待时把该 Activity 置为 `WAITING_FOR_HUMAN`；收到决定后恢复 `RUNNING` |

返回 `HumanCheckpoint/1`。只有正式 Workstream Review 才会返回 `DECIDED`；普通评论、修改请求或
旧 revision Review 均不能冒充批准。`resume` 仅在 verdict 为 `APPROVE` 时为 `true`。

### `plan WORKSTREAM`

开始一个 Workstream 或需要修改它的目标时使用。命令先生成待评审方案，不会直接实现代码。
面向用户的短命令等价于完整命令 `plan design --workstream WORKSTREAM`：

```text
verif-harness plan VCHK [--objective TEXT] [--desired TEXT] \
  [--evidence-claim CLAIM] [--exit TEXT] [--decision TEXT]
```

| 参数 | 说明 |
| --- | --- |
| `--objective TEXT` | 覆盖模板目标；省略时用内置目标 |
| `--desired TEXT` | 自定义 required desired state；可重复；一旦提供则替代模板 desired 列表 |
| `--evidence-claim CLAIM` | 与每个自定义 `--desired` 一一对应；确定报告格式、原始产物类型和分析器；实现类 Workstream 不允许省略 |
| `--exit TEXT` | 自定义退出标准；可重复；省略时用模板 |
| `--decision TEXT` | 记录已确认决策；可重复 |
| `--document-root PATH` | 仅用于 VDOC；Agent 将对话确认的验证文档输出目录传给 Engine，Human 通常不直接填写 |

高级查询当前 plan：`plan show --workstream WORKSTREAM`。

### `review [WORKSTREAM]`

Agent 已向 Human 展示目标、退出条件和待答问题，Human 明确表示批准、拒绝或要求修改后，
Agent 才能调用这个命令记录结果。

```text
verif-harness review [WORKSTREAM] \
  [--verdict approve|reject|modify|clarify] \
  [--reviewer NAME] [--reason TEXT]
```

- 默认 verdict：`approve`；
- 未指定 Workstream 时，只有一个 `REVIEW/REVISE` 候选时才自动选择它；
- reviewer 未填写时，依次读取 `git user.name`、`GIT_AUTHOR_NAME`、`USER`；
- approve 的 reason 有审计默认值；其他 verdict 必须显式传 `--reason`；
- 该命令是 Human gate，Agent 只有收到用户明确批准后才能调用。

完整拼写：`plan review --workstream ...`。

### `docs`

当 Agent 创建、修改或评审 VDOC 文档时使用这些命令。Markdown 保存工程师编写的验证设计；
SQLite 只保存文件 SHA-256、文档内容版本、问题/决定的状态和评审记录。

```text
verif-harness docs status [DOCUMENT]
verif-harness docs sync [DOCUMENT ...]
verif-harness docs render [DOCUMENT] [--output PATH]
verif-harness docs review DOCUMENT \
  [--verdict approve|reject|modify|clarify] [--reviewer NAME] [--notes TEXT]
verif-harness docs track DOCUMENT --id ID \
  --kind human-decision|provisional|assumption|external-open-question \
  --title TEXT [--status PENDING|ACTIVE|RESOLVED|SUPERSEDED] \
  [--owner NAME] [--review-trigger TEXT] [--affects NODE] [--anchor TEXT]
```

- `DOCUMENT` 可以是登记的 document ID、项目相对路径或不歧义的文件名；
- `docs status`：只读查看已登记版本，并报告工作区文件是否已经变化；
- `docs sync`：不修改正文；发现 SHA-256 变化时创建新的文档内容版本，保留旧评审，并把
  依赖旧内容的目标标为需要重新验证；
- `docs render`：把 SQLite 中的文档状态显示到终端。只有显式指定 `--output` 才写入单独文件，
  而且不会覆盖验证文档或只读 RTL/spec；
- `docs review`：Human 检查实际正文并明确作出决定后，Agent 用它把评审记录绑定到当前
  SHA-256。`approve` 表示接受当前内容；其他 verdict 必须提供 `--notes`；
- `docs track`：记录一个人工决定、暂定方案、待确认假设或外部问题目前处于什么状态。问题的
  完整说明、选项、依据和影响仍写在 Markdown。`ACTIVE` 表示事项仍有效或尚未关闭，不表示
  后台任务正在执行，也不表示 Human 已经批准。

### `prove SUBJECT SOURCE`

```text
verif-harness prove SUBJECT SOURCE [--kind KIND] [--fail]
```

仅用于项目自行添加、且没有标准证据格式的自定义 node。默认 `kind=verification`、
verdict=`pass`；`--fail`
记录失败证据。SOURCE 必须存在、位于项目内且为文件；系统计算 SHA-256 digest。
标准 VENV/VSTIM/VCHK/VCOV/VCASE/VREG desired node 会拒绝该命令。

### `evidence SUBJECT SOURCE [--claim CLAIM]`

仿真、编译或覆盖率工具的结果已经由项目程序转换成标准 JSON 后，Agent 使用这个命令把报告
关联到具体目标。控制面检查报告并自行生成 PASS/FAIL。

```text
verif-harness evidence SUBJECT SOURCE [--claim CLAIM]
```

标准 node 从 key 自动确定[要证明的内容（claim）](glossary.md#evidence-format)；自定义 node
在规划时已经由 `--evidence-claim` 固定，不能在登记时换成较弱 claim。命令分别校验
`EnvironmentEvidence/1`、`StimulusCapabilityEvidence/1`、`StimulusReachabilityEvidence/1`、
`CheckingEvidence/1`、`CoverageEvidence/1`、
`TestcaseEvidence/1` 或 `RegressionEvidence/1`，然后从内容推导 verdict。VDOC 不接受该
入口，工程正文使用 `docs review`。

每个 claim 要提供哪些字段、原始数据来自哪里、什么条件下可以退出，统一见前面的
[各 Workstream 的证据形式与退出条件](#各-workstream-的证据形式与退出条件)。字段名称的
中文解释见[证据 JSON 常见字段](glossary.md#evidence-format)。当前 desired-state JSON 和
`plan.md` 会直接列出该节点的 `evidence_contract`：缺少要求的 simulation log、波形/事务轨迹、
coverage database 或分析器时，报告会登记为 FAIL，closure 不会将节点视为满足。

### `changed PATH`

用户或外部工具修改了 RTL、规格或验证文件后，Agent 使用这个命令告诉控制面“这个输入已经
变化”。它不会修改该文件。

```text
verif-harness changed PATH \
  [--kind auto|add|modify|delete|rename|spec-change|rtl-change] \
  [--revision REVISION]
```

默认 `auto`；`--revision` 可绑定 commit/build revision。

### `waive NODE`

只有 Human 明确决定“当前版本接受这个未满足项”时才使用。waiver 不是 PASS，原因必须保留。

```text
verif-harness waive NODE --reason TEXT [--reviewer NAME]
```

reason 永远必填；reviewer 的推导规则与 review 相同。这是 Human gate。

### `freeze [WORKSTREAM|final]`

`closure` 已经没有未完成项，而且 Human 明确同意保存当前状态时使用。freeze 不运行仿真，
只创建不能覆盖的基线记录。

```text
verif-harness freeze [WORKSTREAM|final] [--reviewer NAME] [--reason TEXT]
```

- 不指定 Workstream 时只在唯一 ready 候选时推导；
- `freeze final` 要求七个 Workstream 全部 BASELINED 且 audit 通过；
- reviewer 未填写时从 Git 或环境中的用户名读取，reason 未填写时使用内置记录说明；
- 这是 Human gate，且 baseline 不可覆盖。

完整拼写：`plan freeze --workstream ...` 或 `plan freeze --final`。

### `inspect`、`trace`、`impact`

需要回答“系统保存了什么”“这个目标依赖什么”“某个文件变化会影响哪里”时使用。它们只读：

```text
verif-harness inspect                  # 全部验证知识状态
verif-harness inspect NODE             # 单 node
verif-harness trace NODE               # 入边、出边、finding、evidence
verif-harness impact NODE              # 所有通过已登记关系受其影响的下游节点
```

第一行应使用 `verif-harness inspect`。`model show/trace/impact` 仅为旧自动化保留，
不建议在人用流程中继续使用。

### `check`

```text
verif-harness check
```

检查已登记文件是否缺失，并通过 `docs sync` 比较 VDOC 文档 SHA-256；如果文档修改，就把相关
结论标为需要重新验证。`check` 不会比较所有 RTL/验证文件的内容，其他文件修改必须使用
`changed PATH` 明确登记。最后重新列出未完成项。
`check scan` 是为旧脚本保留的完整拼写。它不修代码、不作 waiver、不审批。

### `closure [--workstream WORKSTREAM]`

需要回答“现在还缺哪些工作、为什么不能 freeze”时使用。命令只计算和列出动作，不执行动作。

```text
verif-harness closure
verif-harness closure evaluate --workstream VCHK
```

无 Workstream 时重算全局 closure 和 ranked actions；局部形式只计算指定 Workstream。

### `activity`

Agent 用它登记当前正在执行什么，让 Human 不必等到任务结束才能知道进展。Activity 与节点关联，
但绝不直接改变节点 validity。

```text
verif-harness activity start NODE --operation TEXT --actor NAME \
  [--message TEXT] [--total N] [--log-path PATH]
verif-harness activity update ACTIVITY_ID \
  --status PENDING|RUNNING|WAITING_FOR_HUMAN|WAITING_FOR_PARENT|COMPLETED|FAILED|CANCELLED \
  [--message TEXT] [--current N] [--total N] [--log-path PATH]
verif-harness activity list [--workstream WORKSTREAM] [--node NODE] [--active]
```

`--current/--total` 只表示该 Activity 自己公开的步骤数；不得拿主观百分比冒充覆盖率或完成条件。
`--log-path` 必须位于项目内。结束状态不能再次改写，需要继续工作时创建新的 Activity。

### `agent-work`（别名 `subagent`）

这是 Main Agent 用来把 Codex/Kimi 原生 subagent 映射到当前验证节点的控制面接口；它不启动
进程，也不允许 child 自己修改治理状态。

```text
verif-harness agent-work candidates [--limit N]
verif-harness agent-work claim ACTION_ID --agent ID --role ROLE --operation TEXT \
  [--parent project-agent] [--runtime-ref ID] [--lease-seconds N] \
  [--write-scope PATH] [--message TEXT] [--total N]
verif-harness agent-work heartbeat ASSIGNMENT_ID --agent ID \
  [--phase RUNNING|WAITING_FOR_PARENT] [--message TEXT] [--current N] [--total N]
verif-harness agent-work finish ASSIGNMENT_ID --agent ID \
  --outcome COMPLETED|FAILED|CANCELLED --summary TEXT
verif-harness agent-work list [--workstream WORKSTREAM] [--node NODE] [--active]
```

`claim` 只接受当前、已批准 Workstream 中可执行的 closure action；同一当前节点和同一 agent
最多各有一个 active assignment。`--write-scope` 必须位于 verification 输出根目录，不能覆盖
只读 RTL/spec、`.verif-harness`、`.harness-config.json`、`.git`、`.deps`、`.codex`、
`.kimi-code`、`.agents` 或 `AGENTS.md`（保留路径按大小写不敏感匹配），
并且不能与其他 active assignment 的范围重叠；未提供表示只读执行。这个范围是 Main 与
subagent 的协作合同，不是 OS 级文件隔离。Main 在接收结果时仍须检查实际 diff；不受信任的
child 应在隔离 worktree 或更严格的 runtime sandbox 中执行。
`WAITING_FOR_PARENT` 表示 child 等待 Main Agent 协调，不进入 Human 待处理列表。租约过期只把
协作记录标成 `EXPIRED`，计划 revision 变化则标成 `SUPERSEDED`；两者都不会把验证节点标成失败。
Main Agent 收到真实结果后调用 `finish`，随后复核文件、运行结果并重新计算 closure。只有符合对应
evidence contract 的材料才能通过 `evidence` 改变节点 validity。

### `agent-question`

Main Agent 用它把工程选择题持久化到项目控制状态。Human 可以在 Dashboard 的“需要你处理”页面回答，也可以调用
下面的 `answer` CLI；两者是同一问题的两个交互入口。计划尚未建立时使用项目级目标 `project`；已有计划后应绑定最具体的当前
Workstream 或节点。阻塞问题可以再绑定同一范围的 Activity。

```text
verif-harness agent-question ask TARGET --prompt TEXT \
  --option ID LABEL DESCRIPTION --option ID LABEL DESCRIPTION \
  [--context TEXT] [--recommended ID] [--actor "Project Main Agent"] [--activity ACTIVITY_ID] \
  [--non-blocking] [--no-wait] [--wait-timeout SECONDS]
verif-harness agent-question await QUESTION_ID [--timeout SECONDS]
verif-harness agent-question list [--status open|answered|cancelled|superseded] [--target TARGET]
verif-harness agent-question answer QUESTION_ID --option ID --reviewer NAME [--text TEXT]
```

每个问题必须有 2 到 8 个唯一选项；Dashboard 还提供“其他”，选择它时必须填写说明。默认阻塞问题会
进入等待人工列表，并由 `ask` 保持最长 300 秒的 runtime checkpoint；`--wait-timeout` 可修改单次等待时长，
超时后可继续 `await`。`--non-blocking` 只记录问题，不暂停 Activity；`--no-wait` 登记阻塞问题后立即返回，
仅供脚本编排或立即展示问题并启动后台 `await` 的受管 runtime bridge 使用。Human 的回答会持久化并解除最后一个
关联阻塞问题的 Activity 等待，但不会改变节点有效性或代替 `review`、`evidence`、`waive`、`freeze`。
`ask` 只接受固定的 `Project Main Agent` actor，并拒绝绑定任何 subagent assignment 的 Activity；
subagent 必须返回 `NEEDS_HUMAN` 给 Main，由 Main 判断是否真的需要提问。
原生 Agent 终端中的临时选择器不会自动同步，Dashboard 也不能唤醒已经 idle 的 runtime 会话。凡是会让 Agent 停下等待 Human 的问题，都必须先用
`ask` 登记；终端选择器不得作为唯一入口。subagent Activity 不能直接绑定问题，必须先向 Main Agent
回报，再由 Main Agent 统一判断和登记。

### `human-action`

保存 Human 在 Dashboard 或对话中针对 Workstream/节点提出的输入，不直接批准证据或改变节点状态。

```text
verif-harness human-action add TARGET \
  --action comment|request-change|clarify|prioritize|acknowledge \
  --reviewer NAME --reason TEXT
verif-harness human-action resolve ID --reviewer NAME --resolution TEXT \
  [--status resolved|superseded]
verif-harness human-action list [--status open|recorded|resolved|superseded]
```

`request-change/clarify/prioritize` 会保持 `OPEN`，直到 Agent/Human 明确记录处理结果；
`comment/acknowledge` 作为已经记录的信息保存。正式 Workstream 审批仍使用 `review`，节点豁免仍使用
`waive`，不能用 human-action 代替。

### `reason`

已有日志和固定检查仍无法判断问题含义时使用，例如需要区分 DUT bug、checker bug 或规格
歧义。命令只准备分析请求，不会自动启动另一个 Agent，也不会生成验证证据。

```text
verif-harness reason capabilities
verif-harness reason ROLE PURPOSE [--context VALUE ...] \
  [--operation analyze|propose|modify|review] \
  [--backend auto|codex|kimi|claude]
```

ROLE 可选：`VerificationArchitect`、`EnvironmentEngineer`、`TestEngineer`、
`AssertionEngineer`、`CoverageEngineer`、`DebugEngineer`、`Reviewer`。

完整拼写为 `reason request --role ROLE --purpose PURPOSE ...`。`--context` 可重复；
`auto` 只在唯一后端可用时选择，否则返回 `unselected`，不会静默回退。命令只生成
`VerificationReasoningRequest/2`，不直接执行后端、不产生 evidence。

### `record`

`record` 是项目 adapter 和 CI 登记自定义节点、关系或文件修改时使用的底层入口。普通用户优先使用
`evidence/changed/waive`。

```text
record node NODE --type TYPE --title TEXT
  [--workstream WORKSTREAM]
  [--status STALE|INVALID|REVIEW_REQUIRED|REVALIDATION_REQUIRED|BLOCKED|UNKNOWN]

record edge SOURCE TARGET --relation RELATION
  [--origin explicit|inferred|runtime] [--confidence 0..1]

record dependency DEPENDENT_NODE PREREQUISITE_NODE

record status NODE STATUS

record evidence --subject NODE --kind KIND --source FILE
  --verdict pass|fail

record change --path PATH
  --kind add|modify|delete|rename|spec-change|rtl-change
  [--revision REVISION]

record waive NODE --reviewer NAME --reason TEXT
```

约束：node ID 不得含空白；edge/dependency 两端必须存在；inferred relation 应提供真实
confidence；dependency 不能形成环；新 node 不能直接为 `VALID/WAIVED`；evidence source
必须是真实文件。所有标准实现类 Workstream desired node 必须使用 `evidence`，不能用
底层 `record evidence` 绕过。

### `reachability NODE FILE [--claim reachability|determinism]`

项目 probe 已生成“场景是否到达 DUT 输入边界”的 JSON 后，Agent 使用这个命令登记报告。
命令按固定规则检查并登记 VSTIM-owned probe 报告。标准 VSTIM 目标可从 key 推导 claim；项目自定义
VSTIM node 必须显式指定 `--claim`。报告不满足场景或复跑条件时仍会登记 FAIL evidence，
格式、producer 或观察边界非法时则 fail closed，不写入证据。

### `doctor` 与 `runtime status`

`doctor` 是只读项目审计；未 bootstrap 时返回 `BOOTSTRAP_REQUIRED`。已 bootstrap 时
检查缺失文件和 open finding，失败返回非零。`runtime status` 显示项目 manifest 中
记录的 Agent runtime。

### `xverif` 与 `wavepeek`

```text
verif-harness xverif ADAPTER_ARGS...
verif-harness xverif mcp configure|status ...
verif-harness wavepeek ADAPTER_ARGS...
```

参数原样转发给各 adapter，具体 schema 见 Skill 内的
`xverif/INSTRUCTIONS.md`、`wavepeek/INSTRUCTIONS.md`。xverif 按明确配置执行命令并采集结果，
WavePeek 负责有边界的波形检查；二者输出只有通过 `evidence` 或允许的自定义 evidence
入口绑定到目标后
才进入验证事实。

## 7. CI 与发布

在 verif-harness 自身仓库提交前：

```text
make check
```

公开发布候选：

```text
make release-check
```

不要为通过审计而弱化 denylist 或排除规则。可选 xverif、WavePeek 及其他依赖留在
Git-ignored `.deps/`，不得提交 proprietary DUT、规格、结果、许可或调度器配置。
