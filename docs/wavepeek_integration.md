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
cd /path/to/verif-harness
./scripts/setup --runtime codex --workspace-root /path/to/verification-workspace
# or: ./scripts/setup --runtime kimi --workspace-root /path/to/verification-workspace
# or
make setup-wavepeek check-wavepeek
```

The setup command is run from the verif-harness package checkout. WavePeek is
managed below that checkout's `.deps/`; waveform requests and output artifacts
remain below the verification workspace.

`deps/wavepeek.lock.json` fixes the HTTPS repository, tag, full commit,
version, Apache-2.0 License hash, Cargo.lock hash, empty feature set, official
release URL, four platform archive SHA-256 values, and the GNU glibc 2.34
source/license hashes used by the Linux compatibility path. The installer clones
the exact tag into `.deps/wavepeek`, verifies the current platform's official
VCD/FST release archive, and stores the executable at
`.deps/wavepeek-bin/wavepeek`. Existing or inconsistent state is never
overwritten. On Linux, setup checks the host glibc first. A host older than
2.34 gets an isolated `.deps/glibc-2.34` built from the locked GNU source;
only WavePeek is invoked through its loader and private library path. System
glibc and global `LD_LIBRARY_PATH` remain unchanged. These paths are excluded
from source archives and releases. No Rust toolchain or crates.io access is
required; the private glibc path requires the normal C build prerequisites,
including GCC and GNU Make.

The official WavePeek binary's `libgcc_s.so.1` dependency is copied from the
validated GCC into the same private runtime. Setup records its source and
installed SHA-256 plus its separate GPL-3.0-or-later WITH GCC-exception-3.1
identity. The runtime descriptor and adapter verify the copied library before
each invocation; neither a host library directory nor a global
`LD_LIBRARY_PATH` is added.

Release and private-glibc archives use the host `curl` or `wget` HTTPS trust
path and are then checked against their locked SHA-256. TLS verification is
never disabled; enterprise CA roots must be configured through the host
downloader's normal trust mechanism.

The default build intentionally omits `fsdb`. Upstream FSDB support requires a
proprietary Verdi SDK and is outside public CI and the managed default.

## Adapter use

Normal Agent CLI usage goes through the shortened Skill namespace:

```text
$verif-harness waveform probe
```

For CI or shell automation, the underlying wrapper remains available:

```bash
python3 /path/to/verif-harness/scripts/verif_harness.py wavepeek probe
python3 /path/to/verif-harness/scripts/verif_harness.py wavepeek run \
  --project-root /path/to/verification-workspace \
  --request /path/to/verification-workspace/wavepeek-request.json \
  --out-dir /path/to/verification-workspace/artifacts/wavepeek/query-001
```

In Codex or Kimi Code, use `$verif-harness waveform ...` for the reviewed
waveform operation; the Skill delegates to the same bounded adapter.

Start from `skills/verif-harness/wavepeek/wavepeek-request.example.json`. The
request fixes the operation, native argv, working directory, explicitly
forwarded environment-key names, timeout, output protocol, accepted exit
codes, and expected artifacts. Obtain exact WavePeek flags from the pinned
`help`, `docs`, and `schema` commands; do not infer signal or time semantics.

The adapter invokes no shell. It records request, the real WavePeek binary,
the optional private loader identity, stdout, stderr, and artifact hashes plus
source Git identity. JSON must parse. JSONL must start
with `begin`, end with `end`, and have contiguous sequence numbers. Timeout,
unexpected exit, malformed output, or missing artifacts fails closed.

Adapter PASS means only that the exact query ran under the recorded contract.
It does not approve expected values, signal selection, property meaning,
waivers, stage gates, or verification closure.
