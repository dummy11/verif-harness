# Verification Closure Engine

The Verification Closure Engine runs automatically after plan review, evidence
updates, and consistency events. Use bare `closure`, or `closure evaluate
--workstream NAME`, to
inspect/recompute actions for CI or debugging. It compares desired/current
state globally and may route directly to any Workstream; it never imposes a
DOC→stimulus→checker→coverage→case→regression order.

An action declares executor `deterministic`, `reasoning`, or `human` and a
suggested capability. The closure engine decides what is needed but does not write code,
run a monolithic task list, or pretend to pause. Ask Human questions in the
live Agent conversation, then record evidence or decisions through structured
ingress.
