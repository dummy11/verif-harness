# Public release checklist

Automation prepares evidence; a Human owner makes the publication decision.

## Required before first public push

- [ ] Confirm copyright ownership and permission for every imported file.
- [ ] Review the Apache-2.0 license choice.
- [ ] Review all source, templates, documentation, tests, and examples.
- [ ] Run `make release-check` on a host with Verilator 5.x.
- [ ] Run `./scripts/setup --isolation managed --no-agent` followed by
      `make check-managed runtime-versions`; verify the version inventory,
      CPython, MCP package-lock, and runtime descriptor identities before
      checking integrations.
- [ ] Run `make setup-xverif check-xverif` and verify the locked commit,
      license hash, wrappers, `xverif_mcp` package/launcher, and real xbit
      smoke. If MCP is enabled for the release, retain a runtime `xverif_ping`
      probe with server/tool identity evidence.
- [ ] Confirm `.deps/` and all xverif/vendor build artifacts are absent from
      the release archive; review `THIRD_PARTY_NOTICES.md`.
- [ ] Run `make setup-wavepeek check-wavepeek`; verify the locked source,
      Apache-2.0/Cargo.lock hashes, VCD/FST-only build, and real schema smoke.
- [ ] Confirm WavePeek source, binary, Cargo target data, waveforms, and any
      FSDB/Verdi material are absent from the release archive.
- [ ] Confirm the example prints `SIMPLE_FIFO_SMOKE PASS`.
- [ ] Run `./scripts/managed-python scripts/check_public_release.py` after the
      final commit.
- [ ] Review `git log --all`, all tags, author metadata, and remote URLs.
- [ ] Enable GitHub secret scanning and private vulnerability reporting.
- [ ] Require CI checks on the default branch.
- [ ] Enable GitHub Pages with Actions as its source.
- [ ] Approve repository visibility as Public.

## Release

After CI passes and the Human owner approves publication, push `main`, create
or push the `v0.1.0` tag, and verify that the release workflow publishes the
archive and checksum. Do not tag an unverified commit merely to trigger CI.
