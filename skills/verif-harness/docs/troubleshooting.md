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

设置 `XVERIF_HOME` 指向已批准的 `BLANK2077/xverif` checkout 根目录，或显式传
`--xverif-root <root>`。该目录下必须存在 `tools/<selected-tool>`。不要把 PyPI
同名包或任意 executable 当成该工具仓库。

## xverif probe PASS，但执行失败

Probe 只确认 wrapper 存在并记录 Git commit/hash，不启动真实依赖。根据 selected
tool 检查 Python、Verdi/NPI、VDB/FSDB、license、LSF 和它要求的 environment
keys。adapter 不会自动 fallback 到 MCP、其它 backend 或 fixture。

## xverif 返回 `PROTOCOL_ERROR`

检查 request 的 `output_format` 是否与 native 参数一致：使用 `json` 时 native
command 必须真的输出 JSON；使用 `xout` 时第一条非空行必须是 `@...`；`xsva`
等普通文本命令使用 `text`。不要从 XOUT 表格反解析 JSON，也不要让 adapter
重编码 XOUT。

## xverif native command exit 0，但业务结论仍不完整

继续读取 JSON/XOUT 的 `ok/status/error/finding` 和 canonical completeness 字段，
并核对 expected artifacts。adapter PASS 只说明调用合同满足，不证明 scan/
analysis complete、coverage closed、assertion correct 或 regression passed。

## `oss-readiness` 为零 finding，仍不能公开

零 finding 只说明自动规则没有发现问题，不证明权属、无保密信息或已获公开许可。
仍需 Human 权属审批、组织批准的 secret scan 和全新 clone 验证。

## Markdown 修改后检查失败

运行项目 `AGENTS.md` 规定的 Markdown workflow，review 自动修复 diff，然后
重新执行项目完整检查。不要通过削弱规则或 denylist 让检查变绿。
