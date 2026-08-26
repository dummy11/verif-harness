# Agent runtime and model switching

verif-harness supports Codex and Kimi Code as Agent runtimes. Both runtimes use
the same Spec Kit specifications, Stage workflow, verif-harness modes,
artifacts, evidence contracts, and Human gates. Runtime selection changes only
the Agent integration and native Skill invocation.

## Runtime state

Spec Kit's `.specify/integration.json` is the sole runtime source of truth.
verif-harness does not create a second runtime configuration. The managed Spec
Kit dependency identity in `deps/spec-kit.lock.json` is independent of the
selected runtime.

| Runtime | Spec Kit key | Project Skill directory | Invocation |
| --- | --- | --- | --- |
| Codex | `codex` | `.agents/skills/` | `$verif-harness` |
| Kimi Code | `kimi` | `.kimi-code/skills/` | `/skill:verif-harness` |

The runtime key names the Agent surface, not the model. K3 is selected in Kimi
Code and is not written into `.harness-config.json` or Spec Kit specifications.

## Initialize a verification workspace

Keep the verif-harness package checkout, verification workspace, and RTL
directory separate. Run setup from the package checkout and pass the workspace
explicitly. Managed dependencies remain below the package's Git-ignored
`.deps/`; runtime config, the runtime-native Skill link, Spec Kit artifacts, and
verification outputs belong to the workspace. Stage 0 later records the RTL
root and DUT top file.

```bash
./scripts/setup --isolation managed --runtime codex \
  --workspace-root /path/to/verification-workspace
```

When `--runtime auto` is used, setup selects the only installed Agent CLI. If
both Codex and Kimi are installed, or neither is available, it stops and
requires an explicit choice. An existing `.specify/integration.json` remains
the authority for an already bootstrapped Spec Kit project; setup does not
rewrite that file implicitly.

For an empty workspace without a runtime marker, choose explicitly:

```bash
./scripts/setup --isolation managed --runtime kimi \
  --workspace-root /path/to/verification-workspace
```

After the CLI starts, invoke `$verif-harness` in Codex or
`/skill:verif-harness` in Kimi Code. The first project command is normally
`spec-kit bootstrap`; it installs the local RTL verification preset and records
the selected runtime in `.specify/integration.json`. It refuses an existing
`.specify/` project rather than replacing its specifications or integration
state.

After the CLI runtime starts, setup creates a read-only inventory turn listing
the Skills, MCP servers, and tools actually available to that session. Codex
uses its interactive initial prompt. Kimi runs the inventory with `--prompt`
and immediately opens that same latest session with `--continue`. The prompt
does not call tools or modify files. `/skills` and `/mcp` remain available for
the runtime-native live views.

If setup was run with `--no-agent`, start it later through setup again so the
Agent and xverif wrappers inherit the managed Python environment:

```bash
./scripts/setup --isolation managed --runtime codex \
  --workspace-root /path/to/verification-workspace
# or use --runtime kimi
```

Then invoke the runtime-native Skill inside that CLI. Starting the CLI from the
verif-harness package directory would make `.` refer to the package checkout,
not the verification workspace.

For dependency-only automation, use `./scripts/setup --no-agent`; with runtime
`auto`, one uniquely discovered Agent CLI is configured, while no discovered
CLI skips workspace configuration. Both paths still install and verify Spec
Kit, xverif CLI/MCP, `mcp[cli]`, and WavePeek.
To configure the project Skill and xverif MCP registration without launching an
Agent, also pass explicit `--runtime codex|kimi` and `--workspace-root <path>`.

`--isolation managed` is currently the only implemented dependency backend and
the default. It exports the managed interpreter to xverif wrappers before the
Agent starts. Apptainer, Docker, and Podman are not silently selected or used
as fallbacks.

Inspect the result without changing the project:

```bash
python3 scripts/verif_harness.py runtime status --project-root .
```

## Change the model within one runtime

Changing a model does not require a Spec Kit integration switch. For example,
selecting K3 inside Kimi Code leaves the runtime key as `kimi`.

Use this sequence:

1. Stop at a Spec Kit review gate; do not change models during a running step.
2. Record the workflow run ID and inspect `workflow-status`.
3. Select the new model through the Agent runtime's documented configuration.
4. Run `runtime status` and `$verif-harness doctor` or
   `/skill:verif-harness doctor`.
5. Resume the same reviewed workflow. Do not regenerate approved
   specifications, tasks, evidence, or approval records merely because the
   model changed.

After a frozen or reviewed baseline, record any resulting repository change
through `change-control`. A model change is not a waiver and does not invalidate
or approve verification evidence by itself.

## Switch between Codex and Kimi Code

Use setup once for the target runtime, then switch only from a stable review
gate with no command step running:

```bash
python3 scripts/verif_harness.py workflow-status --project-root .
python3 scripts/verif_harness.py runtime status --project-root .
python3 scripts/verif_harness.py runtime switch --project-root . --to kimi
python3 scripts/verif_harness.py runtime status --project-root .
```

The switch delegates to the pinned Spec Kit `integration switch` command. Spec
Kit updates its default integration, runtime-native skills, shared command
references, and installed preset artifacts. verif-harness then rereads
`.specify/integration.json` and fails if the requested runtime was not made
active.

Spec Kit preserves locally modified managed files and may block the switch for
Human reconciliation. verif-harness never adds `--force` automatically. Do not
delete the previous runtime directory or edit `.specify/integration.json` by
hand to bypass that protection.

After switching, run the runtime-native `doctor`, inspect the paused workflow,
and resume its existing run. The switch must not create a new specification
authority, duplicate a task, rerun a completed mode, or rewrite evidence and
approval history.

## Recovery

- Multiple runtime markers: pass `--integration codex` or `--integration kimi`
  during new-project bootstrap. For an existing project, trust the recorded
  `.specify/integration.json` state.
- Missing runtime state: do not synthesize the JSON file. Restore the reviewed
  Spec Kit project or re-run an authorized bootstrap for a genuinely new
  project.
- Unsupported active integration: verif-harness fails closed. Switch to Codex
  or Kimi Code through Spec Kit before running the Stage workflow.
- Modified managed Skill files: review the diff. Preserve Human changes or
  reconcile them explicitly before retrying the switch.
