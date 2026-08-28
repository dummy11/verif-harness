# add-uvc-skeleton — UVC skeleton generator

**Mode**: `/verif-harness add-uvc-skeleton [<name>]`

**Purpose**: For each interface in harness-spec.yaml, generate a full UVC
skeleton (8-9 files per UVC): package + agent + agent_cfg + driver + monitor
+ sequencer + coverage stub + transaction item + one default sequence. For
interfaces with `instances:` (parameterized like sram), also generate a
top-agent + sub_agent + parameterized driver/monitor pattern.

**Scope**: UVC class skeletons only (empty run_phase / build_phase bodies).
Behavior comes in later manual milestones (M1.3+).

If `<name>` argument is provided, only generate that one UVC. Otherwise
generate all UVCs listed in harness-spec.yaml.

## Pre-conditions

1. The project is bootstrapped and VPlan has an approved UVC action
2. `.harness-config.json` exists
3. `<verif_root>/testbench/uvc/<name>_agent/` is absent/empty or contains only
   reviewed additive targets (derive the directory from the interface name)
4. `<verif_root>/testbench/pkg/<prefix>_tb_pkg.sv` exists (needed by UVC pkg
   imports — run `/verif-harness add-shared-pkg` first if missing)
5. Interface `.sv` files exist under `<verif_root>/testbench/top/if/` (needed
   for `virtual <interface>` handle refs in class body)

## Required reading

- `references/stage1-patterns.md` § 3 (Package-per-UVC Layout), § 1 (compile-
  order), § 4.2 (UVC-local coverage subscriber pattern)
- `<verif_root>/docs/verification/tb_architecture.md` § acc_ctrl_agent (or
  equivalent) — per-UVC component definitions

## Execution plan

### Step 1 — Precondition audit

Standard 5 pre-condition checks. Stop with report on failure.

### Step 2 — Read harness-spec.yaml

For each interface entry (or filtered to `<name>` if arg given), extract:

- `name` (spec name, includes `_if` suffix — strip to derive agent dir)
- `instances:` — presence indicates parameterized sub-agent pattern
- `parameters:` — needed for parameterized driver/monitor
- Custom transaction item name (defaults to `<agent_name>_item`; can be
  overridden via optional `item_name:` field per interface)

Also read (from harness-spec.yaml, optional):

- `<interface>.uvc:` block (optional) with:
  - `item_name: <transaction_class>` (default: `<agent_short>_item`)
  - `seq_list: [<seq_name>, ...]` (default: `[default_seq]`)

### Step 3 — Per-UVC file emission

For each UVC, compute:

- `<agent_short>` = interface name with `_if` suffix stripped (e.g. `ctrl_if`
  → `ctrl`, `data_in_if` → `data_in`, `sram_if` → `sram`)
- `<agent_dir>` = `<verif_root>/testbench/uvc/<agent_short>_agent/`
- `<pkg_name>` = `<prefix>_<agent_short>_agent_pkg`

Emit files in this order (respecting includes-need-defs-first inside pkg):

#### 3a. Common files (all UVCs)

| Target path | Template | Notes |
|---|---|---|
| `<agent_dir>/<prefix>_<agent_short>_agent_cfg.svh` | `PREFIX_NAME_agent_cfg.svh.tmpl` | vif handle + is_active + knobs |
| `<agent_dir>/<prefix>_<item_name>.svh` | `PREFIX_ITEM.svh.tmpl` | uvm_sequence_item stub |
| `<agent_dir>/<prefix>_<agent_short>_sequencer.svh` | `PREFIX_NAME_sequencer.svh.tmpl` | uvm_sequencer #(item) |
| `<agent_dir>/<prefix>_<agent_short>_monitor.svh` | `PREFIX_NAME_monitor.svh.tmpl` | uvm_analysis_port + empty run_phase |
| `<agent_dir>/<prefix>_<agent_short>_cov.svh` | `PREFIX_NAME_cov.svh.tmpl` | uvm_subscriber stub |
| `<agent_dir>/seq/<prefix>_<agent_short>_default_seq.svh` | `PREFIX_NAME_default_seq.svh.tmpl` | one seq per entry in seq_list |

#### 3b. Non-parameterized UVCs (ctrl_if, data_in_if, data_out_if)

| Target path | Template |
|---|---|
| `<agent_dir>/<prefix>_<agent_short>_driver.svh` | `PREFIX_NAME_driver.svh.tmpl` |
| `<agent_dir>/<prefix>_<agent_short>_agent.svh` | `PREFIX_NAME_agent.svh.tmpl` |

#### 3c. Parameterized UVCs (with `instances:`, e.g. sram_if)

Different structure — top agent holds N sub-agents, driver/monitor are
parameterized:

| Target path | Template | Notes |
|---|---|---|
| `<agent_dir>/<prefix>_<agent_short>_driver.svh` | `PREFIX_PARAM_driver.svh.tmpl` | `#(parameter int WIDTH = <default>)` |
| `<agent_dir>/<prefix>_<agent_short>_monitor.svh` | `PREFIX_PARAM_monitor.svh.tmpl` | same |
| `<agent_dir>/<prefix>_<agent_short>_sub_agent.svh` | `PREFIX_PARAM_sub_agent.svh.tmpl` | parameterized uvm_agent |
| `<agent_dir>/<prefix>_<agent_short>_agent.svh` | `PREFIX_PARAM_top_agent.svh.tmpl` | holds N `<sub_agent> #(WIDTH_i) <inst_i>` |

The parameterized top-agent's cfg has one `virtual <prefix>_<iface_name> #(.<param>(<value>)) <inst_name>_vif;` per instance.

#### 3d. Package entry file

Last — after all `.svh` exist:

| Target path | Template |
|---|---|
| `<agent_dir>/<prefix>_<agent_short>_agent_pkg.sv` | `PREFIX_NAME_agent_pkg.sv.tmpl` |

Package includes svh files in dependency order:
`agent_cfg → item → sequencer → driver → monitor → cov → (sub_agent if parameterized) → agent → seq/*.svh`

### Step 4 — Update filelist

If `<verif_root>/filelist/tb.f` exists, add:

- `+incdir+<verif_root>/testbench/uvc/<agent_short>_agent`
- `+incdir+<verif_root>/testbench/uvc/<agent_short>_agent/seq`
- `<verif_root>/testbench/uvc/<agent_short>_agent/<prefix>_<agent_short>_agent_pkg.sv`

Insert in the "4b) UVC packages" section per patterns §1.3 order.

If tb.f doesn't exist, defer to `finalize-filelist-and-make`.

### Step 5 — Report

Per UVC emitted, print:

```text
UVC <agent_short> (from interface <name>):
  Files: <N> svh + 1 pkg
  Parameterized: <yes|no>
  Instances: <inst list, if parameterized>
```

## Post-conditions

- Each UVC has 8-9 files under `<agent_dir>/`
- All UVCs compile to `vlogan` when packaged (test after `add-env-layer` + `finalize-filelist-and-make`)
- Every class has `` `uvm_component_utils`` or `` `uvm_object_utils``, empty
  `new()`, empty `build_phase / run_phase` — no behavior

## Naming edge cases

- Interface `ctrl_if` → agent short name `ctrl` → agent dir `ctrl_agent`,
  UVC pkg `<prefix>_ctrl_agent_pkg`. **Do NOT** shorten further (avoid
  `c_agent` type collision).
- Interface `data_in_if` → agent short name `data_in` → dir `data_in_agent`
  (preserve underscore).
- Interface `sram_if` → agent short name `sram` → parameterized UVC layout.

## Do not

- Do not put behavior in `run_phase` / `build_phase` — that's M1.3+ manual
- Do not include interface `.sv` files inside package `` `include``
  (see stage1-patterns.md § 1.4 anti-pattern B)
- Do not import UVC packages from each other (each UVC is independent; env
  pkg imports all UVCs)
- Do not create `seq/` files without their entry in the pkg's `` `include``
  section — else the pkg compiles but seq classes are unusable
