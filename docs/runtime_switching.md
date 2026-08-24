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

## Bootstrap a new project

Run setup from the cloned verif-harness checkout. It installs all managed
dependencies, creates the selected runtime-native Skill link, and immediately
starts the selected Agent CLI:

```bash
./scripts/setup.sh --runtime codex
```

When `--runtime auto` is used, setup resolves the CLI in this order:

1. an existing `.specify/integration.json` record;
2. exactly one project marker: `.agents/` or `.codex/` for Codex, or
   `.kimi-code/` for Kimi Code;
3. otherwise it stops and requires an explicit choice.

For an empty project without a runtime marker, choose explicitly:

```bash
./scripts/setup.sh --runtime kimi
```

After the CLI starts, invoke `$verif-harness` in Codex or
`/skill:verif-harness` in Kimi Code. The first project command is normally
`spec-kit bootstrap`; it installs the local RTL verification preset and records
the selected runtime in `.specify/integration.json`. It refuses an existing
`.specify/` project rather than replacing its specifications or integration
state.

For dependency-only automation, use `./scripts/setup.sh --no-agent`; this skips
the final CLI launch but still installs and verifies Spec Kit, xverif CLI/MCP,
`mcp[cli]`, and WavePeek.

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
