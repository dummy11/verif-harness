# Architecture

## Design goal

verif-harness makes DUT integration a first-class structural layer. The layer
is intentionally smaller than a verification environment and contains no test
intent, reference-model policy, or Human decisions.

## Ownership

`tb_top` owns only top-level elaboration and test startup. The harness owns:

- clock and reset generation;
- protocol-interface instances;
- DUT instantiation and port mapping;
- explicit tie-offs, straps, and adapters;
- assertion modules and bind placement;
- virtual-interface publication for UVM consumers.

The UVM environment owns stimulus, monitoring, scoreboarding, coverage, and
test control. DUT RTL remains an external read-only asset.

## Dependency direction

```text
tests -> env -> agents -> virtual interfaces
                           |
                           v
                       harness -> DUT
                           |
                           +-> SVA / bind
```

No DUT-specific hierarchical path may leak into a test or reusable UVC when a
harness API or interface can express the dependency.

## Compile-order contract

Use this order unless a reviewed tool-specific exception is documented:

```text
defines
-> packages
-> interfaces
-> RTL
-> assertions
-> bind
-> UVM packages/classes
-> harness
-> tb_top
```

Filelists are explicit, project-root-relative, and reviewed as source code.

## Extension points

- Interfaces define stable protocol boundaries.
- Harness adapters isolate DUT-specific reshaping and tie-offs.
- Bind modules attach non-invasive assertions.
- The Codex skill generates structure from reviewed contracts.
- Simulator wrappers translate the canonical filelist into tool commands.
- The xverif CLI adapter translates one reviewed request into a native xverif
  tool invocation and immutable evidence; it does not own verification policy.

## Deterministic tool delegation

```text
Codex Agent
   |
   v
verif-harness Skill/framework
   |  stage policy, project semantics, Human boundaries
   v
validated CLI adapter
   |  allowlisted argv, controlled environment, timeout, evidence hashes
   v
BLANK2077/xverif tools/<selected-tool>
   |  xbit | xdebug | xcov | xentry | xloc | xsva | xwaveform
   v
native JSON / XOUT / text evidence
```

The adapter pins tool provenance with the checkout Git commit and wrapper
SHA-256. It never invents a unified `xverif` executable, changes native action
semantics, reverse-parses XOUT, or silently falls back between CLI/MCP,
local/LSF, output formats, backends, or data sources.

The default xverif implementation is a separately owned, commit-pinned source
checkout under `.deps/xverif`. `deps/xverif.lock.json` is the dependency
contract; setup validates repository, commit, clean state, MIT License hash,
and wrapper inventory before the adapter can consume it. The checkout is
Git-ignored and excluded from verif-harness source archives.

See [docs/harness_design.md](docs/harness_design.md) for implementation rules.
