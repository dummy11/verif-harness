# add-env-layer — env + test + tb_top generator

**Mode**: `/verif-harness add-env-layer`

**Purpose**: Generate the env layer (`env_cfg / vseqr / env / scoreboard /
cov_collector / env_pkg`), test layer (`base_test / test_pkg`), and the
extra-thin `tb_top` module — everything that wires interfaces + harness +
UVC agents into a runnable UVM environment.

**Scope**: 10 files. Runs after `add-uvc-skeleton` (needs UVC pkg imports)
and either before or after `add-harness-layer` (needs harness_api_pkg
type reference — usually `add-harness-layer` first).

## Pre-conditions

1. `.harness-config.json` exists
2. All Stage 0 docs `Approved`
3. `<verif_root>/testbench/env/` and `<verif_root>/testbench/test/`
   directories exist (from `init` Step 4b)
4. `<verif_root>/testbench/pkg/<prefix>_tb_pkg.sv` exists
   (from `add-shared-pkg`)
5. UVC packages exist under `<verif_root>/testbench/uvc/*/` (from
   `add-uvc-skeleton`)
6. `<verif_root>/testbench/top/harness/tb_harness/<prefix>_harness_api_pkg.sv`
   exists (from `add-harness-layer` — env_cfg references its aggregate class
   type). If missing, prompt user to run `add-harness-layer` first, OR emit
   a placeholder `harness_api_pkg` that env_cfg's field can point to (only
   valid when the user plans to run `add-harness-layer` next).

## Required reading

- `references/stage1-patterns.md` § 6 (Env Layer), § 7 (analysis_imp_decl
  convention), § 8 (tb_top thinness)
- `<verif_root>/docs/verification/tb_architecture.md` § Env Config Object,
  § TB Top

## Execution plan

### Step 1 — Precondition audit

6 checks. Stop with report on failure.

### Step 2 — Read harness-spec.yaml

For each interface, extract:

- Interface name + `agent_short` (strip `_if`)
- Whether it's parameterized (`instances:` present)
- For parameterized: the concrete `WIDTH` values and `inst_name`s (used to
  declare separate vif handles in env_cfg)

### Step 3 — Emit env layer (6 files)

Target directory: `<verif_root>/testbench/env/`.

| Target file | Template |
|---|---|
| `<prefix>_env_cfg.svh` | `PREFIX_env_cfg.svh.tmpl` |
| `<prefix>_virtual_sequencer.svh` | `PREFIX_virtual_sequencer.svh.tmpl` |
| `<prefix>_env.svh` | `PREFIX_env.svh.tmpl` |
| `<prefix>_scoreboard.svh` | `PREFIX_scoreboard.svh.tmpl` |
| `<prefix>_cov_collector.svh` | `PREFIX_cov_collector.svh.tmpl` |
| `<prefix>_env_pkg.sv` | `PREFIX_env_pkg.sv.tmpl` |

Key variable blocks per file:

#### 3.1 env_cfg fields

- `GENERATED_VIF_HANDLES` — one `virtual <prefix>_<name> [#(...)] <name>_vif;`
  line per interface / per concrete instance for parameterized cases.
- `GENERATED_KNOBS` — env-wide knobs from harness-spec's optional
  `env_knobs:` block. Common defaults: `clk_period_ns`, `rst_release_delay_ns`,
  `bp_mode`, `in_stall_prob`, `refmodel_check`, `timeout_cycles`. Also add
  one `enable_<agent_short>_agent = 1'b1;` line per UVC.

#### 3.2 virtual_sequencer fields

- `GENERATED_SUB_SEQR_HANDLES` — one `<prefix>_<name>_sequencer <name>_seqr;`
  line per non-parameterized UVC. For parameterized (sram-like), declare one
  or two handles per concrete instance based on how the vseq needs to reach
  them; simplest for M1.1 skeleton — one handle per sub-agent.

#### 3.3 env child instantiation

- `GENERATED_AGENT_DECLARATIONS` — one `<prefix>_<name>_agent <name>_agent_h;`
  per UVC.
- `GENERATED_AGENT_BUILD` — `if (cfg.enable_<name>_agent) <name>_agent_h = ...::type_id::create(...);`

#### 3.4 scoreboard / cov_collector analysis_imp_decl

Follow stage1-patterns § 7:

- Scoreboard suffixes: `_config, _input, _output, _exception` + one per
  parameterized instance (e.g. `_sram_ws, _sram_scale`)
- Cov_collector suffixes: `_cov_config, _cov_input, _cov_output,
  _cov_exception, _cov_sram_ws, _cov_sram_scale`

Emit `` `uvm_analysis_imp_decl(_<suffix>) `` outside the class + typed
`uvm_analysis_imp_<suffix> #(...) ap_<name>;` field inside.

### Step 4 — Emit test layer (2 files)

Target: `<verif_root>/testbench/test/`.

| Target file | Template |
|---|---|
| `<prefix>_base_test.svh` | `PREFIX_base_test.svh.tmpl` |
| `<prefix>_test_pkg.sv` | `PREFIX_test_pkg.sv.tmpl` |

`base_test` retrieves env_cfg, propagates to env, creates env. No run_phase
body at M1.1 skeleton.

### Step 5 — Emit tb_top (1 file)

Target: `<verif_root>/testbench/top/<prefix>_tb_top.sv`.

Use `PREFIX_tb_top.sv.tmpl`. Key variable blocks:

- `GENERATED_INTERFACE_INSTANCES` — one `<prefix>_<name> [#(...)] <name>_inst(...);`
  per interface / per concrete instance
- `GENERATED_CFG_ASSIGNMENTS` — `cfg.<name>_vif = <name>_inst;` per handle
- `GENERATED_DUT_HARNESS_PORT_CONNECTIONS` — port-by-port connection to
  `<prefix>_dut_harness` instance

Follow LD9 thinness — target 100-200 lines total.

### Step 6 — Update filelist

If `<verif_root>/filelist/tb.f` exists, append env / test entries in the
proper sections per stage1-patterns § 1.5:

- `+incdir+<verif_root>/testbench/env`
- `+incdir+<verif_root>/testbench/env/vseq`
- `+incdir+<verif_root>/testbench/test`
- Section "5) Env pkg": `<verif_root>/testbench/env/<prefix>_env_pkg.sv`
- Section "6) Test pkg": `<verif_root>/testbench/test/<prefix>_test_pkg.sv`
- Section "9) top": `<verif_root>/testbench/top/<prefix>_tb_top.sv`

If tb.f doesn't exist yet, defer to `finalize-filelist-and-make`.

### Step 7 — Report

List all 10 files emitted, and print:

```text
Next step: /verif-harness finalize-filelist-and-make
Then: make -C <verif_root>/regress compile
```

## Post-conditions

- 10 files under env / test / top
- env / test packages compile independently
- tb_top compiles + elabs when all filelist entries are present

## Do not

- Do not put logic in scoreboard/cov_collector write bodies (M1.5+ / Stage 3)
- Do not connect analysis ports in env's connect_phase (M1.5+)
- Do not add UVM_TESTNAME default — leave that to user's runtime command
- Do not add anything to tb_top beyond the 4 responsibilities (see
  stage1-patterns § 8) — no config_db.set of per-agent cfgs, no test-specific
  logic
