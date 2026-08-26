# Third-party notices

## Managed CPython runtime

verif-harness downloads a platform-specific CPython archive produced by
[astral-sh/python-build-standalone](https://github.com/astral-sh/python-build-standalone)
into Git-ignored `.deps/runtime`. The exact distribution release, archive name,
and SHA-256 are recorded in `deps/runtime.lock.json`; no runtime binary is
included in verif-harness source archives or releases.

python-build-standalone is separately licensed under MPL-2.0. CPython is
separately licensed under the Python Software Foundation License, and bundled
third-party components retain their respective notices and licenses. The
hash-locked MCP Python packages are downloaded from their package indexes and
retain their own ownership and licenses. Review those installed distributions
before redistributing a populated `.deps/runtime`; verif-harness distributes
only dependency identities and hashes.

## GitHub Spec Kit

verif-harness can optionally install a release- and commit-pinned checkout of
[GitHub Spec Kit](https://github.com/github/spec-kit). Source and its Python
environment are stored under Git-ignored `.deps/` paths and are not copied into
verif-harness source archives or releases.

Spec Kit is separately owned and licensed under the MIT License. The reviewed
release tag, full commit, license hash, and `pyproject.toml` hash are recorded
in `deps/spec-kit.lock.json`. Spec Kit is an agentic specification framework;
its command or workflow success is not deterministic RTL verification evidence
or Human approval. Its Python transitive dependencies retain their own
licenses and must be reviewed for the intended distribution environment.

## WavePeek

verif-harness can optionally download and build a commit-pinned source checkout
of [kleverhq/wavepeek](https://github.com/kleverhq/wavepeek). Source is stored
under `.deps/wavepeek`; the executable is stored under
`.deps/wavepeek-bin/wavepeek`. Neither is copied into verif-harness source
archives or releases.

WavePeek is separately owned and licensed under Apache License 2.0. The exact
reviewed license file is pinned by SHA-256 in `deps/wavepeek.lock.json` and is
available in the managed checkout. Copyright 2026 esynr3z. The upstream
license is at <https://github.com/kleverhq/wavepeek/blob/main/LICENSE>.

The managed default build enables no optional Cargo features and supports
VCD/FST. FSDB support requires the separately licensed Synopsys Verdi FSDB
Reader SDK; verif-harness does not download, redistribute, configure, or grant
rights to that SDK. Never publish waveform data, Verdi files, vendor libraries,
license configuration, or locally built WavePeek artifacts with this project.

On Linux hosts whose system glibc is older than 2.34, setup can build the
hash-pinned GNU C Library 2.34 source into Git-ignored `.deps/glibc-2.34` for
WavePeek only. glibc remains separately owned and licensed under
LGPL-2.1-or-later with the additional notices documented upstream; its reviewed
`COPYING.LIB`/`LICENSES` hashes and official GNU source archive hash are recorded
in `deps/wavepeek.lock.json`. The private runtime is
not copied into verif-harness source archives or releases, never replaces the
system libc, and is not exposed through a global `LD_LIBRARY_PATH`.

The official WavePeek executable also requires the GCC low-level runtime
`libgcc_s.so.1`. On the private-glibc compatibility path, setup copies that
library from the already validated host GCC into the same Git-ignored private
runtime, records its source and installed SHA-256, and invokes it only through
the WavePeek private loader. libgcc remains separately owned and licensed under
GPL-3.0-or-later with the GCC Runtime Library Exception 3.1. The local copy is
not included in verif-harness source archives or releases; review the host GCC
package notices before redistributing a populated `.deps/` directory.

## xverif

verif-harness can optionally download a commit-pinned source checkout of
[BLANK2077/xverif](https://github.com/BLANK2077/xverif). The checkout is stored
under the Git-ignored `.deps/` directory and is not copied into verif-harness
source archives or releases.

xverif source and documentation are provided under the MIT License. Its
license applies only to material the xverif project is entitled to license; it
does not license Synopsys software, NPI/FSDB interfaces, vendor headers,
libraries, manuals, databases, or other proprietary dependencies.

The optional `xverif_mcp` package is part of the same pinned xverif checkout and
is not vendored into this repository. Its Python runtime dependency
`mcp[cli]` and transitive packages are version- and artifact-hash-locked by the
managed runtime, but remain separately owned and licensed; verif-harness does
not vendor, redistribute, or claim ownership of those packages.

```text
MIT License

Copyright (c) 2026 BLANK2077

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Do not place locally built xverif binaries, proprietary EDA payloads, vendor
headers/libraries, license configuration, or generated databases in a public
verif-harness artifact. Consult the upstream `THIRD_PARTY.md` and the user's
applicable vendor agreements before enabling EDA-dependent xdebug or xcov
backends.
