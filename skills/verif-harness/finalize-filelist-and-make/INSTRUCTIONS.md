# finalize-filelist-and-make — filelist and Makefile finalizer

**Mode**: `/verif-harness finalize-filelist-and-make`

**Purpose**: Emit or update `<verif_root>/filelist/tb.f`, `rtl.f`, `sim.f`
and `<verif_root>/regress/Makefile` so `make -C <verif_root>/regress
compile` runs cleanly at M1.1 exit.

**Scope**: 4 files. Runs LAST in the M1.1 pipeline — after `add-interface`,
`add-shared-pkg`, `add-uvc-skeleton`, `add-env-layer`, and
`add-harness-layer` have populated the source tree.

## Pre-conditions

1. `.harness-config.json` exists
2. All Stage 0 docs `Approved`
3. Every source file referenced by the filelist templates actually exists
   on disk (skill audits before writing filelist)
4. `<verif_root>/filelist/` and `<verif_root>/regress/` directories exist
   (from `init` Step 4b)

## Required reading

- `references/stage1-patterns.md` § 1 (compile-order contract, especially
  the § 1.5 annotated filelist template — this mode implements it verbatim)
- `<verif_root>/docs/verification/tb_architecture.md` § Compilation Structure

## Execution plan

### Step 1 — Precondition audit + source-file inventory

Standard checks + **enumerate what actually exists** under:

- `<verif_root>/testbench/top/if/*.sv`                    → interfaces
- `<verif_root>/testbench/top/harness/tb_harness/*.sv`    → harness_if + api_pkg + clkrst_gen
- `<verif_root>/testbench/pkg/*.sv`                       → tb_pkg, pack_pkg
- `<verif_root>/testbench/uvc/*/*_agent_pkg.sv`           → UVC pkgs
- `<verif_root>/testbench/env/*_env_pkg.sv`               → env pkg
- `<verif_root>/testbench/test/*_test_pkg.sv`             → test pkg
- `<verif_root>/testbench/top/harness/dut_harness/*.sv`   → dut_harness modules
- `<verif_root>/testbench/top/sva/*.sv`                   → assertion checkers
- `<verif_root>/testbench/top/*_tb_top.sv`                → tb_top

Also enumerate RTL under `<rtl_root>/`:

- Every `.v` and `.sv` file, minus any explicitly excluded ones (from
  `.harness-config.json` optional `rtl.exclude:` list — commonly used to
  skip `dut_wrapper.v` per LD7-style decisions).

Report the inventory. If ANY category is empty (e.g. no UVC pkgs found),
STOP and direct user to run the missing prerequisite mode.

### Step 2 — Emit `<verif_root>/filelist/rtl.f`

Use `templates/rtl.f.tmpl`. Substitute `<PREFIX>`, then splice one line per
enumerated RTL file at `# >>> GENERATED_RTL_SOURCES <<<`. Path style:
relative from `<verif_root>` (e.g. `../rtl/demo_fifo.sv`).

### Step 3 — Emit `<verif_root>/filelist/tb.f`

Use `templates/tb.f.tmpl`. Follow the § 1.5 canonical order:

1. `+incdir+` lines — one per directory containing `.svh` files that a
   package will include (all UVC dirs, their `seq/` sub-dirs, `env`, `test`,
   `pkg`, `tb_harness`)
2. Interfaces (`.sv` in `top/if/` + `top/harness/tb_harness/*harness_if.sv`)
3. Comment about uvm_pkg (tool-provided)
4. Shared packages (tb_pkg → pack_pkg)
5. tb_harness API package
6. UVC packages (one per UVC)
7. Env package
8. Test package
9. DUT-side harness modules (rtl_wrap → dut_select → dut_harness)
10. Assertion checker modules
11. clkrst_gen + tb_top

Splice the enumerated files at each `# >>> GENERATED_<X> <<<` marker.

### Step 4 — Emit `<verif_root>/filelist/sim.f`

Use `templates/sim.f.tmpl`. This is a small aggregator:

```text
# Common flags
+define+UVM_NO_DEPRECATED
-ntb_opts uvm-1.2

# RTL sources
-f <verif_root>/filelist/rtl.f

# TB sources
-f <verif_root>/filelist/tb.f

# Top module for elaboration
-top <prefix>_tb_top
```

### Step 5 — Emit `<verif_root>/regress/Makefile`

Use `templates/Makefile.tmpl`. Provide these targets:

- `help` — list available targets
- `compile` — `vlogan + vcs -elab` (M1.1 exit gate)
- `clean` — remove build artifacts

Substitutions:

- `<VERIF_ROOT>` from `.harness-config.json`
- `<PREFIX>` for `simv` naming
- Standard flags: `-sverilog -full64 -kdb -debug_access+all -assert svaext
  -ntb_opts uvm-1.2`

### Step 6 — Update-existing safety

If `tb.f`, `rtl.f`, `sim.f`, or `Makefile` already exist AND contain content
beyond a `.gitkeep`, offer three options using the available user-input mechanism:

1. **Overwrite** — clobber existing (user-approved data loss)
2. **Merge** — read existing, add missing entries, preserve custom sections
3. **Diff only** — write to `<file>.new` and report diff for user to
   manually resolve

Default: **Merge**.

### Step 7 — Compile smoke check (optional)

If `VCS` or `vlogan` is available in `$PATH`, run:

```bash
make -C <verif_root>/regress compile 2>&1 | tail -50
```

Report success or first errors. Do NOT fail the skill on compile error —
report to user for manual investigation. If tools not in PATH, skip
gracefully.

### Step 8 — Report

```text
finalize-filelist-and-make complete.

Filelist entries:
  <verif_root>/filelist/rtl.f       N RTL files
  <verif_root>/filelist/tb.f        M TB files (K UVCs, J interfaces)
  <verif_root>/filelist/sim.f       aggregator + tool options

Makefile targets:
  make help
  make compile     ← M1.1 exit gate
  make clean

Next: run `make -C <verif_root>/regress compile` on a machine with VCS.
Expected: 0 error / 0 warning at M1.1 exit criterion.

If warnings appear:
  - `input port not connected` on interface's decorative `clk_ext` (if any):
    add default `= 1'b0` to the port declaration, OR add `+lint=none` to
    the Makefile.
  - `assign on logic variable` on interface signals: expected — VCS accepts.
```

## Post-conditions

- `tb.f`, `rtl.f`, `sim.f`, `Makefile` all exist and reference every M1.1
  source file
- `make compile` (when run) reaches vcs elaboration successfully

## Do not

- Do not include files that don't exist on disk — skill audits first
- Do not hard-code project paths (use `<verif_root>` throughout)
- Do not add `run`, `regress`, `cov` targets — those come in Stage 4+
