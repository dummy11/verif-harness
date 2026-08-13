# Interface guidelines

- Declare each interface once in a dedicated `.sv` file.
- Use modports to express driver, monitor, DUT, and clock/reset directions.
- Keep protocol signal names stable and adapter logic outside reusable UVCs.
- Parameterize widths only when the protocol contract requires it.
- Avoid embedding assertions with unrelated ownership; bind dedicated checkers.
- Do not include interfaces inside packages.
- Sample monitor-visible signals through a documented clocking convention.

An interface is a structural protocol boundary, not a place for scenario policy
or scoreboard behavior.
