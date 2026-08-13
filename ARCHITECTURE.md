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

See [docs/harness_design.md](docs/harness_design.md) for implementation rules.
