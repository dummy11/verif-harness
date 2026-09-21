"""Explicit evidence admission policy for every standard desired-state node."""

from __future__ import annotations

from typing import Any


ARTIFACT_KINDS = {
    "document", "source", "build-log", "simulation-log", "waveform",
    "transaction-trace", "coverage-database", "regression-manifest",
    "analysis-report", "configuration",
}


def requirement(label: str, *alternatives: tuple[str, str]) -> dict[str, Any]:
    return {
        "label": label,
        "minimum": 1,
        "alternatives": [
            {"kind": kind, "analyzer": analyzer} for kind, analyzer in alternatives
        ],
    }


SOURCE = requirement("实现代码已通过编译或静态检查", ("source", "xverif"))
BUILD = requirement("编译和装载日志已通过检查", ("build-log", "xverif"))
SIM = requirement("仿真日志已通过检查", ("simulation-log", "xverif"))
TRACE = requirement(
    "波形数据库或输入输出事务记录已完成分析",
    ("waveform", "wavepeek"),
    ("transaction-trace", "xverif"),
)
COVERAGE_DB = requirement("覆盖率数据库已导出并通过一致性检查", ("coverage-database", "xverif"))
MANIFEST = requirement("回归测试清单已通过执行器检查", ("regression-manifest", "xverif"))
ANALYSIS = requirement("结构化分析结果已保存", ("analysis-report", "xverif"), ("analysis-report", "wavepeek"))
XVERIF_ANALYSIS = requirement("结构化分析结果由 xverif 生成", ("analysis-report", "xverif"))
DOCUMENT = requirement("验证文档已经负责人评审", ("document", "human-review"))
CONFIG = requirement("运行配置已通过检查", ("configuration", "xverif"))


EVIDENCE_POLICIES: dict[str, dict[str, dict[str, Any]]] = {
    "VENV": {
        "interface-ready": {"requirements": [SOURCE, BUILD], "basis": "source-and-elaboration"},
        "clock-reset-ready": {"requirements": [SOURCE, SIM, TRACE, ANALYSIS], "basis": "simulation-and-trace"},
        "topology-ready": {"requirements": [SOURCE, BUILD], "basis": "source-and-elaboration"},
        "build-ready": {"requirements": [SOURCE, BUILD], "basis": "compile-and-elaboration"},
        "run-ready": {"requirements": [CONFIG, SIM, XVERIF_ANALYSIS], "basis": "runner-self-test"},
        "observation-ready": {"requirements": [SOURCE, TRACE, ANALYSIS], "basis": "connected-observation"},
        "environment-smoke-evidence": {
            "requirements": [SIM, TRACE, ANALYSIS], "basis": "smoke-simulation-and-trace",
        },
    },
    "VSTIM": {
        "transaction-contract": {"requirements": [DOCUMENT], "basis": "reviewed-contract"},
        "stimulus-implementation": {"requirements": [SOURCE, BUILD], "basis": "compiled-implementation"},
        "corner-scenarios": {"requirements": [SOURCE, BUILD], "basis": "compiled-scenario-generators"},
        "reachability-evidence": {"requirements": [SIM, TRACE, ANALYSIS], "basis": "accepted-boundary-observation"},
        "determinism-evidence": {"requirements": [SIM, TRACE, ANALYSIS], "basis": "same-seed-replay"},
    },
    "VCHK": {
        "compare-policy": {"requirements": [DOCUMENT], "basis": "reviewed-policy"},
        "reference-model": {"requirements": [SOURCE, BUILD], "basis": "compiled-adapter"},
        "scoreboard": {"requirements": [SOURCE, BUILD], "basis": "compiled-checker"},
        "assertions": {"requirements": [SOURCE, BUILD], "basis": "compiled-and-bound"},
        "reference-model-evidence": {
            "requirements": [SIM, TRACE, ANALYSIS], "basis": "runtime-comparison",
        },
        "scoreboard-evidence": {"requirements": [SIM, TRACE, ANALYSIS], "basis": "runtime-comparison"},
        "assertion-evidence": {"requirements": [SIM, TRACE, ANALYSIS], "basis": "runtime-attempts"},
    },
    "VCOV": {
        "coverage-model": {"requirements": [SOURCE, BUILD], "basis": "compiled-coverage-model"},
        "coverage-collection": {"requirements": [CONFIG, BUILD], "basis": "configured-exporter"},
        "coverage-collection-evidence": {
            "requirements": [COVERAGE_DB, XVERIF_ANALYSIS], "basis": "database-merge-analysis",
        },
        "hole-analysis-evidence": {
            "requirements": [COVERAGE_DB, XVERIF_ANALYSIS], "basis": "item-level-hole-analysis",
        },
    },
    "VCASE": {
        "case-matrix": {"requirements": [DOCUMENT], "basis": "reviewed-feature-mapping"},
        "case-implementation": {"requirements": [SOURCE, BUILD], "basis": "compiled-registration"},
        "targeted-evidence": {"requirements": [SIM, TRACE, ANALYSIS], "basis": "targeted-simulation"},
    },
    "VREG": {
        "regression-policy": {"requirements": [DOCUMENT], "basis": "reviewed-policy"},
        "executor-ready": {"requirements": [SOURCE, BUILD], "basis": "executor-self-test"},
        "execution-evidence": {"requirements": [MANIFEST, SIM, XVERIF_ANALYSIS], "basis": "batch-execution"},
        "triage-evidence": {"requirements": [SIM, XVERIF_ANALYSIS], "basis": "same-seed-triage"},
        "fresh-evidence": {"requirements": [MANIFEST, XVERIF_ANALYSIS], "basis": "current-revision-audit"},
    },
}


def policy_for(workstream: str, claim: str) -> dict[str, Any] | None:
    policy = EVIDENCE_POLICIES.get(workstream, {}).get(claim)
    if policy is None:
        return None
    return {
        "version": "EvidenceAdmissionPolicy/1",
        "workstream": workstream,
        "claim": claim,
        "basis": policy["basis"],
        "requirements": policy["requirements"],
    }


def validate_artifact_policy(
    workstream: str, claim: str, artifacts: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    policy = policy_for(workstream, claim)
    if policy is None:
        return {}, [f"{workstream}/{claim} 没有明确 evidence admission policy"]
    blockers: list[str] = []
    for item in policy["requirements"]:
        matches = []
        for artifact in artifacts:
            analyzers = set(artifact.get("analyzed_by", []))
            for alternative in item["alternatives"]:
                if artifact.get("kind") == alternative["kind"] and alternative["analyzer"] in analyzers:
                    matches.append(artifact["path"])
                    break
        if len(matches) < item["minimum"]:
            expected = " 或 ".join(
                f"{choice['kind']} 由 {choice['analyzer']} 分析"
                for choice in item["alternatives"]
            )
            blockers.append(f"缺少 {item['label']}：需要 {expected}")
    return policy, blockers
