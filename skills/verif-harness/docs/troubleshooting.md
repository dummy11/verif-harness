# 故障处理

## 未指定模式时只运行了 `doctor`

这是预期行为。项目存在 `.harness-config.json` 时，默认模式是只读检查。
先阅读它报告的 stage 状态，再显式调用建议的写模式。

## `init` 拒绝执行

`init` 只适用于尚无 `.harness-config.json` 的项目。已有项目应运行
`doctor`，不能重新 bootstrap 并覆盖人工内容。

## 生成器拒绝覆盖文件

所有写模式默认只增不覆盖。比较已有实现和生成合约，走人工 merge 或项目
change-control。除非对应模式明确支持且 exact target 已获批准，不要使用强制覆盖。

## `complete-uvc` 拒绝协议

当前具体生成器只支持合约声明的 ready/valid source。其他控制、SRAM、
credit、request/response 或多通道协议必须依据项目架构和 coding guide 实现，
不能通过改名绕过检查。

## Scoreboard 不是 FIFO 对齐

不要使用 `complete-scoreboard`。Port-level compare、tag matching、乱序返回或
项目专用 Golden wrapper 需要独立评审的实现和 evidence contract。

## 编译报告 unknown type/package

检查规范编译顺序：defines → shared packages → interfaces → RTL → checker →
bind → UVC packages/classes → env/test → harness/top。不要在 package 内
`` `include`` interface 源文件。

## Regression 进程返回 0，但 collector 不判 PASS

Collector 还要求稳定的 end-of-test banner。启用 Golden 时，还要求 Golden
engaged、supported traffic 非零、mismatch/residual 为零。缺 banner、NOLOG、
CRASH 或 NO-COMPARE 都不能判 PASS。

## `regression-triage` 保持 BLOCKED

逐项确认：

- primary log 存在；
- 命中已评审的 signature rule；
- 原始 numeric seed 存在；
- 同 testcase、同 seed 的 rerun report 存在。

即使 READY，candidate classification 仍需人工 root-cause review。

## 报告 functional coverage 100%，但 closure 失败

总百分比不够。检查每个 plan ID、非零 hit、重复 ID、coverage database identity、
逐项 totals，以及每个 exclusion 是否带完整 `Approved` waiver metadata。

## Assertion failure 为 0，但 closure 失败

确认 assertion 已 compile、bind/elaborate、attempts > 0，并检查 vacuity、采样
时钟和 reset disable。零 failure 加零 attempt 不是证据。

## `change-control` 报 undeclared Git change

把 baseline 后每个 changed file 放入对应 CR，并记录 tests、coverage、assertion、
docs 和 regression 影响。不能为了通过审计而把未批准 CR 标为 approved。

## `freeze-baseline` 拒绝 dirty worktree

通过项目 workflow 提交或处理确切的 pending changes，再从 clean commit 重跑。
该工具故意没有 `--allow-dirty` 绕过参数。

## 无法得到 `APPROVED_RECORDED`

Sign-off/freeze evidence 必须已经包含完整 Human approval record，而且 approval
evidence 本身必须进入 required-evidence 哈希集合。不能伪造 metadata 改状态。

## 本机无法运行 commercial simulator

不要把 license value、scheduler setting、secret 或内部路径提交进仓库。在获授权
的 EDA 环境执行，返回与 commit、seed、manifest、simulator version 绑定的日志和
报告。无法归档时记录 evidence limitation，不能把缺失证据转为 PASS。

## `xverif` adapter 报 `set XVERIF_HOME`

在完整 verif-harness 仓库先运行 `./scripts/setup.sh --with-xverif`，确认
`.deps/xverif` 已按 lock 安装。独立 Skill 环境可设置 `XVERIF_HOME` 指向已批准
checkout，或显式传 `--xverif-root <root>`。该目录下必须存在
`tools/<selected-tool>`。不要把 PyPI 同名包或任意 executable 当成该工具仓库。

## managed xverif 返回 `BLOCKED`

检查 `origin`、`HEAD`、`git status --porcelain`、`LICENSE` hash 和七个 wrapper。
安装器不会覆盖、清理、checkout 或 pull 已存在目录。不要在 `.deps/xverif`
直接 `git pull`；依赖升级必须先评审新 commit/许可证/第三方边界并更新 lock，
再用新 checkout 重跑 `make setup-xverif check-xverif`。

## Spec Kit 安装提示需要 Python 3.11

固定的 Spec Kit v0.16.4 明确要求 Python 3.11 或更新版本。系统 `python3` 较旧时，
使用已批准的 3.11+ interpreter：

```bash
python3.11 scripts/setup_spec_kit.py
python3.11 scripts/check_spec_kit.py
```

不要降低 lock 中的 `python_requires`，也不要让主项目运行时依赖 Spec Kit。它是
可选规格子系统，core structure/test/example 在未安装时仍应工作。

## Agent runtime 无法解析

`runtime status` 只接受 Codex (`codex`) 或 Kimi Code (`kimi`)。优先检查
`.specify/integration.json`；它是已 bootstrap 项目的唯一事实源。新项目使用
`spec-kit bootstrap --integration codex|kimi` 明确选择，或在只存在一个
`.agents/.codex/.kimi-code` marker 时使用 `--integration auto`。同时存在多个
marker 或没有 marker 时，工具会 fail closed，不按当前模型名称猜测。

## 切换模型或 Agent runtime

同一 runtime 内切换模型（例如 Kimi Code 切到 K3）不修改 integration、spec、task
或 evidence。按 runtime 官方方式选模型，运行 runtime-native `doctor`，然后恢复
原 workflow。Codex 与 Kimi Code 之间切换应在 review gate 暂停时执行：

```bash
python3 scripts/verif_harness.py runtime switch \
  --project-root <project> --to <codex|kimi>
```

不要手工编辑 `.specify/integration.json`，也不要自动传 `--force`；managed Skill
文件有人工修改时，先 review 差异。完整步骤见顶层 `docs/runtime_switching.md`。

## managed Spec Kit 返回 `BLOCKED`

先检查 `.deps/spec-kit` 与 `.deps/spec-kit-venv` 是否只存在一个、source checkout
是否 dirty、origin/commit/LICENSE/pyproject hash 是否与 lock 一致。安装器不会覆盖
或清理部分状态；把精确路径备份后移出 `.deps/`，再运行：

```bash
make setup-spec-kit
make check-spec-kit
```

不要在 managed checkout 中开发，也不要用 `git pull` 更新；升级必须先审阅新
release、完整 commit、license、Python requirement 和 lock hash。

## Spec Kit 与 `sim/docs/` 内容冲突

新项目以 `specs/` 为唯一可编辑 requirement source。`sim/docs/` 只保存治理、
派生视图、证据索引和 review packet；发现冲突时停止执行，把差异记录为 open
question 或 change request，并从已批准的 Spec Kit spec 重新生成视图。不要双向
人工编辑，也不要把派生视图静默提升成权威。

已批准的存量项目先把原文档登记为 immutable imported baseline。不要为了迁移
重写审批日期、Human Decisions、证据或开发历史。

## Spec Kit workflow gate 通过但 Stage 不能关闭

这是预期行为。Spec Kit gate 只审阅文档或授权 reviewed tasks 的执行；它不证明
compile、simulation、coverage、assertion、performance 或 regression，也不授予
waiver、Stage approval、sign-off 或 freeze。继续收集 EDA evidence，运行对应的
closure/audit mode，再由 `stage-gate-review` 生成 packet 交 Human 决策。

## tasks 已声明 mode，但 implement 后没有对应产物

不要在 workflow 外静默手动调用该 mode。先按 task contract 核对：mode 名称、input
contract、owned output/evidence path、validation command 和 Human gate。只要任一
输出缺失或 validation 失败，该 task 就是 incomplete，即使 `speckit.implement`
进程本身成功退出。

让 `converge` 记录 dispatch deviation，并保留原 run ID、task ID、已有产物和日志。
修正规格、task 或执行环境后，按项目批准的 recovery 路径重试同一个 task；重试
必须留痕且不得覆盖先前 evidence。该规则适用于 `init`、所有生成模式、xverif、
WavePeek、回归/审计/closure 模式，不允许把重复手动调用当作正常流程。

## xverif probe PASS，但执行失败

Probe 只确认 wrapper 存在并记录 Git commit/hash，不启动真实依赖。根据 selected
tool 检查 Python、Verdi/NPI、VDB/FSDB、license、LSF 和它要求的 environment
keys。adapter 不会自动 fallback 到 MCP、其它 backend 或 fixture。

## xverif MCP 返回 `MCP_SDK_MISSING`

`xverif mcp install` 只安装锁定 checkout 中的 `xverif_mcp` source 和
`tools/xverif-mcp` launcher，不会把 Python `mcp[cli]` 传递依赖偷偷安装到当前
环境。请在 Codex/Kimi 实际使用的 Python 3.11+ 环境安装该依赖，再运行：

```bash
python3 scripts/verif_harness.py xverif mcp status --project-root .
```

不要把 `.mcp.json`、token、license 值或本机绝对路径提交到项目仓库。

## xverif MCP 已配置但 `xverif_ping` 失败

先确认 runtime 注册的是 `.deps/xverif/tools/xverif-mcp`，且 profile 的
`XVERIF_HOME`/`PYTHONPATH`/`VERDI_HOME`/`PATH` 等环境变量在 MCP 子进程中显式可见。
MCP server 不保证继承外层 shell 环境；direct 与 LSF 不能自动互换。先读取
server 的原始错误，再分别检查 Python、Verdi/NPI、license、VDB/FSDB 或 LSF。
`mcp status` 的 `READY_FOR_RUNTIME_REGISTRATION` 只表示 source/profile/SDK 合同
通过，不表示 Agent host 已完成注册。

## xverif MCP session 卡住或超时

xdebug/xcov 使用独立 stdio-loop session。确认每次操作遵循
`session_open -> query -> session_close`，不要复用错误 backend 的 session_id，
也不要自动重试或自动切换 direct/LSF。检查 MCP 子进程显式传入的
`XVERIF_MCP_STARTUP_TIMEOUT_SEC`、`XVERIF_MCP_REQUEST_TIMEOUT_SEC`、
`XDEBUG_SESSION_START_TIMEOUT_SEC` 和 `XDEBUG_SESSION_IDLE_TIMEOUT_SEC`。

## xverif 返回 `PROTOCOL_ERROR`

检查 request 的 `output_format` 是否与 native 参数一致：使用 `json` 时 native
command 必须真的输出 JSON；使用 `xout` 时第一条非空行必须是 `@...`；`xsva`
等普通文本命令使用 `text`。不要从 XOUT 表格反解析 JSON，也不要让 adapter
重编码 XOUT。

## xverif native command exit 0，但业务结论仍不完整

继续读取 JSON/XOUT 的 `ok/status/error/finding` 和 canonical completeness 字段，
并核对 expected artifacts。adapter PASS 只说明调用合同满足，不证明 scan/
analysis complete、coverage closed、assertion correct 或 regression passed。

## managed WavePeek 返回 `BLOCKED`

检查 `.deps/wavepeek` 与 `.deps/wavepeek-bin/wavepeek` 是否只存在一半、source
是否 dirty、origin/HEAD/License/Cargo.lock 是否与 lock 不同，或 binary version
是否不匹配。安装器不覆盖已有状态。先保存人工文件，由 Human 明确移走这两个
exact path，再运行 `make setup-wavepeek check-wavepeek`。首次安装需要访问固定
GitHub tag 和官方 release archive，不需要 Rust 或 crates.io。

## WavePeek 返回 `PROTOCOL_ERROR`

让 request 的 `output_format` 与 native flag 对齐：`json` 查询使用 `--json`
（`schema` 本身直接输出 JSON）；`jsonl` 查询使用 `--jsonl`，并必须有完整
`begin`/`end` 和连续 `seq`；human output 使用 `text`。不要放宽 parser 来掩盖
contract mismatch。

## WavePeek 无法读取 FSDB

managed build 有意不启用 `fsdb` feature。FSDB 依赖单独许可的 Verdi SDK，不能
通过把 vendor header/library 或 license 变量加入公开仓库来修复。需要时建立经
Human 批准的本地 extension，并继续保证 Git/release 脱敏。

## `oss-readiness` 为零 finding，仍不能公开

零 finding 只说明自动规则没有发现问题，不证明权属、无保密信息或已获公开许可。
仍需 Human 权属审批、组织批准的 secret scan 和全新 clone 验证。

## Markdown 修改后检查失败

运行项目 `AGENTS.md` 规定的 Markdown workflow，review 自动修复 diff，然后
重新执行项目完整检查。不要通过削弱规则或 denylist 让检查变绿。
