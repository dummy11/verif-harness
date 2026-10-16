"""Explicit repair of unchanged code packages replaced by legacy whole-scope replans."""

import json
import uuid

from . import code_workflow as code


def restore_package(store, node_id, previous_plan_id, expected_digest, *, apply=False):
    """Restore original nodes only after proving their existing approvals still apply.

    This never copies an approval or validation to another node/revision. A
    replacement already accepted by its owner remains in place. Dry runs roll
    back the temporary historical artifact-head selection used for the proof.
    """
    from .store import HarnessError, now

    code.refresh(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        plan, current = code.selected(store, node_id, db)
        if plan["workstream"] not in {"VENV", "VSTIM", "VCHK", "VCASE"} or not code.is_plan(current):
            raise HarnessError("只能核对代码工作包的原方案与交付节点")
        current_state = code.review_state(store, node_id, plan, current, db)
        if current_state["definition_digest"] != expected_digest:
            raise HarnessError("当前方案版本已变化，请重新核对后修复")
        delivery = next((n for n in plan["desired_state"] if n.get("parent_id") == node_id), None)
        if delivery is None:
            raise HarnessError("当前工作包缺少对应交付节点")
        delivery_state = code.review_state(store, delivery["id"], plan, delivery, db)
        if delivery_state["completed"]:
            db.rollback()
            return {"status": "ALREADY_ACCEPTED", "node_id": node_id}
        if not current_state["completed"] or not delivery_state["can_approve"]:
            raise HarnessError("当前方案、验证或依赖不满足条件，不能恢复原节点")
        for identifier in (node_id, delivery["id"]):
            if db.execute("SELECT 1 FROM node_plan_section_reviews WHERE node_id=? LIMIT 1", (identifier,)).fetchone():
                raise HarnessError("替代节点存在负责人意见，必须保留并处理，不能恢复原节点")
        original = db.execute("SELECT data_json FROM nodes WHERE id=?", (previous_plan_id,)).fetchone()
        if original is None:
            raise HarnessError("原方案节点不存在")
        original = json.loads(original[0])
        old_revision = code.node_revision(plan, original)
        if old_revision >= code.node_revision(plan, current):
            raise HarnessError("原方案必须早于当前替代节点")
        for event in db.execute("SELECT revision,payload_json FROM events WHERE kind=?",
                                (plan["workstream"].lower() + "-replan",)):
            if int(event["revision"]) > old_revision and json.loads(event["payload_json"]).get("restart"):
                raise HarnessError("显式重启之后不能恢复旧版本批准")
        old_delivery = db.execute("SELECT data_json FROM nodes WHERE id=?", (previous_plan_id + ":delivery",)).fetchone()
        if old_delivery is None:
            raise HarnessError("原交付节点不存在")
        old_delivery = json.loads(old_delivery[0])

        def definition(node):
            return {k: v for k, v in node.items() if k not in {"id", "parent_id"}}

        if (definition(current) != definition(original)
                or definition(delivery) != definition(old_delivery)):
            raise HarnessError("工作包范围或方案内容已经变化，不能恢复原节点")
        old_state = code.review_state(store, original["id"], plan, original, db)
        if not old_state["completed"]:
            raise HarnessError("原方案批准与当前实际输入或依赖版本不匹配")
        _, current_snapshot = code.identity(store, db, plan, current)
        _, old_snapshot = code.identity(store, db, plan, original)
        _, current_delivery_snapshot = code.identity(store, db, plan, delivery)
        _, old_delivery_snapshot = code.identity(store, db, plan, old_delivery)
        if (current_snapshot["questions"] != old_snapshot["questions"]
                or current_delivery_snapshot["questions"] != old_delivery_snapshot["questions"]):
            raise HarnessError("负责人问题或回答发生变化，不能恢复原节点")
        artifact_id = code.ids(original["implementation_key"], plan["workstream"])[0]
        artifact = next((row for row in db.execute(
            "SELECT * FROM code_artifact_versions WHERE artifact_id=? ORDER BY version DESC", (artifact_id,),
        ) if json.loads(row["payload_json"]).get("definition") == original
            and json.loads(row["payload_json"]).get("signature") == old_state["definition_digest"]), None)
        if artifact is None:
            raise HarnessError("没有与原批准匹配的不可变方案产物")
        data = json.loads(db.execute("SELECT data_json FROM nodes WHERE id=?", (artifact_id,)).fetchone()[0])
        data["current"] = {"version": artifact["version"], "signature": artifact["signature"]}
        db.execute("UPDATE nodes SET status='VALID',data_json=? WHERE id=?", (code.encoded(data), artifact_id))
        old_delivery_state = code.review_state(store, old_delivery["id"], plan, old_delivery, db)
        if not old_delivery_state["completed"]:
            raise HarnessError("原交付批准或原始证据已失效，不能恢复原节点")
        old_validation = old_delivery_state["validation"]
        current_validation = delivery_state["validation"]
        for field in ("code_files", "checks", "testcase_contract", "execution_binding"):
            if old_validation.get(field) != current_validation.get(field):
                raise HarnessError("代码、测试证据或检查结论已经变化，不能恢复原节点")
        replacement = {node_id: original, delivery["id"]: old_delivery}
        desired = [replacement.get(n["id"], n) for n in plan["desired_state"]]
        result = {
            "status": "RESTORED" if apply else "VERIFIED", "workstream": plan["workstream"],
            "workstream_revision": plan["revision"], "node_revision": old_revision,
            "replaced_node_ids": sorted(replacement),
            "restored_node_ids": [original["id"], old_delivery["id"]],
            "original_review_ids": [old_state["current_completion"]["id"],
                                    old_delivery_state["current_completion"]["id"]],
        }
        if not apply:
            db.rollback()
            return result
        timestamp = now()
        db.execute("UPDATE workstreams SET desired_json=?,updated_at=? WHERE name=?",
                   (code.encoded(desired), timestamp, plan["workstream"]))
        for identifier in replacement:
            db.execute("UPDATE nodes SET workstream=NULL,status='STALE',updated_at=? WHERE id=?", (timestamp, identifier))
            db.execute("UPDATE actions SET status='SUPERSEDED' WHERE target=? AND status='OPEN'", (identifier,))
            db.execute("UPDATE agent_assignments SET status='SUPERSEDED',ended_at=?,updated_at=? WHERE node_id=? AND status='ACTIVE'",
                       (timestamp, timestamp, identifier))
        for original_node in (original, old_delivery):
            db.execute("UPDATE nodes SET workstream=?,status='VALID',updated_at=? WHERE id=?",
                       (plan["workstream"], timestamp, original_node["id"]))
        db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", (
            "event:" + uuid.uuid4().hex, "code-scope-repair", node_id, str(plan["revision"]),
            code.encoded({**result, "previous_nodes": [current, delivery]}), timestamp,
        ))
    code.refresh(store)
    states = [code.review_state(store, identifier) for identifier in result["restored_node_ids"]]
    if not all(state["completed"] for state in states):
        raise HarnessError("恢复后证据发生变化；节点保持阻塞，请重新核对")
    store.evaluate_closure(plan["workstream"])
    store.write_workstream_projection(plan["workstream"])
    return result
