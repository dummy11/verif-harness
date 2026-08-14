# verif-harness

**verif-harness is a reusable SystemVerilog/UVM DUT integration harness for
ASIC block-level verification, with an optional Codex-assisted workflow.**

It keeps structural integration in one place: clocks and resets, protocol
interfaces, DUT instantiation, tie-offs, adapters, assertions, bind targets,
and virtual-interface publication. Tests and UVM environments stay above that
boundary; DUT RTL stays read-only.

## Why?

Verification projects often scatter DUT wiring across `tb_top`, tests,
packages, and simulator scripts. That makes compile order fragile and creates
hidden dependencies. verif-harness defines a narrow, reviewable integration
layer and provides templates, checks, an executable FIFO example, and a Codex
skill that applies the same rules consistently.

## Architecture

```text
                     +-------------------+
                     |      UVM Test     |
                     +---------+---------+
                               |
                     +---------v---------+
                     |      UVM Env      |
                     +---------+---------+
                               |
                    config_db / virtual IF
                               |
+------------------------------------------------+
|                verif-harness                   |
|                                                |
|  clock/reset       protocol interfaces         |
|  DUT instance      tie-offs and adapters       |
|  SVA / bind        config_db publishing        |
+-----------------------+------------------------+
                        |
                 +------v------+
                 |     DUT     |
                 +-------------+
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for ownership and compile-order rules.

## Features

- Thin `tb_top` and explicit harness ownership.
- Reusable DUT-integration templates and an additive generator.
- Interface, SVA, bind, filelist, and smoke-test patterns.
- A license-free `simple_fifo` example for Verilator.
- Simulator-independent Python structure and public-release checks.
- A bundled 29-mode Codex skill for Stage 0 through verification freeze.
- A fail-closed CLI adapter for deterministic tools from
  `git@github.com:BLANK2077/xverif.git`.
- GitHub CI, documentation deployment, and tagged-release automation.

## Requirements

- Python 3.9 or newer.
- GNU Make.
- Verilator 5.x for the open-source example.
- A UVM-capable commercial simulator for full UVM regressions.

Commercial simulator licenses, scheduler configuration, and private wrappers
are intentionally not included.

## Quick start

```bash
git clone https://github.com/dummy11/verif-harness.git
cd verif-harness
./scripts/setup.sh
./scripts/run_example.sh
```

Expected result with Verilator installed:

```text
SIMPLE_FIFO_SMOKE PASS
```

## Generate a DUT integration skeleton

```bash
python3 scripts/verif_harness.py init my_dut --output ./work
```

The command creates additive, non-overwriting files under `interfaces/`,
`sva/`, `bind/`, `tb/`, and `filelists/`. It does not parse or modify DUT RTL.
Review and replace every TODO against the approved DUT specification.

## Delegate to xverif

`verif-harness` remains the planning and governance framework. Its CLI adapter
can execute one reviewed operation from an approved xverif checkout while
capturing argv, Git identity, wrapper and artifact hashes, and native output:

```bash
python3 scripts/verif_harness.py xverif probe \
  --xverif-root /path/to/xverif --tool xbit
```

xverif is a tool suite (`xbit`, `xdebug`, `xcov`, `xentry`, `xloc`, `xsva`, and
`xwaveform`), not a single `xverif` executable. See
[docs/xverif_integration.md](docs/xverif_integration.md).

## Adding a new DUT

1. Generate or create `tb/harness/<dut>_tb_harness.sv`.
2. Instantiate protocol interfaces in the harness.
3. Instantiate the DUT and preserve its original port order.
4. Connect clock/reset and document tie-offs.
5. Add checker and bind targets.
6. Publish virtual interfaces through `uvm_config_db` when UVM is enabled.
7. Add an explicit compile-order filelist.
8. Keep `<dut>_tb_top.sv` thin.
9. Add and run a deterministic smoke test.

See [docs/dut_integration.md](docs/dut_integration.md) for the complete review
checklist.

## Simulator support

| Simulator | Scope | Status |
| --- | --- | --- |
| Verilator 5.x | Non-UVM example, lint, assertions | Open CI target |
| Synopsys VCS | Full SystemVerilog/UVM flow | Local/commercial integration |
| Questa | Full SystemVerilog/UVM flow | Community validation wanted |
| Xcelium | Full SystemVerilog/UVM flow | Community validation wanted |

CI success proves the open-source checks and example only. It does not claim a
commercial-simulator regression passed. See
[docs/simulator_support.md](docs/simulator_support.md).

## Repository structure

```text
docs/                    Design and integration documentation
examples/simple_fifo/    License-free executable example
filelists/               Shared simulator option guidance
scripts/                 Generator, checks, and runner wrappers
skills/verif-harness/    Reusable Codex skill
templates/dut/           Standalone DUT integration templates
tests/                   Python and structural tests
.github/                 CI, Pages, release, issue, and PR automation
```

## Codex skill

The reusable skill is under `skills/verif-harness/`. Install it into a Codex
skill directory, then ask:

```text
$verif-harness Integrate this DUT into a verification environment.
```

The skill reads repository instructions and RTL ports, but preserves the rule
that DUT RTL and Human approval decisions are outside agent authority.
The bundled Chinese [skill README](skills/verif-harness/README.md) provides the
quick-start catalog, while its
[complete user guide](skills/verif-harness/docs/user_guide.md) documents every
mode's inputs, outputs, usage, scenarios, and Human review points.
See [docs/skill_modes.md](docs/skill_modes.md) for every mode, its purpose,
usage, and recommended lifecycle position.

## Documentation

Start at [docs/index.md](docs/index.md). The MkDocs configuration can build the
same content as a documentation site.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). Contributions must use neutral example
names and pass the public-release audit; never submit proprietary RTL, logs,
URLs, license configuration, or specifications.

## License

Licensed under Apache License 2.0. See [LICENSE](LICENSE).
