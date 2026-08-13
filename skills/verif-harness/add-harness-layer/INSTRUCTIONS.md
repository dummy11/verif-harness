# add-harness-layer — M1.1 Harness Generator

**Mode**: `/verif-harness add-harness-layer`

**Purpose**: Generate Stage 1 Milestone 1.1 harness-integration-layer scaffolding
for an existing verif-harness project (Stage 0 already approved). Produces 15
files: 3 `dut_harness/` modules + 7 `tb_harness/` files + 5 SVA checker stubs,
plus a filelist snippet.

**Scope**: harness layer only. This mode does NOT generate: protocol
interfaces (assumed pre-existing), UVC agent packages, env/test packages, or
tb_top. Those are separate concerns; a future `stage1-skeleton` mode may
bundle them.

## Pre-conditions

Before proceeding, verify ALL of the following. If any check fails, STOP and
report to the user.

1. `.harness-config.json` exists in project root
2. All 12 Stage 0 docs at `Approved` (grep `Review Metadata` block in each doc
   under `<verif_root>/docs/`)
3. `<verif_root>/testbench/top/harness/dut_harness/` empty or missing
4. Protocol interfaces already scaffolded at `<verif_root>/testbench/top/if/`
   (at least one `*_if.sv` file exists there). If missing, direct the user to
   run `/verif-harness add-interface` FIRST — that mode generates the
   interfaces from the same `harness-spec.yaml`. Do NOT proceed without
   interfaces; the harness has nothing to route otherwise.
5. RTL top file exists at `<rtl_root>/<dut_top>.v` or `.sv`

## Required reading (MANDATORY, in order)

Read these files completely before writing any code. They encode hard rules
the generator must honor.

1. `<skill-dir>/references/stage1-patterns.md` — §1 (compile
   order), §4 (harness layer), §5 (bind syntax). These sections are load-bearing.
2. `<verif_root>/docs/verification/tb_architecture.md` — project-specific
   interface names, modport conventions, per-interface signal lists
3. `<verif_root>/docs/verification/verification_plan.md` — Human Decisions LD8,
   LD9, LD10, LD11, LD12 in particular

Do not skim. If the generator disagrees with what these docs say, STOP and
surface the conflict — do not silently deviate.

## Inputs

- `.harness-config.json` — for `<prefix>`, `<rtl_root>`, `<dut_top>`, `<verif_root>`
- `<verif_root>/docs/verification/harness-spec.yaml` — signal-to-interface
  grouping, DFT strap list, status probe list, variants. If absent, this mode
  asks the user interactively (see Step 3).
- Parsed DUT top port list — from `rtl_parser.py`

## Execution plan

Follow these steps IN ORDER. Do not merge, reorder, or skip.

### Step 1 — Precondition audit

- Read `.harness-config.json`. Extract `project_name` (→ `<prefix>`),
  `rtl_root`, `rtl_top`, `verif_root`.
- Run the 5 pre-condition checks. Report each with ✓/✗.
- If any ✗, STOP and ask the user how to proceed. Do NOT try to fix
  automatically.

### Step 2 — Parse DUT top port list

Run the parser:

```bash
python3 <skill-dir>/add-harness-layer/rtl_parser.py \
  --top <dut_top> <rtl_root>/<dut_top>.v > /tmp/verif_harness_ports.json
```

Verify the output is a JSON list of `{name, dir, width_expr, is_2d}` objects.
Read it and hold in context. If the parser errors, report to the user — do
not silently proceed with a partial port list.

### Step 3 — Get harness spec

**Path A (preferred)**: read `<verif_root>/docs/verification/harness-spec.yaml`
if it exists. Validate it has: `prefix` (or derive from config), `interfaces:`,
`straps:`, `status_probes:`, `variants:`. Reject with a clear error if any
required section is missing.

**Path B (interactive)**: if the yaml is absent, use the available user-input mechanism to
gather:

1. Which port name patterns group into each interface (show the parsed port
   list, ask user to assign each port to an interface — or read prefix
   heuristics: `s_*` → data_in_if, `m_*` → data_out_if, `*_sram_*` / `*_rden`
   / `*_rdata` → sram_if, `clk`/`rst_n`/`ptest_*`/`clk_always_on`/`compute_*`/
   `*_dtype`/`*_m1`/`small_*`/`kernel_*` → ctrl_if).
2. Which DFT strap signals to route from `<prefix>_harness_if` into `ctrl_if`.
3. Whether to tie all status probes (`dut_compute_done`, `dut_output_drained`,
   `dut_hung`) to `1'b0` for M1.1 (recommended default).
4. Variant list (default: `[DUT_RTL]`).

After collection, offer to save the answers to `<verif_root>/docs/verification/
harness-spec.yaml` for reproducibility (recommended: yes).

### Step 4 — Emit tb_harness/ files (7 files)

Target directory: `<verif_root>/testbench/top/harness/tb_harness/`.

For each of the following templates in `<skill-dir>/
add-harness-layer/templates/`, read the `.tmpl`, substitute placeholders,
and write to the target path.

Global placeholder rules:
- `<PREFIX>_` → `<prefix>_` (e.g. `<PREFIX>_ctrl_if` → `acc_ctrl_if`)
- `<PREFIX>` (uppercase) → uppercase form of prefix (used in `` `define`` names)
- Preserve all comments; they carry lineage back to stage1-patterns.md sections

Files to emit (target path : template):

| Target file | Template | Notes |
|---|---|---|
| `<prefix>_harness_if.sv` | `PREFIX_harness_if.sv.tmpl` | Env control interface + tasks |
| `<prefix>_harness_api_pkg.sv` | `PREFIX_harness_api_pkg.sv.tmpl` | Package entry, includes 4 svh |
| `<prefix>_harness_api.svh` | `PREFIX_harness_api.svh.tmpl` | Aggregate class |
| `<prefix>_reset_api.svh` | `PREFIX_reset_api.svh.tmpl` | reset sub-API |
| `<prefix>_status_api.svh` | `PREFIX_status_api.svh.tmpl` | status sub-API |
| `<prefix>_strap_api.svh` | `PREFIX_strap_api.svh.tmpl` | strap sub-API |
| `<prefix>_clkrst_gen.sv` | `PREFIX_clkrst_gen.sv.tmpl` | M1.1: initial clk=0 only |

If any target file already exists, ASK the user before overwriting.

### Step 5 — Emit dut_harness/ files (3 files)

Target directory: `<verif_root>/testbench/top/harness/dut_harness/`.

Three files, but two contain **variable-length blocks** that must be
generated from the harness spec + parsed port list.

#### Formatting conventions (apply to every variable block below)

These rules make skill output reproducible across runs. Follow them literally.

- **Marker splicing**: each `// >>> GENERATED_<X> <<<` line in the template is
  followed by **example-comment lines** (starting with `//`) that show what the
  block should look like. Delete the marker AND all subsequent `//` example
  lines up to the next blank line or non-comment line, then insert the
  generated content. Do not leave the marker or example comments in the emitted
  file.
- **Port map alignment**: DUT port names are padded to column **24**
  (i.e. `.` + port name + spaces so `(` starts at column 24). Example:
  ```
      .clk                    (ctrl.clk),
      .mac_acc_fifo_overflow  (dout.exc_overflow),
  ```
  If a port name is longer than 22 characters, use a single space then `(`.
- **Interface port list alignment**: interface type + `.dut_mp` padded so the
  instance name starts at column 42. Example:
  ```
    acc_ctrl_if.dut_mp                     ctrl,
    acc_data_in_if.dut_mp                  din,
  ```
- **No trailing comma**: the last item in any comma-separated block (port
  map, interface port list, dut_select port connections) does NOT get a
  trailing comma. Join with `,\n`, do not append a final `,`.
- **Preserve DUT port order**: emit port-map lines in the order they appear
  in `rtl_parser.py` output, not sorted or regrouped. Adding section-header
  comments (`// Clock / reset / DFT`, etc.) is optional cosmetic — skip if
  in doubt.
- **`assign` alignment**: strap and status assigns pad the LHS name to
  column 28. Example:
  ```
    assign ctrl.rst_n           = harness.rst_n;
    assign ctrl.ptest_icg_mode  = harness.test_mode;
    assign harness.dut_compute_done   = 1'b0;
  ```

#### `<prefix>_rtl_wrap.sv` — one variable block (`GENERATED_PORT_MAP`)

For each DUT port from the parser output, emit one line following the port
map alignment rule above:

```
    .<dut_port>              (<if_inst>.<signal>),
```

Where:
- `<if_inst>` is the interface **instance name** (harness module port name —
  e.g. `ctrl`, `din`, `dout`, `ws_sram`, `scale_sram`), determined by looking
  up `<dut_port>` in the harness spec's `interfaces[].ports` or `port_map`.
- `<signal>` is the field name inside that interface — same as `<dut_port>`
  unless the spec's `port_map:` remaps it (e.g. `s_acc_vld → vld`).

Splice into `PREFIX_rtl_wrap.sv.tmpl` at `// >>> GENERATED_PORT_MAP <<<`,
following the marker splicing rule above. Also generate the module port list
at `// >>> GENERATED_WRAP_PORTS <<<` (one line per protocol interface / one
line per parameterized instance).

#### `<prefix>_dut_select.sv` — two blocks (near-static)

Fill `GENERATED_WRAP_PORTS` and `GENERATED_WRAP_INST_CONNECTIONS`. Both are
derived from the harness spec's interface list (same content as rtl_wrap's
module port list). The `` `ifdef DUT_RTL`` branch instantiates
`<prefix>_rtl_wrap`; the `` `ifndef`` chain at the top provides the safe
default (do NOT edit the fallback block).

#### `<prefix>_dut_harness.sv` — five variable blocks

Emit in this order (matches the template's marker order):

1. **`GENERATED_HARNESS_PORTS`**: one interface port per protocol interface
   in the spec (or per parameterized instance for `sram_if`), preceded by
   `<prefix>_harness_if harness` as the first line. Comma-separated, no
   trailing comma.

2. **`GENERATED_STRAP_ASSIGNS`**: for each `strap:` entry in the spec, emit:
   ```
     assign ctrl.<ctrl_signal> = harness.<harness_signal>;
   ```
   **Do NOT emit `assign ctrl.rst_n = harness.rst_n;` here** — the template
   already has this line hard-coded above the marker (per §4.3 Rule 1 it is
   an invariant, not spec-driven).

3. **`GENERATED_STATUS_ASSIGNS`**: for each `status_probes:` entry, emit:
   ```
     assign harness.<probe_name> = <tie_expr>;
   ```
   M1.1 tie is `1'b0` for all probes.

4. **`GENERATED_DUT_SELECT_PORTS`**: same shape as HARNESS_PORTS but WITHOUT
   `harness` — this is the `<prefix>_dut_select u_dut_sel (...)` instance
   port connection list. Use `.<inst_name>(<inst_name>)` per line, aligned.

5. **`GENERATED_BINDS`**: one bind per protocol interface (type-level bind per
   §5.2 / §5.3 of stage1-patterns.md):
   ```
     bind <PREFIX>_<if_name> <PREFIX>_<checker_name>_checker u_<name>_chk ();
   ```
   For parameterized interfaces (e.g. `<PREFIX>_sram_if` with two
   instances), emit exactly ONE bind — type-level bind covers all instances.

### Step 6 — Emit SVA checker stubs (5 files)

Target directory: `<verif_root>/testbench/top/sva/`.

For each protocol interface in the harness spec, emit one portless empty
checker module from `PREFIX_INTERFACE_checker.sv.tmpl` (substituting the
interface name and checker name).

Emit `<prefix>_internal_checker.sv` from `PREFIX_internal_checker.sv.tmpl` —
contains two empty modules (`<prefix>_internal_fifo_checker` and
`<prefix>_internal_ctrl_checker`) with no bind statements (per §4.1 note,
internal binds are deferred to Milestone 1.4+).

### Step 7 — Emit filelist snippet

If `<verif_root>/filelist/tb.f` does not exist, generate it in full from
`harness_files.f.tmpl` — with a note to the user that they still need to add
their UVC / env / test / top entries (this mode's scope is harness only).

If `<verif_root>/filelist/tb.f` DOES exist, DO NOT modify it. Instead:

1. Read the existing tb.f
2. Check which of the 15 emitted files are already referenced (grep)
3. Report which are missing
4. Ask the user whether to append the missing entries in the correct sections
   or output a diff for manual review

Do not silently overwrite an existing filelist — it may contain the user's
env/test/UVC entries that we don't want to lose.

### Step 8 — Report + verify

1. List every file created (or overwritten, with user consent).
2. Print the exact compile command the user should now run:
   ```
   make -C <verif_root>/regress compile
   ```
   ...or the equivalent given their Makefile setup.
3. Remind the user:
   - Milestone 1.1 exit criterion: `vlogan + vcs -elab` with 0 error / 0 warning.
   - The generated harness contains no assertion bodies (§5.3), no
     `clkrst_gen` waveform (§9 will populate in M1.2), and status probes
     tied to `1'b0` (§10 / real probes in M1.5). This is by design.
4. If any file emission was skipped (existed & user declined overwrite),
   surface which ones so the user can reconcile.

## Post-conditions

After successful execution:

- `<verif_root>/testbench/top/harness/dut_harness/` contains 3 files
- `<verif_root>/testbench/top/harness/tb_harness/` contains 7 files
- `<verif_root>/testbench/top/sva/` contains 4-5 files (one per protocol
  interface + 1 internal)
- `<verif_root>/docs/verification/harness-spec.yaml` exists (if Path B was
  taken and user opted to save)
- Filelist entries referenced or added

The generated harness follows every rule in `references/stage1-patterns.md`
sections 1, 4, 5. If the user later modifies the generated files, they must
uphold those rules themselves — the skill does not re-check on subsequent
runs.

## Failure modes and recovery

| Symptom | Likely cause | Recovery |
|---------|--------------|----------|
| Parser output empty or malformed | RTL top uses Verilog-95 style or macro-heavy port decls | Ask user to provide port list manually or convert to Verilog-2001 ANSI |
| A DUT port doesn't match any interface pattern | Missing entry in `harness-spec.yaml` | Ask user which interface it belongs to; update spec; regenerate |
| Interface referenced in spec but no `.sv` under `top/if/` | Interfaces not yet scaffolded | STOP; direct user to run `/verif-harness add-interface` first (same `harness-spec.yaml` covers both modes) |
| Compile fails on generated files | Bug in this skill's template or spec | Report the error verbatim; do NOT hand-fix — file a fix for the template |

## Do not

- Do not modify `rtl/` (harness is TB, RTL is read-only)
- Do not touch existing `.sv` / `.svh` files in the target project (this mode
  only ADDS files)
- Do not deviate from the file naming / directory layout in `tb_architecture.md`
- Do not add assertion bodies to the emitted checker stubs (that's Stage 3+
  scope)
- Do not add UVC / env / test / tb_top files (out of this mode's scope)
