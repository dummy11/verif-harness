# Verification Consistency Engine

The Verification Consistency Engine runs automatically after structured writes. Use bare `check`
for explicit CI/debug reconciliation. Record a spec, RTL, TB, or evidence-source
change with `changed PATH`; use `record change --path ... --kind ...` only when
automation must provide an exact kind or revision. The consistency engine
propagates `STALE`/`REVALIDATION_REQUIRED` across Workstream relations and
preserves the causal event.

It judges validity; it does not execute repairs, infer waivers, approve
plans, or modify DUT RTL.
