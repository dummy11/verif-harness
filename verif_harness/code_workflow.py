"""VENV code plans, validated deliveries, and derived, version-bound capabilities.

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

ROLES = {"code-plan", "code-deliverable"}
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
    return plan.get("planning_context", {}).get("code_model") == 2


def protected(identifier):
    return identifier.startswith(("art.code_plan:", "art.code:", "cap.venv:"))


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


def ids(key):
    return "art.code_plan:" + key, "art.code:" + key, "cap.venv:" + key


def error(message):
    from .store import HarnessError
    raise HarnessError(message)


def selected(store, node_id, connection=None):
    plan = store._read_workstream(connection, "VENV") if connection else store.workstream("VENV")
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
    if node["role"] == "code-deliverable":
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
    return value


def review_state(store, node_id, plan=None, node=None, connection=None):
    if connection is None:
        with store.read_connect() as db:
            return review_state(store, node_id, plan, node, db)
    if plan is None or node is None:
        plan, node = selected(store, node_id, connection)
    signature, snapshot = identity(store, connection, plan, node)
    validation = validation_current(store, connection, plan, node, signature) if node["role"] == "code-deliverable" else None
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
    expected_dependencies = set(node['inputs']) if node['role'] == 'code-plan' else {ids(node['implementation_key'])[0]}
    if {v['id'] for v in snapshot['dependencies']} != expected_dependencies:
        reasons.append("前置结果与批准范围不一致，请重新登记方案依赖")
    reasons.extend("前置结果尚未验收或已经变化：" + str(v["title"] or '前置交付') for v in snapshot["dependencies"] if v["status"] != "VALID" or not v["current"])
    if any(v["sha256"] is None for v in snapshot["sources"]):
        reasons.append("方案输入文件缺失")
    if node["role"] == "code-deliverable" and not (validation and validation["current"] and validation["ready"]):
        reasons.append("Agent 尚未完成当前代码版本的验证，或验证证据已经变化")
    complete = bool(completion and not reasons)
    return {"node_id": node_id, "workstream": "VENV", "revision": plan["revision"],
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


def design(store, source, objective=None, decisions=None, restart=None):
    from .store import now, Validity
    from .evidence_policy import EVIDENCE_POLICIES
    store.ensure_dashboard_schema()
    nodes = []
    if source:
        path = store.root / local_path(store, source)
        try:
            proposal = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            error(f"无法读取代码实现方案：{exc}")
        if not isinstance(proposal, dict) or proposal.get("schema") != "DesiredStateProposal/1" or proposal.get("workstream") != "VENV":
            error("代码方案必须使用 VENV 的 DesiredStateProposal/1")
        nodes = proposal.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            error("代码实现方案必须包含工作包")
    normalized = []
    known_keys = set()
    known_outputs = set()
    for raw in nodes:
        if not isinstance(raw, dict) or raw.get("role") != "code-plan":
            error("VENV 方案只包含 code-plan；批准后由系统建立对应 code-deliverable")
        key = raw.get("implementation_key", "")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*:[a-z0-9][a-z0-9._:-]*", key) or key in known_keys:
            error("implementation_key 必须是唯一、稳定的工作包标识")
        known_keys.add(key)
        item = {"implementation_key": key, "key": raw.get("key") or key.replace(":", "-"), "role": "code-plan"}
        if not isinstance(item['key'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', item['key']):
            error("代码方案 key 只能使用小写字母、数字、点、短横线和下划线")
        for field in ("title", "statement"):
            if not isinstance(raw.get(field), str) or not raw[field].strip():
                error(f"代码方案缺少 {field}")
            item[field] = raw[field].strip()
        for field in ("scope", "work_content", "implementation_approach", "validation_methods", "deliverables", "acceptance_criteria", "source_refs", "inputs", "output_paths", "capabilities"):
            item[field] = strings(raw, field)
        if not all(v.startswith(("cap.doc:", "cap.venv:")) for v in item["inputs"]):
            error("VENV 上游必须使用 cap.doc 或 cap.venv，不能依赖工作节点或未验收产物")
        if not any(v.startswith("cap.doc:") for v in item["inputs"]):
            error("代码方案必须说明所依据的已验收文档 cap.doc")
        if ids(key)[2] in item["inputs"]:
            error("工作包不能依赖自己的交付能力")
        item["output_paths"] = store._normalized_write_scopes(item["output_paths"])
        for path in item["output_paths"]:
            if any(store._scopes_overlap(path, old) for old in known_outputs):
                error("工作包的输出范围不能重叠")
            known_outputs.add(path)
        unsupported = set(item["capabilities"]) - set(EVIDENCE_POLICIES["VENV"])
        if unsupported:
            error("未知的 VENV 验证要求：" + ", ".join(sorted(unsupported)))
        item["input_files"] = [store._project_or_declared_input_path(v) for v in strings(raw, "input_files")]
        if any(not (Path(v) if Path(v).is_absolute() else store.root / v).is_file() for v in item["input_files"]):
            error("input_files 必须逐项引用实际输入文件，目录仅用于界面展示")
        item.update(required=raw.get("required", True), purpose=item["statement"],
                    suggested_mode="plan", definition_origin="project-proposal",
                    definition_status="REVIEW_CANDIDATE", quality_checks=item["validation_methods"],
                    progress_measures=[], evidence_claim="code-validation", parent_id=None,
                    role_description="当前 DUT 工作包的代码实现方案")
        if not isinstance(item["required"], bool):
            error("required 必须是布尔值")
        normalized.append(item)
    if len({n["key"] for n in normalized}) != len(normalized):
        error("代码方案 key 不能重复")
    by_cap = {ids(n["implementation_key"])[2]: n for n in normalized}
    def visit(cap, parents):
        if cap in parents:
            error("代码工作包存在循环依赖")
        for target in by_cap.get(cap, {}).get("inputs", []):
            if target.startswith("cap.venv:"):
                if target not in by_cap:
                    error("当前方案没有提供前置工作包：" + target)
                visit(target, parents | {cap})
    for cap in by_cap:
        visit(cap, set())
    timestamp = now()
    context = {**store.planning_context("VENV"), "code_model": 2}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT revision,desired_json FROM workstreams WHERE name='VENV'").fetchone()
        revision = old["revision"] + 1 if old else 1
        if restart and (not old or restart["revision"] != old["revision"]):
            error("VENV 版本已变化，请刷新后重新确认")
        previous = json.loads(old["desired_json"]) if old else []
        db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", ("event:" + uuid.uuid4().hex, "venv-replan", "workstream:VENV", str(revision), encoded({"previous_nodes": previous, "restart": restart, "previous_edges": [dict(r) for r in db.execute("SELECT e.* FROM edges e JOIN nodes n ON n.id=e.target WHERE n.workstream='VENV'")]}), timestamp))
        db.execute("UPDATE nodes SET workstream=NULL,status='STALE',updated_at=? WHERE workstream='VENV' AND type='desired-state'", (timestamp,))
        for old_node in previous:
            if old_node.get("key") not in EVIDENCE_POLICIES["VENV"]:
                continue
            cap = "cap.venv:" + old_node["key"]
            store.upsert_node(db, cap, "capability", "代码交付需重新验证和验收", Validity.UNKNOWN, data={"derived": True})
            for row in db.execute("SELECT * FROM edges WHERE target=? AND relation='DEPENDS_ON'", (old_node["id"],)).fetchall():
                db.execute("DELETE FROM edges WHERE source=? AND target=? AND relation='DEPENDS_ON'", (row["source"], row["target"]))
                edge(db, row["source"], cap, timestamp)
        db.execute("UPDATE activities SET status='CANCELLED',ended_at=?,updated_at=? WHERE workstream='VENV' AND status IN ('PENDING','RUNNING','WAITING_FOR_HUMAN','WAITING_FOR_PARENT')", (timestamp, timestamp))
        db.execute("UPDATE agent_assignments SET status='SUPERSEDED',ended_at=?,updated_at=? WHERE workstream='VENV' AND status='ACTIVE'", (timestamp, timestamp))
        db.execute("UPDATE review_feedback_items SET status='SUPERSEDED',updated_at=?,resolved_at=? WHERE workstream='VENV' AND status IN ('DRAFT','PENDING','WAITING_FOR_HUMAN')", (timestamp, timestamp))
        db.execute('DELETE FROM code_watched_files')
        for item in normalized:
            item["id"] = f"workstream:VENV:r{revision}:desired:{item['key']}"
            store.upsert_node(db, item["id"], "desired-state", item["title"], Validity.REVIEW_REQUIRED, "VENV", item)
            for target in item["inputs"]:
                if not db.execute("SELECT 1 FROM nodes WHERE id=?", (target,)).fetchone():
                    store.upsert_node(db, target, "capability", "前置交付尚未验收", Validity.UNKNOWN, data={"derived": True})
                edge(db, item["id"], target, timestamp)
            for path in item["input_files"]:
                db.execute("INSERT OR IGNORE INTO code_watched_files VALUES(?)", (path,))
        db.execute("INSERT INTO workstreams VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET lifecycle=excluded.lifecycle,revision=excluded.revision,objective=excluded.objective,desired_json=excluded.desired_json,exit_json=excluded.exit_json,decisions_json=excluded.decisions_json,context_json=excluded.context_json,updated_at=excluded.updated_at",
                   ("VENV", "REVIEW", revision, objective or "实现并验证当前 DUT 的验证环境", encoded(normalized), encoded(["必需工作包的代码交付均通过验证并由负责人验收"]), encoded(decisions or []), encoded(context), timestamp))
        # Default downstream edges must never fall back to old WorkNodes.
        store._reconcile_default_dependencies(db)
    refresh(store)
    store.write_workstream_projection("VENV")
    return {**store.workstream("VENV"), "auto_closure": store.evaluate_closure("VENV")}


def edge(db, source, target, timestamp, relation="DEPENDS_ON"):
    db.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?,?,?,?,?)", (source, target, relation, "code-workflow", 1.0, "{}", timestamp))


def create_delivery(store, db, plan, node, timestamp):
    from .store import Validity
    if any(n.get("parent_id") == node["id"] for n in plan["desired_state"]):
        return
    value = {**node, "id": node["id"] + ":delivery", "key": node["key"] + "-delivery",
             "role": "code-deliverable", "title": node["title"] + " · 代码交付验收",
             "parent_id": node["id"], "parent_key": node["key"], "suggested_mode": "implement",
             "role_description": "Agent 先完成实现与验证，再由负责人验收当前代码和证据"}
    plan["desired_state"].append(value)
    store.upsert_node(db, value["id"], "desired-state", value["title"], Validity.UNKNOWN, "VENV", value)
    edge(db, value["id"], node["id"], timestamp, "CHILD_OF")
    edge(db, value["id"], ids(node["implementation_key"])[0], timestamp)
    db.execute("UPDATE workstreams SET desired_json=?,updated_at=? WHERE name='VENV'", (encoded(plan["desired_state"]), timestamp))
    for path in value["output_paths"]:
        db.execute("INSERT OR IGNORE INTO code_watched_files VALUES(?)", (path,))


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
            db.execute("INSERT INTO node_plan_reviews VALUES(?,?,?,?,?,?,?,?,?)", (review_id, node_id, "VENV", plan["revision"], expected, "APPROVE", reviewer.strip(), reason.strip(), timestamp))
            if node["role"] == "code-plan":
                create_delivery(store, db, plan, node, timestamp)
        else:
            if state["feedback"]["processing_count"]:
                error("上一批意见仍在等待 Agent 处理")
            if not reason.strip():
                error("请填写审批内容")
            normalized = store._normalize_review_change_items(verdict, changes, default_target=node["title"], default_instruction=reason)
            db.execute("INSERT INTO node_plan_section_reviews VALUES(?,?,?,?,?,?,?,?,?,?)", (review_id, node_id, "VENV", plan["revision"], expected, "writing-plan", verdict.upper(), reviewer.strip(), reason.strip(), timestamp))
            store._store_review_change_items(db, review_id, normalized)
            store._store_review_feedback_items(db, review_id, node_id, plan["revision"], expected, "", reviewer, normalized, timestamp, workstream="VENV")
        store._record_review_submitted_event(db, review_id, node_id, verdict, reviewer, changes or [], timestamp, agent_follow_up="NONE" if verdict == "approve" else "AWAITING_FEEDBACK_SUBMISSION")
    refresh(store)
    return {"review_id": review_id, "node_id": node_id, "verdict": verdict.upper(),
            "plan_review": review_state(store, node_id), "auto_closure": store.evaluate_closure("VENV")}


def validate(store, node_id, report_path):
    from .store import now, PROJECT_AGENT_ACTOR
    from .evidence_contracts import validate_workstream_evidence, EvidenceContractError
    refresh(store)
    path = store.root / local_path(store, report_path)
    try:
        raw_report = path.read_bytes()
        report = json.loads(raw_report)
    except (OSError, ValueError) as exc:
        error(f"无法读取验证报告：{exc}")
    plan, node = selected(store, node_id)
    if node["role"] != "code-deliverable":
        error("只有代码交付节点可以登记验证，方案节点不产生正式代码")
    with store.read_connect() as db:
        signature, snapshot = identity(store, db, plan, node)
        reasons = []
    if not isinstance(report, dict) or report.get("schema") != "CodeValidation/1" or report.get("node_id") != node_id or report.get("revision") != plan["revision"] or report.get("input_signature") != signature:
        error("验证报告必须绑定当前项目节点、revision 和 input_signature")
    if {d['id'] for d in snapshot['dependencies']} != {ids(node['implementation_key'])[0]} or any(d["status"] != "VALID" or not d['current'] for d in snapshot["dependencies"]):
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
    code_sources = set()
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
        try:
            result = validate_workstream_evidence(evidence_path, "VENV", check["claim"])
        except EvidenceContractError as exc:
            error(str(exc))
        result["artifacts"] = store._verify_evidence_artifacts(result["artifacts"])
        store._apply_revision_check(result)
        result['ready'] = not result['blockers']
        facts_by_claim.setdefault(check['claim'], []).append(result['facts'])
        code_sources.update(a['path'] for a in result['artifacts'] if a['kind'] in {'source', 'configuration'})
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
    if set(node['output_paths']) - code_sources:
        error("专用验证报告必须直接引用全部当前交付代码或配置文件，不能只在摘要中声明已检查")
    builds = facts_by_claim.get('build-ready', [])
    for smoke in facts_by_claim.get('environment-smoke-evidence', []):
        if not builds or any(smoke.get('environment_digest') != b.get('environment_digest') for b in builds):
            reasons.append("集成工作包的 smoke 必须与本次构建使用同一版本的验证环境")
    receipt = {**report, "files": file_snapshot(store, files, required=True), "ready": not reasons,
               "blockers": reasons, "checks": checks}
    if {v['path']: v['sha256'] for v in receipt['files']} != expected_files:
        error("检查期间代码或证据发生变化，请重新验证")
    identifier, timestamp = "code-validation:" + uuid.uuid4().hex[:12], now()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        latest_plan, latest_node = selected(store, node_id, db)
        if identity(store, db, latest_plan, latest_node)[0] != signature or receipt["files"] != file_snapshot(store, files, required=True):
            error("登记期间代码或输入已变化，请重新验证")
        db.execute("INSERT INTO code_validations VALUES(?,?,?,?,?,?)", (identifier, node_id, plan["revision"], signature, encoded(receipt), timestamp))
        # Watch only active inputs and latest receipts, not every historical log.
        watched = set()
        for item in latest_plan['desired_state']:
            watched.update(item['input_files'])
            watched.update(item['output_paths'])
            previous = db.execute('SELECT payload_json FROM code_validations WHERE node_id=? ORDER BY rowid DESC LIMIT 1', (item['id'],)).fetchone()
            if previous:
                watched.update(v['path'] for v in json.loads(previous[0])['files'])
        db.execute('DELETE FROM code_watched_files')
        db.executemany('INSERT INTO code_watched_files VALUES(?)', [(p,) for p in sorted(watched)])
    refresh(store)
    return {"id": identifier, "ready": receipt["ready"], "blockers": reasons,
            "node_id": node_id, "auto_closure": store.evaluate_closure("VENV")}


def refresh(store, plans=None):
    from .store import now, Validity
    from . import vdoc_artifacts
    store.ensure_dashboard_schema()
    token = refresh_token(store)
    if getattr(store, "_code_checkpoint", None) == token:
        return
    plans = store.workstreams() if plans is None else plans
    plan = next((p for p in plans if p["workstream"] == "VENV" and modern(p)), None)
    if not plan:
        store._code_checkpoint = token
        return
    vdoc_artifacts.reconcile(store, plans)
    token = refresh_token(store)
    if getattr(store, "_code_checkpoint", None) == token:
        return
    timestamp = now()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        plan = store._read_workstream(db, "VENV")
        old = {r["id"]: dict(r) for r in db.execute("SELECT * FROM nodes WHERE id LIKE 'art.code%' OR id LIKE 'cap.venv:%'")}
        published = set()
        states = {}
        def publish(identifier, kind, title, payload, ready):
            current = None
            if ready:
                signature = digest(payload)
                row = db.execute("SELECT version FROM code_artifact_versions WHERE artifact_id=? AND signature=?", (identifier, signature)).fetchone()
                version = row[0] if row else db.execute("SELECT COALESCE(MAX(version),0)+1 FROM code_artifact_versions WHERE artifact_id=?", (identifier,)).fetchone()[0]
                if row is None:
                    db.execute("INSERT INTO code_artifact_versions VALUES(?,?,?,?,?)", (identifier, version, signature, encoded(payload), timestamp))
                current = {"version": version, "signature": signature}
            data = {"derived": True, "current": current, "implementation_key": payload.get("implementation_key")}
            status = "VALID" if ready else "REVALIDATION_REQUIRED"
            previous = db.execute("SELECT status,data_json FROM nodes WHERE id=?", (identifier,)).fetchone()
            if previous is None or previous["status"] != status or json.loads(previous["data_json"]) != data:
                store.upsert_node(db, identifier, kind, title, Validity(status), data=data)
            published.add(identifier)
        # Topological order follows accepted package CAP dependencies, not node kinds.
        packages = {n["implementation_key"]: n for n in plan["desired_state"] if n["role"] == "code-plan"}
        remaining = dict(packages)
        done = set()
        while remaining:
            eligible = [k for k, n in remaining.items() if all(not v.startswith("cap.venv:") or v.removeprefix("cap.venv:") in done for v in n["inputs"])]
            if not eligible:
                eligible = list(remaining)  # Unexpected stale graph is handled as blocked.
            for key in eligible:
                node = remaining.pop(key)
                p_id, a_id, c_id = ids(key)
                state = review_state(store, node["id"], plan, node, db)
                states[node['id']] = state
                payload = {"implementation_key": key, "definition": node, "revision": plan["revision"],
                           "review": state["current_completion"], "signature": state["definition_digest"],
                           "dependencies": state['dependencies'], "sources": state['sources']}
                publish(p_id, "artifact", node["title"] + " · 批准方案", payload, state["completed"])
                update_status(db, node["id"], "VALID" if state["completed"] else "REVIEW_REQUIRED", timestamp)
                edge(db, p_id, node["id"], timestamp)
                delivery = next((n for n in plan["desired_state"] if n.get("parent_id") == node["id"]), None)
                ready = False
                if delivery:
                    ds = review_state(store, delivery["id"], plan, delivery, db)
                    states[delivery['id']] = ds
                    ready = ds["completed"] and state["completed"]
                    payload = {"implementation_key": key, "definition": delivery, "plan": current_head(db, p_id),
                               "review": ds["current_completion"], "validation": ds["validation"]}
                    update_status(db, delivery["id"], "VALID" if ready else "REVIEW_REQUIRED", timestamp)
                    edge(db, a_id, delivery["id"], timestamp)
                publish(a_id, "artifact", node["title"] + " · 验收交付", payload, ready)
                publish(c_id, "capability", node["title"] + " · 可供下游使用", {"implementation_key": key, "delivery": current_head(db, a_id)}, ready)
                edge(db, c_id, a_id, timestamp)
                done.add(key)
        from .evidence_policy import EVIDENCE_POLICIES
        for claim in EVIDENCE_POLICIES["VENV"]:
            providers = [n for n in packages.values() if n["required"] and claim in n["capabilities"]]
            heads = [current_head(db, ids(n["implementation_key"])[2]) for n in providers]
            ready = bool(heads) and all(h and h["status"] == "VALID" for h in heads)
            cap_id = "cap.venv:" + claim
            publish(cap_id, "capability", "验证环境 · " + claim, {"providers": heads}, ready)
            for head in heads:
                edge(db, cap_id, head["id"], timestamp)
        for identifier in old.keys() - published:
            update_status(db, identifier, "REVALIDATION_REQUIRED", timestamp)
        # Any withdrawn CAP invalidates already-completed downstream consumers.
        revoked = [k for k, v in old.items() if v["status"] == "VALID" and db.execute("SELECT status FROM nodes WHERE id=?", (k,)).fetchone()[0] != "VALID"]
        for identifier in revoked:
            for target in store._impact_targets(db, identifier):
                db.execute("UPDATE nodes SET status='REVALIDATION_REQUIRED',updated_at=? WHERE id=? AND status='VALID'", (timestamp, target))
        lifecycle = closure(store, plan, False, states)['lifecycle']
        db.execute("UPDATE workstreams SET lifecycle=?,updated_at=? WHERE name='VENV' AND lifecycle!=?",
                   (lifecycle, timestamp, lifecycle))
        for loaded in plans:
            if loaded['workstream'] == 'VENV' and loaded['revision'] == plan['revision']:
                loaded['lifecycle'] = lifecycle
        counter = db.execute('SELECT version FROM agent_service_changes WHERE id=1').fetchone()[0]
    store._code_checkpoint = (counter, token[1])


def current_head(db, identifier):
    row = db.execute("SELECT status,data_json FROM nodes WHERE id=?", (identifier,)).fetchone()
    return {"id": identifier, "status": row["status"], **json.loads(row["data_json"])} if row else None


def update_status(db, identifier, status, timestamp):
    db.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=? AND status!=?", (status, timestamp, identifier, status))


def closure(store, plan, persist, states=None):
    from .store import now
    actions = []
    nodes = plan["desired_state"]
    states = states if states is not None else {
        n['id']: review_state(store, n['id'], plan, n) for n in nodes}
    with store.read_connect() as db:
        pending_changes = [dict(r) for r in db.execute(
            "SELECT id,target,reason FROM human_actions WHERE status='OPEN' AND action='REQUEST_CHANGE' "
            "AND (target='VENV' OR target LIKE 'workstream:VENV:%')")]
    for change in pending_changes:
        actions.append({"kind": "APPLY_WORKFLOW_CHANGE", "target": change['target'],
                        "executor": "reasoning", "reason": change['reason'], "change_id": change['id']})
    if not nodes:
        actions.append({"kind": "REFINE_DESIRED_STATE", "target": "workstream:VENV", "executor": "reasoning", "reason": "请 Agent 根据已验收文档形成当前 DUT 的代码实现方案"})
    for node in nodes:
        if not node["required"]:
            continue
        state = states[node['id']]
        feedback = state["feedback"]
        if feedback["draft_count"]:
            kind, actor, reason = "SUBMIT_REVIEW_FEEDBACK", "human", "请提交当前审批意见给 Agent"
        elif feedback["processing_count"]:
            kind, actor, reason = "APPLY_REVIEW_FEEDBACK", "reasoning", "请逐条处理已提交的审批意见并登记结果"
        elif state["completed"]:
            continue
        elif state["can_approve"]:
            kind, actor, reason = "HUMAN_REVIEW", "human", "等待负责人" + ("审批代码实现方案" if node["role"] == "code-plan" else "验收代码交付和验证证据")
        else:
            kind, actor, reason = "IMPLEMENT_AND_VALIDATE", "reasoning", "；".join(state["blockers"])
            if node["role"] == "code-plan" or any("前置结果" in r for r in state["blockers"]):
                kind, actor = "WAIT_FOR_DEPENDENCY", "deterministic"
        actions.append({"kind": kind, "target": node["id"], "executor": actor, "reason": reason,
                        "batch_ids": feedback["batch_ids"]})
    for action in actions:
        action.update(priority=1 if action["executor"] == "human" else 3, suggested_mode="plan" if action["target"] == "workstream:VENV" else "code")
        action["id"] = "action:" + digest(action)[:12]
    approved = any(n["role"] == "code-plan" and states[n['id']]["completed"] for n in nodes)
    lifecycle = "SATISFIED" if not actions and nodes else "ACTIVE" if approved else "REVIEW"
    if lifecycle == 'SATISFIED' and plan['lifecycle'] == 'BASELINED':
        lifecycle = 'BASELINED'
    if persist:
        with store.connect() as db:
            known = {r[0] for r in db.execute("SELECT id FROM actions WHERE workstream='VENV' AND status='OPEN'")}
            if known != {a["id"] for a in actions}:
                db.execute("DELETE FROM actions WHERE workstream='VENV' AND status='OPEN'")
                for a in actions:
                    db.execute("INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?,?)", (a["id"], "VENV", a["kind"], a["target"], a["priority"], "OPEN", a["executor"], a["suggested_mode"], a["reason"], now()))
            db.execute("UPDATE workstreams SET lifecycle=?,updated_at=? WHERE name='VENV' AND lifecycle!=?", (lifecycle, now(), lifecycle))
        store.write_workstream_projection("VENV")
    return {"workstream": "VENV", "ready": not actions and bool(nodes), "lifecycle": lifecycle, "actions": actions}


def artifacts(store):
    refresh(store)
    with store.read_connect() as db:
        heads = [{**dict(r), "data": json.loads(r["data_json"])} for r in db.execute("SELECT * FROM nodes WHERE id LIKE 'art.code%' OR id LIKE 'cap.venv:%'")]
        versions = [{**dict(r), "payload": json.loads(r["payload_json"])} for r in db.execute("SELECT * FROM code_artifact_versions ORDER BY artifact_id,version")]
    return {"heads": heads, "versions": versions}


def request_change(store, body):
    from .store import now
    reviewer, reason = str(body.get("reviewer", "")).strip(), str(body.get("reason", "")).strip()
    kind = body.get("kind")
    plan = store.workstream("VENV")
    if not reviewer or not reason or body.get("revision") != plan["revision"]:
        error("必须填写操作人和具体要求，且工作流版本不能发生变化")
    if kind == "restart":
        if body.get("confirm") is not True:
            error("重新启动工作流需要再次确认")
        return design(store, None, restart={"reviewer": reviewer, "reason": reason, "revision": plan["revision"]})
    if kind not in {"add", "remove"}:
        error("未知的工作流变更操作")
    target = "VENV"
    if kind == "remove":
        target = str(body.get("node", ""))
        _, node = selected(store, target)
        if node["role"] != "code-plan":
            error("删除要求应选择一个代码工作包")
    identifier, timestamp = 'human:' + uuid.uuid4().hex[:12], now()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = store._read_workstream(db, 'VENV')
        if current['revision'] != plan['revision']:
            error("工作流版本已变化，请刷新后重新提交变更要求")
        db.execute('INSERT INTO human_actions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   (identifier, target, 'workstream' if target == 'VENV' else 'node',
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
