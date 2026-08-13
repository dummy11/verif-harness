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
