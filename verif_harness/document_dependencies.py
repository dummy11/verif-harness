"""Repair legacy document-source edges without changing approved definitions.

Preview is read-only. Apply rechecks under the database writer lock, preserves
every review, and records removed edges and discharged edit findings in an event.
Only exact, previously accepted VDOC subjects can regain their stored status;
the ordinary reconciler rechecks downstream code, evidence and capabilities.
"""

from collections import defaultdict, deque
import hashlib
import json
import uuid

from .document_authoring import authoring_source_is_dependency
from . import vdoc_artifacts


def obsolete_edges(connection):
    contracts = {}
    for row in connection.execute("SELECT id,data_json FROM nodes WHERE workstream='VDOC'"):
        contract = json.loads(row["data_json"]).get("authoring_contract")
        if contract:
            contracts[row["id"]] = (contract, {
                "file:" + source["path"]: source for source in contract.get("source_snapshot", [])
            })
    result = []
    for row in connection.execute("SELECT * FROM edges WHERE origin='authoring-source' AND relation='AFFECTS'"):
        entry = contracts.get(row["target"])
        if entry is None:
            continue
        contract, sources = entry
        source = sources.get(row["source"])
        if source and not authoring_source_is_dependency(contract, source):
            result.append(dict(row))
    return result


def _graph(edges):
    graph = defaultdict(list)
    for edge in edges:
        source, target = edge["source"], edge["target"]
        if edge["relation"] == "DEPENDS_ON":
            source, target = target, source
        graph[source].append(target)
    return graph


def _reachable(graph, source):
    queue, seen = deque([source]), set()
    while queue:
        node = queue.popleft()
        if node not in seen:
            seen.add(node)
            queue.extend(graph.get(node, []))
    return seen


def _restorable(store, connection, plan, candidates, resolved, edges):
    """Prove the original accepted subject and all still-causal inputs match."""
    desired = {item["id"]: item for item in plan["desired_state"]}
    statuses = dict(connection.execute("SELECT id,status FROM nodes"))
    blocked = set()
    for table, field, condition in (
        ("agent_questions", "target", "status='OPEN'"),
        ("human_actions", "target", "status='OPEN'"),
        ("review_feedback_items", "node_id", "status IN ('DRAFT','PENDING','WAITING_FOR_HUMAN')"),
    ):
        blocked.update(row[0] for row in connection.execute(f"SELECT {field} FROM {table} WHERE {condition}"))
    blocked.update(row["subject"] for row in connection.execute("SELECT id,subject FROM findings WHERE status='OPEN'")
                   if row["id"] not in resolved)
    blocked.update(row[0] for row in connection.execute(
        "SELECT document_id FROM document_items WHERE kind IN ('human-decision','external-open-question') "
        "AND status IN ('PENDING','ACTIVE')"))
    docs = {row["id"].removeprefix("document:vdoc:"): dict(row)
            for row in connection.execute("SELECT * FROM documents WHERE workstream='VDOC'")}
    hashes = {}

    def file_digest(path):
        if path not in hashes:
            try:
                hashes[path] = hashlib.sha256((store.root / path).read_bytes()).hexdigest()
            except OSError:
                hashes[path] = None
        return hashes[path]

    dependencies = defaultdict(list)
    for edge in edges:
        if edge["relation"] == "DEPENDS_ON":
            dependencies[edge["source"]].append(edge["target"])
    producers = defaultdict(list)
    for item in desired.values():
        key, role = item.get("document_key"), item.get("role")
        if not key or not item.get("required", True):
            continue
        if role == "document-writing-plan":
            producers["art.doc_plan:" + key].append(item["id"])
        elif role == "document-deliverable":
            producers["art.doc:" + key].append(item["id"])
            producers["cap.doc:" + key].append(item["id"])
    eligible, skipped = {}, {}
    for node_id in sorted(candidates & desired.keys()):
        item = desired[node_id]
        role, key = item.get("role"), item.get("document_key")
        if role not in {"document-writing-plan", "document-deliverable"}:
            continue
        if statuses.get(node_id) not in {"REVALIDATION_REQUIRED", "REVIEW_REQUIRED"}:
            continue
        reason = None
        definition = store._node_plan_digest(plan, item)
        prefix = "art.doc_plan:" if role == "document-writing-plan" else "art.doc:"
        accepted = connection.execute(
            "SELECT payload_json FROM vdoc_artifact_versions WHERE artifact_id=? ORDER BY version DESC LIMIT 1",
            (prefix + key,),
        ).fetchone()
        payload = json.loads(accepted[0]) if accepted else {}
        entries = payload.get("plans" if role == "document-writing-plan" else "deliveries", [])
        prior = next((entry for entry in entries if entry["node_id"] == node_id
                      and entry["definition_digest"] == definition), None)
        if node_id in blocked:
            reason = "仍有未处理问题或审批意见"
        elif prior is None or payload.get("revision") != plan["revision"]:
            reason = "没有与当前方案相同的已验收历史版本"
        elif role == "document-writing-plan":
            reviews = [dict(row) for table in ("node_plan_reviews", "node_plan_section_reviews")
                       for row in connection.execute(
                           f"SELECT * FROM {table} WHERE node_id=? AND revision=? AND definition_digest=?",
                           (node_id, plan["revision"], definition))]
            latest = max(reviews, key=lambda row: row["created_at"], default=None)
            complete = any("section" not in row and row["verdict"] == "APPROVE"
                           and row["created_at"] >= latest["created_at"] for row in reviews) if latest else False
            sections = {row["section"]: row for row in sorted(reviews, key=lambda row: row["created_at"])
                        if "section" in row}
            required = store._node_plan_sections(connection, node_id)
            complete = complete or bool(required and all(
                sections.get(section, {}).get("verdict") == "APPROVE" for section in required))
            if (not complete or latest["verdict"] != "APPROVE"
                    or latest["id"] != (prior.get("review") or {}).get("id")
                    or prior.get("manifest") != vdoc_artifacts.content_manifest(connection, item)):
                reason = "原批准或检查清单与当前方案不一致"
            else:
                contract = item.get("authoring_contract", {})
                changed = [source["path"] for source in contract.get("source_snapshot", [])
                           if authoring_source_is_dependency(contract, source)
                           and file_digest(source["path"]) != source["sha256"]]
                if changed:
                    reason = "方案实际输入已变化：" + "、".join(changed)
        else:
            document = docs.get(key)
            path = store.root / document["path"] if document else None
            if (not document or path.is_symlink() or store.root not in path.resolve().parents
                    or any(subject in blocked for subject in (
                        document["id"], document["desired_id"], "file:" + document["path"]))
                    or file_digest(document["path"]) != document["digest"]
                    or document["digest"] != payload.get("document_digest")):
                reason = "正文已经变化、缺失或仍有待处理事项"
            else:
                review = connection.execute(
                    "SELECT * FROM document_delivery_reviews WHERE node_id=? AND revision=? "
                    "AND definition_digest=? AND document_digest=? AND semantic_revision=? ORDER BY rowid DESC LIMIT 1",
                    (node_id, plan["revision"], definition, document["digest"], document["semantic_revision"]),
                ).fetchone()
                content = vdoc_artifacts.content_manifest(connection, item, path.read_text(encoding="utf-8"))
                check = connection.execute("SELECT status FROM review_agent_checks WHERE review_id=?",
                                           (review["id"],)).fetchone() if review else None
                if (not review or review["verdict"] != "APPROVE"
                        or review["id"] != (prior.get("review") or {}).get("id")
                        or not check or check[0] != "COMPLETED"
                        or not vdoc_artifacts.check_ready(connection, review["id"], definition,
                                                         document["digest"], content["digest"])):
                    reason = "当前正文缺少原负责人批准或完整的 Agent 检查"
        if reason:
            skipped[node_id] = reason
        else:
            eligible[node_id] = prior["review"]["id"]

    restored = {}

    def available(node_id, seen=frozenset()):
        if node_id in seen or node_id in blocked:
            return False
        if node_id in producers:
            return all(available(producer, seen | {node_id}) for producer in producers[node_id])
        return (node_id in restored or statuses.get(node_id) == "VALID") and all(
            available(target, seen | {node_id}) for target in dependencies[node_id])

    for _ in range(len(eligible) + 1):
        added = {node_id: review for node_id, review in eligible.items() if node_id not in restored
                 and all(available(target) for target in dependencies[node_id])}
        if not added:
            break
        restored.update(added)
    skipped.update({node_id: "前置文档或方案仍需核验" for node_id in eligible if node_id not in restored})
    return restored, skipped, docs


def repair(store, *, apply=False):
    from .store import now, json_text

    connector = store.connect if apply else store.read_connect
    with connector() as connection:
        connection.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        row = connection.execute("SELECT * FROM workstreams WHERE name='VDOC'").fetchone()
        plan = {"workstream": "VDOC", "revision": row["revision"],
                "desired_state": json.loads(row["desired_json"])} if row else None
        removed = obsolete_edges(connection)
        tokens = {(e["source"], e["target"], e["relation"]) for e in removed}
        edges = [dict(e) for e in connection.execute("SELECT * FROM edges")]
        kept = [e for e in edges if (e["source"], e["target"], e["relation"]) not in tokens]
        old_graph, new_graph = _graph(edges), _graph(kept)
        sources = {edge["source"] for edge in removed}
        discharged, candidates = [], set()
        for event in connection.execute("SELECT * FROM events ORDER BY rowid"):
            if event["subject"] not in sources:
                continue
            path = json.loads(event["payload_json"]).get("path")
            if not path or event["subject"] != "file:" + path:
                continue
            excess = _reachable(old_graph, event["subject"]) - _reachable(new_graph, event["subject"])
            for finding in connection.execute(
                "SELECT * FROM findings WHERE cause_event=? AND status='OPEN' AND details=?",
                (event["id"], f"{path} 的 {event['kind']} 事件使该节点需要重新验证"),
            ):
                if finding["subject"] in excess:
                    discharged.append(dict(finding))
                    candidates.add(finding["subject"])
        restored, skipped, docs = _restorable(
            store, connection, plan, candidates, {f["id"] for f in discharged}, kept,
        ) if plan else ({}, {}, {})
        result = {"schema": "DocumentDependencyRepair/1", "project_root": str(store.root),
                  "revision": plan["revision"] if plan else None, "applied": apply,
                  "changed": bool(removed or discharged or restored), "removed_edges": removed,
                  "resolved_findings": discharged, "restored_nodes": restored, "blocked_nodes": skipped}
        if not apply or not result["changed"]:
            return result
        timestamp = now()
        for edge in removed:
            connection.execute("DELETE FROM edges WHERE source=? AND target=? AND relation=? AND origin='authoring-source'",
                               (edge["source"], edge["target"], edge["relation"]))
        connection.executemany("UPDATE findings SET status='RESOLVED' WHERE id=?", [(f["id"],) for f in discharged])
        connection.executemany("UPDATE nodes SET status='VALID',updated_at=? WHERE id=?",
                               [(timestamp, node_id) for node_id in restored])
        for key, document in docs.items():
            deliveries = [n for n in plan["desired_state"] if n.get("document_key") == key
                          and n.get("role") == "document-deliverable" and n.get("required", True)]
            if deliveries and all(n["id"] in restored for n in deliveries):
                connection.execute("UPDATE documents SET status='VALID',updated_at=? WHERE id=?",
                                   (timestamp, document["id"]))
                connection.executemany("UPDATE nodes SET status='VALID',updated_at=? WHERE id=?",
                                       [(timestamp, node_id) for node_id in
                                        (document["id"], document["desired_id"], "file:" + document["path"])])
        event_id = "event:" + uuid.uuid4().hex[:12]
        connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",
                           (event_id, "document-dependency-repair", "workstream:VDOC", str(plan["revision"]),
                            json_text(result), timestamp))
        result["event_id"] = event_id
        connection.execute("DELETE FROM meta WHERE key='vdoc_graph_checkpoint'")
        return result
