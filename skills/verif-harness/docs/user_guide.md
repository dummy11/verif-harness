# verif-harness v1 用户指南

本文只讲安装和操作。项目定位、适用对象与治理理念见仓库
[README](../../../README.md)，内部边界见[架构说明](../../../ARCHITECTURE.md)。
理解一次操作如何推动状态变化，请先读[工作机制](mechanism.md)；不熟悉的名词可查
[术语表](glossary.md)。

## 1. 两种入口

### 1.1 在 Agent 会话中使用（推荐）

setup 成功后会自动切换到指定 workspace，并启动选定的 Agent，无需再次手动启动。
进入会话后，Human 只需激活 Skill 并用自然语言说明目标：

- Codex：对话中输入 `$verif-harness`，再说明目标；
- Kimi：对话中输入 `/skill:verif-harness`，再说明目标。

Human 不需要直接运行 `verif-harness plan/review/prove/freeze` 等底层命令，也不需要记忆
它们的参数。Skill 激活后，Agent 先读取当前状态、提出需要 Human 回答的问题；Human
通过对话给出目标、工程决定或审批结论；Agent 再自行调用底层 CLI，将结果持久化到
Knowledge Model。标准交互关系是：

```text
Human：激活 Skill，并用自然语言说明目标
  ↓
Agent：读取状态，调用 CLI，生成 proposal 或 Draft
  ↓
Human：回答问题，作出 approve/modify/clarify/reject 等决定
  ↓
Agent：根据明确回答继续调用 CLI 并报告结果
```

首次使用时，Human 可输入“`$verif-harness 为当前项目开始验证治理`”（Codex）或
“`/skill:verif-harness 为当前项目开始验证治理`”（Kimi）。Agent 发现项目尚未
bootstrap 后，会询问必填 DUT 信息，并自行调用 `bootstrap` 建立项目知识模型。
只有传入 `--no-agent` 时 setup 才跳过启动；之后重新运行不带该参数的 setup 即可进入会话。

例如：“`$verif-harness 规划 VDOC，并只询问模型无法确定的决策`”。Agent 会读取
Skill 约束，再调用项目级 CLI。Human review、waiver 和 freeze 必须由用户明确要求，
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

CLI 输出结构化 JSON，适合 Agent 和 CI；人工通常只需关注 `status`、`actions`、
`questions_for_human`、`findings`、`evidence` 与 `baseline`。用户指南保留命令块是为了
解释 Agent 实际执行了什么，以及方便 CI/高级诊断；它们不是要求 Human 在正常对话流程中
手工输入。Human 也可以在终端直接调用 CLI，但直接调用表示调用者自行承担参数、项目范围
和授权语义，不能让 Agent 把 CLI 的默认值当作 Human 决定。

## 2. 安装、runtime、依赖与 MCP

从已审核的 verif-harness checkout 执行一次：

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

`runtime`、`dependency`、`backend` 是三个不同概念：

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

## 3. 从空项目到 final freeze

下面是第一次使用时最容易理解的顺序，不是强制流水线。任何 Workstream 都可以并行、
跳转、修订或重新打开。

### 步骤 0：建立项目模型

setup 已自动进入 workspace 并启动 Agent。在会话中发起 bootstrap：

```text
$verif-harness bootstrap
# Kimi 使用 /skill:verif-harness bootstrap
```

Agent 必须通过对话要求用户明确提供以下输入，不搜索候选目录、不猜测或自行选择 DUT：

| 对话输入 | 是否必填 | 含义 |
| --- | --- | --- |
| `rtl root` | 必填 | RTL 根目录 |
| `dut top` | 必填 | DUT 顶层模块名 |
| `dut top file` | 必填 | DUT 顶层源文件路径 |
| `spec` | 可选 | RTL 规格文件或目录；可以不提供 |

本次对话已明确提供的字段不重复询问；缺失必填字段时先等待用户补齐，不执行初始化。
Agent 只读校验用户给定的路径，然后将回答转为底层 CLI 参数。以下是 Agent 的执行示例，
用户无需手动拼接参数；可选 spec 使用现有 `--docs-root` 接口传入：

```text
verif-harness bootstrap \
  --rtl-root rtl --docs-root docs --verif-root verification \
  --dut-top dut --dut-top-file rtl/dut.sv
```

所有 RTL 和 RTL spec 均为当前 Agent 的只读输入，不允许编辑、生成覆盖、删除、移动或
格式化，也不得通过工具间接更改。发现输入问题时报告用户处理；验证产物必须放在独立路径。
初始化后可用 `status` 和 `doctor` 检查项目状态。

### 步骤 1：形成 VDOC desired state

```text
verif-harness plan VDOC
verif-harness status VDOC
```

Verification Planner 提供 VDOC 通用模板、当前知识模型与项目上下文，产生 proposal 和
`questions_for_human`。Agent 结合项目事实筛选、解释问题，在当前会话收集用户回答；
CLI 本身不会自动完成语义澄清。需要修改时再次运行 `plan VDOC`，
形成新 revision。

Agent 展示 proposal 后，Human 在对话中明确表达评审结论，例如：

```text
批准当前 VDOC 范围。
```

Agent 收到这条明确授权后，才自行执行底层命令并持久化结论：

```text
verif-harness review VDOC --verdict approve
```

当且仅当只有一个 Workstream 等待评审时，Agent 才可以在底层调用中省略目标；默认
verdict 是 `approve`，reviewer 从 `git user.name` 推导。CLI 默认值不是 Human 授权，
Agent 仍必须先取得明确结论。Human 拒绝或要求修改时，在对话中说明原因；例如 Human 说
“需要修改，接口 reset 语义仍不清楚”，Agent 转换为：

```text
verif-harness review VDOC --verdict modify --reason "接口 reset 语义仍不清楚"
```

### VDOC 正式文档产出

默认 `plan VDOC` 建立七个文档目标。每个 desired 节点带 `document` 合同，包含文件名、
Skill 模板路径及后续维护工作域。Agent 使用这些模板在项目的独立验证文档目录中，
结合只读输入和用户对话写出草稿。CLI 本身只生成计划投影，不自动写出下表正文。

| 正式文档 | 内容 | 后续维护 |
| --- | --- | --- |
| `verification_plan.md` | 范围、总体策略、风险和验收条件 | VDOC，面向整个验证工程 |
| `feature_matrix.md` | 验证点、来源、场景与检查/覆盖/用例映射 | 全部工作域 |
| `tb_architecture.md` | 接口、组件分层、数据流、构建与诊断 | VSTIM/VCHK/VREG |
| `reference_model_spec.md` | 验证侧模型接入、支持范围、比较合同或替代方案 | VCHK |
| `coverage_plan.md` | 采样、bins/cross、可达性与收敛口径 | VCOV |
| `assertion_plan.md` | property、挂接、失败处理与非空洞要求 | VCHK/VCOV |
| `testcase_list.md` | 用例目标、优先级、检查方式、实现与证据映射 | VCASE/VREG |

`code_coverage_waiver_manifest.md` 仅出现具体豁免候选时按需建立，由 VCOV 维护，
不是初始 VDOC 的必需产物。所有模板见[VDOC 产出与模板索引](../vplan/vdoc.md)。

`.verif-harness/workstreams/vdoc/plan.md` 表达“本轮准备完成哪些文档目标”，上表文件
承载实际验证设计，不能相互替代。输出目录优先沿用项目验证文档布局，否则采用
`<verif-root>/docs/verification`；与 RTL/spec 输入重叠时必须选择独立位置。
验证侧 `reference_model_spec.md` 的命名不会使同名原始 spec 变成可写文件。

VDOC 先形成可讨论的初版，允许其他工作域在其尚未全部完成时推进。未定内容标为
open question 并注明影响；不适用项写明原因和用户确认的替代策略。正文只保留当前设计，
评审、决策和历史运行通过记录 ID/证据链接引用。已有文档按需修订，不整套覆盖重建。

Agent 将每份输出的文件节点以 `AFFECTS` 关系关联对应 desired 节点，后续修改通过
`changed` 使消费者重新验证。计划批准不等于文档内容批准；文件存在、模板已复制也不
等于目标通过。只有真实内容经过用户评审后才登记相应 review evidence。
`--desired` 自定义目标仍替代默认七项，需要 Agent 显式关联实际文档。

### VDOC 完整执行步骤与角色

VDOC 使用三类责任标记：

- **Human**：提供工程判断、范围决定、内容批准、waiver 和 freeze 授权；
- **Agent**：当前 Codex/Kimi 会话，负责只读分析、提问、起草、执行已授权命令和解释结果；
- **Engine**：verif-harness CLI 的确定性部分，负责持久化、状态计算、证据摘要、失效传播和
  closure。Engine 不作工程判断。

| 步骤 | 责任主体 | 操作与结果 |
| --- | --- | --- |
| 0. 建立项目事实 | Human + Agent + Engine | Human 提供 DUT 信息；Agent 只读校验；Engine 通过 `bootstrap` 建立最小知识模型 |
| 1. 读取当前状态 | Agent + Engine | Agent 调用 `status VDOC`、`inspect`；Engine 返回当前模型、历史决策和缺口 |
| 2. 建立 proposal | Agent + Engine | Agent 调用 `plan VDOC`；Engine 创建新 revision、七个默认文档 desired node、退出条件和待答问题 |
| 3. 确认输出目录 | Agent；有歧义时 Human | Agent 沿用已有验证文档目录或提议 `<verif-root>/docs/verification`；与只读输入重叠或有多个候选时由 Human 选择 |
| 4. 读取输入与模板 | Agent | 只读分析 RTL、spec、已有验证文档、Knowledge Model 和本轮所需模板，不搜索或替换用户未指定的 DUT 输入 |
| 5. 形成初始草案 | Agent | 先提出 scope 和 Feature/VF 分解，再补充策略、架构、reference model、coverage、assertion 和 testcase 候选内容 |
| 6. 解决开放决策 | Human + Agent | Agent 只询问事实无法确定的问题；Human 作出工程选择；Agent 将答案及其影响目标写入新 revision |
| 7. 审批 desired scope | Human | Human 对本轮目标和退出条件作出 `approve/reject/modify/clarify` 决定；Agent 不得代批 |
| 8. 记录规划审批 | Agent + Engine | 收到 Human 明确决定后，Agent 调用 `review VDOC`；Engine 将 revision 更新为 `ACTIVE` 或 `REVISE` |
| 9. 生成文档 Draft | Agent | 在可写的验证输出目录创建或增量修改所需文档；所有 RTL 和原始 spec 保持只读 |
| 10. 登记追踪关系 | Agent + Engine | Agent 登记或复用文件节点和 `AFFECTS`/跨工作域依赖；Engine 写入 Knowledge Model |
| 11. 检查一致性 | Engine + Agent | Engine 通过 `check` 扫描已登记事实并传播状态；Agent 解释冲突、缺失链接和开放问题 |
| 12. 评审文档内容 | Human + Agent | Agent 展示正文、来源、差异和遗留问题；Human 判断内容能否作为当前验证基线 |
| 13. 登记评审证据 | Agent + Engine | Human 明确接受后，Agent 通过 `prove` 登记真实 review evidence；Engine 校验文件、计算摘要并更新目标有效性 |
| 14. 计算下一动作 | Engine + Agent | Engine 通过 `closure` 给出最小未闭合动作；Agent 向 Human 解释，不静默执行写操作 |
| 15. 冻结 VDOC | Human + Agent + Engine | Human 明确授权；Agent 调用 `freeze VDOC`；Engine 检查条件并生成不可覆盖的 baseline |
| 16. 后续修订 | Agent + Engine + Human | Agent 登记 `changed`；Engine 传播 `STALE`/`REVALIDATION_REQUIRED`；Agent 只修订受影响内容，Human 重新评审 |

VDOC 的典型命令顺序如下。命令由 Agent 在当前会话执行；表中标为 Human 的决定必须先
由用户明确给出：

```text
# Agent + Engine：建立 proposal
verif-harness status VDOC
verif-harness plan VDOC

# Human：回答 questions_for_human，确认 desired scope
# Agent + Engine：仅在收到明确 verdict 后记录规划审批
verif-harness review VDOC --verdict approve --reviewer <human-name>

# Agent：生成 Draft，并登记文档节点和依赖关系
# Agent + Engine：检查一致性和未闭合动作
verif-harness check
verif-harness status VDOC
verif-harness closure

# Human：评审具体文档内容
# Agent + Engine：仅在 Human 明确接受后登记真实评审证据
verif-harness prove <VDOC-DESIRED-NODE> <REVIEW-EVIDENCE-FILE> \
  --kind human-review

# Human：明确授权冻结
# Agent + Engine：验证条件并冻结当前 revision
verif-harness freeze VDOC --reviewer <human-name> \
  --reason "VDOC revision reviewed and accepted"
```

这里存在两个不能合并的 Human gate：

1. **规划审批**：`review VDOC` 只批准 desired scope、交付范围与退出条件，允许 Agent
   按此开展文档工作；
2. **内容审批**：Human 逐份检查实际文档后，Agent 才能登记 review evidence。文档存在、
   模板已复制或 Agent 自检通过都不是内容批准。

职责边界可以概括为：

```text
Agent：读取、分析、提问、提出方案、生成 Draft、登记关系、执行检查
Human：工程取舍、范围确认、内容批准、waiver、freeze
Engine：持久化、状态计算、证据摘要、失效传播、closure、冻结条件检查
```

即使由 Agent 在终端输入了 `review`、`prove` 或 `freeze`，授权来源仍必须是当前 Human。
Agent 生成七份 Markdown 也不表示 VDOC 完成；只有对应 desired node 获得真实评审证据，
并满足本轮退出条件后，VDOC 才能进入 baseline。

### 步骤 2：规划实现类 Workstream

根据项目情况规划所需工作域：

```text
verif-harness plan VSTIM
verif-harness plan VCHK
verif-harness plan VCASE
verif-harness plan VCOV
verif-harness plan VREG
```

可以先规划 VCHK 再规划 VSTIM，也可以同时推进。若多个 Workstream 都在 `REVIEW`，
审批时必须指明目标：

```text
verif-harness review VSTIM
verif-harness review VCHK
```

六个通用模板的关注点：

| Workstream | 典型输入 | 典型产物/证据 | 常见回跳原因 |
| --- | --- | --- | --- |
| `VDOC` | 规格、RTL 清单、历史决策 | feature/策略/架构/退出标准 | 实现暴露规格歧义 |
| `VSTIM` | transaction contract、场景目标 | driver/sequence/constraint、可达性证据 | coverage hole、场景不可达 |
| `VCHK` | compare policy、reference behavior | scoreboard/refmodel/assertion、检查证据 | mismatch 无法归因 |
| `VCOV` | feature/case/checker 映射 | coverage model/report/hole disposition | 缺 stimulus/case/checker |
| `VCASE` | feature 和 scenario | testcase/virtual sequence、targeted run | case 不可诊断或覆盖不足 |
| `VREG` | 可执行 case、工具配置 | regression result、triage、fresh evidence | RTL/TB 变化或失败聚类 |

### 步骤 3：执行当前最小动作

```text
verif-harness status
verif-harness closure
```

Verification Closure Engine 为每个 gap 返回：

- `target`：要满足的 node；
- `executor`：`deterministic`、`reasoning` 或 `human`；
- `suggested_mode`：建议使用的工具/能力；
- `reason`：产生动作的原因。

按 action 执行生成器、xverif、WavePeek、仿真或人工讨论。CLI 不启动隐藏 worker，
也不会把一个大型 task 放进后台等待 stdin。需要人工输入时，问题就在当前 Agent 会话中
完成；回答后记录决策或重新 plan。

### 步骤 4：记录事实和证据

最常用的是 `prove`：

```text
verif-harness prove NODE results/smoke.json
verif-harness prove NODE results/failure.json --fail --kind simulation
```

`NODE` 来自 `status`/`closure`。source 必须是项目内真实文件；系统保存相对路径、摘要、
kind 和 verdict。默认是通过证据，因为命令本身明确表达“证明”；失败用 `--fail`。

新 artifact、关系等高级事实通过 `record` 写入，见[命令参考](#6-完整命令参考)。
证据与变更等结构化写入会更新相关节点状态并重算 closure；这不意味着每次都执行完整
文件扫描。扫描使用 `check`，动作与失效传播规则见[工作机制](mechanism.md)。

### 步骤 5：处理变化和失效

RTL、规格或验证资产变化时：

```text
verif-harness changed rtl/dut.sv
verif-harness changed docs/spec.md
verif-harness status
```

常见 RTL/文档后缀会自动分类为 `rtl-change`/`spec-change`；其他文件默认为
`modify`。Verification Consistency Engine 从该文件沿关系传播 `STALE` 或
`REVALIDATION_REQUIRED`，Verification Closure Engine
重新计算动作。旧 evidence 和 baseline 不会被覆盖。

### 步骤 6：冻结单个 Workstream

当 Workstream 已经 Human approve，且所有 required desired state 为 `VALID` 或
Human `WAIVED`：

```text
verif-harness freeze VDOC
```

只有一个 ready Workstream 时也可直接运行 `verif-harness freeze`。系统生成内容寻址、
不可覆盖的 baseline manifest。若 closure 仍有 action，freeze 会 fail closed。

### 步骤 7：最终冻结

六个 Workstream 都已存在并分别 `BASELINED`，且 audit 没有 open finding 或缺失文件后：

```text
verif-harness freeze final
```

final freeze 只封存当前已审核事实，不等于工具替项目做出 sign-off 决策。后续项目变化
应形成新 revision 和新 baseline，不能改写旧 manifest。

## 4. 日常闭环场景

### Coverage hole 路由回 stimulus

```text
verif-harness changed verification/coverage/model.sv
verif-harness closure
verif-harness impact file:verification/coverage/model.sv
verif-harness plan VSTIM --decision "补充 backpressure × error 组合"
```

### Checker mismatch 有多种解释

确定性日志和波形不足以判断 DUT bug、checker bug 或规格歧义时：

```text
verif-harness reason DebugEngineer "分析 mismatch 的候选根因" \
  --context results/mismatch.json --context waves/failing.vcd
```

Verification Reasoning Engine 只返回分析请求/建议；真实验证动作仍须执行并通过 `prove` 记录。

### Human waiver

```text
verif-harness waive NODE --reason "该场景在当前产品配置中不可达，依据 DEC-017"
```

waiver 只允许用于已规划 Workstream node，必须提供理由，reviewer 默认从 git identity
推导。Agent 不得自行运行该命令。

## 5. 状态、文件与治理边界

这里的状态来自 [Verification Knowledge Model](glossary.md#subsystems)。
[Desired/current state](glossary.md#desired-current) 的差距形成
[gap、finding 和 action](glossary.md#gap-action)；动作产生的
[artifact/evidence](glossary.md#evidence) 经登记后改变节点
[validity](glossary.md#validity)。工作域达到条件后，经过
[Human gate](glossary.md#human-gate) 创建 [baseline](glossary.md#baseline)。
完整事件示例见[从工程动作到证据](mechanism.md#4-工程动作怎样成为证据)。

### 5.1 Validity

| 状态 | 含义 |
| --- | --- |
| `UNKNOWN` | 尚无足够事实 |
| `VALID` | 有通过 evidence 支持 |
| `STALE` | 直接依赖发生变化 |
| `REVALIDATION_REQUIRED` | 上游变化，需要重新验证 |
| `INVALID` | 失败 evidence 或确定性检查失败 |
| `REVIEW_REQUIRED` | 需要人工评审 |
| `BLOCKED` | 当前无法推进 |
| `WAIVED` | Human 有理由接受该 gap |

不能用 `record status ... VALID/WAIVED` 绕过治理：`VALID` 只能由 evidence 建立，
`WAIVED` 只能由 Human waiver 建立。

### 5.2 Workstream lifecycle

`REVIEW → ACTIVE → SATISFIED → BASELINED` 是常见路径；replan 可回到 `REVIEW`，
change 可进入 `PARTIALLY_STALE`，reject/modify/clarify 可进入 `REVISE`。

### 5.3 项目文件

```text
.verif-harness/
├── model.sqlite3                 # 验证知识状态：节点、关系、评审等
├── project.json                  # bootstrap manifest
├── inventory.json                # 文件清单投影
├── model.md                      # 人工阅读投影
├── workstreams/<name>/
│   ├── desired-state.json        # 当前 desired revision 投影
│   └── plan.md                   # 简洁人工阅读投影
└── baselines/
    ├── <workstream>/<id>/manifest.json
    └── final/<id>/manifest.json
```

不要通过编辑阅读投影改变机器状态；所有 mutation 必须走 CLI。
`project.json` 也被 CLI 用来读取项目身份和 runtime，属于配置清单；它与纯阅读投影
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
| `--rtl-root PATH` | 声明 RTL 根目录；可重复 |
| `--docs-root PATH` | 声明文档根目录；可重复 |
| `--verif-root PATH` | 声明验证资产根目录 |
| `--dut-top MODULE` | 明确 DUT top；不会自动猜测 |
| `--dut-top-file PATH` | 明确 DUT top 文件 |
| `--refresh` | 刷新非语义 inventory；保留已存在语义状态 |

已 bootstrap 的项目再次运行必须加 `--refresh`，防止意外覆盖。
上述参数属于底层自动化接口；Skill 首次初始化必须先在对话中收齐三个必填 DUT 字段。
用户提供的可选 spec 路径映射到 `--docs-root`，未提供时不推导或补填。

### `status [WORKSTREAM]`

无参数显示全局模型、Workstream 和 ranked actions；指定 Workstream 只显示其 plan 与
只读 closure。WORKSTREAM 为 `VDOC/VSTIM/VCHK/VCOV/VCASE/VREG`。

### `plan WORKSTREAM`

人用短命令；等价于结构化命令 `plan design --workstream WORKSTREAM`：

```text
verif-harness plan VCHK [--objective TEXT] [--desired TEXT] \
  [--exit TEXT] [--decision TEXT]
```

| 参数 | 说明 |
| --- | --- |
| `--objective TEXT` | 覆盖模板目标；省略时用内置目标 |
| `--desired TEXT` | 自定义 required desired state；可重复；一旦提供则替代模板 desired 列表 |
| `--exit TEXT` | 自定义退出标准；可重复；省略时用模板 |
| `--decision TEXT` | 记录已确认决策；可重复 |

高级查询当前 plan：`plan show --workstream WORKSTREAM`。

### `review [WORKSTREAM]`

```text
verif-harness review [WORKSTREAM] \
  [--verdict approve|reject|modify|clarify] \
  [--reviewer NAME] [--reason TEXT]
```

- 默认 verdict：`approve`；
- 未指定 Workstream 时，只在唯一 `REVIEW/REVISE` 候选时自动推导；
- reviewer 依次从 `git user.name`、`GIT_AUTHOR_NAME`、`USER` 推导；
- approve 的 reason 有审计默认值；其他 verdict 必须显式传 `--reason`；
- 该命令是 Human gate，Agent 只有收到用户明确批准后才能调用。

结构化等价命令：`plan review --workstream ...`。

### `prove SUBJECT SOURCE`

```text
verif-harness prove SUBJECT SOURCE [--kind KIND] [--fail]
```

默认 `kind=verification`、verdict=`pass`。`--fail` 记录失败证据。SOURCE 必须存在、
位于项目内且为文件；系统计算 SHA-256 digest。

### `changed PATH`

```text
verif-harness changed PATH \
  [--kind auto|add|modify|delete|rename|spec-change|rtl-change] \
  [--revision REVISION]
```

默认 `auto`；`--revision` 可绑定 commit/build revision。

### `waive NODE`

```text
verif-harness waive NODE --reason TEXT [--reviewer NAME]
```

reason 永远必填；reviewer 的推导规则与 review 相同。这是 Human gate。

### `freeze [WORKSTREAM|final]`

```text
verif-harness freeze [WORKSTREAM|final] [--reviewer NAME] [--reason TEXT]
```

- 不指定 Workstream 时只在唯一 ready 候选时推导；
- `freeze final` 要求六个 Workstream 全部 BASELINED 且 audit 通过；
- reviewer 自动推导，reason 有审计默认值；
- 这是 Human gate，且 baseline 不可覆盖。

结构化等价命令：`plan freeze --workstream ...` 或 `plan freeze --final`。

### `inspect`、`trace`、`impact`

只读查询：

```text
verif-harness inspect                  # 全部验证知识状态
verif-harness inspect NODE             # 单 node
verif-harness trace NODE               # 入边、出边、finding、evidence
verif-harness impact NODE              # 下游依赖影响闭包
```

第一行应使用 `verif-harness inspect`。`model show/trace/impact` 仅为旧自动化保留，
不建议在人用流程中继续使用。

### `check`

```text
verif-harness check
```

扫描项目内已登记文件和确定性结构事实，传播 validity 并自动 reconciliation。
`check scan` 是结构化兼容拼写。它不修代码、不作 waiver、不审批。

### `closure [--workstream WORKSTREAM]`

```text
verif-harness closure
verif-harness closure evaluate --workstream VCHK
```

无 Workstream 时重算全局 closure 和 ranked actions；局部形式只计算指定 Workstream。

### `reason`

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

`record` 是 Agent、adapter 和 CI 使用的低层结构化写入口，普通用户优先使用
`prove/changed/waive`。

```text
record node NODE --type TYPE --title TEXT
  [--workstream WORKSTREAM]
  [--status STALE|INVALID|REVIEW_REQUIRED|REVALIDATION_REQUIRED|BLOCKED|UNKNOWN]

record edge SOURCE TARGET --relation RELATION
  [--origin explicit|inferred|runtime] [--confidence 0..1]

record status NODE STATUS

record evidence --subject NODE --kind KIND --source FILE
  --verdict pass|fail

record change --path PATH
  --kind add|modify|delete|rename|spec-change|rtl-change
  [--revision REVISION]

record waive NODE --reviewer NAME --reason TEXT
```

约束：node ID 不得含空白；edge 两端必须存在；inferred relation 应提供真实 confidence；
新 node 不能直接为 `VALID/WAIVED`；evidence source 必须是真实文件。

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
`xverif/INSTRUCTIONS.md`、`wavepeek/INSTRUCTIONS.md`。xverif 负责确定性执行与结果采集，
WavePeek 负责有边界的波形检查；二者输出只有通过 `prove`/`record evidence` 绑定到目标后
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
