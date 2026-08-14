# xverif CLI adapter contract

## 定位

权威上游为 `git@github.com:BLANK2077/xverif.git`。仓库提供多个确定性工具，
而不是一个名为 `xverif` 的统一 executable：

| 工具 | 主要用途 |
| --- | --- |
| `xdebug` | daidir/FSDB 设计、波形、协议和 active-driver 事实查询 |
| `xcov` | VCS/Verdi coverage database 查询与导出 |
| `xbit` | SystemVerilog literal、slice、mask、表达式确定性计算 |
| `xentry` | 多拍 entry/descriptor/header raw field 解码 |
| `xloc` | UVM 日志位置压缩 ID 恢复与统计 |
| `xsva` | SVA 解析、IR、lint 与确定性解释 |
| `xwaveform` | 由已导出数据生成波形图和统计 |

调用链必须保持：

```text
Codex Agent
  -> verif-harness Skill/framework：选择阶段动作、解释项目语义、守住审批边界
     -> CLI adapter：验证请求、执行 argv、固定环境、超时、归档证据
        -> xverif tools/<tool>：执行底层 deterministic operation
```

`xverif` 的 native action/schema/reference 是工具参数的 source of truth；
`verif-harness` 的计划、roadmap、coverage/assertion/test plan 是“为什么执行”的
source of truth。两者不能互相替代。

## 请求合同

请求使用 `xverif-request.schema.json`。adapter 还执行 JSON Schema 之外的路径、
placeholder、secret-like argv 和精确字段检查。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `schema_version` | integer | 固定为 `1` |
| `tool` | enum | 七个白名单 wrapper 之一 |
| `operation` | string | 用于 evidence 分类的 native command/action 名称 |
| `arguments` | string array | executable 之后的原生 argv token；可为空 |
| `stdin_path` | string/null | 项目内 stdin 文件；只记录路径、大小和哈希 |
| `working_directory` | string | 项目内相对工作目录 |
| `environment_keys` | string array | 允许继承的环境变量名，不含 value |
| `timeout_seconds` | integer | 1～86400 秒 |
| `output_format` | enum | `json`、`xout` 或 `text` |
| `acceptable_exit_codes` | integer array | 明确允许的退出码，通常仅 `[0]` |
| `expected_artifacts` | string array | 项目内必须存在并归档 SHA-256 的文件 |

允许的 argv placeholder 只有：`{project_root}`、`{output_dir}`、
`{request_path}`、`{xverif_root}`。adapter 不执行 shell expansion。

## xverif 身份合同

`--xverif-root` 或 `XVERIF_HOME` 指向已批准 checkout。adapter 只从
`<xverif-root>/tools/<tool>` 解析 wrapper，并记录：

- wrapper 绝对路径、大小无关的 SHA-256；
- Git commit、origin remote、dirty 状态（存在 Git metadata 时）；
- tool name 和 adapter version。

Probe `PASS` 只代表 wrapper 存在且可执行。它不会运行真实 NPI/EDA probe，也不
代表 selected tool、license、FSDB/VDB、scheduler 或 Python dependencies 可用。

## 执行合同

1. 严格验证 request exact keys 与值域；
2. project、working directory、stdin 和 artifact 路径不得逃逸项目根；
3. argv 使用 `shell=False`；
4. 环境从最小基线开始，只加入列出的变量名，并固定 `XVERIF_HOME`；
5. stdout/stderr 原样写入单独文件；
6. JSON 必须可解析；XOUT 第一条非空行必须以 `@` 开始且正文不重写；text 只归档；
7. expected artifact 必须存在，并记录 size 与 SHA-256；
8. output directory 已存在时拒绝覆盖；
9. `result.json` 原子写入，不加入 wall-clock timestamp，以便同输入可比较。

## 结果状态

| 状态 | 含义 |
| --- | --- |
| `PASS` | 退出码、输出协议和 artifact 合同都满足 |
| `FAIL` | native tool 返回未接受退出码 |
| `TIMEOUT` | 超过 request timeout |
| `TOOL_NOT_FOUND` | approved root 中没有 selected wrapper |
| `PROTOCOL_ERROR` | JSON/XOUT 不满足声明格式 |
| `MISSING_ARTIFACT` | 必需产物缺失 |

所有非 `PASS` 状态返回非零。`PASS` 仍必须继续读取 native response 中的
`ok/status/error/finding` 与完整性字段；process `0` 不能覆盖业务失败。

## Surface 与输出边界

- xdebug/xcov/xentry 需要结构化字段时，通过其 native JSON envelope 和 `--json`
  执行；不能把 MCP 参数壳写进 CLI envelope。
- Agent 交互可以使用 XOUT，但 adapter 只做完整原文归档，不从排版反推 JSON。
- xsva 等 native text command 声明 `text`；不要强行要求 XOUT。
- 失败时禁止静默从 CLI 切 MCP、从 local 切 LSF、从 JSON 切 XOUT，或从真实数据
  切 fixture。

## 安全与人工边界

- adapter 不修改 DUT RTL，不批准测试、waiver、stage gate 或 freeze；
- environment 只保存 key，不输出 value；argv 出现 secret-like material 时拒绝；
- xdebug/xcov 的真实 EDA/NPI 动作在项目规定的获授权环境执行；
- Git commit 和 wrapper hash 证明工具身份，不证明结果语义正确；
- CI fake xverif 只验证 adapter，真实兼容性必须由 approved upstream checkout 的
  focused native operation 证明。
