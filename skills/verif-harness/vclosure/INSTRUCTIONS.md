# VClosure mode

VClosure runs automatically after VPlan review, evidence updates, and VCheck
events. Use `closure evaluate [--workstream NAME]` or bare `vclosure` to
inspect/recompute actions for CI or debugging. It compares desired/current
state globally and may route directly to any Workstream; it never imposes a
DOC→stimulus→checker→coverage→case→regression order.

An action declares executor `deterministic`, `reasoning`, or `human` and a
suggested capability. VClosure decides what is needed but does not write code,
run a monolithic task list, or pretend to pause. Ask Human questions in the
live Agent conversation, then record evidence or decisions through structured
ingress.
