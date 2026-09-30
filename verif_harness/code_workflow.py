"""Code plans, validated deliveries, and version-bound capabilities.

No simulator is launched here. Main Agent submits typed tool reports; existing
evidence admission rules check them before a delivery can be offered for review.
"""
from __future__ import annotations

import json
import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

from .vdoc_artifacts import digest, encoded

VCOV_PLAN_ROLES = {"coverage-implementation-plan", "coverage-convergence-plan"}
VCOV_DELIVERY_ROLES = {"coverage-implementation-deliverable", "coverage-convergence-deliverable"}
PLAN_ROLES = {"code-plan", *VCOV_PLAN_ROLES}
DELIVERY_ROLES = {"code-deliverable", *VCOV_DELIVERY_ROLES}
ROLES = PLAN_ROLES | DELIVERY_ROLES
VCOV_IMPLEMENTATION_CLAIMS = {"coverage-model", "coverage-collection"}
VCOV_CONVERGENCE_CLAIMS = {"coverage-collection-evidence", "hole-analysis-evidence"}
VCOV_VALIDATION_CONTRACT = "CoverageConvergence/2"
VCOV_ROLE_LABELS = {
    "coverage-implementation-plan": "覆盖率实现方案",
    "coverage-implementation-deliverable": "覆盖率实现交付",
    "coverage-convergence-plan": "覆盖率收敛方案",
    "coverage-convergence-deliverable": "覆盖率收敛交付",
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
        "plan_term": "回归执行与闭环方案",
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
"""


def modern(plan):
    return (plan.get("workstream") in CODE_WORKSTREAMS
            and plan.get("planning_context", {}).get("code_model") == 2)


def supported(workstream):
    return workstream in CODE_WORKSTREAMS


def is_plan(node):
    return node.get("role") in PLAN_ROLES


def is_delivery(node):
    return node.get("role") in DELIVERY_ROLES


def coverage_items(node):
    from .evidence_contracts import ID
    value = node.get("coverage_item_ids")
    return bool(isinstance(value, list) and value and all(
        isinstance(identifier, str) and ID.fullmatch(identifier)
        for identifier in value) and len(value) == len(set(value)))


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


def node_label(node, workstream):
    if workstream == "VCOV":
        return VCOV_ROLE_LABELS.get(vcov_role(node), "覆盖率工作节点")
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
        result.append({"id": row["id"], "title": row['title'], "status": row["status"], "current": data.get("current")})
    return result


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
    payload = {"revision": plan["revision"], "node": node, "dependencies": deps,
               "sources": file_snapshot(store, node.get("input_files", [])),
               "project": str(store.root), "project_inputs": cached[1],
               "questions": [dict(r) for r in connection.execute(
                   'SELECT id,status,answer_option,answer_text,answered_at FROM agent_questions WHERE target=? ORDER BY id',
                   (node['id'],))]}
    if is_delivery(node):
        payload["outputs"] = file_snapshot(store, node["output_paths"])
    return digest(payload), payload


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
    value["current"] = (row["signature"] == signature and row["revision"] == plan["revision"]
                        and value["files"] == file_snapshot(store, [v["path"] for v in value["files"]]))
    if plan["workstream"] == "VCOV" and value.get("coverage_contract") != VCOV_VALIDATION_CONTRACT:
        value["current"] = False
    return value


def review_state(store, node_id, plan=None, node=None, connection=None):
    if connection is None:
        with store.read_connect() as db:
            return review_state(store, node_id, plan, node, db)
    if plan is None or node is None:
        plan, node = selected(store, node_id, connection)
    signature, snapshot = identity(store, connection, plan, node)
    validation = validation_current(store, connection, plan, node, signature) if is_delivery(node) else None
    # Owner approval binds the exact validation receipt too, not just code files.
    approval_digest = digest({"definition": signature, "validation": validation["id"] if validation and validation["current"] else None})
    history = [dict(r) for r in connection.execute("SELECT * FROM node_plan_reviews WHERE node_id=? ORDER BY rowid", (node_id,))]
    opinions = [dict(r) for r in connection.execute("SELECT * FROM node_plan_section_reviews WHERE node_id=? ORDER BY rowid", (node_id,))]
    feedback = feedback_state(connection, plan, node, approval_digest)
    changes = store._review_change_items(connection, [r["id"] for r in opinions])
    for row in opinions:
        row["change_items"] = changes.get(row["id"], [])
        row["feedback_items"] = [v for v in feedback["items"] if v["review_id"] == row["id"]]
    latest_opinion = max((r["created_at"] for r in opinions), default="")
    completion = next((r for r in reversed(history) if r["definition_digest"] == approval_digest
                       and r["revision"] == plan["revision"] and r["created_at"] >= latest_opinion), None)
    reasons = blockers(connection, node_id)
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
        if vcov_stage(node) == "implementation" and not coverage_items(node):
            reasons.append("覆盖率实现方案缺少已批准的必需覆盖项清单，请重新形成方案")
        if vcov_stage(node) == "convergence":
            manifests, manifest_reasons = _vcov_expected_manifests(store, connection, plan, node)
            reasons.extend(manifest_reasons)
            if is_delivery(node) and validation and validation["current"]:
                for claim in sorted(VCOV_CONVERGENCE_CLAIMS):
                    observed = {check.get("validation", {}).get("facts", {}).get("coverage_manifest_digest")
                                for check in validation.get("checks", []) if check.get("claim") == claim}
                    if not manifests or observed != manifests:
                        reasons.append("覆盖率收敛证据的覆盖项清单与已验收实现不一致：" + claim)
    complete = bool(completion and not reasons)
    return {"node_id": node_id, "workstream": workstream, "revision": plan["revision"],
            "definition_digest": approval_digest, "input_signature": signature,
            "status": "APPROVED" if complete else "PENDING", "completed": complete,
            "current_completion": completion if complete else None,
            "completion_reviews": history, "reviews": opinions,
            "sections": [{"section": "writing-plan", "status": "APPROVED" if complete else "PENDING"}],
            "feedback": feedback, "can_approve": not reasons, "blockers": reasons,
            "validation": validation, "code_files": snapshot.get("outputs", []),
            "dependencies": snapshot['dependencies'], "sources": snapshot['sources']}


def feedback_state(connection, plan, node, signature):
    rows = [dict(r) for r in connection.execute("SELECT * FROM review_feedback_items WHERE node_id=? ORDER BY rowid", (node["id"],))]
    current = [r for r in rows if r["revision"] == plan["revision"]]
    drafts = [r for r in current if r["status"] == "DRAFT"]
    pending = [r for r in current if r["status"] in {"PENDING", "WAITING_FOR_HUMAN"}]
    return {"node_id": node["id"], "revision": plan["revision"], "definition_digest": signature,
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
        infrastructure = {"regression-policy", "executor-ready"}
        closure = {"execution-evidence", "triage-evidence", "fresh-evidence"}
        if frozenset(claims) not in {frozenset(infrastructure), frozenset(closure)}:
            error("VREG 工作包必须是回归策略与执行器，或执行、失败分类和结果新鲜度证据；两类工作包不能混在一起")


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


def _vcov_expected_manifests(store, connection, plan, node):
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
        manifests = {check.get("validation", {}).get("facts", {}).get("coverage_manifest_digest") for check in checks}
        manifests.discard(None)
        if not state["completed"] or not manifests:
            reasons.append(provider["title"] + " 缺少当前已验收的覆盖项清单，请重新验证实现")
        expected.update(manifests)
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
    connection.execute("DELETE FROM code_watched_files")
    connection.executemany(
        "INSERT INTO code_watched_files VALUES(?)", [(path,) for path in sorted(watched)],
    )


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
            error("覆盖率方案必须包含工作节点" if workstream == "VCOV" else "代码实现方案必须包含工作包")
    normalized = []
    known_keys = set()
    known_outputs = set()
    for raw in nodes:
        allowed_roles = {"code-plan", *VCOV_PLAN_ROLES} if workstream == "VCOV" else {"code-plan"}
        if not isinstance(raw, dict) or raw.get("role") not in allowed_roles:
            error("VCOV 方案只能包含覆盖率实现方案或覆盖率收敛方案；批准后建立对应交付节点"
                  if workstream == "VCOV" else f"{workstream} 方案只包含 code-plan；批准后由系统建立对应 code-deliverable")
        key = raw.get("implementation_key", "")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*:[a-z0-9][a-z0-9._:-]*", key) or key in known_keys:
            error("implementation_key 必须是唯一、稳定的方案与交付关联标识" if workstream == "VCOV"
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
                item["coverage_item_ids"] = raw.get("coverage_item_ids")
                if not coverage_items(item):
                    error("覆盖率实现方案必须列出非空、唯一且有效的 coverage_item_ids，供负责人批准覆盖范围")
            elif "coverage_item_ids" in raw:
                error("覆盖率收敛范围由明确关联的实现能力继承，不另行登记 coverage_item_ids")
        if not all(v.startswith(settings["input_prefixes"]) for v in item["inputs"]):
            error(f"{workstream} 上游必须使用 " + "、".join(settings["input_prefixes"]) + "，不能依赖工作节点、未验收产物或下游结果")
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
        if ids(key, workstream)[2] in item["inputs"]:
            error("覆盖率方案不能依赖自己的交付能力" if workstream == "VCOV" else "工作包不能依赖自己的交付能力")
        item["output_paths"] = store._normalized_write_scopes(item["output_paths"])
        for path in item["output_paths"]:
            if any(store._scopes_overlap(path, old) for old in known_outputs):
                error("覆盖率节点的输出范围不能重叠" if workstream == "VCOV" else "工作包的输出范围不能重叠")
            known_outputs.add(path)
        item["input_files"] = [store._project_or_declared_input_path(v) for v in strings(raw, "input_files")]
        if any(not (Path(v) if Path(v).is_absolute() else store.root / v).is_file() for v in item["input_files"]):
            error("input_files 必须逐项引用实际输入文件，目录仅用于界面展示")
        item.update(required=raw.get("required", True), purpose=item["statement"],
                    suggested_mode="plan", definition_origin="project-proposal",
                    definition_status="REVIEW_CANDIDATE", quality_checks=item["validation_methods"],
                    progress_measures=[], evidence_claim="code-validation", parent_id=None,
                    role_description=("当前 DUT 的" + node_label(item, workstream) if workstream == "VCOV"
                                      else "当前 DUT 工作包的" + settings.get("plan_term", "代码实现方案")))
        if not isinstance(item["required"], bool):
            error("required 必须是布尔值")
        normalized.append(item)
    if len({n["key"] for n in normalized}) != len(normalized):
        error("代码方案 key 不能重复")
    by_cap = {ids(n["implementation_key"], workstream)[2]: n for n in normalized}
    def visit(cap, parents):
        if cap in parents:
            error("覆盖率节点存在循环依赖" if workstream == "VCOV" else "代码工作包存在循环依赖")
        for target in by_cap.get(cap, {}).get("inputs", []):
            if target.startswith(settings["cap_prefix"]):
                if target not in by_cap:
                    error(("当前方案没有提供前置覆盖率实现节点：" if workstream == "VCOV"
                           else "当前方案没有提供前置工作包：") + target)
                if workstream == "VCOV" and vcov_stage(by_cap[target]) != "implementation":
                    error("覆盖率收敛方案必须依赖覆盖率实现能力，不能依赖收敛结果")
                visit(target, parents | {cap})
    for cap in by_cap:
        visit(cap, set())
    timestamp = now()
    context = {**store.planning_context(workstream), "code_model": 2}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT revision,desired_json FROM workstreams WHERE name=?", (workstream,)).fetchone()
        revision = old["revision"] + 1 if old else 1
        if restart and (not old or restart["revision"] != old["revision"]):
            error(f"{workstream} 版本已变化，请刷新后重新确认")
        previous = json.loads(old["desired_json"]) if old else []
        previous_edges = [dict(row) for row in db.execute(
            "SELECT e.* FROM edges e JOIN nodes n ON n.id=e.target WHERE n.workstream=?",
            (workstream,),
        )]
        db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", (
            "event:" + uuid.uuid4().hex, workstream.lower() + "-replan",
            f"workstream:{workstream}", str(revision),
            encoded({"previous_nodes": previous, "restart": restart, "previous_edges": previous_edges}),
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
        db.execute("UPDATE review_feedback_items SET status='SUPERSEDED',updated_at=?,resolved_at=? WHERE workstream=? AND status IN ('DRAFT','PENDING','WAITING_FOR_HUMAN')", (timestamp, timestamp, workstream))
        for item in normalized:
            item["id"] = f"workstream:{workstream}:r{revision}:desired:{item['key']}"
            store.upsert_node(db, item["id"], "desired-state", item["title"], Validity.REVIEW_REQUIRED, workstream, item)
            for target in item["inputs"]:
                if not db.execute("SELECT 1 FROM nodes WHERE id=?", (target,)).fetchone():
                    store.upsert_node(db, target, "capability", "前置交付尚未验收", Validity.UNKNOWN, data={"derived": True})
                edge(db, item["id"], target, timestamp)
        db.execute("INSERT INTO workstreams VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET lifecycle=excluded.lifecycle,revision=excluded.revision,objective=excluded.objective,desired_json=excluded.desired_json,exit_json=excluded.exit_json,decisions_json=excluded.decisions_json,context_json=excluded.context_json,updated_at=excluded.updated_at",
                   (workstream, "REVIEW", revision, objective or settings["objective"], encoded(normalized),
                    encoded(["当前必需覆盖率实现与收敛节点均已验证并由负责人验收" if workstream == "VCOV"
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
    role = vcov_role(node).replace("-plan", "-deliverable") if workstream == "VCOV" else "code-deliverable"
    value = {**node, "id": node["id"] + ":delivery", "key": node["key"] + "-delivery",
             "role": role, "title": node["title"] + " · " + node_label({**node, "role": role}, workstream),
             "parent_id": node["id"], "parent_key": node["key"], "suggested_mode": "implement",
             "role_description": "Agent 先完成实现与验证，再由负责人验收当前代码和证据"}
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
            db.execute("INSERT INTO node_plan_reviews VALUES(?,?,?,?,?,?,?,?,?)", (review_id, node_id, plan["workstream"], plan["revision"], expected, "APPROVE", reviewer.strip(), reason.strip(), timestamp))
            if is_plan(node):
                create_delivery(store, db, plan, node, timestamp)
        else:
            if state["feedback"]["processing_count"]:
                error("上一批意见仍在等待 Agent 处理")
            if not reason.strip():
                error("请填写审批内容")
            normalized = store._normalize_review_change_items(verdict, changes, default_target=node["title"], default_instruction=reason)
            db.execute("INSERT INTO node_plan_section_reviews VALUES(?,?,?,?,?,?,?,?,?,?)", (review_id, node_id, plan["workstream"], plan["revision"], expected, "writing-plan", verdict.upper(), reviewer.strip(), reason.strip(), timestamp))
            store._store_review_change_items(db, review_id, normalized)
            store._store_review_feedback_items(db, review_id, node_id, plan["revision"], expected, "", reviewer, normalized, timestamp, workstream=plan["workstream"])
        store._record_review_submitted_event(db, review_id, node_id, verdict, reviewer, changes or [], timestamp, agent_follow_up="NONE" if verdict == "approve" else "AWAITING_FEEDBACK_SUBMISSION")
    refresh(store)
    return {"review_id": review_id, "node_id": node_id, "verdict": verdict.upper(),
            "plan_review": review_state(store, node_id), "auto_closure": store.evaluate_closure(plan["workstream"])}


def _validate_evidence(store, path, workstream, claim):
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
        return validate_workstream_evidence(path, workstream, claim, artifact_root=store.root)
    except EvidenceContractError as exc:
        error(str(exc))


def _feedback_routes(workstream, claim, facts):
    """Extract analysis-driven feedback; this never mutates the target workflow."""
    routes = []
    if workstream == "VCOV" and claim == "hole-analysis-evidence":
        for item in facts.get("items", []):
            if item.get("status") != "uncovered" or not item.get("responsible_workstream"):
                continue
            routes.append({
                "source_workstream": workstream,
                "source_claim": claim,
                "finding": item.get("id"),
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
                "finding": item.get("test"),
                "responsible_workstream": item.get("responsible_workstream"),
                "target_implementation_key": item.get("target_implementation_key") or "",
                "next_action": item.get("next_action") or "",
            })
    return routes


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
    if not isinstance(report, dict) or report.get("schema") != "CodeValidation/1" or report.get("node_id") != node_id or report.get("revision") != plan["revision"] or report.get("input_signature") != signature:
        error("验证报告必须绑定当前项目节点、revision 和 input_signature")
    workstream = plan["workstream"]
    if {d['id'] for d in snapshot['dependencies']} != {ids(node['implementation_key'], workstream)[0]} or any(d["status"] != "VALID" or not d['current'] for d in snapshot["dependencies"]):
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
        result = _validate_evidence(store, evidence_path, workstream, check["claim"])
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
    if workstream == "VCOV" and vcov_stage(node) == "implementation":
        source_digests = {source["sha256"] for source in snapshot["sources"]}
        output_digests = {output["sha256"] for output in snapshot["outputs"]}
        for facts in facts_by_claim.get("coverage-model", []):
            if set(facts.get("required_item_ids", [])) != set(node.get("coverage_item_ids", [])):
                reasons.append("覆盖项清单与负责人批准的必需覆盖范围不一致")
            if facts.get("plan_digest") not in source_digests:
                reasons.append("覆盖计划摘要不属于批准方案的当前输入文件")
            if facts.get("model_digest") not in output_digests:
                reasons.append("覆盖模型摘要不属于当前交付文件")
        for facts in facts_by_claim.get("coverage-collection", []):
            if facts.get("exporter_digest") not in output_digests:
                reasons.append("覆盖率采集配置摘要不属于当前交付文件")
    if workstream == "VCOV" and vcov_stage(node) == "convergence":
        with store.read_connect() as db:
            expected_manifests, manifest_reasons = _vcov_expected_manifests(store, db, plan, node)
        reasons.extend(manifest_reasons)
        for claim in sorted(VCOV_CONVERGENCE_CLAIMS):
            observed = {facts.get("coverage_manifest_digest") for facts in facts_by_claim.get(claim, [])}
            if not expected_manifests or observed != expected_manifests:
                reasons.append("覆盖率收敛证据的覆盖项清单与已验收实现不一致：" + claim)
        databases_by_claim = {}
        for claim in VCOV_CONVERGENCE_CLAIMS:
            databases = {}
            for check in checks:
                if check["claim"] == claim:
                    evidence = check["validation"]
                    databases.setdefault(evidence["facts"].get("coverage_manifest_digest"), set()).update(
                        artifact["sha256"] for artifact in evidence["artifacts"]
                        if artifact["kind"] == "coverage-database")
            databases_by_claim[claim] = databases
        if databases_by_claim["coverage-collection-evidence"] != databases_by_claim["hole-analysis-evidence"]:
            reasons.append("缺口分析没有使用本轮采集和合并的同一覆盖率数据库")
        with store.read_connect() as db:
            for facts in facts_by_claim.get("hole-analysis-evidence", []):
                for item in facts.get("items", []):
                    if item.get("status") != "excluded":
                        continue
                    waiver = item.get("waiver") or {}
                    record = db.execute("SELECT * FROM reviews WHERE id=? AND verdict='WAIVE'", (waiver.get("id"),)).fetchone()
                    if (record is None or record["workstream"] != "VCOV" or record["revision"] != plan["revision"]
                            or record["reviewer"] != waiver.get("reviewer")
                            or record["created_at"][:10] != waiver.get("decision_date")
                            or not re.search(r"(?<![A-Za-z0-9_.:-])" + re.escape(item["id"])
                                             + r"(?![A-Za-z0-9_.:-])", record["reason"])):
                        reasons.append(item["id"] + " 的排除项没有当前版本的负责人例外批准记录")
    receipt = {**report, "files": file_snapshot(store, files, required=True), "ready": not reasons,
               "blockers": reasons, "checks": checks, "feedback_routes": feedback_routes}
    if workstream == "VCOV":
        receipt["coverage_contract"] = VCOV_VALIDATION_CONTRACT
    if {v['path']: v['sha256'] for v in receipt['files']} != expected_files:
        error("检查期间代码或证据发生变化，请重新验证")
    identifier, timestamp = "code-validation:" + uuid.uuid4().hex[:12], now()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        latest_plan, latest_node = selected(store, node_id, db)
        if identity(store, db, latest_plan, latest_node)[0] != signature or receipt["files"] != file_snapshot(store, files, required=True):
            error("登记期间代码或输入已变化，请重新验证")
        db.execute("INSERT INTO code_validations VALUES(?,?,?,?,?,?)", (identifier, node_id, plan["revision"], signature, encoded(receipt), timestamp))
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
                signature = digest(payload)
                row = db.execute("SELECT version FROM code_artifact_versions WHERE artifact_id=? AND signature=?", (identifier, signature)).fetchone()
                version = row[0] if row else db.execute("SELECT COALESCE(MAX(version),0)+1 FROM code_artifact_versions WHERE artifact_id=?", (identifier,)).fetchone()[0]
                if row is None:
                    db.execute("INSERT INTO code_artifact_versions VALUES(?,?,?,?,?)", (identifier, version, signature, encoded(payload), timestamp))
                current = {"version": version, "signature": signature}
            data = {"derived": True, "current": current, "implementation_key": payload.get("implementation_key"),
                    "workstream": workstream}
            status = "VALID" if ready else "REVALIDATION_REQUIRED"
            previous = db.execute("SELECT status,data_json FROM nodes WHERE id=?", (identifier,)).fetchone()
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
                    state = review_state(store, node["id"], plan, node, db)
                    states[node['id']] = state
                    payload = {"implementation_key": key, "workstream": candidate,
                               "definition": node, "revision": plan["revision"],
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
    elif workstream == "VCOV":
        structure = vcov_structure_blockers(plan)
        for node in nodes:
            if is_plan(node) and node["required"] and states[node["id"]]["completed"] and not any(
                    is_delivery(child) and child.get("parent_id") == node["id"] and child["required"]
                    and vcov_stage(child) == vcov_stage(node)
                    and child.get("implementation_key") == node.get("implementation_key") for child in nodes):
                structure.append(node["title"] + " 缺少对应的必需交付节点")
        if structure:
            actions.append({"kind": "REFINE_DESIRED_STATE", "target": "workstream:VCOV",
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
        else:
            kind, actor, reason = "IMPLEMENT_AND_VALIDATE", "reasoning", "；".join(state["blockers"])
            if routes:
                kind, actor = "ANALYZE_VERIFICATION_FEEDBACK", "reasoning"
                targets = sorted({route["responsible_workstream"] for route in routes})
                reason = "分析验证反馈并向责任工作流登记重规划或重验证要求：" + "、".join(targets)
            if workstream == "VCOV" and is_plan(node) and any("请重新形成方案" in r for r in state["blockers"]):
                kind, actor = "REFINE_DESIRED_STATE", "reasoning"
            elif is_plan(node) or any("前置结果" in r for r in state["blockers"]):
                kind, actor = "WAIT_FOR_DEPENDENCY", "deterministic"
        actions.append({"kind": kind, "target": node["id"], "executor": actor, "reason": reason,
                        "batch_ids": feedback["batch_ids"],
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
            error("删除要求应选择一个覆盖率方案节点" if workstream == "VCOV" else "删除要求应选择一个代码工作包")
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
