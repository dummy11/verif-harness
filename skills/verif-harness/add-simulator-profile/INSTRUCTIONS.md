# add-simulator-profile — explicit simulator capability profile

Generate a reviewable simulator profile and Makefile fragment from an explicit
JSON contract. This mode records commands and capabilities; it does not run the
simulator or claim that an unverified simulator is supported.

## Preconditions

- Read project `AGENTS.md`, simulator support documentation, compile flow, and
  existing Makefiles/filelists.
- Read `../references/implementation-patterns.md` completely.
- Confirm the command tokens contain no credentials, license values, internal
  hostnames, or absolute project paths.

## Procedure

1. Copy `simulator-profile.example.json` and replace every example value with
   reviewed project data.
2. Keep commands as token arrays. Supported placeholders are `{filelist}`,
   `{top}`, `{binary}`, `{seed}`, and `{test}`.
3. List required environment variable **names** only. Never store their values.
4. Run:

   ```bash
   python3 scripts/generate_profile.py \
     --spec simulator-profile.json \
     --profile-out sim/config/simulator-profile.json \
     --make-out sim/config/simulator-profile.mk
   ```

5. Review both outputs and run the real compile/smoke flow separately.
6. Record actual tool/version/log evidence before changing the support matrix.

## Boundaries

- The generator refuses unknown keys, unsafe tokens, secret-looking values,
  absolute paths, unsupported placeholders, and existing outputs.
- A generated profile means `CONFIGURED`, not `TESTED` or `SUPPORTED`.
- Never edit a live CI secret, license setting, or remote simulator service.
