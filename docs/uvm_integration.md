# UVM integration

The open-source FIFO smoke test is intentionally non-UVM. A full UVM project
uses the same harness boundary with a UVM-capable simulator.

## Virtual interfaces

Publish virtual-interface handles from the harness or top before `run_test`.
Consume them through agent configuration objects. Drivers and monitors must not
reach into DUT hierarchy.

## Layering

```text
test -> env -> agent -> driver/monitor -> virtual interface -> harness -> DUT
```

Keep sequencer, driver, monitor, agent, environment, scoreboard, coverage, and
reference-model responsibilities separate. The bundled Codex skill can create
these skeletons, but project semantics still require Human review.

## Commercial boundary

UVM regressions are not claimed by GitHub CI. Record the simulator, UVM
version, compile options, seed, and manifest with local regression evidence.
