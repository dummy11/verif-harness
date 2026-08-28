# V1 control plane

The v1 control plane uses five cooperating subsystems: VPlan, VModel, VCheck,
VClosure, and VReason. See the [mode catalog](skill_modes.md) for commands and
the [architecture summary](architecture.md) for authority boundaries.

There is no long-lived workflow worker. The Agent remains in the foreground for
questions; deterministic commands are short-lived and persist their result
before returning.
