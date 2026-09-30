"""VDOC-gated launch policy for the remaining verification workstreams.

The owner selects how Main Agent should form downstream plans.  This module
never approves plans or creates public work nodes; it only records the choice
and starts empty, revisioned workstream envelopes for Main Agent to refine.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .vdoc_artifacts import encoded


WORKSTREAMS = ("VENV", "VREG", "VSTIM", "VCHK", "VCASE", "VCOV")
STRATEGIES = {"parallel", "dependency_order"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_launch_decisions (
 id TEXT PRIMARY KEY, vdoc_revision INTEGER NOT NULL, vdoc_signature TEXT NOT NULL,
 strategy TEXT NOT NULL, reviewer TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS workflow_launch_current
  ON workflow_launch_decisions(vdoc_revision,vdoc_signature,created_at);
"""


def _digest(value: object) -> str:
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def _vdoc_gate(connection) -> dict[str, Any]:
    row = connection.execute(
        "SELECT revision,desired_json FROM workstreams WHERE name='VDOC'"
    ).fetchone()
    if row is None:
        return {"ready": False, "revision": None, "signature": None, "capabilities": []}
    desired = json.loads(row["desired_json"])
    required_keys = sorted({
        str(item.get("document_key"))
        for item in desired
        if item.get("role") == "document-deliverable"
        and item.get("required", True)
        and item.get("document_key")
    })
    heads = []
    for key in required_keys:
        node = connection.execute(
            "SELECT status,data_json FROM nodes WHERE id=?", (f"cap.doc:{key}",),
        ).fetchone()
        data = json.loads(node["data_json"] or "{}") if node else {}
        heads.append({
            "id": f"cap.doc:{key}",
            "status": node["status"] if node else "UNKNOWN",
            "current": data.get("current"),
        })
    ready = bool(required_keys) and all(
        item["status"] == "VALID" and item["current"] for item in heads
    )
    return {
        "ready": ready,
        "revision": row["revision"],
        "signature": _digest({"revision": row["revision"], "capabilities": heads}) if ready else None,
        "capabilities": heads,
    }


def status(store, plans: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return the current, revision-bound launch choice and its scheduling gate."""
    plans = store.workstreams() if plans is None else plans
    by_name = {plan["workstream"]: plan for plan in plans}
    with store.read_connect() as connection:
        gate = _vdoc_gate(connection)
        has_history = bool(connection.execute(
            "SELECT 1 FROM workflow_launch_decisions LIMIT 1"
        ).fetchone())
        decision = None
        if gate["ready"]:
            row = connection.execute(
                "SELECT * FROM workflow_launch_decisions "
                "WHERE vdoc_revision=? AND vdoc_signature=? ORDER BY rowid DESC LIMIT 1",
                (gate["revision"], gate["signature"]),
            ).fetchone()
            decision = dict(row) if row else None
        valid_caps = {
            row[0] for row in connection.execute(
                "SELECT id FROM nodes WHERE type='capability' AND status='VALID'"
            )
        }

    started = {
        name: bool(by_name.get(name, {}).get("desired_state"))
        for name in WORKSTREAMS
    }
    modern = {
        name: bool(by_name.get(name, {}).get("planning_context", {}).get("code_model") == 2)
        for name in WORKSTREAMS
    }
    allowed: list[str] = []
    blocked: dict[str, str] = {}
    if decision:
        if decision["strategy"] == "parallel":
            allowed = list(WORKSTREAMS)
        else:
            allowed.append("VENV")
            venv_ready = bool(by_name.get("VENV") and store.evaluate_closure("VENV", persist=False)["ready"])
            if venv_ready:
                allowed.append("VREG")
            else:
                blocked["VREG"] = "等待 VENV 形成已验收的环境能力"
            if "cap.vreg:executor-ready" in valid_caps:
                allowed.append("VSTIM")
            else:
                blocked["VSTIM"] = "等待 VREG 的回归执行器通过自检"
            vstim_ready = bool(by_name.get("VSTIM") and store.evaluate_closure("VSTIM", persist=False)["ready"])
            if vstim_ready:
                allowed.append("VCHK")
            else:
                blocked["VCHK"] = "等待 VSTIM 形成已验收的激励能力"
            vchk_ready = bool(by_name.get("VCHK") and store.evaluate_closure("VCHK", persist=False)["ready"])
            if vchk_ready:
                allowed.append("VCASE")
            else:
                blocked["VCASE"] = "等待 VCHK 形成已验收的检查能力"
            vcase_ready = bool(by_name.get("VCASE") and store.evaluate_closure("VCASE", persist=False)["ready"])
            if vcase_ready:
                allowed.append("VCOV")
            else:
                blocked["VCOV"] = "等待 VCASE 形成已验收的测试用例能力"
    return {
        "schema": "WorkflowLaunch/1",
        "available": gate["ready"],
        "vdoc_revision": gate["revision"],
        "vdoc_signature": gate["signature"],
        "capabilities": gate["capabilities"],
        "decision": decision,
        "has_history": has_history,
        "selection_required": bool((gate["ready"] or has_history) and decision is None),
        "strategy": decision["strategy"] if decision else None,
        "started": started,
        "modern": modern,
        "allowed_workstreams": allowed,
        "blocked_workstreams": blocked,
    }


def choose(store, strategy: str, reviewer: str, expected_signature: str) -> dict[str, Any]:
    """Bind the owner's choice to the current accepted VDOC capability heads."""
    from .store import HarnessError, now
    from . import code_workflow

    strategy = str(strategy).strip().lower()
    reviewer = str(reviewer).strip()
    if strategy not in STRATEGIES:
        raise HarnessError("启动方式必须是 parallel 或 dependency_order")
    if not reviewer:
        raise HarnessError("请选择启动方式并填写负责人")
    store.ensure_dashboard_schema()
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        gate = _vdoc_gate(connection)
        if not gate["ready"]:
            raise HarnessError("验证文档尚未全部形成当前有效的 art.doc 和 cap.doc")
        if expected_signature != gate["signature"]:
            raise HarnessError("验证文档版本已经变化，请刷新后重新选择启动方式")
        existing = connection.execute(
            "SELECT * FROM workflow_launch_decisions WHERE vdoc_revision=? AND vdoc_signature=? "
            "ORDER BY rowid DESC LIMIT 1", (gate["revision"], gate["signature"]),
        ).fetchone()
        if existing:
            if existing["strategy"] != strategy:
                raise HarnessError("当前验证文档版本已经选择启动方式；文档能力变化后可重新选择")
        else:
            connection.execute(
                "INSERT INTO workflow_launch_decisions VALUES(?,?,?,?,?,?)",
                ("launch:" + uuid.uuid4().hex[:12], gate["revision"], gate["signature"],
                 strategy, reviewer, now()),
            )

    # Start only missing workflow envelopes.  Main Agent still has to submit a
    # DUT-specific proposal; no public work node or approval is created here.
    existing_names = {plan["workstream"] for plan in store.workstreams()}
    for name in WORKSTREAMS:
        if name not in existing_names:
            code_workflow.design(store, name, None, decisions=[
                "负责人选择" + ("并行形成其余工作流方案" if strategy == "parallel" else "按依赖顺序形成其余工作流方案")
            ])
    return status(store)
