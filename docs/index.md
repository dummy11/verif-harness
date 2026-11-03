# verif-harness documentation

verif-harness is a reusable SystemVerilog/UVM DUT integration harness with a
continuous Codex- or Kimi-assisted verification engineering control plane.

## Start here

- [Install v3 and select project versions](installation.md): shared user/system
  installation, pinned NSIM, project bootstrap, migration, restart and switch.
- [verif-harness 3.0.0 release](releases/3.0.0.md)
- [Harness design](harness_design.md)
- [V1 control plane](control_plane.md)
- [DUT integration](dut_integration.md)
- [Compile flow](compile_flow.md)
- [Simulator support](simulator_support.md)
- [Agent Skill modes](skill_modes.md)
- [Runtime permissions](runtime_permissions.md)
- [xverif integration](xverif_integration.md)
- [WavePeek integration](wavepeek_integration.md)
- [Troubleshooting](troubleshooting.md)

The executable example is documented in `examples/simple_fifo/README.md` at
the repository root.

Install a tool version once, bootstrap each new project, then use
`verif-harness restart` from that project or a subdirectory to continue work.
Installing another version does not upgrade existing projects. Source-checkout
`scripts/setup` commands elsewhere in these docs are contributor instructions;
released installations use the v3 installation guide.
