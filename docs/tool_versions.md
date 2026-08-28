# Tool versions

| Tool | Supported baseline | Purpose |
| --- | --- | --- |
| Managed CPython | 3.12.11 / python-build-standalone 20251007 | Default setup, v1 control plane, xverif MCP, generators, audits, tests |
| MCP Python package set | `mcp[cli]` 1.29.1 plus hash-locked transitive dependencies | xverif MCP runtime; last reviewed 1.x API with `mcp.server.fastmcp` |
| GNU Make | 3.81+ for contributor targets; 4.0+ for a conditional private glibc build | Command entry points and old-host WavePeek compatibility build |
| Verilator | 5.x | Open example compile and run |
| UVM | IEEE 1800.2-compatible | Commercial simulator integration |
| VCS | User-validated | Full UVM integration target |
| xverif | Approved Git commit | Deterministic bit/debug/coverage/SVA tool delegation |
| xverif MCP | Same approved xverif Git commit; `mcp[cli]` is runtime-managed | Codex/Kimi MCP server for xdebug/xcov and stateless xverif tools |
| WavePeek | 2.2.3 / approved Git commit | Deterministic VCD/FST waveform queries |
| Private glibc | 2.34 / pinned GNU source archive | WavePeek-only compatibility runtime when host glibc is older than 2.34 |
| Private `libgcc_s` | Copied and SHA-256-recorded from validated GCC | WavePeek-only GCC runtime dependency inside the private-glibc boundary |

## Managed runtime

`./scripts/setup --isolation managed` bootstraps CPython below
`.deps/runtime` without invoking a host Python or pip. `deps/runtime.lock.json`
pins the four reviewed macOS/Linux x86-64/AArch64 archives and SHA-256 values.
`deps/runtime-requirements.lock` pins all MCP Python packages with artifact
hashes. Existing partial or drifted runtime state is preserved and reported as
blocked rather than overwritten.

Setup runs the consolidated version check before launching the selected Agent.
Run the same inventory independently with:

```bash
./scripts/runtime-versions
./scripts/runtime-versions --verbose
./scripts/runtime-versions --json
```

The report distinguishes required, conditional, optional, and informational
entries. It verifies the exact managed CPython and applicable Python package
pins, integration locks, host bootstrap commands, conditional private-glibc
build chain, optional EDA/scheduler tools, and Agent CLI selection. JSON output
uses a non-zero exit status when a required entry is blocked.

The remaining bootstrap host contract is standard POSIX file utilities, Bash,
Git, tar, an HTTPS downloader (`curl` or `wget`), a SHA-256 implementation
(`sha256sum` or `shasum`), the supported kernel/CPU architecture, and
writable/executable `.deps` storage.
GCC 6.2+, GNU Make 4.0+, binutils assembler/linker 2.25+, GNU awk 3.1.2+,
Bison 2.7+, GNU sed 3.02+, and Python 3.4+ are conditional requirements only
when a Linux host older than glibc 2.34 must build the private WavePeek
runtime. The Python requirement is satisfied by managed CPython. GNU texinfo
4.7+ is reported as optional because `makeinfo` is only needed to translate
and install glibc documentation, which the WavePeek private runtime does not
use. EDA tools, licenses, and scheduler integration remain host-provided
boundaries.

The reviewed package lock was generated with uv 0.12.5:

```bash
uv pip compile deps/runtime-requirements.in \
  --universal --python-version 3.12 --generate-hashes \
  --no-header --no-annotate \
  --output-file deps/runtime-requirements.lock
```

After regeneration, update and review the requirements SHA-256 in
`deps/runtime.lock.json`; never update the runtime implicitly during setup.

On Ubuntu, install the packaged Verilator with:

```bash
sudo apt-get update
sudo apt-get install verilator
```

Package versions vary by distribution. CI records `verilator --version` in
every run. Contributors should include exact tool versions with bug reports.
`./scripts/setup --install-verilator` supports Homebrew and apt-based hosts.

xverif integration uses an approved checkout of
`https://github.com/BLANK2077/xverif.git`. The exact reviewed commit is stored
in `deps/xverif.lock.json`; run `./scripts/setup --runtime codex|kimi
--workspace-root <verification-workspace>` from the verif-harness package checkout to install it into
`.deps/xverif`, including the locked `xverif_mcp` package and
`tools/xverif-mcp` launcher. The CLI adapter records the selected wrapper
SHA-256 and checkout commit for every run. The MCP Python dependency
`mcp[cli]` is installed by setup in the selected Python environment and is not
vendored by verif-harness. Updating the lock is a separately reviewed dependency
change, never an implicit branch update.

WavePeek uses reviewed source from `https://github.com/kleverhq/wavepeek.git`.
Its lock records the exact commit, version, License and Cargo.lock hashes.
the default `./scripts/setup --runtime codex|kimi --workspace-root <verification-workspace>`
from the verif-harness package checkout verifies an official platform-specific
VCD/FST release archive against a pinned SHA-256. On Linux it first checks the
host glibc version. Hosts older than 2.34 build the pinned GNU glibc 2.34 source
under `.deps/glibc-2.34` and launch only WavePeek through that private loader;
setup never exports a global `LD_LIBRARY_PATH` or changes the system libc.
Public CI does not enable proprietary FSDB support and no local Rust build is
required.
