"""DUT-grounded verification-document authoring profiles and proposal builder."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


AUTHORING_CONTRACT_SCHEMA = "VerificationDocumentAuthoringContract/1"
AUTHORING_CONTEXT_SCHEMA = "VerificationDocumentAuthoringContext/1"
AUTHORING_PROFILE_SCHEMA = "VerificationDocumentAuthoringProfile/1"
AUTHORING_ENGINE_VERSION = "verification-doc-authoring/1"
AUTHORING_DOCUMENT_ORDER = (
    "verification-workflow", "verification-plan", "feature-matrix",
    "tb-architecture", "reference-model", "coverage-plan",
    "assertion-plan", "testcase-list",
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPOSITORY_ROOT / "skills" / "verification-doc-authoring"
PROFILE_ROOT = SKILL_ROOT / "profiles"
COMMON_RULES_PATH = SKILL_ROOT / "core" / "common-rules.json"
VDOC_TEMPLATE_ROOT = REPOSITORY_ROOT / "skills" / "verif-harness" / "assets" / "vdoc"

RTL_SUFFIXES = {".v", ".sv", ".svh", ".vhd", ".vhdl"}
TEXT_SUFFIXES = {".md", ".rst", ".txt", ".sv", ".svh", ".v", ".vhd", ".vhdl"}
IGNORED_PARTS = {".git", ".deps", ".verif-harness", "__pycache__"}

CONTRACT_FIELDS = {
    "schema", "profile", "generation", "source_requirements", "source_snapshot",
    "source_gaps", "dut_scope", "rtl_spec_analysis_method", "document_dependencies",
    "document_structure", "section_authoring_instructions", "required_tables",
    "domain_rules", "cross_document_consistency_rules", "traceability_requirements",
    "review", "freeze", "change_invalidation_rules",
}
DUT_SCOPE_FIELDS = {
    "dut_top", "hierarchy", "ports", "interfaces", "clock_reset",
    "internal_structures", "protocols", "registers", "error_interrupts",
}


class DocumentAuthoringError(ValueError):
    """A project-authoring contract or profile is invalid."""


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DocumentAuthoringError(f"无法读取 verification-doc-authoring 资源 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DocumentAuthoringError(f"verification-doc-authoring 资源必须是 JSON object: {path}")
    return value


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return _digest_bytes(payload.encode("utf-8"))


def _project_context_digest(manifest: dict[str, Any]) -> str:
    """Bind semantic bootstrap context, excluding planner-owned timestamps/routes."""
    return _canonical_digest({
        key: manifest.get(key)
        for key in (
            "schema_version", "project_name", "project_root", "runtime",
            "baseline_revision", "rtl_roots", "docs_roots", "verif_root",
            "verification_inputs", "dut",
        )
    })


def _non_empty_strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise DocumentAuthoringError(f"{field} 必须是非空字符串数组")
    return [item.strip() for item in value]


def _profile_files(profile_root: Path = PROFILE_ROOT) -> list[Path]:
    return sorted(path for path in profile_root.glob("*.json") if path.is_file())


def load_common_rules(path: Path = COMMON_RULES_PATH) -> dict[str, Any]:
    rules = _json(path)
    if rules.get("schema") != "VerificationDocumentAuthoringCommonRules/1":
        raise DocumentAuthoringError("verification-doc-authoring common rules schema 无效")
    required = {
        "source_requirements", "rtl_spec_analysis_method",
        "cross_document_consistency_rules", "traceability_requirements",
        "review_roles", "review_criteria", "freeze_criteria",
        "change_invalidation_rules",
    }
    missing = sorted(required - set(rules))
    if missing:
        raise DocumentAuthoringError("verification-doc-authoring common rules 缺少: " + ", ".join(missing))
    return rules


def load_authoring_profiles(profile_root: Path = PROFILE_ROOT) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    required = {
        "schema", "document_key", "filename", "node_key", "title", "purpose",
        "dependencies", "source_requirements", "dut_fact_requirements",
        "document_structure", "section_authoring_instructions", "required_tables",
        "domain_rules", "cross_document_rules", "traceability_rules",
        "review_roles", "review_criteria", "freeze_criteria", "change_invalidation_rules",
    }
    for path in _profile_files(profile_root):
        profile = _json(path)
        if profile.get("schema") != AUTHORING_PROFILE_SCHEMA:
            raise DocumentAuthoringError(f"profile schema 无效: {path.name}")
        missing = sorted(required - set(profile))
        if missing:
            raise DocumentAuthoringError(f"profile {path.name} 缺少字段: {', '.join(missing)}")
        key = str(profile.get("document_key", "")).strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", key):
            raise DocumentAuthoringError(f"profile document_key 无效: {path.name}")
        if key in profiles:
            raise DocumentAuthoringError(f"profile document_key 重复: {key}")
        if path.stem != key:
            raise DocumentAuthoringError(f"profile 文件名必须与 document_key 一致: {path.name}")
        expected_node_key = key.replace("-", "_") + "_authoring"
        if profile.get("node_key") != expected_node_key:
            raise DocumentAuthoringError(f"profile {key} node_key 必须是 {expected_node_key}")
        dependencies = _non_empty_strings(profile["dependencies"], f"profile {key}.dependencies") if profile["dependencies"] else []
        if key in dependencies:
            raise DocumentAuthoringError(f"profile {key} 不能依赖自身")
        profile["dependencies"] = dependencies
        profile["profile_digest"] = _canonical_digest({
            field: value for field, value in profile.items() if field != "profile_digest"
        })
        profiles[key] = profile

    for key, profile in profiles.items():
        unknown = sorted(set(profile["dependencies"]) - set(profiles))
        if unknown:
            raise DocumentAuthoringError(f"profile {key} 引用了未知 document dependency: {', '.join(unknown)}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise DocumentAuthoringError(f"authoring profile dependency 存在循环: {key}")
        if key in visited:
            return
        visiting.add(key)
        for dependency in profiles[key]["dependencies"]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in profiles:
        visit(key)
    if set(profiles) != set(AUTHORING_DOCUMENT_ORDER):
        raise DocumentAuthoringError(
            "authoring profile registry 必须与八份 VDOC 文档一致"
        )
    return profiles


def profile_registry() -> dict[str, dict[str, str]]:
    return {
        key: {
            "document_key": key,
            "filename": str(profile["filename"]),
            "node_key": str(profile["node_key"]),
            "profile_digest": str(profile["profile_digest"]),
        }
        for key, profile in load_authoring_profiles().items()
    }


def _within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _declared_roots(root: Path, manifest: dict[str, Any]) -> list[Path]:
    values: list[str] = [
        *[str(item) for item in manifest.get("rtl_roots", [])],
        *[str(item) for item in manifest.get("docs_roots", [])],
    ]
    verification_inputs = manifest.get("verification_inputs", {})
    if isinstance(verification_inputs, dict):
        for field in ("testbench_root", "reference_model"):
            value = verification_inputs.get(field)
            if isinstance(value, str) and value.strip():
                values.append(value)
        scripts = verification_inputs.get("scripts", [])
        if isinstance(scripts, list):
            values.extend(str(item) for item in scripts if str(item).strip())
    return [_resolve(root, value) for value in values]


def _path_is_allowed(root: Path, manifest: dict[str, Any], path: Path) -> bool:
    resolved = path.resolve()
    return _within(resolved, root.resolve()) or any(
        _within(resolved, declared) for declared in _declared_roots(root, manifest)
    )


def _iter_files(source: Path) -> Iterable[Path]:
    candidates = [source] if source.is_file() else sorted(source.rglob("*"))
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            continue
        relative = Path(path.name) if source.is_file() else path.relative_to(source)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        yield path.resolve()


def _read_text(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _text_anchors(text: str) -> list[str]:
    anchors: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            anchor = stripped.lstrip("#").strip()
            if anchor and anchor not in anchors:
                anchors.append(anchor[:200])
        if len(anchors) >= 50:
            break
    return anchors


REQUIREMENT_ID = re.compile(r"\b(?:REQ|FEATURE|SPEC|INTF|REG|CSR|ERR)[-_][A-Za-z0-9_.-]+\b", re.IGNORECASE)
NORMATIVE_WORD = re.compile(r"\b(?:shall|must|required|forbidden)\b|必须|应当|不得|禁止", re.IGNORECASE)


def _source_statements(text: str) -> list[str]:
    statements: list[str] = []
    for line in text.splitlines():
        stripped = " ".join(line.strip().split())
        if not stripped or stripped.startswith(("```", "| ---")):
            continue
        if REQUIREMENT_ID.search(stripped) or NORMATIVE_WORD.search(stripped):
            value = stripped[:500]
            if value not in statements:
                statements.append(value)
        if len(statements) >= 200:
            break
    return statements


def _spec_kind(path: Path) -> str:
    name = path.name.lower().replace("_", "-")
    if any(token in name for token in ("micro-arch", "microarch", "uarch", "microarchitecture")):
        return "micro-architecture-spec"
    if any(token in name for token in ("interface", "protocol", "bus-spec")):
        return "interface-spec"
    if any(token in name for token in ("register", "regmap", "csr")):
        return "register-spec"
    return "design-spec"


def _source_id(kind: str, display_path: str) -> str:
    return f"source:{kind}:{hashlib.sha256(display_path.encode('utf-8')).hexdigest()[:12]}"


def _source_record(
    root: Path, path: Path, kind: str, *, status: str = "available",
    document_key: str | None = None, facts: list[str] | None = None,
) -> dict[str, Any]:
    display = _display_path(root, path)
    text = _read_text(path)
    row: dict[str, Any] = {
        "id": _source_id(kind, display),
        "kind": kind,
        "path": display,
        "sha256": _digest_bytes(path.read_bytes()),
        "status": status,
        "anchors": _text_anchors(text) if text is not None else [],
        "facts": list(facts if facts is not None else _source_statements(text or "")),
    }
    if document_key is not None:
        row["document_key"] = document_key
    return row


def _strip_sv_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def _balanced(text: str, start: int) -> tuple[str, int] | None:
    if start >= len(text) or text[start] != "(":
        return None
    depth = 1
    for index in range(start + 1, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
    return None


def _split_ports(body: str) -> list[str]:
    tokens: list[str] = []
    depth = 0
    buffer: list[str] = []
    for character in body:
        if character in "[({":
            depth += 1
        elif character in "])}":
            depth -= 1
        if character == "," and depth == 0:
            token = " ".join("".join(buffer).split())
            if token:
                tokens.append(token)
            buffer = []
        else:
            buffer.append(character)
    token = " ".join("".join(buffer).split())
    if token:
        tokens.append(token)
    return tokens


PORT_RE = re.compile(
    r"^(?P<direction>input|output|inout)\b"
    r"(?:\s+(?:reg|wire|logic|bit|signed|unsigned))*"
    r"(?P<width>\s*\[[^\]]+\])?\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_$]*)"
    r"(?:\s*\[[^\]]+\])?\s*$"
)


def _parse_top_ports(text: str, top: str) -> tuple[list[dict[str, str]], list[str], bool]:
    source = _strip_sv_comments(text)
    match = re.search(rf"\bmodule\s+{re.escape(top)}\b", source)
    if match is None:
        return [], [f"DUT top module {top} 未在登记的 top file 中找到"], False
    index = match.end()
    while index < len(source) and source[index].isspace():
        index += 1
    if index < len(source) and source[index] == "#":
        index += 1
        while index < len(source) and source[index].isspace():
            index += 1
        parameter_block = _balanced(source, index)
        if parameter_block is None:
            return [], [f"DUT top module {top} parameter header 无法解析"], False
        index = parameter_block[1]
    while index < len(source) and source[index].isspace():
        index += 1
    if index < len(source) and source[index] == ";":
        return [], [], True
    port_block = _balanced(source, index)
    if port_block is None:
        return [], [f"DUT top module {top} port header 无法解析"], False
    ports: list[dict[str, str]] = []
    gaps: list[str] = []
    last_direction: str | None = None
    last_width = "1"
    for token in _split_ports(port_block[0]):
        parsed = PORT_RE.fullmatch(token)
        if parsed is not None:
            last_direction = str(parsed.group("direction"))
            raw_width = parsed.group("width")
            last_width = raw_width.strip()[1:-1].strip() if raw_width else "1"
            ports.append({
                "name": str(parsed.group("name")),
                "direction": last_direction,
                "width": last_width,
            })
            continue
        bare = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_$]*)", token)
        if bare is not None and last_direction is not None:
            ports.append({"name": bare.group(1), "direction": last_direction, "width": last_width})
        else:
            gaps.append(f"未解析 top port declaration: {token[:200]}")
    return ports, gaps, True


def _fact(name: str, detail: str, source_refs: list[str]) -> dict[str, Any]:
    return {"name": name, "detail": detail, "source_refs": source_refs}


def _collect_sources(root: Path, manifest: dict[str, Any], profiles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    project_context = root / ".harness-config.json"
    if not project_context.is_file():
        project_context = root / ".verif-harness" / "project.json"
    facts = [
        f"project_name={manifest.get('project_name')}",
        f"dut_top={manifest.get('dut', {}).get('top_module')}",
        "rtl_roots=" + ",".join(str(item) for item in manifest.get("rtl_roots", [])),
        "spec_roots=" + ",".join(str(item) for item in manifest.get("docs_roots", [])),
    ]
    sources = [_source_record(root, project_context, "project-context", facts=facts)]
    seen = {project_context.resolve()}
    for value in manifest.get("rtl_roots", []):
        source = _resolve(root, str(value))
        for path in _iter_files(source):
            if path in seen or path.suffix.lower() not in RTL_SUFFIXES:
                continue
            seen.add(path)
            text = _read_text(path) or ""
            modules = re.findall(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)", _strip_sv_comments(text))
            sources.append(_source_record(
                root, path, "rtl", facts=[f"declared module {name}" for name in modules],
            ))
    for value in manifest.get("docs_roots", []):
        source = _resolve(root, str(value))
        for path in _iter_files(source):
            if path in seen:
                continue
            seen.add(path)
            sources.append(_source_record(root, path, _spec_kind(path)))

    verification_inputs = manifest.get("verification_inputs", {})
    if isinstance(verification_inputs, dict):
        registered_inputs = (
            ("testbench_root", "verification-testbench"),
            ("reference_model", "reference-model-implementation"),
        )
        for field, kind in registered_inputs:
            value = verification_inputs.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            for path in _iter_files(_resolve(root, value)):
                if path in seen:
                    continue
                seen.add(path)
                sources.append(_source_record(root, path, kind))
        scripts = verification_inputs.get("scripts", [])
        if isinstance(scripts, list):
            for value in scripts:
                path = _resolve(root, str(value))
                if path in seen or not path.is_file():
                    continue
                seen.add(path)
                sources.append(_source_record(root, path, "verification-script"))

    document_root = manifest.get("vdoc_document_root")
    if isinstance(document_root, str) and document_root.strip():
        base = _resolve(root, document_root)
        for key, profile in profiles.items():
            path = base / str(profile["filename"])
            if not path.is_file() or path.resolve() in seen:
                continue
            seen.add(path.resolve())
            template = VDOC_TEMPLATE_ROOT / str(profile["filename"])
            status = (
                "template-only"
                if template.is_file() and _digest_bytes(path.read_bytes()) == _digest_bytes(template.read_bytes())
                else "available"
            )
            sources.append(_source_record(
                root, path.resolve(), "verification-document",
                status=status, document_key=key,
            ))
    return sources


def _source_matches(requirement: str, source: dict[str, Any]) -> bool:
    kind = str(source.get("kind"))
    if requirement == "design-spec":
        return kind in {
            "design-spec", "micro-architecture-spec", "interface-spec", "register-spec",
        }
    if requirement == "verification-artifact":
        return kind in {
            "verification-document", "verification-testbench",
            "reference-model-implementation", "verification-script",
        }
    if requirement.startswith("verification-document:"):
        return kind == "verification-document" and source.get("document_key") == requirement.split(":", 1)[1]
    return kind == requirement


def _merge_source_requirements(common: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in [*common["source_requirements"], *profile["source_requirements"]]:
        if not isinstance(item, dict):
            raise DocumentAuthoringError(f"profile {profile['document_key']} source requirement 必须是 object")
        expected = {"source_kind", "required", "purpose", "selection_rule"}
        if set(item) != expected:
            raise DocumentAuthoringError(
                f"profile {profile['document_key']} source requirement 必须且只能包含 "
                "source_kind、required、purpose、selection_rule"
            )
        merged[str(item["source_kind"])] = dict(item)
    for dependency in profile["dependencies"]:
        merged[f"verification-document:{dependency}"] = {
            "source_kind": f"verification-document:{dependency}",
            "required": True,
            "purpose": f"继承 {dependency} 已形成的项目级范围、术语、ID 和工程决定。",
            "selection_rule": "只使用当前 revision 已登记的正文；template-only 或过期内容必须记录为 source gap。",
        }
    return list(merged.values())


def _dut_scope(
    root: Path, manifest: dict[str, Any], sources: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_by_path = {str(item["path"]): item for item in sources}
    dut = manifest.get("dut", {}) if isinstance(manifest.get("dut"), dict) else {}
    top = str(dut.get("top_module") or "").strip()
    top_path_value = str(dut.get("top_file") or "").strip()
    top_path = _resolve(root, top_path_value) if top_path_value else None
    top_display = _display_path(root, top_path) if top_path is not None else ""
    top_source = source_by_path.get(top_display)
    top_refs = [str(top_source["id"])] if top_source is not None else []
    top_fact = _fact(top or "unresolved", f"DUT top file: {top_display or 'unresolved'}", top_refs)
    result: dict[str, Any] = {
        "dut_top": top_fact,
        "hierarchy": [], "ports": [], "interfaces": [], "clock_reset": [],
        "internal_structures": [], "protocols": [], "registers": [],
        "error_interrupts": [],
    }
    gaps: list[dict[str, Any]] = []
    if top_path is None or not top_path.is_file() or not top:
        gaps.append({
            "id": "gap:dut-top", "missing_source": "rtl",
            "impact": "无法把 authoring plan 绑定到明确 DUT top 与顶层接口。",
            "required_review": "负责人补齐 bootstrap 的 dut top 和 dut top file。",
            "blocks_document_authoring": True,
        })
        return result, gaps
    text = _read_text(top_path) or ""
    ports, port_gaps, parsed = _parse_top_ports(text, top)
    for port in ports:
        detail = f"{port['direction']} width={port['width']}"
        result["ports"].append(_fact(port["name"], detail, top_refs))
        lowered = port["name"].lower()
        if re.search(r"(^|_)(clk|clock|rst|reset)(_|$)", lowered):
            result["clock_reset"].append(_fact(
                port["name"],
                f"name-based clock/reset candidate; direction={port['direction']}, width={port['width']}; semantics require spec review",
                top_refs,
            ))
    if not parsed:
        port_gaps.append("顶层 port 列表未形成可靠解析结果")
    for index, message in enumerate(port_gaps, 1):
        gaps.append({
            "id": f"gap:rtl-port-{index}", "missing_source": "rtl-port-analysis",
            "impact": message,
            "required_review": "由验证架构负责人对照 RTL 与 Interface Spec 补齐端口语义。",
            "blocks_document_authoring": False,
        })

    module_names: dict[str, str] = {}
    for source in sources:
        if source.get("kind") != "rtl":
            continue
        for statement in source.get("facts", []):
            if isinstance(statement, str) and statement.startswith("declared module "):
                module_names[statement.removeprefix("declared module ").strip()] = str(source["id"])
    stripped = _strip_sv_comments(text)
    for module_name, source_id in module_names.items():
        if module_name == top:
            continue
        instance = re.search(
            rf"\b{re.escape(module_name)}\s+(?:#\s*\([^;]*?\)\s*)?([A-Za-z_][A-Za-z0-9_$]*)\s*\(",
            stripped,
            flags=re.DOTALL,
        )
        if instance is not None:
            result["hierarchy"].append(_fact(
                instance.group(1), f"direct child module {module_name}", [*top_refs, source_id],
            ))

    categorized: dict[str, set[tuple[str, str, str]]] = {
        "internal_structures": set(), "protocols": set(), "registers": set(),
        "error_interrupts": set(),
    }
    for source in sources:
        if source.get("kind") not in {
            "design-spec", "micro-architecture-spec", "interface-spec", "register-spec",
        }:
            continue
        for statement in source.get("facts", []):
            if not isinstance(statement, str):
                continue
            lower = statement.lower()
            targets: list[str] = []
            if re.search(r"\b(protocol|handshake|ready|valid|credit|axi|apb|ahb)\b|握手|协议", lower):
                targets.append("protocols")
            if re.search(r"\b(register|csr|regmap|mmio)\b|寄存器", lower):
                targets.append("registers")
            if re.search(r"\b(error|interrupt|irq|fault|exception)\b|错误|中断|异常", lower):
                targets.append("error_interrupts")
            if re.search(r"\b(fsm|fifo|pipeline|buffer|queue|credit)\b|状态机|流水|缓冲", lower):
                targets.append("internal_structures")
            identity = REQUIREMENT_ID.search(statement)
            name = identity.group(0) if identity is not None else statement[:80]
            for target in targets:
                categorized[target].add((name, statement, str(source["id"])))
    for target, values in categorized.items():
        result[target].extend(
            _fact(name, f"explicit source statement: {statement}", [source_id])
            for name, statement, source_id in sorted(values)
        )
    return result, gaps


def _gap_for_requirement(item: dict[str, Any]) -> dict[str, Any]:
    source_kind = str(item["source_kind"])
    return {
        "id": "gap:source:" + re.sub(r"[^a-z0-9]+", "-", source_kind.lower()).strip("-"),
        "missing_source": source_kind,
        "impact": f"当前项目没有可用的 {source_kind}，无法把相关撰写指令绑定到项目事实。",
        "required_review": (
            "负责人补充来源，或明确记录该来源对当前 DUT 不适用及替代依据；Agent 不得补写不存在的事实。"
        ),
        "blocks_document_authoring": bool(item["required"]),
    }


def _gap_for_dut_fact(field: str, blocking: bool = False) -> dict[str, Any]:
    return {
        "id": f"gap:dut-fact:{field.replace('_', '-')}",
        "missing_source": f"dut-scope.{field}",
        "impact": f"当前来源尚未形成 DUT-specific {field} 事实，相关章节只能保留待确认项。",
        "required_review": "由 DV/Design/Interface owner 对照 RTL 与对应规格补齐或确认不适用。",
        "blocks_document_authoring": blocking,
    }


def build_authoring_proposal(
    project_root: Path, document_keys: Iterable[str] = (),
) -> dict[str, Any]:
    root = project_root.resolve()
    project_path = root / ".verif-harness" / "project.json"
    if not project_path.is_file():
        raise DocumentAuthoringError("项目尚未 bootstrap；缺少 .verif-harness/project.json")
    manifest = _json(project_path)
    profiles = load_authoring_profiles()
    common = load_common_rules()
    selected = (
        list(dict.fromkeys(str(item) for item in document_keys))
        or list(AUTHORING_DOCUMENT_ORDER)
    )
    unknown = sorted(set(selected) - set(profiles))
    if unknown:
        raise DocumentAuthoringError("未知 verification document profile: " + ", ".join(unknown))
    selected_set = set(selected)
    missing_dependencies = sorted({
        dependency
        for key in selected
        for dependency in profiles[key]["dependencies"]
        if dependency not in selected_set
    })
    if missing_dependencies:
        raise DocumentAuthoringError(
            "选择的 authoring profiles 缺少依赖: " + ", ".join(missing_dependencies)
        )

    sources = _collect_sources(root, manifest, profiles)
    dut_scope, dut_gaps = _dut_scope(root, manifest, sources)
    nodes: list[dict[str, Any]] = []
    for key in selected:
        profile = profiles[key]
        requirements = _merge_source_requirements(common, profile)
        relevant_sources = [
            source for source in sources
            if any(_source_matches(str(requirement["source_kind"]), source) for requirement in requirements)
        ]
        gaps = [dict(item) for item in dut_gaps]
        for requirement in requirements:
            matches = [source for source in relevant_sources if _source_matches(str(requirement["source_kind"]), source)]
            usable = [source for source in matches if source.get("status") == "available"]
            if not usable:
                gaps.append(_gap_for_requirement(requirement))
        for field in profile["dut_fact_requirements"]:
            if field not in DUT_SCOPE_FIELDS:
                raise DocumentAuthoringError(f"profile {key} dut_fact_requirements 无效: {field}")
            value = dut_scope[field]
            if field == "dut_top":
                if value.get("name") == "unresolved":
                    gaps.append(_gap_for_dut_fact(field, True))
            elif not value:
                gaps.append(_gap_for_dut_fact(field))
        unique_gaps = {item["id"]: item for item in gaps}
        profile_info = {
            "schema": AUTHORING_PROFILE_SCHEMA,
            "document_key": key,
            "filename": profile["filename"],
            "node_key": profile["node_key"],
            "profile_digest": profile["profile_digest"],
        }
        sections = [dict(item) for item in profile["document_structure"]]
        contract = {
            "schema": AUTHORING_CONTRACT_SCHEMA,
            "profile": profile_info,
            "generation": {
                "engine": AUTHORING_ENGINE_VERSION,
                "project_revision": manifest.get("baseline_revision"),
                "project_context_digest": _project_context_digest(manifest),
            },
            "source_requirements": requirements,
            "source_snapshot": relevant_sources,
            "source_gaps": list(unique_gaps.values()),
            "dut_scope": dut_scope,
            "rtl_spec_analysis_method": [
                *common["rtl_spec_analysis_method"], *profile.get("rtl_spec_analysis_method", []),
            ],
            "document_dependencies": list(profile["dependencies"]),
            "document_structure": sections,
            "section_authoring_instructions": [
                dict(item) for item in profile["section_authoring_instructions"]
            ],
            "required_tables": [dict(item) for item in profile["required_tables"]],
            "domain_rules": list(profile["domain_rules"]),
            "cross_document_consistency_rules": [
                *common["cross_document_consistency_rules"], *profile["cross_document_rules"],
            ],
            "traceability_requirements": [
                *common["traceability_requirements"], *profile["traceability_rules"],
            ],
            "review": {
                "roles": list(dict.fromkeys([*common["review_roles"], *profile["review_roles"]])),
                "criteria": [*common["review_criteria"], *profile["review_criteria"]],
            },
            "freeze": {
                "criteria": [*common["freeze_criteria"], *profile["freeze_criteria"]],
            },
            "change_invalidation_rules": [
                *common["change_invalidation_rules"], *profile["change_invalidation_rules"],
            ],
        }
        source_refs = [str(item["path"]) for item in relevant_sources]
        source_refs.extend(str(item["id"]) for item in contract["source_gaps"])
        nodes.append({
            "key": profile["node_key"],
            "title": profile["title"],
            "role": "document-writing-plan",
            "parent_key": key,
            "document_key": key,
            "required": True,
            "statement": f"为当前 DUT 定义 {profile['filename']} 的项目级撰写方法、结构、表格、追溯和签核约束。",
            "purpose": profile["purpose"],
            "scope": [
                f"DUT top: {dut_scope['dut_top']['name']}",
                *[str(item["purpose"]) for item in sections],
            ],
            "acceptance_criteria": [
                "来源快照绑定真实文件与 SHA-256；缺失或冲突的信息已进入 source_gaps",
                "DUT scope、章节级指令、required tables、领域规则、追溯和变更失效规则完整",
                "节点只定义如何撰写，不包含最终正文、正文验收或验证通过结论",
            ],
            "source_refs": source_refs or ["gap:source:no-usable-source"],
            "work_content": [
                *[f"{item['section']}: {item['purpose']}" for item in sections],
                *[f"领域规则: {item}" for item in profile["domain_rules"]],
            ],
            "implementation_approach": list(contract["rtl_spec_analysis_method"]),
            "deliverables": [
                f"结构化 {profile['node_key']} authoring node",
                f"供后续 {profile['filename']} 正文节点使用的 {AUTHORING_CONTRACT_SCHEMA}",
            ],
            "progress_measures": [{
                "id": f"{profile['node_key']}-reviewed",
                "label": f"已审批的 {profile['filename']} 撰写合同",
                "unit": "authoring contract", "target": "1",
                "source": AUTHORING_CONTRACT_SCHEMA,
            }],
            "quality_checks": [
                *contract["review"]["criteria"],
                "不存在没有 source ref 的 DUT 事实，也不把 source gap 改写成确定语义",
            ],
            "suggested_mode": "review",
            "evidence_claim": "document-review",
            "authoring_contract": contract,
        })
    proposal = {"schema": "DesiredStateProposal/1", "workstream": "VDOC", "nodes": nodes}
    for node in nodes:
        normalize_authoring_contract(node["authoring_contract"], str(node["document_key"]), root)
    return proposal


def _validate_fact(value: object, field: str, source_ids: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"name", "detail", "source_refs"}:
        raise DocumentAuthoringError(f"{field} 必须且只能包含 name、detail、source_refs")
    name = str(value.get("name", "")).strip()
    detail = str(value.get("detail", "")).strip()
    refs = _non_empty_strings(value.get("source_refs"), f"{field}.source_refs")
    unknown = sorted(set(refs) - source_ids)
    if unknown:
        raise DocumentAuthoringError(f"{field}.source_refs 引用了未知 source id: {', '.join(unknown)}")
    if not name or not detail:
        raise DocumentAuthoringError(f"{field} 的 name/detail 不能为空")
    return {"name": name, "detail": detail, "source_refs": refs}


def normalize_authoring_contract(
    value: object, document_key: str, project_root: Path,
) -> dict[str, Any]:
    prefix = f"authoring_contract[{document_key}]"
    if not isinstance(value, dict):
        raise DocumentAuthoringError(f"{prefix} 必须是 object")
    missing = sorted(CONTRACT_FIELDS - set(value))
    unexpected = sorted(set(value) - CONTRACT_FIELDS)
    if missing:
        raise DocumentAuthoringError(f"{prefix} 缺少字段: {', '.join(missing)}")
    if unexpected:
        raise DocumentAuthoringError(f"{prefix} 包含未支持字段: {', '.join(unexpected)}")
    if value.get("schema") != AUTHORING_CONTRACT_SCHEMA:
        raise DocumentAuthoringError(f"{prefix}.schema 必须是 {AUTHORING_CONTRACT_SCHEMA}")
    profiles = load_authoring_profiles()
    if document_key not in profiles:
        raise DocumentAuthoringError(f"{prefix} document profile 不存在")
    expected_profile = profiles[document_key]
    profile = value.get("profile")
    profile_fields = {"schema", "document_key", "filename", "node_key", "profile_digest"}
    if not isinstance(profile, dict) or set(profile) != profile_fields:
        raise DocumentAuthoringError(f"{prefix}.profile 字段无效")
    expected_profile_values = {
        "schema": AUTHORING_PROFILE_SCHEMA,
        "document_key": document_key,
        "filename": expected_profile["filename"],
        "node_key": expected_profile["node_key"],
        "profile_digest": expected_profile["profile_digest"],
    }
    if profile != expected_profile_values:
        raise DocumentAuthoringError(f"{prefix}.profile 与当前 registry/profile digest 不一致")

    root = project_root.resolve()
    manifest_path = root / ".verif-harness" / "project.json"
    manifest = _json(manifest_path)
    generation = value.get("generation")
    if not isinstance(generation, dict) or set(generation) != {
        "engine", "project_revision", "project_context_digest",
    }:
        raise DocumentAuthoringError(f"{prefix}.generation 字段无效")
    if generation.get("engine") != AUTHORING_ENGINE_VERSION:
        raise DocumentAuthoringError(f"{prefix}.generation.engine 无效")
    if generation.get("project_context_digest") != _project_context_digest(manifest):
        raise DocumentAuthoringError(f"{prefix} 绑定的 project context 已变化；请重新生成 authoring plan")

    requirements = value.get("source_requirements")
    if not isinstance(requirements, list) or not requirements:
        raise DocumentAuthoringError(f"{prefix}.source_requirements 必须是非空对象数组")
    requirement_kinds: set[str] = set()
    normalized_requirements: list[dict[str, Any]] = []
    for index, item in enumerate(requirements):
        field = f"{prefix}.source_requirements[{index}]"
        if not isinstance(item, dict) or set(item) != {"source_kind", "required", "purpose", "selection_rule"}:
            raise DocumentAuthoringError(f"{field} 字段无效")
        kind = str(item.get("source_kind", "")).strip()
        purpose = str(item.get("purpose", "")).strip()
        selection = str(item.get("selection_rule", "")).strip()
        required = item.get("required")
        if not kind or not purpose or not selection or not isinstance(required, bool):
            raise DocumentAuthoringError(f"{field} 包含空值或无效 required")
        if kind in requirement_kinds:
            raise DocumentAuthoringError(f"{field}.source_kind 重复: {kind}")
        requirement_kinds.add(kind)
        normalized_requirements.append(dict(item))

    snapshot = value.get("source_snapshot")
    if not isinstance(snapshot, list) or not snapshot:
        raise DocumentAuthoringError(f"{prefix}.source_snapshot 必须是非空对象数组")
    source_ids: set[str] = set()
    normalized_sources: list[dict[str, Any]] = []
    for index, item in enumerate(snapshot):
        field = f"{prefix}.source_snapshot[{index}]"
        if not isinstance(item, dict):
            raise DocumentAuthoringError(f"{field} 必须是 object")
        allowed = {"id", "kind", "path", "sha256", "status", "anchors", "facts", "document_key"}
        required_fields = {"id", "kind", "path", "sha256", "status", "anchors", "facts"}
        if not required_fields.issubset(item) or set(item) - allowed:
            raise DocumentAuthoringError(f"{field} 字段无效")
        source_id = str(item.get("id", "")).strip()
        kind = str(item.get("kind", "")).strip()
        path_value = str(item.get("path", "")).strip()
        digest = str(item.get("sha256", "")).strip()
        status = str(item.get("status", "")).strip()
        if not source_id or not kind or not path_value or status not in {"available", "template-only"}:
            raise DocumentAuthoringError(f"{field} 包含空值或无效 status")
        if source_id in source_ids:
            raise DocumentAuthoringError(f"{field}.id 重复: {source_id}")
        source_ids.add(source_id)
        path = _resolve(root, path_value)
        if not _path_is_allowed(root, manifest, path) or not path.is_file():
            raise DocumentAuthoringError(f"{field}.path 不是已登记的当前项目来源: {path_value}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or _digest_bytes(path.read_bytes()) != digest:
            raise DocumentAuthoringError(f"{field}.sha256 与当前文件不一致: {path_value}")
        _non_empty_strings(item.get("anchors"), f"{field}.anchors") if item.get("anchors") else []
        _non_empty_strings(item.get("facts"), f"{field}.facts") if item.get("facts") else []
        normalized_sources.append(dict(item))

    gaps = value.get("source_gaps")
    if not isinstance(gaps, list):
        raise DocumentAuthoringError(f"{prefix}.source_gaps 必须是数组")
    gap_ids: set[str] = set()
    normalized_gaps: list[dict[str, Any]] = []
    for index, item in enumerate(gaps):
        field = f"{prefix}.source_gaps[{index}]"
        expected = {"id", "missing_source", "impact", "required_review", "blocks_document_authoring"}
        if not isinstance(item, dict) or set(item) != expected:
            raise DocumentAuthoringError(f"{field} 字段无效")
        strings = {name: str(item.get(name, "")).strip() for name in expected - {"blocks_document_authoring"}}
        if not all(strings.values()) or not isinstance(item.get("blocks_document_authoring"), bool):
            raise DocumentAuthoringError(f"{field} 包含空值或无效 blocks_document_authoring")
        if strings["id"] in gap_ids:
            raise DocumentAuthoringError(f"{field}.id 重复: {strings['id']}")
        gap_ids.add(strings["id"])
        normalized_gaps.append(dict(item))
    for requirement in normalized_requirements:
        matches = [item for item in normalized_sources if _source_matches(str(requirement["source_kind"]), item)]
        usable = [item for item in matches if item.get("status") == "available"]
        gap = [item for item in normalized_gaps if item.get("missing_source") == requirement["source_kind"]]
        if not usable and not gap:
            raise DocumentAuthoringError(
                f"{prefix} 来源 {requirement['source_kind']} 既没有 available snapshot，也没有 source gap"
            )

    scope = value.get("dut_scope")
    if not isinstance(scope, dict) or set(scope) != DUT_SCOPE_FIELDS:
        raise DocumentAuthoringError(f"{prefix}.dut_scope 字段无效")
    normalized_scope: dict[str, Any] = {
        "dut_top": _validate_fact(scope["dut_top"], f"{prefix}.dut_scope.dut_top", source_ids),
    }
    for field in sorted(DUT_SCOPE_FIELDS - {"dut_top"}):
        raw = scope[field]
        if not isinstance(raw, list):
            raise DocumentAuthoringError(f"{prefix}.dut_scope.{field} 必须是数组")
        normalized_scope[field] = [
            _validate_fact(item, f"{prefix}.dut_scope.{field}[{index}]", source_ids)
            for index, item in enumerate(raw)
        ]

    dependencies = value.get("document_dependencies")
    if dependencies != expected_profile["dependencies"]:
        raise DocumentAuthoringError(f"{prefix}.document_dependencies 与 profile registry 不一致")
    for field in (
        "rtl_spec_analysis_method", "domain_rules", "cross_document_consistency_rules",
        "traceability_requirements", "change_invalidation_rules",
    ):
        _non_empty_strings(value.get(field), f"{prefix}.{field}")

    structure = value.get("document_structure")
    if not isinstance(structure, list) or not structure:
        raise DocumentAuthoringError(f"{prefix}.document_structure 必须是非空对象数组")
    section_names: set[str] = set()
    for index, item in enumerate(structure):
        field = f"{prefix}.document_structure[{index}]"
        if not isinstance(item, dict) or set(item) != {"section", "purpose", "required"}:
            raise DocumentAuthoringError(f"{field} 字段无效")
        section = str(item.get("section", "")).strip()
        if not section or not str(item.get("purpose", "")).strip() or not isinstance(item.get("required"), bool):
            raise DocumentAuthoringError(f"{field} 包含空值或无效 required")
        if section in section_names:
            raise DocumentAuthoringError(f"{field}.section 重复: {section}")
        section_names.add(section)
    instructions = value.get("section_authoring_instructions")
    if not isinstance(instructions, list) or not instructions:
        raise DocumentAuthoringError(f"{prefix}.section_authoring_instructions 必须是非空对象数组")
    covered: set[str] = set()
    for index, item in enumerate(instructions):
        field = f"{prefix}.section_authoring_instructions[{index}]"
        if not isinstance(item, dict) or set(item) != {"section", "instructions", "required_source_kinds"}:
            raise DocumentAuthoringError(f"{field} 字段无效")
        section = str(item.get("section", "")).strip()
        if section not in section_names or section in covered:
            raise DocumentAuthoringError(f"{field}.section 未登记或重复: {section}")
        covered.add(section)
        _non_empty_strings(item.get("instructions"), f"{field}.instructions")
        _non_empty_strings(item.get("required_source_kinds"), f"{field}.required_source_kinds")
    required_sections = {str(item["section"]) for item in structure if item["required"]}
    missing_sections = sorted(required_sections - covered)
    if missing_sections:
        raise DocumentAuthoringError(f"{prefix} 缺少必需 section instructions: {', '.join(missing_sections)}")
    tables = value.get("required_tables")
    if not isinstance(tables, list) or not tables:
        raise DocumentAuthoringError(f"{prefix}.required_tables 必须是非空对象数组")
    for index, item in enumerate(tables):
        field = f"{prefix}.required_tables[{index}]"
        if not isinstance(item, dict) or set(item) != {"table", "purpose", "required_columns"}:
            raise DocumentAuthoringError(f"{field} 字段无效")
        if not str(item.get("table", "")).strip() or not str(item.get("purpose", "")).strip():
            raise DocumentAuthoringError(f"{field} table/purpose 不能为空")
        _non_empty_strings(item.get("required_columns"), f"{field}.required_columns")
    review = value.get("review")
    if not isinstance(review, dict) or set(review) != {"roles", "criteria"}:
        raise DocumentAuthoringError(f"{prefix}.review 字段无效")
    _non_empty_strings(review.get("roles"), f"{prefix}.review.roles")
    _non_empty_strings(review.get("criteria"), f"{prefix}.review.criteria")
    freeze = value.get("freeze")
    if not isinstance(freeze, dict) or set(freeze) != {"criteria"}:
        raise DocumentAuthoringError(f"{prefix}.freeze 字段无效")
    _non_empty_strings(freeze.get("criteria"), f"{prefix}.freeze.criteria")
    return {
        **value,
        "source_requirements": normalized_requirements,
        "source_snapshot": normalized_sources,
        "source_gaps": normalized_gaps,
        "dut_scope": normalized_scope,
    }
