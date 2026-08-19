# xverif integration

## Responsibility split

verif-harness remains the Skill and lifecycle framework. It selects the
verification task, applies repository and stage policy, and preserves Human
approval boundaries. The adapter validates and executes one request. xverif
performs the selected deterministic operation.

```text
Codex or Kimi Code Agent
  -> verif-harness Skill/framework
     -> CLI adapter
        -> BLANK2077/xverif tools/<selected-tool>
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
License hash, and required wrapper set. Installation uses a temporary checkout,
validates it completely, and atomically publishes `.deps/xverif`. An existing
checkout is never overwritten or silently updated; origin, commit, dirty state,
license hash, or wrapper drift returns `BLOCKED`.

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

MCP, loop-server, LSF administration, installation, and test orchestration are
not part of this one-shot adapter.

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

Adapter `PASS` means the invocation contract passed. Consumers must still read
the native result and completeness fields. It is not a testcase verdict,
coverage/assertion closure, stage approval, waiver, or freeze authorization.

The managed checkout is not included in verif-harness archives. Public CI runs
the hermetic adapter and real xbit smoke only. EDA-dependent xdebug/xcov work
still requires a separately authorized environment and must not publish vendor
headers, libraries, binaries, databases, or license configuration.
