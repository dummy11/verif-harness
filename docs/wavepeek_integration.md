# WavePeek integration

WavePeek is a separately owned deterministic CLI for bounded RTL
waveform inspection. verif-harness supplies lifecycle policy, a closed request
contract, provenance capture, and fail-closed execution; WavePeek owns VCD/FST
parsing and queries.

```text
Codex/Kimi Code Agent -> verif-harness Skill -> WavePeek adapter -> pinned WavePeek CLI
```

## Managed setup

```bash
./scripts/setup.sh --runtime codex   # or --runtime kimi
# or
make setup-wavepeek check-wavepeek
```

`deps/wavepeek.lock.json` fixes the HTTPS repository, tag, full commit,
version, Apache-2.0 License hash, Cargo.lock hash, empty feature set, official
release URL, and four platform archive SHA-256 values. The installer clones
the exact tag into `.deps/wavepeek`, verifies the current platform's official
VCD/FST release archive, and stores the executable at
`.deps/wavepeek-bin/wavepeek`. Existing or inconsistent state is never
overwritten. Both paths are excluded from source archives and releases. No
Rust toolchain or crates.io access is required.

The default build intentionally omits `fsdb`. Upstream FSDB support requires a
proprietary Verdi SDK and is outside public CI and the managed default.

## Adapter use

Normal Agent CLI usage goes through the shortened Skill namespace:

```text
$verif-harness waveform probe
```

For CI or shell automation, the underlying wrapper remains available:

```bash
python3 scripts/verif_harness.py wavepeek probe
python3 scripts/verif_harness.py wavepeek run \
  --project-root . --request wavepeek-request.json \
  --out-dir artifacts/wavepeek/query-001
```

In Codex or Kimi Code, use `$verif-harness waveform ...` for the reviewed
waveform operation; the Skill delegates to the same bounded adapter.

Start from `skills/verif-harness/wavepeek/wavepeek-request.example.json`. The
request fixes the operation, native argv, working directory, explicitly
forwarded environment-key names, timeout, output protocol, accepted exit
codes, and expected artifacts. Obtain exact WavePeek flags from the pinned
`help`, `docs`, and `schema` commands; do not infer signal or time semantics.

The adapter invokes no shell. It records request, binary, stdout, stderr, and
artifact hashes plus source Git identity. JSON must parse. JSONL must start
with `begin`, end with `end`, and have contiguous sequence numbers. Timeout,
unexpected exit, malformed output, or missing artifacts fails closed.

Adapter PASS means only that the exact query ran under the recorded contract.
It does not approve expected values, signal selection, property meaning,
waivers, stage gates, or verification closure.
