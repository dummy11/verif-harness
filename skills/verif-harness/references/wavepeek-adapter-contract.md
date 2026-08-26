# WavePeek adapter contract

The adapter is an execution and evidence boundary:

```text
Codex/Kimi Code Agent -> verif-harness Skill -> WavePeek adapter -> pinned WavePeek CLI
```

The managed source checkout is `.deps/wavepeek`; the compiled executable is
`.deps/wavepeek-bin/wavepeek`. Both are excluded from Git and release archives.
Linux hosts older than glibc 2.34 additionally use `.deps/glibc-2.34` and a
`.deps/wavepeek-bin/wavepeek-runtime.json` descriptor. The adapter validates
the private loader and locally managed `libgcc_s.so.1` hashes and invokes them
with `--library-path` for WavePeek only; it never exports `LD_LIBRARY_PATH` or
changes the system libc. The copied GCC runtime remains under `.deps/`, records
its separate license identity, and is excluded from source archives/releases.
Discovery order is explicit CLI arguments, `WAVEPEEK_HOME`/`WAVEPEEK_BIN`, the
request project's managed paths, the current directory, then the
verif-harness repository managed paths.

Requests are closed-schema JSON. `arguments[0]` must equal the allowlisted
operation. Execution uses an argv vector with no shell and a controlled
environment. Evidence records request, the real WavePeek binary, optional
private loader identity, stdout, stderr, and artifact hashes plus source Git
identity. JSON must parse. JSONL must contain contiguous
sequence numbers and complete `begin`/`end` records. Timeout, unexpected exit,
malformed output, and missing artifacts fail closed.

WavePeek query success is not RTL verification approval. Signal interpretation,
property meaning, expected values, time-window selection, and closure remain
governed verification decisions.
