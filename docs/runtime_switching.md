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

Install the verif-harness Skill at exactly one runtime-native project path,
then bootstrap with automatic detection:

```bash
python3 .tools/verif-harness/scripts/verif_harness.py spec-kit bootstrap \
  --project-root . --integration auto
```

`auto` resolves in this order:

1. an existing `.specify/integration.json` record;
2. exactly one project marker: `.agents/` or `.codex/` for Codex, or
   `.kimi-code/` for Kimi Code;
3. otherwise it stops and requires an explicit choice.

For an empty project without a runtime marker, choose explicitly:

```bash
python3 .tools/verif-harness/scripts/verif_harness.py spec-kit bootstrap \
  --project-root . --integration kimi
```

Bootstrap passes the resolved integration to Spec Kit, installs the local RTL
verification preset, and verifies that `.specify/integration.json` records the
same runtime. It refuses an existing `.specify/` project rather than replacing
its specifications or integration state.

`--ignore-agent-tools` exists only for CI and scaffold validation on hosts that
do not install either Agent CLI. Normal bootstrap must omit it so a missing
Codex or Kimi Code executable is reported before project initialization.

Inspect the result without changing the project:

```bash
python3 .tools/verif-harness/scripts/verif_harness.py runtime status \
  --project-root .
```

## Change the model within one runtime

Changing a model does not require a Spec Kit integration switch. For example,
selecting K3 inside Kimi Code leaves the runtime key as `kimi`.

Use this sequence:

1. Stop at a Spec Kit review gate; do not change models during a running step.
2. Record the workflow run ID and inspect `spec-kit status`.
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

First install the same verif-harness Skill at the target runtime path. Then
switch only from a stable review gate with no command step running:

```bash
python3 .tools/verif-harness/scripts/verif_harness.py spec-kit status \
  --project-root .
python3 .tools/verif-harness/scripts/verif_harness.py runtime status \
  --project-root .
python3 .tools/verif-harness/scripts/verif_harness.py runtime switch \
  --project-root . --to kimi
python3 .tools/verif-harness/scripts/verif_harness.py runtime status \
  --project-root .
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
