# xverif integration

## Responsibility split

verif-harness remains the Skill and lifecycle framework. It selects the
verification task, applies repository and stage policy, and preserves Human
approval boundaries. The adapter validates and executes one request. xverif
performs the selected deterministic operation.

```text
Codex or Kimi Code Agent
  -> verif-harness Skill/framework
     -> CLI adapter or MCP runtime profile
        -> BLANK2077/xverif tools/<selected-tool> / xverif_mcp
```

The authoritative upstream is `https://github.com/BLANK2077/xverif.git`. It exposes
a family of wrappers under `tools/`; there is no assumed executable named
`xverif`.

xverif is integrated as a managed source dependency. Its source,
history, license, releases, and issue tracking remain owned by the upstream
project; verif-harness stores only a reviewed lock and installs the checkout
under the Git-ignored `.deps/` directory.

## Install the pinned dependency

```bash
cd /path/to/verif-harness
./scripts/setup --runtime codex --workspace-root /path/to/verification-workspace
# or: ./scripts/setup --runtime kimi --workspace-root /path/to/verification-workspace
```

The package checkout owns the managed `.deps/xverif` source and launcher. The
verification workspace owns `.harness/`, MCP profiles, requests, and evidence;
Stage 0 records the RTL directory separately.

Equivalent focused commands are:

```bash
make setup-xverif
make check-xverif
```

`deps/xverif.lock.json` fixes the HTTPS repository, full Git object ID, MIT
License hash, seven CLI wrappers, and the `xverif_mcp` package/launcher. Installation
uses a temporary checkout, validates it completely, and atomically publishes
`.deps/xverif`. An existing checkout is never overwritten or silently updated;
origin, commit, dirty state, license hash, package layout, launcher, or wrapper
drift returns `BLOCKED`.

## Supported one-shot wrappers

| Wrapper | Adapter use |
| --- | --- |
| `xbit` | SystemVerilog literal, slice, mask, and expression calculation |
| `xdebug` | Design, waveform, protocol, and active-driver fact queries |
| `xcov` | Coverage database queries and exports |
| `xentry` | Structured entry/descriptor/header field decoding |
| `xloc` | Compressed log-location resolution and statistics |
| `xsva` | SVA list, scan, lint, parse, and explain operations |
| `xwaveform` | Rendering from previously exported waveform manifests |

MCP is a separate surface from the one-shot CLI adapter. Loop-server, LSF
administration, and test orchestration are not part of the CLI request contract.

## MCP 安装、配置和使用

锁定的 xverif commit 已包含 `xverif_mcp` FastMCP server，以及
`tools/xverif-mcp` launcher。安装 source checkout：

```bash
/path/to/verif-harness/scripts/managed-python \
  /path/to/verif-harness/scripts/verif_harness.py xverif mcp install \
  --project-root /path/to/verification-workspace
```

setup 会同时安装并验证 source、launcher 和 commit，并在 managed CPython
环境安装 artifact-hash-locked 的 `mcp[cli]==1.29.1` 传递依赖；2.x 不满足锁定
xverif server 的 `mcp.server.fastmcp` API 合同。

为当前 Agent runtime 生成项目级、无凭据 profile：

```bash
/path/to/verif-harness/scripts/managed-python \
  /path/to/verif-harness/scripts/verif_harness.py xverif mcp configure \
  --project-root /path/to/verification-workspace --runtime codex --backend direct
```

Kimi Code 使用 `--runtime kimi`。profile 写入
`.harness/mcp/xverif.json`，只记录 runtime、direct/LSF backend、锁定 commit、
所需环境变量名和 `project-managed` 注册边界。`configure` 同时生成工作区内的
`.harness/mcp/xverif-mcp` launcher，并将它注册到 `.codex/config.toml` 或
`.kimi-code/mcp.json`。这些文件不会写入 token、license 值或私有 URL，也不会
修改 Codex/Kimi 的用户级配置；已有的同名冲突注册会阻断 setup。

检查 source、profile、项目级注册和 Python SDK：

```bash
python3 /path/to/verif-harness/scripts/verif_harness.py xverif mcp status \
  --project-root /path/to/verification-workspace
```

默认 setup 会自动执行上述 configure/status。使用 `--no-agent --runtime auto` 时，
若 PATH 中只有一种 Agent CLI 就自动选择并注册；无法唯一确定 runtime 时只安装
依赖并明确报告未注册。传入 `--runtime codex` 或 `--runtime kimi` 即使不启动
Agent 也会完成项目级注册。LSF 使用显式
`--backend lsf` 重新 configure；direct 与 LSF 不自动互换。注册后仍须由新启动的
Agent session 调用 `xverif_ping`，静态文件检查不能伪造协议成功。

Kimi 0.38 的 `--prompt` 是阻塞的非交互请求，不能作为 TUI initial prompt。setup
不会在 Kimi TUI 前运行模型清单，避免认证、模型请求或 MCP 初始化令启动无限等待。
进入 TUI 后使用 `/mcp` 查看 host 连接状态；底部出现
`MCP server "xverif" connected` 仍只证明 host 已挂载 tool schema，首次真实协议
探针依旧是 `xverif_ping`。

注册完成后，第一次调用必须是 `xverif_ping`。随后先调用 `xverif_tools` 获取工具
目录，再按 upstream schema 使用 `xverif_xdebug_*`、`xverif_xcov_*`、`xverif_bit_*`、
`xverif_entry_*`、`xverif_loc_*` 或 `xverif_sva_*`。xdebug/xcov 的有状态流程必须
遵循 `session_open -> query -> session_close`；禁止猜 action、自动重试、自动切换
direct/LSF 或把 MCP response 直接当作 closure。

`mcp probe` 只做 fail-closed 提示：真实协议探针必须由 Codex/Kimi 调用
`xverif_ping` 完成。CLI 静态检查不能证明 Agent host 已注册 MCP server。

## Probe

Normal Agent CLI usage goes through the shortened Skill namespace:

```text
$verif-harness evidence probe --tool xbit
```

For CI or shell automation, the underlying wrapper remains available:

```bash
python3 scripts/verif_harness.py xverif probe --tool xbit
```

Probe checks only that `tools/xbit` exists and is executable. It records the
wrapper SHA-256 and, when available, checkout commit, remote, and dirty state.
It does not prove Python, NPI, EDA, license, FSDB/VDB, or scheduler readiness.

## Execute a request

Copy `skills/verif-harness/xverif/xverif-request.example.json`, review it
against the selected tool's upstream schema/reference, then run:

```bash
python3 scripts/verif_harness.py xverif run \
  --project-root . \
  --request xverif-request.json \
  --out-dir artifacts/xverif/xbit-conv-001
```

This lower-level form is intended for CI/automation. In Codex or Kimi Code,
delegate the reviewed request with `$verif-harness evidence ...` and let the
Skill preserve the same adapter contract and evidence paths.

The output directory must not exist. It receives `result.json`, `stdout.log`,
and `stderr.log`. The result contains request and stdin hashes, exact argv,
allowlisted environment-key names, native output format, parsed JSON when
requested, expected-artifact hashes, and blockers.

Root discovery is deterministic:

```text
explicit --xverif-root
-> XVERIF_HOME
-> <project-root>/.deps/xverif
-> verif-harness package checkout .deps/xverif
-> fail closed
```

Explicit roots remain available for development and controlled forks. Normal
repository use relies on the managed checkout.

## Dependency upgrade

Do not run `git pull` inside `.deps/xverif`. Review the new upstream commit and
license/third-party changes, update the lock and license hash, move the old
managed checkout aside, then rerun setup and the full checks. The lock change,
adapter evidence, public CI, and third-party notice must be reviewed together.

## Determinism and safety

- Requests use an exact JSON contract with no unknown keys.
- Only seven native wrappers can be selected.
- Arguments are tokens executed with `shell=False`; no shell string is used.
- Paths cannot escape the project root.
- Environment values are never written to the result.
- Native XOUT is preserved byte-for-byte and is not reverse-parsed.
- JSON and XOUT declarations are validated; text is archived without parsing.
- Existing evidence directories are never overwritten.
- Existing managed dependency directories are never overwritten or updated.
- Failures never trigger an automatic surface, backend, transport, format, or
  data-source fallback.
- MCP source installation alone never implies registration. Explicit-runtime
  setup/configure proves project registration structure, but not protocol
  availability; record the native `xverif_ping` response separately.

Adapter `PASS` means the invocation contract passed. Consumers must still read
the native result and completeness fields. It is not a testcase verdict,
coverage/assertion closure, stage approval, waiver, or freeze authorization.

The managed checkout is not included in verif-harness archives. Public CI runs
the hermetic adapter and real xbit smoke only. EDA-dependent xdebug/xcov work
still requires a separately authorized environment and must not publish vendor
headers, libraries, binaries, databases, or license configuration.
