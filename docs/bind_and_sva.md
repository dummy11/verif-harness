# Bind and SVA

Assertions should have stable plan identifiers, explicit clocks, reset-disable
semantics, actionable failure messages, and cover properties when engagement
matters.

Keep checker modules separate from DUT RTL and attach them through a reviewed
bind file. Compile assertion modules before bind statements and ensure the bind
target is stable for each supported DUT variant.

An empty or unresolved property remains a TODO and is not counted as assertion
coverage. A zero-error run does not prove assertions were compiled or engaged;
archive elaboration and coverage evidence when claiming assertion closure.
