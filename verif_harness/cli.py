"""Command-line interface for the verif-harness v1 control plane."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .store import HarnessError, ProjectStore, Validity, WORKSTREAM_TEMPLATES, capabilities


ALIASES = {
    "vplan": "plan", "vmodel": "model", "vcheck": "check",
    "vclosure": "closure", "vreason": "reason",
    "waveform": "wavepeek",
}
ROLES = (
    "VerificationArchitect", "EnvironmentEngineer", "TestEngineer",
    "AssertionEngineer", "CoverageEngineer", "DebugEngineer", "Reviewer",
)


def emit(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def project_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", type=Path, default=Path.cwd())


def workstream_argument(parser: argparse.ArgumentParser, required: bool = True) -> None:
    parser.add_argument("--workstream", choices=tuple(WORKSTREAM_TEMPLATES), type=str.upper, required=required)


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
        description="以 Verification Knowledge Model 为事实源的持续 RTL verification control plane",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""常用命令：
  verif-harness bootstrap
  verif-harness plan VDOC
  verif-harness review [VDOC]
  verif-harness status [VDOC]
  verif-harness inspect [NODE]
  verif-harness trace NODE
  verif-harness impact NODE
  verif-harness prove NODE FILE
  verif-harness changed PATH
  verif-harness freeze VDOC|final

完整操作与参数见 skills/verif-harness/docs/user_guide.md。""",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    bootstrap = commands.add_parser("bootstrap", help="发现项目并建立最小 Verification Knowledge Model；不生成验证语义")
    project_argument(bootstrap)
    bootstrap.add_argument("--project-name")
    bootstrap.add_argument("--runtime", choices=("auto", "codex", "kimi", "claude", "none"), default="auto")
    bootstrap.add_argument("--rtl-root", action="append", default=[])
    bootstrap.add_argument("--docs-root", action="append", default=[])
    bootstrap.add_argument("--verif-root")
    bootstrap.add_argument("--dut-top")
    bootstrap.add_argument("--dut-top-file")
    bootstrap.add_argument("--refresh", action="store_true")

    status = commands.add_parser("status", help="显示全局模型、Workstream 与自动 closure 摘要")
    project_argument(status)
    status.add_argument("workstream", nargs="?", choices=tuple(WORKSTREAM_TEMPLATES), type=str.upper)

    plan = commands.add_parser("plan", help="Verification Planner：使用 plan WORKSTREAM 形成/修订 desired state")
    plan_commands = plan.add_subparsers(dest="plan_command", required=True)
    design = plan_commands.add_parser("design", help="设计或修订一个可重入 Workstream")
    project_argument(design); workstream_argument(design)
    design.add_argument("--objective")
    design.add_argument("--desired", action="append", default=[])
    design.add_argument("--exit", dest="exit_criteria", action="append", default=[])
    design.add_argument("--decision", action="append", default=[])
    show = plan_commands.add_parser("show", help="显示当前 Workstream plan")
    project_argument(show); workstream_argument(show)
    review = plan_commands.add_parser("review", help="记录 Human 对当前 revision 的判定")
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
    validity = record_commands.add_parser("status"); project_argument(validity)
    validity.add_argument("node_id")
    validity.add_argument("status", choices=[item.value for item in Validity if item not in {Validity.VALID, Validity.WAIVED}])
    evidence = record_commands.add_parser("evidence"); project_argument(evidence)
    evidence.add_argument("--subject", required=True); evidence.add_argument("--kind", required=True)
    evidence.add_argument("--source", required=True); evidence.add_argument("--verdict", choices=("pass", "fail"), required=True)
    change = record_commands.add_parser("change"); project_argument(change)
    change.add_argument("--path", required=True)
    change.add_argument("--kind", choices=("add", "modify", "delete", "rename", "spec-change", "rtl-change"), required=True)
    change.add_argument("--revision")
    waive = record_commands.add_parser("waive"); project_argument(waive)
    waive.add_argument("node_id"); waive.add_argument("--reviewer", required=True); waive.add_argument("--reason", required=True)

    prove = commands.add_parser("prove", help="把一个真实文件记录为 node 的通过/失败证据")
    project_argument(prove)
    prove.add_argument("subject", help="status/closure 输出中的目标 node ID")
    prove.add_argument("source", help="项目内 evidence 文件")
    prove.add_argument("--kind", default="verification", help="证据类型，默认 verification")
    prove.add_argument("--fail", action="store_true", help="记录失败证据；默认通过")

    changed = commands.add_parser("changed", help="记录文件变化并自动传播失效")
    project_argument(changed)
    changed.add_argument("path", help="项目内发生变化的文件")
    changed.add_argument("--kind", choices=("auto", "add", "modify", "delete", "rename", "spec-change", "rtl-change"), default="auto")
    changed.add_argument("--revision")

    simple_waive = commands.add_parser("waive", help="记录 Human waiver")
    project_argument(simple_waive)
    simple_waive.add_argument("node_id")
    simple_waive.add_argument("--reason", required=True)
    simple_waive.add_argument("--reviewer")

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
            emit(store.bootstrap(args.project_name, args.runtime, args.rtl_root, args.docs_root,
                                 args.verif_root, args.dut_top, args.dut_top_file, args.refresh))
        elif args.command == "status":
            emit({"plan": store.workstream(args.workstream), "closure": store.evaluate_closure(args.workstream, persist=False)} if args.workstream else store.status())
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
                emit(store.design_workstream(args.workstream, args.objective, args.desired, args.exit_criteria, args.decision))
            elif args.plan_command == "show": emit(store.workstream(args.workstream))
            elif args.plan_command == "review":
                workstream = infer_workstream(store, args.workstream, "review")
                reviewer = reviewer_identity(store.root, args.reviewer)
                if args.verdict != "approve" and not args.reason:
                    raise HarnessError("reject/modify/clarify 必须提供 --reason")
                reason = args.reason or "Human approved the current desired-state revision"
                emit(store.review_workstream(workstream, args.verdict, reviewer, reason))
            elif args.final:
                if args.workstream: raise HarnessError("--final 与 --workstream 不能同时使用")
                emit(store.freeze_final(reviewer_identity(store.root, args.reviewer), args.reason or "Human approved final verification freeze"))
            else:
                workstream = infer_workstream(store, args.workstream, "freeze")
                emit(store.freeze_workstream(workstream, reviewer_identity(store.root, args.reviewer), args.reason or "Closure ready; Human requested immutable freeze"))
        elif args.command == "inspect": emit(store.model(args.node_id))
        elif args.command == "trace": emit(store.trace(args.node_id))
        elif args.command == "impact": emit(store.impact(args.node_id))
        elif args.command == "record":
            if args.record_command == "node": emit(store.add_node(args.node_id, args.node_type, args.title, args.workstream, Validity(args.status)))
            elif args.record_command == "edge": emit(store.add_edge(args.source, args.target, args.relation, args.origin, args.confidence))
            elif args.record_command == "status": emit(store.set_status(args.node_id, Validity(args.status)))
            elif args.record_command == "evidence": emit(store.add_evidence(args.subject, args.kind, args.source, args.verdict))
            elif args.record_command == "change": emit(store.record_change(args.path, args.kind, args.revision))
            else: emit(store.waive_node(args.node_id, args.reviewer, args.reason))
        elif args.command == "prove":
            emit(store.add_evidence(args.subject, args.kind, args.source, "fail" if args.fail else "pass"))
        elif args.command == "changed":
            kind = args.kind
            if kind == "auto":
                suffix = Path(args.path).suffix.lower()
                kind = "rtl-change" if suffix in {".v", ".sv", ".svh", ".vhd", ".vhdl"} else "spec-change" if suffix in {".md", ".rst", ".txt", ".pdf"} else "modify"
            emit(store.record_change(args.path, kind, args.revision))
        elif args.command == "waive":
            emit(store.waive_node(args.node_id, reviewer_identity(store.root, args.reviewer), args.reason))
        elif args.command == "check": emit(store.scan())
        elif args.command == "closure":
            emit(store.evaluate_closure(args.workstream) if args.workstream else store.reconcile())
        else: parser.error(f"unsupported command: {args.command}")
        return 0
    except HarnessError as exc:
        parser.error(str(exc))
    return 2
