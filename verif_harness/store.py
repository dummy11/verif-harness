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
DOCUMENT_ITEM_KINDS = {
    "human-decision", "provisional", "assumption", "external-open-question",
}
DOCUMENT_ITEM_STATUSES = {"PENDING", "ACTIVE", "RESOLVED", "SUPERSEDED"}
AGENTS_MANAGED_BEGIN = "<!-- BEGIN verif-harness managed project instructions -->"
AGENTS_MANAGED_END = "<!-- END verif-harness managed project instructions -->"


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
VDOC_DOCUMENTS = {
    "verification-workflow": ("verification_workflow.md", "文档治理、评审、决策和变更失效机制已定义并评审", ["VDOC"]),
    "verification-plan": ("verification_plan.md", "验证范围、策略、风险和验收条件已定义并评审", ["VDOC"]),
    "feature-matrix": ("feature_matrix.md", "验证点、来源及检查/覆盖/用例映射可追溯", ["VDOC", "VSTIM", "VCHK", "VCOV", "VCASE", "VREG"]),
    "tb-architecture": ("tb_architecture.md", "验证组件职责、接口、数据流和构建边界已定义", ["VDOC", "VSTIM", "VCHK", "VREG"]),
    "reference-model": ("reference_model_spec.md", "参考模型适用性、接入与比较合同或替代检查策略已评审", ["VDOC", "VCHK"]),
    "coverage-plan": ("coverage_plan.md", "覆盖目标、采样语义、映射和补洞规则已评审", ["VDOC", "VCOV"]),
    "assertion-plan": ("assertion_plan.md", "断言性质、挂接和非空洞验证要求已评审", ["VDOC", "VCHK", "VCOV"]),
    "testcase-list": ("testcase_list.md", "用例目标、场景、检查方法和执行映射已定义", ["VDOC", "VCASE", "VREG"]),
}


def vdoc_document_contract(key: str) -> dict[str, Any]:
    filename, _title, workstreams = VDOC_DOCUMENTS[key]
    return {"filename": filename, "template": f"assets/vdoc/{filename}",
            "maintained_by": workstreams, "completion": "reviewed-content-not-file-existence"}


WORKSTREAM_TEMPLATES: dict[str, dict[str, Any]] = {
    "VDOC": {
        "name": "Verification Documentation",
        "objective": "形成并持续维护可评审的验证定义、架构、策略和退出标准",
        "desired": [(key, value[1], "plan") for key, value in VDOC_DOCUMENTS.items()],
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


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def default_vdoc_document_root(manifest: dict[str, Any]) -> str:
    verif_root = str(manifest.get("verif_root") or ".").rstrip("/")
    return "docs/verification" if verif_root in {"", "."} else f"{verif_root}/docs/verification"


def project_agents_block(manifest: dict[str, Any], document_root: str | None = None) -> str:
    rtl_roots = manifest.get("rtl_roots") or []
    docs_roots = manifest.get("docs_roots") or []
    dut = manifest.get("dut") if isinstance(manifest.get("dut"), dict) else {}
    lines = [
        AGENTS_MANAGED_BEGIN,
        "## verif-harness 项目合同（受管）",
        "",
        "本区块由 verif-harness 维护。项目自有说明必须保留在 markers 之外；",
        "仅通过 bootstrap 或 VDOC planning 刷新本区块。",
        "",
        "### 项目标识与边界",
        "",
        f"- 项目：`{manifest.get('project_name') or 'unknown'}`",
        f"- RTL roots（只读，可位于项目外）：{', '.join(f'`{item}`' for item in rtl_roots) or '`未记录`'}",
        f"- DUT top: `{dut.get('top_module') or 'not recorded'}`",
        f"- DUT top file（只读）：`{dut.get('top_file') or 'not recorded'}`",
        f"- RTL specification 输入（只读，可位于项目外）：{', '.join(f'`{item}`' for item in docs_roots) or '`未提供`'}",
        f"- Verification 输出根目录：`{manifest.get('verif_root') or '.'}`",
        "- 治理状态事实源：`.verif-harness/model.sqlite3`",
        "",
        "工程语义以列出的 Markdown 合同为准；SQLite 保存文档摘要、revision、review、",
        "evidence、开放事项状态和失效关系，不保存或覆盖工程语义正文。",
        "所有 RTL 和 RTL specification 都是只读输入。禁止编辑、创建、覆盖、删除、",
        "重命名、格式化这些输入，也禁止向其中生成文件。验证产物必须放在 verification",
        "输出根目录；发现输入缺陷时交由 Human 处理。",
        "",
        "### 交互与权限",
        "",
        "- Human 在 Agent 对话中说明目标、回答工程问题，并明确决定 review、waiver、",
        "  freeze 等 gate。",
        "- Agent 在对话后自行调用 verif-harness CLI；CLI 默认值不构成 Human 授权。",
        "- 生成文件只是 review candidate。文件存在、模板已复制或 Agent 自检通过，",
        "  都不等于语义已批准或 evidence 已通过。",
        "- capability 写入验证资产前，必须读取本文件，执行 `docs sync`，查询当前",
        "  `status`/`closure`，并读取下列与当前动作相关且已经评审的合同。",
        "- 文档状态、Revision Log、Review Trace 与 Human Review Notes 通过 `docs status`",
        "  或 `docs render` 按需投影，不在工程语义正文中手工维护。",
        "- 所需合同缺失或未解决时，返回 VDOC 或负责该目标的 Workstream；不得猜测后继续。",
        "- 本项目不采用 Stage 或 Spec Kit；不得创建 `spec/plan/tasks` 流水线或按阶段阻塞工作域。",
        "",
        "### 必读上下文路由",
        "",
    ]
    if document_root is None:
        lines.extend([
            "VDOC 文档路由尚未建立。执行实现类 capability 前，必须通过 `plan VDOC`",
            "生成缺失模板，并由 Agent 与 Human 对话形成经过评审的工程语义文档集。",
        ])
    else:
        lines.append(f"VDOC 文档根目录：`{document_root}`")
        lines.append("")
        for filename, _title, workstreams in VDOC_DOCUMENTS.values():
            owners = ", ".join(workstreams)
            lines.append(f"- `{document_root}/{filename}` — 维护者：{owners}")
        lines.extend([
            "",
            "只读取当前动作需要的合同。列出的文档尚不存在或未经评审时，将依赖视为",
            "pending 并返回 VDOC/closure，不得虚构项目语义。",
        ])
    lines.extend(["", AGENTS_MANAGED_END])
    return "\n".join(lines)


def update_project_agents(path: Path, block: str) -> None:
    if path.is_symlink():
        raise HarnessError(f"拒绝跟随项目指令符号链接: {path}")
    if path.exists() and not path.is_file():
        raise HarnessError(f"项目指令路径不是普通文件: {path}")
    source = path.read_text(encoding="utf-8") if path.exists() else ""
    begin_count = source.count(AGENTS_MANAGED_BEGIN)
    end_count = source.count(AGENTS_MANAGED_END)
    if (begin_count != end_count or begin_count > 1
            or (begin_count == 1 and source.find(AGENTS_MANAGED_BEGIN) > source.find(AGENTS_MANAGED_END))):
        raise HarnessError(f"AGENTS.md 中的 verif-harness managed block 损坏: {path}")
    if begin_count == 1:
        prefix, remainder = source.split(AGENTS_MANAGED_BEGIN, 1)
        _managed, suffix = remainder.split(AGENTS_MANAGED_END, 1)
        rendered = f"{prefix}{block}{suffix}"
    else:
        separator = "\n\n" if source and not source.endswith("\n\n") else ""
        rendered = f"{source}{separator}{block}\n"
    atomic_text(path, rendered)


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


def input_path(root: Path, value: str | Path) -> str:
    """Keep project-local inputs relative and explicit external inputs absolute."""
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix() or "."
    except ValueError:
        return str(resolved)


def resolved_path(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def path_is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def source_inventory(
    root: Path, additional_inputs: Iterable[str] = (), limit: int = 10000,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    visited: set[Path] = set()
    roots: list[Path] = []
    seen_roots: set[Path] = set()
    for value in additional_inputs:
        source = resolved_path(root, value)
        if source not in seen_roots:
            roots.append(source)
            seen_roots.add(source)
    if root.resolve() not in seen_roots:
        roots.append(root.resolve())
    for source in roots:
        candidates = [source] if source.is_file() else sorted(source.rglob("*"))
        for path in candidates:
            canonical = path.resolve()
            if canonical in visited or path.is_symlink() or not path.is_file():
                continue
            visited.add(canonical)
            relative_to_source = Path(path.name) if source.is_file() else path.relative_to(source)
            if any(part in IGNORED_PARTS for part in relative_to_source.parts):
                continue
            suffix = path.suffix.lower()
            if suffix not in RTL_SUFFIXES | DOC_SUFFIXES | {".json", ".yaml", ".yml", ".toml", ".f"}:
                continue
            stat = path.stat()
            kind = "rtl" if suffix in RTL_SUFFIXES else "document" if suffix in DOC_SUFFIXES else "metadata"
            rows.append({"path": input_path(root, path), "kind": kind, "size": stat.st_size})
            if len(rows) >= limit:
                return rows
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
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, title TEXT NOT NULL, workstream TEXT NOT NULL,
  desired_id TEXT, owner TEXT NOT NULL, semantic_revision INTEGER NOT NULL, digest TEXT NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_revisions (
  document_id TEXT NOT NULL, semantic_revision INTEGER NOT NULL, digest TEXT NOT NULL,
  summary TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (document_id, semantic_revision)
);
CREATE TABLE IF NOT EXISTS document_reviews (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, semantic_revision INTEGER NOT NULL,
  verdict TEXT NOT NULL, reviewer TEXT NOT NULL, notes TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_items (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
  anchor TEXT, status TEXT NOT NULL, owner TEXT, review_trigger TEXT,
  affects_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
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
        caps = capabilities()
        reasoning = caps["reasoning"]
        detected = [name for name in ("codex", "kimi", "claude") if reasoning[name]["available"]]
        selected = runtime
        if runtime == "auto":
            selected = str(previous.get("runtime") or (detected[0] if len(detected) == 1 else "unselected"))
        rtl_values = [input_path(self.root, item) for item in rtl_roots] or list(previous.get("rtl_roots", []))
        docs_values = [input_path(self.root, item) for item in docs_roots] or list(previous.get("docs_roots", []))
        verif_value = relative_path(self.root, verif_root) if verif_root is not None else str(previous.get("verif_root", "."))
        previous_dut = previous.get("dut", {}) if isinstance(previous.get("dut"), dict) else {}
        dut_top = dut_top or previous_dut.get("top_module")
        dut_top_file = dut_top_file or previous_dut.get("top_file")
        if not rtl_values or not dut_top or not dut_top_file:
            raise HarnessError("bootstrap 必须明确提供 rtl root、dut top 和 dut top file")
        for value in rtl_values:
            if not resolved_path(self.root, value).is_dir():
                raise HarnessError(f"RTL root 不是目录: {value}")
        top_file_value = input_path(self.root, dut_top_file)
        top_file_path = resolved_path(self.root, top_file_value)
        if not top_file_path.is_file():
            raise HarnessError(f"DUT top file 不是文件: {top_file_value}")
        if not any(path_is_within(top_file_path, resolved_path(self.root, value)) for value in rtl_values):
            raise HarnessError("DUT top file 必须位于某个已声明的 RTL root 内")
        for value in docs_values:
            if not resolved_path(self.root, value).exists():
                raise HarnessError(f"RTL specification 输入不存在: {value}")
        vdoc_document_root = previous.get("vdoc_document_root")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "project_name": project_name or previous.get("project_name") or self.root.name,
            "project_root": str(self.root), "runtime": selected,
            "baseline_revision": git_revision(self.root), "rtl_roots": rtl_values,
            "docs_roots": docs_values, "verif_root": verif_value,
            "dut": {"top_module": dut_top, "top_file": top_file_value},
            "vdoc_document_root": vdoc_document_root,
            "project_instructions": {"path": "AGENTS.md", "managed_by": ["bootstrap", "VDOC"]},
            "inventory_count": 0, "capabilities": caps, "updated_at": now(),
        }
        update_project_agents(self.root / "AGENTS.md", project_agents_block(manifest, vdoc_document_root))
        capability_config = self.root / ".harness-config.json"
        if not capability_config.exists():
            docs_output = "docs" if verif_value in {"", "."} else f"{verif_value.rstrip('/')}/docs"
            atomic_json(capability_config, {
                "project_name": manifest["project_name"],
                "rtl": {"root": rtl_values[0], "top_module": dut_top, "top_file": manifest["dut"]["top_file"]},
                "verif": {"root": verif_value, "docs_root": docs_output,
                          "verification_subdir": "verification", "governance_subdir": "governance"},
            })
        inventory = source_inventory(self.root, [*rtl_values, *docs_values])
        manifest["inventory_count"] = len(inventory)
        atomic_json(self.state / "project.json", manifest)
        atomic_json(self.state / "inventory.json", inventory)
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

    def _document_path_allowed(self, relative: str) -> None:
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        target = (self.root / relative).resolve()
        for value in [*manifest.get("rtl_roots", []), *manifest.get("docs_roots", [])]:
            source = resolved_path(self.root, value)
            if source.is_dir() and (target == source or source in target.parents):
                raise HarnessError(f"文档输出不得位于只读 RTL/spec 输入内: {relative}")
            if source.is_file() and target == source:
                raise HarnessError(f"文档输出与只读 RTL/spec 输入冲突: {relative}")

    def _project_or_declared_input_path(self, value: str | Path) -> str:
        candidate = resolved_path(self.root, value)
        if path_is_within(candidate, self.root):
            return candidate.relative_to(self.root).as_posix() or "."
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        declared = [*manifest.get("rtl_roots", []), *manifest.get("docs_roots", [])]
        if any(path_is_within(candidate, resolved_path(self.root, item)) for item in declared):
            return str(candidate)
        raise HarnessError(f"项目外路径必须位于已声明的只读 RTL/spec 输入内: {value}")

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _register_document(
        self, connection: sqlite3.Connection, document_id: str, relative: str,
        title: str, desired_id: str | None, owner: str, summary: str,
    ) -> tuple[bool, dict[str, Any]]:
        path = self.root / relative
        if path.is_symlink():
            raise HarnessError(f"拒绝跟随语义文档符号链接: {relative}")
        if not path.is_file():
            raise HarnessError(f"语义文档不存在或不是文件: {relative}")
        digest = self._digest(path)
        existing = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        changed = existing is not None and existing["digest"] != digest
        revision = int(existing["semantic_revision"]) + 1 if changed else int(existing["semantic_revision"]) if existing else 1
        status = Validity.REVIEW_REQUIRED.value if existing is None or changed else existing["status"]
        timestamp = now()
        if existing is None:
            connection.execute(
                "INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (document_id, relative, title, "VDOC", desired_id, owner, revision, digest,
                 status, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO document_revisions VALUES(?,?,?,?,?)",
                (document_id, revision, digest, summary, timestamp),
            )
        else:
            connection.execute(
                "UPDATE documents SET path=?,title=?,desired_id=?,owner=?,semantic_revision=?,digest=?,status=?,updated_at=? WHERE id=?",
                (relative, title, desired_id, owner, revision, digest, status, timestamp, document_id),
            )
            if changed:
                connection.execute(
                    "INSERT INTO document_revisions VALUES(?,?,?,?,?)",
                    (document_id, revision, digest, summary, timestamp),
                )
        data = {
            "path": relative, "digest": digest, "semantic_revision": revision,
            "desired_id": desired_id, "owner": owner,
        }
        self.upsert_node(connection, f"file:{relative}", "artifact", relative,
                         Validity.UNKNOWN, data={"path": relative, "kind": "document"}, preserve_status=True)
        self.upsert_node(connection, document_id, "semantic-document", title, status, "VDOC", data)
        connection.execute(
            "INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
            (f"file:{relative}", document_id, "REPRESENTS", "runtime", 1.0, "{}", timestamp),
        )
        if desired_id:
            connection.execute(
                "INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)",
                (document_id, desired_id, "AFFECTS", "runtime", 1.0, "{}", timestamp),
            )
        return changed, {"id": document_id, "path": relative, "semantic_revision": revision,
                         "digest": digest, "status": status, "created": existing is None}

    def _materialize_vdoc_documents(self, desired_rows: list[dict[str, Any]], document_root: str) -> list[dict[str, Any]]:
        output = self.root / document_root
        output.mkdir(parents=True, exist_ok=True)
        changed_paths: list[tuple[str, int]] = []
        results: list[dict[str, Any]] = []
        skill_root = Path(__file__).resolve().parents[1] / "skills" / "verif-harness"
        with self.connect() as connection:
            for desired in desired_rows:
                contract = desired.get("document")
                if not contract:
                    continue
                candidate = output / contract["filename"]
                if candidate.is_symlink():
                    raise HarnessError(f"拒绝跟随语义文档符号链接: {candidate}")
                relative = relative_path(self.root, candidate)
                self._document_path_allowed(relative)
                target = self.root / relative
                source = skill_root / contract["template"]
                if not source.is_file():
                    raise HarnessError(f"VDOC 模板不存在: {contract['template']}")
                created = not target.exists()
                if created:
                    atomic_text(target, source.read_text(encoding="utf-8"))
                document_id = f"document:vdoc:{desired['key']}"
                owners = ",".join(contract["maintained_by"])
                changed, row = self._register_document(
                    connection, document_id, relative, desired["title"], desired["id"], owners,
                    "由 VDOC 模板创建" if created else "登记已有语义文档",
                )
                row["materialized"] = created
                results.append(row)
                if changed:
                    changed_paths.append((relative, row["semantic_revision"]))
        for relative, revision in changed_paths:
            self.record_change(relative, "modify", f"document-r{revision}")
        self.write_model_projection()
        return results

    def design_workstream(
        self, workstream: str, objective: str | None, desired: list[str],
        exit_criteria: list[str], decisions: list[str], document_root: str | None = None,
    ) -> dict[str, Any]:
        self.require()
        name = self.normalize_workstream(workstream)
        if document_root is not None and name != "VDOC":
            raise HarnessError("--document-root 只适用于 VDOC")
        template = WORKSTREAM_TEMPLATES[name]
        objective_value = objective.strip() if objective and objective.strip() else template["objective"]
        desired_specs = (
            [(f"custom-{index:03d}", title, "reason") for index, title in enumerate(desired, 1)]
            if desired else list(template["desired"])
        )
        exit_values = exit_criteria or list(template["exit"])
        context = self.planning_context(name)
        manifest = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        document_root_value: str | None = None
        if name == "VDOC":
            document_root_value = (
                relative_path(self.root, document_root)
                if document_root is not None
                else str(manifest.get("vdoc_document_root") or default_vdoc_document_root(manifest))
            )
            output_path = (self.root / document_root_value).resolve()
            if output_path.exists() and not output_path.is_dir():
                raise HarnessError(f"VDOC document root 不是目录: {document_root_value}")
            readonly_inputs = [*manifest.get("rtl_roots", []), *manifest.get("docs_roots", [])]
            for value in readonly_inputs:
                source = resolved_path(self.root, value)
                if source.is_dir() and (output_path == source or source in output_path.parents):
                    raise HarnessError(f"VDOC document root 不得位于只读输入内: {document_root_value}")
                if source.is_file() and output_path == source:
                    raise HarnessError(f"VDOC document root 与只读输入冲突: {document_root_value}")
            context["document_root"] = document_root_value
        with self.connect() as connection:
            observed = connection.execute("SELECT revision FROM workstreams WHERE name=?", (name,)).fetchone()
            revision = int(observed["revision"]) + 1 if observed else 1
            connection.execute("UPDATE nodes SET workstream=NULL,status=?,updated_at=? WHERE workstream=? AND type='desired-state'",
                               (Validity.STALE.value, now(), name))
            desired_rows = []
            for key, title, suggested_mode in desired_specs:
                node_id = f"workstream:{name}:r{revision}:desired:{key}"
                row = {"id": node_id, "key": key, "title": title, "required": True, "suggested_mode": suggested_mode}
                if name == "VDOC" and not desired:
                    row["document"] = vdoc_document_contract(key)
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
        materialized_documents: list[dict[str, Any]] = []
        if name == "VDOC":
            manifest["vdoc_document_root"] = document_root_value
            manifest["updated_at"] = now()
            atomic_json(self.state / "project.json", manifest)
            update_project_agents(self.root / "AGENTS.md", project_agents_block(manifest, document_root_value))
            if not desired:
                materialized_documents = self._materialize_vdoc_documents(desired_rows, document_root_value)
        result = self.workstream(name)
        result["template"] = {"name": template["name"], "topics": [item[0] for item in template["desired"]]}
        if name == "VDOC":
            result["document_guidance"] = {
                "instructions": "vplan/vdoc.md",
                "templates_relative_to": "skill-root",
                "materialization": "missing-templates-created; agent-dialogue-required-for-semantics",
                "document_root": document_root_value,
                "project_instructions": "AGENTS.md",
                "documents": materialized_documents,
                "optional_documents": [{"filename": "code_coverage_waiver_manifest.md",
                                        "template": "assets/vdoc/code_coverage_waiver_manifest.md",
                                        "when": "specific-code-coverage-waiver-candidate", "maintained_by": ["VCOV"]}],
            }
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

    def documents(self, selector: str | None = None) -> list[dict[str, Any]]:
        self.require()
        with self.read_connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
            ).fetchone()
            if exists is None:
                if selector is not None:
                    raise HarnessError(f"未知语义文档: {selector}；先执行 plan VDOC")
                return []
            rows = [dict(row) for row in connection.execute("SELECT * FROM documents ORDER BY path")]
            if selector is not None:
                matches = [row for row in rows if selector in {row["id"], row["path"], Path(row["path"]).name}]
                if not matches:
                    raise HarnessError(f"未知语义文档: {selector}")
                if len(matches) > 1:
                    raise HarnessError(f"文档选择不唯一，请使用完整路径或 ID: {selector}")
                rows = matches
            for row in rows:
                current_path = self.root / row["path"]
                row["exists"] = current_path.is_file()
                row["content_changed"] = row["exists"] and self._digest(current_path) != row["digest"]
                row["effective_status"] = (
                    Validity.INVALID.value if not row["exists"] else
                    Validity.REVIEW_REQUIRED.value if row["content_changed"] else row["status"]
                )
                row["revisions"] = [dict(item) for item in connection.execute(
                    "SELECT semantic_revision,digest,summary,created_at FROM document_revisions WHERE document_id=? ORDER BY semantic_revision",
                    (row["id"],),
                )]
                row["reviews"] = [dict(item) for item in connection.execute(
                    "SELECT id,semantic_revision,verdict,reviewer,notes,created_at FROM document_reviews WHERE document_id=? ORDER BY created_at",
                    (row["id"],),
                )]
                items = [dict(item) for item in connection.execute(
                    "SELECT id,kind,title,anchor,status,owner,review_trigger,affects_json,created_at,updated_at "
                    "FROM document_items WHERE document_id=? ORDER BY kind,id",
                    (row["id"],),
                )]
                for item in items:
                    item["affects"] = json.loads(item.pop("affects_json"))
                row["governance_items"] = items
        return rows

    def sync_documents(self, selectors: Iterable[str] = ()) -> dict[str, Any]:
        requested = list(selectors)
        rows = self.documents()
        if requested:
            selected: list[dict[str, Any]] = []
            for selector in requested:
                selected.extend(self.documents(selector))
            unique = {row["id"]: row for row in selected}
            rows = [unique[key] for key in sorted(unique)]
        if not rows:
            raise HarnessError("尚未登记语义文档；先执行 plan VDOC")
        changed: list[tuple[str, int]] = []
        missing: list[str] = []
        newly_missing: list[str] = []
        restored: list[tuple[str, int]] = []
        with self.connect() as connection:
            for row in rows:
                path = self.root / row["path"]
                if not path.is_file():
                    connection.execute("UPDATE documents SET status=?,updated_at=? WHERE id=?",
                                       (Validity.INVALID.value, now(), row["id"]))
                    connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                                       (Validity.INVALID.value, now(), row["id"]))
                    missing.append(row["path"])
                    if row["status"] != Validity.INVALID.value:
                        newly_missing.append(row["path"])
                    continue
                observed_changed, result = self._register_document(
                    connection, row["id"], row["path"], row["title"], row["desired_id"],
                    row["owner"], "语义正文内容摘要发生变化",
                )
                if observed_changed:
                    changed.append((row["path"], result["semantic_revision"]))
                elif row["status"] == Validity.INVALID.value:
                    connection.execute("UPDATE documents SET status=?,updated_at=? WHERE id=?",
                                       (Validity.REVIEW_REQUIRED.value, now(), row["id"]))
                    connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                                       (Validity.REVIEW_REQUIRED.value, now(), row["id"]))
                    restored.append((row["path"], result["semantic_revision"]))
        for path, revision in changed:
            self.record_change(path, "modify", f"document-r{revision}")
        for path in newly_missing:
            self.record_change(path, "delete", None)
        for path, revision in restored:
            self.record_change(path, "add", f"document-r{revision}")
        self.write_model_projection()
        return {"documents": self.documents(), "changed": [path for path, _revision in changed],
                "missing": missing, "restored": [path for path, _revision in restored],
                "state_projection_written": False}

    def review_document(
        self, selector: str, verdict: str, reviewer: str, notes: str,
    ) -> dict[str, Any]:
        self.sync_documents([selector])
        document = self.documents(selector)[0]
        plan = self.workstream("VDOC")
        if plan["lifecycle"] not in {"ACTIVE", "SATISFIED", "PARTIALLY_STALE"}:
            raise HarnessError("必须先由 Human approve 当前 VDOC desired-state revision，再评审文档正文")
        normalized = verdict.upper()
        review_id = uuid.uuid4().hex
        status = Validity.VALID.value if verdict == "approve" else Validity.REVIEW_REQUIRED.value
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO document_reviews VALUES(?,?,?,?,?,?,?)",
                (review_id, document["id"], document["semantic_revision"], normalized,
                 reviewer, notes, now()),
            )
            connection.execute("UPDATE documents SET status=?,updated_at=? WHERE id=?",
                               (status, now(), document["id"]))
            connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                               (status, now(), document["id"]))
            if verdict == "approve":
                connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                                   (Validity.VALID.value, now(), f"file:{document['path']}"))
                connection.execute(
                    "UPDATE findings SET status='RESOLVED' WHERE subject IN (?,?) AND status='OPEN'",
                    (document["id"], f"file:{document['path']}"),
                )
            if verdict != "approve" and document["desired_id"]:
                connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?",
                                   (Validity.REVIEW_REQUIRED.value, now(), document["desired_id"]))
        evidence = None
        if verdict == "approve" and document["desired_id"]:
            evidence = self.add_evidence(document["desired_id"], "document-review", document["path"], "pass")
        self.write_model_projection()
        return {"review_id": review_id, "document": self.documents(selector)[0],
                "verdict": normalized, "reviewer": reviewer, "evidence": evidence,
                "auto_closure": self.evaluate_closure("VDOC")}

    def track_document_item(
        self, selector: str, item_id: str, kind: str, title: str, status: str,
        owner: str | None, review_trigger: str | None, affects: list[str], anchor: str | None,
    ) -> dict[str, Any]:
        document = self.documents(selector)[0]
        normalized_kind = kind.lower()
        normalized_status = status.upper()
        if normalized_kind not in DOCUMENT_ITEM_KINDS:
            raise HarnessError("治理事项类型必须是 " + ", ".join(sorted(DOCUMENT_ITEM_KINDS)))
        if normalized_status not in DOCUMENT_ITEM_STATUSES:
            raise HarnessError("治理事项状态必须是 " + ", ".join(sorted(DOCUMENT_ITEM_STATUSES)))
        if not item_id.strip() or any(character.isspace() for character in item_id):
            raise HarnessError("治理事项 ID 不能为空或包含空白")
        timestamp = now()
        with self.connect() as connection:
            previous = connection.execute("SELECT * FROM document_items WHERE id=?", (item_id,)).fetchone()
            connection.execute(
                "INSERT INTO document_items VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET document_id=excluded.document_id,kind=excluded.kind,"
                "title=excluded.title,anchor=excluded.anchor,status=excluded.status,owner=excluded.owner,"
                "review_trigger=excluded.review_trigger,affects_json=excluded.affects_json,updated_at=excluded.updated_at",
                (item_id, document["id"], normalized_kind, title, anchor, normalized_status,
                 owner, review_trigger, json_text(affects), timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?)",
                (f"event:{uuid.uuid4().hex[:12]}", "document-item-change", item_id,
                 str(document["semantic_revision"]), json_text({
                     "document_id": document["id"], "previous_status": previous["status"] if previous else None,
                     "status": normalized_status, "kind": normalized_kind,
                 }), timestamp),
            )
        return {"id": item_id, "document_id": document["id"], "kind": normalized_kind,
                "title": title, "status": normalized_status, "owner": owner,
                "review_trigger": review_trigger, "affects": affects, "anchor": anchor}

    def render_document_state(self, selector: str | None = None) -> str:
        documents = self.documents(selector)
        if not documents:
            raise HarnessError("尚未登记语义文档；先执行 plan VDOC")

        def cell(value: Any) -> str:
            return str(value if value not in {None, ""} else "—").replace("|", "\\|").replace("\n", " ")

        lines = ["# 验证文档治理状态", "",
                 "> 本内容由 `.verif-harness/model.sqlite3` 按需投影；不要手工并入工程语义正文。"]
        labels = {
            "human-decision": "Human Decisions", "provisional": "Provisional Decisions",
            "assumption": "Assumptions", "external-open-question": "External Open Questions",
        }
        for document in documents:
            lines.extend(["", f"## `{document['path']}`", "",
                          f"- Document ID：`{document['id']}`",
                          f"- Semantic revision：**{document['semantic_revision']}**",
                          f"- Status：**{document['effective_status']}**",
                          f"- Recorded status：**{document['status']}**",
                          f"- Working tree content changed：**{str(document['content_changed']).lower()}**",
                          f"- Content digest：`{document['digest']}`",
                          f"- Desired ID：`{document['desired_id'] or '—'}`",
                          f"- Owner：{document['owner']}"])
            for kind, label in labels.items():
                items = [item for item in document["governance_items"] if item["kind"] == kind]
                lines.extend(["", f"### {label}", "",
                              "| ID | 状态 | 内容 | Owner | 复审触发器 | 影响目标 | 文档锚点 |",
                              "| --- | --- | --- | --- | --- | --- | --- |"])
                lines.extend(
                    f"| `{cell(item['id'])}` | {cell(item['status'])} | {cell(item['title'])} | "
                    f"{cell(item['owner'])} | {cell(item['review_trigger'])} | "
                    f"{cell(', '.join(item['affects']))} | {cell(item['anchor'])} |" for item in items
                )
                if not items:
                    lines.append("| — | — | 无 | — | — | — | — |")
            lines.extend(["", "### Review Trace", "",
                          "| Revision | Verdict | Reviewer | 时间 |",
                          "| --- | --- | --- | --- |"])
            lines.extend(
                f"| {item['semantic_revision']} | {cell(item['verdict'])} | {cell(item['reviewer'])} | {cell(item['created_at'])} |"
                for item in document["reviews"]
            )
            if not document["reviews"]:
                lines.append("| — | — | 尚无评审 | — |")
            lines.extend(["", "### Human Review Notes", ""])
            notes = [item for item in document["reviews"] if item["notes"]]
            lines.extend(
                f"- r{item['semantic_revision']} · {item['reviewer']} · {item['verdict']}：{item['notes']}"
                for item in notes
            )
            if not notes:
                lines.append("- 无")
            lines.extend(["", "### Revision Log", "",
                          "| Revision | Digest | 摘要 | 时间 |",
                          "| --- | --- | --- | --- |"])
            lines.extend(
                f"| {item['semantic_revision']} | `{item['digest']}` | {cell(item['summary'])} | {cell(item['created_at'])} |"
                for item in document["revisions"]
            )
        return "\n".join(lines) + "\n"

    def write_document_state_projection(self, output: str, selector: str | None = None) -> dict[str, Any]:
        relative = relative_path(self.root, output)
        self._document_path_allowed(relative)
        if any(row["path"] == relative for row in self.documents()):
            raise HarnessError("治理状态投影不能覆盖工程语义文档")
        atomic_text(self.root / relative, self.render_document_state(selector))
        return {"path": relative, "selector": selector, "source": ".verif-harness/model.sqlite3"}

    def _baseline_payload(self, workstream: str, reviewer: str, reason: str) -> dict[str, Any]:
        plan = self.workstream(workstream)
        model = self.model()
        payload = {
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
        if workstream == "VDOC":
            documents = self.documents()
            if documents:
                payload["documents"] = documents
                payload["document_governance_projection"] = "document-governance.md"
                for document in documents:
                    document["snapshot_path"] = f"documents/{Path(document['path']).name}"
        return payload

    def freeze_workstream(self, workstream: str, reviewer: str, reason: str) -> dict[str, Any]:
        name = self.normalize_workstream(workstream)
        if name == "VDOC":
            registered_documents = self.documents()
            if registered_documents:
                self.sync_documents()
                unreviewed = [row["path"] for row in self.documents() if row["status"] != Validity.VALID.value]
                if unreviewed:
                    raise HarnessError("VDOC 存在尚未批准或内容已变化的语义文档: " + ", ".join(unreviewed))
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
        if name == "VDOC" and payload.get("documents"):
            for document in payload.get("documents", []):
                source = self.root / document["path"]
                if self._digest(source) != document["digest"]:
                    raise HarnessError(f"语义文档在 freeze 期间发生变化: {document['path']}")
            atomic_text(target.parent / payload["document_governance_projection"], self.render_document_state())
            for document in payload.get("documents", []):
                source = self.root / document["path"]
                snapshot = target.parent / document["snapshot_path"]
                atomic_text(snapshot, source.read_text(encoding="utf-8"))
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
        if missing or not_ready or audit["open_findings"] or audit["status"] == "FAIL":
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
        relative = self._project_or_declared_input_path(path)
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
        document_sync = self.sync_documents() if self.documents() else {"changed": [], "missing": []}
        missing: list[str] = []
        with self.connect() as connection:
            for row in connection.execute("SELECT id FROM nodes WHERE id LIKE 'file:%'"):
                relative = row["id"][5:]
                if relative != "." and not (self.root / relative).exists():
                    missing.append(row["id"])
                    connection.execute("UPDATE nodes SET status=?,updated_at=? WHERE id=?", (Validity.INVALID.value, now(), row["id"]))
            open_findings = connection.execute("SELECT COUNT(*) count FROM findings WHERE status='OPEN'").fetchone()["count"]
        self.write_model_projection()
        failed = bool(missing or document_sync["changed"] or open_findings)
        return {"missing_files": missing, "changed_documents": document_sync["changed"],
                "open_findings": open_findings, "status": "FAIL" if failed else "PASS",
                "auto_closure": self.reconcile()}

    def audit(self) -> dict[str, Any]:
        self.require()
        missing: list[str] = []
        changed_documents: list[str] = []
        registered_documents = self.documents()
        with self.read_connect() as connection:
            for row in connection.execute("SELECT id FROM nodes WHERE id LIKE 'file:%'"):
                relative = row["id"][5:]
                if relative != "." and not (self.root / relative).exists():
                    missing.append(row["id"])
            open_findings = connection.execute("SELECT COUNT(*) count FROM findings WHERE status='OPEN'").fetchone()["count"]
            for row in registered_documents:
                if row["content_changed"]:
                    changed_documents.append(row["path"])
        failed = bool(missing or changed_documents or open_findings)
        return {"missing_files": missing, "changed_documents": changed_documents,
                "open_findings": open_findings, "status": "FAIL" if failed else "PASS"}

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
        document_rows = self.documents()
        document_status: dict[str, int] = {}
        for document in document_rows:
            observed = document["effective_status"]
            document_status[observed] = document_status.get(observed, 0) + 1
        return {
            "project": manifest["project_name"], "baseline_revision": manifest.get("baseline_revision"),
            "runtime": manifest.get("runtime"), "lifecycle": "ACTIVE",
            "workstreams": plans, "closures": [self.evaluate_closure(item["workstream"], persist=False) for item in plans],
            "node_status": counts, "open_findings": sum(item["status"] == "OPEN" for item in model["findings"]),
            "documents": {"count": len(document_rows), "status": document_status,
                          "content_changed": [row["path"] for row in document_rows if row["content_changed"]]},
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
        documents = [item for item in plan["desired_state"] if item.get("document")]
        if documents:
            lines.extend(["", "## Document Deliverables", "",
                          "模板相对 Skill 根目录；由 Agent 在独立验证文档目录中对话填充，文件存在不代表目标通过。", "",
                          "| Desired ID | 文档 | 模板 | 维护工作域 |", "| --- | --- | --- | --- |"])
            lines.extend(f"| `{item['id']}` | `{item['document']['filename']}` | `{item['document']['template']}` | {', '.join(item['document']['maintained_by'])} |"
                         for item in documents)
        lines.extend(["", "## Exit Criteria", ""])
        lines.extend(f"- [ ] {item}" for item in plan["exit_criteria"])
        lines.extend(["", "## Human Decisions", ""])
        lines.extend(f"- {item}" for item in plan["decisions"])
        if not plan["decisions"]: lines.append("- 无")
        (directory / "plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
