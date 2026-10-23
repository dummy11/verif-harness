"""Immutable owner-approved subjects and read-only, approval-based comparisons.

Snapshots are evidence for display, never authority to grant an approval. Legacy
subjects are recovered only from artifacts tied to that exact review receipt.
"""
from __future__ import annotations

import json
import hashlib
from . import code_workflow as code

SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_subject_snapshots (
 review_id TEXT PRIMARY KEY, node_id TEXT NOT NULL,
 subject_json TEXT NOT NULL, created_at TEXT NOT NULL
);
"""

FIELDS = (
    "title", "statement", "purpose", "scope", "work_content",
    "implementation_approach", "validation_methods", "deliverables",
    "acceptance_criteria", "quality_checks", "source_refs", "inputs",
    "input_files", "output_paths", "capabilities", "progress_measures", "coverage_scope",
    "coverage_implementation_config", "coverage_collection_config", "coverage_item_ids",
    "regression_config", "authoring_contract", "required",
)


def definition(node):
    # Preserve extension fields too: new contracts must not silently disappear
    # from the approval comparison. Node identity is navigation, not content.
    return {**{field: node.get(field) for field in FIELDS},
            **{key: value for key, value in node.items() if key not in {"id", "parent_id"}}}


def files(items):
    return {item["path"]: item["sha256"] for item in items}


def dependencies(items):
    # Availability and display titles are not dependency versions.
    return {item["id"]: item.get("current") for item in items}


def validation_fields(validation):
    value = code.validation_subject(validation)
    return {"checks": value.get("checks", []),
            "evidence_files": files(value.get("files", [])),
            "code_files": files(value.get("code_files", [])),
            "validation_details": {key: item for key, item in value.items() if key not in {
                "checks", "files", "code_files", "input_signature", "node_id", "revision"}}}


def current(store, db, plan, node):
    subject = {"definition": definition(node),
               "workflow_context": {key: plan.get(key) for key in ("objective", "decisions")}}
    if code.supported(plan["workstream"]):
        signature, snapshot = code.identity(store, db, plan, node)
        subject.update(sources=files(snapshot["sources"]),
                       dependencies=dependencies(snapshot["dependencies"]),
                       project_inputs=snapshot["project_inputs"], questions=snapshot["questions"])
        if code.is_delivery(node):
            validation = code.validation_current(store, db, plan, node, signature)
            subject.update(validation_fields(validation) if validation else
                           {"checks": [], "evidence_files": {}, "code_files": {}, "validation_details": {}})
            subject["code_files"] = files(snapshot.get("outputs", []))
            if validation:
                paths = [item["path"] for item in code.validation_evidence_files(validation)]
                subject["evidence_files"] = files(code.file_snapshot(store, paths))
        for key in ("execution_binding", "coverage_exclusion"):
            if key in snapshot:
                subject[key] = snapshot[key]
    elif node["role"] == "document-deliverable":
        from .store import HarnessError
        key = store._vdoc_document_key(plan, node)
        document = db.execute("SELECT * FROM documents WHERE id=?", (f"document:vdoc:{key}",)).fetchone()
        if document is None:
            raise HarnessError("当前文档尚未登记，无法核对正文变化")
        path = store.root / document["path"]
        if (path.is_symlink() or store.root not in path.resolve().parents
                or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024):
            raise HarnessError("当前正文无法安全读取，请重新核对文档")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != document["digest"]:
            raise HarnessError("正文版本已变化，请同步后重新读取工作节点")
        try:
            subject["document_body"] = raw.decode("utf-8")
        except UnicodeError as exc:
            raise HarnessError("验证文档必须为 UTF-8 文本") from exc
        subject["document_digest"] = document["digest"]
    return subject


def record(store, db, plan, node, review_id, timestamp):
    from .store import HarnessError
    subject = current(store, db, plan, node)
    if code.supported(plan["workstream"]):
        approved = db.execute("SELECT definition_digest FROM node_plan_reviews WHERE id=?", (review_id,)).fetchone()
        if code.review_state(store, node["id"], plan, node, db)["definition_digest"] != approved[0]:
            raise HarnessError("保存审批期间内容或证据版本已变化，请重新核对")
    db.execute("INSERT INTO approval_subject_snapshots VALUES(?,?,?,?)",
               (review_id, node["id"], json.dumps(subject, ensure_ascii=False), timestamp))


def same_work(node, other):
    if node.get("role") != other.get("role"):
        return False
    if node.get("document_key") != other.get("document_key"):
        return False
    for key in ("implementation_key", "key"):
        if node.get(key):
            return node[key] == other.get(key)
    return node["id"] == other.get("id")


def legacy(store, db, plan, node, review):
    """Never substitute today's bytes for an unavailable historical subject."""
    if code.supported(plan["workstream"]):
        artifact_id = code.ids(node["implementation_key"], plan["workstream"])[
            1 if code.is_delivery(node) else 0]
        for row in db.execute("SELECT payload_json FROM code_artifact_versions WHERE artifact_id=? ORDER BY version DESC", (artifact_id,)):
            payload = json.loads(row[0])
            if (payload.get("review") or {}).get("id") != review["id"]:
                continue
            subject = {"definition": definition(payload["definition"])}
            if code.is_plan(node):
                subject.update(sources=files(payload.get("sources", [])),
                               dependencies=dependencies(payload.get("dependencies", [])))
            else:
                subject.update(validation_fields(payload["validation"]))
                head = (payload.get("plan") or {}).get("current")
                subject["dependencies"] = {code.ids(node["implementation_key"], plan["workstream"])[0]: head}
                if head:
                    parent = db.execute("SELECT payload_json FROM code_artifact_versions WHERE artifact_id=? AND version=? AND signature=?",
                                        (code.ids(node["implementation_key"], plan["workstream"])[0], head["version"], head["signature"])).fetchone()
                    if parent:
                        subject["sources"] = files(json.loads(parent[0]).get("sources", []))
            return subject
    else:
        for row in db.execute("SELECT payload_json FROM vdoc_artifact_versions ORDER BY rowid DESC"):
            payload = json.loads(row[0])
            for item in payload.get("plans", []) + payload.get("deliveries", []):
                if (item.get("review") or {}).get("id") != review["id"]:
                    continue
                old = item.get("definition")
                if old is None:
                    row_node = db.execute("SELECT data_json FROM nodes WHERE id=?", (review["node_id"],)).fetchone()
                    candidate = json.loads(row_node[0]) if row_node else None
                    if candidate and store._node_plan_digest({**plan, "revision": review["revision"]}, candidate) == review["definition_digest"]:
                        old = candidate
                subject = {"definition": definition(old)} if old else {}
                if "body" in payload:
                    subject.update(document_body=payload["body"], document_digest=payload["document_digest"])
                return subject
    return None


def compare(store, db, plan, node, expected, document_digest=None):
    from .store import HarnessError
    if code.supported(plan["workstream"]):
        state = code.review_state(store, node["id"], plan, node, db)
        actual, revision = state["definition_digest"], state["revision"]
    else:
        actual, revision = store._node_plan_digest(plan, node), plan["revision"]
        state = None
    if actual != expected:
        raise HarnessError("节点内容或证据版本已变化，请刷新当前工作节点后重新对照")
    subject = current(store, db, plan, node)
    if document_digest is not None and subject.get("document_digest") != document_digest:
        raise HarnessError("正文版本已变化，请刷新当前工作节点后重新对照")
    candidates = {node["id"]}
    for row in db.execute("SELECT id,data_json FROM nodes WHERE type='desired-state' AND id LIKE ?",
                          (f"workstream:{plan['workstream']}:r%:desired:%",)):
        if same_work(node, json.loads(row["data_json"])):
            candidates.add(row["id"])
    table = "document_delivery_reviews" if node["role"] == "document-deliverable" else "node_plan_reviews"
    review = next((dict(row) for row in db.execute(
        f"SELECT * FROM {table} WHERE workstream=? AND verdict='APPROVE' ORDER BY rowid DESC",
        (plan["workstream"],)) if row["node_id"] in candidates), None)
    result = {"schema": "NodeApprovalChanges/2", "node_id": node["id"],
              "workstream": plan["workstream"], "revision": revision, "definition_digest": actual,
              "document_digest": subject.get("document_digest"),
              "previous_node_id": review["node_id"] if review else None,
              "previous_revision": review["revision"] if review else None,
              "previous_review": review, "baseline_status": "FIRST_APPROVAL", "changes": [],
              "unavailable_fields": [], "blockers": state["blockers"] if state else []}
    result["approval_notice"] = ""
    if review and review["node_id"] != node["id"]:
        result["approval_notice"] = "当前为新的工作节点版本，历史批准仅用于内容对照，不代表本版已获批准。"
    elif review and state and not state["completed"] and state["reviews"]:
        result["approval_notice"] = "请同时核对审批意见和当前阻塞；后续审批意见处理完成后仍需重新批准。"
    result["context_updates"] = []
    if plan["workstream"] == "VCASE":
        live = files(code.file_snapshot(store, node.get("input_files", [])))
        result["context_updates"] = sorted(path for path, value in subject.get("sources", {}).items()
                                           if value != live.get(path))
    if review is None:
        return result
    row = db.execute("SELECT subject_json FROM approval_subject_snapshots WHERE review_id=?", (review["id"],)).fetchone()
    before = json.loads(row[0]) if row else legacy(store, db, plan, node, review)
    if before is None:
        result.update(baseline_status="UNAVAILABLE", unavailable_fields=list(subject))
        return result
    result["unavailable_fields"] = sorted(set(subject) - set(before))
    result["baseline_status"] = "PARTIAL" if result["unavailable_fields"] else "COMPLETE"
    for key in sorted(set(before) & set(subject)):
        if key == "definition":
            result["changes"].extend({"field": field, "before": before[key].get(field), "after": subject[key].get(field)}
                                     for field in sorted(set(before[key]) | set(subject[key]))
                                     if before[key].get(field) != subject[key].get(field))
        elif key != "document_digest" and before[key] != subject[key]:
            result["changes"].append({"field": key, "before": before[key], "after": subject[key]})
    return result
