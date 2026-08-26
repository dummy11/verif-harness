# WavePeek mode

Use this mode for deterministic, bounded inspection of VCD/FST waveform
artifacts. It delegates to the separately owned
[`kleverhq/wavepeek`](https://github.com/kleverhq/wavepeek) CLI through a
strict request file and records replayable evidence.

## Required reads

Read `wavepeek-request.schema.json`, the selected request, and
`../references/wavepeek-adapter-contract.md`. For exact WavePeek flags and
machine contracts, run the pinned executable's `help`, `docs`, and `schema`
commands; do not guess them.

## Workflow

1. Confirm waveform inputs are authorized artifacts and remain inside the
   project root.
2. In the verif-harness repository, install/validate the locked source and
   binary with `scripts/setup_wavepeek.py`; never clone a moving branch.
3. Review the request allowlist, arguments, output mode, timeout, environment
   key names, acceptable exit codes, and expected artifacts.
4. Run `scripts/verif_harness.py wavepeek run ...`.
5. Preserve `result.json`, `stdout.log`, and `stderr.log` as query evidence.
6. Treat adapter `PASS` as successful execution only. A Human or a governed
   downstream checker owns debug conclusions, waivers, and closure.

## Boundaries

- Default managed builds enable VCD/FST only. FSDB is source-only, requires a
  proprietary Verdi SDK, and is never enabled implicitly.
- Never vendor WavePeek source or generated binaries into verif-harness.
- On Linux, use the lock-pinned private glibc only when the host glibc is older
  than 2.34. Invoke it as a WavePeek-only loader; never replace system libc or
  export its library path globally. Keep the WavePeek-required `libgcc_s.so.1`
  as a hashed local copy inside that private runtime with its separate GCC
  Runtime Library Exception identity; never add a host library directory to a
  global search path.
- Never bypass the commit, Cargo.lock, license hash, clean-tree, or version
  checks.
- Never put waveform contents, secrets, or environment values into requests.
- Do not invoke a shell, infer signal names, broaden time ranges, or silently
  retry with different query semantics.
- Use `wavepeek --version` for identity; the pinned v2.2.3 CLI does not expose
  a `version` subcommand.
