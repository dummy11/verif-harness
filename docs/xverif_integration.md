# xverif integration

## Responsibility split

verif-harness remains the Skill and lifecycle framework. It selects the
verification task, applies repository and stage policy, and preserves Human
approval boundaries. The adapter validates and executes one request. xverif
performs the selected deterministic operation.

```text
Codex Agent
  -> verif-harness Skill/framework
     -> CLI adapter
        -> BLANK2077/xverif tools/<selected-tool>
```

The authoritative upstream is `git@github.com:BLANK2077/xverif.git`. It exposes
a family of wrappers under `tools/`; there is no assumed executable named
`xverif`.

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
  --xverif-root /path/to/xverif --tool xbit
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
  --xverif-root /path/to/xverif \
  --out-dir artifacts/xverif/xbit-conv-001
```

The output directory must not exist. It receives `result.json`, `stdout.log`,
and `stderr.log`. The result contains request and stdin hashes, exact argv,
allowlisted environment-key names, native output format, parsed JSON when
requested, expected-artifact hashes, and blockers.

## Determinism and safety

- Requests use an exact JSON contract with no unknown keys.
- Only seven native wrappers can be selected.
- Arguments are tokens executed with `shell=False`; no shell string is used.
- Paths cannot escape the project root.
- Environment values are never written to the result.
- Native XOUT is preserved byte-for-byte and is not reverse-parsed.
- JSON and XOUT declarations are validated; text is archived without parsing.
- Existing evidence directories are never overwritten.
- Failures never trigger an automatic surface, backend, transport, format, or
  data-source fallback.

Adapter `PASS` means the invocation contract passed. Consumers must still read
the native result and completeness fields. It is not a testcase verdict,
coverage/assertion closure, stage approval, waiver, or freeze authorization.
