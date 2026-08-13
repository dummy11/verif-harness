# Simulator support

## Tested in public CI

Verilator 5.x compiles and runs the non-UVM `simple_fifo` example with timing
and assertions enabled. Python checks validate generators, structure,
filelists, and open-source readiness.

## Commercial integration

Synopsys VCS is the initial full SystemVerilog/UVM integration target. It
requires a user-provided installation and license. This repository contains no
license server, scheduler queue, private wrapper, or vendor installation path.
The neutral `scripts/run_vcs.sh` wrapper accepts only an in-repository filelist
and top-module name.

## Community validation

Questa and Xcelium support is planned and requires reproducible contributor
evidence. Verilator supports the non-UVM subset only. Do not interpret a green
public CI run as a full UVM regression result.
