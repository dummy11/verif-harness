"""Code plans, validated deliveries, and version-bound capabilities.

No simulator is launched here. Main Agent submits typed tool reports; existing
evidence admission rules check them before a delivery can be offered for review.
"""
from __future__ import annotations

import json
import copy
import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from .vdoc_artifacts import digest, encoded
from .approval_policy import assessment, dependency_subject, retain_head

VCOV_PLAN_ROLES = {"coverage-implementation-plan", "coverage-convergence-plan"}
VCOV_DELIVERY_ROLES = {"coverage-implementation-deliverable", "coverage-convergence-deliverable"}
VREG_PLAN_ROLES = {"regression-infrastructure-plan", "regression-results-plan"}
VREG_DELIVERY_ROLES = {"regression-infrastructure-deliverable", "regression-results-deliverable"}
PLAN_ROLES = {"code-plan", *VCOV_PLAN_ROLES, *VREG_PLAN_ROLES}
DELIVERY_ROLES = {"code-deliverable", *VCOV_DELIVERY_ROLES, *VREG_DELIVERY_ROLES}
ROLES = PLAN_ROLES | DELIVERY_ROLES
VCOV_IMPLEMENTATION_CLAIMS = {"coverage-model", "coverage-collection"}
VCOV_CONVERGENCE_CLAIMS = {"coverage-collection-evidence", "hole-analysis-evidence"}
VCOV_VALIDATION_CONTRACT = "CoverageConvergence/5"
MAX_COVERAGE_EXCLUSION_BYTES = 512 * 1024
VREG_INFRASTRUCTURE_CLAIMS = {"regression-policy", "executor-ready"}
VREG_RESULTS_CLAIMS = {"execution-evidence", "triage-evidence", "fresh-evidence"}
VCASE_VALIDATION_CONTRACT = "TestcaseExecution/3"
VREG_VALIDATION_CONTRACT = "RegressionResults/4"
VCOV_ROLE_LABELS = {
    "coverage-implementation-plan": "覆盖率实现方案",
    "coverage-implementation-deliverable": "覆盖率实现交付",
    "coverage-convergence-plan": "覆盖率收敛方案",
    "coverage-convergence-deliverable": "覆盖率收敛交付",
}
VREG_ROLE_LABELS = {
    "regression-infrastructure-plan": "回归基础设施方案",
    "regression-infrastructure-deliverable": "回归基础设施交付",
    "regression-results-plan": "回归结果方案",
    "regression-results-deliverable": "回归结果交付",
}
CODE_WORKSTREAMS = ("VENV", "VSTIM", "VCHK", "VCASE", "VCOV", "VREG")
PROFILES: dict[str, dict[str, Any]] = {
    "VENV": {
        "cap_prefix": "cap.venv:",
        "input_prefixes": ("cap.doc:", "cap.venv:"),
        "required_input_prefixes": ("cap.doc:",),
        "objective": "实现并验证当前 DUT 的验证环境",
        "label": "验证环境",
        "delivery_label": "代码交付验收",
        "allowed_claims": {
            "interface-ready", "clock-reset-ready", "topology-ready", "build-ready",
            "run-ready", "observation-ready", "environment-smoke-evidence",
        },
    },
    "VSTIM": {
        "cap_prefix": "cap.vstim:",
        "input_prefixes": ("cap.doc:", "cap.venv:", "cap.vstim:", "cap.vreg:"),
        "required_input_prefixes": ("cap.doc:", "cap.venv:"),
        "objective": "实现并验证当前 DUT 必需功能和场景的激励能力",
        "label": "激励",
        "delivery_label": "激励代码交付验收",
        "allowed_claims": {
            "stimulus-implementation", "corner-scenarios",
            "reachability-evidence", "determinism-evidence",
        },
    },
    "VCHK": {
        "cap_prefix": "cap.vchk:",
        "input_prefixes": ("cap.doc:", "cap.venv:", "cap.vstim:", "cap.vchk:"),
        "required_input_prefixes": ("cap.doc:", "cap.venv:", "cap.vstim:"),
        "objective": "实现并验证当前 DUT 的参考模型、结果检查和断言能力",
        "label": "检查机制",
        "delivery_label": "检查代码交付验收",
        "allowed_claims": {
            "reference-model", "scoreboard", "assertions",
            "reference-model-evidence", "scoreboard-evidence", "assertion-evidence",
        },
    },
    "VCASE": {
        "cap_prefix": "cap.vcase:",
        "input_prefixes": (
            "cap.doc:", "cap.venv:", "cap.vstim:", "cap.vchk:",
            "cap.vcase:", "cap.vreg:",
        ),
        "required_input_prefixes": ("cap.doc:", "cap.venv:", "cap.vstim:", "cap.vchk:"),
        "objective": "实现并验证当前 DUT 必需验证点对应的测试用例",
        "label": "测试用例",
        "delivery_label": "测试用例代码交付验收",
        "allowed_claims": {"case-implementation", "targeted-evidence"},
    },
    "VCOV": {
        "cap_prefix": "cap.vcov:",
        "input_prefixes": (
            "cap.doc:", "cap.venv:", "cap.vstim:", "cap.vchk:",
            "cap.vcase:", "cap.vcov:", "cap.vreg:",
        ),
        "required_input_prefixes": ("cap.doc:", "cap.venv:"),
        "objective": "实现当前 DUT 的覆盖率模型、采集链路，并用当前结果关闭覆盖缺口",
        "label": "覆盖率",
        "delivery_label": "覆盖率实现与证据验收",
        "plan_term": "覆盖率实现与收敛方案",
        "allowed_claims": {
            "coverage-model", "coverage-collection",
            "coverage-collection-evidence", "hole-analysis-evidence",
        },
    },
    "VREG": {
        "cap_prefix": "cap.vreg:",
        "input_prefixes": (
            "cap.doc:", "cap.venv:", "cap.vstim:", "cap.vchk:",
            "cap.vcase:", "cap.vcov:", "cap.vreg:",
        ),
        "required_input_prefixes": ("cap.doc:", "cap.venv:"),
        "objective": "建立当前 DUT 的回归执行基础设施，并形成可复现、已分类且版本新鲜的回归结论",
        "label": "回归",
        "delivery_label": "回归实现与证据验收",
        "plan_term": "回归基础设施与结果方案",
        "allowed_claims": {
            "regression-policy", "executor-ready", "execution-evidence",
            "triage-evidence", "fresh-evidence",
        },
    },
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS code_validations (
 id TEXT PRIMARY KEY, node_id TEXT NOT NULL, revision INTEGER NOT NULL,
 signature TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS code_validations_node ON code_validations(node_id);
CREATE TABLE IF NOT EXISTS code_artifact_versions (
 artifact_id TEXT NOT NULL, version INTEGER NOT NULL, signature TEXT NOT NULL,
 payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(artifact_id,version), UNIQUE(artifact_id,signature)
);
CREATE TABLE IF NOT EXISTS code_watched_files (path TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS code_feedback_inputs (
 node_id TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
 review_id TEXT NOT NULL, PRIMARY KEY(node_id,path)
);
CREATE TABLE IF NOT EXISTS coverage_exclusion_approvals (
 id TEXT PRIMARY KEY, node_id TEXT NOT NULL, workstream TEXT NOT NULL,
 revision INTEGER NOT NULL, scope_digest TEXT NOT NULL,
 path TEXT NOT NULL, sha256 TEXT NOT NULL, reviewer TEXT NOT NULL,
 reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS coverage_exclusion_approvals_node
 ON coverage_exclusion_approvals(node_id,revision);
CREATE TABLE IF NOT EXISTS regression_execution_rounds (
 id TEXT PRIMARY KEY, node_id TEXT NOT NULL, revision INTEGER NOT NULL,
 round_number INTEGER NOT NULL, plan_digest TEXT NOT NULL,
 request_digest TEXT NOT NULL DEFAULT '',
 config_json TEXT NOT NULL DEFAULT '{}',
 request_key TEXT NOT NULL, requested_by TEXT NOT NULL, reason TEXT NOT NULL,
 status TEXT NOT NULL, requested_at TEXT NOT NULL, dispatched_at TEXT,
 validated_at TEXT, accepted_at TEXT, validation_id TEXT,
 activity_id TEXT, archive_json TEXT NOT NULL DEFAULT '{}',
 UNIQUE(node_id,request_key), UNIQUE(node_id,round_number)
);
CREATE INDEX IF NOT EXISTS regression_execution_rounds_node
 ON regression_execution_rounds(node_id,round_number);
"""


def migrate(connection):
    # Do not reconstruct early development rounds from today's configuration.
    if "config_json" not in {row[1] for row in connection.execute("PRAGMA table_info(regression_execution_rounds)")}:
        connection.execute("ALTER TABLE regression_execution_rounds ADD COLUMN config_json TEXT NOT NULL DEFAULT '{}'")


def modern(plan):
    return (plan.get("workstream") in CODE_WORKSTREAMS
            and plan.get("planning_context", {}).get("code_model") == 2)


def supported(workstream):
    return workstream in CODE_WORKSTREAMS


def is_plan(node):
    return node.get("role") in PLAN_ROLES


def is_delivery(node):
    return node.get("role") in DELIVERY_ROLES


def _coverage_scope_strings(value, field, *, allowed=None):
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} 必须是非空字符串数组")
    normalized = [item.strip() for item in value]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} 不能包含重复项")
    if allowed is not None and any(item not in allowed for item in normalized):
        raise ValueError(f"{field} 包含不支持的值")
    return sorted(normalized)


def normalize_coverage_scope(value):
    """Normalize the Human-approved scope; native object expansion stays in evidence files."""
    if not isinstance(value, dict) or value.get("schema") != "CoverageScope/1":
        raise ValueError("coverage_scope.schema 必须是 CoverageScope/1")
    allowed_top = {"schema", "code", "functional", "semantic_goal_ids"}
    if set(value) - allowed_top:
        raise ValueError("coverage_scope 包含不支持的字段")
    normalized = {"schema": "CoverageScope/1"}
    code_scope = value.get("code")
    if code_scope is not None:
        if not isinstance(code_scope, dict) or set(code_scope) - {
            "metrics", "hierarchy_selectors", "hierarchy_files", "exclusion_files",
        }:
            raise ValueError("coverage_scope.code 包含不支持的字段")
        code = {
            "metrics": _coverage_scope_strings(
                code_scope.get("metrics"), "coverage_scope.code.metrics",
                allowed={"line", "condition", "branch", "toggle", "fsm"},
            ),
        }
        for field in ("hierarchy_selectors", "hierarchy_files", "exclusion_files"):
            if field in code_scope:
                code[field] = _coverage_scope_strings(
                    code_scope.get(field), f"coverage_scope.code.{field}",
                )
        if not code.get("hierarchy_selectors") and not code.get("hierarchy_files"):
            raise ValueError("code 覆盖范围必须提供 hierarchy_selectors 或 hierarchy_files")
        normalized["code"] = code
    functional_scope = value.get("functional")
    if functional_scope is not None:
        if not isinstance(functional_scope, dict) or set(functional_scope) - {
            "covergroup_selectors", "object_kinds",
        }:
            raise ValueError("coverage_scope.functional 包含不支持的字段")
        normalized["functional"] = {
            "covergroup_selectors": _coverage_scope_strings(
                functional_scope.get("covergroup_selectors"),
                "coverage_scope.functional.covergroup_selectors",
            ),
            "object_kinds": _coverage_scope_strings(
                functional_scope.get("object_kinds"),
                "coverage_scope.functional.object_kinds",
                allowed={"coverpoint-bin", "cross-bin"},
            ),
        }
    if "code" not in normalized and "functional" not in normalized:
        raise ValueError("coverage_scope 必须至少包含 code 或 functional 范围")
    if "semantic_goal_ids" in value:
        from .evidence_contracts import ID
        goals = _coverage_scope_strings(value.get("semantic_goal_ids"), "coverage_scope.semantic_goal_ids")
        if any(not ID.fullmatch(item) for item in goals):
            raise ValueError("coverage_scope.semantic_goal_ids 包含非法标识")
        normalized["semantic_goal_ids"] = goals
    return normalized


def coverage_scope(node):
    try:
        return normalize_coverage_scope(node.get("coverage_scope"))
    except ValueError:
        return None


def coverage_scope_digest(node):
    scope = coverage_scope(node)
    if scope is None:
        return None
    return hashlib.sha256(json.dumps(
        scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def coverage_scope_files(node):
    scope = coverage_scope(node) or {}
    code = scope.get("code", {})
    return set(code.get("hierarchy_files", [])) | set(code.get("exclusion_files", []))


def _sha256(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{field} 必须是小写 SHA-256")
    return value


def _named_version(value, field, *, role=False):
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是对象")
    allowed = {"name", "version", *(('role',) if role else ())}
    if set(value) - allowed:
        raise ValueError(f"{field} 包含不支持的字段")
    result = {}
    if role:
        if not isinstance(value.get("role"), str) or not value["role"].strip():
            raise ValueError(f"{field}.role 必须是非空字符串")
        result["role"] = value["role"].strip()
    for key in ("name", "version"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"{field}.{key} 必须是非空字符串")
        result[key] = value[key].strip()
    return result


def normalize_coverage_implementation_config(value):
    """Normalize coverage-only implementation mechanics; VREG owns run selection."""
    if not isinstance(value, dict) or value.get("schema") != "CoverageImplementationConfig/1":
        raise ValueError("coverage_implementation_config.schema 必须是 CoverageImplementationConfig/1")
    if set(value) - {"schema", "code_coverage_target", "configuration_refs", "compatible_submit_profile_digests", "toolchain"}:
        raise ValueError("coverage_implementation_config 包含不支持的字段")
    if value.get("code_coverage_target") != "dut":
        raise ValueError("coverage_implementation_config.code_coverage_target 必须是 dut")
    refs = value.get("configuration_refs")
    if not isinstance(refs, list) or not refs:
        raise ValueError("coverage_implementation_config.configuration_refs 必须是非空数组")
    allowed_roles = {"instrumentation", "elaboration", "collection", "export", "analysis"}
    normalized_refs = []
    seen_roles = set()
    for index, item in enumerate(refs):
        field = f"coverage_implementation_config.configuration_refs[{index}]"
        if not isinstance(item, dict) or set(item) != {"role", "path", "sha256"}:
            raise ValueError(f"{field} 必须只包含 role/path/sha256")
        role = item.get("role")
        if role not in allowed_roles or role in seen_roles:
            raise ValueError(f"{field}.role 必须唯一且属于批准的覆盖实现角色")
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"{field}.path 必须是非空字符串")
        seen_roles.add(role)
        normalized_refs.append({"role": role, "path": path.strip(),
                                "sha256": _sha256(item.get("sha256"), f"{field}.sha256")})
    profiles = value.get("compatible_submit_profile_digests")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("coverage_implementation_config.compatible_submit_profile_digests 必须是非空数组")
    profiles = [_sha256(item, "compatible_submit_profile_digests[]") for item in profiles]
    if len(profiles) != len(set(profiles)):
        raise ValueError("compatible_submit_profile_digests 不能包含重复项")
    toolchain = value.get("toolchain")
    if not isinstance(toolchain, list) or not toolchain:
        raise ValueError("coverage_implementation_config.toolchain 必须是非空数组")
    tools = [_named_version(item, f"coverage_implementation_config.toolchain[{index}]", role=True)
             for index, item in enumerate(toolchain)]
    if len({item["role"] for item in tools}) != len(tools):
        raise ValueError("coverage_implementation_config.toolchain role 不能重复")
    return {"schema": "CoverageImplementationConfig/1", "code_coverage_target": "dut",
            "configuration_refs": sorted(normalized_refs, key=lambda item: item["role"]),
            "compatible_submit_profile_digests": sorted(profiles),
            "toolchain": sorted(tools, key=lambda item: item["role"])}


def normalize_dut_build_fingerprint(value):
    """Normalize the DUT-only merge-compatibility partition."""
    required = {
        "schema", "coverage_target", "dut_design_id", "rtl_digest",
        "parameter_digest", "macro_digest", "dut_elaboration_digest",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("dut_build_fingerprint 必须是完整 DutBuildFingerprint/1")
    if value.get("schema") != "DutBuildFingerprint/1" or value.get("coverage_target") != "dut":
        raise ValueError("dut_build_fingerprint 必须描述 DUT code coverage 构建")
    design_id = value.get("dut_design_id")
    if not isinstance(design_id, str) or not design_id.strip():
        raise ValueError("dut_build_fingerprint.dut_design_id 必须是非空字符串")
    return {
        "schema": "DutBuildFingerprint/1", "coverage_target": "dut",
        "dut_design_id": design_id.strip(),
        **{key: _sha256(value.get(key), f"dut_build_fingerprint.{key}")
           for key in ("rtl_digest", "parameter_digest", "macro_digest",
                       "dut_elaboration_digest")},
    }


def normalize_coverage_collection_config(value):
    """Normalize VREG source references and merge mechanics without copying run policy."""
    if not isinstance(value, dict) or value.get("schema") != "CoverageCollectionConfig/1":
        raise ValueError("coverage_collection_config.schema 必须是 CoverageCollectionConfig/1")
    if set(value) != {"schema", "regression_sources", "dut_build_fingerprint", "merge_profile"}:
        raise ValueError(
            "coverage_collection_config 必须只包含 schema/regression_sources/"
            "dut_build_fingerprint/merge_profile"
        )
    sources = value.get("regression_sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("coverage_collection_config.regression_sources 必须是非空数组")
    normalized_sources = []
    seen = set()
    for index, source in enumerate(sources):
        field = f"coverage_collection_config.regression_sources[{index}]"
        if not isinstance(source, dict) or set(source) != {
                "plan_node_id", "plan_revision", "regression_config_digest"}:
            raise ValueError(f"{field} 必须只引用 VREG 结果方案、版本和 regression_config 摘要")
        node_id = source.get("plan_node_id")
        revision = source.get("plan_revision")
        if not isinstance(node_id, str) or not node_id.startswith("workstream:VREG:"):
            raise ValueError(f"{field}.plan_node_id 必须引用 VREG 工作节点")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError(f"{field}.plan_revision 必须是正整数")
        key = (node_id, revision)
        if key in seen:
            raise ValueError("coverage_collection_config 不能重复引用同一 VREG 结果方案")
        seen.add(key)
        normalized_sources.append({"plan_node_id": node_id, "plan_revision": revision,
                                   "regression_config_digest": _sha256(
                                       source.get("regression_config_digest"),
                                       f"{field}.regression_config_digest")})
    profile = value.get("merge_profile")
    if not isinstance(profile, dict) or set(profile) != {"path", "sha256", "adapter", "tool"}:
        raise ValueError("coverage_collection_config.merge_profile 必须包含 path/sha256/adapter/tool")
    path = profile.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("coverage_collection_config.merge_profile.path 必须是非空字符串")
    return {"schema": "CoverageCollectionConfig/1",
            "regression_sources": sorted(normalized_sources, key=lambda item: item["plan_node_id"]),
            "dut_build_fingerprint": normalize_dut_build_fingerprint(
                value.get("dut_build_fingerprint")
            ),
            "merge_profile": {"path": path.strip(),
                              "sha256": _sha256(profile.get("sha256"), "merge_profile.sha256"),
                              "adapter": _named_version(profile.get("adapter"), "merge_profile.adapter"),
                              "tool": _named_version(profile.get("tool"), "merge_profile.tool")}}


def coverage_implementation_config(node):
    try:
        return normalize_coverage_implementation_config(node.get("coverage_implementation_config"))
    except ValueError:
        return None


def coverage_collection_config(node):
    try:
        return normalize_coverage_collection_config(node.get("coverage_collection_config"))
    except ValueError:
        return None


def config_digest(value):
    return digest(value)


def regression_config(node):
    from .vreg_contract import normalize_config
    return normalize_config(node.get("regression_config"))


def execution_round(connection, node_id):
    row = connection.execute(
        "SELECT * FROM regression_execution_rounds WHERE node_id=? ORDER BY round_number DESC LIMIT 1",
        (node_id,),
    ).fetchone()
    return dict(row) if row else None


def execution_binding(plan, node, value):
    return {"round_id": value["id"], "plan_node_id": node["parent_id"],
            "plan_revision": value["revision"], "plan_digest": value["plan_digest"]}


def _new_execution_round(db, plan, node, plan_digest, request_key, reviewer, reason, timestamp):
    identifier = "regression-round:" + uuid.uuid4().hex
    number = db.execute("SELECT COALESCE(MAX(round_number),0)+1 FROM regression_execution_rounds WHERE node_id=?",
                        (node["id"],)).fetchone()[0]
    db.execute(
        "INSERT INTO regression_execution_rounds(id,node_id,revision,round_number,plan_digest,request_key,"
        "requested_by,reason,status,requested_at,config_json) VALUES(?,?,?,?,?,?,?,?,'REQUESTED',?,?)",
        (identifier, node["id"], plan["revision"], number, plan_digest, request_key, reviewer, reason, timestamp,
         encoded(regression_config(node))),
    )
    return execution_round(db, node["id"])


def _round_files(store, connection, value):
    archived = json.loads(value.get("archive_json") or "{}")
    if archived:
        return [{"path": path, "sha256": item["sha256"],
                 "available": bool(item.get("archive_path") and (store.root / item["archive_path"]).is_file())}
                for path, item in archived.items()]
    receipt = connection.execute("SELECT payload_json FROM code_validations WHERE id=?",
                                 (value.get("validation_id"),)).fetchone()
    files = json.loads(receipt[0]).get("files", []) if receipt else []
    result = []
    for item in files:
        try:
            path = local_path(store, item["path"])
            available = file_snapshot(store, [path])[0]["sha256"] == item["sha256"]
        except (ValueError, RuntimeError):
            available = False
        result.append({**item, "available": available})
    return result


def regression_execution_state(store, connection, plan, node, parent_state=None):
    if not is_delivery(node) or vreg_stage(node) != "results":
        return None
    if parent_state is None:
        parent = next((n for n in plan["desired_state"] if n["id"] == node.get("parent_id")), None)
        parent_state = review_state(store, parent["id"], plan, parent, connection) if parent else None
    rows = [dict(row) for row in connection.execute(
        "SELECT * FROM regression_execution_rounds WHERE node_id=? ORDER BY round_number",
        (node["id"],),
    )]
    reasons = blockers(connection, node["id"])
    if not parent_state or not parent_state["completed"]:
        reasons.append("对应回归结果方案尚未批准或已经失效")
    if node.get("role") != "regression-results-deliverable":
        reasons.append("旧结果节点尚未具备完整回归合同，请重新形成方案")
    try:
        config = regression_config(node)
        if parent_state and config != parent_state.get("regression_config"):
            reasons.append("回归执行参数与对应批准方案不一致，请重新形成方案")
    except ValueError as exc:
        reasons.append("请重新形成包含回归组和执行参数的结果方案：" + str(exc))
    latest = rows[-1] if rows else None
    if latest:
        from .vreg_contract import normalize_config
        try:
            normalize_config(json.loads(latest["config_json"]))
        except (ValueError, TypeError):
            reasons.append("原轮次缺少确切的批准执行配置，不能重新回归或推定旧任务结束")
    if latest and latest["status"] == "INTERRUPTED":
        reasons.append("工具结果尚未核实，请 Main Agent 核对原轮次工具状态并登记证据")
    elif latest and latest["status"] in {"REQUESTED", "DISPATCHED", "RUNNING"}:
        reasons.append("当前回归轮次尚未结束，不能重复启动")
    if connection.execute("SELECT 1 FROM activities WHERE node_id=? AND status IN ('PENDING','RUNNING','WAITING_FOR_HUMAN','WAITING_FOR_PARENT')",
                          (node["id"],)).fetchone():
        reasons.append("对应回归结果交付仍有在途 Agent 工作")
    from .store import now
    if connection.execute("SELECT 1 FROM agent_assignments WHERE node_id=? AND status='ACTIVE' AND lease_expires_at>?",
                          (node["id"], now())).fetchone():
        reasons.append("对应回归结果交付仍有有效的 Agent 任务租约")
    def project(value):
        receipt = connection.execute("SELECT payload_json FROM code_validations WHERE id=?", (value.get("validation_id"),)).fetchone()
        report = json.loads(receipt[0]) if receipt else {}
        recorded_runs = any(
            check.get("claim") == "execution-evidence"
            and check.get("validation", {}).get("facts", {}).get("execution_binding") == execution_binding(plan, node, value)
            and check.get("validation", {}).get("facts", {}).get("run_records")
            for check in report.get("checks", [])
        )
        return {key: item for key, item in value.items() if key not in {"archive_json", "config_json"}} | {
            "round_id": value["id"],
            "execution_binding": execution_binding(plan, node, value),
            "files": _round_files(store, connection, value),
            "execution_confirmed": bool(recorded_runs),
        }
    return {"current": project(latest) if latest else None,
            "history": [project(value) for value in rows], "can_rerun": not reasons,
            "blockers": reasons}


def _archive_execution_round(store, db, value):
    """Preserve available project-owned evidence before fixed output paths change."""
    if not value or not value.get("validation_id"):
        return
    receipt = db.execute("SELECT payload_json FROM code_validations WHERE id=?", (value["validation_id"],)).fetchone()
    if not receipt:
        return
    archived = json.loads(value.get("archive_json") or "{}")
    for item in json.loads(receipt[0]).get("files", []):
        if item["path"] in archived:
            continue
        record = {"sha256": item["sha256"], "archive_path": None}
        archived[item["path"]] = record
        try:
            path = local_path(store, item["path"])
        except ValueError:
            continue
        if file_snapshot(store, [path])[0]["sha256"] != item["sha256"]:
            continue
        destination = store.state / "regression-rounds" / value["id"].split(":", 1)[1] / item["sha256"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(store.root / path, destination)
        if file_snapshot(store, [str(destination)])[0]["sha256"] != item["sha256"]:
            error("归档期间历史回归文件发生变化，请核对后重试")
        record["archive_path"] = str(destination.relative_to(store.root))
    db.execute("UPDATE regression_execution_rounds SET archive_json=? WHERE id=?", (encoded(archived), value["id"]))


def request_regression_rerun(store, body):
    """Persist execution intent; never start a simulator or restart the workstream."""
    from .store import now
    refresh(store)
    node_id = str(body.get("node", ""))
    reviewer = str(body.get("reviewer", "")).strip()
    reason = str(body.get("reason", "")).strip()
    key = str(body.get("request_key", "")).strip()
    if not reviewer or not key or len(key) > 160 or body.get("confirm") is not True:
        error("重新回归必须填写负责人、请求标识并再次确认")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        plan, node = selected(store, node_id, db)
        if plan["workstream"] != "VREG" or node.get("role") != "regression-results-deliverable":
            error("重新回归只能绑定当前回归结果交付节点")
        previous = db.execute("SELECT * FROM regression_execution_rounds WHERE node_id=? AND request_key=?", (node_id, key)).fetchone()
        if previous:
            if (previous["revision"] != body.get("revision") or previous["requested_by"] != reviewer
                    or previous["reason"] != reason or previous["request_digest"] != body.get("definition_digest")):
                error("此请求标识已用于不同的重新回归要求")
            result_id = previous["id"]
        else:
            state = review_state(store, node_id, plan, node, db)
            execution = state["regression_execution"]
            if body.get("revision") != plan["revision"] or body.get("definition_digest") != state["definition_digest"]:
                error("回归方案、结果或工作流版本已变化，请刷新后重新确认")
            if not execution["can_rerun"]:
                error("当前不能重新回归：" + "；".join(execution["blockers"]))
            _archive_execution_round(store, db, execution_round(db, node_id))
            parent = next(n for n in plan["desired_state"] if n["id"] == node["parent_id"])
            parent_state = review_state(store, parent["id"], plan, parent, db)
            if not parent_state["completed"]:
                error("归档期间回归方案或依赖发生变化，请重新确认")
            value = _new_execution_round(db, plan, node, parent_state["definition_digest"], key, reviewer, reason, now())
            db.execute("UPDATE regression_execution_rounds SET request_digest=? WHERE id=?", (body["definition_digest"], value["id"]))
            result_id = value["id"]
    refresh(store)
    state = review_state(store, node_id)
    result = next(r for r in state["regression_execution"]["history"] if r["id"] == result_id)
    return {"node_id": node_id, "revision": state["revision"], "round": result,
            "regression_execution": state["regression_execution"],
            "auto_closure": store.evaluate_closure("VREG")}


def start_regression_execution(store, node_id, binding, actor):
    """Main Agent records a tool invocation, not completion or live simulator proof."""
    from .store import PROJECT_AGENT_ACTOR, now
    from .vreg_contract import normalize_binding
    try:
        binding = normalize_binding(binding)
    except ValueError as exc:
        error("回归执行轮次绑定无效：" + str(exc))
    refresh(store)
    if actor != PROJECT_AGENT_ACTOR:
        error("只有 Project Main Agent 可以登记回归工具调用")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        plan, node = selected(store, node_id, db)
        if plan["workstream"] != "VREG" or node.get("role") != "regression-results-deliverable":
            error("回归调用必须绑定当前回归结果交付")
        value = execution_round(db, node_id)
        if not value or binding != execution_binding(plan, node, value):
            error("回归调用不属于当前执行轮次")
        parent = next(n for n in plan["desired_state"] if n["id"] == node["parent_id"])
        parent_state = review_state(store, parent["id"], plan, parent, db)
        if not parent_state["completed"] or parent_state["definition_digest"] != value["plan_digest"] or blockers(db, node_id):
            error("回归方案或授权已失效，不能登记工具调用")
        if regression_config(node) != regression_config(parent):
            error("回归执行参数与对应批准方案不一致，不能登记工具调用")
        from .vreg_contract import normalize_config
        try:
            original_config = normalize_config(json.loads(value["config_json"]))
        except (ValueError, TypeError):
            error("原轮次缺少确切的批准执行配置，不能登记工具调用")
        if original_config != regression_config(node):
            error("当前执行配置与本轮原批准配置不一致，不能登记工具调用")
        if value["status"] == "INTERRUPTED":
            error("原轮次工具状态尚未核实；请核对任务后沿同一轮次登记真实证据，不得重复提交")
        if value["status"] not in {"REQUESTED", "DISPATCHED", "RUNNING"}:
            error("本轮已有验证结果；重新执行需要新的回归轮次")
        db.execute("UPDATE regression_execution_rounds SET status='RUNNING' WHERE id=?", (value["id"],))
    return review_state(store, node_id)["regression_execution"]


def regression_history_content(store, node_id, round_id, path):
    plan, node = selected(store, node_id)
    if plan["workstream"] != "VREG" or not is_delivery(node) or vreg_stage(node) != "results":
        error("此节点不提供回归历史文件")
    with store.read_connect() as db:
        row = db.execute("SELECT * FROM regression_execution_rounds WHERE id=? AND node_id=?", (round_id, node_id)).fetchone()
        if not row:
            error("当前项目和交付节点中找不到此回归轮次")
        value = dict(row)
        files = {f["path"]: f for f in _round_files(store, db, value)}
        item = files.get(path)
        if not item or not item["available"]:
            error("此历史文件未登记或已经不可用；不能用当前文件代替历史证据")
        archived = json.loads(value["archive_json"] or "{}")
        resolved = store.root / local_path(store, archived[path]["archive_path"] if path in archived else path)
    if resolved.stat().st_size > 2 * 1024 * 1024:
        error("历史文件超过 2 MiB，不能在 Dashboard 预览")
    data = resolved.read_bytes()
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        error("历史回归文件摘要已变化，不能预览为旧证据")
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        error("Dashboard 只预览 UTF-8 历史回归文件")
    return {"node_id": node_id, "round_id": round_id, "path": path, "sha256": item["sha256"], "content": content}


def vcov_stage(node):
    role = node.get("role", "")
    if role.startswith("coverage-implementation-"):
        return "implementation"
    if role.startswith("coverage-convergence-"):
        return "convergence"
    claims = set(node.get("capabilities", []))
    if claims == VCOV_IMPLEMENTATION_CLAIMS:
        return "implementation"
    if claims == VCOV_CONVERGENCE_CLAIMS:
        return "convergence"
    return None


def vcov_role(node):
    stage = vcov_stage(node)
    if stage:
        return f"coverage-{stage}-" + ("plan" if is_plan(node) else "deliverable")
    return node.get("role")


def vreg_stage(node):
    role = node.get("role", "")
    if role.startswith("regression-infrastructure-"):
        return "infrastructure"
    if role.startswith("regression-results-"):
        return "results"
    claims = set(node.get("capabilities", []))
    if claims == VREG_INFRASTRUCTURE_CLAIMS:
        return "infrastructure"
    if claims == VREG_RESULTS_CLAIMS:
        return "results"
    return None


def vreg_role(node):
    stage = vreg_stage(node)
    if stage:
        return f"regression-{stage}-" + ("plan" if is_plan(node) else "deliverable")
    return node.get("role")


def stage(node, workstream):
    return vcov_stage(node) if workstream == "VCOV" else vreg_stage(node) if workstream == "VREG" else None


def node_label(node, workstream):
    if workstream == "VCOV":
        return VCOV_ROLE_LABELS.get(vcov_role(node), "覆盖率工作节点")
    if workstream == "VREG":
        return VREG_ROLE_LABELS.get(vreg_role(node), "回归工作节点")
    return profile(workstream).get("plan_term", "代码实现方案") if is_plan(node) else profile(workstream)["delivery_label"]


def profile(workstream):
    try:
        return PROFILES[workstream]
    except KeyError:
        error("代码方案工作流必须是 " + "、".join(CODE_WORKSTREAMS))


def node_workstream(node_id):
    return next(
        (name for name in CODE_WORKSTREAMS if node_id.startswith(f"workstream:{name}:")),
        None,
    )


def protected(identifier):
    return identifier.startswith((
        "art.code_plan:", "art.code:",
        *(value["cap_prefix"] for value in PROFILES.values()),
    ))


def refresh_token(store):
    """Use committed semantic writes, not a post-commit database stat race."""
    with store.read_connect() as db:
        counter = db.execute('SELECT version FROM agent_service_changes WHERE id=1').fetchone()[0]
        paths = {store.state / 'project.json'}
        paths.update(store.root / r[0] for r in db.execute('SELECT path FROM code_watched_files'))
        paths.update(store.root / r[0] for r in db.execute('SELECT path FROM documents'))
    stamps = []
    for path in sorted(paths):
        try:
            stat = path.stat()
            stamps.append((str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino))
        except OSError:
            stamps.append((str(path), None))
    return counter, digest(stamps)


def ids(key, workstream="VENV"):
    suffix = key if workstream == "VENV" else workstream.lower() + ":" + key
    return "art.code_plan:" + suffix, "art.code:" + suffix, profile(workstream)["cap_prefix"] + key


def error(message):
    from .store import HarnessError
    raise HarnessError(message)


def selected(store, node_id, connection=None):
    workstream = node_workstream(node_id)
    if workstream is None:
        error("当前项目或版本中找不到此代码工作节点，请返回节点列表")
    plan = store._read_workstream(connection, workstream) if connection else store.workstream(workstream)
    node = next((n for n in plan["desired_state"] if n["id"] == node_id), None)
    if not modern(plan) or not node or node["role"] not in ROLES:
        error("当前项目或版本中找不到此代码工作节点，请返回节点列表")
    return plan, node


def strings(item, field):
    value = item.get(field)
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        error(f"代码方案的 {field} 必须是非空字符串数组")
    return list(dict.fromkeys(v.strip() for v in value))


def local_path(store, value):
    from .store import relative_path
    return relative_path(store.root, value)


def file_snapshot(store, paths, *, required=False):
    result = []
    for value in sorted(set(paths)):
        path = Path(value) if Path(value).is_absolute() else store.root / value
        if not path.is_file():
            if required:
                error(f"交付文件或验证证据不存在：{value}")
            result.append({"path": value, "sha256": None})
        else:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
            cache = getattr(store, "_code_file_digests", {})
            cached = cache.get(str(path))
            if cached is None or cached[0] != stamp:
                content_hash = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        content_hash.update(chunk)
                after = path.stat()
                if stamp != (after.st_mtime_ns, after.st_ctime_ns, after.st_size, after.st_ino):
                    error("读取期间文件发生变化，请刷新后重新检查")
                cached = (stamp, content_hash.hexdigest())
                cache[str(path)] = cached
                store._code_file_digests = cache
            result.append({"path": value, "sha256": cached[1]})
    return result


def dependency_snapshot(connection, node):
    result = []
    for row in connection.execute(
        "SELECT n.id,n.title,n.status,n.data_json FROM edges e LEFT JOIN nodes n ON n.id=e.target "
        "WHERE e.source=? AND e.relation='DEPENDS_ON' ORDER BY e.target", (node["id"],),
    ):
        data = json.loads(row["data_json"] or "{}")
        result.append({"id": row["id"], "title": row['title'], "status": row["status"], "current": data.get("current"),
                       **({"last_current": data["last_current"]} if not data.get("current") and data.get("last_current") else {})})
    return result


def retains_node_version(workstream, node):
    """Result-scope replans retain unchanged coverage models and executors."""
    return (workstream in {"VENV", "VSTIM", "VCHK", "VCASE"}
            or workstream == "VCOV" and vcov_stage(node) == "implementation"
            or workstream == "VREG" and vreg_stage(node) == "infrastructure")


def node_revision(plan, node):
    """An unchanged code package keeps its original version in a newer scope."""
    if retains_node_version(plan["workstream"], node):
        match = re.fullmatch(
            r"workstream:" + plan["workstream"] + r":r([0-9]+):desired:.+", node["id"],
        )
        if match and 0 < int(match[1]) <= plan["revision"]:
            return int(match[1])
    return plan["revision"]


def coverage_exclusion_scope_digest(plan, node):
    """Bind an owner-provided exclude file to one convergence delivery scope."""
    return digest({
        "workstream": plan["workstream"], "revision": plan["revision"],
        "node_id": node["id"], "implementation_key": node.get("implementation_key"),
        "parent_id": node.get("parent_id"), "inputs": node.get("inputs", []),
        "output_paths": node.get("output_paths", []),
        "acceptance_criteria": node.get("acceptance_criteria", []),
        "capabilities": node.get("capabilities", []),
    })


def coverage_exclusion_state(store, connection, plan, node):
    """Return immutable approval history and the current file-level approval."""
    rows = [dict(row) for row in connection.execute(
        "SELECT * FROM coverage_exclusion_approvals WHERE node_id=? ORDER BY rowid",
        (node["id"],),
    )]
    scope = coverage_exclusion_scope_digest(plan, node)
    latest = rows[-1] if rows else None
    current = None
    if latest and latest["workstream"] == "VCOV" and latest["revision"] == plan["revision"] \
            and latest["scope_digest"] == scope:
        observed = file_snapshot(store, [latest["path"]])
        if observed and observed[0]["sha256"] == latest["sha256"]:
            current = dict(latest)
    return {"scope_digest": scope, "current": current, "latest": latest, "history": rows}


def self_output_inputs(store, node):
    """A plan cannot consume files produced by its own delivery."""
    return sorted(path for path in node.get("input_files", []) if any(
        store._scopes_overlap(str((store.root / path).resolve()),
                              str((store.root / output).resolve()))
        for output in node.get("output_paths", [])))


def feedback_report_paths(store, connection, plan, node):
    """Approved planning feedback, never checked evidence or delivery output."""
    if plan["workstream"] != "VCASE" and not node.get("planning_feedback_files"):
        return set()
    evidence = set(node.get("output_paths", []))
    family = [node["id"]] + [n["id"] for n in plan["desired_state"] if n.get("parent_id") == node["id"]]
    for identifier in family:
        for row in connection.execute("SELECT payload_json FROM code_validations WHERE node_id=?", (identifier,)):
            evidence.update(item["path"] for item in validation_evidence_files(json.loads(row[0])))
    paths = set()
    for path in node.get("planning_feedback_files", node.get("input_files", []) if plan["workstream"] == "VCASE" else []):
        if (any(store._scopes_overlap(path, output) for output in evidence)
                or not path.endswith(".json")):
            continue
        source = store.root / path
        if source.is_symlink() or store.root not in source.resolve().parents:
            continue
        try:
            report = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            continue
        if isinstance(report, dict) and report.get("schema") == "HoleAnalysisReport/1":
            paths.add(path)
    return paths


def bind_feedback_context(store, connection, plan, node, approved=None):
    """Anchor only bytes proven to be present in an actual approved plan.

    For old projects this is a conservative metadata migration: if the live
    report no longer matches the approved hash we cannot infer its old schema.
    It never synthesizes, copies, or replaces an owner approval.
    """
    if not is_plan(node) or (plan["workstream"] != "VCASE" and not node.get("planning_feedback_files")):
        return
    if approved is None:
        for row in connection.execute(
                "SELECT payload_json FROM code_artifact_versions WHERE artifact_id=? ORDER BY version DESC",
                (ids(node["implementation_key"], plan["workstream"])[0],)):
            candidate = json.loads(row[0])
            if (candidate.get("definition", {}).get("id") == node["id"]
                    and (candidate.get("review") or {}).get("verdict") == "APPROVE"):
                approved = candidate
                break
    if approved is None:
        return
    anchored = {item["path"]: item["sha256"] for item in approved.get("sources", [])}
    for source in file_snapshot(store, feedback_report_paths(store, connection, plan, node)):
        if source["sha256"] and source["sha256"] == anchored.get(source["path"]):
            connection.execute("INSERT OR IGNORE INTO code_feedback_inputs VALUES(?,?,?,?)",
                               (node["id"], source["path"], source["sha256"], approved["review"]["id"]))


def plan_input_snapshot(store, connection, plan, node):
    """A downstream hole report motivates a fixed VCASE scope, not a live input.

    New holes require explicit impact analysis/replanning. Native code, specs,
    profiles, and all evidence consumed by validation remain live inputs.
    """
    sources = file_snapshot(store, node.get("input_files", []))
    if plan["workstream"] != "VCASE" and not node.get("planning_feedback_files"):
        return sources
    parent_id = node.get("parent_id") if is_delivery(node) else node["id"]
    eligible = feedback_report_paths(store, connection, plan, node)
    anchored = {row["path"]: row["sha256"] for row in connection.execute(
        "SELECT path,sha256 FROM code_feedback_inputs WHERE node_id=?", (parent_id,))}
    for source in sources:
        if source["sha256"] and source["path"] in eligible and source["path"] in anchored:
            source["sha256"] = anchored[source["path"]]
    return sources


def identity(store, connection, plan, node):
    deps = dependency_snapshot(connection, node)
    manifest_path = store.state / 'project.json'
    stat = manifest_path.stat()
    stamp = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    cached = getattr(store, '_code_project_identity', None)
    if cached is None or cached[0] != stamp:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        cached = (stamp, {k: manifest.get(k) for k in ('project_name', 'baseline_revision', 'dut', 'rtl_roots', 'docs_roots', 'verification_inputs')})
        store._code_project_identity = cached
    payload = {"revision": node_revision(plan, node), "node": node, "dependencies": deps,
               "sources": plan_input_snapshot(store, connection, plan, node),
               "project": str(store.root), "project_inputs": cached[1],
               "questions": [dict(r) for r in connection.execute(
                   'SELECT id,status,answer_option,answer_text,answered_at FROM agent_questions WHERE target=? ORDER BY id',
                   (node['id'],))]}
    if is_delivery(node):
        payload["outputs"] = file_snapshot(store, node["output_paths"])
        if plan["workstream"] == "VREG" and vreg_stage(node) == "results":
            value = execution_round(connection, node["id"])
            payload["execution_binding"] = execution_binding(plan, node, value) if value else None
    if plan["workstream"] == "VCOV" and is_delivery(node) and vcov_stage(node) == "convergence":
        exclusion = coverage_exclusion_state(store, connection, plan, node)
        payload["coverage_exclusion"] = ({
            key: exclusion["current"][key]
            for key in ("id", "path", "sha256", "reviewer", "created_at")
        } if exclusion["current"] else None)
    # Status is an availability gate, not a different version of an input.
    # Keep the historical digest for VALID dependencies while making a
    # status-only outage/recovery leave the approved subject unchanged.
    subject = {**payload, "dependencies": dependency_subject(deps)}
    return digest(subject), payload


def blockers(connection, node_id):
    reasons = []
    for table, field, condition, label in (
        ("agent_questions", "target", "status='OPEN'", "存在尚未解决的负责人提问"),
        ("human_actions", "target", "status='OPEN'", "存在尚未处理的负责人意见"),
        ("findings", "subject", "status='OPEN'", "存在尚未处理的问题记录"),
        ("review_feedback_items", "node_id", "status IN ('DRAFT','PENDING','WAITING_FOR_HUMAN')", "审批意见尚未处理完成"),
    ):
        if connection.execute(f"SELECT 1 FROM {table} WHERE {field}=? AND {condition} LIMIT 1", (node_id,)).fetchone():
            reasons.append(label)
    return reasons


def validation_current(store, connection, plan, node, signature):
    row = connection.execute("SELECT * FROM code_validations WHERE node_id=? ORDER BY rowid DESC LIMIT 1", (node["id"],)).fetchone()
    if not row:
        return None
    value = json.loads(row["payload_json"])
    value.update(id=row["id"], created_at=row["created_at"])
    evidence_files = validation_evidence_files(value)
    value["current"] = (row["signature"] == signature and row["revision"] == node_revision(plan, node)
                        and evidence_files == file_snapshot(store, [v["path"] for v in evidence_files]))
    if plan["workstream"] == "VCOV" and value.get("coverage_contract") != VCOV_VALIDATION_CONTRACT:
        value["current"] = False
    if plan["workstream"] == "VCOV" and vcov_stage(node) == "convergence" and value["current"]:
        sources, source_reasons = _coverage_collection_sources(
            store, connection, coverage_collection_config(node),
        )
        expected_bindings = sorted(
            (item["execution_binding"] for item in sources), key=lambda item: item["round_id"],
        )
        observed_bindings = sorted(
            value.get("coverage_execution_bindings", []), key=lambda item: item.get("round_id", ""),
        )
        if source_reasons or observed_bindings != expected_bindings:
            value["current"] = False
    if plan["workstream"] == "VCASE":
        if value.get("testcase_contract") != VCASE_VALIDATION_CONTRACT:
            value["current"] = False
        elif case_confirmation_blockers(connection, node, [
                item for check in value.get("checks", []) if check.get("claim") == "case-implementation"
                for item in check.get("validation", {}).get("facts", {}).get("case_records", [])]):
            value["current"] = False
    if plan["workstream"] == "VREG" and vreg_stage(node) == "results":
        current_round = execution_round(connection, node["id"])
        if (value.get("regression_contract") != VREG_VALIDATION_CONTRACT or not current_round
                or value.get("execution_binding") != execution_binding(plan, node, current_round)):
            value["current"] = False
        elif value["current"]:
            checks = copy.deepcopy(value.get("checks", []))
            reasons = _vreg_result_blockers(store, connection, plan, node, checks)
            if reasons or checks != value.get("checks", []):
                value["current"] = False
    return value


def validation_evidence_files(validation):
    """Keep all checked evidence; the registration envelope is an audit source.

    Older receipts did not name their envelope. It is the one file outside the
    output files, dedicated evidence reports and their verified artifacts. If
    that boundary is ambiguous, retain every file rather than dropping evidence.
    """
    files = validation.get("files", [])
    referenced = {item["path"] for item in validation.get("code_files", [])}
    for check in validation.get("checks", []):
        referenced.add(check["report"])
        referenced.update(item["path"] for item in check.get("validation", {}).get("artifacts", []))
    envelopes = [item["path"] for item in files if item["path"] not in referenced]
    explicit = validation.get("registration_report", {}).get("path")
    if len(envelopes) != 1 or explicit is not None and envelopes != [explicit]:
        return files
    return [item for item in files if item["path"] != envelopes[0]]


def validation_subject(validation):
    """The checked code/evidence/conclusions, excluding registration metadata."""
    subject = {key: value for key, value in validation.items()
               if key not in {"id", "created_at", "current", "summary", "registration_report"}}
    subject["files"] = validation_evidence_files(validation)
    return subject


def _coverage_collection_sources(store, connection, config, *, require_execution=True):
    """Resolve approved VREG configs and, for delivery, immutable execution rounds."""
    resolved = []
    reasons = []
    if config is None:
        return resolved, ["覆盖率收敛方案缺少合法的 coverage_collection_config，请重新形成方案"]
    from .store import HarnessError
    try:
        vreg = store._read_workstream(connection, "VREG")
    except HarnessError as exc:
        return resolved, ["当前 VREG 回归结果方案不可用：" + str(exc)]
    plans = {item["id"]: item for item in vreg["desired_state"]
             if is_plan(item) and vreg_stage(item) == "results"}
    for source in config["regression_sources"]:
        referenced = plans.get(source["plan_node_id"])
        if referenced is None or source["plan_revision"] != vreg["revision"]:
            reasons.append("coverage_collection_config 引用的 VREG 回归结果方案已经变化")
            continue
        try:
            observed_digest = config_digest(regression_config(referenced))
        except ValueError:
            reasons.append("coverage_collection_config 引用的 VREG regression_config 已不合法")
            continue
        if observed_digest != source["regression_config_digest"]:
            reasons.append("coverage_collection_config 引用的 regression_config 摘要已经变化")
            continue
        source_state = review_state(store, referenced["id"], vreg, referenced, connection)
        if not source_state["completed"]:
            reasons.append("引用的 VREG 回归结果方案尚未批准：" + referenced["title"])
            continue
        normalized_config = regression_config(referenced)
        basic = {**source,
                 "regression_group": normalized_config["regression_group"],
                 "submit_profile_id": normalized_config["submit_profile"]["profile_id"],
                 "regression_config": normalized_config}
        if not require_execution:
            resolved.append(basic)
            continue
        delivery = next((item for item in vreg["desired_state"]
                         if item.get("parent_id") == referenced["id"]), None)
        if delivery is None:
            reasons.append("引用的 VREG 回归结果方案尚未建立结果交付：" + referenced["title"])
            continue
        value = execution_round(connection, delivery["id"])
        if value is None:
            reasons.append("引用的 VREG 回归结果方案尚未登记执行轮次：" + referenced["title"])
            continue
        if value["revision"] != vreg["revision"] or value["plan_digest"] != source_state["definition_digest"]:
            reasons.append("引用的 VREG 执行轮次没有绑定当前批准方案：" + referenced["title"])
            continue
        try:
            round_digest = config_digest(json.loads(value["config_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            reasons.append("引用的 VREG 执行轮次缺少不可变 regression_config：" + referenced["title"])
            continue
        if round_digest != source["regression_config_digest"]:
            reasons.append("引用的 VREG 执行轮次与收敛方案中的 regression_config 不一致")
            continue
        if value["status"] not in {"VALIDATED", "FAILED", "ACCEPTED"}:
            reasons.append("引用的 VREG 执行轮次尚未结束并形成可分析 VDB：" + referenced["title"])
            continue
        resolved.append({**basic, "delivery_node_id": delivery["id"],
                         "execution_binding": execution_binding(vreg, delivery, value),
                         "round_status": value["status"]})
    return resolved, reasons


def _legacy_completion(connection, node_id, revision, signature, subject, reviews):
    """Recognize an existing ID-bound approval for the same reviewed evidence."""
    by_digest = {row["definition_digest"]: row for row in reviews}
    for row in connection.execute(
        "SELECT id,payload_json FROM code_validations WHERE node_id=? AND revision=? AND signature=? ORDER BY rowid DESC",
        (node_id, revision, signature),
    ):
        if validation_subject(json.loads(row["payload_json"])) != subject:
            continue
        legacy_subject = {key: value for key, value in json.loads(row["payload_json"]).items()
                          if key not in {"id", "created_at", "current"}}
        for old_digest in (
            digest({"definition": signature, "validation": row["id"]}),
            digest({"definition": signature, "validation": digest(legacy_subject)}),
        ):
            if old_digest in by_digest:
                return by_digest[old_digest]
    return None


def review_state(store, node_id, plan=None, node=None, connection=None):
    if connection is None:
        with store.read_connect() as db:
            return review_state(store, node_id, plan, node, db)
    if plan is None or node is None:
        plan, node = selected(store, node_id, connection)
    signature, snapshot = identity(store, connection, plan, node)
    validation = validation_current(store, connection, plan, node, signature) if is_delivery(node) else None
    subject = validation_subject(validation) if validation and validation["current"] else None
    approval_digest = digest({"definition": signature, "validation": digest(subject) if subject is not None else None})
    history = [dict(r) for r in connection.execute("SELECT * FROM node_plan_reviews WHERE node_id=? ORDER BY rowid", (node_id,))]
    opinions = [dict(r) for r in connection.execute("SELECT * FROM node_plan_section_reviews WHERE node_id=? ORDER BY rowid", (node_id,))]
    feedback = feedback_state(connection, plan, node, approval_digest)
    changes = store._review_change_items(connection, [r["id"] for r in opinions])
    for row in opinions:
        row["change_items"] = changes.get(row["id"], [])
        row["feedback_items"] = [v for v in feedback["items"] if v["review_id"] == row["id"]]
    latest_opinion = max((r["created_at"] for r in opinions), default="")
    revision = node_revision(plan, node)
    eligible_reviews = [r for r in history if r["revision"] == revision
                        and r["created_at"] >= latest_opinion]
    completion = next((r for r in reversed(eligible_reviews) if r["definition_digest"] == approval_digest), None)
    if completion is None and subject is not None and eligible_reviews:
        completion = _legacy_completion(connection, node_id, revision, signature,
                                        subject, eligible_reviews)
    reasons = blockers(connection, node_id)
    conflicts = self_output_inputs(store, node)
    if conflicts:
        reasons.append("方案输入包含本节点交付输出，请修订方案以避免生成报告后反复审批：" + "、".join(conflicts))
    workstream = plan["workstream"]
    expected_dependencies = (set(node['inputs']) if is_plan(node)
                             else {ids(node['implementation_key'], workstream)[0]})
    if {v['id'] for v in snapshot['dependencies']} != expected_dependencies:
        reasons.append("前置结果与批准范围不一致，请重新登记方案依赖")
    reasons.extend("前置结果尚未验收或已经变化：" + str(v["title"] or '前置交付') for v in snapshot["dependencies"] if v["status"] != "VALID" or not v["current"])
    if any(v["sha256"] is None for v in snapshot["sources"]):
        reasons.append("方案输入文件缺失")
    if is_delivery(node) and not (validation and validation["current"] and validation["ready"]):
        reasons.append("Agent 尚未完成当前代码版本的验证，或验证证据已经变化")
    if workstream == "VREG":
        if is_delivery(node):
            parent = next((n for n in plan["desired_state"] if n["id"] == node.get("parent_id")), None)
            if (parent is None or not is_plan(parent) or vreg_stage(parent) != vreg_stage(node)
                    or parent.get("implementation_key") != node.get("implementation_key")
                    or parent.get("required") != node.get("required")):
                reasons.append("回归交付与当前对应方案不一致，请重新形成方案")
        expected_claims = VREG_INFRASTRUCTURE_CLAIMS if vreg_stage(node) == "infrastructure" else VREG_RESULTS_CLAIMS
        if (vreg_stage(node) is None or set(node.get("capabilities", [])) != expected_claims
                or node.get("role") not in {"code-plan", "code-deliverable", *VREG_PLAN_ROLES, *VREG_DELIVERY_ROLES}):
            reasons.append("回归节点类型与验证要求不一致，请重新形成方案")
        inputs = node.get("inputs", [])
        if vreg_stage(node) == "infrastructure" and any(
                not value.startswith(("cap.doc:", "cap.venv:")) for value in inputs):
            reasons.append("回归基础设施只能依赖已验收文档和验证环境，不能等待最终回归结果，请重新形成方案")
        if vreg_stage(node) == "results":
            try:
                config = regression_config(node)
                if config["submit_profile"]["submit_file"] not in node.get("input_files", []):
                    reasons.append("回归 submit 配置未纳入当前方案输入，请重新形成方案")
                elif next((source["sha256"] for source in snapshot["sources"]
                           if source["path"] == config["submit_profile"]["submit_file"]), None) != config["submit_profile"]["submit_file_digest"]:
                    reasons.append("回归 submit 文件已变化，必须重新形成包含当前文件版本的结果方案")
                from .vreg_contract import group_identity
                for other in plan["desired_state"]:
                    if not is_plan(other) or vreg_stage(other) != "results" or other["implementation_key"] == node["implementation_key"]:
                        continue
                    other_config = regression_config(other)
                    if (config["regression_group"] == other_config["regression_group"]
                            or group_identity(config) == group_identity(other_config)):
                        reasons.append("同一回归组对应多个结果方案，请重新形成方案")
                if is_delivery(node) and parent is not None and config != regression_config(parent):
                    reasons.append("回归执行参数与对应批准方案不一致，请重新形成方案")
                if is_plan(node):
                    delivery = next((other for other in plan["desired_state"] if other.get("parent_id") == node_id), None)
                    previous_round = execution_round(connection, delivery["id"]) if delivery else None
                    if (previous_round and previous_round["plan_digest"] != approval_digest
                            and previous_round["status"] in {"DISPATCHED", "RUNNING", "INTERRUPTED"}):
                        reasons.append("旧回归任务尚未核实结束，请先核对旧任务并登记真实证据，再重新批准方案")
            except ValueError as exc:
                reasons.append("回归结果方案缺少合法回归组或执行参数，请重新形成方案：" + str(exc))
            infrastructure = {ids(n["implementation_key"], "VREG")[2]
                              for n in plan["desired_state"] if is_plan(n) and vreg_stage(n) == "infrastructure"}
            own_inputs = {value for value in inputs if value.startswith("cap.vreg:")}
            if not own_inputs or not own_inputs <= infrastructure:
                reasons.append("回归结果方案必须明确关联当前回归基础设施能力，不能依赖结果能力，请重新形成方案")
            if "cap.vcov:coverage-collection" not in inputs:
                reasons.append("回归结果方案必须依赖已验收的覆盖率采集实现 cap.vcov:coverage-collection")
            if is_delivery(node):
                current_round = execution_round(connection, node_id)
                if current_round is None:
                    reasons.append("当前结果交付未登记执行轮次，请重新形成方案")
                elif parent is not None:
                    parent_state = review_state(store, parent["id"], plan, parent, connection)
                    if current_round["plan_digest"] != parent_state["definition_digest"] or current_round["revision"] != plan["revision"]:
                        reasons.append("当前回归轮次未绑定当前批准方案，请重新形成方案")
                if validation and validation["current"] and validation["ready"]:
                    for capability in ("cap.vcov:coverage-collection-evidence", "cap.vcov:hole-analysis-evidence"):
                        current = connection.execute("SELECT status FROM nodes WHERE id=?", (capability,)).fetchone()
                        if current is None or current["status"] != "VALID":
                            reasons.append("回归结果最终验收仍需当前覆盖率收敛能力：" + capability)
    if workstream == "VCOV":
        if is_delivery(node):
            parent = next((n for n in plan["desired_state"] if n["id"] == node.get("parent_id")), None)
            if (parent is None or not is_plan(parent) or vcov_stage(parent) != vcov_stage(node)
                    or parent.get("implementation_key") != node.get("implementation_key")
                    or parent.get("required") != node.get("required")):
                reasons.append("覆盖率交付与当前对应方案不一致，请重新形成方案")
        expected_claims = VCOV_IMPLEMENTATION_CLAIMS if vcov_stage(node) == "implementation" else VCOV_CONVERGENCE_CLAIMS
        if vcov_stage(node) is None or set(node.get("capabilities", [])) != expected_claims:
            reasons.append("覆盖率节点类型与验证要求不一致，请重新形成方案")
        if "cap.vreg:executor-ready" not in node.get("inputs", []):
            reasons.append("前置结果缺少已验收的回归执行能力，请重新形成方案")
        if vcov_stage(node) == "implementation" and coverage_scope(node) is None:
            reasons.append("覆盖率实现方案缺少合法的覆盖范围，请重新形成方案")
        if vcov_stage(node) == "implementation" and coverage_implementation_config(node) is None:
            reasons.append("覆盖率实现方案缺少合法的 coverage_implementation_config，请重新形成方案")
        if vcov_stage(node) == "convergence":
            collection_config = coverage_collection_config(node)
            resolved_sources, source_reasons = _coverage_collection_sources(
                store, connection, collection_config, require_execution=is_delivery(node),
            )
            reasons.extend(source_reasons)
            inventories, inventory_reasons = _vcov_expected_inventories(store, connection, plan, node)
            reasons.extend(inventory_reasons)
            if is_delivery(node) and validation and validation["current"]:
                for claim in sorted(VCOV_CONVERGENCE_CLAIMS):
                    observed = {check.get("validation", {}).get("facts", {}).get("coverage_inventory_digest")
                                for check in validation.get("checks", []) if check.get("claim") == claim}
                    if not inventories or observed != inventories:
                        reasons.append("覆盖率收敛证据的覆盖对象清单与已验收实现不一致：" + claim)
    complete = bool(completion and not reasons)
    exclusion = (coverage_exclusion_state(store, connection, plan, node)
                 if workstream == "VCOV" and is_delivery(node) and vcov_stage(node) == "convergence"
                 else None)
    return {"node_id": node_id, "workstream": workstream, "revision": revision,
            "workstream_revision": plan["revision"],
            "definition_digest": approval_digest, "input_signature": signature,
            "status": "APPROVED" if complete else "PENDING", "completed": complete,
            "validity": assessment(
                completion, blockers=reasons, evidence_current=not is_delivery(node) or bool(validation and validation["current"]),
                has_history=bool(history)),
            "current_completion": completion if complete else None,
            "completion_reviews": history, "reviews": opinions,
            "sections": [{"section": "writing-plan", "status": "APPROVED" if complete else "PENDING"}],
            "feedback": feedback, "can_approve": not reasons, "blockers": reasons,
            "validation": validation, "code_files": snapshot.get("outputs", []),
            "coverage_exclusion": exclusion,
            "coverage_implementation_config": node.get("coverage_implementation_config"),
            "coverage_collection_config": node.get("coverage_collection_config"),
            "coverage_regression_sources": (resolved_sources if workstream == "VCOV" and vcov_stage(node) == "convergence" else []),
            "regression_config": node.get("regression_config"),
            "regression_execution": (regression_execution_state(store, connection, plan, node)
                                     if workstream == "VREG" and vreg_stage(node) == "results" else None),
            "dependencies": snapshot['dependencies'], "sources": snapshot['sources']}


def feedback_state(connection, plan, node, signature):
    rows = [dict(r) for r in connection.execute("SELECT * FROM review_feedback_items WHERE node_id=? ORDER BY rowid", (node["id"],))]
    revision = node_revision(plan, node)
    current = [r for r in rows if r["revision"] == revision]
    drafts = [r for r in current if r["status"] == "DRAFT"]
    pending = [r for r in current if r["status"] in {"PENDING", "WAITING_FOR_HUMAN"}]
    return {"node_id": node["id"], "revision": revision, "definition_digest": signature,
            "document_digest": "", "draft_count": len(drafts), "processing_count": len(pending),
            "waiting_for_human_count": sum(r["status"] == "WAITING_FOR_HUMAN" for r in pending),
            "unresolved_count": len(drafts) + len(pending), "can_approve": not drafts and not pending,
            "resolved_count": sum(r["status"] == "RESOLVED" for r in current),
            "draft_items": drafts, "processing_items": pending, "items": rows, "current_items": current,
            "batch_ids": sorted({r["batch_id"] for r in pending if r["batch_id"]})}


def validate_claims(workstream, claims):
    """Reject packages that cannot prove the workstream-specific delivery contract."""
    claims = set(claims)
    unsupported = claims - profile(workstream)["allowed_claims"]
    if unsupported:
        error(f"未知的 {workstream} 验证要求：" + ", ".join(sorted(unsupported)))
    if workstream == "VSTIM":
        if not claims & {"stimulus-implementation", "corner-scenarios"}:
            error("VSTIM 工作包至少包含一项激励实现能力")
        required = {"reachability-evidence", "determinism-evidence"}
        if not required <= claims:
            error("VSTIM 代码交付必须同时证明场景可达和同配置同 seed 可复现")
    elif workstream == "VCHK":
        pairs = {
            "reference-model": "reference-model-evidence",
            "scoreboard": "scoreboard-evidence",
            "assertions": "assertion-evidence",
        }
        selected = {claim for claim in pairs if claim in claims}
        if not selected:
            error("VCHK 工作包至少包含参考模型、scoreboard 或断言中的一项实现")
        missing = {pairs[claim] for claim in selected} - claims
        if missing:
            error("VCHK 实现必须提供对应的运行证据：" + ", ".join(sorted(missing)))
        orphan = {value for value in pairs.values() if value in claims} - {pairs[claim] for claim in selected}
        if orphan:
            error("VCHK 运行证据缺少同工作包实现：" + ", ".join(sorted(orphan)))
    elif workstream == "VCASE" and claims != {"case-implementation", "targeted-evidence"}:
        error("VCASE 代码交付必须同时包含测试用例实现和定向执行证据")
    elif workstream == "VCOV":
        if frozenset(claims) not in {frozenset(VCOV_IMPLEMENTATION_CLAIMS), frozenset(VCOV_CONVERGENCE_CLAIMS)}:
            error("VCOV 节点必须是覆盖率实现或覆盖率收敛；两类节点的验证要求不能混在一起")
    elif workstream == "VREG":
        if frozenset(claims) not in {frozenset(VREG_INFRASTRUCTURE_CLAIMS), frozenset(VREG_RESULTS_CLAIMS)}:
            error("VREG 节点必须是回归基础设施或回归结果；两类节点的验证要求不能混在一起")


def required_input_prefixes(workstream, claims):
    """Return claim-specific upstream gates without introducing completion cycles."""
    if workstream == "VCOV":
        if set(claims) == {"coverage-model", "coverage-collection"}:
            return ("cap.doc:", "cap.venv:", "cap.vreg:")
        return ("cap.doc:", "cap.venv:", "cap.vstim:", "cap.vchk:",
                "cap.vcase:", "cap.vcov:", "cap.vreg:")
    if workstream == "VREG":
        if set(claims) == {"regression-policy", "executor-ready"}:
            return ("cap.doc:", "cap.venv:")
        return ("cap.doc:", "cap.venv:", "cap.vstim:", "cap.vchk:",
                "cap.vcase:", "cap.vcov:", "cap.vreg:")
    return profile(workstream)["required_input_prefixes"]


def vcov_structure_blockers(plan):
    """A completed implementation alone cannot satisfy coverage convergence."""
    required = [n for n in plan["desired_state"] if is_plan(n) and n.get("required", True)]
    implementations = {ids(n["implementation_key"], "VCOV")[2]: n for n in required
                       if vcov_stage(n) == "implementation"}
    convergence = [n for n in required if vcov_stage(n) == "convergence"]
    reasons = []
    if not implementations:
        reasons.append("尚未登记必需的覆盖率实现方案")
    if not convergence:
        reasons.append("尚未登记必需的覆盖率收敛方案，覆盖率实现完成后仍需采集和分析缺口")
    consumed = set()
    for node in convergence:
        inputs = set(node.get("inputs", [])) & implementations.keys()
        if not inputs:
            reasons.append(node["title"] + " 尚未关联必需覆盖率实现能力")
        consumed.update(inputs)
    for identifier in implementations.keys() - consumed:
        reasons.append(implementations[identifier]["title"] + " 尚未纳入必需覆盖率收敛范围")
    return reasons


def vreg_structure_blockers(plan):
    """Executor acceptance unlocks downstream work, not whole regression completion."""
    required = [n for n in plan["desired_state"] if is_plan(n) and n.get("required", True)]
    infrastructure = {ids(n["implementation_key"], "VREG")[2]: n for n in required
                      if vreg_stage(n) == "infrastructure"}
    results = [n for n in required if vreg_stage(n) == "results"]
    reasons = []
    if not infrastructure:
        reasons.append("尚未登记必需的回归基础设施方案")
    if not results:
        reasons.append("尚未登记必需的回归结果方案，执行器验收后仍需执行回归、处理失败并检查版本新鲜度")
    consumed = set()
    for node in results:
        inputs = set(node.get("inputs", [])) & infrastructure.keys()
        if not inputs:
            reasons.append(node["title"] + " 尚未关联必需回归基础设施能力")
        consumed.update(inputs)
    for identifier in infrastructure.keys() - consumed:
        reasons.append(infrastructure[identifier]["title"] + " 尚未纳入必需回归结果范围")
    return reasons


def workflow_progress(plan, nodes, closure, progress):
    """Project current completion, never accumulated rounds or execution time.

    An absent results/convergence scope has no known denominator. Keep the
    registered-node counts for audit, but do not turn them into overall 100%.
    This projection creates neither placeholder WorkNodes nor approval facts.
    """
    workstream = plan["workstream"]
    if workstream not in {"VREG", "VCOV"}:
        return {}
    scope_blockers = (vreg_structure_blockers(plan) if workstream == "VREG"
                      else vcov_structure_blockers(plan))
    reasons = list(scope_blockers)
    total, completed = progress["required"], progress["satisfied"]
    if not reasons and completed == total and not closure["ready"]:
        reasons = [action["reason"] for action in closure["actions"]]
        if not reasons:
            reasons = ["节点完成统计与工作流完成条件不一致，请重新核对当前状态"]
    elif not reasons and closure["ready"] and completed != total:
        reasons = ["工作流完成结论与当前必需节点统计不一致，请重新计算并核对状态"]
    stages = []
    labels = (("infrastructure", "回归基础设施"), ("results", "回归结果")) if workstream == "VREG" else (
        ("implementation", "覆盖率实现"), ("convergence", "覆盖率收敛"))
    for key, label in labels:
        required = [n for n in nodes if n.get("required", True) and stage(n, workstream) == key]
        pending = sum(is_plan(n) and not any(
            is_delivery(d) and d.get("parent_id") == n["id"]
            and d.get("implementation_key") == n.get("implementation_key")
            for d in required) for n in required)
        stages.append({"key": key, "label": label, "registered_required": len(required),
                       "required": len(required) + pending, "pending_registration": pending,
                       "satisfied": sum(bool((n.get("plan_review") or {}).get("completed"))
                                        for n in required)})
    rounds = []
    if workstream == "VREG":
        for n in nodes:
            if not n.get("required", True) or not is_delivery(n) or vreg_stage(n) != "results":
                continue
            review = n.get("plan_review") or {}
            current = (review.get("regression_execution") or {}).get("current")
            if current:
                rounds.append({"node_id": n["id"], "title": n["title"],
                               "round_number": current["round_number"], "status": current["status"],
                               "completed": bool(review.get("completed"))})
    return {"scope_complete": not scope_blockers, "scope_blockers": scope_blockers,
            "completion_ready": closure["ready"], "percentage_reasons": reasons,
            "percentage": completed * 100 // total if total and not reasons else None,
            "stages": stages, "current_rounds": rounds}


def _vcov_expected_inventories(store, connection, plan, node):
    """Resolve accepted implementation reports through explicit capability inputs."""
    owner = node if is_plan(node) else next(
        (n for n in plan["desired_state"] if n["id"] == node.get("parent_id")), None)
    if owner is None:
        return set(), ["覆盖率收敛交付缺少对应方案"]
    expected, reasons = set(), []
    implementations = {ids(n["implementation_key"], "VCOV")[2]: n
                       for n in plan["desired_state"] if is_plan(n) and vcov_stage(n) == "implementation"}
    selected_inputs = set(owner.get("inputs", [])) & implementations.keys()
    if not selected_inputs:
        reasons.append("覆盖率收敛方案没有关联覆盖率实现能力")
    for identifier in sorted(selected_inputs):
        provider = implementations[identifier]
        delivery = next((n for n in plan["desired_state"] if n.get("parent_id") == provider["id"]), None)
        if not delivery:
            reasons.append(provider["title"] + " 尚未交付覆盖率实现")
            continue
        state = review_state(store, delivery["id"], plan, delivery, connection)
        validation = state.get("validation") or {}
        checks = [check for check in validation.get("checks", []) if check.get("claim") == "coverage-model"]
        inventories = {
            check.get("validation", {}).get("facts", {}).get("coverage_inventory_digest")
            for check in checks
        }
        inventories.discard(None)
        if not state["completed"] or not inventories:
            reasons.append(provider["title"] + " 缺少当前已验收的覆盖对象清单，请重新验证实现")
        expected.update(inventories)
    return expected, reasons


def _sync_watched_files(store, connection):
    """Watch every active code workflow; one workflow must not erase another's paths."""
    watched = set()
    for workstream in CODE_WORKSTREAMS:
        row = connection.execute(
            "SELECT desired_json,context_json FROM workstreams WHERE name=?", (workstream,),
        ).fetchone()
        if row is None or json.loads(row["context_json"]).get("code_model") != 2:
            continue
        for item in json.loads(row["desired_json"]):
            watched.update(item.get("input_files", []))
            watched.update(item.get("output_paths", []))
            previous = connection.execute(
                "SELECT payload_json FROM code_validations WHERE node_id=? ORDER BY rowid DESC LIMIT 1",
                (item["id"],),
            ).fetchone()
            if previous:
                watched.update(value["path"] for value in json.loads(previous[0]).get("files", []))
            exclusion = connection.execute(
                "SELECT path FROM coverage_exclusion_approvals WHERE node_id=? ORDER BY rowid DESC LIMIT 1",
                (item["id"],),
            ).fetchone()
            if exclusion:
                watched.add(exclusion["path"])
    connection.execute("DELETE FROM code_watched_files")
    connection.executemany(
        "INSERT INTO code_watched_files VALUES(?)", [(path,) for path in sorted(watched)],
    )


def _validate_project_dependency_graph(store, workstream, proposed, connection=None):
    """Reject cycles across current code plans before a new revision is stored.

    WorkNodes depend on accepted capabilities.  A capability can be either the
    implementation-specific result or a claim summary backed by every required
    provider.  Expanding both forms here prevents a locally valid proposal from
    closing a cross-workstream cycle through an already registered plan.
    """
    if connection is None:
        current = [plan for plan in store.workstreams() if modern(plan)]
    else:
        current = [
            {
                "workstream": row["name"],
                "desired_state": json.loads(row["desired_json"]),
            }
            for row in connection.execute(
                "SELECT name,desired_json,context_json FROM workstreams"
            )
            if json.loads(row["context_json"]).get("code_model") == 2
        ]
    plans = {
        plan["workstream"]: [
            node for node in plan["desired_state"] if is_plan(node)
        ]
        for plan in current
    }
    plans[workstream] = list(proposed)
    providers: dict[str, set[tuple[str, str]]] = {}
    labels: dict[tuple[str, str], str] = {}
    for candidate, nodes in plans.items():
        for node in nodes:
            key = node.get("implementation_key")
            if not isinstance(key, str) or not key:
                continue
            token = (candidate, key)
            labels[token] = f"{candidate}/{node.get('title') or key}"
            providers.setdefault(ids(key, candidate)[2], set()).add(token)
            if node.get("required", True):
                for claim in node.get("capabilities", []):
                    providers.setdefault(
                        profile(candidate)["cap_prefix"] + claim, set(),
                    ).add(token)

    dependencies: dict[tuple[str, str], set[tuple[str, str]]] = {
        token: set() for token in labels
    }
    for candidate, nodes in plans.items():
        for node in nodes:
            token = (candidate, node.get("implementation_key"))
            if token not in dependencies:
                continue
            for capability in node.get("inputs", []):
                dependencies[token].update(providers.get(capability, set()))

    completed: set[tuple[str, str]] = set()
    active: set[tuple[str, str]] = set()
    stack: list[tuple[str, str]] = []

    def visit(token):
        if token in completed:
            return
        if token in active:
            start = stack.index(token)
            cycle = [*stack[start:], token]
            error(
                "跨工作流能力依赖形成循环，无法保证闭环收敛："
                + " -> ".join(labels[item] for item in cycle)
            )
        active.add(token)
        stack.append(token)
        for dependency in sorted(dependencies.get(token, set())):
            visit(dependency)
        stack.pop()
        active.remove(token)
        completed.add(token)

    for token in sorted(dependencies):
        visit(token)


def design(store, workstream, source, objective=None, decisions=None, restart=None):
    from .store import now, Validity
    from .evidence_policy import EVIDENCE_POLICIES
    store.ensure_dashboard_schema()
    workstream = workstream.upper()
    settings = profile(workstream)
    nodes = []
    if source:
        path = store.root / local_path(store, source)
        try:
            proposal = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            error(f"无法读取代码实现方案：{exc}")
        if not isinstance(proposal, dict) or proposal.get("schema") != "DesiredStateProposal/1" or proposal.get("workstream") != workstream:
            error(f"代码方案必须使用 {workstream} 的 DesiredStateProposal/1")
        nodes = proposal.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            error("方案必须包含工作节点" if workstream in {"VCOV", "VREG"} else "代码实现方案必须包含工作包")
    normalized = []
    known_keys = set()
    known_outputs = set()
    known_groups = set()
    known_group_names = set()
    for raw in nodes:
        allowed_roles = ({"code-plan", *VCOV_PLAN_ROLES} if workstream == "VCOV" else
                         {"code-plan", *VREG_PLAN_ROLES} if workstream == "VREG" else {"code-plan"})
        if not isinstance(raw, dict) or raw.get("role") not in allowed_roles:
            error("VCOV 方案只能包含覆盖率实现方案或覆盖率收敛方案；批准后建立对应交付节点"
                  if workstream == "VCOV" else "VREG 方案只能包含回归基础设施方案或回归结果方案；批准后建立对应交付节点"
                  if workstream == "VREG" else f"{workstream} 方案只包含 code-plan；批准后由系统建立对应 code-deliverable")
        key = raw.get("implementation_key", "")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*:[a-z0-9][a-z0-9._:-]*", key) or key in known_keys:
            error("implementation_key 必须是唯一、稳定的方案与交付关联标识" if workstream in {"VCOV", "VREG"}
                  else "implementation_key 必须是唯一、稳定的工作包标识")
        known_keys.add(key)
        item = {"implementation_key": key, "key": raw.get("key") or key.replace(":", "-"), "role": raw["role"]}
        if not isinstance(item['key'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', item['key']):
            error("代码方案 key 只能使用小写字母、数字、点、短横线和下划线")
        for field in ("title", "statement"):
            if not isinstance(raw.get(field), str) or not raw[field].strip():
                error(f"代码方案缺少 {field}")
            item[field] = raw[field].strip()
        for field in ("scope", "work_content", "implementation_approach", "validation_methods", "deliverables", "acceptance_criteria", "source_refs", "inputs", "output_paths", "capabilities"):
            item[field] = strings(raw, field)
        validate_claims(workstream, item["capabilities"])
        if workstream == "VCOV":
            inferred = "implementation" if set(item["capabilities"]) == VCOV_IMPLEMENTATION_CLAIMS else "convergence"
            canonical = f"coverage-{inferred}-plan"
            if item["role"] != "code-plan" and item["role"] != canonical:
                error("覆盖率节点类型与验证要求不一致")
            item["role"] = canonical
            if inferred == "implementation":
                try:
                    item["coverage_scope"] = normalize_coverage_scope(raw.get("coverage_scope"))
                except ValueError as exc:
                    error("覆盖率实现方案必须登记负责人可审查的 coverage_scope：" + str(exc))
                try:
                    item["coverage_implementation_config"] = normalize_coverage_implementation_config(
                        raw.get("coverage_implementation_config")
                    )
                except ValueError as exc:
                    error("覆盖率实现方案必须登记结构化 coverage_implementation_config：" + str(exc))
                if "coverage_item_ids" in raw:
                    error("新覆盖率方案不再登记 coverage_item_ids；请登记覆盖范围，由工具生成覆盖对象清单")
            else:
                if "coverage_scope" in raw or "coverage_item_ids" in raw:
                    error("覆盖率收敛范围由明确关联的实现能力继承，不另行登记 coverage_scope 或 coverage_item_ids")
                try:
                    item["coverage_collection_config"] = normalize_coverage_collection_config(
                        raw.get("coverage_collection_config")
                    )
                except ValueError as exc:
                    error("覆盖率收敛方案必须登记结构化 coverage_collection_config：" + str(exc))
        if workstream == "VREG":
            inferred = "infrastructure" if set(item["capabilities"]) == VREG_INFRASTRUCTURE_CLAIMS else "results"
            canonical = f"regression-{inferred}-plan"
            if item["role"] != "code-plan" and item["role"] != canonical:
                error("回归节点类型与验证要求不一致")
            item["role"] = canonical
            if inferred == "results":
                from .vreg_contract import group_identity
                try:
                    item["regression_config"] = regression_config(raw)
                except ValueError as exc:
                    error("回归结果方案必须明确回归组及执行参数：" + str(exc))
                group = item["regression_config"]
                submit_path = local_path(store, group["submit_profile"]["submit_file"])
                group["submit_profile"]["submit_file"] = submit_path
                identity_key = group_identity(group)
                if identity_key in known_groups or group["regression_group"] in known_group_names:
                    error("同一回归组只能对应一个回归结果方案")
                known_groups.add(identity_key)
                known_group_names.add(group["regression_group"])
                if file_snapshot(store, [submit_path])[0]["sha256"] != group["submit_profile"]["submit_file_digest"]:
                    error("回归方案引用的 submit 配置文件缺失或摘要已经变化")
            if inferred == "infrastructure" and any(
                    not value.startswith(("cap.doc:", "cap.venv:")) for value in item["inputs"]):
                error("回归基础设施只能依赖已验收文档和验证环境，不能依赖激励、检查、用例、覆盖率或最终回归结果")
        if not all(v.startswith(settings["input_prefixes"]) for v in item["inputs"]):
            error(f"{workstream} 上游必须使用 " + "、".join(settings["input_prefixes"]) + "，不能依赖工作节点、未验收产物或下游结果")
        if workstream in {"VSTIM", "VCASE", "VCOV"} and any(
            value.startswith("cap.vreg:") and value != "cap.vreg:executor-ready"
            for value in item["inputs"]
        ):
            error(
                f"{workstream} 只能使用回归基础设施验收派生的 "
                "cap.vreg:executor-ready，不能反向依赖最终回归结果或其他回归能力"
            )
        if not any(v.startswith("cap.doc:") for v in item["inputs"]):
            error("代码方案必须说明所依据的已验收文档 cap.doc")
        missing_inputs = [
            prefix for prefix in required_input_prefixes(workstream, item["capabilities"])
            if not any(value.startswith(prefix) for value in item["inputs"])
        ]
        if missing_inputs:
            error(f"{workstream} 代码方案缺少必需上游能力：" + ", ".join(missing_inputs))
        if workstream == "VCOV" and "cap.vreg:executor-ready" not in item["inputs"]:
            error("覆盖率方案必须依赖已验收的回归执行能力 cap.vreg:executor-ready")
        if workstream == "VREG" and vreg_stage(item) == "results":
            coverage_inputs = {value for value in item["inputs"] if value.startswith("cap.vcov:")}
            if coverage_inputs != {"cap.vcov:coverage-collection"}:
                error("回归结果方案必须且只能把 cap.vcov:coverage-collection 作为覆盖率执行前置；收敛结果留到最终验收检查")
        if ids(key, workstream)[2] in item["inputs"]:
            error("方案不能依赖自己的交付能力" if workstream in {"VCOV", "VREG"} else "工作包不能依赖自己的交付能力")
        item["output_paths"] = store._normalized_write_scopes(item["output_paths"])
        for path in item["output_paths"]:
            if any(store._scopes_overlap(path, old) for old in known_outputs):
                error("工作节点的输出范围不能重叠" if workstream in {"VCOV", "VREG"} else "工作包的输出范围不能重叠")
            known_outputs.add(path)
        item["input_files"] = [store._project_or_declared_input_path(v) for v in strings(raw, "input_files")]
        if "planning_feedback_files" in raw:
            item["planning_feedback_files"] = [store._project_or_declared_input_path(v)
                                                for v in strings(raw, "planning_feedback_files")]
            if not set(item["planning_feedback_files"]) <= set(item["input_files"]):
                error("规划反馈文件必须同时登记在方案输入中")
            with store.read_connect() as feedback_db:
                eligible = feedback_report_paths(store, feedback_db, {"workstream": workstream, "desired_state": []},
                                                 {**item, "id": "unregistered"})
            if set(item["planning_feedback_files"]) != eligible:
                error("规划反馈只允许独立的 HoleAnalysisReport/1 缺口报告，不能作为本节点输出或验证证据")
        if workstream == "VCOV" and vcov_stage(item) == "implementation":
            code_scope = item["coverage_scope"].get("code", {})
            for field in ("hierarchy_files", "exclusion_files"):
                if field in code_scope:
                    code_scope[field] = [store._project_or_declared_input_path(v) for v in code_scope[field]]
            missing_scope_files = sorted(coverage_scope_files(item) - set(item["input_files"]))
            if missing_scope_files:
                error("coverage_scope 引用的层次或排除配置必须纳入 input_files：" + "、".join(missing_scope_files))
            refs = item["coverage_implementation_config"]["configuration_refs"]
            for ref in refs:
                ref["path"] = store._project_or_declared_input_path(ref["path"])
            missing_config_files = sorted({ref["path"] for ref in refs} - set(item["input_files"]))
            if missing_config_files:
                error("覆盖率实现配置文件必须纳入 input_files：" + "、".join(missing_config_files))
            observed = {entry["path"]: entry["sha256"] for entry in file_snapshot(
                store, [ref["path"] for ref in refs]
            )}
            if any(observed.get(ref["path"]) != ref["sha256"] for ref in refs):
                error("覆盖率实现配置文件缺失或摘要已经变化")
        if workstream == "VCOV" and vcov_stage(item) == "convergence":
            merge = item["coverage_collection_config"]["merge_profile"]
            merge["path"] = store._project_or_declared_input_path(merge["path"])
            if merge["path"] not in item["input_files"]:
                error("覆盖率 merge profile 必须纳入 input_files")
            if file_snapshot(store, [merge["path"]])[0]["sha256"] != merge["sha256"]:
                error("覆盖率 merge profile 文件缺失或摘要已经变化")
        if workstream == "VREG" and vreg_stage(item) == "results":
            item["input_files"] = sorted(set([*item["input_files"], item["regression_config"]["submit_profile"]["submit_file"]]))
        if any(not (Path(v) if Path(v).is_absolute() else store.root / v).is_file() for v in item["input_files"]):
            error("input_files 必须逐项引用实际输入文件，目录仅用于界面展示")
        conflicts = self_output_inputs(store, item)
        if conflicts:
            error("方案输入不能包含本节点交付输出，否则生成文件会使方案审批失效：" + "、".join(conflicts))
        item.update(required=raw.get("required", True), purpose=item["statement"],
                    suggested_mode="plan", definition_origin="project-proposal",
                    definition_status="REVIEW_CANDIDATE", quality_checks=item["validation_methods"],
                    progress_measures=[], evidence_claim="code-validation", parent_id=None,
                    role_description=("当前 DUT 的" + node_label(item, workstream) if workstream in {"VCOV", "VREG"}
                                      else "当前 DUT 工作包的" + settings.get("plan_term", "代码实现方案")))
        if not isinstance(item["required"], bool):
            error("required 必须是布尔值")
        normalized.append(item)
    if len({n["key"] for n in normalized}) != len(normalized):
        error("代码方案 key 不能重复")
    if workstream == "VCOV" and any(vcov_stage(candidate) == "convergence" for candidate in normalized):
        from .store import HarnessError
        try:
            vreg = store.workstream("VREG")
        except HarnessError:
            error("覆盖率收敛方案引用回归配置前，必须先形成当前 VREG 回归结果方案")
        vreg_plans = {entry["id"]: entry for entry in vreg["desired_state"]
                      if is_plan(entry) and vreg_stage(entry) == "results"}
        implementation_profiles = {
            ids(item["implementation_key"], "VCOV")[2]: set(
                item["coverage_implementation_config"]["compatible_submit_profile_digests"]
            )
            for item in normalized if vcov_stage(item) == "implementation"
        }
        for candidate in normalized:
            if vcov_stage(candidate) != "convergence":
                continue
            selected_profiles = set().union(*(
                implementation_profiles[value]
                for value in candidate["inputs"] if value in implementation_profiles
            )) if any(value in implementation_profiles for value in candidate["inputs"]) else set()
            for source in candidate["coverage_collection_config"]["regression_sources"]:
                referenced = vreg_plans.get(source["plan_node_id"])
                if referenced is None or vreg["revision"] != source["plan_revision"]:
                    error("coverage_collection_config 引用了非当前 VREG 回归结果方案")
                if config_digest(regression_config(referenced)) != source["regression_config_digest"]:
                    error("coverage_collection_config 引用的 regression_config 摘要与当前 VREG 方案不一致")
                profile_digest = regression_config(referenced)["submit_profile"]["profile_digest"]
                if profile_digest not in selected_profiles:
                    error("VREG submit profile 未声明为本收敛方案所选覆盖率实现支持的采集 profile")
    by_cap = {ids(n["implementation_key"], workstream)[2]: n for n in normalized}
    def visit(cap, parents):
        if cap in parents:
            error("工作节点存在循环依赖" if workstream in {"VCOV", "VREG"} else "代码工作包存在循环依赖")
        for target in by_cap.get(cap, {}).get("inputs", []):
            if target.startswith(settings["cap_prefix"]):
                if target not in by_cap:
                    error(("当前方案没有提供前置覆盖率实现节点：" if workstream == "VCOV"
                           else "当前方案没有提供前置回归基础设施节点：" if workstream == "VREG"
                           else "当前方案没有提供前置工作包：") + target)
                if workstream == "VCOV" and vcov_stage(by_cap[target]) != "implementation":
                    error("覆盖率收敛方案必须依赖覆盖率实现能力，不能依赖收敛结果")
                if workstream == "VREG" and vreg_stage(by_cap[target]) != "infrastructure":
                    error("回归结果方案必须依赖回归基础设施能力，不能依赖结果能力")
                visit(target, parents | {cap})
    for cap in by_cap:
        visit(cap, set())
    timestamp = now()
    context = {**store.planning_context(workstream), "code_model": 2}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        _validate_project_dependency_graph(
            store, workstream, normalized, connection=db,
        )
        old = db.execute("SELECT revision,desired_json,objective,decisions_json,context_json FROM workstreams WHERE name=?", (workstream,)).fetchone()
        revision = old["revision"] + 1 if old else 1
        if restart and (not old or restart["revision"] != old["revision"]):
            error(f"{workstream} 版本已变化，请刷新后重新确认")
        if workstream == "VREG" and db.execute(
                "SELECT 1 FROM regression_execution_rounds WHERE status IN ('DISPATCHED','RUNNING','INTERRUPTED') LIMIT 1"
        ).fetchone():
            # Include orphaned/historical rounds: cancelling an Agent or changing
            # its public node revision cannot establish an external job's end.
            error("旧回归任务尚未核实结束，请先让 Agent 核对旧任务结束事实，再重新形成方案或重启 VREG")
        previous = json.loads(old["desired_json"]) if old else []
        retained = {}
        if old and not restart and json.loads(old["context_json"]).get("code_model") == 2:
            existing_plans = {
                node["implementation_key"]: {key: value for key, value in node.items() if key != "id"}
                for node in previous if is_plan(node)
            }
            proposed_plans = {node["implementation_key"]: node for node in normalized}
            if (existing_plans == proposed_plans and old["objective"] == (objective or settings["objective"])
                    and json.loads(old["decisions_json"]) == (decisions or [])):
                pending_change = db.execute(
                    "SELECT 1 FROM human_actions WHERE status='OPEN' AND action='REQUEST_CHANGE' "
                    "AND (target=? OR target LIKE ?) LIMIT 1",
                    (workstream, f"workstream:{workstream}:%"),
                ).fetchone()
                if pending_change:
                    error("负责人已登记工作节点变更要求；方案仍与当前版本相同，请先落实变更要求")
                # A status-only dependency transition must not turn the same
                # public proposal into a new revision and a new approval set.
                db.execute("ROLLBACK")
                return {**store.workstream(workstream), "auto_closure": store.evaluate_closure(workstream)}
            if (old["objective"] == (objective or settings["objective"])
                    and json.loads(old["decisions_json"]) == (decisions or [])):
                for previous_node in previous:
                    key = previous_node.get("implementation_key")
                    if (is_plan(previous_node) and retains_node_version(workstream, previous_node)
                            and key in proposed_plans
                            and existing_plans[key] == proposed_plans[key]):
                        retained[key] = [previous_node, *(
                            child for child in previous
                            if child.get("parent_id") == previous_node["id"]
                        )]
        retained_statuses = {
            node["id"]: db.execute("SELECT status FROM nodes WHERE id=?", (node["id"],)).fetchone()[0]
            for package in retained.values() for node in package
        }
        previous_edges = [dict(row) for row in db.execute(
            "SELECT e.* FROM edges e JOIN nodes n ON n.id=e.target WHERE n.workstream=?",
            (workstream,),
        )]
        db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", (
            "event:" + uuid.uuid4().hex, workstream.lower() + "-replan",
            f"workstream:{workstream}", str(revision),
            encoded({"previous_nodes": previous, "restart": restart, "previous_edges": previous_edges,
                     "retained_node_ids": sorted(retained_statuses)}),
            timestamp,
        ))
        db.execute("UPDATE nodes SET workstream=NULL,status='STALE',updated_at=? WHERE workstream=? AND type='desired-state'", (timestamp, workstream))
        for old_node in previous:
            if old_node.get("key") not in EVIDENCE_POLICIES[workstream]:
                continue
            cap = settings["cap_prefix"] + old_node["key"]
            store.upsert_node(db, cap, "capability", "代码交付需重新验证和验收", Validity.UNKNOWN, data={"derived": True})
            for row in db.execute("SELECT * FROM edges WHERE target=? AND relation='DEPENDS_ON'", (old_node["id"],)).fetchall():
                db.execute("DELETE FROM edges WHERE source=? AND target=? AND relation='DEPENDS_ON'", (row["source"], row["target"]))
                edge(db, row["source"], cap, timestamp)
        db.execute("UPDATE activities SET status='CANCELLED',ended_at=?,updated_at=? WHERE workstream=? AND status IN ('PENDING','RUNNING','WAITING_FOR_HUMAN','WAITING_FOR_PARENT')", (timestamp, timestamp, workstream))
        db.execute("UPDATE agent_assignments SET status='SUPERSEDED',ended_at=?,updated_at=? WHERE workstream=? AND status='ACTIVE'", (timestamp, timestamp, workstream))
        retained_feedback = (" AND node_id NOT IN (" + ",".join("?" for _ in retained_statuses) + ")"
                             if retained_statuses else "")
        db.execute("UPDATE review_feedback_items SET status='SUPERSEDED',updated_at=?,resolved_at=? WHERE workstream=? AND status IN ('DRAFT','PENDING','WAITING_FOR_HUMAN')" + retained_feedback,
                   (timestamp, timestamp, workstream, *retained_statuses))
        registered = []
        for item in normalized:
            package = retained.get(item["implementation_key"])
            if package:
                for retained_node in package:
                    store.upsert_node(db, retained_node["id"], "desired-state", retained_node["title"],
                                      Validity(retained_statuses[retained_node["id"]]), workstream, retained_node)
                registered.extend(package)
                continue
            item["id"] = f"workstream:{workstream}:r{revision}:desired:{item['key']}"
            registered.append(item)
            store.upsert_node(db, item["id"], "desired-state", item["title"], Validity.REVIEW_REQUIRED, workstream, item)
            for target in item["inputs"]:
                if not db.execute("SELECT 1 FROM nodes WHERE id=?", (target,)).fetchone():
                    store.upsert_node(db, target, "capability", "前置交付尚未验收", Validity.UNKNOWN, data={"derived": True})
                edge(db, item["id"], target, timestamp)
        db.execute("INSERT INTO workstreams VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET lifecycle=excluded.lifecycle,revision=excluded.revision,objective=excluded.objective,desired_json=excluded.desired_json,exit_json=excluded.exit_json,decisions_json=excluded.decisions_json,context_json=excluded.context_json,updated_at=excluded.updated_at",
                   (workstream, "REVIEW", revision, objective or settings["objective"], encoded(registered),
                    encoded(["当前必需覆盖率实现与收敛节点均已验证并由负责人验收" if workstream == "VCOV"
                             else "当前必需回归基础设施与结果节点均已验证并由负责人验收" if workstream == "VREG"
                             else "必需工作包的代码交付均通过专用验证并由负责人验收"]),
                    encoded(decisions or []), encoded(context), timestamp))
        # Default downstream edges must never fall back to old WorkNodes.
        store._reconcile_default_dependencies(db)
        _sync_watched_files(store, db)
    refresh(store)
    store.write_workstream_projection(workstream)
    return {**store.workstream(workstream), "auto_closure": store.evaluate_closure(workstream)}


def edge(db, source, target, timestamp, relation="DEPENDS_ON"):
    db.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?,?,?,?,?)", (source, target, relation, "code-workflow", 1.0, "{}", timestamp))


def create_delivery(store, db, plan, node, timestamp):
    from .store import Validity
    if any(n.get("parent_id") == node["id"] for n in plan["desired_state"]):
        return
    workstream = plan["workstream"]
    role = (vcov_role(node).replace("-plan", "-deliverable") if workstream == "VCOV" else
            vreg_role(node).replace("-plan", "-deliverable") if workstream == "VREG" else "code-deliverable")
    value = {**node, "id": node["id"] + ":delivery", "key": node["key"] + "-delivery",
             "role": role, "title": node["title"] + " · " + node_label({**node, "role": role}, workstream),
             "parent_id": node["id"], "parent_key": node["key"], "suggested_mode": "implement",
             "role_description": "Agent 先完成实现与验证，再由负责人验收当前交付文件和证据"}
    plan["desired_state"].append(value)
    store.upsert_node(db, value["id"], "desired-state", value["title"], Validity.UNKNOWN, workstream, value)
    edge(db, value["id"], node["id"], timestamp, "CHILD_OF")
    edge(db, value["id"], ids(node["implementation_key"], workstream)[0], timestamp)
    db.execute("UPDATE workstreams SET desired_json=?,updated_at=? WHERE name=?", (encoded(plan["desired_state"]), timestamp, workstream))
    _sync_watched_files(store, db)


def review(store, node_id, expected, reviewer, reason="", verdict="approve", changes=None):
    from .store import now
    if not reviewer.strip() or verdict not in {"approve", "modify", "reject", "clarify"}:
        error("审批必须提供审批人和有效结论")
    refresh(store)
    timestamp, review_id = now(), "code-review:" + uuid.uuid4().hex[:12]
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        plan, node = selected(store, node_id, db)
        state = review_state(store, node_id, plan, node, db)
        if expected != state["definition_digest"]:
            error("方案、代码或验证证据版本已变化，请刷新后重新审查")
        if verdict == "approve":
            if not state["can_approve"]:
                error("当前不能批准：" + "；".join(state["blockers"]))
            if state["completed"]:
                error("当前版本已批准，无需重复提交")
            db.execute("INSERT INTO node_plan_reviews VALUES(?,?,?,?,?,?,?,?,?)", (review_id, node_id, plan["workstream"], node_revision(plan, node), expected, "APPROVE", reviewer.strip(), reason.strip(), timestamp))
            from .approval_subjects import record
            record(store, db, plan, node, review_id, timestamp)
            if is_plan(node):
                bind_feedback_context(store, db, plan, node, {
                    "sources": state["sources"], "review": {"id": review_id}})
                create_delivery(store, db, plan, node, timestamp)
                if plan["workstream"] == "VREG" and vreg_stage(node) == "results":
                    delivery = next(n for n in plan["desired_state"] if n.get("parent_id") == node["id"])
                    previous = execution_round(db, delivery["id"])
                    if not previous or previous["plan_digest"] != expected:
                        if previous:
                            _archive_execution_round(store, db, previous)
                            db.execute("UPDATE regression_execution_rounds SET status='SUPERSEDED' WHERE id=?", (previous["id"],))
                        _new_execution_round(db, plan, delivery, expected, "initial:" + review_id,
                                             reviewer.strip(), "按已批准方案执行本轮回归", timestamp)
            elif plan["workstream"] == "VREG" and vreg_stage(node) == "results":
                value = execution_round(db, node_id)
                db.execute("UPDATE regression_execution_rounds SET status='ACCEPTED',accepted_at=? WHERE id=?",
                           (timestamp, value["id"]))
        else:
            if state["feedback"]["processing_count"]:
                error("上一批意见仍在等待 Agent 处理")
            if not reason.strip():
                error("请填写审批内容")
            normalized = store._normalize_review_change_items(verdict, changes, default_target=node["title"], default_instruction=reason)
            db.execute("INSERT INTO node_plan_section_reviews VALUES(?,?,?,?,?,?,?,?,?,?)", (review_id, node_id, plan["workstream"], node_revision(plan, node), expected, "writing-plan", verdict.upper(), reviewer.strip(), reason.strip(), timestamp))
            store._store_review_change_items(db, review_id, normalized)
            store._store_review_feedback_items(db, review_id, node_id, node_revision(plan, node), expected, "", reviewer, normalized, timestamp, workstream=plan["workstream"])
        store._record_review_submitted_event(db, review_id, node_id, verdict, reviewer, changes or [], timestamp, agent_follow_up="NONE" if verdict == "approve" else "AWAITING_FEEDBACK_SUBMISSION")
    refresh(store)
    return {"review_id": review_id, "node_id": node_id, "verdict": verdict.upper(),
            "plan_review": review_state(store, node_id), "auto_closure": store.evaluate_closure(plan["workstream"])}


def _validate_evidence(store, path, workstream, claim, plan=None, node=None):
    from .evidence_contracts import validate_workstream_evidence, EvidenceContractError
    if workstream == "VSTIM" and claim in {"reachability-evidence", "determinism-evidence"}:
        from .reachability import validate_reachability, ReachabilityError
        try:
            summary = validate_reachability(path)
        except ReachabilityError as exc:
            error(str(exc))
        result = {
            "schema": summary["schema"], "workstream": workstream, "claim": claim,
            "revision": summary["revision"], "artifacts": summary["artifacts"],
            "admission_policy": summary["admission_policy"],
            "blockers": list(summary["blockers"]), "facts": summary,
        }
        if claim == "reachability-evidence" and not summary["reachability_ready"]:
            if summary["missing_scenarios"]:
                result["blockers"].append(
                    "必需激励场景尚未到达 DUT 接收边界：" + ", ".join(summary["missing_scenarios"])
                )
        if claim == "determinism-evidence" and not summary["determinism_ready"]:
            if summary["non_deterministic_scenarios"]:
                result["blockers"].append(
                    "同配置同 seed 重放尚未证明一致：" + ", ".join(summary["non_deterministic_scenarios"])
                )
            if summary["mismatched_reproduction_groups"]:
                result["blockers"].append(
                    "重放生成的激励摘要不一致：" + ", ".join(summary["mismatched_reproduction_groups"])
                )
        return result
    try:
        if workstream == "VCASE" and plan is not None and node is not None:
            with store.read_connect() as db:
                return validate_workstream_evidence(path, workstream, claim, artifact_root=store.root,
                    case_confirmation_validator=lambda records: case_confirmation_blockers(db, node, records))
        return validate_workstream_evidence(path, workstream, claim, artifact_root=store.root)
    except EvidenceContractError as exc:
        error(str(exc))


def case_confirmation_blockers(connection, node, records):
    """Reuse existing node questions; manifest text alone cannot claim approval."""
    from .case_traceability import confirmation_context
    reasons = []
    family = {node["id"], node.get("parent_id")}
    for item in records:
        trace = item.get("traceability")
        if not trace:
            reasons.append(item["id"] + " 缺少当前用例来源和预期结果依据，请重新验证")
            continue
        expected = trace["expected_result"]
        if expected["status"] != "confirmed":
            continue
        row = connection.execute("SELECT * FROM agent_questions WHERE id=?",
                                 (expected["confirmation_question_id"],)).fetchone()
        try:
            context = json.loads(row["context"]) if row else None
        except ValueError:
            context = None
        if (not row or row["target"] not in family or row["workstream"] != "VCASE"
                or row["status"] != "ANSWERED" or row["answer_option"] != "confirm"
                or not row["answered_by"] or context != confirmation_context(item["id"], trace)):
            reasons.append(item["id"] + " 的 RTL 推导或工程决定缺少本节点当前行为版本的负责人确认")
    return reasons


def _feedback_routes(workstream, claim, facts):
    """Extract analysis-driven feedback; this never mutates the target workflow."""
    routes = []
    if workstream == "VCOV" and claim == "hole-analysis-evidence":
        for item in facts.get("holes", []):
            if item.get("status") != "uncovered" or not item.get("responsible_workstream"):
                continue
            routes.append({
                "source_workstream": workstream,
                "source_claim": claim,
                "finding": item.get("object_key"),
                "responsible_workstream": item.get("responsible_workstream"),
                "target_implementation_key": item.get("target_implementation_key") or "",
                "next_action": item.get("next_action") or "",
            })
    if workstream == "VREG" and claim == "triage-evidence":
        closed = {"fixed", "accepted-known-fail", "rerun-pass"}
        for item in facts.get("failures", []):
            if item.get("disposition") in closed or not item.get("responsible_workstream"):
                continue
            routes.append({
                "source_workstream": workstream,
                "source_claim": claim,
                "finding": item.get("case_id") or item.get("test"),
                "responsible_workstream": item.get("responsible_workstream"),
                "target_implementation_key": item.get("target_implementation_key") or "",
                "next_action": item.get("next_action") or "",
            })
    return routes


def _vreg_result_blockers(store, connection, plan, node, checks):
    """Bind execution, failure disposition and Engine-derived current scope."""
    reasons = []
    facts = {}
    for check in checks:
        claim = check["claim"]
        value = check["validation"]["facts"]
        facts.setdefault(claim, {})[digest(value)] = value
    from .vreg_contract import execution_blockers, normalize_config
    current_round = execution_round(connection, node["id"])
    try:
        config = regression_config(node)
        if current_round is None:
            reasons.append("结果交付尚未登记当前执行轮次")
        else:
            original_config = normalize_config(json.loads(current_round["config_json"]))
            if original_config != config:
                reasons.append("当前方案执行参数与本轮原批准配置不一致，旧任务只能按原配置核对结束事实")
            binding = execution_binding(plan, node, current_round)
            for claim in VREG_RESULTS_CLAIMS:
                for value in facts.get(claim, {}).values():
                    if value.get("execution_binding") != binding:
                        reasons.append("回归证据未绑定当前方案和执行轮次：" + claim)
            batches = [batch for value in facts.get("execution-evidence", {}).values() for batch in value.get("batches", [])]
            reasons.extend(execution_blockers(config, batches, binding))
    except ValueError as exc:
        reasons.append("回归结果方案或轮次合同不完整：" + str(exc))
    def run_key(item, seed_field):
        return (
            item.get("batch_id") or "",
            item.get("case_id") or item.get("test") or "",
            item.get(seed_field) or "",
            int(item.get("iteration") or 0),
        )

    def run_label(key):
        batch, case, seed, iteration = key
        return "/".join(part for part in (batch, case, str(seed), str(iteration)) if part != "")

    executed = [run_key(item, "seed")
                for value in facts.get("execution-evidence", {}).values()
                for item in value.get("failed_runs", [])]
    failures = [item for value in facts.get("triage-evidence", {}).values() for item in value.get("failures", [])]
    triaged = [run_key(item, "original_seed") for item in failures]
    if len(executed) != len(set(executed)) or len(triaged) != len(set(triaged)):
        reasons.append("回归执行或失败分类包含重复的 batch/case/seed/iteration 记录")
    missing, extra = set(executed) - set(triaged), set(triaged) - set(executed)
    if missing:
        reasons.append("回归执行失败尚未分类处理：" + "、".join(run_label(key) for key in sorted(missing)))
    if extra:
        reasons.append("失败分类包含当前回归执行不存在的失败：" + "、".join(run_label(key) for key in sorted(extra)))
    for item in failures:
        if item.get("disposition") != "accepted-known-fail":
            continue
        record = connection.execute("SELECT * FROM reviews WHERE id=? AND verdict='WAIVE'", (item.get("waiver_ref"),)).fetchone()
        if record is None or record["workstream"] != "VREG" or record["revision"] != plan["revision"]:
            reasons.append((item.get("case_id") or item.get("test") or "case") +
                           " 的已知失败没有当前 VREG 版本的负责人例外批准记录")
    accepted_cases: set[tuple[str, str, str]] = set()
    for row in connection.execute(
        "SELECT id,data_json FROM nodes WHERE id LIKE 'art.code:vcase:%' AND status='VALID'"
    ):
        head = json.loads(row["data_json"] or "{}").get("current")
        if not isinstance(head, dict) or not isinstance(head.get("version"), int):
            continue
        version = connection.execute(
            "SELECT payload_json FROM code_artifact_versions WHERE artifact_id=? AND version=?",
            (row["id"], head["version"]),
        ).fetchone()
        if version is None:
            continue
        validation = json.loads(version["payload_json"]).get("validation") or {}
        if validation.get("testcase_contract") != VCASE_VALIDATION_CONTRACT:
            continue
        for check in validation.get("checks", []):
            if check.get("claim") != "case-implementation":
                continue
            for item in check.get("validation", {}).get("facts", {}).get("case_records", []):
                accepted_cases.add((
                    item["id"], item["case_digest"],
                    item["submit_profile"]["profile_digest"],
                ))
    if accepted_cases:
        for value in facts.get("execution-evidence", {}).values():
            for batch in value.get("batches", []):
                profile_digest = batch["submit_profile"]["profile_digest"]
                for item in batch.get("cases", []):
                    key = (item["case_id"], item["case_digest"], profile_digest)
                    if key not in accepted_cases:
                        reasons.append(
                            f"batch {batch['batch_id']} 引用了未验收的完整 case："
                            f"{item['case_id']}/{batch['submit_profile']['profile_id']}"
                        )
    current = store._current_desired_nodes(connection)
    for check in checks:
        if check["claim"] == "fresh-evidence":
            reasons.extend(store._derive_fresh_evidence(connection, node["id"], check["validation"], current))
    return reasons


def validate(store, node_id, report_path):
    from .store import now, PROJECT_AGENT_ACTOR
    refresh(store)
    path = store.root / local_path(store, report_path)
    try:
        raw_report = path.read_bytes()
        report = json.loads(raw_report)
    except (OSError, ValueError) as exc:
        error(f"无法读取验证报告：{exc}")
    plan, node = selected(store, node_id)
    if not is_delivery(node):
        error("只有代码交付节点可以登记验证，方案节点不产生正式代码")
    with store.read_connect() as db:
        signature, snapshot = identity(store, db, plan, node)
        reasons = []
    if not isinstance(report, dict) or report.get("schema") != "CodeValidation/1" or report.get("node_id") != node_id or report.get("revision") != node_revision(plan, node) or report.get("input_signature") != signature:
        error("验证报告必须绑定当前项目节点、revision 和 input_signature")
    workstream = plan["workstream"]
    result_round = None
    if workstream == "VREG" and vreg_stage(node) == "results":
        from .vreg_contract import normalize_binding
        try:
            report["execution_binding"] = normalize_binding(report.get("execution_binding"))
        except ValueError as exc:
            error("回归验证报告必须绑定当前方案和执行轮次：" + str(exc))
        with store.read_connect() as db:
            result_round = execution_round(db, node_id)
        if (result_round is None or report.get("execution_binding") != execution_binding(plan, node, result_round)
                or result_round["status"] not in {"RUNNING", "INTERRUPTED", "VALIDATED", "FAILED", "ACCEPTED"}):
            error("验证报告必须绑定已登记工具调用的当前回归轮次，不能沿用旧轮次报告")
    if {d['id'] for d in snapshot['dependencies']} != {ids(node['implementation_key'], workstream)[0]} or any(d["status"] != "VALID" or not d['current'] for d in snapshot["dependencies"]):
        if result_round and result_round["status"] in {"RUNNING", "INTERRUPTED"}:
            reasons.append("批准的代码方案已失效；本报告仅核对原轮次结束事实，不构成交付验收或新执行授权")
        else:
            error("批准的代码方案已失效，不能登记验证结果")
    if report.get("checked_by") != PROJECT_AGENT_ACTOR or not str(report.get("summary", "")).strip():
        error("Main Agent 必须检查验证结果并填写摘要")
    outputs = file_snapshot(store, node["output_paths"], required=True)
    if report.get("code_files") != outputs:
        error("验证报告的 code_files 必须覆盖全部输出并匹配当前文件摘要")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        error("验证必须逐项覆盖批准方案的全部交付条件")
    checked = set()
    files = [local_path(store, path), *node["output_paths"]]
    expected_files = {v['path']: v['sha256'] for v in outputs}
    expected_files[local_path(store, path)] = hashlib.sha256(raw_report).hexdigest()
    claims = set()
    delivered_artifacts = set()
    feedback_routes = []
    facts_by_claim = {}
    exclusion_approval = None
    excluded_items = []
    for check in checks:
        criterion = check.get("criterion") if isinstance(check, dict) else None
        if criterion not in node["acceptance_criteria"]:
            error("交付条件不属于批准方案")
        checked.add(criterion)
        for field in ("method", "expected", "actual", "report", "claim"):
            if not isinstance(check.get(field), str) or not check[field].strip():
                error("每项验证必须说明方法、预期、实际结果及专用证据报告")
        if check["claim"] not in node["capabilities"]:
            error("验证报告的 claim 不属于批准方案")
        claims.add(check["claim"])
        evidence_path = store.root / local_path(store, check["report"])
        expected_files.update({v['path']: v['sha256'] for v in file_snapshot(store, [local_path(store, evidence_path)], required=True)})
        result = _validate_evidence(store, evidence_path, workstream, check["claim"], plan, node)
        if workstream == "VCOV" and result.get("schema") != "CoverageEvidence/3":
            error("当前 VCOV 交付必须使用 CoverageEvidence/3 绑定覆盖实现配置、VREG 执行轮次和 VDB merge")
        if workstream == "VCASE" and result.get("schema") != "TestcaseEvidence/2":
            error("当前 VCASE 交付必须使用 TestcaseEvidence/2 绑定 submit profile")
        if workstream == "VREG" and result.get("schema") != "RegressionEvidence/3":
            error("当前 VREG 交付必须使用 RegressionEvidence/3 绑定批准方案和执行轮次")
        result["artifacts"] = store._verify_evidence_artifacts(result["artifacts"])
        store._apply_revision_check(result)
        result['ready'] = not result['blockers']
        facts_by_claim.setdefault(check['claim'], []).append(result['facts'])
        feedback_routes.extend(_feedback_routes(workstream, check['claim'], result['facts']))
        delivered_artifacts.update(a['path'] for a in result['artifacts'])
        reasons.extend(result["blockers"])
        files.extend([local_path(store, evidence_path), *(a["path"] for a in result["artifacts"])])
        for artifact in result['artifacts']:
            if artifact['path'] in expected_files and expected_files[artifact['path']] != artifact['sha256']:
                error("各项证据引用了不同的文件版本，请重新验证")
            expected_files[artifact['path']] = artifact['sha256']
        check["validation"] = result
    if checked != set(node['acceptance_criteria']):
        error("验证必须逐项覆盖批准方案的全部交付条件")
    if claims != set(node["capabilities"]):
        error("尚未提供全部约定能力的验证证据")
    if set(node['output_paths']) - delivered_artifacts:
        error("专用验证报告必须直接引用全部当前交付文件，不能只在摘要中声明已检查")
    builds = facts_by_claim.get('build-ready', [])
    for smoke in facts_by_claim.get('environment-smoke-evidence', []):
        if not builds or any(smoke.get('environment_digest') != b.get('environment_digest') for b in builds):
            reasons.append("集成工作包的 smoke 必须与本次构建使用同一版本的验证环境")
    if workstream == "VCASE":
        matrix_cases = {
            case
            for facts in facts_by_claim.get("case-matrix", [])
            for mapping in facts.get("mappings", [])
            for case in mapping.get("cases", [])
        }
        case_records = [
            item for facts in facts_by_claim.get("case-implementation", [])
            for item in facts.get("case_records", [])
        ]
        implemented_cases = {item["id"] for item in case_records}
        missing_implementations = sorted(matrix_cases - implemented_cases)
        if missing_implementations:
            reasons.append("用例矩阵中的 case 尚未实现：" + "、".join(missing_implementations))
        implemented_variants = {
            (item["id"], item["submit_profile"]["profile_digest"]): item
            for item in case_records
        }
        run_records = [
            item for facts in facts_by_claim.get("targeted-evidence", [])
            for item in facts.get("run_records", [])
        ]
        executed_variants = {
            (item["case_id"], item["submit_profile_digest"])
            for item in run_records
        }
        missing_runs = sorted(set(implemented_variants) - executed_variants)
        if missing_runs:
            reasons.append("完整 case 尚无定向执行证据：" + "、".join(
                f"{case}/{implemented_variants[(case, profile)]['submit_profile']['profile_id']}"
                for case, profile in missing_runs
            ))
        for item in run_records:
            key = (item["case_id"], item["submit_profile_digest"])
            current_case = implemented_variants.get(key)
            if current_case is None:
                reasons.append(
                    f"定向执行未绑定当前完整 case："
                    f"{item['case_id']}/{item['submit_profile_id']}"
                )
            elif (item["case_digest"] != current_case["case_digest"] or
                  item["submit_profile_id"] != current_case["submit_profile"]["profile_id"]):
                reasons.append(
                    f"定向执行的 case/submit profile 摘要与当前实现不一致："
                    f"{item['case_id']}/{item['submit_profile_id']}"
                )
    if workstream == "VCOV" and vcov_stage(node) == "implementation":
        source_digests = {source["sha256"] for source in snapshot["sources"]}
        output_digests = {output["sha256"] for output in snapshot["outputs"]}
        expected_scope_digest = coverage_scope_digest(node)
        expected_implementation_config_digest = config_digest(coverage_implementation_config(node))
        for facts in facts_by_claim.get("coverage-model", []):
            if facts.get("scope_digest") != expected_scope_digest:
                reasons.append("工具生成的覆盖对象清单与负责人批准的覆盖范围不一致")
            category_counts = facts.get("category_counts", {})
            kind_counts = facts.get("kind_counts", {})
            scope = coverage_scope(node) or {}
            if "code" in scope and not category_counts.get("code"):
                reasons.append("批准的 code 覆盖范围没有展开出任何必需覆盖对象")
            if "functional" in scope and not category_counts.get("functional"):
                reasons.append("批准的 functional 覆盖范围没有展开出任何必需覆盖对象")
            expected_kinds = set(scope.get("code", {}).get("metrics", [])) | set(
                scope.get("functional", {}).get("object_kinds", [])
            )
            missing_kinds = sorted(kind for kind in expected_kinds if not kind_counts.get(kind))
            unexpected_kinds = sorted(set(kind_counts) - expected_kinds)
            if missing_kinds:
                reasons.append("批准的覆盖对象类型没有展开出对象：" + "、".join(missing_kinds))
            if unexpected_kinds:
                reasons.append("工具清单包含批准范围之外的覆盖对象类型：" + "、".join(unexpected_kinds))
            if facts.get("plan_digest") not in source_digests:
                reasons.append("覆盖计划摘要不属于批准方案的当前输入文件")
            if facts.get("model_digest") not in output_digests:
                reasons.append("覆盖模型摘要不属于当前交付文件")
            if facts.get("implementation_config_digest") != expected_implementation_config_digest:
                reasons.append("覆盖对象清单没有绑定当前批准的 CoverageImplementationConfig/1")
        for facts in facts_by_claim.get("coverage-collection", []):
            if facts.get("scope_digest") != expected_scope_digest:
                reasons.append("覆盖率采集配置没有绑定负责人批准的覆盖范围")
            if facts.get("exporter_digest") not in output_digests:
                reasons.append("覆盖率采集配置摘要不属于当前交付文件")
            if facts.get("implementation_config_digest") != expected_implementation_config_digest:
                reasons.append("覆盖率采集实现没有绑定当前批准的 CoverageImplementationConfig/1")
    if workstream == "VCOV" and vcov_stage(node) == "convergence":
        with store.read_connect() as db:
            expected_inventories, inventory_reasons = _vcov_expected_inventories(store, db, plan, node)
            exclusion_approval = coverage_exclusion_state(store, db, plan, node)["current"]
            resolved_sources, source_reasons = _coverage_collection_sources(
                store, db, coverage_collection_config(node),
            )
        reasons.extend(inventory_reasons)
        reasons.extend(source_reasons)
        expected_collection_digest = config_digest(coverage_collection_config(node))
        expected_bindings = sorted(
            (item["execution_binding"] for item in resolved_sources), key=lambda item: item["round_id"],
        )
        expected_config_digests = sorted(
            item["regression_config_digest"] for item in resolved_sources
        )
        expected_dut_fingerprint_digest = config_digest(
            coverage_collection_config(node)["dut_build_fingerprint"]
        )
        for claim in sorted(VCOV_CONVERGENCE_CLAIMS):
            observed = {facts.get("coverage_inventory_digest") for facts in facts_by_claim.get(claim, [])}
            if not expected_inventories or observed != expected_inventories:
                reasons.append("覆盖率收敛证据的覆盖对象清单与已验收实现不一致：" + claim)
            for facts in facts_by_claim.get(claim, []):
                if facts.get("coverage_collection_config_digest") != expected_collection_digest:
                    reasons.append("覆盖率收敛证据没有绑定当前批准的 CoverageCollectionConfig/1：" + claim)
        collection_facts = facts_by_claim.get("coverage-collection-evidence", [])
        for facts in collection_facts:
            if facts.get("source_execution_bindings") != expected_bindings:
                reasons.append("VDB 分片没有精确绑定收敛方案引用的当前 VREG 执行轮次")
            if facts.get("regression_config_digests") != expected_config_digests:
                reasons.append("VDB 分片的 regression_config 与收敛方案引用不一致")
            if facts.get("dut_build_fingerprint_digests") != [expected_dut_fingerprint_digest]:
                reasons.append(
                    "VDB 的 DUT 构建指纹不属于当前收敛方案；不同 DUT 指纹必须拆分为独立收敛节点"
                )
            from .vreg_contract import execution_blockers
            sources_by_round = {
                item["execution_binding"]["round_id"]: item for item in resolved_sources
            }
            for batch in facts.get("regression_batches", []):
                source = sources_by_round.get(batch["execution_binding"]["round_id"])
                if source is None:
                    reasons.append("VDB batch 不属于收敛方案引用的 VREG 执行轮次")
                else:
                    reasons.extend(execution_blockers(
                        source["regression_config"], [batch], source["execution_binding"],
                    ))
            merge_profile = coverage_collection_config(node)["merge_profile"]
            if facts.get("merge_profile_digest") != merge_profile["sha256"]:
                reasons.append("coverage merge 没有使用当前批准的 merge profile")
        databases_by_claim = {}
        for claim in VCOV_CONVERGENCE_CLAIMS:
            databases = {}
            for check in checks:
                if check["claim"] == claim:
                    evidence = check["validation"]
                    databases.setdefault(evidence["facts"].get("coverage_inventory_digest"), set()).update(
                        artifact["sha256"] for artifact in evidence["artifacts"]
                        if artifact["kind"] == "coverage-database")
            databases_by_claim[claim] = databases
        current_coverage_evidence = any(
            check.get("validation", {}).get("schema") == "CoverageEvidence/3"
            for check in checks if check.get("claim") in VCOV_CONVERGENCE_CLAIMS
        )
        if (not current_coverage_evidence
                and databases_by_claim["coverage-collection-evidence"] != databases_by_claim["hole-analysis-evidence"]):
            reasons.append("缺口分析没有使用本轮采集和合并的同一覆盖率数据库")
        merged_by_claim = {
            claim: {facts.get("merged_database_digest") for facts in facts_by_claim.get(claim, [])}
            for claim in VCOV_CONVERGENCE_CLAIMS
        }
        if merged_by_claim["coverage-collection-evidence"] != merged_by_claim["hole-analysis-evidence"]:
            reasons.append("缺口分析没有使用本轮 CoverageMergeManifest/1 的同一合并数据库")
        excluded_items = [item for facts in facts_by_claim.get("hole-analysis-evidence", [])
                          for item in facts.get("holes", []) if item.get("status") == "excluded"]
        if excluded_items and exclusion_approval is None:
            reasons.append("覆盖率报告包含排除项，但负责人尚未为当前收敛范围提供已审批的 exclude 文件")
        if excluded_items and exclusion_approval is not None:
            analyzed = [artifact for check in checks if check["claim"] == "hole-analysis-evidence"
                        for artifact in check["validation"]["artifacts"]
                        if artifact["path"] == exclusion_approval["path"]
                        and artifact["sha256"] == exclusion_approval["sha256"]
                        and artifact["kind"] == "configuration"
                        and "xverif" in artifact.get("analyzed_by", [])]
            if not analyzed:
                reasons.append("缺口分析没有引用并检查负责人提供的当前 exclude 文件")
            expected_waiver = {
                "id": exclusion_approval["id"],
                "reviewer": exclusion_approval["reviewer"],
                "decision_date": exclusion_approval["created_at"][:10],
                "rationale": exclusion_approval["reason"],
                "status": "Approved",
            }
            for item in excluded_items:
                if item.get("waiver") != expected_waiver:
                    reasons.append(item["object_key"] + " 没有引用负责人提供的当前 exclude 文件审批记录")
    if workstream == "VREG" and vreg_stage(node) == "results":
        with store.read_connect() as db:
            reasons.extend(_vreg_result_blockers(store, db, plan, node, checks))
    receipt = {**report, "registration_report": {"path": local_path(store, path),
                                               "sha256": hashlib.sha256(raw_report).hexdigest()},
               "files": file_snapshot(store, files, required=True), "ready": not reasons,
               "blockers": reasons, "checks": checks, "feedback_routes": feedback_routes}
    if workstream == "VCOV":
        receipt["coverage_contract"] = VCOV_VALIDATION_CONTRACT
        if vcov_stage(node) == "convergence":
            receipt["coverage_execution_bindings"] = expected_bindings
            receipt["coverage_exclusion_approval"] = exclusion_approval
            receipt["needs_coverage_exclusion"] = bool(excluded_items and exclusion_approval is None)
    if workstream == "VCASE":
        receipt["testcase_contract"] = VCASE_VALIDATION_CONTRACT
    if workstream == "VREG" and vreg_stage(node) == "results":
        receipt["regression_contract"] = VREG_VALIDATION_CONTRACT
    if {v['path']: v['sha256'] for v in receipt['files']} != expected_files:
        error("检查期间代码或证据发生变化，请重新验证")
    identifier, timestamp = "code-validation:" + uuid.uuid4().hex[:12], now()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        latest_plan, latest_node = selected(store, node_id, db)
        if identity(store, db, latest_plan, latest_node)[0] != signature or receipt["files"] != file_snapshot(store, files, required=True):
            error("登记期间代码或输入已变化，请重新验证")
        if workstream == "VREG" and vreg_stage(node) == "results":
            previous_scope = [check["validation"]["facts"].get("required_nodes") for check in checks if check["claim"] == "fresh-evidence"]
            latest_reasons = _vreg_result_blockers(store, db, latest_plan, latest_node, checks)
            latest_scope = [check["validation"]["facts"].get("required_nodes") for check in checks if check["claim"] == "fresh-evidence"]
            if previous_scope != latest_scope or any(reason not in reasons for reason in latest_reasons):
                error("登记期间必需回归证据或负责人例外批准发生变化，请重新验证")
            previous_state = review_state(store, node_id, latest_plan, latest_node, db)
            previous_validation = previous_state.get("validation")
            keep_round_accepted = bool(
                result_round["status"] == "ACCEPTED" and receipt["ready"]
                and previous_state["completed"] and previous_validation
                and previous_validation["current"]
                and validation_subject(previous_validation) == validation_subject(receipt)
            )
        db.execute("INSERT INTO code_validations VALUES(?,?,?,?,?,?)", (identifier, node_id, node_revision(plan, node), signature, encoded(receipt), timestamp))
        if result_round is not None:
            from .vreg_contract import execution_blockers, normalize_config
            execution_checks = [check for check in checks if check["claim"] == "execution-evidence"]
            execution_facts = {digest(check["validation"]["facts"]): check["validation"]["facts"]
                               for check in execution_checks}.values()
            try:
                terminal_execution = (bool(execution_checks)
                                      and all(check["validation"]["ready"] for check in execution_checks)
                                      and not execution_blockers(normalize_config(json.loads(result_round["config_json"])),
                                          [batch for facts in execution_facts for batch in facts.get("batches", [])],
                                          execution_binding(plan, node, result_round)))
            except (ValueError, TypeError):
                terminal_execution = False
            round_status = ("ACCEPTED" if keep_round_accepted else "VALIDATED" if receipt["ready"]
                            else "FAILED" if terminal_execution else "INTERRUPTED")
            db.execute("UPDATE regression_execution_rounds SET status=?,validated_at=?,validation_id=? WHERE id=?",
                       (round_status, timestamp, identifier, result_round["id"]))
        _sync_watched_files(store, db)
    refresh(store)
    return {"id": identifier, "ready": receipt["ready"], "blockers": reasons,
            "node_id": node_id, "auto_closure": store.evaluate_closure(workstream)}


def refresh(store, plans=None):
    from .store import now, Validity
    from . import vdoc_artifacts
    store.ensure_dashboard_schema()
    token = refresh_token(store)
    if getattr(store, "_code_checkpoint", None) == token:
        return
    plans = store.workstreams() if plans is None else plans
    modern_plans = [plan for plan in plans if modern(plan)]
    if not modern_plans:
        store._code_checkpoint = token
        return
    vdoc_artifacts.reconcile(store, plans)
    token = refresh_token(store)
    if getattr(store, "_code_checkpoint", None) == token:
        return
    timestamp = now()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        def publish(identifier, kind, title, payload, ready, published, workstream):
            current = None
            if ready:
                # An art.code version describes accepted evidence. A fresh receipt
                # with identical evidence must not create a new CAP version.
                subject_payload = dict(payload)
                if identifier.startswith("art.code:") and payload.get("validation"):
                    subject_payload["validation"] = validation_subject(payload["validation"])
                signature = digest(subject_payload)
                row = db.execute("SELECT version,signature FROM code_artifact_versions WHERE artifact_id=? AND signature=?",
                                 (identifier, signature)).fetchone()
                if row is None and identifier.startswith("art.code:"):
                    # Earlier versions used the full receipt, including its ID.
                    # Reuse them when their reviewed content is unchanged.
                    for old in db.execute("SELECT version,signature,payload_json FROM code_artifact_versions WHERE artifact_id=? ORDER BY version DESC",
                                          (identifier,)):
                        old_payload = json.loads(old["payload_json"])
                        if old_payload.get("validation"):
                            old_payload["validation"] = validation_subject(old_payload["validation"])
                        if old_payload == subject_payload:
                            row = old
                            break
                version = row["version"] if row else db.execute("SELECT COALESCE(MAX(version),0)+1 FROM code_artifact_versions WHERE artifact_id=?", (identifier,)).fetchone()[0]
                if row is None:
                    db.execute("INSERT INTO code_artifact_versions VALUES(?,?,?,?,?)", (identifier, version, signature, encoded(payload), timestamp))
                else:
                    signature = row["signature"]
                current = {"version": version, "signature": signature}
            data = {"derived": True, "current": current, "implementation_key": payload.get("implementation_key"),
                    "workstream": workstream}
            status = "VALID" if ready else "REVALIDATION_REQUIRED"
            previous = db.execute("SELECT status,data_json FROM nodes WHERE id=?", (identifier,)).fetchone()
            data = retain_head(data, json.loads(previous["data_json"]) if previous else None)
            if previous is None or previous["status"] != status or json.loads(previous["data_json"]) != data:
                store.upsert_node(db, identifier, kind, title, Validity(status), data=data)
            published.add(identifier)
        # Legacy VREG remains a measurement workflow. Expose its current checked
        # capabilities so code packages can depend on executor readiness without
        # depending directly on a legacy work node.
        vreg_row = db.execute("SELECT revision,desired_json,context_json FROM workstreams WHERE name='VREG'").fetchone()
        if vreg_row is not None and json.loads(vreg_row["context_json"]).get("code_model") != 2:
            for item in json.loads(vreg_row["desired_json"]):
                node = db.execute("SELECT status FROM nodes WHERE id=?", (item["id"],)).fetchone()
                cap_id = "cap.vreg:" + item["key"]
                ready = bool(node and node["status"] == "VALID")
                data = {"derived": True, "current": ({"revision": vreg_row["revision"], "node": item["id"]} if ready else None),
                        "workstream": "VREG"}
                store.upsert_node(db, cap_id, "capability", "回归执行 · " + item["key"],
                                  Validity.VALID if ready else Validity.REVALIDATION_REQUIRED, data=data)
                edge(db, cap_id, item["id"], timestamp)

        for candidate in CODE_WORKSTREAMS:
            if not any(value["workstream"] == candidate for value in modern_plans):
                continue
            plan = store._read_workstream(db, candidate)
            settings = profile(candidate)
            all_derived = {
                row["id"]: dict(row) for row in db.execute(
                    "SELECT * FROM nodes WHERE id LIKE 'art.code%' OR id LIKE ?",
                    (settings["cap_prefix"] + "%",),
                )
            }
            old = {}
            scoped_marker = ":" + candidate.lower() + ":"
            for identifier, row in all_derived.items():
                if identifier.startswith(settings["cap_prefix"]):
                    old[identifier] = row
                    continue
                data = json.loads(row["data_json"] or "{}")
                if data.get("workstream") == candidate:
                    old[identifier] = row
                elif candidate == "VENV" and data.get("workstream") is None and not any(
                    (":" + name.lower() + ":") in identifier for name in CODE_WORKSTREAMS if name != "VENV"
                ):
                    old[identifier] = row
                elif candidate != "VENV" and scoped_marker in identifier:
                    old[identifier] = row
            published = set()
            states = {}
            # Topological order follows accepted package CAP dependencies, not node kinds.
            packages = {n["implementation_key"]: n for n in plan["desired_state"] if is_plan(n)}
            remaining = dict(packages)
            done = set()
            while remaining:
                eligible = [key for key, node in remaining.items() if all(
                    not value.startswith(settings["cap_prefix"])
                    or value.removeprefix(settings["cap_prefix"]) in done
                    for value in node["inputs"]
                )]
                if not eligible:
                    eligible = list(remaining)  # Stale persisted graphs fail closed in review_state.
                for key in eligible:
                    node = remaining.pop(key)
                    p_id, a_id, c_id = ids(key, candidate)
                    bind_feedback_context(store, db, plan, node)
                    state = review_state(store, node["id"], plan, node, db)
                    states[node['id']] = state
                    payload = {"implementation_key": key, "workstream": candidate,
                               "definition": node, "revision": node_revision(plan, node),
                               "review": state["current_completion"], "signature": state["definition_digest"],
                               "dependencies": state['dependencies'], "sources": state['sources']}
                    publish(p_id, "artifact", node["title"] + " · 批准方案", payload,
                            state["completed"], published, candidate)
                    update_status(db, node["id"], "VALID" if state["completed"] else "REVIEW_REQUIRED", timestamp)
                    edge(db, p_id, node["id"], timestamp)
                    delivery = next((n for n in plan["desired_state"] if n.get("parent_id") == node["id"]), None)
                    ready = False
                    if delivery:
                        delivery_state = review_state(store, delivery["id"], plan, delivery, db)
                        states[delivery['id']] = delivery_state
                        ready = delivery_state["completed"] and state["completed"]
                        payload = {"implementation_key": key, "workstream": candidate,
                                   "definition": delivery, "plan": current_head(db, p_id),
                                   "review": delivery_state["current_completion"],
                                   "validation": delivery_state["validation"]}
                        update_status(db, delivery["id"], "VALID" if ready else "REVIEW_REQUIRED", timestamp)
                        edge(db, a_id, delivery["id"], timestamp)
                    publish(a_id, "artifact", node["title"] + " · 验收交付", payload,
                            ready, published, candidate)
                    publish(c_id, "capability", node["title"] + " · 可供下游使用",
                            {"implementation_key": key, "workstream": candidate,
                             "delivery": current_head(db, a_id)}, ready, published, candidate)
                    edge(db, c_id, a_id, timestamp)
                    done.add(key)
            for claim in sorted(settings["allowed_claims"]):
                providers = [n for n in packages.values() if n["required"] and claim in n["capabilities"]]
                heads = [current_head(db, ids(n["implementation_key"], candidate)[2]) for n in providers]
                ready = bool(heads) and all(head and head["status"] == "VALID" for head in heads)
                cap_id = settings["cap_prefix"] + claim
                publish(cap_id, "capability", settings["label"] + " · " + claim,
                        {"workstream": candidate, "providers": heads}, ready, published, candidate)
                for head in heads:
                    edge(db, cap_id, head["id"], timestamp)
            for identifier in old.keys() - published:
                update_status(db, identifier, "REVALIDATION_REQUIRED", timestamp)
            # Any withdrawn CAP invalidates already-completed downstream consumers.
            revoked = []
            for identifier, previous in old.items():
                current = db.execute("SELECT status FROM nodes WHERE id=?", (identifier,)).fetchone()
                if previous["status"] == "VALID" and current and current["status"] != "VALID":
                    revoked.append(identifier)
            for identifier in revoked:
                for target in store._impact_targets(db, identifier):
                    db.execute("UPDATE nodes SET status='REVALIDATION_REQUIRED',updated_at=? WHERE id=? AND status='VALID'", (timestamp, target))
            lifecycle = closure(store, plan, False, states)['lifecycle']
            db.execute("UPDATE workstreams SET lifecycle=?,updated_at=? WHERE name=? AND lifecycle!=?",
                       (lifecycle, timestamp, candidate, lifecycle))
            for loaded in plans:
                if loaded['workstream'] == candidate and loaded['revision'] == plan['revision']:
                    loaded['lifecycle'] = lifecycle
        _sync_watched_files(store, db)
        counter = db.execute('SELECT version FROM agent_service_changes WHERE id=1').fetchone()[0]
    store._code_checkpoint = (counter, token[1])


def current_head(db, identifier):
    row = db.execute("SELECT status,data_json FROM nodes WHERE id=?", (identifier,)).fetchone()
    return {"id": identifier, "status": row["status"], **json.loads(row["data_json"])} if row else None


def update_status(db, identifier, status, timestamp):
    db.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=? AND status!=?", (status, timestamp, identifier, status))


def closure(store, plan, persist, states=None):
    from .store import now
    workstream = plan["workstream"]
    actions = []
    nodes = plan["desired_state"]
    states = states if states is not None else {
        n['id']: review_state(store, n['id'], plan, n) for n in nodes}
    with store.read_connect() as db:
        pending_changes = [dict(r) for r in db.execute(
            "SELECT id,target,reason FROM human_actions WHERE status='OPEN' AND action='REQUEST_CHANGE' "
            "AND (target=? OR target LIKE ?)", (workstream, f"workstream:{workstream}:%"))]
    for change in pending_changes:
        actions.append({"kind": "APPLY_WORKFLOW_CHANGE", "target": change['target'],
                        "executor": "reasoning", "reason": change['reason'], "change_id": change['id']})
    if not nodes:
        actions.append({"kind": "REFINE_DESIRED_STATE", "target": f"workstream:{workstream}", "executor": "reasoning", "reason": "请 Agent 根据已验收文档和上游能力形成当前 DUT 的" + profile(workstream).get("plan_term", "代码实现方案")})
    elif workstream in {"VCOV", "VREG"}:
        structure = vcov_structure_blockers(plan) if workstream == "VCOV" else vreg_structure_blockers(plan)
        for node in nodes:
            if is_plan(node) and node["required"] and states[node["id"]]["completed"] and not any(
                    is_delivery(child) and child.get("parent_id") == node["id"] and child["required"]
                    and stage(child, workstream) == stage(node, workstream)
                    and child.get("implementation_key") == node.get("implementation_key") for child in nodes):
                structure.append(node["title"] + " 缺少对应的必需交付节点")
        if structure:
            actions.append({"kind": "REFINE_DESIRED_STATE", "target": f"workstream:{workstream}",
                            "executor": "reasoning", "reason": "；".join(structure)})
    for node in nodes:
        if not node["required"]:
            continue
        state = states[node['id']]
        feedback = state["feedback"]
        validation = state.get("validation") or {}
        routes = validation.get("feedback_routes", []) if validation.get("current") else []
        if feedback["draft_count"]:
            kind, actor, reason = "SUBMIT_REVIEW_FEEDBACK", "human", "请提交当前审批意见给 Agent"
        elif feedback["processing_count"]:
            kind, actor, reason = "APPLY_REVIEW_FEEDBACK", "reasoning", "请逐条处理已提交的审批意见并登记结果"
        elif state["completed"]:
            continue
        elif state["can_approve"]:
            kind, actor, reason = "HUMAN_REVIEW", "human", "等待负责人" + (
                ("审批" if is_plan(node) else "验收") + node_label(node, workstream)
            )
        elif (workstream == "VCOV" and is_delivery(node) and vcov_stage(node) == "convergence"
              and validation.get("current") and validation.get("needs_coverage_exclusion")):
            kind, actor = "PROVIDE_COVERAGE_EXCLUSIONS", "human"
            reason = "覆盖率报告包含排除项；请负责人提供已审批的 exclude 文件，随后由 Agent 重新验证"
        else:
            kind, actor, reason = "IMPLEMENT_AND_VALIDATE", "reasoning", "；".join(state["blockers"])
            if routes:
                kind, actor = "ANALYZE_VERIFICATION_FEEDBACK", "reasoning"
                targets = sorted({route["responsible_workstream"] for route in routes})
                reason = "分析验证反馈并向责任工作流登记重规划或重验证要求：" + "、".join(targets)
            if workstream in {"VCOV", "VREG"} and is_plan(node) and any("请重新形成方案" in r for r in state["blockers"]):
                kind, actor = "REFINE_DESIRED_STATE", "reasoning"
            elif is_plan(node) or any("前置结果" in r for r in state["blockers"]):
                kind, actor = "WAIT_FOR_DEPENDENCY", "deterministic"
        actions.append({"kind": kind, "target": node["id"], "executor": actor, "reason": reason,
                        "batch_ids": feedback["batch_ids"],
                        "execution_binding": ((state.get("regression_execution") or {}).get("current") or {}).get("execution_binding"),
                        "feedback_routes": routes})
    for action in actions:
        action.update(priority=1 if action["executor"] == "human" else 3, suggested_mode="plan" if action["target"] == f"workstream:{workstream}" else "code")
        action["id"] = "action:" + digest(action)[:12]
    approved = any(is_plan(n) and states[n['id']]["completed"] for n in nodes)
    lifecycle = "SATISFIED" if not actions and nodes else "ACTIVE" if approved else "REVIEW"
    if lifecycle == 'SATISFIED' and plan['lifecycle'] == 'BASELINED':
        lifecycle = 'BASELINED'
    if persist:
        with store.connect() as db:
            known = {r[0] for r in db.execute("SELECT id FROM actions WHERE workstream=? AND status='OPEN'", (workstream,))}
            if known != {a["id"] for a in actions}:
                db.execute("DELETE FROM actions WHERE workstream=? AND status='OPEN'", (workstream,))
                for a in actions:
                    db.execute("INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?,?)", (a["id"], workstream, a["kind"], a["target"], a["priority"], "OPEN", a["executor"], a["suggested_mode"], a["reason"], now()))
            db.execute("UPDATE workstreams SET lifecycle=?,updated_at=? WHERE name=? AND lifecycle!=?", (lifecycle, now(), workstream, lifecycle))
        store.write_workstream_projection(workstream)
    return {"workstream": workstream, "ready": not actions and bool(nodes), "lifecycle": lifecycle, "actions": actions}


def artifacts(store, workstream=None):
    refresh(store)
    prefixes = tuple(profile(name)["cap_prefix"] for name in CODE_WORKSTREAMS if workstream is None or name == workstream)
    with store.read_connect() as db:
        rows = db.execute("SELECT * FROM nodes WHERE id LIKE 'art.code%' OR id LIKE 'cap.%'")
        heads = []
        for row in rows:
            data = json.loads(row["data_json"])
            if row["id"].startswith(prefixes) or (row["id"].startswith("art.code") and (workstream is None or data.get("workstream", "VENV") == workstream)):
                heads.append({**dict(row), "data": data})
        versions = [{**dict(r), "payload": json.loads(r["payload_json"])} for r in db.execute("SELECT * FROM code_artifact_versions ORDER BY artifact_id,version")]
        if workstream is not None:
            versions = [value for value in versions if value["payload"].get("workstream", "VENV") == workstream]
    return {"heads": heads, "versions": versions}


def request_change(store, body):
    from .store import now
    reviewer, reason = str(body.get("reviewer", "")).strip(), str(body.get("reason", "")).strip()
    kind = body.get("kind")
    workstream = str(body.get("workstream") or "VENV").upper()
    profile(workstream)
    plan = store.workstream(workstream)
    if not modern(plan):
        error(f"{workstream} 尚未使用代码方案工作流")
    if not reviewer or not reason or body.get("revision") != plan["revision"]:
        error("必须填写操作人和具体要求，且工作流版本不能发生变化")
    if kind == "restart":
        if body.get("confirm") is not True:
            error("重新启动工作流需要再次确认")
        return design(store, workstream, None, restart={"reviewer": reviewer, "reason": reason, "revision": plan["revision"]})
    if kind not in {"add", "remove"}:
        error("未知的工作流变更操作")
    target = workstream
    if kind == "remove":
        target = str(body.get("node", ""))
        _, node = selected(store, target)
        if not is_plan(node):
            error("删除要求应选择一个覆盖率方案节点" if workstream == "VCOV" else
                  "删除要求应选择一个回归方案节点" if workstream == "VREG" else "删除要求应选择一个代码工作包")
    identifier, timestamp = 'human:' + uuid.uuid4().hex[:12], now()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = store._read_workstream(db, workstream)
        if current['revision'] != plan['revision']:
            error("工作流版本已变化，请刷新后重新提交变更要求")
        db.execute('INSERT INTO human_actions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   (identifier, target, 'workstream' if target == workstream else 'node',
                    'REQUEST_CHANGE', 'OPEN', reviewer, reason,
                    encoded({'change_kind': kind, 'revision': plan['revision'], 'next_revision_only': True}),
                    None, None, timestamp, timestamp))
    return store.human_action(identifier)


def provide_coverage_exclusions(
    store, node_id, reviewer, reason="", *, confirm=False, source=None,
    content=None, filename=None,
):
    """Record one owner-provided exclusion file as the approval for its contents."""
    from .store import now
    refresh(store)
    reviewer = str(reviewer or "").strip()
    reason = str(reason or "").strip() or "负责人确认该 exclude 文件中的覆盖率排除范围"
    if not reviewer or confirm is not True:
        error("提供 exclude 文件必须填写负责人并显式确认；提供即表示其中排除范围已审批")
    plan, node = selected(store, node_id)
    if plan["workstream"] != "VCOV" or not is_delivery(node) or vcov_stage(node) != "convergence":
        error("exclude 文件只能提供给当前 VCOV 覆盖率收敛交付节点")
    if content is None:
        if not source:
            error("必须提供 exclude 文件")
        source_path = store.root / local_path(store, source)
        try:
            raw = source_path.read_bytes()
        except OSError as exc:
            error(f"无法读取 exclude 文件：{exc}")
        original_name = source_path.name
    else:
        if not isinstance(content, (bytes, bytearray)):
            error("exclude 文件内容必须是 bytes")
        raw = bytes(content)
        original_name = Path(str(filename or "coverage-exclusions.el")).name
    if not raw:
        error("exclude 文件不能为空")
    if len(raw) > MAX_COVERAGE_EXCLUSION_BYTES:
        error("exclude 文件不能超过 512 KiB")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", original_name).strip("._-")
    if not safe_name:
        safe_name = "coverage-exclusions.el"
    sha256 = hashlib.sha256(raw).hexdigest()
    directory = store.state / "coverage-exclusions" / digest(node_id)[:12]
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = directory / f"{sha256[:16]}-{safe_name}"
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
            error("受控 exclude 文件路径存在内容冲突")
    else:
        temporary = target.with_name(target.name + ".tmp-" + uuid.uuid4().hex[:8])
        temporary.write_bytes(raw)
        temporary.chmod(0o600)
        os.replace(temporary, target)
    relative = str(target.relative_to(store.root))
    identifier, timestamp = "coverage-exclusion:" + uuid.uuid4().hex[:12], now()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        latest_plan, latest_node = selected(store, node_id, db)
        if (latest_plan["revision"] != plan["revision"]
                or coverage_exclusion_scope_digest(latest_plan, latest_node)
                != coverage_exclusion_scope_digest(plan, node)):
            error("登记期间覆盖率收敛范围已经变化，请刷新后重新提供 exclude 文件")
        db.execute(
            "INSERT INTO coverage_exclusion_approvals VALUES(?,?,?,?,?,?,?,?,?,?)",
            (identifier, node_id, "VCOV", plan["revision"],
             coverage_exclusion_scope_digest(plan, node), relative, sha256,
             reviewer, reason, timestamp),
        )
        _sync_watched_files(store, db)
    refresh(store)
    state = review_state(store, node_id)
    return {"approval": state["coverage_exclusion"]["current"],
            "history_count": len(state["coverage_exclusion"]["history"]),
            "validation_current": bool(state.get("validation") and state["validation"]["current"]),
            "auto_closure": store.evaluate_closure("VCOV")}


def content(store, node_id, path, expected):
    refresh(store)
    state = review_state(store, node_id)
    receipt = state.get("validation")
    if not receipt or not receipt["current"]:
        error("当前代码或证据已经变化，请返回节点重新验证")
    file = next((f for f in receipt["files"] if f["path"] == path and f["sha256"] == expected), None)
    if not file:
        error("该文件不属于当前节点的验证证据")
    safe = store.root / local_path(store, path)
    if file_snapshot(store, [path], required=True)[0] != file:
        error("文件版本已变化，请刷新")
    with safe.open("rb") as stream:
        data = stream.read(65537)
    try:
        text = data[:65536].decode("utf-8")
    except UnicodeDecodeError:
        error("该证据是二进制文件，请使用对应的验证工具查看")
    return {"node_id": node_id, "path": path, "content": text + ("\n（仅预览前 64 KiB）" if len(data) > 65536 else "")}


def coverage_exclusion_content(store, node_id, path, expected):
    refresh(store)
    plan, node = selected(store, node_id)
    if plan["workstream"] != "VCOV" or not is_delivery(node) or vcov_stage(node) != "convergence":
        error("该节点没有覆盖率 exclude 文件")
    with store.read_connect() as db:
        state = coverage_exclusion_state(store, db, plan, node)
    approval = state["current"]
    if not approval or approval["path"] != path or approval["sha256"] != expected:
        error("该 exclude 文件不属于当前覆盖率收敛范围，或文件版本已经变化")
    safe = store.root / local_path(store, path)
    try:
        data = safe.read_bytes()
    except OSError as exc:
        error(f"无法读取当前 exclude 文件：{exc}")
    if hashlib.sha256(data).hexdigest() != expected:
        error("读取期间 exclude 文件已经变化，请刷新")
    try:
        preview = data[:65536].decode("utf-8")
    except UnicodeDecodeError:
        error("该 exclude 文件不是 UTF-8 文本；Agent 仍可通过专用工具分析")
    return {"node_id": node_id, "path": path,
            "content": preview + ("\n（仅预览前 64 KiB）" if len(data) > 65536 else "")}
