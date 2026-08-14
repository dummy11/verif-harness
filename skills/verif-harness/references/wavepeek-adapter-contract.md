# WavePeek adapter contract

The adapter is an execution and evidence boundary:

```text
Codex Agent -> verif-harness Skill -> WavePeek adapter -> pinned WavePeek CLI
```

The managed source checkout is `.deps/wavepeek`; the compiled executable is
`.deps/wavepeek-bin/wavepeek`. Both are excluded from Git and release archives.
Discovery order is explicit CLI arguments, `WAVEPEEK_HOME`/`WAVEPEEK_BIN`, the
request project's managed paths, the current directory, then the
verif-harness repository managed paths.

Requests are closed-schema JSON. `arguments[0]` must equal the allowlisted
operation. Execution uses an argv vector with no shell and a controlled
environment. Evidence records request, binary, stdout, stderr, and artifact
hashes plus source Git identity. JSON must parse. JSONL must contain contiguous
sequence numbers and complete `begin`/`end` records. Timeout, unexpected exit,
malformed output, and missing artifacts fail closed.

WavePeek query success is not RTL verification approval. Signal interpretation,
property meaning, expected values, time-window selection, and closure remain
governed verification decisions.
