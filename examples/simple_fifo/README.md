# simple_fifo example

This example demonstrates the core harness boundary without UVM or commercial
licenses. It includes a small FIFO DUT, protocol interface, thin `tb_top`,
harness-owned DUT integration, an assertion bound to the DUT, and an explicit
compile-order filelist.

From the repository root:

```bash
./scripts/run_example.sh
```

The runner uses Verilator and expects `SIMPLE_FIFO_SMOKE PASS`. Full UVM flows
remain commercial-simulator integrations and are not exercised by this example.
