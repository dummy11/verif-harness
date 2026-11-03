# Public release checklist

Automation prepares evidence; the release owner authorizes publication.

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

v3 releases are built from a reviewed commit on the selected release branch.
The branch name `v3` is not a package version. Each package version has one
immutable `vMAJOR.MINOR.PATCH` tag, one release manifest, and one fixed NSIM
version. Do not tag an unverified commit merely to trigger CI.

1. Independently test and publish the required NSIM version first. Record its
   full commit, wheel filename/URL/SHA-256, and installer URL/SHA-256 in
   `release.json`. A moving NSIM branch or an unpinned latest release is not a
   release dependency. Confirm the actual published bytes can be downloaded.
2. Set the same new verif-harness version in `pyproject.toml` and `release.json`;
   review project database compatibility and the three dependency-lock hashes.
   Add `docs/releases/VERSION.md` with installation/migration instructions and
   evidence limits. Existing published versions and attachments remain unchanged.
3. Run `make release-check` and `make docs`, build a candidate with
   `python3 scripts/package_release.py --output EMPTY_DIRECTORY`, and run the
   standalone installation checks shown below. The build interpreter needs
   Python 3.11+, `build`, `setuptools>=77`, and `wheel`.
4. Commit the reviewed changes, confirm CI for that exact commit, and obtain
   publication authorization. Create the matching tag on the clean commit;
   `package_release.py --release` requires both the clean checkout and the tag
   to identify HEAD.
5. Use the manual `Release` workflow with that tag. It checks out the tag,
   repeats source/example/docs checks, builds and verifies the distributions,
   tests real installation with the published NSIM assets, then creates the
   GitHub Release. Pushing a tag alone does not start this v3 workflow.

For candidate installation tests, replace the wheel filenames with the versions
under review; these commands use temporary installation and project directories:

```bash
python3 scripts/fetch_release_nsim.py --output /tmp/nsim-release
python3 -m pip download --dest /tmp/nsim-wheels /tmp/nsim-release/*.whl
python3 scripts/test_distribution_install.py --wheel dist/*.whl \
  --nsim-wheel /tmp/nsim-release/*.whl --nsim-installer /tmp/nsim-release/nsim-install.py \
  --wheelhouse /tmp/nsim-wheels
python3 verif-harness-install.py install --wheel dist/*.whl \
  --root /tmp/installed-verif --nsim-root /tmp/installed-nsim --python "$(command -v python3)" \
  --nsim-wheel /tmp/nsim-release/*.whl --nsim-installer /tmp/nsim-release/nsim-install.py \
  --wheelhouse /tmp/nsim-wheels
python3 scripts/test_installed_profiles.py --launcher /tmp/installed-verif/bin/verif-harness
```

Use a fresh output directory for each candidate; `dist` above is the candidate
output directory. The workflow also runs these installation checks. The profiles
check prepares Codex/Kimi configuration, exercises restart without launching an
Agent, checks authorized Dashboard access and legacy Skill-link migration, and
simulates a shared dependency checkout with a different owner. Temporary roots
and Git's ownership-test setting do not prove a real multi-user/NFS deployment.

For an authorized manual publication using equivalent completed checks, build
with `python3 scripts/package_release.py --release --output EMPTY_DIRECTORY`
and upload exactly its outputs. Both publication paths require the same tested
source and fixed dependencies; neither permits replacing existing assets.

## Published-asset verification

- Verify the public tag resolves to the tested commit.
- Confirm the Release contains a wheel, sdist, `verif-harness-install.py`,
  `release.json`, and `SHA256SUMS`.
- Download the assets again and verify their checksums and the fixed NSIM
  relationship. Install from the public download URL into a fresh temporary
  root; inspect `verif-harness version` outside the source checkout.
- Keep source CI, distribution checks, installation checks, and any actual
  EDA/farm acceptance evidence distinct. A successful installer or bootstrap
  does not establish simulator support or DUT verification acceptance.
- Documentation-only updates after publication can be committed to the release
  branch. Do not move the published tag or rebuild its attachments to include
  those updates; a changed installation package requires a new version.
