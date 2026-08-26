# Troubleshooting

## Managed runtime is missing or blocked

Start with `./scripts/runtime-versions --verbose` for the consolidated required,
current, status, and resolved-path inventory. Use `--json` when attaching the
result to CI evidence or a bug report.

Run `./scripts/setup_managed.sh --check`. Normal setup downloads only the
platform asset pinned by `deps/runtime.lock.json`, verifies its SHA-256, creates
`.deps/runtime/venv`, and installs only packages accepted by the hash-locked
requirements file. It does not use `python3`, pip aliases, conda, pyenv, or a
shell-selected Python.

If `.deps/runtime` is partial or its descriptor has drifted, setup fails closed
and preserves it. Inspect or move that exact ignored directory aside manually;
do not make setup delete an unknown runtime automatically. A host still needs
standard POSIX file utilities, Bash, Git, tar, HTTPS/CA access, `curl` or
`wget`, and `sha256sum` or `shasum`.
On noexec filesystems, place the verif-harness checkout on executable storage.

## Managed WavePeek is missing or blocked

From the verif-harness package checkout, run `./scripts/setup --no-agent` or `make setup-wavepeek
check-wavepeek`. The installer refuses partial, dirty, wrong-origin,
wrong-commit, wrong-license, wrong-Cargo.lock, or wrong-version state. It never
updates an existing checkout. Preserve any user files, move the exact failed
`.deps/wavepeek*` paths aside manually, then reinstall. Network access to the
locked GitHub source tag and official release archive is required initially.
WavePeek and private-glibc archives use the same host `curl`/`wget` trust path
as the managed bootstrap, while retaining HTTPS-only transport and locked
SHA-256 validation. On an enterprise TLS network, configure the approved CA in
the host trust store or the downloader's standard CA-bundle setting. Never use
`curl -k`, `--no-check-certificate`, or a disabled Python SSL context.

On Linux, setup reports the detected host glibc version. If it is older than
2.34, setup also downloads the hash-pinned GNU glibc 2.34 source and builds it
under `.deps/glibc-2.34`. The conditional build chain requires GCC 6.2+,
GNU Make 4.0+, binutils assembler/linker 2.25+, GNU awk 3.1.2+, Bison 2.7+,
GNU sed 3.02+, and Python 3.4+; the managed Python satisfies the last
requirement. `makeinfo` 4.7+ is documentation-only and remains an optional
diagnostic, so its absence does not block the WavePeek private runtime. A
missing or old required prerequisite, a drifted private runtime, or a failed
loader probe is `BLOCKED`; do not work around it with a global
`LD_LIBRARY_PATH`.

The official WavePeek binary also needs `libgcc_s.so.1`. Setup resolves it with
the validated GCC, copies it into the Git-ignored private runtime, and records
source/installed SHA-256 provenance plus the GCC Runtime Library Exception
identity. A private glibc created by the earlier installer is migrated by adding
only this missing managed file and provenance record; other partial or drifted
state remains blocked. Do not add host library directories to a global search
path.

## WavePeek cannot open FSDB

The managed public build deliberately supports VCD/FST only. FSDB needs the
upstream `fsdb` feature and a separately licensed Verdi SDK. Configure that as
an explicit local extension; do not add vendor files, licenses, or FSDB data to
this repository.

## Managed xverif is missing or blocked

From the verif-harness package checkout, run `./scripts/setup --no-agent` or
`make setup-xverif check-xverif`. The installer refuses to overwrite an existing
`.deps/xverif`; it also fails closed when origin, commit, clean state, MIT
License hash, or wrapper inventory differs from `deps/xverif.lock.json`.

Do not repair drift with an implicit `git pull`, reset, or clean. Preserve any
local content, review the dependency change, and create a fresh checkout from
the updated lock. Explicit `--xverif-root` and `XVERIF_HOME` remain controlled
overrides, not automatic fallbacks after a managed-checkout failure.

## Verilator is missing

From the verif-harness package checkout, run `./scripts/setup --no-agent` for the diagnostic and install Verilator 5.x using the
method appropriate for the host. CI installs the Ubuntu package explicitly.

## A type is unknown during compilation

Check the canonical compile order. Packages and interfaces must precede their
consumers; assertion modules must precede bind files.

## The generator refuses to run

The generator is additive. Move to a clean output directory or review and
remove the exact generated targets yourself. It will not overwrite Human work.

## Public-release audit fails

Review the reported file and line. Replace private values with neutral data or
remove the artifact. Do not add exclusions merely to suppress a real finding.
When history contains sensitive data, create a new clean export or use an
organization-approved history-rewrite process before publication.

## Public CI passes but UVM fails locally

Public CI validates only the non-UVM example and structural checks. Compare the
commercial simulator version, UVM library, compile order, macros, and filelist.
