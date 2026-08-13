# Tool versions

| Tool | Supported baseline | Purpose |
| --- | --- | --- |
| Python | 3.9+ | Generators, audits, tests |
| GNU Make | 3.81+ | Local command entry points |
| Verilator | 5.x | Open example compile and run |
| UVM | IEEE 1800.2-compatible | Commercial simulator integration |
| VCS | User-validated | Full UVM integration target |

On Ubuntu, install the packaged Verilator with:

```bash
sudo apt-get update
sudo apt-get install verilator
```

Package versions vary by distribution. CI records `verilator --version` in
every run. Contributors should include exact tool versions with bug reports.
`./scripts/setup.sh --install-verilator` supports Homebrew and apt-based hosts.
