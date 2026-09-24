"""Command-line interface for the verif-harness v1 control plane."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

from .store import (
    ACTIVITY_STATUSES, AGENT_ASSIGNMENT_PHASES, AGENT_QUESTION_STATUSES,
    DOCUMENT_ITEM_KINDS, DOCUMENT_ITEM_STATUSES,
    HUMAN_ACTIONS, HUMAN_ACTION_STATUSES, HarnessError, ProjectStore, Validity,
    PROJECT_AGENT_ACTOR, VERIFICATION_AGENT_ROLES, WORKSTREAM_TEMPLATES,
    capabilities,
)


ALIASES = {
    "vplan": "plan", "vmodel": "model", "vcheck": "check",
    "vclosure": "closure", "vreason": "reason",
    "waveform": "wavepeek", "subagent": "agent-work",
}
ROLES = VERIFICATION_AGENT_ROLES


def emit(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def project_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", type=Path, default=Path.cwd())


def workstream_argument(parser: argparse.ArgumentParser, required: bool = True) -> None:
    parser.add_argument("--workstream", choices=tuple(WORKSTREAM_TEMPLATES), type=str.upper, required=required)


def bootstrap_dashboard_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("dashboard port 必须是整数") from exc
    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError("bootstrap dashboard port 必须在 1..65535")
    return port


def reviewer_identity(root: Path, explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    configured = subprocess.run(
        ["git", "-C", str(root), "config", "user.name"], check=False,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    ).stdout.strip()
    identity = configured or os.environ.get("GIT_AUTHOR_NAME", "").strip() or os.environ.get("USER", "").strip()
    if not identity:
        raise HarnessError("无法推导 reviewer；请配置 git user.name 或显式传 --reviewer")
    return identity


def infer_workstream(store: ProjectStore, explicit: str | None, operation: str) -> str:
    if explicit:
        return explicit
    plans = store.workstreams()
    if operation == "review":
        candidates = [item["workstream"] for item in plans if item["lifecycle"] in {"REVIEW", "REVISE"}]
    else:
        candidates = [
            item["workstream"] for item in plans
            if item["lifecycle"] in {"ACTIVE", "SATISFIED"}
            and store.evaluate_closure(item["workstream"], persist=False)["ready"]
        ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise HarnessError(f"没有可执行 {operation} 的 Workstream")
    raise HarnessError(f"存在多个候选 Workstream：{', '.join(candidates)}；请显式指定")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verif-harness",
        description="以 Verification Knowledge Model 为治理状态事实源的持续 RTL verification control plane",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""常用命令：
  verif-harness bootstrap
  verif-harness plan authoring --output .verif-harness/proposals/vdoc-authoring.json
  verif-harness plan VDOC
  verif-harness review [VDOC]
  verif-harness status [VDOC]
  verif-harness docs status [DOCUMENT]
  verif-harness docs render [DOCUMENT]
  verif-harness inspect [NODE]
  verif-harness trace NODE
  verif-harness impact NODE
  verif-harness prove NODE FILE
  verif-harness evidence NODE FILE
  verif-harness reachability NODE FILE
  verif-harness changed PATH
  verif-harness freeze VDOC|final
  verif-harness dashboard --open-browser
  verif-harness agent-work candidates
  verif-harness agent-question ask NODE --prompt TEXT --option ID LABEL DESCRIPTION
  verif-harness agent-review-check list --status PENDING
  verif-harness await-human VDOC

完整操作与参数见 skills/verif-harness/docs/user_guide.md。""",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    bootstrap = commands.add_parser("bootstrap", help="根据明确的 DUT 输入建立最小验证控制状态；不生成验证文档或验证内容")
    project_argument(bootstrap)
    bootstrap.add_argument("--project-name")
    bootstrap.add_argument("--runtime", choices=("auto", "codex", "kimi", "claude", "none"), default="auto")
    bootstrap.add_argument("--rtl-root", action="append", default=[],
                           help="只读 RTL 根目录；可重复，也可显式位于 project root 外")
    docs_input = bootstrap.add_mutually_exclusive_group()
    docs_input.add_argument("--docs-root", action="append", default=[],
                            help="可选只读 RTL spec 文件或目录；可重复，也可位于 project root 外")
    docs_input.add_argument("--clear-docs-root", action="store_true",
                            help="refresh 时明确清除已有 RTL spec 输入")
    bootstrap.add_argument("--verif-root", help="project root 内的验证资产输出根目录")
    testbench_input = bootstrap.add_mutually_exclusive_group()
    testbench_input.add_argument(
        "--testbench-root",
        help="可选的已有 testbench 根目录；只登记和读取，不表示已通过验证",
    )
    testbench_input.add_argument(
        "--clear-testbench-root", action="store_true",
        help="refresh 时明确移除以前登记的 testbench 目录",
    )
    reference_model_input = bootstrap.add_mutually_exclusive_group()
    reference_model_input.add_argument(
        "--reference-model", "--gold-model", dest="reference_model",
        help="可选的 reference/golden model 文件或目录；只登记，不执行",
    )
    reference_model_input.add_argument(
        "--clear-reference-model", action="store_true",
        help="refresh 时明确移除以前登记的参考模型",
    )
    verification_script_input = bootstrap.add_mutually_exclusive_group()
    verification_script_input.add_argument(
        "--verification-script", action="append", default=[],
        help="可选的编译、仿真或回归入口脚本；可重复",
    )
    verification_script_input.add_argument(
        "--clear-verification-scripts", action="store_true",
        help="refresh 时明确移除以前登记的验证脚本",
    )
    bootstrap.add_argument("--dut-top")
    bootstrap.add_argument("--dut-top-file", help="属于某个 --rtl-root 的 DUT top 文件")
    bootstrap.add_argument(
        "--refresh", action="store_true",
        help="重新配置；未提供其他参数时只返回等待负责人确认的问题，不写入配置",
    )
    bootstrap_dashboard = bootstrap.add_mutually_exclusive_group()
    bootstrap_dashboard.add_argument(
        "--dashboard", dest="force_dashboard", action="store_true",
        help="即使当前不是交互终端，也在 bootstrap 完成后启动或复用后台 Dashboard",
    )
    bootstrap_dashboard.add_argument(
        "--no-dashboard", action="store_true",
        help="bootstrap 完成后不启动 Dashboard",
    )
    bootstrap.add_argument(
        "--dashboard-port", type=bootstrap_dashboard_port,
        help="显式指定 Dashboard 端口；默认从 8765 起为当前系统账号自动选择并复用",
    )

    status = commands.add_parser("status", help="显示全局模型、Workstream 与自动 closure 摘要")
    project_argument(status)
    status.add_argument("workstream", nargs="?", choices=tuple(WORKSTREAM_TEMPLATES), type=str.upper)

    dashboard = commands.add_parser("dashboard", help="在固定端口注册、检查或注销项目 Dashboard")
    project_argument(dashboard)
    dashboard.add_argument("--host", help="仅允许 loopback host；默认读取运行记录或使用 127.0.0.1")
    dashboard.add_argument(
        "--port", type=int,
        help="显式指定端口；默认读取运行记录，或从 8765 起为当前系统账号自动选择",
    )
    dashboard.add_argument("--open-browser", action="store_true")
    dashboard_mode = dashboard.add_mutually_exclusive_group()
    dashboard_mode.add_argument(
        "--status", action="store_true", help="检查后台 Dashboard 状态后退出",
    )
    dashboard_mode.add_argument(
        "--stop", action="store_true",
        help="从共享 Dashboard 注销当前项目；最后一个项目注销后停止服务",
    )
    dashboard_mode.add_argument(
        "--snapshot", action="store_true", help="输出 Dashboard JSON 后退出，不启动服务",
    )
    dashboard_mode.add_argument(
        "--foreground", action="store_true", help="前台运行服务；仅用于调试和后台启动器内部",
    )

    plan = commands.add_parser("plan", help="Verification Planner：使用 plan WORKSTREAM 形成/修订 desired state")
    plan_commands = plan.add_subparsers(dest="plan_command", required=True)
    design = plan_commands.add_parser("design", help="设计或修订一个可重入 Workstream")
    project_argument(design); workstream_argument(design)
    design.add_argument("--objective")
    design.add_argument("--desired", action="append", default=[])
    design.add_argument(
        "--evidence-claim", action="append", default=[],
        help="与自定义 --desired 一一对应的专用 evidence claim",
    )
    design.add_argument("--exit", dest="exit_criteria", action="append", default=[])
    design.add_argument("--decision", action="append", default=[])
    design.add_argument("--document-root", help="VDOC 文档输出目录；由 Agent 在对话确认后传入")
    design.add_argument(
        "--desired-file",
        help="供 Agent 和负责人评审的 DesiredStateProposal/1 JSON；在模板汇总节点下追加项目级子节点",
    )
    authoring = plan_commands.add_parser(
        "authoring",
        help="从当前 DUT RTL/spec 和已有验证文档生成结构化 VDOC 撰写方案候选",
    )
    project_argument(authoring)
    authoring.add_argument(
        "--document", action="append", default=[],
        help="生成指定 document_key；可重复，省略时生成 registry 中全部八份文档",
    )
    authoring.add_argument(
        "--output",
        help="把候选 proposal 写入项目内路径；省略时直接输出 DesiredStateProposal/1",
    )
    show = plan_commands.add_parser("show", help="显示当前 Workstream plan")
    project_argument(show); workstream_argument(show)
    review = plan_commands.add_parser("review", help="记录负责人对当前工作流方案版本的评审结论")
    project_argument(review); workstream_argument(review, required=False)
    review.add_argument("--verdict", choices=("approve", "reject", "modify", "clarify"), default="approve")
    review.add_argument("--reviewer"); review.add_argument("--reason")
    freeze = plan_commands.add_parser("freeze", help="冻结 Workstream 或最终不可变 baseline")
    project_argument(freeze); workstream_argument(freeze, required=False)
    freeze.add_argument("--final", action="store_true")
    freeze.add_argument("--reviewer"); freeze.add_argument("--reason")

    inspect = commands.add_parser("inspect", help="查看全部验证知识或一个 node")
    project_argument(inspect); inspect.add_argument("node_id", nargs="?")
    direct_trace = commands.add_parser("trace", help="查看 node 的依赖、finding 与 evidence")
    project_argument(direct_trace); direct_trace.add_argument("node_id")
    direct_impact = commands.add_parser("impact", help="查看 node 的下游依赖影响")
    project_argument(direct_impact); direct_impact.add_argument("node_id")

    record = commands.add_parser("record", help="结构化事实入口；写入后自动运行 consistency/closure engines")
    record_commands = record.add_subparsers(dest="record_command", required=True)
    node = record_commands.add_parser("node"); project_argument(node)
    node.add_argument("node_id"); node.add_argument("--type", dest="node_type", required=True)
    node.add_argument("--title", required=True); workstream_argument(node, required=False)
    node.add_argument("--status", choices=[item.value for item in Validity], default=Validity.UNKNOWN.value)
    edge = record_commands.add_parser("edge"); project_argument(edge)
    edge.add_argument("source"); edge.add_argument("target"); edge.add_argument("--relation", required=True)
    edge.add_argument("--origin", choices=("explicit", "inferred", "runtime"), default="explicit")
    edge.add_argument("--confidence", type=float, default=1.0)
    dependency = record_commands.add_parser("dependency", help="登记 node 级依赖；不会等待整个 Workstream")
    project_argument(dependency)
    dependency.add_argument("subject", help="被阻塞的 dependent node")
    dependency.add_argument("prerequisite", help="必须先 VALID/WAIVED 的 prerequisite node")
    validity = record_commands.add_parser("status"); project_argument(validity)
    validity.add_argument("node_id")
    validity.add_argument("status", choices=[item.value for item in Validity if item not in {Validity.VALID, Validity.PROVISIONAL, Validity.WAIVED}])
    evidence = record_commands.add_parser("evidence"); project_argument(evidence)
    evidence.add_argument("--subject", required=True); evidence.add_argument("--kind", required=True)
    evidence.add_argument("--source", required=True); evidence.add_argument("--verdict", choices=("pass", "fail"), required=True)
    change = record_commands.add_parser("change"); project_argument(change)
    change.add_argument("--path", required=True)
    change.add_argument("--kind", choices=("add", "modify", "delete", "rename", "spec-change", "rtl-change"), required=True)
    change.add_argument("--revision")
    waive = record_commands.add_parser("waive"); project_argument(waive)
    waive.add_argument("node_id"); waive.add_argument("--reviewer", required=True); waive.add_argument("--reason", required=True)

    prove = commands.add_parser("prove", help="仅为无专用合同的自定义 node 登记调用方判定")
    project_argument(prove)
    prove.add_argument("subject", help="status/closure 输出中的目标 node ID")
    prove.add_argument("source", help="项目内 evidence 文件")
    prove.add_argument("--kind", default="verification", help="证据类型，默认 verification")
    prove.add_argument("--fail", action="store_true", help="记录失败证据；默认通过")

    reachability = commands.add_parser(
        "reachability", help="校验并登记 VSTIM 自有 probe 的场景可达性/确定性证据",
    )
    project_argument(reachability)
    reachability.add_argument("subject", help="VSTIM desired-state 或 stimulus-scenario node")
    reachability.add_argument("source", help="项目内 StimulusReachabilityEvidence/1 JSON")
    reachability.add_argument("--claim", choices=("reachability", "determinism"),
                              help="默认从标准 VSTIM desired-state key 推导")

    specialized_evidence = commands.add_parser(
        "evidence", help="按 node 所属 Workstream 校验专用 schema 并从内容推导 verdict",
    )
    project_argument(specialized_evidence)
    specialized_evidence.add_argument("subject", help="VENV/VSTIM/VCHK/VCOV/VCASE/VREG desired node")
    specialized_evidence.add_argument("source", help="项目内专用 evidence JSON")
    specialized_evidence.add_argument("--claim", help="标准 desired node 自动推导；自定义 node 必须显式提供")

    changed = commands.add_parser("changed", help="记录文件变化并自动传播失效")
    project_argument(changed)
    changed.add_argument("path", help="项目内发生变化的文件")
    changed.add_argument("--kind", choices=("auto", "add", "modify", "delete", "rename", "spec-change", "rtl-change"), default="auto")
    changed.add_argument("--revision")

    docs = commands.add_parser("docs", help="管理验证文档索引，并按需输出 SQLite 中记录的评审和状态")
    docs_commands = docs.add_subparsers(dest="docs_command", required=True)
    docs_status = docs_commands.add_parser("status", help="查看一个或全部验证文档的评审和内容状态")
    project_argument(docs_status); docs_status.add_argument("document", nargs="?")
    docs_sync = docs_commands.add_parser("sync", help="重新计算正文摘要；变化会触发失效和重新评审")
    project_argument(docs_sync); docs_sync.add_argument("documents", nargs="*")
    docs_render = docs_commands.add_parser("render", help="按需生成状态、决策、评审和修订投影")
    project_argument(docs_render); docs_render.add_argument("document", nargs="?")
    docs_render.add_argument("--output", help="显式写入项目内独立投影文件；省略时输出到终端")
    docs_review = docs_commands.add_parser("review", help="记录负责人对当前验证文档正文版本的评审")
    project_argument(docs_review); docs_review.add_argument("document")
    docs_review.add_argument("--verdict", choices=("approve", "reject", "modify", "clarify"), default="approve")
    docs_review.add_argument("--reviewer"); docs_review.add_argument("--notes")
    docs_track = docs_commands.add_parser("track", help="登记文档中的决策、假设或外部开放问题")
    project_argument(docs_track); docs_track.add_argument("document")
    docs_track.add_argument("--id", dest="item_id", required=True)
    docs_track.add_argument("--kind", choices=tuple(sorted(DOCUMENT_ITEM_KINDS)), required=True)
    docs_track.add_argument("--title", required=True)
    docs_track.add_argument("--status", choices=tuple(sorted(DOCUMENT_ITEM_STATUSES)), default="PENDING")
    docs_track.add_argument("--owner"); docs_track.add_argument("--review-trigger")
    docs_track.add_argument("--affects", action="append", default=[]); docs_track.add_argument("--anchor")

    simple_waive = commands.add_parser("waive", help="记录负责人接受例外的结论")
    project_argument(simple_waive)
    simple_waive.add_argument("node_id")
    simple_waive.add_argument("--reason", required=True)
    simple_waive.add_argument("--reviewer")

    activity = commands.add_parser("activity", help="登记 Agent/工具当前正在执行的有边界工作")
    activity_commands = activity.add_subparsers(dest="activity_command", required=True)
    activity_start = activity_commands.add_parser("start", help="开始一个 Activity")
    project_argument(activity_start)
    activity_start.add_argument("node_id", help="工作节点 ID；plan 前的项目级工作使用 project")
    activity_start.add_argument("--operation", required=True)
    activity_start.add_argument("--actor", default="Agent")
    activity_start.add_argument("--message", default="")
    activity_start.add_argument("--total", type=int)
    activity_start.add_argument("--log-path")
    activity_update = activity_commands.add_parser("update", help="更新 Activity 状态和进度")
    project_argument(activity_update)
    activity_update.add_argument("activity_id")
    activity_update.add_argument(
        "--status", choices=tuple(sorted(ACTIVITY_STATUSES)), type=str.upper, required=True,
    )
    activity_update.add_argument("--message")
    activity_update.add_argument("--current", type=int)
    activity_update.add_argument("--total", type=int)
    activity_update.add_argument("--log-path")
    activity_list = activity_commands.add_parser("list", help="查看 Activity")
    project_argument(activity_list)
    activity_list.add_argument("--workstream", choices=tuple(WORKSTREAM_TEMPLATES), type=str.upper)
    activity_list.add_argument("--node")
    activity_list.add_argument("--active", action="store_true")

    agent_work = commands.add_parser(
        "agent-work",
        help="由 Main Agent 登记 runtime-native subagent 的 claim、heartbeat 和结果",
    )
    agent_work_commands = agent_work.add_subparsers(dest="agent_work_command", required=True)
    agent_candidates = agent_work_commands.add_parser(
        "candidates", help="列出当前可独立分派的 closure actions",
    )
    project_argument(agent_candidates)
    agent_candidates.add_argument("--limit", type=int, default=20)
    agent_claim = agent_work_commands.add_parser(
        "claim", help="原子领取一个当前 closure action，并自动建立 Activity",
    )
    project_argument(agent_claim)
    agent_claim.add_argument("action_id")
    agent_claim.add_argument("--agent", required=True)
    agent_claim.add_argument("--parent", default="project-agent")
    agent_claim.add_argument("--role", choices=ROLES, required=True)
    agent_claim.add_argument("--operation", required=True)
    agent_claim.add_argument("--runtime-ref")
    agent_claim.add_argument("--lease-seconds", type=int, default=300)
    agent_claim.add_argument("--write-scope", action="append", default=[])
    agent_claim.add_argument("--message", default="")
    agent_claim.add_argument("--total", type=int)
    agent_heartbeat = agent_work_commands.add_parser(
        "heartbeat", help="由 Main Agent 同步 subagent 进度或等待协调状态",
    )
    project_argument(agent_heartbeat)
    agent_heartbeat.add_argument("assignment_id")
    agent_heartbeat.add_argument("--agent", required=True)
    agent_heartbeat.add_argument(
        "--phase", choices=tuple(sorted(AGENT_ASSIGNMENT_PHASES)),
        type=str.upper, default="RUNNING",
    )
    agent_heartbeat.add_argument("--message")
    agent_heartbeat.add_argument("--current", type=int)
    agent_heartbeat.add_argument("--total", type=int)
    agent_finish = agent_work_commands.add_parser(
        "finish", help="结束 subagent assignment；不会改变 node validity 或 evidence",
    )
    project_argument(agent_finish)
    agent_finish.add_argument("assignment_id")
    agent_finish.add_argument("--agent", required=True)
    agent_finish.add_argument(
        "--outcome", choices=("COMPLETED", "FAILED", "CANCELLED"),
        type=str.upper, required=True,
    )
    agent_finish.add_argument("--summary", required=True)
    agent_work_list = agent_work_commands.add_parser(
        "list", help="查看 active 或历史 subagent assignments",
    )
    project_argument(agent_work_list)
    agent_work_list.add_argument(
        "--workstream", choices=tuple(WORKSTREAM_TEMPLATES), type=str.upper,
    )
    agent_work_list.add_argument("--node")
    agent_work_list.add_argument("--active", action="store_true")

    human_action = commands.add_parser("human-action", help="登记负责人在 Dashboard 或 Agent 对话中提出的意见和调整请求")
    human_commands = human_action.add_subparsers(dest="human_command", required=True)
    human_add = human_commands.add_parser("add", help="为节点或验证工作流添加负责人意见")
    project_argument(human_add)
    human_add.add_argument("target")
    human_add.add_argument(
        "--action", choices=tuple(sorted(HUMAN_ACTIONS)), type=str.upper, required=True,
    )
    human_add.add_argument("--reviewer")
    human_add.add_argument("--reason", required=True)
    human_resolve = human_commands.add_parser("resolve", help="记录负责人意见的处理结果；不直接修改节点完成状态")
    project_argument(human_resolve)
    human_resolve.add_argument("action_id")
    human_resolve.add_argument("--reviewer")
    human_resolve.add_argument("--resolution", required=True)
    human_resolve.add_argument(
        "--status", choices=("RESOLVED", "SUPERSEDED"), type=str.upper, default="RESOLVED",
    )
    human_list = human_commands.add_parser("list", help="查看负责人意见")
    project_argument(human_list)
    human_list.add_argument(
        "--status", choices=tuple(sorted(HUMAN_ACTION_STATUSES)), type=str.upper,
    )

    agent_question = commands.add_parser(
        "agent-question",
        help="把 Agent 需要负责人回答的工程问题登记到 Dashboard",
    )
    question_commands = agent_question.add_subparsers(dest="question_command", required=True)
    question_ask = question_commands.add_parser(
        "ask",
        help="登记问题；阻塞问题默认保持 checkpoint，直到 Dashboard/CLI 回答或等待超时",
    )
    project_argument(question_ask)
    question_ask.add_argument("target", help="project、当前 Workstream 或具体工作节点")
    question_ask.add_argument("--prompt", required=True)
    question_ask.add_argument("--context", default="")
    question_ask.add_argument(
        "--actor", choices=(PROJECT_AGENT_ACTOR,), default=PROJECT_AGENT_ACTOR,
        help="需要负责人回答的问题只能由 Project Main Agent 登记",
    )
    question_ask.add_argument("--activity")
    question_ask.add_argument("--recommended")
    question_ask.add_argument("--non-blocking", action="store_true")
    question_ask.add_argument(
        "--no-wait", action="store_true",
        help=(
            "登记后立即返回；仅用于脚本编排，或立即展示问题并启动后台 await 的"
            "受管 runtime bridge"
        ),
    )
    question_ask.add_argument(
        "--wait-timeout", type=float, default=300.0,
        help="阻塞问题本次最长等待秒数；超时返回 TIMEOUT，可用 await 继续等待（默认 300）",
    )
    question_ask.add_argument(
        "--option", action="append", nargs=3, required=True,
        metavar=("ID", "LABEL", "DESCRIPTION"),
        help="可重复 2 到 8 次；DESCRIPTION 不需要时传空字符串",
    )
    question_answer = question_commands.add_parser("answer", help="回答 Dashboard 问题")
    project_argument(question_answer)
    question_answer.add_argument("question_id")
    question_answer.add_argument("--option", required=True)
    question_answer.add_argument("--reviewer")
    question_answer.add_argument("--text", default="")
    question_list = question_commands.add_parser("list", help="列出 Agent questions")
    project_argument(question_list)
    question_list.add_argument(
        "--status", choices=tuple(sorted(AGENT_QUESTION_STATUSES)), type=str.upper,
    )
    question_list.add_argument("--target")
    question_await = question_commands.add_parser(
        "await", help="等待 Dashboard 回答；超时可安全重试",
    )
    project_argument(question_await)
    question_await.add_argument("question_id")
    question_await.add_argument("--timeout", type=float, default=60.0)

    agent_review_check = commands.add_parser(
        "agent-review-check",
        help="检查负责人提交的正文验收结论，并决定是否需要继续向负责人提问",
    )
    review_check_commands = agent_review_check.add_subparsers(
        dest="review_check_command", required=True,
    )
    review_check_list = review_check_commands.add_parser(
        "list", help="列出等待 Agent 检查、等待负责人回答或已完成的审批检查",
    )
    project_argument(review_check_list)
    review_check_list.add_argument(
        "--status", choices=("PENDING", "WAITING_FOR_HUMAN", "COMPLETED"),
        type=str.upper,
    )
    review_check_complete = review_check_commands.add_parser(
        "complete", help="确认 Agent 已检查且当前没有未解决的问题",
    )
    project_argument(review_check_complete)
    review_check_complete.add_argument("review_id")
    review_check_complete.add_argument("--summary", required=True)

    await_human = commands.add_parser(
        "await-human",
        help="等待负责人通过 Dashboard 或 CLI 提交当前工作流方案版本的正式评审",
    )
    project_argument(await_human)
    await_human.add_argument("workstream", choices=tuple(WORKSTREAM_TEMPLATES), type=str.upper)
    await_human.add_argument(
        "--revision", type=int,
        help="省略时在调用开始时绑定当前 revision；旧 revision 会被拒绝",
    )
    await_human.add_argument(
        "--after-review",
        help="同一 revision 再次等待时，忽略这个 review 及更早决定",
    )
    await_human.add_argument(
        "--timeout", type=float, default=60.0,
        help="本次最长等待秒数；超时返回 TIMEOUT，可安全重试（默认 60）",
    )
    await_human.add_argument(
        "--activity",
        help="可选 Activity ID；等待时置为 WAITING_FOR_HUMAN，收到决定后恢复 RUNNING",
    )

    check = commands.add_parser("check", help="Verification Consistency Engine：自动执行，也可显式扫描确定性事实")
    check_commands = check.add_subparsers(dest="check_command", required=True)
    scan = check_commands.add_parser("scan"); project_argument(scan)

    closure = commands.add_parser("closure", help="Verification Closure Engine：自动执行，也可显式查看全局或局部动作")
    closure_commands = closure.add_subparsers(dest="closure_command", required=True)
    evaluate = closure_commands.add_parser("evaluate"); project_argument(evaluate); workstream_argument(evaluate, required=False)

    reason = commands.add_parser("reason", help="Verification Reasoning Engine：Role × Backend 的语义不确定性边界")
    reason_commands = reason.add_subparsers(dest="reason_command", required=True)
    reason_caps = reason_commands.add_parser("capabilities"); project_argument(reason_caps)
    request = reason_commands.add_parser("request"); project_argument(request)
    request.add_argument("--purpose", required=True); request.add_argument("--context", action="append", default=[])
    request.add_argument("--role", choices=ROLES, required=True)
    request.add_argument("--operation", choices=("analyze", "propose", "modify", "review"), default="analyze")
    request.add_argument("--backend", choices=("auto", "codex", "kimi", "claude"), default="auto")

    doctor = commands.add_parser("doctor", help="只读审计 v1 项目状态"); project_argument(doctor)
    runtime = commands.add_parser("runtime", help="查询 setup 选择的 Agent runtime")
    runtime_commands = runtime.add_subparsers(dest="runtime_command", required=True)
    runtime_status = runtime_commands.add_parser("status"); project_argument(runtime_status)

    for name, help_text in (("xverif", "调用 deterministic xverif adapter"), ("wavepeek", "调用 bounded WavePeek adapter")):
        adapter = commands.add_parser(name, help=help_text); adapter.add_argument("adapter_args", nargs=argparse.REMAINDER)
    return parser


def normalize(arguments: list[str]) -> list[str]:
    if not arguments:
        return arguments
    first_original = arguments[0].lower()
    values = [ALIASES.get(first_original, first_original), *arguments[1:]]
    first = values[0]
    second = values[1] if len(values) > 1 else None
    if first == "review":
        values = ["plan", "review", *values[1:]]
    elif first == "freeze":
        values = ["plan", "freeze", *values[1:]]
    elif first == "plan" and second and second.upper() in WORKSTREAM_TEMPLATES:
        values = ["plan", "design", "--workstream", second.upper(), *values[2:]]
    elif first == "model":
        if second == "show":
            values = ["inspect", *values[2:]]
        elif second in {"trace", "impact"}:
            values = [second, *values[2:]]
        else:
            values = ["inspect", *values[1:]]
    elif first == "check" and (second is None or second.startswith("-")):
        values.insert(1, "scan")
    elif first == "closure" and (second is None or second.startswith("-")):
        values.insert(1, "evaluate")
    elif first == "reason" and second in ROLES:
        if len(values) < 3:
            return values
        values = ["reason", "request", "--role", second, "--purpose", values[2], *values[3:]]

    if values[:2] == ["plan", "review"] and len(values) > 2 and values[2].upper() in WORKSTREAM_TEMPLATES:
        values = ["plan", "review", "--workstream", values[2].upper(), *values[3:]]
    if values[:2] == ["plan", "freeze"] and len(values) > 2:
        if values[2].lower() == "final":
            values = ["plan", "freeze", "--final", *values[3:]]
        elif values[2].upper() in WORKSTREAM_TEMPLATES:
            values = ["plan", "freeze", "--workstream", values[2].upper(), *values[3:]]
    return values


def run_adapter(name: str, arguments: list[str], parser: argparse.ArgumentParser) -> int:
    if not arguments:
        parser.error(f"{name} requires adapter arguments")
    root = Path(__file__).resolve().parents[1]
    if name == "xverif":
        relative = "skills/verif-harness/xverif/scripts/xverif_mcp.py" if arguments[0] == "mcp" else "skills/verif-harness/xverif/scripts/xverif_adapter.py"
        forwarded = arguments[1:] if arguments[0] == "mcp" else arguments
    else:
        relative = "skills/verif-harness/wavepeek/scripts/wavepeek_adapter.py"; forwarded = arguments
    return subprocess.run([sys.executable, str(root / relative), *forwarded], check=False).returncode


def _truthy_environment(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() not in {"", "0", "false", "no", "off"}


def _remote_session() -> bool:
    return any(os.environ.get(name) for name in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"))


def dashboard_access_instructions(dashboard_url: str, remote: bool) -> dict[str, object]:
    """Build copyable local, single-hop, and double-hop access guidance."""
    dashboard_parts = urllib.parse.urlsplit(dashboard_url)
    dashboard_port = dashboard_parts.port or 8765
    selected_project_url = urllib.parse.urlunsplit((
        "http", f"127.0.0.1:{dashboard_port}", dashboard_parts.path or "/",
        dashboard_parts.query, "",
    ))
    if not remote:
        return {"mode": "local-url", "url": selected_project_url}
    single_hop = (
        f"ssh -N -L {dashboard_port}:127.0.0.1:{dashboard_port} "
        "<remote-user>@<remote-host>"
    )
    single_hop_config = "\n".join((
        "Host verification-server-direct",
        "    HostName <remote-host>",
        "    User <remote-user>",
        "    Port <remote-ssh-port>",
        "    IdentityFile ~/.ssh/<remote-private-key>",
        "    IdentitiesOnly yes",
        f"    LocalForward {dashboard_port} 127.0.0.1:{dashboard_port}",
    ))
    double_hop_config = "\n".join((
        "Host verification-jump",
        "    HostName <jump-host>",
        "    User <jump-user>",
        "    Port <jump-ssh-port>",
        "    IdentityFile ~/.ssh/<jump-private-key>",
        "    IdentitiesOnly yes",
        "",
        "Host verification-server",
        "    HostName <remote-host>",
        "    User <remote-user>",
        "    Port <remote-ssh-port>",
        "    IdentityFile ~/.ssh/<remote-private-key>",
        "    IdentitiesOnly yes",
        "    ProxyJump verification-jump",
        f"    LocalForward {dashboard_port} 127.0.0.1:{dashboard_port}",
    ))
    return {
        "mode": "ssh-tunnel",
        "url": selected_project_url,
        "remote_dashboard_port": dashboard_port,
        # Kept for existing consumers; the structured single_hop field is preferred.
        "command": single_hop,
        "single_hop": {
            "ssh_config": single_hop_config,
            "command": single_hop,
            "url": selected_project_url,
        },
        "double_hop": {
            "ssh_config": double_hop_config,
            "command": "ssh -N verification-server",
            "url": selected_project_url,
        },
        "local_port_note": (
            f"如果本地 {dashboard_port} 已占用，只修改 LocalForward 左侧端口；"
            f"右侧仍使用远端 Dashboard 端口 {dashboard_port}"
        ),
        "required_agent_output": {
            "must_print": True,
            "items": [
                "single_hop.ssh_config", "single_hop.command",
                "double_hop.ssh_config", "double_hop.command", "url",
            ],
            "message": "\n".join((
                "远端 Dashboard 已就绪。Agent 必须向负责人完整打印以下三项，不能只引用字段名：",
                "",
                "单跳 SSH 配置（写入本地 ~/.ssh/config）：",
                single_hop_config,
                f"启动命令：{single_hop}",
                "",
                "双跳 SSH 配置（写入本地 ~/.ssh/config）：",
                double_hop_config,
                "启动命令：ssh -N verification-server",
                "",
                "本地浏览器访问远端 Dashboard 的完整 URL（必须保留 project 和 token）：",
                selected_project_url,
            )),
        },
        "message": (
            "远端不会尝试打开浏览器；Agent 必须完整打印单跳配置、双跳配置和本地访问 URL"
        ),
    }


def bootstrap_dashboard(
    store: ProjectStore, runtime: str, force: bool, disabled: bool, port: int | None,
) -> dict[str, object]:
    """Apply bootstrap's interactive/CI policy and return a structured launch result."""
    if disabled:
        return {
            "schema": "DashboardLaunch/1", "status": "DISABLED",
            "message": "已通过 --no-dashboard 关闭自动启动",
        }
    in_ci = any(_truthy_environment(name) for name in (
        "CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL", "BUILDKITE",
    ))
    agent_runtime = runtime in {"codex", "kimi", "claude"}
    terminal_interactive = sys.stdin.isatty() or sys.stdout.isatty()
    if not force and (in_ci or not (agent_runtime or terminal_interactive)):
        reason = "CI 环境不自动启动 Dashboard" if in_ci else "非交互环境不自动启动；需要时使用 --dashboard"
        return {"schema": "DashboardLaunch/1", "status": "SKIPPED", "message": reason}

    remote = _remote_session()
    desktop = sys.platform == "darwin" or os.name == "nt" or bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )
    from .dashboard import ensure_dashboard_running
    result = ensure_dashboard_running(
        store, None, port,
        open_browser=bool(not remote and desktop and (agent_runtime or terminal_interactive)),
    )
    if result.get("status") in {"STARTED", "REUSED"}:
        result["access"] = dashboard_access_instructions(
            str(result.get("url") or "http://127.0.0.1:8765/"), remote,
        )
        if not remote and result.get("browser_opened"):
            result["access"]["mode"] = "local-browser"
    return result


def main(arguments: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(normalize(list(sys.argv[1:] if arguments is None else arguments)))
    try:
        if args.command in {"xverif", "wavepeek"}:
            return run_adapter(args.command, args.adapter_args, parser)
        if args.command == "reason":
            backends = capabilities()["reasoning"]
            if args.reason_command == "capabilities":
                emit({"interface": "VerificationReasoningEngine/2", "separation": "Role x Backend", "roles": ROLES,
                      "backends": backends, "execution": "explicit-adapter-required"})
            else:
                selected = args.backend
                if selected == "auto":
                    available = [name for name, value in backends.items() if value["available"]]
                    selected = available[0] if len(available) == 1 else "unselected"
                emit({"schema": "VerificationReasoningRequest/2", "purpose": args.purpose, "context": args.context,
                      "role": args.role, "operation": args.operation, "backend": selected,
                      "required_response": ["diagnosis", "confidence", "proposed_actions", "risk", "human_review", "evidence_requirements"],
                      "executed": False})
            return 0
        store = ProjectStore(args.project_root.resolve())
        if args.command == "bootstrap":
            supplied_reconfiguration = any((
                args.project_name, args.rtl_root, args.docs_root, args.clear_docs_root,
                args.verif_root, args.testbench_root, args.clear_testbench_root,
                args.reference_model, args.clear_reference_model,
                args.verification_script, args.clear_verification_scripts,
                args.dut_top, args.dut_top_file,
            ))
            if args.refresh and store.initialized and not supplied_reconfiguration:
                emit(store.bootstrap_refresh_prompt())
            else:
                result = store.bootstrap(
                    project_name=args.project_name, runtime=args.runtime,
                    rtl_roots=args.rtl_root, docs_roots=args.docs_root,
                    verif_root=args.verif_root, dut_top=args.dut_top,
                    dut_top_file=args.dut_top_file, refresh=args.refresh,
                    clear_docs_roots=args.clear_docs_root,
                    testbench_root=args.testbench_root,
                    reference_model=args.reference_model,
                    verification_scripts=args.verification_script,
                    clear_testbench_root=args.clear_testbench_root,
                    clear_reference_model=args.clear_reference_model,
                    clear_verification_scripts=args.clear_verification_scripts,
                )
                result["dashboard"] = bootstrap_dashboard(
                    store, str(result.get("runtime", "")), args.force_dashboard,
                    args.no_dashboard, args.dashboard_port,
                )
                emit(result)
        elif args.command == "status":
            emit({"plan": store.workstream(args.workstream), "closure": store.evaluate_closure(args.workstream, persist=False)} if args.workstream else store.status())
        elif args.command == "dashboard":
            if args.snapshot:
                emit(store.dashboard_snapshot())
            elif args.status:
                from .dashboard import dashboard_status
                emit(dashboard_status(store, args.host, args.port))
            elif args.stop:
                from .dashboard import stop_dashboard
                emit(stop_dashboard(store, args.host, args.port))
            elif args.foreground:
                from .dashboard import serve_dashboard
                return serve_dashboard(
                    store, args.host or "127.0.0.1",
                    args.port, args.open_browser,
                )
            else:
                from .dashboard import ensure_dashboard_running
                launched = ensure_dashboard_running(
                    store, args.host, args.port,
                    open_browser=args.open_browser,
                )
                if launched.get("status") in {"STARTED", "REUSED"}:
                    launched["access"] = dashboard_access_instructions(
                        str(launched["url"]), _remote_session(),
                    )
                    if not _remote_session() and launched.get("browser_opened"):
                        launched["access"]["mode"] = "local-browser"
                emit(launched)
        elif args.command == "doctor":
            if not store.initialized:
                emit({"status": "INFO", "code": "BOOTSTRAP_REQUIRED", "next": "bootstrap", "project_root": str(store.root)})
            else:
                result = store.audit(); emit({"status": result["status"], "project_root": str(store.root), "scan": result, "summary": store.status()})
                return 1 if result["status"] == "FAIL" else 0
        elif args.command == "runtime":
            store.require(); manifest = json.loads((store.state / "project.json").read_text(encoding="utf-8"))
            emit({"runtime": manifest.get("runtime"), "source": f"{store.state.name}/project.json"})
        elif args.command == "plan":
            if args.plan_command == "design":
                emit(store.design_workstream(args.workstream, args.objective, args.desired, args.exit_criteria,
                                             args.decision, args.document_root, args.evidence_claim,
                                             args.desired_file))
            elif args.plan_command == "authoring":
                emit(store.build_vdoc_authoring_proposal(args.document, args.output))
            elif args.plan_command == "show": emit(store.workstream(args.workstream))
            elif args.plan_command == "review":
                workstream = infer_workstream(store, args.workstream, "review")
                reviewer = reviewer_identity(store.root, args.reviewer)
                if args.verdict != "approve" and not args.reason:
                    raise HarnessError("reject/modify/clarify 必须提供 --reason")
                reason = args.reason or "负责人批准了当前工作流方案版本"
                emit(store.review_workstream(workstream, args.verdict, reviewer, reason))
            elif args.final:
                if args.workstream: raise HarnessError("--final 与 --workstream 不能同时使用")
                emit(store.freeze_final(reviewer_identity(store.root, args.reviewer), args.reason or "负责人同意保存最终验证基线"))
            else:
                workstream = infer_workstream(store, args.workstream, "freeze")
                emit(store.freeze_workstream(workstream, reviewer_identity(store.root, args.reviewer), args.reason or "完成条件已满足，负责人要求保存当前工作流基线"))
        elif args.command == "inspect": emit(store.model(args.node_id))
        elif args.command == "trace": emit(store.trace(args.node_id))
        elif args.command == "impact": emit(store.impact(args.node_id))
        elif args.command == "record":
            if args.record_command == "node": emit(store.add_node(args.node_id, args.node_type, args.title, args.workstream, Validity(args.status)))
            elif args.record_command == "edge": emit(store.add_edge(args.source, args.target, args.relation, args.origin, args.confidence))
            elif args.record_command == "dependency": emit(store.add_dependency(args.subject, args.prerequisite))
            elif args.record_command == "status": emit(store.set_status(args.node_id, Validity(args.status)))
            elif args.record_command == "evidence": emit(store.add_evidence(args.subject, args.kind, args.source, args.verdict))
            elif args.record_command == "change": emit(store.record_change(args.path, args.kind, args.revision))
            else: emit(store.waive_node(args.node_id, args.reviewer, args.reason))
        elif args.command == "prove":
            emit(store.add_evidence(args.subject, args.kind, args.source, "fail" if args.fail else "pass"))
        elif args.command == "reachability":
            emit(store.add_reachability_evidence(args.subject, args.source, args.claim))
        elif args.command == "evidence":
            emit(store.add_workstream_evidence(args.subject, args.source, args.claim))
        elif args.command == "changed":
            kind = args.kind
            if kind == "auto":
                suffix = Path(args.path).suffix.lower()
                kind = "rtl-change" if suffix in {".v", ".sv", ".svh", ".vhd", ".vhdl"} else "spec-change" if suffix in {".md", ".rst", ".txt", ".pdf"} else "modify"
            emit(store.record_change(args.path, kind, args.revision))
        elif args.command == "docs":
            if args.docs_command == "status":
                emit({"documents": store.documents(args.document)})
            elif args.docs_command == "sync":
                emit(store.sync_documents(args.documents, require_active=True))
            elif args.docs_command == "render":
                if args.output:
                    emit(store.write_document_state_projection(args.output, args.document))
                else:
                    print(store.render_document_state(args.document), end="")
            elif args.docs_command == "review":
                if args.verdict != "approve" and not args.notes:
                    raise HarnessError("reject/modify/clarify 必须提供 --notes")
                notes = args.notes or "负责人认可当前验证文档正文版本"
                emit(store.review_document(args.document, args.verdict,
                                           reviewer_identity(store.root, args.reviewer), notes))
            else:
                emit(store.track_document_item(
                    args.document, args.item_id, args.kind, args.title, args.status,
                    args.owner, args.review_trigger, args.affects, args.anchor,
                ))
        elif args.command == "waive":
            emit(store.waive_node(args.node_id, reviewer_identity(store.root, args.reviewer), args.reason))
        elif args.command == "activity":
            if args.activity_command == "start":
                emit(store.create_activity(
                    args.node_id, args.operation, args.actor, args.message, args.total, args.log_path,
                ))
            elif args.activity_command == "update":
                emit(store.update_activity(
                    args.activity_id, args.status, args.message, args.current, args.total, args.log_path,
                ))
            else:
                emit({"activities": store.activities(args.workstream, args.node, args.active)})
        elif args.command == "agent-work":
            if args.agent_work_command == "candidates":
                emit(store.agent_work_candidates(args.limit))
            elif args.agent_work_command == "claim":
                emit(store.claim_agent_work(
                    args.action_id, args.agent, args.role, args.operation,
                    args.parent, args.runtime_ref, args.lease_seconds,
                    args.write_scope, args.message, args.total,
                ))
            elif args.agent_work_command == "heartbeat":
                emit(store.heartbeat_agent_work(
                    args.assignment_id, args.agent, args.phase,
                    args.message, args.current, args.total,
                ))
            elif args.agent_work_command == "finish":
                emit(store.finish_agent_work(
                    args.assignment_id, args.agent, args.outcome, args.summary,
                ))
            else:
                emit({
                    "agent_assignments": store.agent_assignments(
                        args.workstream, args.node, args.active,
                    )
                })
        elif args.command == "human-action":
            if args.human_command == "add":
                emit(store.add_human_action(
                    args.target, args.action, reviewer_identity(store.root, args.reviewer), args.reason,
                ))
            elif args.human_command == "resolve":
                emit(store.resolve_human_action(
                    args.action_id, reviewer_identity(store.root, args.reviewer),
                    args.resolution, args.status,
                ))
            else:
                emit({"human_actions": store.human_actions(args.status)})
        elif args.command == "agent-question":
            if args.question_command == "ask":
                if args.wait_timeout < 0:
                    raise HarnessError("agent-question ask wait timeout 不能小于 0")
                options = [
                    {"id": item[0], "label": item[1], "description": item[2]}
                    for item in args.option
                ]
                question = store.ask_agent_question(
                    args.target, args.prompt, options, args.recommended,
                    args.context, args.actor, not args.non_blocking, args.activity,
                )
                if args.non_blocking or args.no_wait:
                    emit(question)
                else:
                    emit(store.await_agent_question(question["id"], args.wait_timeout))
            elif args.question_command == "answer":
                emit(store.answer_agent_question(
                    args.question_id, args.option,
                    reviewer_identity(store.root, args.reviewer), args.text,
                ))
            elif args.question_command == "await":
                emit(store.await_agent_question(args.question_id, args.timeout))
            else:
                emit({"agent_questions": store.agent_questions(args.status, args.target)})
        elif args.command == "agent-review-check":
            if args.review_check_command == "complete":
                emit(store.complete_review_agent_check(
                    args.review_id, PROJECT_AGENT_ACTOR, args.summary,
                ))
            else:
                emit({"agent_review_checks": store.review_agent_checks(args.status)})
        elif args.command == "await-human":
            emit(store.await_human_review(
                args.workstream, args.revision, args.after_review,
                args.timeout, args.activity,
            ))
        elif args.command == "check": emit(store.scan())
        elif args.command == "closure":
            emit(store.evaluate_closure(args.workstream) if args.workstream else store.reconcile())
        else: parser.error(f"unsupported command: {args.command}")
        return 0
    except HarnessError as exc:
        parser.error(str(exc))
    return 2
