# verif-harness v1 用户指南

## 1. 基本调用方式

Codex 中使用 `$verif-harness`，Kimi 中使用 `/skill:verif-harness`。下文用
前者。项目只有一个[机器事实源](#verification-model)：
`.verif-harness/model.sqlite3`；JSON/Markdown 是人工阅读投影。

```text
$verif-harness bootstrap --rtl-root rtl --docs-root docs
$verif-harness status
$verif-harness doctor
```

Bootstrap 只发现项目、revision、文件元数据和工具能力，建立最小
[Verification Model](#verification-model)，不生成验证语义或总计划。

## 2. 全流程与全部 Workstream

项目生命周期与工程工作域分开。项目保持 `ACTIVE`，直到 closure 和 final
freeze；工程工作在六个可并行、可重入的 [Workstream](#workstream) 中进行：

| Workstream | 负责内容 |
| --- | --- |
| `VDOC` | 验证文档、feature/strategy、architecture、risk/decision |
| `VSTIM` | driver、sequence、constraint、scenario/stimulus |
| `VCHK` | reference model、scoreboard、checker、assertion |
| `VCOV` | functional/code/assertion coverage、goal 与 hole |
| `VCASE` | testcase、virtual sequence、scenario composition |
| `VREG` | compile、simulation、regression、rerun、triage、fresh evidence |

每个 Workstream 都使用同一组命令，且 `--objective`、`--desired`、`--exit`
可省略，默认采用详细通用模板：

```text
# 形成模板 + 当前 VModel 驱动的 proposal
$verif-harness plan design --workstream VDOC

# 在当前 Agent 会话回答 open decisions；按回答修订
$verif-harness plan design --workstream VDOC \
  --desired "接口、feature 与 checking strategy 已评审" \
  --decision "backpressure 属于 required scenario"

# Human review
$verif-harness review --workstream VDOC --verdict approve \
  --reviewer NAME --reason "proposal 与项目实际一致"

# 自动 reconciliation 之外，显式检查/调试
$verif-harness vcheck
$verif-harness closure evaluate --workstream VDOC

# desired state 有真实 evidence 后冻结不可变 snapshot
$verif-harness freeze --workstream VDOC \
  --reviewer NAME --reason "required desired state 已满足"

# 六个 Workstream 的 baseline 均满足后做最终冻结
$verif-harness freeze --final --reviewer NAME --reason "sign-off approved"
```

不要求先完成 VDOC 再开始 VSTIM，也不要求一个 Workstream 100% 完成才进入
另一个。coverage finding 可以路由回 VSTIM；checker mismatch 可以路由回 VDOC；
RTL change 可以同时使 VCHK 与 VREG 进入 revalidation。

## 3. Workstream 内部步骤与细节

每个 Workstream 都是局部循环，不是一次性任务：

```text
Desired -> Plan -> Act -> Observe -> Evaluate -> Replan
   ^                                            |
   +--------------------------------------------+
```

1. **VPlan proposal**：载入该 Workstream 的详细模板、项目上下文和当前 VModel；
   已知事实自动填入，只把真正的 [Open Decision](#open-question--human-decision)
   留给工程师。
2. **Human dialogue**：Agent 在当前交互会话提问。CLI 不启动后台 worker，也不
   让隐藏进程等待 stdin。
3. **Desired state**：写入 revisioned `desired-state.json`，同时生成简洁
   `plan.md`；二者不是 `tasks.md`。
4. **Review**：Human `approve/reject/modify/clarify`。Agent 不代批。
5. **Act**：VClosure action 指定 `deterministic/reasoning/human` executor 与
   suggested capability；确定性动作优先调用 xverif、WavePeek 或生成器。
6. **Record/Check**：artifact、edge、evidence 或 change 通过结构化 `record`
   写入；随后自动运行 VCheck/VClosure。
7. **Replan**：新 evidence/finding 可修订当前 Workstream，也可直接跳到其他
   Workstream。旧 desired revision 变为 `STALE`，但历史仍可追溯。
8. **Freeze**：当前 desired state 满足且经过 Human review 后生成不可覆盖的
   baseline manifest。后续变化不修改旧 snapshot，只产生新 revision/baseline。

常用事实入口与只读查询：

```text
$verif-harness model show [NODE]
$verif-harness model trace NODE
$verif-harness model impact NODE

$verif-harness record node VF-001 --type verification-feature \
  --title "正常流握手" --workstream VDOC
$verif-harness record edge SOURCE TARGET --relation VALIDATED_BY
$verif-harness record evidence --subject NODE --kind simulation \
  --source results/smoke.json --verdict pass
$verif-harness record change --path rtl/dut.sv --kind rtl-change --revision COMMIT
```

VModel 对人只读。所有 mutation 都经过 `record`，从而不会绕开 provenance、
validity 与自动 reconciliation。

## 4. 持续治理流程

全局闭环始终存在：

```text
Change / Evidence
       -> VModel
       -> VCheck (判断 validity，不执行修复)
       -> VClosure (选择 gap/action，不写代码)
       -> Tool / VReason / Human
       -> Result
       -> VModel
```

推荐追踪链：

```text
REQ -> VF -> DESIRED -> ACTION -> MODE -> ARTIFACT -> EVIDENCE -> REVIEW
```

- 确定性事实和动作走工具；只有语义不确定性进入 VReason。
- VReason 使用 [Role × Backend](#vreason)，角色与 Codex/Kimi/Claude 后端分离。
- relation 来源是 `explicit`、`inferred` 或 `runtime`；推断关系必须有 confidence。
- validity 包含 `VALID`、`STALE`、`INVALID`、`REVIEW_REQUIRED`、
  `REVALIDATION_REQUIRED`、`BLOCKED`、`WAIVED`、`UNKNOWN`。
- Human gate 放在语义、风险、waiver 和 baseline 边界，不放在每条命令前。

VPlan 的详细模板、当前 VModel、Human dialogue、structured desired state 与文档
投影共同构成唯一规划闭环；不再叠加 `spec -> plan -> tasks -> implement` 的第二套
生命周期，以免与持续 invalidation/replan 冲突。

## 5. 关键术语与概念

### Verification Model

保存 intent、desired state、实现、artifact、evidence、关系、validity、finding、
review 和 baseline 的 typed graph。SQLite 是 authority，Markdown 只是 projection。

### Workstream

带 desired/current state、finding、decision、evidence 和 revision 的可重入工作上下文。
它不是状态机步骤；六个 Workstream 可以同时活跃并任意跳转。

### Desired state

当前 Workstream 希望成立且可验证的状态，不是执行步骤清单。每次 replan 生成新
revision；VClosure 根据 desired/current gap 动态派生 action。

### Open question / Human Decision

Open question 是缺少信息、不能可靠闭合的问题。涉及接口语义、风险、waiver、
baseline 或发布的结论属于 Human Decision；Agent 只能提出、记录和提醒。

### Evidence

具有 subject、source、kind、digest、verdict 和 provenance 的可追溯结果。工具
退出码或 Agent 文本本身不自动构成语义 evidence。

### VReason

后端无关的语义推理接口。`Role`（VerificationArchitect、DebugEngineer 等）描述
职责，`Backend`（Codex、Kimi、Claude）描述执行能力。响应必须结构化，不能替代
VCheck、真实 evidence 或 Human approval。

### Baseline

不可变 snapshot，至少绑定 project revision、Workstream desired revision、模型
节点、关系、finding、evidence 和 Human review。工作区继续演化；旧 baseline 不回写。

## 6. Mode 与工具索引

- 核心：`bootstrap`、`vplan`、`vmodel`、`record`、`vcheck`、`vclosure`、`vreason`。
- 证据：`xverif`（别名 `evidence`）、`wavepeek`（别名 `waveform`）。
- 实现：interface/package/UVC/harness/env/build/test/coverage/assertion/refmodel。
- 闭合：regression/triage/coverage/assertion/traceability/change/signoff/freeze/release。

底层 capability 只有在 VClosure action 与当前权限允许时才执行；DUT RTL 始终只读。
