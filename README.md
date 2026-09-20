# verif-harness

verif-harness 是面向 [RTL/ASIC 验证项目](skills/verif-harness/docs/glossary.md#dv-terms)的持续验证
[控制面](skills/verif-harness/docs/glossary.md#control-plane)。它把验证目标、工程事实、
变更影响、验证证据和人工决策放进同一个可追溯模型，让项目能够持续回答：

- 当前想证明什么？
- 现在已经实现和证明了什么？
- 哪些结论因 RTL、规格或验证环境变化而失效？
- 下一步应执行工具、调用推理，还是等待人工决策？
- 依据什么证据可以冻结 Workstream 或最终验证基线？

它不是新的仿真器，也不是一份从头跑到尾的 `tasks.md`。它位于工程师、
[Agent](skills/verif-harness/docs/glossary.md#control-plane)、
xverif、WavePeek、仿真器、回归系统和验证代码之上，负责持续规划、治理和追溯。

这里“可复用”的是 ASIC 验证控制能力，不是通用项目管理模板。工作流、工作节点、进度、
依赖和完成条件必须由当前被验证设计（DUT）、接口、功能、验证点、场景和证据决定，因此
不同验证对象可以有不同的节点类型和数量。面向用户的主要页面先用清楚的中文说明验证对象、
当前结论、依据、缺口和下一步；行业已有术语保留标准写法并解释含义，不机械翻译，也不另造词。
即使使用者不是 ASIC 验证工程师，也应能理解当前状态和需要采取的动作；专业细节仍保留在详情中。

## 给谁使用

- **验证工程师**：规划验证目标，组织激励、检查器、覆盖率、用例和回归工作。
- **验证负责人/Reviewer**：评审 [desired state](skills/verif-harness/docs/glossary.md#desired-current)、
  处理风险与[豁免](skills/verif-harness/docs/glossary.md#human-gate)、冻结可审计基线。
- **验证基础设施工程师**：把编译、仿真、波形、回归和
  [代码生成器或激励生成器](skills/verif-harness/docs/glossary.md#dv-terms)接入统一控制面。
- **Codex/Kimi Agent**：依据当前模型执行有边界的工程动作，而不是凭聊天历史猜测状态。

它适合验证工作反复迭代、并行推进的项目。文档、验证环境、激励、检查器、覆盖率、用例和回归
都可以随新发现重新打开，不要求按固定 Stage 顺序一次做完。

## 能做什么

verif-harness 将验证工程划分为七个可以同时推进、发现问题后可以重新打开的
[Workstream（工作域）](skills/verif-harness/docs/glossary.md#workstream)：

| Workstream | 负责内容 |
| --- | --- |
| `VDOC` | 验证定义、验证点、架构、策略、风险和决策 |
| `VENV` | 验证环境的接口连接、时钟复位、组件结构、构建、最小运行入口和观测点 |
| `VSTIM` | [driver、sequence、constraint 和场景激励](skills/verif-harness/docs/glossary.md#dv-terms) |
| `VCHK` | [reference model、scoreboard、checker 和 assertion](skills/verif-harness/docs/glossary.md#dv-terms) |
| `VCOV` | [coverage model、采集和 coverage hole 处理](skills/verif-harness/docs/glossary.md#dv-terms) |
| `VCASE` | [testcase、virtual sequence 和场景组合](skills/verif-harness/docs/glossary.md#dv-terms) |
| `VREG` | [compile、simulation、regression、rerun 和 triage](skills/verif-harness/docs/glossary.md#dv-terms) |

围绕这些 Workstream，它提供：

- 详细通用模板与当前项目事实驱动的 [desired-state](skills/verif-harness/docs/glossary.md#desired-current) 规划；
- [node、relation、validity、finding 和 evidence](skills/verif-harness/docs/glossary.md#knowledge) 模型；
- Agent 用 `changed PATH` 登记 RTL/spec/验证文件已修改后，自动找出需要重新验证的下游目标；
- 根据当前[未完成项](skills/verif-harness/docs/glossary.md#gap-action)，重新列出并按规则排序下一步建议；
- xverif、WavePeek、回归及代码生成能力的受控接入；
- [Human review 和 waiver](skills/verif-harness/docs/glossary.md#human-gate)、
  [Workstream baseline 和 final freeze](skills/verif-harness/docs/glossary.md#baseline) 审计链；
- 可编辑验证文档与 SQLite 状态分离；`docs sync` 用 SHA-256 判断文档是否修改，并按需生成
  [状态阅读文件](skills/verif-harness/docs/glossary.md#authority)；
- Codex/Kimi 运行环境、受管 Python 依赖和项目级 xverif MCP 配置。
- 本机实时 [Dashboard](skills/verif-harness/docs/glossary.md#dashboard)：总览以默认折叠的项目/DUT、
  Agent 交互、待处理事项、验证工作流和验证风险与变更作为入口；状态摘要点击后在新标签页查看或
  处理。Closure 需要正式评审时，revision-aware 人工检查点可让等待中的 Agent 在收到 Dashboard
  决定后继续。
- 每个目标节点显示一份可复核的
  [节点完成结论](skills/verif-harness/docs/glossary.md#node-closure-assessment)：Engine 列出使用的规则、
  证据、前置节点、开放问题和逐项检查结果；Human 可以认可、要求修改、要求说明或拒绝该结论，
  但评审不会凭空创建 PASS 证据。
- VDOC 在 Dashboard 中以正式文档作为父节点，节点内展示正文版本、内容变化、开放问题、工程决定
  和评审记录；Human 可直接预览当前 Markdown 正文并提交评审，无需直接输入评审命令。未处理的 `docs track` 问题会计入
  “待处理事项”，不会再只影响退出检查而在页面上显示为 0。

## 运行逻辑

用户表达目标，当前 Agent 根据 Skill 与用户对话，并调用 CLI 更新 Verification
Knowledge Model。CLI 返回待处理的缺口，Agent 再调用工程工具、检查结果和登记证据。
这个闭环由当前会话推进，五个子系统不是五个独立进程。

```text
用户提出目标
    |
    v
Planner（整理目标）---- 用户确认 ----> 本轮目标
    |                                |
    v                                v
SQLite 状态库 <--- 验证证据 --- 工程工具 / 仿真器
    |
    +----> 检查文件和证据 ----> 结论是否仍有效 + 发现的问题
    |                         |
    +----> 列出当前未完成项 <--------+
                 |
                 +---- 运行固定规则工具
                 +---- 请求 Agent 分析
                 +---- 等待用户决定
```

例如用户希望“backpressure 下输出比较正确”：

1. Planner 将目标组织为 VCHK 的 [desired state](skills/verif-harness/docs/glossary.md#desired-current)，由用户评审。
2. 当前目标还没有证据，Closure Engine 返回待实现/证明的 [action](skills/verif-harness/docs/glossary.md#gap-action)。
3. Agent 实现验证代码并运行测试，检查报告，再将结果登记为目标的 [evidence](skills/verif-harness/docs/glossary.md#evidence)。
4. 控制面更新状态、重新计算缺口。所有 required 目标满足后，用户可冻结该工作域。
5. 用户以后修改 RTL，Agent 调用 `changed PATH` 登记具体文件；系统再沿已登记依赖标出需要
   重新验证的目标。

标准 VENV/VSTIM/VCHK/VCOV/VCASE/VREG 目标必须通过 `evidence` 专用
[schema 和 validator](skills/verif-harness/docs/glossary.md#evidence-format)，由控制面从报告内容
生成 [verdict](skills/verif-harness/docs/glossary.md#evidence)；不能提交任意 PASS 文件。
Coverage、cover property 和波形只能作为 VSTIM 补充材料。Planner 把模板拆成
[capability/closure-evidence node](skills/verif-harness/docs/glossary.md#node-role)，并按当前
计划版本自动建立节点之间的默认依赖。完成条件检查还会检查相关证据、尚未回答的人工问题，
以及根据当前必需目标生成的[当前版本证据清单](skills/verif-harness/docs/glossary.md#runtime-evidence)。
`closure` 只返回动作建议，不自动执行；`reason` 生成
分析请求，不直接启动推理后端。具体规则见[工作机制](skills/verif-harness/docs/mechanism.md)。

编译 log、仿真 log、回归 manifest、VDB/UCDB 和波形只是
[工具原始输出](skills/verif-harness/docs/glossary.md#evidence-source)，不直接等于验证结论。
项目 adapter/extractor 将明确事实转换成绑定 revision 与原始文件 SHA-256 的 JSON 报告，
动态运行目标还必须同时登记 xverif 或 WavePeek 生成的结构化分析结果；再由专用 validator
决定节点状态。当前没有内置支持所有工具格式的 extractor。具体形式和
退出条件见[用户指南](skills/verif-harness/docs/user_guide.md#步骤-4把工程结果登记为证据)。

## 五个核心子系统

用户不需要启动五个程序。下面说明它们分别会在什么情况下出现，以及用户能看到什么结果：

| 子系统 | 什么时候使用 | 实际结果 |
| --- | --- | --- |
| [Verification Planner](skills/verif-harness/docs/glossary.md#subsystems) | 用户提出“规划 VCHK”或要求修改现有目标时 | 结合模板和当前项目状态，生成一份待用户确认的目标清单、退出条件和问题；不会直接开始实现 |
| [Verification Knowledge Model](skills/verif-harness/docs/glossary.md#subsystems) | `status`、`inspect` 或新 Agent 会话需要了解以前做到哪里时 | 从 SQLite 读出已经确认的目标、文件、证据、依赖和评审记录；不会凭聊天内容补造事实 |
| [Verification Consistency Engine](skills/verif-harness/docs/glossary.md#subsystems) | Agent 调用 `changed PATH`、`docs sync` 或 `evidence` 后 | `changed` 使用调用方明确给出的文件；`docs sync` 比较文档 SHA-256；`evidence` 检查报告格式和引用文件 SHA-256。随后标记需要重验的下游目标；不会后台监控或修改文件 |
| [Verification Closure Engine](skills/verif-harness/docs/glossary.md#subsystems) | 用户询问“现在还缺什么”或准备 freeze 时 | 列出当前阻塞目标、前置依赖和下一项建议动作；不会自行执行这些动作或批准冻结 |
| [Verification Reasoning Engine](skills/verif-harness/docs/glossary.md#subsystems) | 日志和固定规则无法判断 DUT bug、checker bug 或规格含义时 | 整理与问题直接相关的文件、日志和已知事实，生成分析请求和候选解释；分析结果仍需测试证据或 Human 决定确认 |

实际写验证代码、编译、仿真和读取波形由 Agent 调用工程工具完成；范围批准、豁免和冻结由
Human 决定。

## 治理原则

- 项目 VDOC Markdown 保存工程师需要直接阅读和修改的验证设计；
  `.verif-harness/model.sqlite3` 保存文件指纹、状态、评审、证据和依赖；`project.json`
  保存项目配置。供人查看的状态 Markdown 由 CLI 需要时生成。详见
  [哪些文件可以编辑](skills/verif-harness/docs/glossary.md#authority)。
- desired state 是“需要成立的状态”，不是必须顺序执行的 task 清单。
- `VDOC/VENV/VSTIM/VCHK/VCOV/VCASE/VREG` 是七类可以反复开展的工作，不是必须依次通过的步骤。
- 标准依赖建立在具体节点之间，而不是要求先完成整个工作域。例如 VSTIM 实现只等待
  VENV 的接口、组件结构和构建节点；VCHK 的运行证明才等待 VENV 的最小环境运行证明。
  因此各工作域仍可并行规划和局部推进。详见[工作流之间的依赖](skills/verif-harness/docs/mechanism.md#workstream-dependencies)。
- 能由固定输入和规则完成的工作交给工具；只有规格含义、失败责任或工程取舍无法由规则判断时，
  才交给 Verification Reasoning Engine 整理分析材料。
- `VALID` 必须由真实 evidence 建立；`WAIVED` 必须由 Human 明确给出理由。
- Workstream freeze 和 final freeze 生成用 SHA-256 标识、不能覆盖旧版本的基线记录。
- 所有 RTL 和 RTL spec 始终只读，当前 Agent 不得直接或通过工具更改；输入问题由用户处理。
  显式输入可以位于项目目录之外，但控制状态和所有生成产物必须保留在项目内。
  Agent 不得代替 Human 审批，也不得把工具退出码冒充 sign-off。
- proprietary RTL、规格、日志、向量、URL、license 和调度器配置不得进入公共仓库。

## 文档入口

- [工作机制](skills/verif-harness/docs/mechanism.md)：谁推动闭环、状态如何变化、
  动作如何生成、依赖失效如何传播，以及当前实现边界。
- [术语表](skills/verif-harness/docs/glossary.md)：目标、工作域、知识节点、证据、
  finding、closure、人工门禁、基线和 runtime 的含义与区别。
- [用户指南](skills/verif-harness/docs/user_guide.md)：安装、从 bootstrap 到 final freeze
  的完整步骤、全部命令及参数、常见闭环场景。
- [架构说明](ARCHITECTURE.md)：控制环、状态模型、子系统与 RTL 分层边界。
- [故障排查](skills/verif-harness/docs/troubleshooting.md)：运行环境与工具问题。
- [Skill 入口](skills/verif-harness/SKILL.md)：Codex/Kimi 使用 verif-harness 时的行为边界。

## 项目状态

v1 允许每个 Workstream 在发现新问题后重新打开，并持续检查还缺哪些目标和证据。
xverif、WavePeek 等可选能力
保持独立许可和发布边界；v1 主控制流程不依赖外部 specification workflow。

提交前运行 `make check`；公开发布候选运行 `make release-check`。测试通过只说明
结构和契约满足，不代表任何外部仿真器已得到验证或项目已经 sign-off。
