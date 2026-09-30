# VSTIM：激励代码方案与交付验收

VSTIM 沿用 VENV 的两阶段代码工作流，但验证对象是“必需场景能稳定生成并真正
到达 DUT 接收边界”，不是验证环境本身。按可独立实现、验证和失效的激励工作包
建立稳定 `implementation_key`，每包只有 `code-plan` 和 `code-deliverable` 两种
公开节点。

方案使用 `plan VSTIM --desired-file proposal.json`，至少依赖已验收的 `cap.doc`
和 `cap.venv`；同工作流包之间使用 `cap.vstim:<implementation_key>`。可以把当前
`cap.vreg:executor-ready` 作为运行入口依赖，但不得依赖 VCOV 结论或旧 VSTIM
工作节点。

每个包至少交付一项 `stimulus-implementation` 或 `corner-scenarios`，并同时提交：

- `reachability-evidence`：真实运行表明必需场景经过生成、驱动并到达 DUT 接收边界；
- `determinism-evidence`：相同测试、seed 和配置至少重放两次，激励摘要和必需场景一致。

两项运行结论使用 `StimulusReachabilityEvidence/1`，必须绑定当前代码、运行配置、
仿真日志、事务记录或波形分析以及工程 revision。coverage hit 只能作为旁证，不能
代替 DUT 输入边界观测。Main Agent 用 `code validate` 核对全部条件后再请负责人
验收；负责人验收后派生 `art.code`、包级 `cap.vstim` 和 claim 汇总 CAP。

