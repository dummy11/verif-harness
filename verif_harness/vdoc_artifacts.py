"""Versioned VDOC results, not additional work or approval targets.

ProjectStore owns authorization and transactions. This module derives current
heads from its recorded approvals; immutable versions preserve accepted content.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS vdoc_artifact_versions (
  artifact_id TEXT NOT NULL, version INTEGER NOT NULL, signature TEXT NOT NULL,
  payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(artifact_id,version), UNIQUE(artifact_id,signature)
);
CREATE TABLE IF NOT EXISTS vdoc_manifest_checks (
  review_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, definition_digest TEXT NOT NULL,
  document_digest TEXT NOT NULL, manifest_digest TEXT NOT NULL,
  manifest_json TEXT NOT NULL, checked_by TEXT NOT NULL, summary TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vdoc_legacy_units (
  node_id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, item_json TEXT NOT NULL,
  history_json TEXT NOT NULL, migrated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS vdoc_legacy_parent ON vdoc_legacy_units(parent_id);
"""


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(value: Any) -> str:
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def protected(node_id: str) -> bool:
    return node_id.startswith(("art.doc_plan:", "art.doc:", "cap.doc:"))


def ids(document_key: str) -> tuple[str, str, str]:
    return tuple(f"{prefix}:{document_key}" for prefix in ("art.doc_plan", "art.doc", "cap.doc"))


def manifest(desired: dict[str, Any], body: str = "") -> dict[str, Any]:
    """Keep source/requirement mappings inside a result, with no WorkNode state."""
    items = [{"key": item["id"], "kind": item["field"],
              "content": item["content"], "digest": item["digest"]}
             for item in desired.get("internal_semantic_units", [])]
    # Heading occurrences are scoped by their full path. Ignore code examples.
    path: list[tuple[int, str]] = []
    occurrences: dict[str, int] = defaultdict(int)
    fence = ""
    section: list[str] = []
    section_key = "preamble"

    def append_section() -> None:
        content = "\n".join(section).strip()
        if content:
            items.append({"key": "section:" + section_key, "kind": "body-section",
                          "content": content, "digest": digest(content)})

    for line in body.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ""
            section.append(line)
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line) if not fence else None
        if heading:
            append_section()
            section = []
            level, title = len(heading.group(1)), heading.group(2)
            path = [(n, text) for n, text in path if n < level] + [(level, title)]
            key = "/".join(text for _, text in path)
            occurrences[key] += 1
            section_key = f"{key}:{occurrences[key]}"
        section.append(line)
    append_section()
    return {"items": items, "digest": digest(items)}


def content_manifest(connection, desired: dict[str, Any], body: str = "") -> dict[str, Any]:
    result = manifest(desired, body)
    known = {(item["key"], item["digest"]) for item in result["items"]}
    for row in connection.execute("SELECT node_id,item_json FROM vdoc_legacy_units WHERE parent_id=? ORDER BY node_id", (desired["id"],)):
        old = json.loads(row["item_json"])
        if (old.get("semantic_unit_id"), old.get("semantic_digest")) in known:
            continue
        # Preserve extra/edited legacy checks not represented in the public
        # definition. They must be inspected too, without changing its approval.
        content = old.get("statement") or old.get("work_content") or old["title"]
        result["items"].append({"key": "legacy:" + row["node_id"], "kind": "legacy-check",
                                "content": content, "digest": digest(content)})
    result["digest"] = digest(result["items"])
    return result


def migrate(connection, timestamp: str) -> None:
    """Archive mechanical v1 nodes atomically; never inherit their completion.

    Public definitions are not edited, so exact owner approvals remain bound.
    Existing Agent checks are retained in the migration audit and reopened.
    """
    if connection.execute("SELECT 1 FROM meta WHERE key='vdoc_graph_v2'").fetchone():
        return
    row = connection.execute("SELECT desired_json FROM workstreams WHERE name='VDOC'").fetchone()
    desired = json.loads(row[0]) if row else []
    children = {item["id"]: item for item in desired if item.get("role") == "document-semantic-unit"}
    for node_id, item in children.items():
        parent_id = item["parent_id"]
        history = {"node": dict(connection.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()),
                   "edges": [dict(edge) for edge in connection.execute(
                       "SELECT * FROM edges WHERE source=? OR target=?", (node_id, node_id))],
                   "agent_checks": [dict(check) for check in connection.execute(
                       "SELECT * FROM review_agent_checks WHERE node_id=?", (parent_id,))]}
        connection.execute("INSERT INTO vdoc_legacy_units VALUES(?,?,?,?,?)",
                           (node_id, parent_id, encoded(item), encoded(history), timestamp))
        # Rebind unresolved work, retaining original targets in the migration audit.
        for table, column in (("agent_questions", "target"), ("human_actions", "target"),
                              ("findings", "subject")):
            originals = [dict(r) for r in connection.execute(
                f"SELECT * FROM {table} WHERE {column}=? AND status='OPEN'", (node_id,))]
            history[table] = originals
            connection.execute(f"UPDATE {table} SET {column}=? WHERE {column}=? AND status='OPEN'",
                               (parent_id, node_id))
        connection.execute("UPDATE agent_questions SET node_id=? WHERE node_id=? AND status='OPEN'",
                           (parent_id, node_id))
        connection.execute("UPDATE vdoc_legacy_units SET history_json=? WHERE node_id=?",
                           (encoded(history), node_id))
        connection.execute("UPDATE activities SET status='CANCELLED',ended_at=?,updated_at=? "
                           "WHERE node_id=? AND status IN ('PENDING','RUNNING','WAITING_FOR_HUMAN','WAITING_FOR_PARENT')", (timestamp, timestamp, node_id))
        connection.execute("UPDATE agent_assignments SET status='SUPERSEDED',ended_at=?,updated_at=? "
                           "WHERE node_id=? AND status='ACTIVE'", (timestamp, timestamp, node_id))
        connection.execute("UPDATE actions SET status='SUPERSEDED' WHERE target=? AND status='OPEN'", (node_id,))
        connection.execute("UPDATE nodes SET workstream=NULL WHERE id=?", (node_id,))
        if item.get("parent_role") == "document-deliverable":
            connection.execute("UPDATE review_agent_checks SET status='PENDING',updated_at=? WHERE node_id=?",
                               (timestamp, parent_id))
            connection.execute("UPDATE nodes SET status='REVIEW_REQUIRED' WHERE id=?", (parent_id,))
            connection.execute("UPDATE documents SET status='REVIEW_REQUIRED' WHERE id=?",
                               (f"document:vdoc:{item['document_key']}",))
    # Preserve independent explicit dependencies, mapped to the public owner or CAP.
    edges = [dict(r) for r in connection.execute("SELECT * FROM edges")]
    for edge in edges:
        source, target = edge["source"], edge["target"]
        if source not in children and target not in children:
            continue
        connection.execute("DELETE FROM edges WHERE source=? AND target=? AND relation=?",
                           (source, target, edge["relation"]))
        if edge["relation"] not in {"DEPENDS_ON", "AFFECTS"} or edge["origin"] == "planner-default":
            continue
        source = children.get(source, {}).get("parent_id", source)
        if target in children:
            child = children[target]
            owner = connection.execute("SELECT workstream FROM nodes WHERE id=?", (source,)).fetchone()
            target = (ids(child["document_key"])[2]
                      if edge["relation"] == "DEPENDS_ON" and owner and owner[0] != "VDOC"
                      else child["parent_id"])
        if source != target:
            connection.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?,?,?,?,?)",
                               (source, target, edge["relation"], edge["origin"], edge["confidence"],
                                edge["data_json"], timestamp))
    if children:
        connection.execute("UPDATE workstreams SET desired_json=?,updated_at=? WHERE name='VDOC'",
                           (encoded([item for item in desired if item["id"] not in children]), timestamp))
    document_keys = {item["id"]: item.get("document_key") or item.get("key")
                     for item in desired if item.get("role") in {
                         "document-catalog", "document-writing-plan", "document-deliverable"}}
    rewired = []
    for edge in connection.execute("SELECT edges.* FROM edges JOIN nodes ON nodes.id=edges.source "
                                   "WHERE relation='DEPENDS_ON' AND nodes.workstream IS NOT NULL "
                                   "AND nodes.workstream!='VDOC'").fetchall():
        key = document_keys.get(edge["target"])
        if not key and edge["target"].startswith("document:vdoc:"):
            key = edge["target"].removeprefix("document:vdoc:")
        if not key:
            continue
        cap_id = ids(key)[2]
        connection.execute("INSERT OR IGNORE INTO nodes VALUES(?,?,?,NULL,?,?,?,?)",
                           (cap_id, "capability", "文档尚未验收通过", "UNKNOWN",
                            encoded({"document_key": key, "derived": True}), timestamp, timestamp))
        connection.execute("DELETE FROM edges WHERE source=? AND target=? AND relation='DEPENDS_ON'",
                           (edge["source"], edge["target"]))
        connection.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?,?,?,?,?)",
                           (edge["source"], cap_id, "DEPENDS_ON", edge["origin"], edge["confidence"], edge["data_json"], timestamp))
        rewired.append(dict(edge))
    if rewired:
        connection.execute("INSERT INTO events VALUES('migration:vdoc-v2-dependencies',?,?,NULL,?,?)",
                           ("vdoc-v2-migration", "workstream:VDOC", encoded({"previous_edges": rewired}), timestamp))
    connection.execute("INSERT INTO meta VALUES('vdoc_graph_v2','1')")


def check_ready(connection, review_id: str, definition_digest: str,
                document_digest: str, manifest_digest: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM vdoc_manifest_checks WHERE review_id=? AND definition_digest=? "
        "AND document_digest=? AND manifest_digest=?",
        (review_id, definition_digest, document_digest, manifest_digest),
    ).fetchone() is not None


def reconcile(store, plans: list[dict[str, Any]]) -> None:
    """Rebuild only after authoritative changes; no per-entry SQL or worker launch."""
    from .store import now  # ProjectStore imports the schema without a cycle.

    plan = next((item for item in plans if item["workstream"] == "VDOC"), None)
    if plan is None:
        return
    with store.connect() as connection:
        docs = {row["id"].removeprefix("document:vdoc:"): dict(row)
                for row in connection.execute("SELECT * FROM documents WHERE workstream='VDOC'")}
        stamps = []
        for key, document in sorted(docs.items()):
            try:
                stat = (store.root / document["path"]).stat()
                stamps.append((key, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino))
            except OSError:
                stamps.append((key, None))
        file_token = digest(stamps)
        counter = connection.execute("SELECT version FROM agent_service_changes WHERE id=1").fetchone()[0]
        if getattr(store, "_vdoc_graph_checkpoint", None) == (counter, file_token):
            return
        previous = connection.execute("SELECT value FROM meta WHERE key='vdoc_graph_checkpoint'").fetchone()
        if previous and previous[0] == encoded([counter, file_token]):
            return
        # Serializes competing API/CLI reconcilers with approval writers.
        connection.execute("BEGIN IMMEDIATE")
        observed = connection.execute("SELECT revision,desired_json FROM workstreams WHERE name='VDOC'").fetchone()
        if observed["revision"] != plan["revision"] or json.loads(observed["desired_json"]) != plan["desired_state"]:
            # A concurrent proposal changed the input; never publish mixed revisions.
            return
        docs = {row["id"].removeprefix("document:vdoc:"): dict(row)
                for row in connection.execute("SELECT * FROM documents WHERE workstream='VDOC'")}
        timestamp = now()
        statuses = {row["id"]: row["status"] for row in connection.execute("SELECT id,status FROM nodes")}
        dependencies: dict[str, list[str]] = defaultdict(list)
        for row in connection.execute("SELECT source,target FROM edges WHERE relation='DEPENDS_ON'"):
            dependencies[row["source"]].append(row["target"])
        blocked = set()
        for table, column, condition in (
            ("agent_questions", "target", "status='OPEN'"),
            ("human_actions", "target", "status='OPEN'"),
            ("findings", "subject", "status='OPEN'"),
            ("review_feedback_items", "node_id", "status IN ('DRAFT','PENDING','WAITING_FOR_HUMAN')"),
        ):
            blocked.update(row[0] for row in connection.execute(f"SELECT {column} FROM {table} WHERE {condition}"))
        for row in connection.execute("SELECT document_id FROM document_items WHERE "
                                      "kind IN ('human-decision','external-open-question') AND status IN ('PENDING','ACTIVE')"):
            blocked.add(row[0])
        groups: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for item in plan["desired_state"]:
            if item.get("document_key") and item.get("role") in {"document-writing-plan", "document-deliverable"}:
                groups[item["document_key"]][item["role"]].append(item)
        # First revoke existing heads. Below each current document earns validity.
        old_heads = {row["id"]: dict(row) for row in connection.execute(
            "SELECT id,status,data_json FROM nodes WHERE id LIKE 'art.doc:%' "
            "OR id LIKE 'art.doc_plan:%' OR id LIKE 'cap.doc:%'")}
        heads: dict[str, tuple[str, dict[str, Any]]] = {}
        new_edges: set[tuple[str, str]] = set()

        def usable(node_id: str, visiting=None) -> bool:
            visiting = set() if visiting is None else visiting
            if node_id in visiting or node_id in blocked:
                return False
            if node_id in heads:
                return heads[node_id][0] == "VALID"
            if protected(node_id):
                return False
            if statuses.get(node_id) != "VALID":
                return False
            return all(usable(target, visiting | {node_id}) for target in dependencies[node_id])

        def publish(artifact_id: str, payload: dict[str, Any], valid: bool) -> None:
            current = None
            if valid:
                signature = digest(payload)
                current = connection.execute("SELECT version FROM vdoc_artifact_versions WHERE artifact_id=? AND signature=?",
                                             (artifact_id, signature)).fetchone()
                if current is None:
                    version = connection.execute("SELECT COALESCE(MAX(version),0)+1 FROM vdoc_artifact_versions WHERE artifact_id=?",
                                                 (artifact_id,)).fetchone()[0]
                    connection.execute("INSERT INTO vdoc_artifact_versions VALUES(?,?,?,?,?)",
                                       (artifact_id, version, signature, encoded(payload), timestamp))
                else:
                    version = current[0]
                current = {"version": version, "signature": signature}
            heads[artifact_id] = ("VALID" if valid else "REVIEW_REQUIRED", {
                "document_key": payload["document_key"], "workstream_revision": plan["revision"],
                "current": current, "derived": True,
            })

        # Plans first, so body artifacts bind an exact accepted plan version.
        for key, group in groups.items():
            plan_id, _, _ = ids(key)
            producers = [item for item in group["document-writing-plan"] if item.get("required", True)]
            valid = bool(producers)
            payload = {"document_key": key, "revision": plan["revision"], "plans": []}
            for item in producers:
                definition = store._node_plan_digest(plan, item)
                reviews = [dict(r) for table in ("node_plan_reviews", "node_plan_section_reviews")
                           for r in connection.execute(f"SELECT * FROM {table} WHERE node_id=? AND revision=? AND definition_digest=? ORDER BY rowid",
                                                       (item["id"], plan["revision"], definition))]
                latest = max(reviews, key=lambda r: r["created_at"], default=None)
                completion = [r for r in reviews if "section" not in r and r["verdict"] == "APPROVE"]
                sections = {r["section"]: r for r in reviews if "section" in r}
                complete = bool(latest and any(r["created_at"] >= latest["created_at"] for r in completion))
                required = store._node_plan_sections(connection, item["id"])
                section_approved = bool(required) and all(sections.get(s, {}).get("verdict") == "APPROVE" for s in required)
                valid = valid and usable(item["id"]) and (complete or section_approved)
                payload["plans"].append({"node_id": item["id"], "definition_digest": definition,
                                         "definition": item, "manifest": content_manifest(connection, item), "review": latest})
                new_edges.add((plan_id, item["id"]))
            publish(plan_id, payload, valid)
        for key, group in groups.items():
            plan_id, doc_id, cap_id = ids(key)
            producers = [item for item in group["document-deliverable"] if item.get("required", True)]
            document = docs.get(key)
            body = ""
            current_file = False
            if document:
                try:
                    path = store.root / document["path"]
                    if path.is_symlink() or store.root not in path.resolve().parents:
                        raise OSError("document path no longer belongs to this project")
                    raw = path.read_bytes()
                    body = raw.decode("utf-8")
                    current_file = hashlib.sha256(raw).hexdigest() == document["digest"]
                except (OSError, UnicodeError):
                    pass
            valid = (bool(producers) and current_file and heads[plan_id][0] == "VALID"
                     and document["id"] not in blocked)
            payload = {"document_key": key, "revision": plan["revision"],
                       "plan": heads[plan_id][1]["current"], "plan_id": plan_id,
                       "document_digest": document["digest"] if document else None,
                       "body": body, "deliveries": []}
            covered = set()
            for item in producers:
                definition = store._node_plan_digest(plan, item)
                content = content_manifest(connection, item, body)
                review = connection.execute("SELECT * FROM document_delivery_reviews WHERE node_id=? AND revision=? "
                    "AND definition_digest=? AND document_digest=? AND semantic_revision=? ORDER BY rowid DESC LIMIT 1",
                    (item["id"], plan["revision"], definition, document["digest"] if document else "",
                     document["semantic_revision"] if document else 0)).fetchone()
                check = connection.execute("SELECT * FROM review_agent_checks WHERE review_id=?",
                                           (review["id"],)).fetchone() if review else None
                checked = bool(review and check and check["status"] == "COMPLETED" and check_ready(
                    connection, review["id"], definition, document["digest"], content["digest"]))
                item_current = (current_file and heads[plan_id][0] == "VALID" and checked
                                and usable(item["id"]) and bool(review and review["verdict"] == "APPROVE"))
                valid = valid and item_current
                if not item_current and statuses.get(item["id"]) in {"VALID", "WAIVED"}:
                    connection.execute("UPDATE nodes SET status='REVIEW_REQUIRED',updated_at=? WHERE id=?", (timestamp, item["id"]))
                    connection.execute("UPDATE workstreams SET lifecycle='PARTIALLY_STALE',updated_at=? "
                                       "WHERE name='VDOC' AND lifecycle IN ('ACTIVE','SATISFIED')", (timestamp,))
                covered.add(item.get("parent_id"))
                payload["deliveries"].append({"node_id": item["id"], "definition_digest": definition,
                    "manifest": content, "review": dict(review) if review else None,
                    "agent_check": dict(check) if check else None})
                new_edges.update(((item["id"], plan_id), (doc_id, item["id"])))
            valid = valid and all(item["id"] in covered for item in group["document-writing-plan"] if item.get("required", True))
            publish(doc_id, payload, bool(valid))
            heads[cap_id] = ("VALID" if valid else "REVIEW_REQUIRED", {
                "document_key": key, "derived": True, "artifact_id": doc_id,
                "current": heads[doc_id][1]["current"], "workstream_revision": plan["revision"],
            })
            new_edges.update(((doc_id, plan_id), (cap_id, doc_id)))
        for node_id, old in old_heads.items():
            if node_id not in heads:
                data = json.loads(old["data_json"])
                data["current"] = None
                heads[node_id] = ("STALE", data)
        changed_caps = []
        for node_id, (status, data) in heads.items():
            data_json = encoded(data)
            old = old_heads.get(node_id)
            if old and old["status"] == status and old["data_json"] == data_json:
                continue
            if node_id.startswith("cap.doc:") and old and old["status"] == "VALID":
                changed_caps.append(node_id)
            label = "文档可用状态" if node_id.startswith("cap.") else "批准后的文档方案" if node_id.startswith("art.doc_plan:") else "验收后的文档正文"
            connection.execute("INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                               "title=excluded.title,status=excluded.status,data_json=excluded.data_json,updated_at=excluded.updated_at",
                               (node_id, "capability" if node_id.startswith("cap.") else "artifact",
                                f"{label} · {data['document_key']}", None, status, data_json, timestamp, timestamp))
        existing = {(r[0], r[1]) for r in connection.execute("SELECT source,target FROM edges WHERE origin='vdoc-artifact'")}
        for source, target in existing - new_edges:
            connection.execute("DELETE FROM edges WHERE source=? AND target=? AND origin='vdoc-artifact'", (source, target))
        for source, target in new_edges - existing:
            connection.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?,?,?,?,?)",
                               (source, target, "DEPENDS_ON", "vdoc-artifact", 1.0, "{}", timestamp))
        # Revoke completed consumers transitively; new evidence must re-establish them.
        pending, visited = list(changed_caps), set()
        while pending:
            target = pending.pop()
            if target in visited:
                continue
            visited.add(target)
            for row in connection.execute("SELECT source FROM edges WHERE target=? AND relation='DEPENDS_ON'", (target,)):
                source = row[0]
                pending.append(source)
                if not protected(source):
                    connection.execute("UPDATE nodes SET status='REVALIDATION_REQUIRED',updated_at=? "
                                       "WHERE id=? AND status IN ('VALID','PROVISIONAL','WAIVED')", (timestamp, source))
                    connection.execute("UPDATE workstreams SET lifecycle='PARTIALLY_STALE',updated_at=? "
                        "WHERE name IN (SELECT workstream FROM nodes WHERE id=?) AND lifecycle IN ('ACTIVE','SATISFIED')",
                        (timestamp, source))
        counter = connection.execute("SELECT version FROM agent_service_changes WHERE id=1").fetchone()[0]
        # Unrelated writes must not turn a read into another DB change/cache miss.
        if connection.total_changes:
            connection.execute("INSERT OR REPLACE INTO meta VALUES('vdoc_graph_checkpoint',?)", (encoded([counter, file_token]),))
            headers = {r["name"]: r for r in connection.execute("SELECT name,lifecycle,updated_at FROM workstream_read_headers")}
            for workstream in plans:
                header = headers[workstream["workstream"]]
                workstream.update(lifecycle=header["lifecycle"], updated_at=header["updated_at"])
        store._vdoc_graph_checkpoint = (counter, file_token)
