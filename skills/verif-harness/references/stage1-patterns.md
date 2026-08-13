# Stage 1+ TB Code Patterns

Reference document consumed by the `add-harness-layer` mode of `verif-harness`
(and by any future Stage 1+ code-generation modes). Encodes the hard rules
learned from harness-style TB bootstrap, so downstream code generation stays
consistent across projects and does not repeat classic pitfalls (bind syntax,
compile ordering, multi-driver races, ...).

Symbol convention: `<prefix>` = the project's DUT / TB name prefix — e.g.
`demo` → `demo_ctrl_if`, `demo_dut_harness`, etc.
Skills should read the prefix from `.harness-config.json`.

---

## 1. Compile-Order Contract

The single most common source of hard-to-diagnose skeleton build failures is
interface / package mis-ordering. This section codifies the rules.

### 1.1 Interface / package separation

**Rule**: an interface is declared exactly once at project scope in a
dedicated `.sv` file. No `` `include`` of an interface file into any package,
before or after `endpackage`. Classes reference the interface via a
`virtual <if_name>` type handle only — the type name resolves from the
`$unit` scope where the interface declaration lives.

**Why**: SystemVerilog LRM restricts `interface` declarations to `$unit`,
module, or program scope. `` `include``-ing an interface file inside
`package … endpackage` puts the declaration in package scope, which is
illegal. `` `include``-ing outside `endpackage` (into `$unit`) compiles for a
single agent but breaks the moment two agent packages both reach the same
interface — either duplicate declaration (single-CU compile mode) or
`virtual <if>` type-identity mismatch across compile units (multi-CU mode).

### 1.2 `.sv` vs `.svh` split

| Suffix | Purpose | Independent CU | Include-able |
|--------|---------|----------------|--------------|
| `.sv`  | Top module / interface / package | ✓ | ✗ (is a compile entry) |
| `.svh` | Class definition header | ✗ (expands via include) | ✓ (into exactly one package) |

**Rules**:

- Interface → `.sv`, single project-wide instance
- Package → `.sv`, only `` `include``s `.svh` (never a `.sv`)
- Class → `.svh`, included into exactly one package

An `.svh` included by two packages defines the class twice → link conflict.
Enforce one-`.svh`-to-one-package by directory convention (per-UVC folder).

### 1.3 `$unit` scope ordering (filelist canonical order)

`vlogan` (or equivalent) processes the filelist top-to-bottom. Interfaces,
packages, and modules populate `$unit` scope; classes referencing interface
types need the interface visible at include time.

Canonical order:

1. **Interfaces** — every `.sv` under `top/if/` and `top/harness/tb_harness/*_harness_if.sv`
2. **`uvm_pkg`** — tool-provided (e.g. `vlogan -ntb_opts uvm-1.2`)
3. **Shared packages** — `<prefix>_tb_pkg`, `<prefix>_pack_pkg` (order matters if pack imports tb)
4. **tb_harness API package** — `<prefix>_harness_api_pkg.sv` (before env_pkg, env_cfg references its aggregate class type)
5. **UVC packages** — `<prefix>_<name>_agent_pkg.sv` × N
6. **Env package** — `<prefix>_env_pkg.sv` (imports all UVC pkgs + api_pkg + shared pkg)
7. **Test package** — `<prefix>_test_pkg.sv` (imports env_pkg)
8. **Structural modules** — rtl_wrap → dut_select → dut_harness
9. **Assertion checker module stubs** — external + internal
10. **Clock generator + tb_top** — `<prefix>_clkrst_gen.sv` then `<prefix>_tb_top.sv`

Also required: `+incdir+` for every directory containing `.svh` files that a
package will include, including `seq/` sub-directories under each UVC.

### 1.4 Anti-patterns

- **A.** `` `include`` an interface `.sv` inside `package … endpackage` — SV
  LRM violation, compile fails immediately.
- **B.** `` `include`` an interface `.sv` after `endpackage` (into `$unit`) —
  compiles for a single package, fails on multi-agent projects with either
  duplicate declaration (single-CU) or type mismatch on `virtual <if>`
  passed between agents (multi-CU). **Don't do it.** Keep interfaces as
  independent top-level `.sv` files.
- **C.** Same `.svh` included by two `.sv` packages — class defined twice,
  link conflict. Enforce one-owner rule.
- **D.** Package `.sv` including another package's `.sv` file — packages are
  imported (`import <pkg>::*;`), never included.
- **E.** `.svh` doing `import uvm_pkg::*;` at file scope — imports belong to
  the enclosing package; `.svh` should assume the enclosing package already
  imported what it needs.

### 1.5 Filelist template (annotated)

```text
# <verif_root>/filelist/tb.f
# Compile-order for Stage 1+ TB (see stage1-patterns.md §1.3).

# +incdir: every dir containing .svh a package will include
+incdir+<verif_root>/testbench/uvc/<name1>_agent
+incdir+<verif_root>/testbench/uvc/<name1>_agent/seq
# ... one pair per UVC ...
+incdir+<verif_root>/testbench/env
+incdir+<verif_root>/testbench/env/vseq
+incdir+<verif_root>/testbench/test
+incdir+<verif_root>/testbench/pkg
+incdir+<verif_root>/testbench/top/harness/tb_harness

# 1) Interfaces ($unit CU, must be first)
<verif_root>/testbench/top/if/<prefix>_<proto1>_if.sv
# ... one per protocol ...
<verif_root>/testbench/top/harness/tb_harness/<prefix>_harness_if.sv

# 2) uvm_pkg via tool option (-ntb_opts uvm-1.2)

# 3) Shared packages
<verif_root>/testbench/pkg/<prefix>_tb_pkg.sv
<verif_root>/testbench/pkg/<prefix>_pack_pkg.sv

# 4a) tb_harness API package (must precede env_pkg)
<verif_root>/testbench/top/harness/tb_harness/<prefix>_harness_api_pkg.sv

# 4b) UVC packages
<verif_root>/testbench/uvc/<name1>_agent/<prefix>_<name1>_agent_pkg.sv
# ... one per UVC ...

# 5) Env package
<verif_root>/testbench/env/<prefix>_env_pkg.sv

# 6) Test package
<verif_root>/testbench/test/<prefix>_test_pkg.sv

# 7) DUT-side harness modules
<verif_root>/testbench/top/harness/dut_harness/<prefix>_rtl_wrap.sv
<verif_root>/testbench/top/harness/dut_harness/<prefix>_dut_select.sv
<verif_root>/testbench/top/harness/dut_harness/<prefix>_dut_harness.sv

# 8) Assertion checker modules
<verif_root>/testbench/top/sva/<prefix>_<proto>_checker.sv
# ... one per protocol + <prefix>_internal_checker.sv ...

# 9) Clock generator + tb top
<verif_root>/testbench/top/harness/tb_harness/<prefix>_clkrst_gen.sv
<verif_root>/testbench/top/<prefix>_tb_top.sv

# RTL sources
-f <verif_root>/filelist/rtl.f
```

---

## 2. Interface Design

*(Outline — expand in follow-up pass)*

- 2.1 One-interface-per-protocol convention (LD8-style)
- 2.2 Standard modports: `driver` / `monitor` / `dut_mp` / (optional) `clkrst_gen`
- 2.3 Parameterized interfaces (e.g. WIDTH) — parameter propagation through port hierarchy
- 2.4 Anti-pattern: unused interface input port with no default → elab warning; either
  give a `= 1'b0` default or drop the port

---

## 3. Package-per-UVC Layout

*(Outline — expand in follow-up pass)*

- 3.1 Directory convention `uvc/<name>_agent/` per UVC (agent + agent_cfg + item + drv + mon + seqr + cov + seq/)
- 3.2 Include order inside `<name>_agent_pkg.sv`: agent_cfg → item → seqr → drv → mon → cov → agent → seq/
- 3.3 Dependency reasoning: cov subscribes item; agent constructs drv/mon/seqr
- 3.4 Anti-pattern: cross-UVC include of same `.svh`

---

## 4. Harness Integration Layer

The harness is the boundary between the UVM env (DUT-agnostic) and the DUT
implementation (RTL / gate / model). It absorbs everything DUT-specific so
UVM env never touches port names, hierarchy, variant selection, or DFT
strapping. Layout convention:

```
<verif_root>/testbench/top/harness/
├── dut_harness/     ← structural SV (rtl_wrap, dut_select, dut_harness)
└── tb_harness/      ← procedural env control (harness_if, api_pkg, clkrst_gen)
```

### 4.1 dut_harness/ — structural integration

Three modules; each has a single, non-overlapping responsibility.

**`<prefix>_rtl_wrap.sv` — pure port map**

- Ports: `.dut_mp` modports of every protocol interface (ctrl, data-in,
  data-out, SRAM × N)
- Body: exactly one DUT module instantiation, `.<dut_port>(<if_name>.<field>)`
  for each DUT port
- **No** UVM code, **no** decisions, **no** conditional logic. If port map
  becomes conditional, split into per-variant wrap files (rtl vs gate vs model)

**`<prefix>_dut_select.sv` — variant switch**

- Same port list as rtl_wrap
- Body: `` `ifdef DUT_RTL / DUT_GATE / DUT_MODEL`` selects which `_wrap`
  module to instantiate
- **Always include a fallback**: at the top of the file, if none of the
  variant macros is defined, `` `define DUT_RTL``. This lets `make compile`
  work without any `+define` on the command line. Undefined-variant fatal
  should be behind an `` `else`` `initial $fatal` — not the default path

**`<prefix>_dut_harness.sv` — structural entry point**

Ports: 4 protocol interfaces + `<prefix>_harness_if` (env control).

Responsibilities in order:

1. **Route control signals**: `assign ctrl_if.rst_n = harness_if.rst_n;`
   plus one `assign` per DFT strap (test_mode, clk_always_on, ...). Each
   strap has exactly one continuous assign here — nowhere else.
2. **Aggregate status probes**: `assign harness_if.dut_compute_done = <expr>;`
   The `<expr>` comes from `bind` probes into DUT internals (e.g.
   `!compute_en && ping_empty && pong_empty`). **In Milestone 1.1**, tie
   these to `1'b0` — probes come in later milestones.
3. **Instantiate `<prefix>_dut_select`**: pass all interface ports through
4. **Bind external protocol checkers**: `bind <if_type> <checker> u_<x> ();` —
   see §5 for the strict syntax rules

### 4.2 tb_harness/ — procedural env control

Purpose: give UVM env cycle-accurate reset / DFT strap / status polling
capability, without ever exposing DUT hierarchy or requiring env to know how
reset is applied.

**`<prefix>_harness_if.sv` — env control interface**

Not a protocol interface. Hosts:

- Control signals: `rst_n`, `test_mode`, `scan_enable`, `mbist_enable`,
  `clk_always_on` (drive from env → routed by dut_harness into DUT)
- Status signals: `dut_compute_done`, `dut_output_drained`, `dut_hung`
  (drive from DUT-side aggregation → read by env)
- Cycle-accurate tasks: `apply_cold_reset(assert_cycles, release_cycles)`,
  `wait_compute_done(timeout)`, `wait_output_drain(timeout)`
- Query functions: `is_compute_done()`, `is_output_drained()`

**Design decision LD12 B — class API in a package, not in the interface.**
The interface hosts only signals + tasks/functions that operate on those
signals with `@(posedge clk)`. All class-based APIs (reset_api, status_api,
strap_api) live in `<prefix>_harness_api_pkg`. Rationale:

- Classes inside an interface complicate cross-file type identity when env
  code needs a class handle
- Package-scope classes are trivially imported and cleanly show ownership
- Interfaces stay lean; their responsibility remains RTL-adjacent timing

**`<prefix>_harness_api_pkg.sv` — class API package**

Imports `uvm_pkg`; includes four `.svh` files in order:

```systemverilog
package <prefix>_harness_api_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  `include "<prefix>_reset_api.svh"    // reset_api
  `include "<prefix>_status_api.svh"   // status_api
  `include "<prefix>_strap_api.svh"    // strap_api
  `include "<prefix>_harness_api.svh"  // aggregate — must be last (holds sub-API handles)
endpackage
```

**Sub-API classes** — each takes `virtual <prefix>_harness_if vif` at
construction, wraps interface tasks/functions into a class-friendly API:

- `<prefix>_reset_api::cold_reset(cycles)` → `vif.apply_cold_reset(cycles)`
- `<prefix>_status_api::wait_compute_done(t)` → `vif.wait_compute_done(t)`
  (and `wait_output_drain`, `is_done`, `is_drained`)
- `<prefix>_strap_api::set_test_mode(en)` → `vif.test_mode = en;`
  (and set_scan_enable / set_mbist_enable / set_clk_always_on)

**Aggregate class `<prefix>_harness_api`** — holds one instance of each
sub-API; constructed once by tb_top and stored in env_cfg:

```systemverilog
class <prefix>_harness_api;
  <prefix>_reset_api  reset;
  <prefix>_status_api status;
  <prefix>_strap_api  strap;
  function new(virtual <prefix>_harness_if vif);
    reset  = new(vif); status = new(vif); strap = new(vif);
  endfunction
endclass
```

Usage from a test: `env.cfg.harness_api.reset.cold_reset(10);`

**task vs function rule**:

| Operation | Kind | Reason |
|-----------|------|--------|
| `cold_reset`, `wait_compute_done`, `wait_output_drain` | task | multi-cycle |
| `is_done`, `is_drained` | function | no time advance |
| `set_test_mode`, `set_*_enable`, `set_clk_always_on` | function void | immediate assign |

### 4.3 Single-source-of-truth rules

The interfaces are the sole connection between multiple SV modules. Every
signal on an interface must have exactly one driver — anywhere else invites
X-propagation races that only show up after the sim starts.

**Rule 1: `rst_n` — one driver, from `<prefix>_harness_if`**

- Source: `<prefix>_harness_if.rst_n` (driven by `apply_cold_reset` task)
- Route: `<prefix>_dut_harness` has `assign ctrl_if.rst_n = harness_if.rst_n;`
- **Do NOT** drive `rst_n` from `clkrst_gen` (its `clkrst_gen` modport
  permits it, but leave unused)
- **Do NOT** drive `rst_n` from tb_top or test `initial` blocks

**Rule 2: `clk` — one driver, from `<prefix>_clkrst_gen`**

- Source: `<prefix>_clkrst_gen` module (drives `ctrl_if.clk` via modport)
- Route: tb_top may `assign clk = ctrl_if_inst.clk;` to fan out to other
  interface constructors — this is a read-out, not a second driver
- Do NOT `initial clk = 0;` in tb_top or elsewhere

**Rule 3: DFT straps — one driver each, from `<prefix>_harness_if`**

- Source: `harness_if.test_mode / scan_enable / mbist_enable / clk_always_on`
  (set by `<prefix>_strap_api`)
- Route: `<prefix>_dut_harness` assigns each into the DUT-facing signal on
  ctrl_if

**Detection heuristic** (for skill audit): grep for `assign <if_name>\.` on
each interface variable — if the count is > 1 outside `<prefix>_dut_harness`,
flag as violation.

---

## 5. Bind Semantics

The single most common M1.1 skeleton bug is `bind` syntax. This section
codifies the correct forms and rejects the incorrect ones.

### 5.1 SV LRM 23.11 — bind scope is a TYPE

Formal grammar:

```
bind_directive     ::= bind bind_target_scope [: bind_target_instance_list]
                       bind_instantiation ;
bind_target_scope  ::= module_identifier | interface_identifier
bind_target_instance_list ::= bind_target_instance { , bind_target_instance }
```

Meaning:

- **Legal**: `bind <prefix>_ctrl_if <prefix>_ctrl_checker u_chk ();` — binds
  the checker module into every instance of interface type `<prefix>_ctrl_if`
- **Legal (instance-qualified)**: `bind <prefix>_ctrl_if : tb_top.ctrl_if_inst <prefix>_ctrl_checker u_chk ();`
  — same, but restricted to the named instance
- **ILLEGAL**: `bind ctrl <prefix>_ctrl_checker u_chk (...)` where `ctrl` is
  a **port** identifier (not a type). LRM violation — VCS will error.

### 5.2 Type-level bind vs instance-qualified bind

- **Type-level** — `bind <type> <mod> <inst> ();` — implicitly "every
  instance of `<type>`". Use for M1.1 skeleton where the checker is empty
  or per-instance behavior is uniform.
- **Instance-qualified** — `bind <type> : <inst_path> <mod> <inst> ();` —
  restricts to one instance. Use when the checker takes different
  parameter/port context per instance (e.g. per-lane assertion tuning).

### 5.3 Empty checker + type-level bind (M1.1 skeleton pattern)

Recommended for the skeleton stage — checker module is portless with empty
body:

```systemverilog
// sim/testbench/top/sva/<prefix>_ctrl_checker.sv
module <prefix>_ctrl_checker ();
  // Stage 3+ will add assertion bodies here.
  // Reachable signals: everything declared in <prefix>_ctrl_if
  // (bind places this module inside the interface's scope).
endmodule
```

```systemverilog
// Inside <prefix>_dut_harness
bind <prefix>_ctrl_if <prefix>_ctrl_checker u_ctrl_chk ();
```

In Stage 3, checker bodies can refer to `clk`, `rst_n`, and every other
signal declared inside `<prefix>_ctrl_if` as if declared locally — bind
places the module in the interface's scope. No port passing required.

### 5.4 Anti-pattern: `bind <port_name>` — will fail

Occasionally seen in design docs and legacy code:

```systemverilog
// Inside a module that has port `ctrl` of type <prefix>_ctrl_if:
bind ctrl <prefix>_ctrl_checker u_ctrl_chk (.ctrl_if(ctrl));  // ✗ LRM violation
```

`ctrl` is a port identifier, not a module or interface identifier. VCS will
error at compile time with a message referencing an invalid bind target.

**Fix**: switch to type-level bind — the checker becomes portless and the
bind statement targets the interface type:

```systemverilog
module <prefix>_ctrl_checker ();
endmodule

bind <prefix>_ctrl_if <prefix>_ctrl_checker u_ctrl_chk ();
```

### 5.5 Parameterized interfaces + type-level bind

`<prefix>_sram_if #(WIDTH=352)` (ws) and `<prefix>_sram_if #(WIDTH=256)`
(scale) are two instances of the **same** interface type `<prefix>_sram_if`.

- A single `bind <prefix>_sram_if <checker> u_x ();` binds into **both**
  instances
- If the checker needs to reason about the different WIDTHs, either
  parameterize the checker itself (`module <prefix>_sram_checker
  #(parameter int WIDTH = 352) (); ...`) and use two instance-qualified
  binds, or reference `$bits(rdata)` inside the checker body
- For M1.1 empty checker, no width dependence → single type-level bind is
  sufficient

### 5.6 Where to put bind statements

Convention: **all external protocol checker binds live in
`<prefix>_dut_harness.sv`**. Rationale:

- Keeps DUT-boundary assertions attached to the DUT-integration layer
- Avoids interleaving assertions with UVM env or tb_top setup
- One place to review "what's being enforced at the boundary"

**Internal design-intent checkers** (bound to DUT internal hierarchy —
FIFO state, FSM state, etc.) live separately in
`<prefix>_internal_checker.sv` (see §2.x when expanded). They're bound to
hierarchical paths inside the RTL, and only apply to the RTL variant.

---

## 6. Env Layer

*(Outline — expand in follow-up pass)*

- 6.1 `<prefix>_env_cfg` — single container for vif handles + api handle + knobs
- 6.2 tb_top calls `uvm_config_db#(env_cfg)::set` exactly once
- 6.3 `<prefix>_virtual_sequencer` — sub-sequencer handle holder only, no seq_item type
- 6.4 `<prefix>_scoreboard` / `<prefix>_cov_collector` — `uvm_component` with
  `uvm_analysis_imp` per analysis source (see §7 for suffix convention)
- 6.5 env `build_phase` creates children based on `cfg.enable_<x>_agent`; connect_phase
  wires up analysis ports (Milestone 1.5+)

---

## 7. `uvm_analysis_imp_decl` Convention

*(Outline — expand in follow-up pass)*

- 7.1 Macro placement: outside class body, inside enclosing package (before includes)
- 7.2 Suffix namespace convention:
  - Scoreboard uses `_config` / `_input` / `_output` / `_exception` / `_sram_<name>`
  - Cov collector uses `_cov_config` / `_cov_input` / ...
  - Any additional subscriber uses its own prefix suffix
- 7.3 Anti-pattern: reusing the same suffix across two components in the same package
  → duplicate class name → compile error

---

## 8. tb_top Thinness

*(Outline — expand in follow-up pass)*

- 8.1 Only 4 responsibilities: clock/interface instantiation, harness instantiation,
  env_cfg build + `uvm_config_db::set`, `run_test()`
- 8.2 Target line count: 100–200
- 8.3 Anti-patterns: tb_top referring to DUT port names, tb_top knowing DUT hierarchy,
  tb_top having `` `ifdef`` variant switches (belongs to `<prefix>_dut_select`)

---

## 9. clkrst_gen as SV Module

*(Outline — expand in follow-up pass)*

- 9.1 Rationale for SV module (not UVM agent): elab-order robustness — clock is
  running before UVM's build_phase, so early X-propagation checks pass
- 9.2 Drives `clk` via `<prefix>_ctrl_if.clkrst_gen` modport; leaves `rst_n` /
  DFT straps un-driven (harness_if owns them per §4.3)
- 9.3 Knobs (clk_period_ns, dft_icg_mode, ...) consumed from env_cfg via
  `uvm_config_db` in Milestone 1.2+; M1.1 skeleton just `initial clk = 1'b0`

---

## 10. M1.1 Skeleton Elab-Safety Rules

*(Outline — expand in follow-up pass)*

- 10.1 `run_test()` without `+UVM_TESTNAME` completes with a warning; `build_phase`
  never fires; `uvm_config_db::get` failures never trigger
- 10.2 Empty `run_phase` / `build_phase` bodies are acceptable — they don't execute
- 10.3 DUT status probes tied to `1'b0` — real bind probes deferred to M1.5
- 10.4 Elab must resolve: every referenced module name, every imported package,
  every interface modport passed at instantiation. Class internals (uvm_config_db
  lookups, string paths) are runtime concerns — not checked at elab

---

## 11. Anti-Pattern Catalog (quick reference)

*(Outline — expand in follow-up pass. Table format: Pattern | Why wrong | Correct alternative)*

- Interface `` `include`` inside package → LRM violation → separate `.sv` file in top/if/
- Interface `` `include`` after endpackage → cross-CU type mismatch → same as above
- `bind <port_name>` → LRM violation → `bind <interface_type>` (§5)
- Class API defined inside interface → cross-file type identity issues → class in package (LD12 B, §4.2)
- Multiple `assign` on same interface variable → driver race → single-source rule (§4.3)
- Non-unique `uvm_analysis_imp_decl` suffix → duplicate class → per-component suffix prefix (§7)
- rtl_wrap containing UVM code → tight coupling → rtl_wrap is pure port map (§4.1)
- tb_top referencing DUT hierarchy → variant-switch failure → tb_top thin, DUT knowledge in dut_harness (§8)
- Stage without runnable code — "empty skeleton" spanning multiple stages → roadmap forbids;
  every post-Stage-0 stage delivers real runnable code (see project AGENTS.md / roadmap conventions)

---

## Consumer notes

For skill developers (`add-harness-layer` and future Stage 1 modes):

- Read this file **before** generating any SV code
- Use §1.5 filelist template as the exact ordering; do not reorder to "look nicer"
- Use §5.3 bind pattern for M1.1 skeleton (empty portless checker + type-level bind);
  do not copy `bind <port_name>` from legacy docs
- When emitting `<prefix>_dut_harness.sv`, enforce §4.3 single-source rules — grep the
  generated harness for `assign <if>.<sig>` collisions before writing
- `.harness-config.json` provides `<prefix>` and DUT top module path; use these
  consistently throughout emitted code
