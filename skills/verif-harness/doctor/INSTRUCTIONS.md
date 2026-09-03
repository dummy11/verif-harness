# doctor mode

Run the native read-only v1 health audit:

```text
$verif-harness doctor
```

If the project is not bootstrapped, report `bootstrap` as the next mode. If the
model contains missing artifacts or open findings, run `inspect` and `closure`.
Doctor never edits DUT RTL, approves a Workstream, repairs evidence, or
silently creates project state.
