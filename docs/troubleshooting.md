# Troubleshooting

## Managed WavePeek is missing or blocked

From the verif-harness package checkout, run `./scripts/setup.sh --no-agent` or `make setup-wavepeek
check-wavepeek`. The installer refuses partial, dirty, wrong-origin,
wrong-commit, wrong-license, wrong-Cargo.lock, or wrong-version state. It never
updates an existing checkout. Preserve any user files, move the exact failed
`.deps/wavepeek*` paths aside manually, then reinstall. Network access to the
locked GitHub source tag and official release archive is required initially.

## WavePeek cannot open FSDB

The managed public build deliberately supports VCD/FST only. FSDB needs the
upstream `fsdb` feature and a separately licensed Verdi SDK. Configure that as
an explicit local extension; do not add vendor files, licenses, or FSDB data to
this repository.

## Managed xverif is missing or blocked

From the verif-harness package checkout, run `./scripts/setup.sh --no-agent` or
`make setup-xverif check-xverif`. The installer refuses to overwrite an existing
`.deps/xverif`; it also fails closed when origin, commit, clean state, MIT
License hash, or wrapper inventory differs from `deps/xverif.lock.json`.

Do not repair drift with an implicit `git pull`, reset, or clean. Preserve any
local content, review the dependency change, and create a fresh checkout from
the updated lock. Explicit `--xverif-root` and `XVERIF_HOME` remain controlled
overrides, not automatic fallbacks after a managed-checkout failure.

## Verilator is missing

From the verif-harness package checkout, run `./scripts/setup.sh --no-agent` for the diagnostic and install Verilator 5.x using the
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
