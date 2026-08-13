# Contributing

Thank you for improving verif-harness.

## Before opening a change

1. Search existing issues.
2. Keep the change focused on reusable, public verification infrastructure.
3. Do not include proprietary RTL, specifications, vectors, logs, internal
   names, paths, URLs, credentials, license servers, or scheduler settings.
4. Add tests for generator or checker behavior.
5. Document simulator-specific behavior without claiming untested support.

## Development checks

```bash
./scripts/setup.sh
make check
```

Run `make example` when Verilator is available. Run `make release-check` for
changes that affect packaging or public content.

## Pull requests

Explain the problem, architecture impact, validation performed, and whether
the change touches templates, simulator behavior, or the bundled Codex skill.
All Human decisions and semantic assumptions must remain explicit.

By contributing, you agree that your contribution is licensed under the
Apache License 2.0 applicable to this repository.
