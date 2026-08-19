# xverif — deterministic CLI adapter

Use this mode when `verif-harness` has selected a concrete deterministic
operation provided by the xverif tool suite. The authoritative upstream is
`https://github.com/BLANK2077/xverif.git`. xverif is a repository of tool wrappers,
not one executable named `xverif`.

## Required reading

- Read project `AGENTS.md` and the verification documents it requires.
- Read `xverif-request.schema.json` and
  `../references/xverif-adapter-contract.md` completely.
- Read the selected tool reference in the upstream xverif repository before
  creating the request. Do not guess action names, arguments, schemas, output
  formats, environment requirements, or fallback behavior.

## Layering

```text
Codex / Kimi Code Agent
  -> verif-harness Skill/framework: intent, stage policy, Human boundaries
     -> xverif CLI adapter: validated argv, environment, timeout, evidence
        -> xverif tools/{xbit,xentry,xloc,xsva,xcov,xdebug,xwaveform}
```

The adapter never replaces project semantics or Human review. It only executes
one explicit request and records deterministic evidence.

## Procedure

1. In a complete verif-harness checkout, run
   `./scripts/setup.sh --with-xverif`. This reads `deps/xverif.lock.json`,
   installs the exact detached commit under `.deps/xverif`, and validates
   origin, clean state, MIT License hash, and wrappers. In a standalone Skill
   installation, identify an equivalent approved checkout and set
   `XVERIF_HOME` or pass `--xverif-root`.
2. Probe only the selected wrapper:

   ```bash
   python3 <skill-dir>/xverif/scripts/xverif_adapter.py probe \
     --tool xbit \
     --out /tmp/xverif-probe.json
   ```

   Probe PASS proves wrapper discovery and records its SHA-256 and Git identity;
   it does not prove EDA/runtime capability.
3. Copy `xverif-request.example.json`. Select one allowlisted tool, preserve its
   native argv exactly, name required environment variables without storing
   their values, and choose `json`, `xout`, or `text` from the native contract.
4. For xdebug/xcov/xentry JSON envelopes, prefer a project-relative
   `stdin_path`; do not put large or sensitive request bodies in argv.
5. Execute:

   ```bash
   python3 <skill-dir>/xverif/scripts/xverif_adapter.py run \
     --project-root . --request xverif-request.json \
     --out-dir artifacts/xverif/<unique-run-id>
   ```

6. Review `result.json`, `stdout.log`, `stderr.log`, the xverif Git commit,
   wrapper hash, completeness fields in native output, and all expected
   artifact hashes. Never infer PASS from process exit alone.

## Boundaries

- Allow only `xbit`, `xentry`, `xloc`, `xsva`, `xcov`, `xdebug`, and
  `xwaveform`; MCP/loop/admin wrappers are outside this one-shot CLI mode.
- Run with argv tokens and `shell=False`; do not accept a shell command string.
- Never auto-switch CLI/MCP, XOUT/JSON, local/LSF, backend, data source, or test
  level after failure.
- Preserve XOUT bytes exactly. Do not reverse-parse, reorder, re-encode, or add
  transport markers.
- Do not log environment values. License, scheduler, EDA, NPI, VDB, FSDB, and
  LSF availability remain deployment responsibilities.
- A fake wrapper validates adapter behavior only. Real support requires an
  approved xverif checkout and the selected tool's native tests/evidence.
- `PASS` is operation evidence, never Stage approval, waiver approval,
  verification closure, or freeze authorization.
- Never run `git pull` in `.deps/xverif`, vendor its source into verif-harness,
  or publish the managed checkout. Upgrade only by reviewing and changing the
  lock, reinstalling a clean checkout, and rerunning public and native tests.
