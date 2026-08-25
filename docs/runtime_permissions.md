# Runtime permissions

verif-harness supports Codex and Kimi Code as equivalent Agent runtimes. Both
use the same Skill modes, repository instructions, evidence contracts, and
Human approval boundaries. The runtime changes only the native Skill spelling:

```text
Codex      $verif-harness <mode>
Kimi Code  /skill:verif-harness <mode>
```

## What verif-harness controls

The repository controls which files and commands its modes are allowed to
touch. Write modes must keep DUT RTL read-only, preserve reviewed decisions,
and fail closed on ambiguous state. `setup.sh` installs dependencies and the
runtime-native Skill link, but it never writes Codex or Kimi user settings.

The intended command policy is:

| Operation | Policy |
| --- | --- |
| Read or edit files below the workspace root | Allow within the sandbox |
| `git status`, `diff`, `log`, `show`, `branch` | Allow |
| `git add`, local `commit`, `switch` | Allow after the requested change is reviewed |
| `make`, Python tests, Verilator, VCS, xverif, WavePeek | Allow when declared by the project workflow |
| `git fetch` | Allow when needed for repository inspection |
| `git push` | Keep as a separately authorized remote mutation |
| `git reset --hard`, `git clean -fd[x]`, force push | Block |
| Writes outside the approved workspace root | Block |

This policy is guidance for the Agent host; it is not a replacement for the
host sandbox or approval engine.

## Codex

This repository includes an opt-in project-scoped Codex configuration at
`.codex/config.toml` and destructive-command rules at
`.codex/rules/default.rules`. Codex loads these files only after the project is
trusted. They affect this checkout and do not modify `~/.codex`.

The controlled profile is:

```toml
approval_policy = "never"
sandbox_mode = "workspace-write"
```

The active workspace is the writable root, so the project file does not embed a
machine-specific absolute path.

If command rules are enabled by the installed version, allow routine build,
test, and local Git prefixes, while blocking destructive Git prefixes. Keep
remote `push` separate unless it has an explicit project-level authorization.

The project rules block hard reset, destructive clean, and force-push variants.
Validate field names and enum values against the local Codex schema when the
installed Codex version changes.

## Kimi Code

Kimi Code uses its own sandbox, approval, and command-policy configuration. Do
not copy Codex TOML or assume that Codex `prefix_rule` syntax is accepted by
Kimi. Apply the same policy table above through Kimi's documented native
settings, keeping the workspace root as the only writable workspace whenever
possible.

For Kimi projects, setup creates the project-local Kimi file and Skill entry at:

```text
.kimi-code/local.toml
.kimi-code/skills/verif-harness
```

`local.toml` contains only Kimi Code's currently supported project-local
workspace schema (`[workspace] additional_dir = []`). Setup never writes
`~/.kimi-code/config.toml` and never copies Codex TOML into the Kimi directory.
Kimi's no-ask startup is selected by passing its native `--yolo` flag. Kimi
permission rules are host-level in the current Kimi Code release, so the
project file cannot claim to enforce the destructive-Git denylist. Keep that
denylist in the Kimi host policy (or an equivalent wrapper) when operating
outside Codex.

Invoke it with `/skill:verif-harness <mode>`. Selecting K3 or another Kimi
model does not change the runtime key, specification artifacts, evidence, or
approval records.

## Runtime setup

Keep the package checkout, verification workspace, and RTL directory separate.
Choose the workspace and runtime explicitly:

```bash
./scripts/setup --runtime codex --workspace-root /path/to/verification-workspace
./scripts/setup --runtime kimi --workspace-root /path/to/verification-workspace
```

The setup workspace is not the RTL root. Stage 0 asks for and records the RTL
root and DUT top file in `.harness-config.json`; those paths may be workspace
relative or explicitly reviewed external paths.

The selected runtime determines both the project configuration and launch
arguments: Codex requires `.codex/config.toml` and starts without extra flags;
Kimi creates/uses `.kimi-code/local.toml` and starts as `kimi --yolo`. These
files are written below the selected workspace, while managed dependencies
remain below the verif-harness package checkout. Neither path changes a
user-level configuration file.

Use `--no-agent` for dependency-only CI setup. Runtime switching is performed
at a stable review gate and is recorded by Spec Kit; it does not copy private
host configuration between Codex and Kimi.
