# Repository instructions

## Scope

This repository contains public, reusable verification infrastructure.

- Keep `examples/*/rtl/` small, license-free, and self-contained.
- Never import proprietary DUT RTL, specifications, logs, vectors, URLs,
  license configuration, or scheduler settings.
- Keep harness, interfaces, assertions, bind, UVM, and test responsibilities
  layered as described in `ARCHITECTURE.md`.
- Treat generated files as review candidates, not approved semantics.
- Do not claim simulator support without reproducible evidence.
- Keep optional xverif source under Git-ignored `.deps/`; never vendor it or
  publish proprietary EDA dependencies. Treat its lock changes as reviewed
  dependency upgrades and preserve separate licensing/ownership.
- Keep optional WavePeek source and binaries under Git-ignored `.deps/`; pin
  source, Cargo.lock, license, and version, keep FSDB disabled by default, and
  preserve WavePeek's separate Apache-2.0 ownership and release boundary.

## Product and interaction principles

- verif-harness 是面向 ASIC 验证工程师的验证控制面，不是通用项目管理、
  任务管理或审批系统。这里可复用的是 ASIC 验证控制能力，不是与验证对象
  无关的通用工作流模板。
- 工作流、工作节点、状态、进度、操作和退出条件必须对应当前被验证设计
  （DUT）、接口、功能、验证点、测试场景、检查机制、覆盖目标或验证证据。
  不同 DUT 可以具有不同的工作流结构、节点类型、节点数量、依赖和完成条件；
  不得默认套用固定的通用项目模板。
- 面向用户的文字应优先说明“验证什么、当前结论、依据是什么、还缺什么、
  谁需要处理”。使用已有的 ASIC 验证术语，不机械翻译英文，不自行创造术语；
  没有通行中文名称时保留标准英文，并在首次出现时说明含义。
- 主要页面和操作必须让不是 ASIC 验证工程师的用户也能理解当前对象、状态、
  依据和下一步。内部编号、schema、digest、数据库状态码和工具字段放在详情或
  审计信息中，不作为主要界面语言。

## Required checks

Before committing, run:

```bash
make check
```

Before a public release candidate, run:

```bash
make release-check
```

Do not weaken the denylist or exclusion rules merely to make an audit pass.
