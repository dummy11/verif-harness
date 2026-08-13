# Compile flow

Use an explicit filelist and preserve this dependency order:

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

The `simple_fifo` example implements the relevant non-UVM subset. Paths are
repository-root-relative so CI and local execution resolve the same sources.

Simulator wrappers may translate flags but must not silently reorder sources,
drop assertions, or change macro selection. Treat warnings and unsupported
options as visible evidence, not harmless noise.
