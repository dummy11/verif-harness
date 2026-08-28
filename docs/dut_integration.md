# DUT integration

## Inputs

Before integration, collect the approved DUT top, port list, reset semantics,
clock requirements, protocol specifications, required parameters, legal
tie-offs, and assertion targets. Record ambiguity rather than guessing.

## Establish the reviewed action

```bash
$verif-harness bootstrap --rtl-root rtl --docs-root docs
$verif-harness plan design --workstream VDOC --objective "Integrate the DUT read-only" \
  --desired "Harness maps every reviewed DUT port"
$verif-harness closure evaluate --workstream VDOC
```

After Human review, use the lower-level interface/harness modes selected by
VClosure. Those generators are additive and refuse to overwrite existing files.

## Complete the integration

1. Define protocol signals and modport directions.
2. Instantiate clocks, resets, and interfaces in the harness.
3. Instantiate the read-only DUT.
4. Map every port and document constants or unconnected outputs.
5. Add structural adapters only when widths or groupings require them.
6. Add reviewed assertions and a bind file.
7. Publish virtual interfaces for UVM agents.
8. Add all sources to the canonical filelist in dependency order.
9. Keep `tb_top` thin.
10. Add a deterministic smoke test and negative checks.

## Exit evidence

- No DUT RTL changes.
- No unresolved port or reset assumptions.
- Filelist and structure checks pass.
- Smoke test proves clock, reset, write, read, and assertion engagement.
- Simulator and tool versions are recorded.
