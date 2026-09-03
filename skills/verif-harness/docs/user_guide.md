# verif-harness v1 用户指南

本文只讲安装和操作。项目定位、适用对象与治理理念见仓库
[README](../../../README.md)，内部边界见[架构说明](../../../ARCHITECTURE.md)。

## 1. 两种入口

### 1.1 在 Agent 会话中使用（推荐）

完成 setup 后，在项目目录启动 Agent：

- Codex：对话中输入 `$verif-harness`，再说明目标；
- Kimi：对话中输入 `/skill:verif-harness`，再说明目标。

例如：“`$verif-harness 规划 VDOC，并只询问模型无法确定的决策`”。Agent 会读取
Skill 约束，再调用项目级 CLI。Human review、waiver 和 freeze 必须由用户明确要求，
Agent 不得自行批准。

### 1.2 直接调用 CLI

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
`questions_for_human`、`findings`、`evidence` 与 `baseline`。

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

进入 setup 指定的 workspace：

```text
verif-harness bootstrap
verif-harness status
verif-harness doctor
```

`bootstrap` 自动清点项目内 RTL、文档和元数据并建立最小 Verification Knowledge Model；它不会生成验证语义、
不会猜 DUT top，也不会创建总 `plan.md/tasks.md`。常见目录无法表达项目边界时才覆盖：

```text
verif-harness bootstrap \
  --rtl-root rtl --docs-root docs --verif-root verification \
  --dut-top dut --dut-top-file rtl/dut.sv
```

### 步骤 1：形成 VDOC desired state

```text
verif-harness plan VDOC
verif-harness status VDOC
```

Verification Planner 合并 VDOC 通用模板、当前知识模型与项目清单，产生 proposal 和真正需要人工确认的
`questions_for_human`。在 Agent 会话回答这些问题；需要修改时再次运行 `plan VDOC`，
形成新 revision。

确认 proposal 后，由 Human 明确执行：

```text
verif-harness review
```

当且仅当只有一个 Workstream 等待评审时，目标可省略；默认 verdict 是 `approve`，
reviewer 从 `git user.name` 推导。拒绝或要求修改必须说明原因：

```text
verif-harness review VDOC --verdict modify --reason "接口 reset 语义仍不清楚"
```

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
每次结构化写入后都会自动执行 Verification Consistency Engine 和 Verification Closure Engine。

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
├── model.sqlite3                 # 唯一机器事实源
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

不要通过编辑 Markdown/JSON 投影改变机器状态；所有 mutation 必须走 CLI。

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
