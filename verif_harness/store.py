"""Durable project model for the verif-harness v1 control plane."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 2
STATE_DIR = ".verif-harness"
IGNORED_PARTS = {".git", ".deps", STATE_DIR, "__pycache__"}
RTL_SUFFIXES = {".v", ".sv", ".svh", ".vhd", ".vhdl"}
DOC_SUFFIXES = {".md", ".rst", ".txt", ".pdf"}


class HarnessError(ValueError):
    """A user-actionable project-state error."""


class Validity(str, Enum):
    VALID = "VALID"
    STALE = "STALE"
    INVALID = "INVALID"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    BLOCKED = "BLOCKED"
    WAIVED = "WAIVED"
    UNKNOWN = "UNKNOWN"


WORKSTREAM_STATES = {"REVIEW", "ACTIVE", "SATISFIED", "BASELINED", "PARTIALLY_STALE", "REVISE"}
WORKSTREAM_TEMPLATES: dict[str, dict[str, Any]] = {
    "VDOC": {
        "name": "Verification Documentation",
        "objective": "形成并持续维护可评审的验证定义、架构、策略和退出标准",
        "desired": [
            ("scope", "验证范围、目标、优先级和 deferred scope 明确", "plan"),
            ("dut-understanding", "DUT 行为、接口、配置、reset 与异常语义可追溯", "plan"),
            ("feature-model", "feature、scenario、risk、open question 与 Human Decision 已结构化", "plan"),
            ("strategy", "stimulus、checking、coverage、case、regression 策略已定义", "plan"),
            ("architecture", "verification environment 与 reference-model 边界已定义", "plan"),
        ],
        "exit": ["required 文档节点为 VALID 或 Human WAIVED", "无未处置 CRITICAL open decision"],
    },
    "VSTIM": {
        "name": "Stimulus",
        "objective": "实现可复现、可组合并覆盖目标场景的激励能力",
        "desired": [
            ("transaction-contract", "transaction、sequence 与 constraint 合同明确", "plan"),
            ("stimulus-implementation", "required feature 有可复现 stimulus 实现", "add-uvc-skeleton"),
            ("corner-scenarios", "边界、错误、并发与 backpressure 场景可生成", "add-testcase"),
            ("stimulus-evidence", "targeted run 证明 stimulus 可达且行为确定", "xverif"),
        ],
        "exit": ["required stimulus 节点有效", "目标场景存在新鲜可达性证据"],
    },
    "VCHK": {
        "name": "Checking",
        "objective": "建立可信的 comparison、reference model、scoreboard 与 assertion",
        "desired": [
            ("compare-policy", "数值、时序、顺序、异常与容差策略明确", "plan"),
            ("reference-model", "reference-model adapter 与 DUT 边界可验证", "add-refmodel-bridge"),
            ("scoreboard", "scoreboard/checker 对 required feature 生效", "complete-scoreboard"),
            ("assertions", "协议与关键不变量有 assertion 和非空洞证据", "add-assertion-skeleton"),
        ],
        "exit": ["required checking path 有确定性 evidence", "无未解释 checker mismatch"],
    },
    "VCOV": {
        "name": "Coverage",
        "objective": "建立可追溯 coverage model 并持续分析、关闭 coverage hole",
        "desired": [
            ("coverage-model", "functional/code/assertion coverage 目标可追溯", "add-coverage-skeleton"),
            ("coverage-collection", "coverage 数据可重复收集并关联 revision", "xverif"),
            ("hole-analysis", "coverage hole 已补测、证明不可达或 Human waiver", "coverage-closure"),
        ],
        "exit": ["required coverage goal 有新鲜证据", "所有 required hole 已处置"],
    },
    "VCASE": {
        "name": "Testcase",
        "objective": "把 verification feature 组合成可重复执行、可诊断的 testcase",
        "desired": [
            ("case-matrix", "feature/scenario 到 testcase 的映射完整", "plan"),
            ("case-implementation", "required testcase 与 virtual sequence 已实现", "add-testcase"),
            ("targeted-evidence", "新增 testcase 通过 targeted run", "xverif"),
        ],
        "exit": ["required feature 无 testcase 缺口", "新增 case 有新鲜通过证据"],
    },
    "VREG": {
        "name": "Regression",
        "objective": "执行可复现 regression、聚类失败、调试并刷新验证证据",
        "desired": [
            ("regression-policy", "smoke/nightly/full、seed、timeout、rerun 与 known-fail policy 明确", "add-regression-runner"),
            ("execution", "required regression 可确定性执行并保留 revision 信息", "xverif"),
            ("triage", "失败已聚类，语义歧义才路由到 Verification Reasoning Engine", "regression-triage"),
            ("fresh-evidence", "required verification node 关联当前 revision 的新鲜 evidence", "xverif"),
        ],
        "exit": ["无未处置 P0/P1 failure", "required evidence 与当前 revision 一致"],
    },
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def git_revision(root: Path) -> str | None:
    checked = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=False,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    value = checked.stdout.strip()
    return value if checked.returncode == 0 and len(value) == 40 else None


def relative_path(root: Path, value: str | Path) -> str:
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise HarnessError(f"路径必须位于项目内: {value}") from exc
    return relative.as_posix() or "."


def source_inventory(root: Path, limit: int = 10000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts) or path.is_symlink() or not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in RTL_SUFFIXES | DOC_SUFFIXES | {".json", ".yaml", ".yml", ".toml", ".f"}:
            continue
        stat = path.stat()
        kind = "rtl" if suffix in RTL_SUFFIXES else "document" if suffix in DOC_SUFFIXES else "metadata"
        rows.append({"path": relative.as_posix(), "kind": kind, "size": stat.st_size})
        if len(rows) >= limit:
            break
    return rows


def capabilities() -> dict[str, Any]:
    groups = {
        "reasoning": {"codex": ("codex",), "kimi": ("kimi", "kimi-cli"), "claude": ("claude",)},
        "simulation": {"verilator": ("verilator",), "vcs": ("vcs",), "xrun": ("xrun",), "vsim": ("vsim",)},
        "debug": {"verdi": ("verdi",), "simvision": ("simvision",), "visualizer": ("visualizer",)},
        "scheduler": {"bsub": ("bsub",)},
        "formal_lint": {"jaspergold": ("jg", "jaspergold"), "vcformal": ("vcf", "vcformal"), "spyglass": ("spyglass",)},
        "source": {"git": ("git",)},
    }
    result: dict[str, Any] = {}
    for group, commands in groups.items():
        result[group] = {}
        for name, candidates in commands.items():
            executable = next((shutil.which(item) for item in candidates if shutil.which(item)), None)
            result[group][name] = {"available": executable is not None, "executable": executable}
    return result


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL, workstream TEXT,
  status TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
  source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT NOT NULL, origin TEXT NOT NULL,
  confidence REAL NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (source, target, relation)
);
CREATE TABLE IF NOT EXISTS workstreams (
  name TEXT PRIMARY KEY, lifecycle TEXT NOT NULL, revision INTEGER NOT NULL,
  objective TEXT NOT NULL, desired_json TEXT NOT NULL, exit_json TEXT NOT NULL,
  decisions_json TEXT NOT NULL, context_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY, workstream TEXT NOT NULL, revision INTEGER NOT NULL, verdict TEXT NOT NULL,
  reviewer TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, revision TEXT,
  payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,
  cause_event TEXT, details TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
  digest TEXT, verdict TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
  id TEXT PRIMARY KEY, workstream TEXT NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL,
  priority INTEGER NOT NULL, status TEXT NOT NULL, executor TEXT NOT NULL, suggested_mode TEXT,
  reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS baselines (
  id TEXT PRIMARY KEY, workstream TEXT, revision INTEGER, kind TEXT NOT NULL, digest TEXT NOT NULL,
  path TEXT NOT NULL, reviewer TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


@dataclass
class ProjectStore:
    root: Path

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.state = self.root / STATE_DIR
        self.database = self.state / "model.sqlite3"

    @property
    def initialized(self) -> bool:
        return (self.state / "project.json").is_file() and self.database.is_file()

    def require(self) -> None:
        if not self.initialized:
            raise HarnessError(f"项目尚未 bootstrap: {self.root}")

    def connect(self) -> sqlite3.Connection:
        self.state.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        observed = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if observed is not None and int(observed["value"]) != SCHEMA_VERSION:
            connection.close()
            raise HarnessError("检测到不兼容的 v1 开发态数据库；请移走 .verif-harness 后重新 bootstrap")
        connection.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
        connection.commit()
        return connection

    def read_connect(self) -> sqlite3.Connection:
        self.require()
        connection = sqlite3.connect(f"{self.database.as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def bootstrap(
        self, project_name: str | None = None, runtime: str = "auto",
        rtl_roots: Iterable[str] = (), docs_roots: Iterable[str] = (),
        verif_root: str | None = None, dut_top: str | None = None,
        dut_top_file: str | None = None, refresh: bool = False,
    ) -> dict[str, Any]:
        if self.initialized and not refresh:
            raise HarnessError("项目已经 bootstrap；如需刷新非语义清单，请使用 --refresh")
        if not self.root.is_dir():
            raise HarnessError(f"项目目录不存在: {self.root}")
        previous: dict[str, Any] = {}
        if self.initialized:
            previous = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        inventory = source_inventory(self.root)
        caps = capabilities()
        reasoning = caps["reasoning"]
        detected = [name for name in ("codex", "kimi", "claude") if reasoning[name]["available"]]
        selected = runtime
        if runtime == "auto":
            selected = str(previous.get("runtime") or (detected[0] if len(detected) == 1 else "unselected"))
        rtl_values = [relative_path(self.root, item) for item in rtl_roots] or list(previous.get("rtl_roots", []))
        docs_values = [relative_path(self.root, item) for item in docs_roots] or list(previous.get("docs_roots", []))
        verif_value = relative_path(self.root, verif_root) if verif_root is not None else str(previous.get("verif_root", "."))
        previous_dut = previous.get("dut", {}) if isinstance(previous.get("dut"), dict) else {}
        dut_top = dut_top or previous_dut.get("top_module")
        dut_top_file = dut_top_file or previous_dut.get("top_file")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "project_name": project_name or previous.get("project_name") or self.root.name,
            "project_root": str(self.root), "runtime": selected,
            "baseline_revision": git_revision(self.root), "rtl_roots": rtl_values,
            "docs_roots": docs_values, "verif_root": verif_value,
            "dut": {"top_module": dut_top, "top_file": relative_path(self.root, dut_top_file) if dut_top_file else None},
            "inventory_count": len(inventory), "capabilities": caps, "updated_at": now(),
        }
        atomic_json(self.state / "project.json", manifest)
        atomic_json(self.state / "inventory.json", inventory)
        capability_config = self.root / ".harness-config.json"
        if not capability_config.exists() and rtl_values and dut_top and dut_top_file:
            atomic_json(capability_config, {
                "project_name": manifest["project_name"],
                "rtl": {"root": rtl_values[0], "top_module": dut_top, "top_file": manifest["dut"]["top_file"]},
                "verif": {"root": verif_value, "docs_root": docs_values[0] if docs_values else f"{verif_value.rstrip('/')}/docs",
                          "verification_subdir": "verification", "governance_subdir": "governance"},
            })
        with self.connect() as connection:
            for item in inventory:
                node_type = "implementation" if item["kind"] == "rtl" else item["kind"]
                self.upsert_node(connection, f"file:{item['path']}", node_type, item["path"],
                                 Validity.UNKNOWN, data=item, preserve_status=True)
        self.write_model_projection()
        return manifest

    def upsert_node(
        self, connection: sqlite3.Connection, node_id: str, node_type: str, title: str,
        status: Validity | str = Validity.UNKNOWN, workstream: str | None = None,
        data: dict[str, Any] | None = None, preserve_status: bool = False,
    ) -> None:
        timestamp = now()
        status_update = "nodes.status" if preserve_status else "excluded.status"
        connection.execute(f"""
            INSERT INTO nodes(id,type,title,workstream,status,data_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET type=excluded.type,title=excluded.title,
              workstream=COALESCE(excluded.workstream,nodes.workstream),status={status_update},
              data_json=excluded.data_json,updated_at=excluded.updated_at
        """, (node_id, node_type, title, workstream,
              status.value if isinstance(status, Validity) else status,
              json_text(data or {}), timestamp, timestamp))

    @staticmethod
    def normalize_workstream(value: str) -> str:
        name = value.upper()
        if name not in WORKSTREAM_TEMPLATES:
            raise HarnessError("workstream 必须是 " + ", ".join(WORKSTREAM_TEMPLATES))
        return name

    def planning_context(self, workstream: str) -> dict[str, Any]:
        model = self.model()
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        relevant = [item for item in model["nodes"] if item.get("workstream") in {None, workstream}]
        return {
            "project": manifest["project_name"], "revision": manifest.get("baseline_revision"),
            "dut": manifest.get("dut"), "rtl_roots": manifest.get("rtl_roots", []),
            "docs_roots": manifest.get("docs_roots", []),
            "model_summary": {
                "node_count": len(model["nodes"]), "edge_count": len(model["edges"]),
                "open_findings": sum(item["status"] == "OPEN" for item in model["findings"]),
                "workstream_nodes": sum(item.get("workstream") == workstream for item in model["nodes"]),
            },
            "model_excerpt": {
                "nodes": relevant[:200],
                "relations": model["edges"][:200],
                "open_findings": [item for item in model["findings"] if item["status"] == "OPEN"][:100],
                "truncated": len(relevant) > 200 or len(model["edges"]) > 200,
            },
        }

    def design_workstream(
        self, workstream: str, objective: str | None, desired: list[str],
        exit_criteria: list[str], decisions: list[str],
    ) -> dict[str, Any]:
        self.require()
        name = self.normalize_workstream(workstream)
        template = WORKSTREAM_TEMPLATES[name]
        objective_value = objective.strip() if objective and objective.strip() else template["objective"]
        desired_specs = (
            [(f"custom-{index:03d}", title, "reason") for index, title in enumerate(desired, 1)]
            if desired else list(template["desired"])
        )
        exit_values = exit_criteria or list(template["exit"])
        context = self.planning_context(name)
        with self.connect() as connection:
            observed = connection.execute("SELECT revision FROM workstreams WHERE name=?", (name,)).fetchone()
            revision = int(observed["revision"]) + 1 if observed else 1
            connection.execute("UPDATE nodes SET workstream=NULL,status=?,updated_at=? WHERE workstream=? AND type='desired-state'",
                               (Validity.STALE.value, now(), name))
            desired_rows = []
            for key, title, suggested_mode in desired_specs:
                node_id = f"workstream:{name}:r{revision}:desired:{key}"
                row = {"id": node_id, "key": key, "title": title, "required": True, "suggested_mode": suggested_mode}
                desired_rows.append(row)
                self.upsert_node(connection, node_id, "desired-state", title, Validity.UNKNOWN, name, row)
            connection.execute("""
                INSERT INTO workstreams(name,lifecycle,revision,objective,desired_json,exit_json,decisions_json,context_json,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET lifecycle=excluded.lifecycle,revision=excluded.revision,
                  objective=excluded.objective,desired_json=excluded.desired_json,exit_json=excluded.exit_json,
                  decisions_json=excluded.decisions_json,context_json=excluded.context_json,updated_at=excluded.updated_at
            """, (name, "REVIEW", revision, objective_value, json_text(desired_rows), json_text(exit_values),
                  json_text(decisions), json_text(context), now()))
        self.write_workstream_projection(name)
        result = self.workstream(name)
        result["template"] = {"name": template["name"], "topics": [item[0] for item in template["desired"]]}
        result["decision_log"] = decisions
        result["questions_for_human"] = [
            f"请确认 `{key}`：{title}" for key, title, _mode in desired_specs
        ] if not decisions else []
        result["auto_closure"] = self.evaluate_closure(name)
        return result

    def workstream(self, workstream: str) -> dict[str, Any]:
        name = self.normalize_workstream(workstream)
        self.require()
        with self.read_connect() as connection:
            row = connection.execute("SELECT * FROM workstreams WHERE name=?", (name,)).fetchone()
        if row is None:
            raise HarnessError(f"Workstream {name} 尚未设计")
        return {
            "workstream": name, "display_name": WORKSTREAM_TEMPLATES[name]["name"],
            "lifecycle": row["lifecycle"], "revision": row["revision"], "objective": row["objective"],
            "desired_state": json.loads(row["desired_json"]), "exit_criteria": json.loads(row["exit_json"]),
            "decisions": json.loads(row["decisions_json"]), "planning_context": json.loads(row["context_json"]),
            "updated_at": row["updated_at"],
        }

    def workstreams(self) -> list[dict[str, Any]]:
        self.require()
        with self.read_connect() as connection:
            names = [row["name"] for row in connection.execute("SELECT name FROM workstreams ORDER BY name")]
        return [self.workstream(name) for name in names]

    def review_workstream(self, workstream: str, verdict: str, reviewer: str, reason: str) -> dict[str, Any]:
        plan = self.workstream(workstream)
        lifecycle = {"approve": "ACTIVE", "reject": "REVISE", "modify": "REVISE", "clarify": "REVISE"}[verdict]
        with self.connect() as connection:
            review_id = uuid.uuid4().hex
            connection.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?)",
                               (review_id, plan["workstream"], plan["revision"], verdict.upper(), reviewer, reason, now()))
            connection.execute("UPDATE workstreams SET lifecycle=?,updated_at=? WHERE name=?",
                               (lifecycle, now(), plan["workstream"]))
        self.write_workstream_projection(plan["workstream"])
        result = {"review_id": review_id, "workstream": plan["workstream"], "revision": plan["revision"],
                  "verdict": verdict.upper(), "lifecycle": lifecycle}
        result["auto_closure"] = self.evaluate_closure(plan["workstream"])
        return result

    def _baseline_payload(self, workstream: str, reviewer: str, reason: str) -> dict[str, Any]:
        plan = self.workstream(workstream)
        model = self.model()
        return {
            "schema": "WorkstreamBaseline/1", "created_at": now(), "project_revision": git_revision(self.root),
            "reviewer": reviewer, "reason": reason, "plan": plan,
            "nodes": [node for node in model["nodes"] if node.get("workstream") == workstream],
            "edges": [edge for edge in model["edges"] if any(
                node["id"] in {edge["source"], edge["target"]} for node in model["nodes"] if node.get("workstream") == workstream
            )],
            "findings": [finding for finding in model["findings"] if any(
                node["id"] == finding["subject"] for node in model["nodes"] if node.get("workstream") == workstream
            )],
            "evidence": [item for item in model["evidence"] if any(
                node["id"] == item["subject"] for node in model["nodes"] if node.get("workstream") == workstream
            )],
        }

    def freeze_workstream(self, workstream: str, reviewer: str, reason: str) -> dict[str, Any]:
        name = self.normalize_workstream(workstream)
        closure = self.evaluate_closure(name, persist=False)
        plan = self.workstream(name)
        if plan["lifecycle"] not in {"ACTIVE", "SATISFIED"}:
            raise HarnessError("Workstream 必须先由 Human approve，才能 freeze")
        if closure["actions"]:
            raise HarnessError("Workstream desired state 尚未满足；先处理 closure actions")
        payload = self._baseline_payload(name, reviewer, reason)
        canonical = json_text(payload).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        baseline_id = f"{name.lower()}-r{plan['revision']}-{digest[:12]}"
        relative = Path("baselines") / name.lower() / baseline_id / "manifest.json"
        target = self.state / relative
        if target.exists():
            raise HarnessError(f"不可变 baseline 已存在: {relative}")
        atomic_json(target, payload)
        with self.connect() as connection:
            connection.execute("UPDATE workstreams SET lifecycle='BASELINED',updated_at=? WHERE name=?", (now(), name))
            connection.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?)",
                               (uuid.uuid4().hex, name, plan["revision"], "FREEZE", reviewer, reason, now()))
            connection.execute("INSERT INTO baselines VALUES(?,?,?,?,?,?,?,?,?)",
                               (baseline_id, name, plan["revision"], "WORKSTREAM", digest, relative.as_posix(), reviewer, reason, now()))
        self.write_workstream_projection(name)
        return {"workstream": name, "lifecycle": "BASELINED", "revision": plan["revision"],
                "baseline_id": baseline_id, "digest": digest, "path": relative.as_posix()}

    def freeze_final(self, reviewer: str, reason: str) -> dict[str, Any]:
        plans = self.workstreams()
        present = {item["workstream"] for item in plans}
        missing = sorted(set(WORKSTREAM_TEMPLATES) - present)
        not_ready = [item["workstream"] for item in plans if item["lifecycle"] != "BASELINED"]
        audit = self.audit()
        if missing or not_ready or audit["open_findings"] or audit["missing_files"]:
            raise HarnessError(f"final freeze 未满足: missing={missing}, not_baselined={not_ready}, audit={audit}")
        with self.read_connect() as connection:
            recorded_baselines = [dict(row) for row in connection.execute("SELECT * FROM baselines ORDER BY created_at")]
        payload = {
            "schema": "FinalBaseline/1", "created_at": now(), "project_revision": git_revision(self.root),
            "reviewer": reviewer, "reason": reason, "project": json.loads((self.state / "project.json").read_text(encoding="utf-8")),
            "workstreams": plans,
            "baselines": recorded_baselines,
        }
        digest = hashlib.sha256(json_text(payload).encode("utf-8")).hexdigest()
        baseline_id = f"final-{digest[:12]}"
        relative = Path("baselines") / "final" / baseline_id / "manifest.json"
        target = self.state / relative
        if target.exists():
            raise HarnessError(f"不可变 final baseline 已存在: {relative}")
        atomic_json(target, payload)
        with self.connect() as connection:
            connection.execute("INSERT INTO baselines VALUES(?,?,?,?,?,?,?,?,?)",
                               (baseline_id, None, None, "FINAL", digest, relative.as_posix(), reviewer, reason, now()))
        return {"baseline_id": baseline_id, "kind": "FINAL", "digest": digest, "path": relative.as_posix()}

    def add_node(self, node_id: str, node_type: str, title: str, workstream: str | None = None,
                 status: Validity = Validity.UNKNOWN) -> dict[str, Any]:
        self.require()
        if not node_id.strip() or any(character.isspace() for character in node_id):
            raise HarnessError("node ID 不能为空或包含空白")
        if status in {Validity.VALID, Validity.WAIVED}:
            raise HarnessError("新 node 不能直接声明 VALID/WAIVED；必须提供 evidence 或 Human waiver")
        name = self.normalize_workstream(workstream) if workstream else None
        with self.connect() as connection:
            if connection.execute("SELECT 1 FROM nodes WHERE id=?", (node_id,)).fetchone() is not None:
                raise HarnessError(f"node 已存在: {node_id}")
            self.upsert_node(connection, node_id, node_type, title, status, name)
        self.write_model_projection()
        return {"id": node_id, "type": node_type, "title": title, "workstream": name, "status": status.value,
                "auto_closure": self.reconcile()}

    def add_edge(self, source: str, target: str, relation: str, origin: str, confidence: float) -> dict[str, Any]:
        self.require()
        if not 0 <= confidence <= 1:
            raise HarnessError("confidence 必须在 0 到 1 之间")
        with self.connect() as connection:
            known = {row["id"] for row in connection.execute("SELECT id FROM nodes WHERE id IN (?,?)", (source, target))}
            missing = [item for item in (source, target) if item not in known]
            if missing:
                raise HarnessError("未知 node: " + ", ".join(missing))
            connection.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
                               (source, target, relation.upper(), origin, confidence, "{}", now()))
        self.write_model_projection()
        return {"source": source, "target": target, "relation": relation.upper(), "origin": origin,
                "confidence": confidence, "auto_closure": self.reconcile()}

    def set_status(self, node_id: str, status: Validity) -> dict[str, Any]:
        self.require()
        if status in {Validity.VALID, Validity.WAIVED}:
            raise HarnessError("VALID 必须由 evidence 建立，WAIVED 必须由 Human review 建立")
        with self.connect() as connection:
            changed = connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?", (status.value, now(), node_id))
            if changed.rowcount != 1:
                raise HarnessError(f"未知 node: {node_id}")
        self.write_model_projection()
        return {"id": node_id, "status": status.value, "auto_closure": self.reconcile()}

    def waive_node(self, node_id: str, reviewer: str, reason: str) -> dict[str, Any]:
        self.require()
        with self.connect() as connection:
            node = connection.execute("SELECT workstream FROM nodes WHERE id=?", (node_id,)).fetchone()
            if node is None:
                raise HarnessError(f"未知 node: {node_id}")
            if node["workstream"] is None:
                raise HarnessError("waiver 只允许用于已规划 Workstream 中的 node")
            name = node["workstream"]
            plan = connection.execute("SELECT revision FROM workstreams WHERE name=?", (name,)).fetchone()
            review_id = uuid.uuid4().hex
            connection.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?)",
                               (review_id, name, int(plan["revision"]), "WAIVE", reviewer, f"{node_id}: {reason}", now()))
            connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?", (Validity.WAIVED.value, now(), node_id))
            connection.execute("UPDATE findings SET status='WAIVED' WHERE subject=? AND status='OPEN'", (node_id,))
        self.write_model_projection()
        self.write_workstream_projection(name)
        return {"review_id": review_id, "id": node_id, "status": Validity.WAIVED.value,
                "reviewer": reviewer, "reason": reason, "auto_closure": self.reconcile()}

    def add_evidence(self, subject: str, kind: str, source: str, verdict: str) -> dict[str, Any]:
        self.require()
        source_path = Path(source)
        if not source_path.is_absolute():
            source_path = self.root / source_path
        if not source_path.is_file():
            raise HarnessError(f"evidence source 不存在或不是文件: {source}")
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        evidence_id = f"evidence:{uuid.uuid4().hex[:12]}"
        with self.connect() as connection:
            if connection.execute("SELECT 1 FROM nodes WHERE id=?", (subject,)).fetchone() is None:
                raise HarnessError(f"未知 evidence subject: {subject}")
            connection.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?)",
                               (evidence_id, subject, kind, relative_path(self.root, source_path), digest, verdict.upper(), "{}", now()))
            self.upsert_node(connection, evidence_id, "evidence", relative_path(self.root, source_path),
                             Validity.VALID if verdict == "pass" else Validity.INVALID)
            connection.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
                               (subject, evidence_id, "VALIDATED_BY", "runtime", 1.0, "{}", now()))
            connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                               (Validity.VALID.value if verdict == "pass" else Validity.INVALID.value, now(), subject))
            if verdict == "pass":
                connection.execute("UPDATE findings SET status='RESOLVED' WHERE subject=? AND status='OPEN'", (subject,))
        self.write_model_projection()
        return {"id": evidence_id, "subject": subject, "kind": kind, "source": relative_path(self.root, source_path),
                "digest": digest, "verdict": verdict.upper(), "auto_closure": self.reconcile()}

    def record_change(self, path: str, kind: str, revision: str | None = None) -> dict[str, Any]:
        self.require()
        relative = relative_path(self.root, path)
        subject = f"file:{relative}"
        event_id = f"event:{uuid.uuid4().hex[:12]}"
        initial = Validity.INVALID if kind == "delete" else Validity.STALE
        affected: list[str] = []
        with self.connect() as connection:
            if connection.execute("SELECT 1 FROM nodes WHERE id=?", (subject,)).fetchone() is None:
                self.upsert_node(connection, subject, "artifact", relative, initial)
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",
                               (event_id, kind, subject, revision, json_text({"path": relative}), now()))
            queue = [subject]
            visited: set[str] = set()
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                affected.append(current)
                queue.extend(row["target"] for row in connection.execute("SELECT target FROM edges WHERE source=?", (current,)))
            for index, node_id in enumerate(affected):
                status = initial if index == 0 else Validity.REVALIDATION_REQUIRED
                connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?", (status.value, now(), node_id))
                connection.execute("INSERT INTO findings VALUES(?,?,?,?,?,?,?)",
                                   (f"finding:{uuid.uuid4().hex[:12]}", node_id, "HIGH" if index == 0 else "MEDIUM",
                                    "OPEN", event_id, f"{relative} 的 {kind} 事件使该节点需要重新验证", now()))
            names = {row["workstream"] for row in connection.execute(
                "SELECT DISTINCT workstream FROM nodes WHERE id IN (%s) AND workstream IS NOT NULL" % ",".join("?" * len(affected)), affected
            )} if affected else set()
            for name in names:
                connection.execute("UPDATE workstreams SET lifecycle='PARTIALLY_STALE',updated_at=? WHERE name=? AND lifecycle IN ('ACTIVE','SATISFIED','BASELINED')",
                                   (now(), name))
        self.write_model_projection()
        for name in names:
            self.write_workstream_projection(name)
        return {"event_id": event_id, "kind": kind, "subject": subject, "revision": revision,
                "affected": affected, "auto_closure": self.reconcile()}

    def scan(self) -> dict[str, Any]:
        self.require()
        missing: list[str] = []
        with self.connect() as connection:
            for row in connection.execute("SELECT id FROM nodes WHERE id LIKE 'file:%'"):
                relative = row["id"][5:]
                if relative != "." and not (self.root / relative).exists():
                    missing.append(row["id"])
                    connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?", (Validity.INVALID.value, now(), row["id"]))
            open_findings = connection.execute("SELECT COUNT(*) count FROM findings WHERE status='OPEN'").fetchone()["count"]
        self.write_model_projection()
        return {"missing_files": missing, "open_findings": open_findings, "status": "FAIL" if missing else "PASS",
                "auto_closure": self.reconcile()}

    def audit(self) -> dict[str, Any]:
        self.require()
        missing: list[str] = []
        with self.read_connect() as connection:
            for row in connection.execute("SELECT id FROM nodes WHERE id LIKE 'file:%'"):
                relative = row["id"][5:]
                if relative != "." and not (self.root / relative).exists():
                    missing.append(row["id"])
            open_findings = connection.execute("SELECT COUNT(*) count FROM findings WHERE status='OPEN'").fetchone()["count"]
        return {"missing_files": missing, "open_findings": open_findings, "status": "FAIL" if missing else "PASS"}

    def evaluate_closure(self, workstream: str, persist: bool = True) -> dict[str, Any]:
        name = self.normalize_workstream(workstream)
        plan = self.workstream(name)
        actions: list[dict[str, Any]] = []
        connector = self.connect if persist else self.read_connect
        with connector() as connection:
            for desired in plan["desired_state"]:
                row = connection.execute("SELECT status FROM nodes WHERE id=?", (desired["id"],)).fetchone()
                status = row["status"] if row else Validity.UNKNOWN.value
                if desired.get("required", True) and status not in {Validity.VALID.value, Validity.WAIVED.value}:
                    if status in {Validity.STALE.value, Validity.REVALIDATION_REQUIRED.value}:
                        kind, executor = "REVALIDATE", "deterministic"
                    elif status in {Validity.INVALID.value, Validity.BLOCKED.value}:
                        kind, executor = "REPAIR_OR_REPLAN", "reasoning"
                    else:
                        kind, executor = "SATISFY_DESIRED_STATE", "reasoning"
                    actions.append({"kind": kind, "target": desired["id"], "priority": 10, "executor": executor,
                                    "suggested_mode": desired.get("suggested_mode"), "reason": f"required desired-state 当前为 {status}"})
            for row in connection.execute("SELECT subject,severity,details FROM findings WHERE status='OPEN' AND subject IN (SELECT id FROM nodes WHERE workstream=?)", (name,)):
                actions.append({"kind": "RESOLVE_FINDING", "target": row["subject"], "priority": 5,
                                "executor": "reasoning", "suggested_mode": "reason", "reason": row["details"]})
            if plan["lifecycle"] in {"REVIEW", "REVISE"}:
                actions.append({"kind": "HUMAN_REVIEW", "target": f"workstream:{name}", "priority": 1,
                                "executor": "human", "suggested_mode": "plan", "reason": f"lifecycle 为 {plan['lifecycle']}"})
            actions.sort(key=lambda item: (item["priority"], item["target"], item["kind"]))
            for action in actions:
                stable = json_text({"workstream": name, **action})
                action["id"] = "action:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:12]
            lifecycle = plan["lifecycle"]
            if persist:
                connection.execute("DELETE FROM actions WHERE workstream=? AND status='OPEN'", (name,))
                for action in actions:
                    connection.execute("INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?,?)",
                                       (action["id"], name, action["kind"], action["target"], action["priority"], "OPEN",
                                        action["executor"], action["suggested_mode"], action["reason"], now()))
                if not actions and lifecycle in {"ACTIVE", "PARTIALLY_STALE"}:
                    lifecycle = "SATISFIED"
                    connection.execute("UPDATE workstreams SET lifecycle='SATISFIED',updated_at=? WHERE name=?", (now(), name))
        if persist:
            self.write_workstream_projection(name)
        return {"workstream": name, "ready": not actions, "lifecycle": lifecycle, "actions": actions}

    def reconcile(self) -> dict[str, Any]:
        closures = [self.evaluate_closure(item["workstream"]) for item in self.workstreams()]
        ranked = [
            {"workstream": closure["workstream"], **action}
            for closure in closures for action in closure["actions"]
        ]
        ranked.sort(key=lambda item: (item["priority"], item["workstream"], item["target"]))
        return {"workstreams": closures, "ranked_actions": ranked}

    def model(self, node_id: str | None = None) -> dict[str, Any]:
        self.require()
        with self.read_connect() as connection:
            suffix, params = ("", ()) if node_id is None else (" WHERE id=?", (node_id,))
            nodes = [dict(row) for row in connection.execute("SELECT id,type,title,workstream,status,updated_at FROM nodes" + suffix + " ORDER BY id", params)]
            if node_id is not None and not nodes:
                raise HarnessError(f"未知 node: {node_id}")
            if node_id is None:
                edges = [dict(row) for row in connection.execute("SELECT source,target,relation,origin,confidence FROM edges ORDER BY source,target,relation")]
                findings = [dict(row) for row in connection.execute("SELECT id,subject,severity,status,cause_event,details FROM findings ORDER BY created_at")]
                evidence = [dict(row) for row in connection.execute("SELECT id,subject,kind,source,digest,verdict,created_at FROM evidence ORDER BY created_at")]
            else:
                edges = [dict(row) for row in connection.execute("SELECT source,target,relation,origin,confidence FROM edges WHERE source=? OR target=? ORDER BY source,target,relation", (node_id, node_id))]
                findings = [dict(row) for row in connection.execute("SELECT id,subject,severity,status,cause_event,details FROM findings WHERE subject=? ORDER BY created_at", (node_id,))]
                evidence = [dict(row) for row in connection.execute("SELECT id,subject,kind,source,digest,verdict,created_at FROM evidence WHERE subject=? ORDER BY created_at", (node_id,))]
        return {"schema_version": SCHEMA_VERSION, "nodes": nodes, "edges": edges, "findings": findings, "evidence": evidence}

    def trace(self, node_id: str) -> dict[str, Any]:
        model = self.model(node_id)
        return {"node": model["nodes"][0], "incoming": [e for e in model["edges"] if e["target"] == node_id],
                "outgoing": [e for e in model["edges"] if e["source"] == node_id],
                "findings": model["findings"], "evidence": model["evidence"]}

    def impact(self, node_id: str) -> dict[str, Any]:
        self.model(node_id)
        with self.read_connect() as connection:
            queue: list[tuple[str, int]] = [(node_id, 0)]
            visited: set[str] = set()
            affected: list[dict[str, Any]] = []
            while queue:
                current, depth = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                if current != node_id:
                    row = connection.execute("SELECT id,type,title,workstream,status FROM nodes WHERE id=?", (current,)).fetchone()
                    if row:
                        item = dict(row); item["depth"] = depth; affected.append(item)
                queue.extend((row["target"], depth + 1) for row in connection.execute("SELECT target FROM edges WHERE source=? ORDER BY target", (current,)))
        return {"source": node_id, "affected": affected}

    def status(self) -> dict[str, Any]:
        self.require()
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        model = self.model()
        counts: dict[str, int] = {}
        for node in model["nodes"]:
            counts[node["status"]] = counts.get(node["status"], 0) + 1
        plans = self.workstreams()
        return {
            "project": manifest["project_name"], "baseline_revision": manifest.get("baseline_revision"),
            "runtime": manifest.get("runtime"), "lifecycle": "ACTIVE",
            "workstreams": plans, "closures": [self.evaluate_closure(item["workstream"], persist=False) for item in plans],
            "node_status": counts, "open_findings": sum(item["status"] == "OPEN" for item in model["findings"]),
        }

    def write_model_projection(self) -> None:
        if not self.initialized:
            return
        model = self.model()
        lines = ["# Verification Knowledge Model", "", "> Verification Knowledge Model 生成的只读投影；SQLite 是机器事实源。", "", "## Nodes", ""]
        lines.extend(f"- `{item['id']}` · {item['type']} · **{item['status']}** · {item['title']}" for item in model["nodes"])
        if not model["nodes"]: lines.append("- 无")
        lines.extend(["", "## Relations", ""])
        lines.extend(f"- `{item['source']}` -[{item['relation']}]-> `{item['target']}` ({item['origin']}, {item['confidence']:.2f})" for item in model["edges"])
        if not model["edges"]: lines.append("- 无")
        lines.extend(["", "## Open Findings", ""])
        open_findings = [item for item in model["findings"] if item["status"] == "OPEN"]
        lines.extend(f"- **{item['severity']}** `{item['subject']}`：{item['details']}" for item in open_findings)
        if not open_findings: lines.append("- 无")
        (self.state / "model.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_workstream_projection(self, workstream: str) -> None:
        plan = self.workstream(workstream)
        directory = self.state / "workstreams" / plan["workstream"].lower()
        directory.mkdir(parents=True, exist_ok=True)
        atomic_json(directory / "desired-state.json", plan)
        lines = [f"# {plan['workstream']} · {plan['display_name']}", "",
                 "> Verification Planner 阅读投影；请通过结构化 CLI 记录修改。", "",
                 f"- 生命周期：**{plan['lifecycle']}**", f"- 修订：**{plan['revision']}**",
                 f"- 目标：{plan['objective']}", "", "## Current Verification Knowledge Model Context", "",
                 f"- Project: `{plan['planning_context']['project']}`",
                 f"- Model nodes: {plan['planning_context']['model_summary']['node_count']}",
                 f"- Open findings: {plan['planning_context']['model_summary']['open_findings']}",
                 "", "## Desired State", ""]
        lines.extend(f"- [ ] `{item['key']}` {item['title']}" for item in plan["desired_state"])
        lines.extend(["", "## Exit Criteria", ""])
        lines.extend(f"- [ ] {item}" for item in plan["exit_criteria"])
        lines.extend(["", "## Human Decisions", ""])
        lines.extend(f"- {item}" for item in plan["decisions"])
        if not plan["decisions"]: lines.append("- 无")
        (directory / "plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
