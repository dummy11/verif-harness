# 用户指南：从 Stage 0 到 Verification Freeze

本文是 `verif-harness` 的完整操作手册，包含：

- RTL 验证项目从 0 到 freeze 的推荐顺序；
- 29 个模式各自的用途、输入、输出、用法和适用场景；
- 每个阶段必须由人工完成的决策；
- 各模式的能力边界和不能据此得出的结论。

项目自身的 `AGENTS.md`、roadmap、verification plan 和 architecture 优先于
本文。调用任何写模式前，必须先读取项目规则；DUT RTL 始终只读。

## 1. 基本调用方式

在 RTL 验证项目根目录中调用：

```text
$verif-harness <mode> [arguments]
```

例如：

```text
$verif-harness doctor
$verif-harness add-uvc-skeleton data_in
$verif-harness stage-gate-review 4
```

未指定 mode 时：

- 存在 `.harness-config.json`：默认执行只读 `doctor`；
- 不存在 `.harness-config.json`：进入 `init`；
- 项目状态冲突或 stage 不明确：停止写入并报告冲突。

所有写模式默认只增不覆盖。Markdown 发生变化后，执行项目 `AGENTS.md`
规定的 Markdown workflow，并 review 自动修复产生的 diff。

## 2. Stage 0→freeze 总流程

```text
Stage 0：文档与治理基线
  -> Human 批准范围、规格来源和 Human Decisions
  -> Stage 1：可编译、可运行的最小 harness/UVM 环境
  -> Human Stage 1 gate
  -> Stage 2：Golden/reference-model 功能对拍
  -> Human Stage 2 gate
  -> Stage 3：coverage model 与 assertion fleet
  -> Human Stage 3 gate
  -> Stage 4：随机回归、边界场景与 CI
  -> Human Stage 4 gate
  -> Stage 5：coverage/assertion/performance/stability closure
  -> Human Stage 5 sign-off
  -> freeze-baseline
  -> Human freeze approval
  -> 单独授权的 tag/push/release
```

`doctor` 在每个 stage 入口和每次 session 恢复时重复使用；
`regression-triage` 在任何非全绿 regression 后使用；`change-control` 在任何
approved/frozen baseline 发生变化时立即使用。

`xverif` 不是独立 stage，而是贯穿 Stage 0～5 的确定性工具委派通道：需要做
SystemVerilog bit 计算、设计/波形事实查询、coverage database 查询、entry 解码、
日志位置恢复、SVA 解释或波形渲染时，由 `verif-harness` 先选择验证任务，再经
CLI adapter 调用对应 xverif native tool。

## 3. 分阶段推荐顺序

### 3.1 Stage 0：文档基线

```text
doctor
  -> init
  -> audit-traceability
  -> stage-gate-review 0
  -> Human Stage 0 baseline approval
```

人工必须确认验证范围、规格权威来源、sign-off 标准、Human Decisions、
Provisional 和 open questions。Stage 0 不允许生成 TB 源码。

### 3.2 Stage 1：最小可运行环境

```text
doctor
  -> add-interface
  -> add-shared-pkg
  -> add-uvc-skeleton
  -> add-harness-layer
  -> add-env-layer
  -> finalize-filelist-and-make
  -> add-simulator-profile
  -> complete-uvc
  -> add-testcase
  -> add-regression-runner
  -> audit-traceability
  -> stage-gate-review 1
  -> Human Stage 1 approval
```

人工提供并确认 clock/reset、协议、SRAM、timeout、DUT port 和 simulator
语义；在真实 EDA 环境检查 compile、elaboration、waveform 和 sanity test。

### 3.3 Stage 2：Reference model 与功能对拍

```text
doctor
  -> add-refmodel-bridge
  -> complete-scoreboard          # 仅在项目确实使用 FIFO alignment 时
  -> add-testcase
  -> regression-triage            # 失败时
  -> audit-traceability
  -> stage-gate-review 2
  -> Human Stage 2 approval
```

人工确认 numeric representation、mask、alignment、residual、unsupported
configuration 和 Golden engagement。Port-level compare 或项目专用 wrapper
不能由通用 FIFO scoreboard 替换。

### 3.4 Stage 3：Coverage 与 Assertion

```text
doctor
  -> add-coverage-skeleton
  -> add-assertion-skeleton
  -> add-testcase
  -> regression-triage            # 失败时
  -> audit-traceability
  -> stage-gate-review 3
  -> Human Stage 3 approval
```

人工批准 coverage denominator、cross、property、sampling clock、reset disable、
vacuity 处理和逐对象 unreachable waiver。

### 3.5 Stage 4：Regression 与 CI

```text
doctor
  -> add-testcase
  -> add-regression-runner        # 已完整时复用
  -> add-ci-hook
  -> regression-triage            # 每次非全绿时
  -> audit-traceability
  -> change-control               # baseline 发生变化时
  -> stage-gate-review 4
  -> Human Stage 4 approval
```

人工或获授权基础设施提供 simulator license、scheduler、secret 和 CI runner；
test 从 candidate 晋级 default regression 必须有已评审的动态 PASS 证据。

### 3.6 Stage 5：闭合、签核与 freeze

```text
doctor
  -> add-performance-gate
  -> add-testcase                 # 只补剩余 hole/corner/closure case
  -> required deterministic regression rounds
  -> regression-triage            # 直到所有失败关闭
  -> coverage-closure
  -> assertion-closure
  -> audit-traceability
  -> change-control
  -> stage-gate-review 5
  -> Human Stage 5 approval
  -> signoff-audit 5
  -> freeze-baseline
  -> Human freeze approval
  -> separately authorized tag/push
```

`coverage-closure` 和 `assertion-closure` 的 JSON 只是 tool-neutral adapter，
不能替代原始 coverage database、compile/elaboration report 和 assertion report。

## 4. Bootstrap 与 Stage 1 结构模式

### 4.1 `init`

**用途**：把一个只有 RTL 或尚未建立系统验证流程的项目 bootstrap 成
harness-style 项目。

**适用场景**：项目根目录没有 `.harness-config.json`，准备建立 Stage 0。

**输入**：

- 项目根目录及其中的 `.v/.sv` 文件；
- 项目名、RTL root、verification root；
- DUT top file/module；
- 可选 design-doc root；
- 可选 reference-model spec；
- 通过 discovery 和 Human 回答形成的初始配置。

**用法**：

```text
$verif-harness init
```

**输出**：

- `.harness-config.json`；
- `AGENTS.md`；
- `.harness/` workflow assets；
- `.codex/agents/` 辅助 agent 配置；
- verification docs、governance docs 和 Stage 0 review packet；
- Stage 1 M1.1 空目录骨架与 `.gitkeep`。

**人工参与**：确认所有 discovery 结果，评审整个 Stage 0 文档集，批准或修改
Human Decisions/Provisional/open questions。

**边界**：已有配置时不得重新覆盖；Stage 0 不生成 TB 代码；生成文档不是
Stage 0 approval。

### 4.2 `add-interface`

**用途**：根据明确的 interface contract 生成 protocol interface 和对应 UVC
落点目录。

**适用场景**：Stage 0 已批准，准备建立 ctrl/data/SRAM 等接口。

**输入**：

- `.harness-config.json`；
- `harness-spec.yaml` 中的 interface name、parameters、input args、signals；
- 每个 signal 的 `to-dut`、`from-dut` 或 `clkrst` 角色；
- 可选 modport name override 和 parameterized instances；
- `tb_architecture.md` 的 modport/接口约束。

**用法**：

```text
$verif-harness add-interface
```

**输出**：

- `<verif_root>/testbench/top/if/<prefix>_<name>.sv`；
- 每个接口对应的 `uvc/<agent>_agent/seq/` 目录；
- driver、monitor、DUT 和 clock/reset modport。

**人工参与**：确认 signal direction、clocking ownership、参数宽度和接口分组。

**边界**：不生成 UVC class；不能只凭端口名前缀确认协议语义；缺少完整 spec
时不能继续。

### 4.3 `add-shared-pkg`

**用途**：生成 UVM 无关的公共类型、参数以及宽总线 pack/unpack helper。

**适用场景**：interface 已存在，多个 UVC/Golden/monitor 需要一致的数据布局。

**输入**：

- `.harness-config.json`；
- `harness-spec.yaml` 的 parameters、local parameters、enums；
- 可选 `pack_pattern`：packed signal、二维 dimensions、element width；
- architecture 中已批准的位打包顺序。

**用法**：

```text
$verif-harness add-shared-pkg
```

**输出**：

- `<prefix>_tb_pkg.sv`：parameter、enum、lane typedef；
- `<prefix>_pack_pkg.sv`：pack/unpack function，或无 pattern 时的明确 stub；
- 必要时向 `tb.f` 添加 package 条目。

**人工参与**：确认 lane 顺序、signedness、dimension 和 enum 编码。

**边界**：当前 pack generator 只直接支持二维 pattern；不导入 UVM/UVC；不同
来源的同名参数值冲突时必须停止。

### 4.4 `add-uvc-skeleton [name]`

**用途**：为一个或全部 interface 生成分层 UVC class 骨架。

**适用场景**：interface 和 shared packages 已完成，但 driver/monitor 行为尚未实现。

**输入**：

- 可选 `<name>`，省略时处理全部 interfaces；
- `harness-spec.yaml` 的 interface、instances、parameters、item/sequence names；
- 已存在的 shared package 和 interface；
- `tb_architecture.md` 的 agent 分层定义。

**用法**：

```text
$verif-harness add-uvc-skeleton
$verif-harness add-uvc-skeleton data_in
```

**输出**：

- agent config、item、sequencer、driver、monitor、coverage subscriber；
- agent 或 parameterized top-agent/sub-agent；
- default sequence 和 UVC package；
- 必要的 `tb.f` incdir/package 条目。

**人工参与**：确认 active/passive ownership、parameterized instances、item 字段
和 sequence 职责。

**边界**：run/build phase 仅为空骨架；骨架 compile visibility 不代表协议完成。

### 4.5 `add-harness-layer`

**用途**：建立 DUT 与验证环境之间唯一的结构集成层。

**适用场景**：interfaces 已生成，准备连接 DUT、clock/reset、straps、status
probes、SVA 和 bind。

**输入**：

- `.harness-config.json`；
- `harness-spec.yaml` 的接口 port map、straps、status probes、variants；
- 只读解析得到的 DUT top port list；
- architecture/verification plan 中已批准的 harness ownership。

**用法**：

```text
$verif-harness add-harness-layer
```

**输出**：

- DUT-side `rtl_wrap`、`dut_select`、`dut_harness`；
- TB-side harness interface、API package、reset/status/strap API、clock/reset
  generator；
- SVA checker stubs 和 filelist snippet。

**人工参与**：逐端口 review 映射、tie-off、variant、probe 层级和 reset/strap
语义，并在真实编译器确认 elaboration。

**边界**：不修改 RTL；不根据端口名静默猜测 mapping；缺少 interface 或完整
port spec 时停止。

### 4.6 `add-env-layer`

**用途**：生成 env/test 层及轻薄 `tb_top`，把 harness 和 UVC 组合成可编译环境。

**适用场景**：UVC packages 和 harness API 已存在。

**输入**：

- `.harness-config.json` 和 `harness-spec.yaml`；
- UVC package/agent 类型；
- harness aggregate API；
- env knobs、interface instances 和 architecture ownership。

**用法**：

```text
$verif-harness add-env-layer
```

**输出**：

- env config、virtual sequencer、env；
- scoreboard/coverage collector shell；
- env package、base test、test package；
- thin `tb_top`；
- 必要的 filelist 条目。

**人工参与**：确认 virtual interface 分发、agent enable、analysis connection
计划和 `tb_top` 只承担结构职责。

**边界**：初始 scoreboard/coverage write body 无功能；不加入 test-specific
logic 或默认 `UVM_TESTNAME`。

### 4.7 `finalize-filelist-and-make`

**用途**：按规范依赖顺序生成完整 filelist 和首次 compile/elaboration target。

**适用场景**：Stage 1 M1.1 所有结构源文件已落地。

**输入**：

- `.harness-config.json`；
- 实际存在的 RTL、interface、package、UVC、env/test、harness、SVA、top 文件；
- 可选 RTL exclude list；
- architecture 中的 compile-order contract。

**用法**：

```text
$verif-harness finalize-filelist-and-make
```

**输出**：

- `<verif_root>/filelist/rtl.f`；
- `<verif_root>/filelist/tb.f`；
- `<verif_root>/filelist/sim.f`；
- `<verif_root>/regress/Makefile`，提供 `help/compile/clean`。

**人工参与**：已有 filelist/Makefile 时选择 merge/diff/approved overwrite；在
VCS 等真实环境 review warning 和 elaboration。

**边界**：不把不存在的文件写入 filelist；该阶段不自动增加完整 regress/cov
target；compile error 不会被解释为通过。

## 5. 实现、执行与集成模式

### 5.1 `doctor`

**用途**：只读判断项目健康度、阶段状态和下一安全动作。

**适用场景**：接手项目、恢复 session、进入新 stage、升级 skill 或不知道下一步。

**输入**：项目根目录、可选 `AGENTS.md`、`.harness-config.json`、docs/TB/Git 状态。

**用法**：

```text
$verif-harness doctor
```

底层命令可加 `--json`：

```bash
python3 <skill-dir>/doctor/scripts/doctor.py --project-root . --json
```

**输出**：ERROR、WARNING、INFO、推断出的 stage state、legacy Claude artifact、
RTL dirtiness 和 recommended next mode。

**人工参与**：决定是否执行建议的写模式，解释 ambiguous stage state。

**边界**：不修复文件；clean audit 不证明 simulation PASS 或 stage approval。

### 5.2 `add-simulator-profile`

**用途**：把 simulator 命令、能力和 evidence path 固化成可 review 配置。

**适用场景**：增加 VCS、Questa、Xcelium、Verilator 或 custom simulator profile。

**输入**：`simulator-profile.json`，包含 name、provider、version、compile/run token
arrays、environment variable names、capabilities、evidence paths。支持
`{filelist}`、`{top}`、`{binary}`、`{seed}`、`{test}` placeholder。

**用法**：

```bash
python3 <skill-dir>/add-simulator-profile/scripts/generate_profile.py \
  --spec simulator-profile.json \
  --profile-out sim/config/simulator-profile.json \
  --make-out sim/config/simulator-profile.mk
```

**输出**：normalized JSON profile 和 Makefile fragment。

**人工参与**：提供真实 tool/version，审查命令，在真实 EDA 环境运行并归档日志。

**边界**：环境只记录变量名，不记录 license/secret value；输出状态仅
`CONFIGURED`，不是 `TESTED` 或 `SUPPORTED`。

### 5.3 `complete-uvc`

**用途**：根据显式协议合约生成具体 driver/monitor 行为。

**适用场景**：ready/valid source UVC 已有 item/interface 骨架，需要实现 drive、
handshake timeout 和 monitor publish。

**输入**：`uvc-contract.json`，包含 item/class/base/vif types、config-db vif key、
driver/monitor clocking block、valid/ready signal、payload mapping、timeout 和
plan references。

**用法**：

```bash
python3 <skill-dir>/complete-uvc/scripts/generate_uvc.py \
  --spec uvc-contract.json --driver-out <driver.svh> \
  --monitor-out <monitor.svh>
```

**输出**：具体 driver 和 monitor class，包含 vif 获取、ready timeout、transaction
capture 和 analysis-port publish。

**人工参与**：确认协议确实是 ready/valid source，review reset ownership、
clocking region、payload timing，并运行 protocol tests。

**边界**：不支持的控制/SRAM/credit/乱序协议必须另行实现；生成代码不是协议
正确性证明。

### 5.4 `complete-scoreboard`

**用途**：根据显式 compare contract 生成 FIFO-aligned UVM scoreboard。

**适用场景**：expected/actual transaction 一一按顺序到达，比较策略已评审。

**输入**：`scoreboard-contract.json`，包含 class/base、expected/actual type、
`alignment: fifo`、字段表达式、`exact/masked/abs_tolerance` 策略和 plan refs。

**用法**：

```bash
python3 <skill-dir>/complete-scoreboard/scripts/generate_scoreboard.py \
  --spec scoreboard-contract.json --out <scoreboard.svh>
```

**输出**：两个 analysis FIFO、pair compare、compare/mismatch counter、no-compare
和 residual check。

**人工参与**：批准 alignment、mask、numeric/tolerance、reset flush 和 end-of-test
policy；运行 mismatch/residual/no-compare focused tests。

**边界**：不支持 tag matching、乱序或 port-level compare；不能从字段名推断
mask/tolerance。

### 5.5 `add-testcase`

**用途**：创建一个 compile-safe UVM test/vseq，并注册 package include。

**适用场景**：testcase list 中已有批准的 testcase ID、feature mapping 和预期结果。

**输入**：project root、test name、base test、base vseq；可选 candidate caselist。

**用法**：

```bash
python3 <skill-dir>/add-testcase/scripts/add_testcase.py \
  --project-root . --test-name <prefix>_<name>_test \
  --base-test <prefix>_base_test --base-vseq <prefix>_job_vseq_base \
  --dry-run
```

Review 后去掉 `--dry-run`；只有明确的 focused list 才使用：

```text
--candidate-caselist <path>
```

**输出**：test `.svh`、vseq `.svh`、package include；可选 candidate caselist 条目。

**人工参与**：实现并审阅 stimulus/expected behavior，确认动态 PASS 后决定是否
晋级 default regression。

**边界**：不会自动加入 default regression；骨架不证明 stimulus/checking 完成。

### 5.6 `add-coverage-skeleton`

**用途**：从已评审 JSON 合约生成 coverage class。

**适用场景**：coverage plan 已给出确切表达式、bins、cross 和 plan ID。

**输入**：coverage spec 的 class/base、sample fields、covergroups、coverpoints、raw
bin clauses、cross items 和 `plan_refs`。

**用法**：

```bash
python3 <skill-dir>/add-coverage-skeleton/scripts/generate_coverage.py \
  --spec coverage-spec.json --out <collector-fragment.svh>
```

**输出**：可编译 coverage class/fragment。

**人工参与**：批准 denominator、bin boundary、ignore/illegal bin、sampling event
和 cross 价值；查看真实 coverage report。

**边界**：不从自然语言或 signal name 猜 coverage；拒绝缺 plan ref、重复 name
和 output overwrite。

### 5.7 `add-assertion-skeleton`

**用途**：从已评审 property contract 生成 checker 和可选 bind。

**适用场景**：assertion plan 已给出 clock/reset、property 和 failure message。

**输入**：assertion spec 的 checker ports、clock/reset、assertion IDs、property
expressions、messages、plan refs 和可选 bind mapping。

**用法**：

```bash
python3 <skill-dir>/add-assertion-skeleton/scripts/generate_assertions.py \
  --spec assertion-spec.json --checker-out <checker.sv> \
  --bind-out <bind.sv>
```

**输出**：checker module 和可选 bind statement。

**人工参与**：review sampling region、reset disable、vacuity、X behavior、width、
hierarchy；执行正向和故障注入 focused tests。

**边界**：缺 property 时只输出 TODO，不伪装成已实现 assertion；不把自然语言
静默翻译成 property。

### 5.8 `add-refmodel-bridge`

**用途**：生成 Syscan HDL shell wrapper 或 DPI-C import package 的结构适配层。

**适用场景**：reference-model backend/API 已批准，准备连接 verification harness。

**输入**：local/upstream reference-model spec，以及 `bridge-spec.json` 中的 backend、
guard、HDL ports 或 DPI signatures、disabled assignments 和 plan refs。

**用法**：

```bash
python3 <skill-dir>/add-refmodel-bridge/scripts/generate_bridge.py \
  --spec bridge-spec.json --out <bridge.sv>
```

**输出**：Syscan structural wrapper 或 DPI import package。

**人工参与**：批准 backend、numeric semantics、alignment、mask、unsupported policy、
residual handling、compare ownership 和 Golden engagement test。

**边界**：adapter 只建立连接；零 mismatch 且 Golden 未 engaged 不能 PASS。

### 5.9 `add-regression-runner`

**用途**：添加 simulator-neutral、隔离、可复现的 regression launcher 和严格
result collector。

**适用场景**：已有 runnable test 和稳定的 end-of-test result contract。

**输入**：

- caselist；
- run directory；
- numeric seed 或 seed file；
- jobs/timeout/log name；
- argv-style simulator command，必须包含 `{test}` 和 `{seed}`；
- collector 的 result prefix/regex 和是否 require Golden。

**用法**：复制 mode scripts 和 Makefile fragment 后，例如：

```bash
python3 run_regression.py --caselist tests.caselist --runs-dir runs \
  --seed 123 --jobs 4 -- simulator +UVM_TESTNAME={test} +ntb_random_seed={seed}

python3 collect_results.py --runs-dir runs --caselist tests.caselist \
  --result-prefix PROJECT_RESULT --require-golden
```

**输出**：每 testcase 独立 run dir、`command.json`、log、`batch_seed.txt`、
`batch.json`、`report.md/json`、`failed.caselist` 和 `seed.txt`。

**人工参与**：定义 result/Golden contract，提供 simulator 环境，审阅 crash、
timeout、no-compare 和 rerun 结果。

**边界**：不替换已有项目专用 runner；不使用 shell interpolation；缺结束 banner
不能 PASS。

### 5.10 `add-ci-hook`

**用途**：从显式合约生成 GitLab CI 或 Jenkins 验证 job fragment。

**适用场景**：本地 compile/smoke/regression 稳定，准备接入 CI。

**输入**：`ci-spec.json` 的 provider、commands、runner tags/agent、timeout、公开
variables 和 artifact paths。

**用法**：

```bash
python3 <skill-dir>/add-ci-hook/scripts/generate_ci.py \
  --spec ci-spec.json --out <ci-fragment>
```

**输出**：可人工 merge 的 `.gitlab-ci.yml` 或 Jenkins fragment。

**人工参与**：配置 runner、license、secret、scheduler、timeout/cleanup，merge
fragment，并在真实 pipeline 验证 commit 与结果。

**边界**：不修改 live CI、不 trigger pipeline、不配置 credential、不执行内部
`git pull`。

### 5.11 `add-performance-gate`

**用途**：按已评审的固定算术和 predicate 检查结构化性能记录。

**适用场景**：需要 gate latency、bubble、utilization、cadence、count 或场景完整性。

**输入**：performance contract 的 marker、required/key fields、constant/field/ratio
operands、`eq/ne/lt/le/gt/ge` predicates、completeness rules；一个或多个 log。

**用法**：

```bash
python3 <skill-dir>/add-performance-gate/scripts/evaluate_performance.py \
  --contract performance-contract.json --log run-a.log --log run-b.log
```

按脚本 help 可加 JSON/report output 参数。

**输出**：逐 record predicate 结果、completeness failures、Markdown/JSON summary
和非零失败退出码。

**人工参与**：定义指标、公式、threshold、expected count 和 waiver；确认 producer
与 contract 使用同一语义。

**边界**：只执行白名单算术；不发明公式/threshold，不因历史表现放宽 gate。

### 5.12 `regression-triage`

**用途**：对失败日志形成稳定 signature、候选分类和同 seed 重跑审计。

**适用场景**：regression 不是全绿，需要保留证据地缩小问题域。

**输入**：primary `report.json`、same-seed rerun `report.json`、包含 regex 和
candidate classification 的 `triage-rules.json`。

**用法**：

```bash
python3 <skill-dir>/regression-triage/scripts/triage_regression.py \
  --report runs/report.json --rerun-report rerun/report.json \
  --rules triage-rules.json --out runs/triage.json
```

**输出**：每个失败的 normalized signature、matched rule、candidate classification、
primary/rerun log、seed consistency、blockers 和整体 state。

**人工参与**：判断真实 root cause，以及属于 RTL、TB、Golden、spec 还是 infra。

**边界**：regex match 不是 root-cause 结论；不改 test verdict、不创建 waiver、
不修改源码。

### 5.13 `xverif`

**用途**：在不削弱 `verif-harness` stage/framework 治理的前提下，把一个已评审
的底层确定性操作委派给 `BLANK2077/xverif` 工具族，并生成可追溯 evidence。

**适用场景**：任一 Stage 需要以下事实或计算时：

- `xbit`：SystemVerilog literal、signed/unsigned、slice、mask、表达式；
- `xdebug`：daidir/FSDB 的 scope、driver/load、value、protocol、active driver；
- `xcov`：VDB coverage summary、hole、scope、source evidence 和 export；
- `xentry`：多拍 entry/descriptor/header 的 raw field 解码；
- `xloc`：从 `L_XXXXXXXX` 恢复 UVM 日志源码位置；
- `xsva`：SVA list/scan/lint/parse/explain；
- `xwaveform`：从已导出 manifest 渲染波形 JPG/stats。

**输入**：

- 完整仓库的 `deps/xverif.lock.json`，固定
  `https://github.com/BLANK2077/xverif.git`、完整 commit、MIT License hash
  和七个 wrapper；独立 Skill 部署则提供等价的已批准 checkout root；
- `xverif-request.json`：`tool`、evidence 分类用 `operation`、native `arguments`、
  可选项目相对 `stdin_path`、working directory、环境变量名、timeout、
  `json/xout/text`、接受退出码和 expected artifacts；
- selected tool 的 upstream reference/action schema；
- 项目 `AGENTS.md`、verification plan 和当前 stage 的证据要求。

**用法**：在完整 verif-harness 仓库一次性安装并验证固定版本：

```bash
./scripts/setup.sh --with-xverif
# 或：make setup-xverif check-xverif
```

安装器只在 `.deps/xverif` 不存在时执行 temporary clone、detached checkout、
完整校验和 atomic publish；已有目录只验证，不 pull、不 checkout、不覆盖。

然后确认 selected wrapper 和上游身份：

```bash
python3 <skill-dir>/xverif/scripts/xverif_adapter.py probe \
  --tool xbit \
  --out /tmp/xverif-xbit-probe.json
```

复制并修改 `xverif/xverif-request.example.json`，然后运行：

```bash
python3 <skill-dir>/xverif/scripts/xverif_adapter.py run \
  --project-root . --request xverif-request.json \
  --out-dir artifacts/xverif/xbit-conv-001
```

也可经开源项目根 CLI 进入同一 adapter：

```bash
python3 scripts/verif_harness.py xverif probe --tool xbit
```

adapter 按显式 `--xverif-root` → `XVERIF_HOME` → project/current/repository
`.deps/xverif` 的固定顺序查找；正常托管使用无需传路径。

`xbit` JSON 示例 request 的核心字段为：

```json
{
  "schema_version": 1,
  "tool": "xbit",
  "operation": "conv",
  "arguments": ["conv", "8'shff", "--json"],
  "stdin_path": null,
  "working_directory": ".",
  "environment_keys": [],
  "timeout_seconds": 60,
  "output_format": "json",
  "acceptable_exit_codes": [0],
  "expected_artifacts": []
}
```

对于 xdebug/xcov/xentry 的 native JSON envelope，优先把请求写入项目内文件，
在 `stdin_path` 指定该文件并让 native arguments 从 `-` 读取。adapter 只在结果中
记录 stdin 的路径、大小和 SHA-256，不复制正文。

**输出**：唯一新 evidence directory，其中包含：

- `result.json`：adapter state、tool/operation、argv、cwd、允许的 environment key、
  request/stdin hash、xverif Git commit/remote/dirty、wrapper hash、exit code、
  native output format、parsed JSON（仅 JSON 模式）、artifact hashes 和 blockers；
- `stdout.log`：native stdout 原样字节，XOUT 不反解析、不重排、不加 marker；
- `stderr.log`：native stderr 原样字节；
- 状态 `PASS/FAIL/TIMEOUT/TOOL_NOT_FOUND/PROTOCOL_ERROR/MISSING_ARTIFACT`。

**人工参与**：选择正确的 native tool/action 和 CLI/MCP surface；评审 JSON schema、
argument、环境、EDA/NPI/license/LSF 条件、output completeness、result semantics 与
项目 stage evidence 的映射；决定失败后的下一动作，不允许自动 fallback。

**边界**：xverif 是可选、单独许可和维护的工具仓库，而不是统一 executable；
`.deps/xverif` 不进入 verif-harness Git/source archive/release；不得直接 pull 或
vendor 上游源码。adapter 只允许七个 one-shot
wrapper，不调用 MCP/loop/admin；不把 MCP 参数壳写进 CLI；不自动切 CLI/MCP、
JSON/XOUT、local/LSF、backend 或 data source；adapter `PASS` 不是 testcase PASS、
coverage/assertion closure、waiver、Stage approval 或 freeze。

## 6. 治理、闭合与发布模式

### 6.1 `audit-traceability`

**用途**：审计 feature/test/manifest/coverage/assertion ID 的结构追踪关系。

**适用场景**：计划、test、caselist 发生变化后，以及每个 stage gate 前。

**输入**：`.harness-config.json`、verification docs、TB tree；可选 manifest。

**用法**：

```bash
python3 <skill-dir>/audit-traceability/scripts/audit_traceability.py \
  --project-root . [--manifest <path>] [--json] [--out <path>] [--strict]
```

**输出**：duplicate、missing implementation、manifest mismatch、verification ID
统计、warnings/errors 和可选 JSON/report。

**人工参与**：判断 focused/retired/planned test 是否合理，并修复真正的 semantic
traceability gap。

**边界**：name/ID match 只证明结构 linkage，不证明 stimulus/checking/coverage
语义闭合；不自动修改文档或 caselist。

### 6.2 `coverage-closure`

**用途**：审计 functional coverage freeze evidence。

**适用场景**：Stage 5，coverage plan 已全部实现并完成 coverage merge。

**输入**：`coverage-evidence.json`，包含 tool/version、database IDs、每个 plan item
的 id/status/hits/plan ref、可选 approved waiver，以及 reported totals。

**用法**：

```bash
python3 <skill-dir>/coverage-closure/scripts/audit_coverage_closure.py \
  --evidence coverage-evidence.json --json \
  --out artifacts/coverage-closure.json
```

**输出**：audited covered/excluded/uncovered totals、closure percentage、blockers、
database IDs 和 `READY_FOR_HUMAN_FREEZE_REVIEW`/`BLOCKED`。

**人工参与**：对照 native VDB/UCDB/URG report，批准 denominator 和逐对象 waiver，
决定是否接受 evidence limitation。

**边界**：不解析 proprietary database、不 merge coverage、不创建 waiver；100%
reported percentage 本身不等于 closure。

### 6.3 `assertion-closure`

**用途**：审计 assertion 是否真正 compile、bind、attempt 且无未处理 failure/vacuity。

**适用场景**：Stage 5 assertion freeze review。

**输入**：`assertion-evidence.json`，包含 tool、compile/elaboration logs，以及每个
assertion 的 id、compiled、bound、attempts、passes、failures、vacuous、plan ref
和可选 approved waiver。

**用法**：

```bash
python3 <skill-dir>/assertion-closure/scripts/audit_assertion_closure.py \
  --evidence assertion-evidence.json --json \
  --out artifacts/assertion-closure.json
```

**输出**：assertion/attempt/pass/failure totals、logs、blockers 和
`READY_FOR_HUMAN_FREEZE_REVIEW`/`BLOCKED`。

**人工参与**：确认 property 语义、clock/reset、vacuity、native report 和 waiver。

**边界**：source presence 或 failure=0 不足以证明 closure；不修改 checker/bind。

### 6.4 `change-control`

**用途**：审计 approved baseline 之后的 change request 和 Git diff 覆盖。

**适用场景**：frozen decision、验证架构、RTL 行为或 sign-off baseline 发生变化。

**输入**：`changes.json` 的 baseline ref，以及每个 CR 的 id/status/description/files、
reviewer/date/rationale、tests/coverage/assertions/docs/regressions impact；可选 Git
project root。

**用法**：

```bash
python3 <skill-dir>/change-control/scripts/audit_change_control.py \
  --contract changes.json --project-root . --audit-git --json \
  --out artifacts/change-control.json
```

**输出**：CR/file counts、Git changed files、undeclared/missing/open/incomplete
blockers 和 `READY_FOR_HUMAN_REVIEW`/`BLOCKED`。

**人工参与**：批准/拒绝 CR，决定 frozen decision 是否变更，批准 RTL owner 的
修复和 rebaseline。

**边界**：输入中的 `approved` 只能记录已有 Human decision；工具不会创建批准。

### 6.5 `stage-gate-review <completed-stage>`

**用途**：从当前仓库证据生成某个 stage 的 Draft review packet。

**适用场景**：Stage N deliverables/exit criteria 已完成，准备进入 Stage N+1；
terminal Stage 使用 `--final`。

**输入**：completed stage、项目 governance/roadmap/plans、Provisional、open
questions、CR、动态 evidence 和 artifact limitations。

**用法**：

```bash
python3 <skill-dir>/stage-gate-review/scripts/build_stage_gate.py \
  --project-root . --completed-stage <N> \
  --out <docs-root>/stage<N>_gate_re_review.md
```

最终 stage 可加 `--final`；已有 draft 只有在批准 exact replacement 后才用
`--force`。

**输出**：所有判定保持未勾选的 Draft packet，列出 exit criteria、证据、
Provisional disposition 候选、open question 和 CR。

**人工参与**：逐项判断 PASS/FAIL/accepted limitation，处理 Provisional，填写
reviewer/date/Approval Decision。

**边界**：不能自行勾选 criterion、关闭问题、修改 frozen source decision 或批准 gate。

### 6.6 `signoff-audit <stage>`

**用途**：只读复核最终 sign-off packet 的结构和已记录批准元数据。

**适用场景**：请求 Human sign-off 前，或批准后确认仓库记录内部一致。

**输入**：project root、stage；可选 packet、authoritative manifest、strict mode。

**用法**：

```bash
python3 <skill-dir>/signoff-audit/scripts/audit_signoff.py \
  --project-root . --stage <N> [--packet <path>] [--manifest <path>] \
  [--json] [--out <path>] [--strict]
```

**输出**：审计 findings、可选 JSON/report，以及以下状态之一：

- `INCOMPLETE`：结构 blocker；
- `READY_FOR_HUMAN_REVIEW`：结构齐全但尚无批准；
- `APPROVED_RECORDED`：packet 中已有 Human approval record。

**人工参与**：对照 regression、coverage、assertion、CI、performance、CR 和 waiver
原始证据，执行最终 sign-off。

**边界**：`APPROVED_RECORDED` 是读取结果，不是 skill 新批准；无法验证不可访问
的原始 EDA artifact。

### 6.7 `freeze-baseline`

**用途**：在 clean Git commit 上生成证据状态校验和 SHA-256 freeze manifest。

**适用场景**：Stage 5 已获得 Human approval，准备锚定最终验证基线。

**输入**：`freeze-contract.json`，包含 freeze name、baseline ref、RTL root/policy、
required evidence、JSON state checks、include files、tool versions，以及可选已存在的
Human approval record。

**用法**：

```bash
python3 <skill-dir>/freeze-baseline/scripts/build_freeze_manifest.py \
  --project-root . --contract freeze-contract.json \
  --out /tmp/freeze-candidate.json
```

**输出**：commit、branch、baseline、clean flag、RTL diff、tool versions、state
checks、每个文件的 SHA-256/size，以及：

- `READY_FOR_HUMAN_FREEZE_REVIEW`；或
- 输入已包含有效 Human approval evidence 时的 `APPROVED_RECORDED`。

**人工参与**：review commit、hash、state、RTL diff、证据限制并批准 freeze；另行
授权 tag/push/release。

**边界**：dirty tree、missing evidence、failed state 或 disallowed RTL change
直接阻塞；不修改 Git、不 tag、不 push、不批准、不公开。

### 6.8 `oss-readiness`

**用途**：检查准备公开的干净 export 是否具备社区文件、可复现 example，并扫描
敏感标识、绝对路径和 Git history。

**适用场景**：把通用 verification infrastructure 发布到公共仓库之前；不属于
内部 DUT functional freeze 主线。

**输入**：待公开 project root、community files、denylist、example/CI；可选 history。

**用法**：

```bash
python3 <skill-dir>/oss-readiness/scripts/audit_oss_readiness.py \
  --project-root . --require-community --history
```

**输出**：敏感 pattern/path、缺失社区文件、example/CI 问题和整体 readiness。

**人工参与**：确认代码权属和公开权限，运行组织批准的 secret scanner，人工 review
每个 finding，并做 fresh-clone reproduction。

**边界**：零 finding 不证明无保密信息、不授予 license/publication rights，也不
执行发布。

### 6.9 `patterns [topic]`

**用途**：查询 harness、compile order、regression、lifecycle 或 Stage 2+ 合约模式。

**适用场景**：需要方法说明、设计 review 或问题解释，但不准备修改项目。

**输入**：可选 topic，例如 `stage1`、`regression`、`coverage`、`signoff`、`freeze`。

**用法**：

```text
$verif-harness patterns regression
$verif-harness patterns freeze
```

**输出**：基于 `references/*.md` 的说明、约束和推荐做法。

**人工参与**：把通用 pattern 与项目 spec/architecture 对齐。

**边界**：只读说明；不会自动应用 pattern 或修改任何文件。

## 7. 人工参与清单

| 人工职责 | 主要阶段 |
| --- | --- |
| 确认规格来源、验证范围和 sign-off 标准 | Stage 0 |
| 批准 Human Decisions 和每个 Stage gate | Stage 0～5 |
| 解释有歧义的协议、位切片、数值、mask、时序和 reset 语义 | 全阶段 |
| 提供 VCS/Questa/Xcelium、Syscan、license、scheduler 和 CI runner | Stage 1～5 |
| 审阅 compile/elaboration、waveform 和原始 EDA evidence | Stage 1～5 |
| 判断 mismatch 属于 RTL、TB、Golden、spec 还是 infra | Stage 2～5 |
| 修改或批准修改 DUT RTL | 出现 RTL bug 时 |
| 批准 testcase 从 candidate 晋级 default regression | Stage 2～5 |
| 批准 coverage denominator、unreachable item 和 waiver | Stage 3～5 |
| 审阅 assertion property、attempt 和 vacuity | Stage 3～5 |
| 批准 change request 和 frozen decision 变更 | 全阶段 |
| 接受无法归档等 evidence limitation | Stage gate/sign-off |
| 最终 Stage 5 sign-off 与 verification freeze | Stage 5 |
| 授权 Git tag、push、release 或公开发布 | Freeze 后 |

## 8. 最终判定原则

以下结果都不能单独代表项目已经验证完成：

- 代码生成成功；
- compile/elaboration 成功；
- regression 进程 exit code 为 0；
- Golden mismatch 为 0 但没有 engagement proof；
- coverage 报告显示 100%，但 denominator/waiver 未审查；
- assertion failure 为 0，但 attempt 为 0 或 vacuous；
- audit 返回 `READY_FOR_HUMAN_REVIEW`；
- manifest 已生成 SHA-256。

真正的 freeze 需要动态证据、结构审计、change-control、Human Stage 5 sign-off、
clean commit freeze manifest，以及单独授权的版本控制动作共同闭合。
