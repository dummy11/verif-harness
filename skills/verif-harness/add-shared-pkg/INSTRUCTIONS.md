# add-shared-pkg — shared package generator

**Mode**: `/verif-harness add-shared-pkg`

**Purpose**: Generate the two shared TB packages —
`<prefix>_tb_pkg.sv` (typedefs / enums / constants) and
`<prefix>_pack_pkg.sv` (pack/unpack helper functions for wide data buses).

**Scope**: 2 files. Runs after `add-interface` (needs interface widths /
parameters in spec) and before `add-uvc-skeleton` (UVC packages import
these two).

## Pre-conditions

1. The project is bootstrapped and the Verification Planner has an approved action for shared packages
2. `.harness-config.json` exists
3. `<verif_root>/testbench/pkg/` is writable; create it additively if missing
4. `<verif_root>/docs/verification/harness-spec.yaml` has interface
   `parameters:` + `local_params:` (for tb_pkg constants) and, if any wide
   packed data buses need pack helpers, a `pack_pattern:` block per relevant
   interface

## Required reading

- `references/stage1-patterns.md` § 1 (compile-order rules; shared pkgs come
  before UVC pkgs in tb.f)
- `<verif_root>/docs/verification/tb_architecture.md` § Data Pack and Unpack

## Inputs

- `.harness-config.json` — for `<prefix>`
- `harness-spec.yaml` — parameters + pack_pattern per interface

**New `harness-spec.yaml` field: `pack_pattern:` per interface** (optional).
Used only when the interface has a wide packed data bus that driver /
monitor / refmodel all need to pack/unpack consistently. Example:

```yaml
interfaces:
  - name: data_in_if
    signals:
      - {name: data, width: "[DATA_WIDTH-1:0]", dir: to-dut}
    pack_pattern:
      packed_signal: data
      dimensions:
        - {name: pixel_idx, size: 8}          # outer index
        - {name: oc_idx,    size: 16}         # inner index
      element_width: 37                       # bits per lane
      # → packed_signal[pixel_idx * (oc_idx_size * elem_w) + oc_idx * elem_w +: elem_w]
```

If a spec has no `pack_pattern:` on any interface, `<prefix>_pack_pkg.sv`
is emitted as a stub (empty package with a comment "no pack helpers
required at this stage").

## Execution plan

### Step 1 — Precondition audit

Standard 4 pre-condition checks. Stop with report on failure.

### Step 2 — Read harness-spec.yaml

Collect from each interface:

- `parameters:` — become `parameter int NAME = DEFAULT;` in tb_pkg
- `local_params:` — become `parameter int NAME = EXPR;` in tb_pkg (top-level;
  they're not localparams here because they cross packages)
- `pack_pattern:` — one per interface that needs pack/unpack

Also load DUT-wide enum lists from `<verif_root>/docs/design/acc_constraints.md`
(or equivalent) if referenced. Note: for M1.1 skeleton, enum values can be
placeholder — human refines them during M1.3+ when constraints matter.

### Step 3 — Emit `<prefix>_tb_pkg.sv`

Use `templates/PREFIX_tb_pkg.sv.tmpl`. Substitute `<PREFIX>` with prefix.
Fill `GENERATED_*` blocks:

- **GENERATED_DUT_PARAMETERS** — one `parameter int NAME = VALUE;` line per
  unique parameter across all interfaces. Detect conflicts (same name,
  different default) and stop with error.
- **GENERATED_DERIVED_PARAMETERS** — from each interface's `local_params:`,
  hoisted to package scope with `parameter int NAME = EXPR;`. Preserve
  declaration order (later params may reference earlier ones).
- **GENERATED_TYPEDEFS** — `typedef enum bit [N-1:0] { ... } <name>_e;` for
  each enum group defined in spec's `enums:` section (optional). For M1.1
  skeleton, emit empty placeholder if not provided.
- **GENERATED_LANE_TYPEDEFS** — `typedef logic [W-1:0] <name>_t [0:D1-1][0:D2-1];`
  for each `pack_pattern:` entry (one typedef per packed signal). Used by
  pack_pkg for function signatures.

### Step 4 — Emit `<prefix>_pack_pkg.sv`

Use `templates/PREFIX_pack_pkg.sv.tmpl`. For each `pack_pattern:` entry,
generate two functions:

```systemverilog
function automatic logic [<total_width>-1:0] pack_<packed_signal>(
  input <lane_typedef> lanes
);
  logic [<total_width>-1:0] packed_data;
  packed_data = '0;
  for (int <dim1> = 0; <dim1> < <size1>; <dim1>++) begin
    for (int <dim2> = 0; <dim2> < <size2>; <dim2>++) begin
      int lsb = <dim1> * (<size2> * <elem_w>) + <dim2> * <elem_w>;
      packed_data[lsb +: <elem_w>] = lanes[<dim1>][<dim2>];
    end
  end
  return packed_data;
endfunction

function automatic <lane_typedef> unpack_<packed_signal>(
  input logic [<total_width>-1:0] packed_data
);
  <lane_typedef> lanes;
  for (int <dim1> = 0; <dim1> < <size1>; <dim1>++) begin
    for (int <dim2> = 0; <dim2> < <size2>; <dim2>++) begin
      int lsb = <dim1> * (<size2> * <elem_w>) + <dim2> * <elem_w>;
      lanes[<dim1>][<dim2>] = packed_data[lsb +: <elem_w>];
    end
  end
  return lanes;
endfunction
```

Only 2D pack patterns supported at this stage. If spec has 3D+ pack
(scale slot × oc-group indexing), emit a stub with `// TODO: 3D pack —
see acc_interface.md §5.2` comment.

If no `pack_pattern:` in any interface, emit an empty package:

```systemverilog
package <prefix>_pack_pkg;
  import <prefix>_tb_pkg::*;
  // No pack helpers required at this stage. Add pack_pattern to
  // harness-spec.yaml when driver/monitor need pack/unpack.
endpackage
```

### Step 5 — Update filelist

If `<verif_root>/filelist/tb.f` exists, insert both files after `# 3) Shared packages`
comment (see stage1-patterns.md §1.3 template). If tb.f doesn't exist yet,
defer to `finalize-filelist-and-make` mode.

### Step 6 — Report

Print summary of what was emitted, including:

- Enum groups present / stubbed
- Pack functions emitted (name + dimensions)
- Any typedefs added

## Post-conditions

- `<verif_root>/testbench/pkg/<prefix>_tb_pkg.sv` exists
- `<verif_root>/testbench/pkg/<prefix>_pack_pkg.sv` exists (may be empty stub)
- Both compile independently (`vlogan` on either succeeds; test after
  `add-uvc-skeleton` completes)

## Do not

- Do not include class declarations (packages here are pure typedef/function)
- Do not import UVC packages (shared pkgs are FOUNDATIONS — dependencies go
  the other way)
- Do not import uvm_pkg here — shared pkgs are UVM-agnostic
