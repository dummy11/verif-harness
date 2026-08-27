# 用户指南：从 Stage 0 到 Verification Freeze

本文面向第一次使用 verif-harness 的验证工程师，按实际操作顺序说明：

1. 基本调用方式；
2. Stage 0–5 的完整操作代码；
3. 每个 Stage 的目标、步骤、产物、证据和退出条件；
4. Spec Kit 的规格治理、任务执行和评审流程；
5. 关键术语与概念；
6. mode 与工具索引。

正文中的关键术语链接到第五章。先按第一、二章跑通主流程，再根据第三、四章
处理 Stage 细节和 review gate。若项目状态不明确，先运行只读的
`$verif-harness doctor` 或 `$verif-harness status <run-id>`，不要猜测当前 Stage，
也不要绕过 workflow 直接执行写模式。

---

## 1. 基本调用方式

### 1.1 Codex 与 Kimi Code

在 setup 选定的 verification workspace 中启动 Agent CLI。setup 已经记录 workspace、
runtime 和对应 Skill，因此正常交互不需要重复传 `--project-root`、`--integration` 或
workspace 路径。

Codex 使用：

```text
$verif-harness <command> [arguments]
```

Kimi Code 使用：

```text
/skill:verif-harness <command> [arguments]
```

本文后续统一使用 Codex 写法。Kimi Code 只需把 `$verif-harness` 替换为
`/skill:verif-harness`，command 和参数保持不变。

### 1.2 第一次进入 workspace

```text
$verif-harness probe
$verif-harness bootstrap
$verif-harness doctor
```

- `probe`：验证固定版本 Spec Kit 和受管 Python runtime。
- `bootstrap`：初始化 `.specify/`、当前 Agent integration 和 RTL verification preset。
- `doctor`：只读检查项目状态并推荐下一安全动作。

即使 workspace 在 setup 开始时为空，setup 安装 Skill、MCP 等资产后目录也会变成
非空。仍然直接运行 `$verif-harness bootstrap`，不要添加 `--force`。wrapper 会先
确认 `.specify/` 不存在，再在内部非交互完成初始化；已有 `.specify/` 时会硬拒绝。

### 1.3 启动一个 Stage workflow

每次只启动一个明确的 [Stage](#term-stage)：

```text
$verif-harness stage --stage <0-5> --objective "本 Stage 的明确目标"
```

runtime-native launcher 会启动独立 worker，并立即返回：

- `run_id`；
- worker PID；
- `.specify/workflows/runs/<run-id>/verif-harness-worker.log`；
- 下一条 `status <run-id>` 命令。

不要用 600 秒 timeout 或其他外层后台任务包裹 `stage`，也不要在 worker 存活时重复
启动同一个 Stage。

### 1.4 查看状态与处理 review gate

```text
$verif-harness status <run-id>
```

重点读取以下机器字段：

| 字段 | 含义 |
| --- | --- |
| `status` | Spec Kit workflow 状态 |
| `worker_active` | 是否仍有 worker 正在修改该 run |
| `resume_allowed` | 当前是否允许调用 `resume` |
| `action_required` | 当前需要等待、评审、回答 blocker 或恢复 stale run |
| `next_action` | wrapper 给出的唯一安全下一动作 |

只有 `paused` 且 `action_required: review-gate` 时，完成真实评审后才能提交 verdict：

```text
$verif-harness resume <run-id> --verdict approve
# 或
$verif-harness resume <run-id> --verdict reject
```

当 `running` 且 `worker_active: true` 时，`resume_allowed` 为 false。即使用户之前已经
写了 `--verdict approve`，也不能调用 resume，只能等待并执行返回的 `next_action`。

当 task runner 报告 [TASK](#term-task) 为 `BLOCKED` 时，取得 Human 回答或 authority
引用后只恢复当前 task：

```text
$verif-harness resume <run-id> --answer "明确回答或 authority 引用"
```

只有确认外层进程异常终止、run 仍标为 `running` 且没有活 worker 时，才允许：

```text
$verif-harness recover <run-id> --confirm-stale
$verif-harness resume <run-id>
```

`recover` 不是普通重试命令，绝不能对 live worker 使用。

### 1.5 常用短命令

```text
$verif-harness help                 # 查看短命令
$verif-harness help coverage        # 查看映射、输入和权限边界
$verif-harness status <run-id>      # workflow 状态
$verif-harness docs                 # 刷新中文阅读镜像
$verif-harness trace                # traceability 审计
$verif-harness gate 3               # 生成 Stage 3 Draft gate packet
$verif-harness signoff 5            # 审计 Stage 5 sign-off packet
```

短命令和 canonical mode 的完整对照见[第六章](#mode-index)。

### 1.6 什么时候使用底层 Python wrapper

正常 Agent 交互优先使用 `$verif-harness`。以下形式只用于 CI、跨项目自动化或高级诊断：

```text
python3 scripts/verif_harness.py spec-kit status \
  --project-root <project> <run-id>
```

不要在普通 workspace 中重复传 setup 已经确定的 root 和 runtime，也不要绕过 Skill
的 [MODE](#term-mode)、权限和 [GATE](#term-gate) 边界。

---

## 2. Stage 0–5 完整操作代码

本章只列用户需要执行的主流程命令，所有 Stage 集中在这里。每个 Stage 内生成的
[TASK](#term-task) 由 persistent task runner 逐项分发到已评审的 [MODE](#term-mode)；
正常路径不要在 workflow 外手工重复调用 implementation mode。

### 2.1 一次性准备

```text
$verif-harness probe
$verif-harness bootstrap
$verif-harness doctor
```

### 2.2 Stage 0：规格与治理基线

```text
$verif-harness stage --stage 0 \
  --objective "建立可评审的验证规格、治理基线和最小工程骨架"

$verif-harness status <run-id>
$verif-harness resume <run-id> --verdict approve   # 仅用于当前 paused gate
# 重复 status → review → resume，直到 workflow 完成

$verif-harness gate 0
```

新项目的已评审 `tasks.md` 必须恰好包含一个 `mode: init` task。execution gate 批准后，
task runner 自动分发它；正常流程不再手工运行 `$verif-harness init`。

### 2.3 Stage 1：最小可运行验证环境

```text
$verif-harness stage --stage 1 \
  --objective "建立接口、UVC、harness、env、filelist 和 compile-only smoke"

$verif-harness status <run-id>
$verif-harness resume <run-id> --verdict approve   # 仅用于当前 paused gate
# 重复 status → review → resume，直到 workflow 完成

$verif-harness gate 1
```

### 2.4 Stage 2：功能检查与 reference model

```text
$verif-harness stage --stage 2 \
  --objective "建立可追踪 testcase、scoreboard 和 reference-model 对拍"

$verif-harness status <run-id>
$verif-harness resume <run-id> --verdict approve   # 仅用于当前 paused gate
# 重复 status → review → resume，直到 workflow 完成

$verif-harness trace
$verif-harness gate 2
```

### 2.5 Stage 3：Coverage 与 Assertion

```text
$verif-harness stage --stage 3 \
  --objective "实现已评审 coverage/assertion 计划并建立可审计证据"

$verif-harness status <run-id>
$verif-harness resume <run-id> --verdict approve   # 仅用于当前 paused gate
# 重复 status → review → resume，直到 workflow 完成

$verif-harness coverage-audit
$verif-harness assertion-audit
$verif-harness trace
$verif-harness gate 3
```

### 2.6 Stage 4：Regression、CI 与性能合同

```text
$verif-harness stage --stage 4 \
  --objective "建立确定性 regression、失败分诊、CI 和性能门禁"

$verif-harness status <run-id>
$verif-harness resume <run-id> --verdict approve   # 仅用于当前 paused gate
# 重复 status → review → resume，直到 workflow 完成

$verif-harness trace
$verif-harness gate 4
```

### 2.7 Stage 5：闭合、sign-off 与 freeze

```text
$verif-harness stage --stage 5 \
  --objective "闭合 traceability、coverage、assertion 和 regression 证据"

$verif-harness status <run-id>
$verif-harness resume <run-id> --verdict approve   # 仅用于当前 paused gate
# 重复 status → review → resume，直到 workflow 完成

$verif-harness trace
$verif-harness coverage-audit
$verif-harness assertion-audit
$verif-harness gate 5
$verif-harness signoff 5

# Human 明确授权 freeze，且工作树位于已评审 clean commit 后：
$verif-harness freeze

# 仅准备公开发布候选时运行；它不授权发布：
$verif-harness release
```

`gate`、`signoff`、`freeze` 和 `release` 只生成或审计候选材料，不替代 Human approval，
也不自动授权 commit、tag、push 或公开发布。

---

## 3. 每个 Stage 的步骤与细节

<a id="stage-0"></a>

### 3.1 Stage 0：规格、权限与治理基线

**目标**

建立唯一规格事实源、项目治理合同、DUT 只读边界、目录 ownership 和最小 M1.1
scaffold。Stage 0 不是完整 testbench 实现阶段。Spec Kit 规格文档与 init 派生文档的
职责和使用方式见[两套文档体系](#term-document-systems)。

**进入条件**

- workspace 和 Agent runtime 已由 setup 确定；
- DUT/specification 的来源与权限明确；
- 不把 proprietary RTL、日志、URL、license 或 scheduler 配置复制进公共仓库；
- `.specify/` 尚未初始化时先执行 bootstrap。

**步骤**

1. Spec Kit 建立或同步 constitution。
2. 在 `specs/` 中定义 [REQ](#term-req)、[VF](#term-vf)，并按
   [Stage 0 决策生命周期](#term-decision-lifecycle)，记录 Human Decision 和 Open Question。
3. 评审 spec，不能由 Agent 自行批准未知语义。
4. clarify 未决的接口、reset、时序、reference-model 和工具约束。
5. 生成 [PLAN](#term-plan)、checklist 和精简 [TASK](#term-task) 合同。
6. `review-tasks` 确认 mode、owned outputs、validation、evidence 和 dependencies。
7. `analyze` 检查歧义、重复权威和 traceability gap。
8. `authorize-execution` 后，task runner 自动分发唯一的 `mode: init` task。
9. `converge` 对照规格复核产物、证据与 validation。
10. 单独生成 Stage 0 gate packet，交由 Human 评审。

**典型 Artifact**

- `.harness-config.json`；
- `AGENTS.md`；
- `.harness/` 控制与 review 资产；
- Spec Kit 权威文档：`specs/<feature>/spec.md`、`plan.md`、`tasks.md`、checklists；
- init 派生文档：roadmap、verification plan、feature matrix、
  TB architecture、coverage/assertion plan、testcase list 和 review packet；
- 必需的 harness/UVM 目录骨架。

**最低 Evidence**

- bootstrap/runtime probe；
- `doctor` 结果；
- init task 的 outputs/evidence/validation postconditions；
- Stage 0 review packet；
- unresolved questions 与 Human Decisions 清单。

**退出条件**

- 单一规格权威明确；
- DUT RTL 保持只读；
- 所有 executable task 均为 `interaction: none`；
- 所有 `OPEN B###` 已解决后才允许 execution gate；
- Human 对 Stage 0 gate packet 作出独立决定。

<a id="stage-1"></a>

### 3.2 Stage 1：结构完整、可编译的最小环境

**目标**

建立 interface、shared package、UVC skeleton、harness、env、thin `tb_top`、显式
filelist 和 compile-only smoke。此阶段证明结构与编译链成立，不宣称功能验证闭合。

**步骤**

1. 从已评审接口合同生成 interface 和 transaction 类型。
2. 为每个协议边界建立 UVC skeleton。
3. 在 harness 层完成 DUT 实例化、端口映射、clock/reset、tie-off、adapter、bind。
4. 在 UVM env 层建立 agent、scoreboard/coverage shell、base test 和 `tb_top`。
5. 固化 compile order、filelist 和 simulator profile。
6. 运行 compile/elaboration/smoke，并归档确定性结果。
7. 审计 tests 不包含可由 interface/harness API 表达的 DUT hierarchy 路径。

**常见 task mode**

`interface`、`package`、`uvc`、`harness`、`env`、`build`、`simulator`。

**典型 Artifact**

- protocol interface；
- UVC class skeleton；
- harness、SVA/bind skeleton；
- env、base test、thin `tb_top`；
- filelist、Makefile fragment、simulator profile。

**最低 Evidence**

- compile order 审计；
- compile/elaboration/smoke 结果；
- DUT RTL dirtiness 检查；
- task-owned outputs 和 validation 记录。

**退出条件**

环境结构可以重复构建，DUT 与验证职责分层正确，尚未实现的行为以显式 TODO 或后续
VF/TASK 表达，不能把 skeleton 存在误报为 simulator support 或功能 PASS。

<a id="stage-2"></a>

### 3.3 Stage 2：功能场景、scoreboard 与 reference model

**目标**

把已评审 [VF](#term-vf) 落为 driver/monitor 行为、testcase、scoreboard 和可选
reference-model adapter，形成 REQ/VF/test/evidence 的功能追踪闭环。

**步骤**

1. 明确 protocol handshake、backpressure、reset 和非法输入合同。
2. 完成 UVC driver/monitor 行为，不从 DUT RTL 猜测协议语义。
3. 定义 exact、mask、tolerance、ordering、timeout 等 compare policy。
4. 接入经评审的 Golden/reference model；记录版本、语义和 adapter 边界。
5. 为正常、边界、错误与恢复路径增加 testcase/vseq。
6. 运行固定 seed 的功能 regression，并保留逐 testcase 结果。
7. 执行 traceability audit，确认每个 testcase 能回溯到 VF/REQ。

**常见 task mode**

`uvc-complete`、`scoreboard`、`refmodel`、`test`、`regression`、`evidence`、`waveform`。

**典型 Artifact**

- 完整 driver/monitor；
- scoreboard 与 compare policy；
- reference-model bridge；
- tests、sequences、caselist；
- regression manifest。

**最低 Evidence**

- testcase PASS/FAIL/TIMEOUT 状态；
- seed、命令、工具版本和 log 路径；
- scoreboard mismatch 证据；
- reference-model identity/provenance；
- REQ/VF/test 映射审计。

**退出条件**

计划内功能场景均有 testcase 和可复现结果；缺少 Golden、工具或输入时必须报告
`MISSING_ARTIFACT`、`TOOL_NOT_FOUND` 或 blocker，不能静默降级成 PASS。

<a id="stage-3"></a>

### 3.4 Stage 3：Coverage 与 Assertion

**目标**

把 coverage plan 和 assertion plan 转换为可执行、可追踪、可审计的实现与证据。

**步骤**

1. 评审 coverpoint、bin、cross、ignore/illegal bin 的精确定义。
2. 为每个 COV ID 生成 coverage skeleton 并关联 REQ/VF/test。
3. 评审 assertion antecedent、consequent、clock、disable/reset 和 vacuity 语义。
4. 为每个 ASRT ID 生成 checker/bind skeleton。
5. 证明 assertion 已 compile、bind 且产生 attempts，而不仅是“文件存在”。
6. 汇总 coverage hits、holes、exclusions 和 totals。
7. 对 coverage/assertion gap 建立 task、blocker、waiver request 或 change request。

**常见 task mode**

`coverage`、`assertion`、`coverage-audit`、`assertion-audit`、`test`、`trace`。

**典型 Artifact**

- covergroup/coverage collector；
- assertion checker 与 bind；
- coverage/assertion plan 更新；
- exclusions/waiver candidate。

**最低 Evidence**

- coverage item/hit/total 报告；
- assertion compile/bind/attempt/failure/vacuity 报告；
- 关联 testcase 和 regression run；
- exclusion 或 waiver 的独立 authority 记录。

**退出条件**

所有计划项均可追踪到实现和证据；coverage hole、vacuous assertion 和 exclusion 未被
隐藏；工具结果不会自动批准 waiver 或 Stage gate。

<a id="stage-4"></a>

### 3.5 Stage 4：确定性 Regression、CI 与性能门禁

**目标**

把单次测试扩展为可重放 regression，建立失败分诊、CI fragment 和经评审的性能合同。

**步骤**

1. 定义 caselist、seed 策略、并发隔离、timeout 和结果 schema。
2. 每个 testcase 使用独立输出目录，避免并发污染证据。
3. 汇总 PASS/FAIL/TIMEOUT/TOOL_NOT_FOUND 等稳定状态。
4. 对失败执行 primary 与 same-seed rerun，生成候选分类而非自动 root cause。
5. 生成待人工合并的 CI fragment，不写入组织 secrets 或 scheduler policy。
6. 对已评审指标运行固定公式的 performance gate。
7. 审计默认 regression 与 REQ/VF/test/coverage/assertion 的结构映射。

**常见 task mode**

`regression`、`triage`、`ci`、`performance`、`evidence`、`waveform`、`trace`。

**典型 Artifact**

- regression runner、caselist 和结果汇总；
- failure triage report；
- CI fragment；
- performance contract 和 evaluator 输出。

**最低 Evidence**

- 每个 testcase 的命令、seed、退出状态和日志；
- same-seed rerun 对比；
- CI 在受支持环境中的可复现运行；
- 性能输入、公式、阈值和结果。

**退出条件**

默认 regression 可重复执行并严格汇总，失败未被重试掩盖，CI/性能声明均有可复现证据；
没有证据时不能声称 simulator、scheduler 或性能目标受支持。

<a id="stage-5"></a>

### 3.6 Stage 5：闭合、sign-off 与 freeze

**目标**

确认规格、实现和证据闭环，审计 baseline 后变更，形成可供 Human sign-off/freeze
决策的候选材料。

**步骤**

1. 运行最终 traceability、coverage、assertion、regression 和 performance 审计。
2. 核对所有 blocker、deviation、waiver 和 change request 的状态及 authority。
3. 检查 baseline 后 Git diff 是否被 change-control 覆盖。
4. 生成 Stage 5 Draft gate packet 并进行 Human Stage review。
5. 运行 signoff audit，只复核 packet/evidence/approval metadata 的结构完整性。
6. Human 明确授权 freeze 后，在 clean reviewed commit 上生成 SHA-256 freeze candidate。
7. 公开发布另走 `release`/OSS readiness 分支，并再次进行保密与许可评审。

**常见 task mode**

`trace`、`coverage-audit`、`assertion-audit`、`change`、`gate`、`signoff`、`freeze`、
`release`。

**典型 Artifact**

- closure reports；
- Stage 5 gate packet；
- sign-off audit report；
- freeze candidate manifest；
- 可选 OSS readiness report。

**最低 Evidence**

- 全链 traceability closure；
- coverage/assertion/performance/regression 最终证据；
- CR/waiver/approval metadata；
- clean commit 和 artifact SHA-256；
- public candidate 的 license、denylist 和敏感内容审计。

**退出条件**

工具只能报告 `READY_FOR_HUMAN_REVIEW` 或发现问题。Human 才能批准 Stage、sign-off、
freeze、tag、push 和公开发布；这些 authority 不能由 Agent 或 workflow success 推导。

---

## 4. Spec Kit 治理流程

### 4.1 四个平面

```text
verif-harness 控制面：Stage policy / dispatch / traceability / authority boundary
          |
          +-> Spec Kit 规格面：constitution / spec / plan / checklist / tasks
          +-> verif-harness 能力面：受控 mode 与 persistent task runner
          +-> xverif / WavePeek / EDA 证据面：确定性工具输出
          +-> Human 权限面：decision / waiver / gate / sign-off / freeze
```

Spec Kit 管理规格生命周期，但不拥有验证证据和 Human approval。verif-harness 是
最上层控制面，决定 [Stage](#term-stage)、[MODE](#term-mode)、traceability 和权限边界。

### 4.2 唯一规格权威

新项目以 `specs/` 为唯一可编辑规格事实源（editable requirement source）：

- `spec.md`：需求、Verification Features、场景、边界和成功标准；
- `plan.md`：架构、owner、Stage、mode、artifact、evidence 和 gate 映射；
- `tasks.md`：精简、可执行、可恢复的 task contracts；
- `checklists/`：规格质量与可验证性检查。

`sim/docs/`、review packet、evidence index 和 `.specify/docs/zh-CN/` 都不是第二个可编辑
需求权威。已有批准项目应作为 `immutable imported baseline` 导入，不重写历史决定。

<a id="term-document-systems"></a>

### 4.3 Spec Kit 文档与 init 派生文档

两套文档处于同一追踪链的不同层级：

```text
用户目标 / 上游规格
        ↓
Spec Kit 文档：定义并评审验证意图
spec.md -> plan.md -> tasks.md
        ↓ review + execution authorization
TASK: mode init
        ↓
init 文档：映射为当前项目的工程与治理视图
.harness-config.json + AGENTS.md + <docs_root>/*
        ↓
实现、Evidence、Converge、Stage Gate
```

#### 4.3.1 职责对照

| 对比项 | Spec Kit 文档 | `init` 生成的文档 |
| --- | --- | --- |
| 主要位置 | `specs/<feature>/` | `<docs_root>/`，通常是 `sim/docs/` |
| 核心性质 | 唯一可编辑规格事实源 | 派生的工程与治理视图 |
| 回答的问题 | 验证什么、为什么、验收标准是什么 | 当前项目怎样组织、实现、评审和维护 |
| 生成时间 | 每个 Stage 的 Spec Kit workflow | Stage 0 execution gate 后由 `mode: init` task 生成 |
| 主要输入 | 用户目标、上游规格、Human Decisions | 已评审 Spec Kit 文档、RTL 结构和项目配置 |
| 修改权限 | 可以定义或修改 REQ、VF、计划和 task | 不得独立定义新的需求语义 |
| 评审方式 | spec/plan/tasks 等 workflow review gate | task postconditions、review packet、convergence 和 Stage gate |
| 后续演进 | 每个 Stage 持续更新 | 随工程演进，但必须保持对 `specs/` 的追踪 |

#### 4.3.2 Spec Kit 文档的使用方式

`specs/<feature>/` 通常包含：

```text
specs/<feature>/
├── spec.md
├── plan.md
├── research.md            # 适用时
├── data-model.md          # 适用时
├── quickstart.md          # 适用时
├── contracts/             # 适用时
├── checklists/
└── tasks.md
```

- `spec.md` 定义 REQ、VF、场景、边界、成功标准、决策和开放问题；
- `plan.md` 定义架构、owner、Stage、mode、artifact、evidence 和 Human gate；
- `tasks.md` 定义经过评审、可执行和可恢复的 task contract；
- `checklists/` 检查规格质量、歧义、边界与可验证性。

需要改变 DUT 行为理解、协议/reset 语义、reference-model 语义或验收条件时，必须先
更新这套文档并重新经过相应 review gate。

#### 4.3.3 init 文档的使用方式

`init` 除了生成 `.harness-config.json`、`.harness/` 和 `AGENTS.md`，还会在
`<docs_root>` 生成：

```text
<docs_root>/
├── governance/
│   └── verification_workflow.md
├── roadmap.md
├── harness_style_methodology.md
├── stage0_review_packet.md
└── verification/
    ├── verification_plan.md
    ├── feature_matrix.md
    ├── tb_architecture.md
    ├── assertion_plan.md
    ├── coverage_plan.md
    ├── testcase_list.md
    └── reference_model_spec.md    # 启用 reference model 时
```

| init 文档 | 用途 |
| --- | --- |
| `verification_workflow.md` | review gate、change request 和治理规则 |
| `roadmap.md` | Stage 0–5 项目演进路线 |
| `harness_style_methodology.md` | 当前项目怎样应用 harness-style 方法 |
| `verification_plan.md` | 总体验证范围、策略和 sign-off 候选标准 |
| `feature_matrix.md` | VF、RTL、test、coverage 和 assertion 的项目映射 |
| `tb_architecture.md` | interface、UVC、env、harness 和 scoreboard 数据流 |
| `assertion_plan.md` | ASRT ID、property、位置和证据规划 |
| `coverage_plan.md` | COV ID、bin、cross、目标和 closure 策略 |
| `testcase_list.md` | TC ID、目标、优先级和 VF 映射 |
| `reference_model_spec.md` | 当前项目使用的上游 reference-model 语义镜像 |
| `stage0_review_packet.md` | 汇总决策和问题，供 Human 集中评审 |

这些文档必须带 provenance、REQ/VF 追踪、RTL `<file>:<line>` 引用和统一 review block。
如果发现权威规格缺少必要信息，必须先在 Spec Kit 中增加问题或决定，再从派生文档
链接过去；不能只在 `<docs_root>` 中静默补充语义。

#### 4.3.4 Stage plan 与总体验证计划

```text
specs/<feature>/plan.md
```

是权威 Stage 计划，定义 VF 如何映射到 mode、artifact、evidence 和 gate。

```text
<docs_root>/verification/verification_plan.md
```

是 init 生成并随项目演进维护的总体验证策略，覆盖所有 Stage 的范围、方法和 sign-off
候选标准；`<docs_root>/roadmap.md` 则定义 Stage 0–5 的成熟度路线。两者都不是某个
Stage 的可执行计划，也不能替代 `specs/<feature>/plan.md`。

新项目不再生成 `<docs_root>/plan.md`，因为它与上述三类文档重复且容易形成双重权威。
旧项目已有的 `<docs_root>/plan.md` 只是可选 legacy 派生视图：可以保留供历史追溯，
但不得作为新 task、review 或 Stage gate 的权威输入。没有 Spec Kit 元数据的纯旧项目，
Stage gate 工具仍允许把它作为兼容性回退；一旦存在 `.specify/`，必须使用当前
`specs/<feature>/plan.md`。

#### 4.3.5 修改与回写规则

规格或语义变更：

```text
更新 specs/<feature>/spec.md
  -> review / clarify
  -> 更新权威 plan/tasks
  -> 刷新 init 派生文档和追踪关系
```

不改变规格语义的工程细节，例如实际路径、UVC owner、test 名称或 collector 位置，
可以更新对应 init 文档并记录 Revision Log；如果影响 Frozen Sections、Human Decision
或已批准架构基线，仍需 change request。

`stage0_review_packet.md` 是集中评审入口，不是事实源。Human 作出决定后，结果必须
回写到对应的 `specs/` 权威文档或受控 init 源文档，再刷新 review packet。

#### 4.3.6 不要把 `.specify/` 当成项目规格

`.specify/` 主要保存 Spec Kit 模板、命令、workflow、run state 和 integration
基础设施；`.specify/docs/zh-CN/` 只是中文阅读镜像。二者都不是项目的可编辑规格事实源。

项目规格权威始终位于 `specs/`。

### 4.4 一个 Stage 的完整 lifecycle

```text
establish-constitution
  -> review-constitution
  -> specify
  -> review-spec
  -> clarify
  -> review-clarification
  -> plan
  -> review-plan
  -> checklist
  -> review-checklist
  -> tasks
  -> review-tasks
  -> analyze
  -> authorize-execution
  -> persistent task runner
  -> review-implementation
  -> converge
  -> review-convergence
  -> independent stage-gate-review
```

其中每个 review gate 都会持久化 `paused`，等待 Human 检查对应工件。一次 verdict 只
绑定当前 gate，不会自动带入下一 gate，也不会提升为 Stage approval。

### 4.5 文档生成与评审

1. `specify` 生成或更新 [REQ](#term-req)、[VF](#term-vf) 和场景。
2. `clarify` 显式处理歧义，不允许 Agent 猜测 DUT、协议或 Human Decision。
3. `plan` 把 VF 映射到 [MODE](#term-mode)、[ARTIFACT](#term-artifact)、
   [EVIDENCE](#term-evidence) 和 [GATE](#term-gate)。
4. `checklist` 检查需求质量、完整性、边界和可验证性。
5. `tasks` 把计划压缩为可执行合同，不复制 `plan.md` 的长篇叙述。
6. `analyze` 在执行前检查冲突、歧义、重复权威和 traceability gap。

文档由 Agent 生成时只是 review candidate。生成成功不等于语义正确或已获批准。

### 4.6 Task contract 与 persistent runner

一个 executable task 使用一行摘要和三行合同：

```text
- [ ] T012 [VF-001] 实现 FIFO 顺序检查
  - mode: `scoreboard`
  - outputs: `tb/env/fifo_scoreboard.sv`; evidence: `evidence/T012.json`
  - validate: `make compile`; needs: `T008`; interaction: `none`
```

多个 `outputs`、`evidence` 或 `needs` 必须用英文逗号分隔，不能用分号。`validate`
不是完成条件的自然语言描述，而是 runner 在项目根目录通过 `/bin/sh` 非交互执行的
真实命令。`review-tasks` 批准时会先检查路径列表、shell 语法和首个可执行命令；例如
“analyze 输出无关键项”会被当场拒绝，而不会等到 implementation 阶段以退出码 127
阻塞。

runner 每次只执行 `current_task_id`，状态为：

```text
READY -> RUNNING -> DONE
                  -> BLOCKED
```

只有以下 postconditions 全部满足，runner 才能标记 `[x]`：

- owned outputs 存在；
- evidence path 存在；
- reviewed validation command 返回 0；
- task contract 未在运行中被 Agent 修改；
- dependencies 已完成。

需要 Human 回答、额外 authority 或规格决策的内容必须成为 `OPEN B###` 或运行时
`BLOCKED`，不能写成假装可自动执行的 task，也不能让 Agent 等待 terminal input。

### 4.7 Workflow 状态机

| 状态 | `resume_allowed` | 正确动作 |
| --- | --- | --- |
| `starting/running`，worker live | false | 等待并轮询 `status` |
| `paused`，review gate | true | 评审工件后提交一个 verdict |
| task `BLOCKED` | true | 取得回答后用 `--answer` 恢复当前 task |
| task `BLOCKED`，且已评审合同有误 | false | 修正并人工评审后用 `revise-tasks --verdict approve --reason ...` 重新绑定 |
| `running`，无 live worker | false | 检查日志，确认 stale 后执行 `recover` |
| recovered `failed` | true | `resume <run-id>` 重试当前 step |
| completed | false | 进入独立 Stage gate 或下一 Stage |

用户命令不能绕过状态前置条件。尤其不能在 live worker 正在运行时因用户已经输入
`approve` 就再次调用 resume。

`revise-tasks` 是旧 run 的受控修订通道，不会回写或伪造原 `review-tasks` gate。
它只允许尚无 DONE task、workflow 已暂停在 `review-implementation`、当前 task 已
BLOCKED 的情形，并记录旧/新 contract hash、Human 理由和 reconciliation 结果。

### 4.8 追踪治理链

每个可执行工作必须保持：

```text
REQ -> VF -> PLAN -> TASK -> MODE -> ARTIFACT -> EVIDENCE -> GATE
```

各术语分别见 [REQ](#term-req)、[VF](#term-vf)、[PLAN](#term-plan)、
[TASK](#term-task)、[MODE](#term-mode)、[ARTIFACT](#term-artifact)、
[EVIDENCE](#term-evidence) 和 [GATE](#term-gate)。

该链支持：

- 正向回答“这条需求将如何实现、验证和评审”；
- 反向回答“这个 PASS 属于哪个 artifact、task、VF 和 requirement”；
- 在 gate 前发现孤立需求、无证据实现、未追踪测试和重复权威。

### 4.9 Converge 与独立 Stage gate

`converge` 对照已评审规格核对每个 task 的 output、evidence 和 validation，把缺失内容
记录为 incomplete task、deviation 或 change request。它不能通过重复运行未追踪 mode
掩盖缺口。

workflow 内的 `review-convergence` 只评审规格漂移和证据完整性。随后运行的
`stage-gate-review` 才生成独立 Draft gate packet；两者都不能自行批准 Stage。

### 4.10 中文阅读镜像

项目规格 `spec.md`、`plan.md`、`tasks.md` 和 checklist 默认使用简体中文；代码、命令、
路径、配置键、协议名、稳定 ID 和原始引用保持原文。上游 `.specify/` 基础设施保留其
发行语言。

```text
$verif-harness docs
```

该命令刷新 `.specify/docs/zh-CN/` 阅读镜像和 hash manifest。镜像不参与 template
resolution、command discovery、workflow execution，也不是 specification、evidence
或 approval 事实源。

---

## 5. 关键术语与概念

<a id="term-stage"></a>

### 5.1 Stage

Stage 是验证成熟度和评审范围，不只是命令序号：

| Stage | 核心问题 |
| --- | --- |
| 0 | 规格、权限、治理和最小 scaffold 是否成立？ |
| 1 | verification environment 是否结构正确且可编译？ |
| 2 | 功能场景、scoreboard 和 reference model 是否可追踪、可复现？ |
| 3 | coverage 和 assertion 是否按计划实现并产生有效证据？ |
| 4 | regression、CI、triage 和性能合同是否稳定？ |
| 5 | traceability、closure、sign-off 和 freeze 候选是否完整？ |

Stage workflow 完成不等于 Stage approval。Human 必须审阅独立 gate packet。

<a id="term-req"></a>

### 5.2 REQ — Requirement

[REQ](#term-req) 描述 DUT 或验证系统必须满足的可观察要求，回答“必须是什么”。

```text
REQ-001：所有被 DUT 接收的输入 transaction 必须保持顺序输出。
```

好的 REQ 应可观察、无歧义、可判断 PASS/FAIL，且不偷偷包含实现假设。

<a id="term-vf"></a>

### 5.3 VF — Verification Feature

[VF](#term-vf) 把 REQ 拆成验证环境必须提供的检查、激励或采集能力，回答“怎样验证”。

```text
REQ-001
├── VF-001 正常流量下的顺序和数据完整性检查
├── VF-002 backpressure 下的顺序检查
└── VF-003 reset 中断后的恢复检查
```

REQ 与 VF 不要求一一对应，但每个 VF 必须能回溯到至少一个已评审 REQ。

<a id="term-plan"></a>

### 5.4 PLAN — 验证计划

[PLAN](#term-plan) 把 REQ/VF 转换为验证架构和执行策略，定义 owner、Stage、mode、
artifact、evidence、失败重跑策略和 Human gate。

| REQ/VF | Stage | Mode | Owned artifact | Evidence | Human gate |
| --- | ---: | --- | --- | --- | --- |
| REQ-001/VF-001 | 2 | `scoreboard` | `tb/env/fifo_scoreboard.sv` | compile + regression | Stage 2 review |

PLAN 是策略，不应膨胀成逐文件操作流水账。

<a id="term-task"></a>

### 5.5 TASK — 可执行任务合同

[TASK](#term-task) 是从 PLAN 拆出的、可以单独执行、验证、阻塞和恢复的最小工作单元。
它必须声明 VF、mode、owned outputs、evidence、validation、dependencies 和
`interaction: none`。

TASK 是一次具体工作；MODE 是完成这类工作的可复用能力。需要 Human 判断的事情不是
TASK，而是 blocker、decision 或 gate。

<a id="term-mode"></a>

### 5.6 MODE — 受控执行能力

[MODE](#term-mode) 是 verif-harness 中职责明确、输入受审、权限受限的执行入口，例如
`interface`、`scoreboard`、`test`、`coverage`、`regression` 和 `trace`。

```text
TASK T012 -> MODE scoreboard
```

task runner 只能分发 task 合同中已评审的 mode 和参数，不能临时选择任意工具或 shell
操作绕过权限边界。

<a id="term-artifact"></a>

### 5.7 ARTIFACT — 产物

[ARTIFACT](#term-artifact) 是 task 实际创建或修改的持久化对象，例如 interface、UVC、
scoreboard、test、coverage model、assertion、filelist、配置或 review packet。

owned artifact 用来限制 task 的写入范围。Artifact 存在只表示“做出了东西”，不证明
其正确性。

<a id="term-evidence"></a>

### 5.8 EVIDENCE — 证据

[EVIDENCE](#term-evidence) 证明 artifact 满足 task、VF 和 REQ，例如：

- compile/elaboration/simulation/regression 结果；
- testcase 状态、seed、命令、工具版本和日志；
- coverage/assertion/performance 报告；
- waveform 查询与 provenance；
- artifact hash 和 traceability audit。

```text
ARTIFACT = 做出了什么
EVIDENCE = 凭什么相信它有效
```

文件存在、Agent 声称完成、Spec Kit command 成功或 checklist 被勾选，都不能单独作为
确定性验证证据。

<a id="term-gate"></a>

### 5.9 GATE — 人工评审门

[GATE](#term-gate) 判断工件和证据是否足够，以及是否允许进入下一步。常见 gate 包括
spec/plan/tasks review、execution authorization、implementation review、Stage gate、
sign-off 和 freeze authorization。

```text
测试 PASS ≠ gate 自动批准
gate 批准 ≠ Stage 自动批准
Stage 通过 ≠ sign-off/freeze 自动批准
```

Agent、Spec Kit、xverif、WavePeek 和 simulator 都不能代替 Human 批准 decision、waiver、
Stage、sign-off、freeze、commit、push 或 release。

<a id="term-decision-lifecycle"></a>

### 5.10 Stage 0 决策生命周期

Stage 0 文档把不确定性和决定分为四类。分类取决于“谁能决定”和“决定是否已经
稳定”，不能把所有未知内容都写成 Open Question。

| 类型 | 含义 | 典型位置 | 标识与要求 |
| --- | --- | --- | --- |
| Human Decision | Human 已明确批准的语义或架构决定 | 权威 `spec.md`；派生文档 review block 中的 `### Human Decisions` | `HD-n`；进入 Frozen Section 后修改需 CR |
| Provisional Decision | 项目已选定方向，但证据不足，需要在后续 Stage 复审 | 受影响文档的 `## 暂定决策 (Provisional)` | `Pn`；记录依据、目标复审、影响和日期 |
| 待 Human Review 的假设 | 本项目 Human 应决定但尚未拍板，Agent 暂按此推理 | 受影响文档的 `## 待 Human Review 的假设` | 明确是假设，不得写成已批准事实 |
| Open Question | 依赖上游团队、第三方规格或项目外部输入，本项目内部无法决定 | 权威 `spec.md` 和相关派生文档的 `## 开放问题` | `OQn`；记录 Depends on、Blocks、Status/owner |

#### Human Decision

Human Decision 用于已经明确批准、会影响规格语义或架构基线的决定。例如 reset 后首个
transaction 是否有效、overflow 的规定行为、reference-model rounding 语义。Agent
不得推断或自行标记批准。已冻结 Human Decision 的修改必须通过 change request。

#### Provisional Decision

当项目已经需要一个工作方向、但证据要到后续 Stage 才充分时，使用 Provisional：

```text
- **P1**: sign-off functional coverage 暂定不低于 98%
  - **依据**: 当前项目风险和 module-level 目标
  - **目标复审**: Stage 4 gate
  - **影响**: coverage plan 与 sign-off candidate
  - **Provisional since**: YYYY-MM-DD
```

到目标 Stage gate 时必须选择保持 Provisional、升级为 Human Decision，或降级为 Open
Question/假设，不能无限期遗忘。

#### 待 Human Review 的假设

假设表示本项目有 authority 作决定，但当前还没有正式结果。它允许 Agent 暂时分析，
不允许 Agent 把假设写入 RTL/TB 实现并声称语义已经确认。会阻塞执行时，应同时形成
`OPEN B###`。

#### Open Question

Open Question 只用于真实外部依赖：

```text
- **OQ1**: 上游是否保证 reset deassert 后第一个 cycle 的 output 无效？
  - **Depends on**: upstream design/spec owner
  - **Blocks**: VF-003、Stage 2 reset recovery testcase
  - **Status**: owner assigned，等待规格更新
```

当 init 派生文档发现缺失语义时，先把问题加入权威 Spec Kit 文档，再在派生文档中引用
OQ ID、影响范围和目标 gate；不能只在 `verification_plan.md` 或 `tb_architecture.md`
新增一条独立语义。

#### Task Blocker

如果决定或问题阻止 task 非交互执行，在 `tasks.md` 的“阻塞项”记录：

```text
- B001 [OPEN] [等待上游确认 reset 后首个 transaction 是否有效；关联 OQ1]
```

`B###` 不是 executable `T###`。review-tasks 和 authorize-execution 在存在未解决 blocker
时不得批准；运行中的 task 遇到同类问题必须进入 `BLOCKED`，由
`resume <run-id> --answer "..."` 只恢复当前 task。

#### Review packet 与回写

`<docs_root>/stage0_review_packet.md` 汇总所有 Human Decisions、Provisional Decisions
和 Open Questions，方便 Human 集中评审，但它不是事实源。正确流程是：

```text
在 specs/ 或受控源文档记录决定/问题
  -> 派生文档记录影响和追踪链接
  -> stage0_review_packet.md 汇总评审
  -> Human 决定后回写源文档
  -> 刷新派生文档和 review packet
```

完整格式规范见 [doc-conventions.md](../assets/doc-conventions.md) 的“决策生命周期约定”。

### 5.11 完整追踪示例

```text
REQ-001
所有已接收 transaction 必须保持顺序输出
    ↓
VF-001
验证环境提供端到端顺序和数据完整性检查
    ↓
PLAN
使用 input/output monitor、reference queue 和 scoreboard
    ↓
TASK T012
实现并注册 FIFO scoreboard
    ↓
MODE scoreboard
    ↓
ARTIFACT
tb/env/fifo_scoreboard.sv
    ↓
EVIDENCE
compile PASS + 正常/乱序注入 regression 报告
    ↓
GATE
Human 审查映射、实现和证据后决定 approve/reject
```

缺少任一链接都不是闭环。常见缺口包括：

- 有 REQ，没有对应 VF；
- 有 PLAN，没有 executable TASK；
- TASK 未指定 MODE 或 owned output；
- 有 ARTIFACT，没有 EVIDENCE；
- 有测试 PASS，但无法回溯到 REQ/VF；
- 有 EVIDENCE，但没有经过对应 Human GATE。

<a id="term-runtime"></a>

### 5.12 Agent runtime 与模型

runtime 指 Codex 或 Kimi Code 的 integration、Skill 目录和启动方式；模型是同一 runtime
内部选择的推理模型。更换模型不等于切换 runtime。`.specify/integration.json` 是项目
runtime 的唯一事实源，runtime switch 必须在稳定 review gate 执行。

<a id="term-baseline"></a>

### 5.13 Baseline、Change Control、Sign-off 与 Freeze

- baseline：经评审、可追溯的起点；
- change control：baseline 后变更必须有 CR、影响分析和证据；
- sign-off audit：检查候选材料，不授予 sign-off；
- freeze candidate：把 clean commit 和 artifacts 固定为 hash manifest；
- Human freeze approval：独立权限决定，不由工具产生。

### 5.14 Spec Kit、xverif 与 WavePeek

- Spec Kit：agentic specification lifecycle，不是 simulator 或证据工具；
- xverif：把一个已评审 request 委托给固定版本 native 工具并保存不可变证据；
- WavePeek：对 VCD/FST 执行有限、可重放查询并记录 provenance；FSDB 默认禁用；
- EDA simulator：产生 compile/simulation/regression 等动态证据，但不拥有 Stage policy。

---

<a id="mode-index"></a>

## 6. Mode 与工具索引

完整的 31 个模式（mode）、用途、典型场景和命令见
[Agent Skill modes](../../../docs/skill_modes.md)。在 Agent 中也可以运行：

```text
$verif-harness help
$verif-harness help <alias-or-mode>
```

### 6.1 结构与实现 mode

| 短命令 | Canonical mode | 常见 Stage |
| --- | --- | ---: |
| `interface` | `add-interface` | 1 |
| `package` | `add-shared-pkg` | 1 |
| `uvc [name]` | `add-uvc-skeleton [name]` | 1 |
| `harness` | `add-harness-layer` | 1 |
| `env` | `add-env-layer` | 1 |
| `build` | `finalize-filelist-and-make` | 1 |
| `simulator` | `add-simulator-profile` | 1–4 |
| `uvc-complete` | `complete-uvc` | 2 |
| `scoreboard` | `complete-scoreboard` | 2 |
| `refmodel` | `add-refmodel-bridge` | 2 |
| `test` | `add-testcase` | 2–4 |
| `coverage` | `add-coverage-skeleton` | 3 |
| `assertion` | `add-assertion-skeleton` | 3 |

### 6.2 执行、证据与治理 mode

| 短命令 | Canonical mode | 常见 Stage |
| --- | --- | ---: |
| `regression` | `add-regression-runner` | 2–4 |
| `triage` | `regression-triage` | 4 |
| `ci` | `add-ci-hook` | 4 |
| `performance` | `add-performance-gate` | 4–5 |
| `coverage-audit` | `coverage-closure` | 3–5 |
| `assertion-audit` | `assertion-closure` | 3–5 |
| `trace` | `audit-traceability` | 2–5 |
| `change` | `change-control` | baseline 后 |
| `gate <stage>` | `stage-gate-review <stage>` | 0–5 |
| `signoff <stage>` | `signoff-audit <stage>` | 5 |
| `freeze` | `freeze-baseline` | 5 |
| `release` | `oss-readiness` | public candidate |
| `pattern [topic]` | `patterns [topic]` | 任意 |

### 6.3 Workflow 与工具入口

| 命令 | 作用 |
| --- | --- |
| `probe` | 检查 pinned Spec Kit runtime |
| `bootstrap` | 初始化规格 infrastructure 和 integration |
| `stage ...` | 启动一个 Stage lifecycle |
| `status [run-id]` | 查看 workflow、worker 和 task 状态 |
| `resume ...` | 只在状态允许时处理 gate/task recovery |
| `recover ...` | 修复确认无 live worker 的 stale run |
| `docs` | 刷新中文阅读镜像 |
| `evidence ...` | 委托 xverif |
| `waveform ...` | 委托 WavePeek |

canonical mode 及输入合同分别位于 `skills/verif-harness/<mode>/INSTRUCTIONS.md`。
不要仅凭 mode 名称猜测必需参数；通过 `help` 或当前 reviewed task contract 调用。

---

## 7. 最终判定原则

1. `specs/` 是新项目唯一可编辑 requirement source。
2. DUT RTL 始终是外部只读资产。
3. Agent 生成内容只是 review candidate，不是批准语义。
4. TASK 必须通过 MODE、ARTIFACT、EVIDENCE 和 validation postconditions 才能 DONE。
5. Spec Kit command 或 workflow success 不是 simulation evidence。
6. simulator/xverif/WavePeek PASS 不是 Human approval。
7. workflow review gate、Stage gate、sign-off、freeze 和 release 是不同权限边界。
8. 任何不确定状态先运行 `doctor` 或 `status`，不要猜测、重跑或跳过 gate。

最短总结：

```text
REQ 定义目标
VF 定义验证能力
PLAN 设计路径
TASK 划分执行单元
MODE 受控实施
ARTIFACT 承载结果
EVIDENCE 证明结果
GATE 决定是否继续
```
