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

VDOC 的 8 份实际文档共用 `verification-doc-authoring` engine 和结构化 schema，
每份文档只保留一个 profile。Engine 把当前 RTL/spec/document digest、DUT-specific
事实和 source gaps 写入 `*_authoring` 节点；profile 依赖和正文验收依赖进入同一图，
由现有 change propagation 失效，而不是复制 8 套 Skill 或生成通用正文模板。
