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

xverif is integrated as an optional managed source dependency. Its source,
history, license, releases, and issue tracking remain owned by the upstream
project; verif-harness stores only a reviewed lock and installs the checkout
under the Git-ignored `.deps/` directory.

## Install the pinned dependency

```bash
./scripts/setup.sh --with-xverif
```

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
python3 scripts/verif_harness.py xverif mcp install --project-root .
```

这一步只安装并验证 source、launcher 和 commit，不会自动安装 Python 的
`mcp[cli]` 传递依赖。请在 Codex/Kimi 使用的 Python 3.11+ 环境中按部署策略安装
该依赖，例如：

```bash
python3 -m pip install "mcp[cli]"
```

为当前 Agent runtime 生成项目级、无凭据 profile：

```bash
python3 scripts/verif_harness.py xverif mcp configure \
  --project-root . --runtime codex --backend direct
```

Kimi Code 使用 `--runtime kimi`。profile 写入
`.harness/mcp/xverif.json`，只记录 runtime、direct/LSF backend、锁定 commit、
所需环境变量名和 `host-managed` 注册边界；不会写入 token、license 值、私有 URL、
绝对路径，也不会覆盖 Codex/Kimi 的用户配置。

检查 source、profile 和 Python SDK：

```bash
python3 scripts/verif_harness.py xverif mcp status --project-root .
```

然后在当前 Agent runtime 的 MCP 配置中注册一个名为 `xverif` 的 stdio server，
使用 `.deps/xverif/tools/xverif-mcp` 作为 launcher，并显式传入 profile 要求的环境
变量。Codex 与 Kimi 的注册语法由各自 runtime 管理，verif-harness 不猜测或改写其
私有配置。

通用 stdio descriptor 可以按当前 runtime 的 MCP 配置格式改写；以下模板不包含
凭据和机器真实路径：

```json
{
  "mcpServers": {
    "xverif": {
      "type": "stdio",
      "command": "<project-root>/.deps/xverif/tools/xverif-mcp",
      "args": [],
      "env": {
        "XVERIF_HOME": "<project-root>/.deps/xverif",
        "PYTHONPATH": "<project-root>/.deps/xverif/xverif_mcp/src:<project-root>/.deps/xverif",
        "XVERIF_MCP_BACKEND": "direct",
        "VERDI_HOME": "<verdi-install>",
        "PATH": "<complete-path>"
      }
    }
  }
}
```

LSF 使用 `XVERIF_MCP_BACKEND=lsf`，并额外显式提供 profile 要求的 LSF/license
环境变量。不要把这个带 placeholder 的 descriptor 误当作已注册证明；注册后仍须
调用 `xverif_ping`。

注册完成后，第一次调用必须是 `xverif_ping`。随后先调用 `xverif_tools` 获取工具
目录，再按 upstream schema 使用 `xverif_xdebug_*`、`xverif_xcov_*`、`xverif_bit_*`、
`xverif_entry_*`、`xverif_loc_*` 或 `xverif_sva_*`。xdebug/xcov 的有状态流程必须
遵循 `session_open -> query -> session_close`；禁止猜 action、自动重试、自动切换
direct/LSF 或把 MCP response 直接当作 closure。

`mcp probe` 只做 fail-closed 提示：真实协议探针必须由 Codex/Kimi 调用
`xverif_ping` 完成。CLI 静态检查不能证明 Agent host 已注册 MCP server。

## Probe

```bash
python3 scripts/verif_harness.py xverif probe \
  --tool xbit
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

The output directory must not exist. It receives `result.json`, `stdout.log`,
and `stderr.log`. The result contains request and stdin hashes, exact argv,
allowlisted environment-key names, native output format, parsed JSON when
requested, expected-artifact hashes, and blockers.

Root discovery is deterministic:

```text
explicit --xverif-root
-> XVERIF_HOME
-> <project-root>/.deps/xverif
-> current/repository .deps/xverif
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
- MCP source/profile setup never implies runtime registration or protocol
  availability; record the native `xverif_ping` response separately.

Adapter `PASS` means the invocation contract passed. Consumers must still read
the native result and completeness fields. It is not a testcase verdict,
coverage/assertion closure, stage approval, waiver, or freeze authorization.

The managed checkout is not included in verif-harness archives. Public CI runs
the hermetic adapter and real xbit smoke only. EDA-dependent xdebug/xcov work
still requires a separately authorized environment and must not publish vendor
headers, libraries, binaries, databases, or license configuration.
