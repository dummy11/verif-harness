# Tool versions

| Tool | Supported baseline | Purpose |
| --- | --- | --- |
| Python | 3.9+ | Generators, audits, tests |
| GNU Make | 3.81+ | Local command entry points |
| Verilator | 5.x | Open example compile and run |
| UVM | IEEE 1800.2-compatible | Commercial simulator integration |
| VCS | User-validated | Full UVM integration target |
| xverif | Approved Git commit | Deterministic bit/debug/coverage/SVA tool delegation |
| xverif MCP | Same approved xverif Git commit; `mcp[cli]` is runtime-managed | Codex/Kimi MCP server for xdebug/xcov and stateless xverif tools |
| WavePeek | 2.2.3 / approved Git commit | Deterministic VCD/FST waveform queries |

On Ubuntu, install the packaged Verilator with:

```bash
sudo apt-get update
sudo apt-get install verilator
```

Package versions vary by distribution. CI records `verilator --version` in
every run. Contributors should include exact tool versions with bug reports.
`./scripts/setup.sh --install-verilator` supports Homebrew and apt-based hosts.

xverif integration uses an approved checkout of
`https://github.com/BLANK2077/xverif.git`. The exact reviewed commit is stored
in `deps/xverif.lock.json`; `./scripts/setup.sh --with-xverif` installs it into
`.deps/xverif`, including the locked `xverif_mcp` package and
`tools/xverif-mcp` launcher. The CLI adapter records the selected wrapper
SHA-256 and checkout commit for every run. The MCP Python dependency
`mcp[cli]` is installed in the Agent runtime environment and is not vendored by
verif-harness. Updating the lock is a separately reviewed dependency change,
never an implicit branch update.

WavePeek uses reviewed source from `https://github.com/kleverhq/wavepeek.git`.
Its lock records the exact commit, version, License and Cargo.lock hashes.
`./scripts/setup.sh --with-wavepeek` verifies an official platform-specific
VCD/FST release archive against a pinned SHA-256; public CI does not enable
proprietary FSDB support and no local Rust build is required.
