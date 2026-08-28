# VCheck mode

VCheck runs automatically after structured writes. Use `check scan` or bare
`vcheck` for explicit CI/debug reconciliation. Record a spec, RTL, TB, or
evidence-source change with `record change --path ... --kind ...`. VCheck
propagates `STALE`/`REVALIDATION_REQUIRED` across Workstream relations and
preserves the causal event.

VCheck judges validity; it does not execute repairs, infer waivers, approve
plans, or modify DUT RTL.
