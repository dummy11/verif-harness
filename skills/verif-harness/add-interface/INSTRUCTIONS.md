# add-interface — protocol interface generator

**Mode**: `/verif-harness add-interface`

**Purpose**: Generate protocol interface `.sv` files for a VSTIM/VCHK action from a
harness-spec.yaml, plus create matching `uvc/<name>_agent/seq/` subdirectory
skeleton per interface. Precedes `add-harness-layer` mode.

**Scope**: interfaces + UVC directory scaffold only. Does NOT generate UVC
class files (that's for future `add-uvc-agent` mode).

## Pre-conditions

Before proceeding, verify ALL:

1. The project is bootstrapped and VPlan has an approved action for interface generation
2. `.harness-config.json` exists in project root
3. `<verif_root>/testbench/top/if/` is absent/empty or contains only reviewed additive targets
4. `<verif_root>/docs/verification/harness-spec.yaml` exists with at least
   one interface entry that has BOTH `signals:` and `dir` roles on each
   signal — OR user is prepared to write it interactively

## Required reading

1. `<skill-dir>/references/stage1-patterns.md` — § 2
   (Interface Design), § 1 (compile-order rules for interfaces)
2. `<verif_root>/docs/verification/tb_architecture.md` — project-specific
   interface layout & modport conventions

## Execution plan

### Step 1 — Precondition audit

Read `.harness-config.json`. Report state of 4 pre-conditions with ✓/✗. If
`harness-spec.yaml` missing or lacking `signals:` sections, offer to:

- (A) collect interface signals interactively via the available user-input mechanism (per
  interface: name + parameters + input_args + signal list with dir role)
- (B) generate a stub `harness-spec.yaml` from `.harness-config.json` and
  the DUT top port list (via `rtl_parser.py`), then ask the user to fill in
  signal-level fields

Do NOT proceed without a complete spec.

### Step 2 — Parse harness-spec.yaml

For each interface entry, extract:

- `name` (required) — becomes `<prefix>_<name>.sv` (the spec name INCLUDES
  the `_if` suffix, e.g. `name: ctrl_if` → `acc_ctrl_if.sv`). Do NOT append
  a second `_if`.
- `parameters:` list of `{name, default}` (optional)
- `local_params:` list of `{name, expr}` (optional)
- `input_args:` list of names (optional, usually `[clk, rst_n]`)
- `signals:` list of `{name, width, dir}` — required
- `modport_names:` optional map to rename default modport names, e.g.:
  ```yaml
  modport_names:
    driver: agent      # override 'driver' → 'agent' (used by sram-style UVCs
                       # where the interface is memory-model, not driver-model)
  ```

For each signal, `dir` must be one of: `to-dut`, `from-dut`, `clkrst`. Any
other value is an error; report and stop.

Note: if the spec has parameterized instances (e.g. `sram_if` with two
`instances:`), still emit ONE interface `.sv` file — parameterized interface
declaration covers all instances. The `instances:` block is consumed by
`add-harness-layer`, not this mode.

### Step 3 — Render each interface (one .sv per entry)

Target: `<verif_root>/testbench/top/if/<prefix>_<name>.sv` (spec `name`
already includes `_if`, so the output filename is `<prefix>_<name>.sv`,
NOT `<prefix>_<name>_if.sv`).

Use `templates/PREFIX_INTERFACE_if.sv.tmpl` as the base. Replace `<PREFIX>`
with the project prefix, `<IFACE_NAME>` with the interface spec name
(includes `_if` suffix), and `<DRIVER_MODPORT>` with either `driver`
(default) or the spec's `modport_names.driver` override (e.g. `agent`).
Splice generated content into each `>>> GENERATED_<X> <<<` marker per
the rules below.

#### 3.1 GENERATED_HEADER

Emit inline immediately after `interface <PREFIX>_<name>` (no newline
between name and header):

- If both `parameters:` and `input_args:` are empty → emit just `;`
  (single semicolon inline). Result: `interface acc_ctrl_if;`
- If `parameters:` non-empty and `input_args:` empty → emit:
  ```
   #(
    parameter int NAME1 = DEFAULT1,
    parameter int NAME2 = DEFAULT2
  );
  ```
- If both non-empty → emit:
  ```
   #(
    parameter int NAME = DEFAULT
  )(
    input logic clk,
    input logic rst_n
  );
  ```
- If only `input_args:` non-empty → emit:
  ```
   (
    input logic clk,
    input logic rst_n
  );
  ```

**Formatting**: 2-space indent inside blocks. No trailing comma inside
either parenthesized block. No blank line between the `interface` line
and the first following content.

#### 3.2 GENERATED_LOCAL_PARAMS

If `local_params:` non-empty, emit one `localparam int NAME = EXPR;` line per
entry. Align `=` to column ~24 for readability. If empty or missing, delete
the marker + example comments (produce no output).

#### 3.3 GENERATED_SIGNALS

One line per signal, preserving spec order:

- `width: 1` → `  logic <name>;`
- `width: "[expr]"` → `  logic [expr] <name>;`

Column-align signal names to column ~26 for readability:

```
  logic [PIXEL_NUM-1:0]      vld;
  logic [RDY_WIDTH-1:0]      rdy;
  logic [DATA_WIDTH-1:0]     data;
```

Preserve spec signal order (do not sort).

#### 3.4 Modport groups — signal → modport direction rules

For every signal, classify into a group by `dir`:

| `dir`     | driver*  | monitor | dut_mp   | clkrst_gen |
|-----------|----------|---------|----------|------------|
| to-dut    | output   | input   | input    | —          |
| from-dut  | input    | input   | output   | —          |
| clkrst    | input    | input   | input    | output     |

`*driver` is the default name — may be renamed via `modport_names.driver`
(e.g. → `agent` for sram-like interfaces).

`input_args` signals (clk/rst from interface port list) are treated as
implicit `clkrst`-role for the purpose of driver/monitor/dut_mp modports —
add them to `input` of driver/monitor/dut_mp. They do NOT go into
`clkrst_gen` modport (they're driven from outside the interface).

**Ordering within each direction group**: use SPEC DECLARATION ORDER, not
role-grouped order. Specifically:

- `driver` input line: `input_args` first (in order), THEN `signals` filtered
  to (`clkrst`, `from-dut`) in signal-declaration order.
- `driver` output line: `signals` filtered to `to-dut` in declaration order.
- `monitor` input line: `input_args` first, THEN ALL `signals` in declaration
  order (unfiltered).
- `dut_mp` input line: `input_args` first, THEN `signals` filtered to
  (`clkrst`, `to-dut`) in declaration order.
- `dut_mp` output line: `signals` filtered to `from-dut` in declaration order.
- `clkrst_gen` output line: `signals` filtered to `clkrst` in declaration order.

#### 3.5 GENERATED_MODPORT_DRIVER

Modport name uses spec's `modport_names.driver` override, or defaults to
`driver`. Emit:

```
  modport <name> (
    input  <input_args + clkrst + from-dut, in declaration order>,
    output <to-dut, in declaration order>
  );
```

- If a direction group has 0 signals, omit that line entirely (don't emit an
  empty `input  ,` or `output ,`).
- If both groups are empty, omit the entire modport (rare — indicates a
  malformed spec; warn user).
- Line-wrap long signal lists: if the combined signal names exceed 72
  characters, break after every ~4-5 signals with 2-space continuation
  indent.

#### 3.6 GENERATED_MODPORT_MONITOR

```
  modport monitor (
    input <all signals, in spec order>
  );
```

`input_args` signals precede declared signals; declared signals in spec
order. Line-wrap same as driver modport.

#### 3.7 GENERATED_MODPORT_DUT_MP

```
  modport dut_mp (
    input  <input_args + clkrst-sigs + to-dut-sigs>,
    output <from-dut-sigs>
  );
```

Same drop-empty and line-wrap rules as driver.

#### 3.8 GENERATED_MODPORT_CLKRST_GEN

Emit ONLY IF at least one signal in the interface has `dir: clkrst`.

```
  modport clkrst_gen (
    output <clkrst-sigs>
  );
```

If no clkrst signals, delete the marker AND all subsequent `//` example
lines up to the next blank line. Result: no `clkrst_gen` modport appears in
the emitted file.

### Step 4 — Create UVC directory skeleton

For each interface `<name>`, create the following directory tree (if not
already present) under `<verif_root>/testbench/uvc/`:

```
uvc/<name_without_if>_agent/
├── seq/
└── (empty — UVC class files come later)
```

Where `<name_without_if>` strips the trailing `_if` (e.g. `ctrl_if` →
`ctrl_agent`). Also strip `data_` if you want the shorter convention (e.g.
`data_in_if` → `data_in_agent` — DO NOT shorten, keep the `data_` prefix).

Rule: `<name>` → strip trailing `_if` → append `_agent`.

Place a `.gitkeep` file in each empty leaf directory (`seq/` and the agent
dir itself) so git tracks them.

For parameterized interfaces with multiple instances (sram_if): still create
one `sram_agent/` directory — the sub-agent pattern lives inside via future
`add-uvc-agent` mode.

### Step 5 — Update filelist

If `<verif_root>/filelist/tb.f` exists, add the new interface `.sv` files
under the `# 1) Interfaces` section (preserve existing content — merge,
don't overwrite). Format:

```
<verif_root>/testbench/top/if/<prefix>_ctrl_if.sv
<verif_root>/testbench/top/if/<prefix>_data_in_if.sv
...
```

Insert BEFORE any harness_if or uvm_pkg reference. Order interfaces
alphabetically or in spec order (either is fine — VCS resolves interface
types at elab, not compile).

If `tb.f` does not exist, do nothing here — `add-harness-layer` will
create it later including these entries.

### Step 6 — Verify

Grep the emitted `.sv` files for:

- Every `modport X (...)` block has at least one signal in either input or
  output group (no empty modports)
- Every `logic <name>;` declaration has a matching modport entry in at
  least one of driver/monitor/dut_mp
- `clkrst_gen` modport appears iff there's at least one `dir: clkrst`
  signal in the spec

Report violations. Do NOT auto-fix — surface to user.

### Step 7 — Report

Print summary:

```text
add-interface complete.

Interfaces emitted (N files):
  <verif_root>/testbench/top/if/<prefix>_<name>_if.sv    (M signals, K modports)
  ...

UVC directory scaffold created:
  <verif_root>/testbench/uvc/<name>_agent/{seq/,.gitkeep}
  ...

Filelist updated: <verif_root>/filelist/tb.f (added N entries)
                  OR "not present — will be created by add-harness-layer"

Next step: run /verif-harness add-harness-layer to generate M1.1 harness.
```

## Post-conditions

- Each interface in the spec has a matching `.sv` in `<verif_root>/testbench/top/if/`
- For each interface, a `uvc/<name>_agent/seq/` scaffold exists with `.gitkeep`
- Filelist references all new interfaces (or is deferred to `add-harness-layer`)

## Do not

- Do not generate UVC class files (`_agent.svh`, `_driver.svh`, etc.) — that's
  future `add-uvc-agent` mode.
- Do not modify existing interfaces — this mode only ADDS.
- Do not derive DUT-port-to-signal mapping (that's what `add-harness-layer`
  does with the `ports:` + `port_map:` fields).
- Do not silently drop signals whose `dir` value is unrecognized — halt and
  report.
