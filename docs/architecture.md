# Architecture summary

The harness is the only layer that owns structural DUT integration. It sits
between verification behavior and read-only RTL.

```text
UVM test and environment
          |
    virtual interfaces
          |
       harness
     /    |    \
 interface DUT SVA/bind
```

The canonical architecture contract is in the root-level `ARCHITECTURE.md`.

At control-plane level, VPlan defines desired state, VModel stores facts,
VCheck propagates change invalidation, VClosure selects minimum next actions,
and VReason handles only ambiguity. Workstreams are parallel, re-entrant
governance contexts rather than lifecycle stages.
