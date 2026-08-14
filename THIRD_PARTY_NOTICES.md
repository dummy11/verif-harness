# Third-party notices

## xverif

verif-harness can optionally download a commit-pinned source checkout of
[BLANK2077/xverif](https://github.com/BLANK2077/xverif). The checkout is stored
under the Git-ignored `.deps/` directory and is not copied into verif-harness
source archives or releases.

xverif source and documentation are provided under the MIT License. Its
license applies only to material the xverif project is entitled to license; it
does not license Synopsys software, NPI/FSDB interfaces, vendor headers,
libraries, manuals, databases, or other proprietary dependencies.

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
