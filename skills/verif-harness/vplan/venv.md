# VENV：代码实现方案与交付验收

先读取当前项目、VDOC 已验收文档和实际 DUT 输入，再按接口、时钟复位域、组件、
连接关系、观测路径和集成配置划分工作包。不是固定六个节点，也不是整个 VENV
只有两个节点。每个工作包有稳定的 `implementation_key` 和两种公开工作节点：

```text
code-plan → 负责人批准 → art.code_plan
  → code-deliverable：Agent 实现、构建、验证并分析结果
  → 负责人验收当前代码及验证证据 → art.code → cap.venv
```

## 方案

使用 `plan VENV --desired-file proposal.json`。proposal 仍为
`DesiredStateProposal/1`，但 VENV 只接受 `code-plan`。方案批准后由控制面建立对应
交付节点，不把两阶段混在一次审批里。不同工作包可以按明确依赖分别推进。
没有 `--desired-file` 时只建立等待 Agent 规划的空方案，不再生成旧式默认节点。
已经采用新模型的项目会返回当前方案，不会因重复执行命令清空节点或重启审批。

每个节点包含：

| 字段 | 面向负责人展示 |
| --- | --- |
| statement | 目标 |
| scope | 工作范围 |
| work_content | 具体工作 |
| implementation_approach | 实现方式 |
| validation_methods | 如何验证 |
| deliverables | 输出 |
| acceptance_criteria | 交付条件 |

另外登记 `key`、`title`、`role`、`implementation_key`、`required`、`source_refs`、
`input_files`、`inputs`、`output_paths`、`capabilities`。
`implementation_key` 例如 `interface:axi0` 或 `integration:vcs-default`。
`input_files` 是内部逐文件来源，必须实际存在；`output_paths` 是验证输出目录内
的明确文件清单，不允许只读 DUT、控制面目录、整个项目或相互重叠的工作包范围。
输入依据默认折叠，代码只展示去重后的目录，文档逐一列出。

`inputs` 至少引用一项 `cap.doc:<document_key>`，也可引用其他工作包的
`cap.venv:<implementation_key>`，不得直接引用旧工作节点或未验收文档产物。
依赖必须无环。`capabilities` 列出需要现有 VENV 专用证据验证的 claim，例如
`interface-ready`、`build-ready`、`run-ready` 或 `environment-smoke-evidence`。
集成交付必须按批准范围包含构建、运行配置和 smoke 所需代码及证据，不能只提交
一个 PASS 标签。不要把不具备的工具运行结果写成已验证。

方案不列“待确认问题”。识别到歧义时，由 Main Agent 绑定当前节点提问，并保存
等待记录。不能自行把观测到的 RTL 行为当作已确认需求。

## 实现与验证

批准方案后，先 `code status NODE` 读取交付节点的当前 `input_signature`、
`revision` 和 `code_files`。所有实现和工具 Activity 绑定这个交付节点。
完成实现后重新读取，使用真实工具结果组织 `CodeValidation/1`：

- `node_id`、`revision`、`input_signature` 绑定当前交付；
- `code_files` 精确复制当前输出清单及摘要；
- `checked_by` 为 `Project Main Agent`，`summary` 写明实际检查结论；
- `checks` 逐项覆盖全部 `acceptance_criteria`，每项有 `criterion`、`method`、
  `expected`、`actual`、`report` 和 `claim`；
- `report` 引用项目内的真实 `EnvironmentEvidence/1`，其 native artifacts、
  当前工程版本和所需工具分析报告仍按已有证据规则核对。
  每个条件可有多项检查；原始报告必须直接引用全部当前交付代码或配置文件。
  smoke 和 build 必须在同一集成工作包提交，并使用相同的环境版本。

执行 `code validate NODE report.json` 登记。它只检查已有证据，不运行仿真，也不
代替负责人批准。失败或证据过期时继续修复并验证；通过后才提交负责人验收。
负责人提出修改后，处理意见、修改、重新验证，再请负责人审查。批准后仅由系统
核对版本和证据未变化，不再要求一轮常规 Agent 验收后检查。

`code artifacts` 查看批准方案、验收交付和历史版本。包级 CAP 不要求其他无关
工作包完成。`cap.venv:<claim>` 是默认下游依赖使用的保守汇总，只有提供该 claim
的全部必需工作包都验收通过才有效。需要区分接口或构建配置时使用包级 CAP。

## 变更与旧项目

方案或上游输入变化后重提方案；只改代码或证据时保留未变化方案，在同一交付
节点重新登记验证和验收。任何审批意见都会使该节点旧批准失效。
旧 VENV 数据不会被删除；提交新代码方案后，原节点保留为历史，旧批准不继承。
已知的旧 capability 依赖映射到派生 CAP；不能确定归属的旧依赖保持阻塞，由
Main Agent 重新规划，不猜测工作包归属。先备份项目 `.verif-harness` 再升级。
