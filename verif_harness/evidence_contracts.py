"""Deterministic validators for standard Workstream evidence contracts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .evidence_policy import ARTIFACT_KINDS, validate_artifact_policy


SHA256 = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[A-Za-z0-9_.:-]+$")
FEEDBACK_OWNERS = {"VDOC", "VENV", "VSTIM", "VCHK", "VCASE", "VCOV", "VREG", "DUT"}

CLAIMS: dict[str, dict[str, str]] = {
    "VENV": {
        "interface-ready": "interface-ready",
        "clock-reset-ready": "clock-reset-ready",
        "topology-ready": "topology-ready",
        "build-ready": "build-ready",
        "run-ready": "run-ready",
        "observation-ready": "observation-ready",
        "environment-smoke-evidence": "environment-smoke-evidence",
    },
    "VSTIM": {
        "transaction-contract": "transaction-contract",
        "stimulus-implementation": "stimulus-implementation",
        "corner-scenarios": "corner-scenarios",
    },
    "VCHK": {
        "compare-policy": "compare-policy",
        "reference-model": "reference-model",
        "scoreboard": "scoreboard",
        "assertions": "assertions",
        "reference-model-evidence": "reference-model-evidence",
        "scoreboard-evidence": "scoreboard-evidence",
        "assertion-evidence": "assertion-evidence",
    },
    "VCOV": {
        "coverage-model": "coverage-model",
        "coverage-collection": "coverage-collection",
        "coverage-collection-evidence": "coverage-collection-evidence",
        "hole-analysis": "hole-analysis-evidence",
        "hole-analysis-evidence": "hole-analysis-evidence",
    },
    "VCASE": {
        "case-matrix": "case-matrix",
        "case-implementation": "case-implementation",
        "targeted-evidence": "targeted-evidence",
    },
    "VREG": {
        "regression-policy": "regression-policy",
        "executor-ready": "executor-ready",
        "execution": "execution-evidence",
        "execution-evidence": "execution-evidence",
        "triage": "triage-evidence",
        "triage-evidence": "triage-evidence",
        "fresh-evidence": "fresh-evidence",
    },
}

SCHEMAS = {
    "VENV": "EnvironmentEvidence/1",
    "VSTIM": "StimulusCapabilityEvidence/1",
    "VCHK": "CheckingEvidence/1",
    "VCOV": "CoverageEvidence/1",
    "VCASE": "TestcaseEvidence/2",
    "VREG": "RegressionEvidence/3",
}

LEGACY_SCHEMAS = {
    "VCASE": "TestcaseEvidence/1",
    "VREG": "RegressionEvidence/1",
}


class EvidenceContractError(ValueError):
    """A malformed Workstream evidence report."""


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceContractError(f"{field} 必须是非空字符串")
    return value.strip()


def _integer(value: object, field: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise EvidenceContractError(f"{field} 必须是大于等于 {minimum} 的整数")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise EvidenceContractError(f"{field} 必须是布尔值")
    return value


def _seed(value: object, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise EvidenceContractError(f"{field} 必须是非空字符串或整数")
    result = str(value).strip()
    if not result:
        raise EvidenceContractError(f"{field} 必须是非空字符串或整数")
    return result


def _digest(value: object, field: str) -> str:
    result = _text(value, field)
    if not SHA256.fullmatch(result):
        raise EvidenceContractError(f"{field} 必须是小写 SHA-256")
    return result


def _strings(value: object, field: str, unique: bool = False) -> list[str]:
    if not isinstance(value, list) or not value:
        raise EvidenceContractError(f"{field} 必须是非空字符串数组")
    result = [_text(item, f"{field}[]") for item in value]
    if unique and len(result) != len(set(result)):
        raise EvidenceContractError(f"{field} 不能包含重复项")
    return result


def _objects(value: object, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise EvidenceContractError(f"{field} 必须是对象数组")
    if not all(isinstance(item, dict) for item in value):
        raise EvidenceContractError(f"{field} 必须只包含对象")
    return value


def _base(path: Path, workstream: str, expected_claim: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceContractError(f"无法读取 evidence JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvidenceContractError("evidence 顶层必须是对象")
    expected_schema = SCHEMAS[workstream]
    accepted_schemas = {expected_schema, LEGACY_SCHEMAS.get(workstream)} - {None}
    if workstream == "VREG":
        accepted_schemas.add("RegressionEvidence/2")
    if payload.get("schema") not in accepted_schemas:
        raise EvidenceContractError(f"schema 必须是 " + " 或 ".join(sorted(accepted_schemas)))
    claim = _text(payload.get("claim"), "claim")
    if claim != expected_claim:
        raise EvidenceContractError(f"claim 必须是 {expected_claim}")
    revision = _text(payload.get("revision"), "revision")
    tool = _text(payload.get("tool"), "tool")
    artifact_items = _objects(payload.get("artifacts"), "artifacts")
    if not artifact_items:
        raise EvidenceContractError("artifacts 不能为空")
    artifacts: list[dict[str, Any]] = []
    artifact_paths: set[str] = set()
    for index, artifact in enumerate(artifact_items):
        artifact_path = _text(artifact.get("path"), f"artifacts[{index}].path")
        if artifact_path in artifact_paths:
            raise EvidenceContractError(f"artifacts path 重复: {artifact_path}")
        artifact_paths.add(artifact_path)
        kind = _text(artifact.get("kind"), f"artifacts[{index}].kind")
        if kind not in ARTIFACT_KINDS:
            raise EvidenceContractError(
                f"artifacts[{index}].kind 必须是 " + ", ".join(sorted(ARTIFACT_KINDS))
            )
        analyzed_by = _strings(
            artifact.get("analyzed_by"), f"artifacts[{index}].analyzed_by", unique=True,
        )
        artifacts.append({
            "path": artifact_path,
            "sha256": _digest(artifact.get("sha256"), f"artifacts[{index}].sha256"),
            "kind": kind,
            "analyzed_by": analyzed_by,
        })
    result = payload.get("result")
    if not isinstance(result, dict):
        raise EvidenceContractError("result 必须是对象")
    normalized = {
        "schema": payload["schema"], "workstream": workstream, "claim": claim,
        "revision": revision, "tool": tool, "artifacts": artifacts,
    }
    admission_policy, admission_blockers = validate_artifact_policy(
        workstream, expected_claim, artifacts, schema=payload["schema"],
    )
    normalized["admission_policy"] = admission_policy
    normalized["admission_blockers"] = admission_blockers
    return payload, result, normalized


def _finish(normalized: dict[str, Any], blockers: list[str], facts: dict[str, Any]) -> dict[str, Any]:
    blockers = [*normalized.pop("admission_blockers", []), *blockers]
    normalized.update({"ready": not blockers, "blockers": blockers, "facts": facts})
    return normalized


def _bound_digest(normalized: dict[str, Any], value: object, field: str) -> str:
    digest = _digest(value, field)
    artifact_digests = {artifact["sha256"] for artifact in normalized["artifacts"]}
    if digest not in artifact_digests:
        raise EvidenceContractError(f"{field} 未绑定到 artifacts 中的 native artifact")
    return digest


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _artifact_file(
    evidence_path: Path, normalized: dict[str, Any], artifact_root: Path | None,
    artifact_path: str, artifact_digest: str, kind: str, field: str,
) -> Path:
    matches = [
        item for item in normalized["artifacts"]
        if item["path"] == artifact_path and item["sha256"] == artifact_digest
        and item["kind"] == kind
    ]
    if len(matches) != 1:
        raise EvidenceContractError(f"{field} 必须唯一绑定 artifacts 中的 {kind}")
    root = (artifact_root or evidence_path.parent).resolve()
    target = (root / artifact_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise EvidenceContractError(f"{field} 路径必须属于当前项目") from exc
    try:
        if hashlib.sha256(target.read_bytes()).hexdigest() != artifact_digest:
            raise EvidenceContractError(f"{field} 文件摘要变化，必须重新验证")
    except OSError as exc:
        raise EvidenceContractError(f"无法读取 {field}: {exc}") from exc
    return target


def _json_artifact(
    evidence_path: Path, normalized: dict[str, Any], artifact_root: Path | None,
    artifact_digest: object, kind: str, schema: str, field: str,
) -> tuple[dict[str, Any], str]:
    digest = _bound_digest(normalized, artifact_digest, field)
    matches = [item for item in normalized["artifacts"]
               if item["sha256"] == digest and item["kind"] == kind]
    if len(matches) != 1:
        raise EvidenceContractError(f"{field} 必须唯一绑定 artifacts 中的 {kind}")
    target = _artifact_file(
        evidence_path, normalized, artifact_root, matches[0]["path"], digest, kind, field,
    )
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceContractError(f"无法读取 {field}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        raise EvidenceContractError(f"{field} schema 必须是 {schema}")
    return payload, digest


def _submit_profile_ref(
    evidence_path: Path, normalized: dict[str, Any], artifact_root: Path | None,
    value: object, field: str,
) -> dict[str, str]:
    if not isinstance(value, dict) or value.get("schema") != "SubmitProfileRef/1":
        raise EvidenceContractError(f"{field}.schema 必须是 SubmitProfileRef/1")
    profile_id = _text(value.get("profile_id"), f"{field}.profile_id")
    if not ID.fullmatch(profile_id):
        raise EvidenceContractError(f"{field}.profile_id 非法")
    submit_file = _text(value.get("submit_file"), f"{field}.submit_file")
    submit_path = Path(submit_file)
    if submit_path.is_absolute() or ".." in submit_path.parts:
        raise EvidenceContractError(f"{field}.submit_file 必须是项目内相对路径")
    submit_file_digest = _digest(value.get("submit_file_digest"), f"{field}.submit_file_digest")
    profile_digest = _digest(value.get("profile_digest"), f"{field}.profile_digest")
    adapter = value.get("adapter")
    if not isinstance(adapter, dict):
        raise EvidenceContractError(f"{field}.adapter 必须是对象")
    adapter_name = _text(adapter.get("name"), f"{field}.adapter.name")
    adapter_version = _text(adapter.get("version"), f"{field}.adapter.version")
    _artifact_file(
        evidence_path, normalized, artifact_root, submit_file, submit_file_digest,
        "configuration", f"{field}.submit_file",
    )
    return {
        "schema": "SubmitProfileRef/1", "profile_id": profile_id,
        "submit_file": submit_file, "submit_file_digest": submit_file_digest,
        "profile_digest": profile_digest, "adapter_name": adapter_name,
        "adapter_version": adapter_version,
    }


def _case_manifest(
    evidence_path: Path, normalized: dict[str, Any], artifact_root: Path | None,
    manifest_digest: object, field: str,
) -> dict[str, Any]:
    manifest, digest = _json_artifact(
        evidence_path, normalized, artifact_root, manifest_digest,
        "case-manifest", "CaseManifest/1", field,
    )
    case_id = _text(manifest.get("case_id"), "case_manifest.case_id")
    if not re.fullmatch(r"[A-Za-z_]\w*", case_id):
        raise EvidenceContractError("case_manifest.case_id 非法")
    entry = manifest.get("entry")
    if not isinstance(entry, dict):
        raise EvidenceContractError("case_manifest.entry 必须是对象")
    entry_kind = _text(entry.get("kind"), "case_manifest.entry.kind")
    if entry_kind not in {"testcase", "sequence"}:
        raise EvidenceContractError("case_manifest.entry.kind 必须是 testcase/sequence")
    entry_name = _text(entry.get("name"), "case_manifest.entry.name")
    if not re.fullmatch(r"[A-Za-z_]\w*", entry_name):
        raise EvidenceContractError("case_manifest.entry.name 非法")
    launcher_test = ""
    if entry_kind == "sequence":
        launcher_test = _text(entry.get("launcher_test"), "case_manifest.entry.launcher_test")
        if not re.fullmatch(r"[A-Za-z_]\w*", launcher_test):
            raise EvidenceContractError("case_manifest.entry.launcher_test 非法")
    sources = _objects(manifest.get("source_files"), "case_manifest.source_files")
    if not sources:
        raise EvidenceContractError("case_manifest.source_files 不能为空")
    normalized_sources: list[dict[str, str]] = []
    for index, source in enumerate(sources):
        source_path = _text(source.get("path"), f"case_manifest.source_files[{index}].path")
        source_digest = _digest(source.get("sha256"), f"case_manifest.source_files[{index}].sha256")
        _artifact_file(
            evidence_path, normalized, artifact_root, source_path, source_digest,
            "source", f"case_manifest.source_files[{index}]",
        )
        normalized_sources.append({"path": source_path, "sha256": source_digest})
    profile = _submit_profile_ref(
        evidence_path, normalized, artifact_root, manifest.get("submit_profile"),
        "case_manifest.submit_profile",
    )
    case_digest = _digest(manifest.get("case_digest"), "case_manifest.case_digest")
    expected = _canonical_digest({key: value for key, value in manifest.items() if key != "case_digest"})
    if case_digest != expected:
        raise EvidenceContractError("case_manifest.case_digest 与当前 manifest 内容不一致")
    return {
        "id": case_id, "case_digest": case_digest, "manifest_digest": digest,
        "entry_kind": entry_kind, "entry_name": entry_name,
        "launcher_test": launcher_test, "source_files": normalized_sources,
        "submit_profile": profile,
    }


def _venv(path: Path, claim: str) -> dict[str, Any]:
    _payload, result, normalized = _base(path, "VENV", claim)
    blockers: list[str] = []
    if claim == "interface-ready":
        interfaces = _objects(result.get("interfaces"), "result.interfaces")
        if not interfaces:
            raise EvidenceContractError("result.interfaces 不能为空")
        seen: set[str] = set()
        normalized_interfaces: list[dict[str, Any]] = []
        for index, item in enumerate(interfaces):
            prefix = f"result.interfaces[{index}]"
            interface_id = _text(item.get("id"), f"{prefix}.id")
            if interface_id in seen:
                blockers.append(f"重复 interface: {interface_id}")
            seen.add(interface_id)
            connected = _boolean(item.get("connected"), f"{prefix}.connected")
            virtual_interface_set = _boolean(
                item.get("virtual_interface_set"), f"{prefix}.virtual_interface_set"
            )
            source_digest = _bound_digest(
                normalized, item.get("source_digest"), f"{prefix}.source_digest"
            )
            if not connected:
                blockers.append(f"{interface_id} 尚未连接 DUT")
            if not virtual_interface_set:
                blockers.append(f"{interface_id} virtual interface 尚未配置")
            normalized_interfaces.append({
                "id": interface_id, "connected": connected,
                "virtual_interface_set": virtual_interface_set,
                "source_digest": source_digest,
            })
        facts = {"interfaces": normalized_interfaces}
    elif claim == "clock-reset-ready":
        clocks = _objects(result.get("clocks"), "result.clocks")
        resets = _objects(result.get("resets"), "result.resets")
        if not clocks or not resets:
            raise EvidenceContractError("result.clocks 和 result.resets 不能为空")
        normalized_clocks: list[dict[str, Any]] = []
        normalized_resets: list[dict[str, Any]] = []
        for index, item in enumerate(clocks):
            clock_id = _text(item.get("id"), f"result.clocks[{index}].id")
            configured = _boolean(item.get("configured"), f"result.clocks[{index}].configured")
            if not configured:
                blockers.append(f"clock {clock_id} 尚未配置")
            normalized_clocks.append({"id": clock_id, "configured": configured})
        for index, item in enumerate(resets):
            reset_id = _text(item.get("id"), f"result.resets[{index}].id")
            configured = _boolean(item.get("configured"), f"result.resets[{index}].configured")
            if not configured:
                blockers.append(f"reset {reset_id} 尚未配置")
            normalized_resets.append({"id": reset_id, "configured": configured})
        facts = {
            "clocks": normalized_clocks, "resets": normalized_resets,
            "implementation_digest": _bound_digest(
                normalized, result.get("implementation_digest"), "result.implementation_digest"
            ),
        }
    elif claim == "topology-ready":
        components = _objects(result.get("components"), "result.components")
        if not components:
            raise EvidenceContractError("result.components 不能为空")
        normalized_components: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(components):
            prefix = f"result.components[{index}]"
            component_id = _text(item.get("id"), f"{prefix}.id")
            if component_id in seen:
                blockers.append(f"重复 component: {component_id}")
            seen.add(component_id)
            kind = _text(item.get("kind"), f"{prefix}.kind")
            constructed = _boolean(item.get("constructed"), f"{prefix}.constructed")
            connected = _boolean(item.get("connected"), f"{prefix}.connected")
            if not constructed or not connected:
                blockers.append(f"{component_id} 尚未完成构建和连接")
            normalized_components.append({
                "id": component_id, "kind": kind,
                "constructed": constructed, "connected": connected,
            })
        facts = {
            "components": normalized_components,
            "topology_digest": _bound_digest(
                normalized, result.get("topology_digest"), "result.topology_digest"
            ),
        }
    elif claim == "build-ready":
        compiled = _boolean(result.get("compiled"), "result.compiled")
        elaborated = _boolean(result.get("elaborated"), "result.elaborated")
        errors = _integer(result.get("errors"), "result.errors")
        if not compiled:
            blockers.append("验证环境编译未通过")
        if not elaborated:
            blockers.append("验证环境 elaboration 未通过")
        if errors:
            blockers.append(f"验证环境构建包含 {errors} 个 error")
        facts = {
            "compiled": compiled, "elaborated": elaborated, "errors": errors,
            "build_log_digest": _bound_digest(
                normalized, result.get("build_log_digest"), "result.build_log_digest"
            ),
            "environment_digest": _bound_digest(
                normalized, result.get("environment_digest"), "result.environment_digest"
            ),
        }
    elif claim == "run-ready":
        selftest_passed = _boolean(result.get("selftest_passed"), "result.selftest_passed")
        clean_exit = _boolean(result.get("clean_exit"), "result.clean_exit")
        failure_propagated = _boolean(
            result.get("failure_propagated"), "result.failure_propagated"
        )
        if not selftest_passed:
            blockers.append("最小运行入口自检未通过")
        if not clean_exit:
            blockers.append("最小运行入口不能正常结束")
        if not failure_propagated:
            blockers.append("仿真错误未传递到命令退出状态")
        facts = {
            "selftest_passed": selftest_passed,
            "clean_exit": clean_exit,
            "failure_propagated": failure_propagated,
            "command_digest": _bound_digest(
                normalized, result.get("command_digest"), "result.command_digest"
            ),
            "collector_digest": _bound_digest(
                normalized, result.get("collector_digest"), "result.collector_digest"
            ),
        }
    elif claim == "observation-ready":
        points = _objects(result.get("points"), "result.points")
        if not points:
            raise EvidenceContractError("result.points 不能为空")
        normalized_points: list[dict[str, Any]] = []
        for index, item in enumerate(points):
            prefix = f"result.points[{index}]"
            point_id = _text(item.get("id"), f"{prefix}.id")
            boundary = _text(item.get("boundary"), f"{prefix}.boundary")
            connected = _boolean(item.get("connected"), f"{prefix}.connected")
            if boundary not in {"dut-input", "dut-output", "dut-state", "driver-monitor"}:
                blockers.append(f"{point_id} observation boundary 未识别: {boundary}")
            if not connected:
                blockers.append(f"{point_id} 观测点尚未连接")
            normalized_points.append({"id": point_id, "boundary": boundary, "connected": connected})
        facts = {
            "points": normalized_points,
            "implementation_digest": _bound_digest(
                normalized, result.get("implementation_digest"), "result.implementation_digest"
            ),
        }
    else:
        clock_edges = _integer(result.get("clock_edges"), "result.clock_edges")
        reset_assertions = _integer(result.get("reset_assertions"), "result.reset_assertions")
        reset_deassertions = _integer(result.get("reset_deassertions"), "result.reset_deassertions")
        observations = _integer(result.get("observations"), "result.observations")
        errors = _integer(result.get("errors"), "result.errors")
        fatals = _integer(result.get("fatals"), "result.fatals")
        timeout = _boolean(result.get("timeout"), "result.timeout")
        clean_exit = _boolean(result.get("clean_exit"), "result.clean_exit")
        if clock_edges == 0:
            blockers.append("smoke 未观察到 clock edge")
        if reset_assertions == 0 or reset_deassertions == 0:
            blockers.append("smoke 未观察到完整 reset assert/deassert")
        if observations == 0:
            blockers.append("smoke 未产生验证侧观测记录")
        if errors or fatals:
            blockers.append(f"smoke 包含 errors={errors}, fatals={fatals}")
        if timeout:
            blockers.append("smoke 发生 timeout")
        if not clean_exit:
            blockers.append("smoke 未正常结束")
        facts = {
            "clock_edges": clock_edges, "reset_assertions": reset_assertions,
            "reset_deassertions": reset_deassertions, "observations": observations,
            "errors": errors, "fatals": fatals, "timeout": timeout, "clean_exit": clean_exit,
            "environment_digest": _bound_digest(
                normalized, result.get("environment_digest"), "result.environment_digest"
            ),
            "log_digest": _bound_digest(normalized, result.get("log_digest"), "result.log_digest"),
        }
    return _finish(normalized, blockers, facts)


def _vstim(path: Path, claim: str) -> dict[str, Any]:
    _payload, result, normalized = _base(path, "VSTIM", claim)
    blockers: list[str] = []
    if claim == "transaction-contract":
        transactions = _objects(result.get("transactions"), "result.transactions")
        if not transactions:
            raise EvidenceContractError("result.transactions 不能为空")
        seen: set[str] = set()
        normalized_transactions: list[dict[str, Any]] = []
        for index, item in enumerate(transactions):
            prefix = f"result.transactions[{index}]"
            transaction_id = _text(item.get("id"), f"{prefix}.id")
            if transaction_id in seen:
                blockers.append(f"重复 transaction: {transaction_id}")
            seen.add(transaction_id)
            direction = _text(item.get("direction"), f"{prefix}.direction")
            if direction not in {"input", "output", "bidirectional"}:
                raise EvidenceContractError(f"{prefix}.direction 必须是 input/output/bidirectional")
            fields = _strings(item.get("fields"), f"{prefix}.fields", unique=True)
            handshake = _text(item.get("handshake"), f"{prefix}.handshake")
            normalized_transactions.append({
                "id": transaction_id, "direction": direction,
                "fields": fields, "handshake": handshake,
            })
        facts = {
            "contract_ref": _text(result.get("contract_ref"), "result.contract_ref"),
            "contract_digest": _bound_digest(
                normalized, result.get("contract_digest"), "result.contract_digest"
            ),
            "review_ref": _text(result.get("review_ref"), "result.review_ref"),
            "transactions": normalized_transactions,
        }
    elif claim == "stimulus-implementation":
        required = set(_strings(result.get("required_features"), "result.required_features", unique=True))
        components = _objects(result.get("components"), "result.components")
        if not components:
            raise EvidenceContractError("result.components 不能为空")
        implemented: set[str] = set()
        component_ids: set[str] = set()
        normalized_components: list[dict[str, Any]] = []
        for index, item in enumerate(components):
            prefix = f"result.components[{index}]"
            component_id = _text(item.get("id"), f"{prefix}.id")
            if component_id in component_ids:
                blockers.append(f"重复 stimulus component: {component_id}")
            component_ids.add(component_id)
            kind = _text(item.get("kind"), f"{prefix}.kind")
            if kind not in {"driver", "sequence", "constraint", "generator"}:
                raise EvidenceContractError(f"{prefix}.kind 非法")
            features = _strings(item.get("features"), f"{prefix}.features", unique=True)
            compiled = _boolean(item.get("compiled"), f"{prefix}.compiled")
            registered = _boolean(item.get("registered"), f"{prefix}.registered")
            digest = _bound_digest(normalized, item.get("source_digest"), f"{prefix}.source_digest")
            implemented.update(features)
            if not compiled or not registered:
                blockers.append(f"{component_id} 未注册或未编译")
            normalized_components.append({
                "id": component_id, "kind": kind, "features": features,
                "compiled": compiled, "registered": registered, "source_digest": digest,
            })
        missing = sorted(required - implemented)
        if missing:
            blockers.append("缺少 stimulus implementation: " + ", ".join(missing))
        facts = {
            "required_features": sorted(required), "implemented_features": sorted(implemented),
            "missing_features": missing, "components": normalized_components,
        }
    else:
        required = set(_strings(result.get("required_scenarios"), "result.required_scenarios", unique=True))
        mappings = _objects(result.get("mappings"), "result.mappings")
        mapped: set[str] = set()
        normalized_mappings: list[dict[str, str]] = []
        for index, item in enumerate(mappings):
            prefix = f"result.mappings[{index}]"
            scenario = _text(item.get("scenario"), f"{prefix}.scenario")
            generator = _text(item.get("generator"), f"{prefix}.generator")
            if scenario in mapped:
                blockers.append(f"重复 corner scenario mapping: {scenario}")
            mapped.add(scenario)
            normalized_mappings.append({"scenario": scenario, "generator": generator})
        missing = sorted(required - mapped)
        if missing:
            blockers.append("未映射 required corner scenario: " + ", ".join(missing))
        facts = {
            "required_scenarios": sorted(required), "mapped_scenarios": sorted(mapped),
            "missing_scenarios": missing, "mappings": normalized_mappings,
        }
    return _finish(normalized, blockers, facts)


def _vchk(path: Path, claim: str) -> dict[str, Any]:
    _payload, result, normalized = _base(path, "VCHK", claim)
    blockers: list[str] = []
    facts: dict[str, Any] = {}
    if claim == "compare-policy":
        facts = {
            "policy_ref": _text(result.get("policy_ref"), "result.policy_ref"),
            "policy_digest": _bound_digest(normalized, result.get("policy_digest"), "result.policy_digest"),
            "review_ref": _text(result.get("review_ref"), "result.review_ref"),
        }
    elif claim in {"reference-model", "scoreboard"}:
        configured = _boolean(result.get("configured"), "result.configured")
        compiled = _boolean(result.get("compiled"), "result.compiled")
        implementation_digest = _bound_digest(
            normalized, result.get("implementation_digest"), "result.implementation_digest"
        )
        if not configured or not compiled:
            blockers.append(f"{claim} 尚未完成配置或编译")
        facts = {"configured": configured, "compiled": compiled,
                 "implementation_digest": implementation_digest}
    elif claim == "assertions":
        planned = _integer(result.get("planned"), "result.planned", 1)
        compiled = _integer(result.get("compiled"), "result.compiled")
        bound = _integer(result.get("bound"), "result.bound")
        implementation_digest = _bound_digest(
            normalized, result.get("implementation_digest"), "result.implementation_digest"
        )
        if compiled != planned or bound != planned:
            blockers.append(f"assertion capability 不完整: planned={planned}, compiled={compiled}, bound={bound}")
        facts = {"planned": planned, "compiled": compiled, "bound": bound,
                 "implementation_digest": implementation_digest}
    elif claim in {"reference-model-evidence", "scoreboard-evidence"}:
        engaged = _boolean(result.get("engaged"), "result.engaged")
        comparisons = _integer(result.get("comparisons"), "result.comparisons")
        mismatches = _integer(result.get("mismatches"), "result.mismatches")
        residual = _integer(result.get("residual"), "result.residual")
        implementation_digest = _bound_digest(
            normalized, result.get("implementation_digest"), "result.implementation_digest"
        )
        label = claim.removesuffix("-evidence")
        if not engaged:
            blockers.append(f"{label} 未实际 engaged")
        if comparisons == 0:
            blockers.append(f"{label} comparisons 为 0")
        if mismatches:
            blockers.append(f"{label} 有 {mismatches} 个 mismatch")
        if residual:
            blockers.append(f"{label} 有 {residual} 个 residual transaction")
        facts = {"engaged": engaged, "comparisons": comparisons, "mismatches": mismatches,
                 "residual": residual, "implementation_digest": implementation_digest}
    else:
        assertions = _objects(result.get("assertions"), "result.assertions")
        if not assertions:
            raise EvidenceContractError("result.assertions 不能为空")
        seen: set[str] = set()
        attempts = failures = 0
        for index, item in enumerate(assertions):
            prefix = f"result.assertions[{index}]"
            item_id = _text(item.get("id"), f"{prefix}.id")
            if not ID.fullmatch(item_id):
                raise EvidenceContractError(f"{prefix}.id 非法")
            if item_id in seen:
                blockers.append(f"重复 assertion: {item_id}")
            seen.add(item_id)
            compiled = _boolean(item.get("compiled"), f"{prefix}.compiled")
            bound = _boolean(item.get("bound"), f"{prefix}.bound")
            item_attempts = _integer(item.get("attempts"), f"{prefix}.attempts")
            item_failures = _integer(item.get("failures"), f"{prefix}.failures")
            vacuous = _boolean(item.get("vacuous"), f"{prefix}.vacuous")
            _text(item.get("plan_ref"), f"{prefix}.plan_ref")
            attempts += item_attempts
            failures += item_failures
            if not compiled or not bound or item_attempts == 0 or item_failures or vacuous:
                blockers.append(f"{item_id} 未编译/挂接/激活，或存在 failure/vacuity")
        facts = {"assertions": len(assertions), "attempts": attempts, "failures": failures}
    return _finish(normalized, blockers, facts)


def _valid_waiver(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    required = ("id", "reviewer", "decision_date", "rationale", "status")
    try:
        if not all(_text(value.get(key), f"waiver.{key}") for key in required):
            return False
        if value["status"] != "Approved":
            return False
        date.fromisoformat(str(value["decision_date"]))
    except (EvidenceContractError, ValueError):
        return False
    return True


def _coverage_manifest(
    path: Path, result: dict[str, Any], normalized: dict[str, Any], artifact_root: Path | None,
) -> tuple[dict[str, Any], list[str]]:
    """Read the item universe from the bound analysis artifact, not report counts."""
    if result.get("coverage_manifest_digest") is None:
        return {}, ["覆盖率证据缺少当前覆盖项清单，必须重新验证"]
    digest = _bound_digest(
        normalized, result.get("coverage_manifest_digest"), "result.coverage_manifest_digest",
    )
    matches = [artifact for artifact in normalized["artifacts"]
               if artifact["sha256"] == digest and artifact["kind"] == "analysis-report"
               and "xverif" in artifact["analyzed_by"]]
    if len(matches) != 1:
        raise EvidenceContractError("coverage_manifest_digest 必须唯一绑定 xverif 分析的覆盖项清单")
    root = (artifact_root or path.parent).resolve()
    manifest_path = (root / matches[0]["path"]).resolve()
    try:
        manifest_path.relative_to(root)
    except ValueError as exc:
        raise EvidenceContractError("覆盖项清单路径必须属于当前项目") from exc
    try:
        raw = manifest_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise EvidenceContractError("覆盖项清单文件摘要变化，必须重新验证")
        manifest = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceContractError(f"无法读取覆盖项清单：{exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != "CoverageItemManifest/1":
        raise EvidenceContractError("覆盖项清单 schema 必须是 CoverageItemManifest/1")
    planned = _strings(manifest.get("planned_item_ids"), "manifest.planned_item_ids", unique=True)
    mapped = _strings(manifest.get("mapped_item_ids"), "manifest.mapped_item_ids", unique=True)
    if any(not ID.fullmatch(item_id) for item_id in planned + mapped):
        raise EvidenceContractError("覆盖项清单中的覆盖项 ID 非法")
    missing = sorted(set(planned) - set(mapped))
    unexpected = sorted(set(mapped) - set(planned))
    blockers = []
    if missing:
        blockers.append("覆盖模型未实现计划覆盖项：" + ", ".join(missing))
    if unexpected:
        blockers.append("覆盖模型包含未登记计划的覆盖项：" + ", ".join(unexpected))
    return {
        "coverage_manifest_digest": digest,
        "plan_digest": _digest(manifest.get("plan_digest"), "manifest.plan_digest"),
        "model_digest": _digest(manifest.get("model_digest"), "manifest.model_digest"),
        "required_item_ids": sorted(planned), "mapped_item_ids": sorted(mapped),
    }, blockers


def _vcov(path: Path, claim: str, artifact_root: Path | None = None) -> dict[str, Any]:
    _payload, result, normalized = _base(path, "VCOV", claim)
    blockers: list[str] = []
    if claim == "coverage-model":
        planned = _integer(result.get("planned_items"), "result.planned_items", 1)
        mapped = _integer(result.get("mapped_items"), "result.mapped_items")
        compiled = _boolean(result.get("compiled"), "result.compiled")
        facts = {"plan_digest": _bound_digest(normalized, result.get("plan_digest"), "result.plan_digest"),
                 "model_digest": _bound_digest(normalized, result.get("model_digest"), "result.model_digest"),
                 "planned_items": planned, "mapped_items": mapped, "compiled": compiled}
        manifest_facts, manifest_blockers = _coverage_manifest(path, result, normalized, artifact_root)
        blockers.extend(manifest_blockers)
        if manifest_facts:
            if (facts["plan_digest"] != manifest_facts["plan_digest"]
                    or facts["model_digest"] != manifest_facts["model_digest"]):
                blockers.append("覆盖项清单与本次覆盖计划或模型版本不一致")
            if (planned != len(manifest_facts["required_item_ids"])
                    or mapped != len(manifest_facts["mapped_item_ids"])):
                blockers.append("覆盖项数量与受控清单不一致")
            facts.update(manifest_facts)
        if mapped != planned:
            blockers.append(f"coverage mapping 不完整: {mapped}/{planned}")
        if not compiled:
            blockers.append("coverage model 未编译")
    elif claim == "coverage-collection":
        configured = _boolean(result.get("configured"), "result.configured")
        exporter_digest = _bound_digest(normalized, result.get("exporter_digest"), "result.exporter_digest")
        if not configured:
            blockers.append("coverage collector/exporter 尚未配置")
        facts = {"configured": configured, "exporter_digest": exporter_digest}
    elif claim == "coverage-collection-evidence":
        databases = _strings(result.get("database_ids"), "result.database_ids", unique=True)
        runs = _integer(result.get("runs"), "result.runs", 1)
        merge_errors = _integer(result.get("merge_errors"), "result.merge_errors")
        stale_shards = _integer(result.get("stale_shards"), "result.stale_shards")
        facts = {"database_ids": databases, "runs": runs, "merge_errors": merge_errors,
                 "stale_shards": stale_shards}
        manifest_facts, manifest_blockers = _coverage_manifest(path, result, normalized, artifact_root)
        facts.update(manifest_facts)
        blockers.extend(manifest_blockers)
        if merge_errors:
            blockers.append(f"coverage merge errors={merge_errors}")
        if stale_shards:
            blockers.append(f"coverage stale shards={stale_shards}")
    else:
        items = _objects(result.get("items"), "result.items")
        if not items:
            raise EvidenceContractError("result.items 不能为空")
        seen: set[str] = set()
        counts = {"covered": 0, "excluded": 0, "uncovered": 0}
        normalized_items: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            prefix = f"result.items[{index}]"
            item_id = _text(item.get("id"), f"{prefix}.id")
            if not ID.fullmatch(item_id):
                raise EvidenceContractError(f"{prefix}.id 非法")
            if item_id in seen:
                blockers.append(f"重复 coverage item: {item_id}")
            seen.add(item_id)
            status = _text(item.get("status"), f"{prefix}.status")
            if status not in counts:
                raise EvidenceContractError(f"{prefix}.status 必须是 covered/excluded/uncovered")
            hits = _integer(item.get("hits"), f"{prefix}.hits")
            plan_ref = _text(item.get("plan_ref"), f"{prefix}.plan_ref")
            owner = str(item.get("responsible_workstream") or "").strip().upper()
            next_action = str(item.get("next_action") or "").strip()
            target_key = str(item.get("target_implementation_key") or "").strip()
            counts[status] += 1
            if status == "covered" and hits == 0:
                blockers.append(f"{item_id} 声明 covered 但 hits=0")
            elif status == "uncovered":
                blockers.append(f"{item_id} 尚未覆盖")
                if owner not in FEEDBACK_OWNERS:
                    blockers.append(f"{item_id} 必须明确反馈责任工作流或 DUT")
                if not next_action:
                    blockers.append(f"{item_id} 必须说明下一步补洞或分析动作")
            elif status == "excluded" and not _valid_waiver(item.get("waiver")):
                blockers.append(f"{item_id} 的排除项缺少完整的负责人例外评审信息")
            normalized_items.append({
                "id": item_id, "status": status, "hits": hits, "plan_ref": plan_ref,
                "responsible_workstream": owner, "next_action": next_action,
                "target_implementation_key": target_key,
                "waiver": dict(item["waiver"]) if isinstance(item.get("waiver"), dict) else {},
            })
        manifest_facts, manifest_blockers = _coverage_manifest(path, result, normalized, artifact_root)
        blockers.extend(manifest_blockers)
        if manifest_facts:
            required = set(manifest_facts["required_item_ids"])
            missing = sorted(required - seen)
            unexpected = sorted(seen - required)
            if missing:
                blockers.append("缺口分析遗漏计划覆盖项：" + ", ".join(missing))
            if unexpected:
                blockers.append("缺口分析包含未登记计划的覆盖项：" + ", ".join(unexpected))
        facts = {**counts, "item_count": len(items), "items": normalized_items, **manifest_facts}
    return _finish(normalized, blockers, facts)


def _vcase(path: Path, claim: str, artifact_root: Path | None = None) -> dict[str, Any]:
    _payload, result, normalized = _base(path, "VCASE", claim)
    blockers: list[str] = []
    legacy = normalized["schema"] == LEGACY_SCHEMAS["VCASE"]
    if claim == "case-matrix":
        required = set(_strings(result.get("required_features"), "result.required_features", unique=True))
        mappings = _objects(result.get("mappings"), "result.mappings")
        mapped: set[str] = set()
        normalized_mappings: list[dict[str, Any]] = []
        for index, item in enumerate(mappings):
            feature = _text(item.get("feature"), f"result.mappings[{index}].feature")
            cases = _strings(item.get("cases"), f"result.mappings[{index}].cases", unique=True)
            if feature in mapped:
                blockers.append(f"重复 feature mapping: {feature}")
            mapped.add(feature)
            normalized_mappings.append({"feature": feature, "cases": cases})
        missing = sorted(required - mapped)
        if missing:
            blockers.append("未映射 required feature: " + ", ".join(missing))
        facts = {"required_features": sorted(required), "mapped_features": sorted(mapped),
                 "missing": missing, "mappings": normalized_mappings}
    elif claim == "case-implementation":
        cases = _objects(result.get("cases"), "result.cases")
        if not cases:
            raise EvidenceContractError("result.cases 不能为空")
        seen: set[str] = set()
        seen_variants: set[tuple[str, str]] = set()
        case_records: list[dict[str, Any]] = []
        for index, item in enumerate(cases):
            prefix = f"result.cases[{index}]"
            if legacy:
                case_id = _text(item.get("id"), f"{prefix}.id")
                _bound_digest(normalized, item.get("source_digest"), f"{prefix}.source_digest")
            else:
                manifest = _case_manifest(
                    path, normalized, artifact_root, item.get("manifest_digest"),
                    f"{prefix}.manifest_digest",
                )
                case_id = manifest["id"]
                case_records.append(manifest)
            if legacy and case_id in seen:
                blockers.append(f"重复 testcase: {case_id}")
            if not legacy:
                variant = (case_id, manifest["submit_profile"]["profile_digest"])
                if variant in seen_variants:
                    blockers.append(
                        f"重复 runnable case: {case_id}/{manifest['submit_profile']['profile_id']}"
                    )
                seen_variants.add(variant)
            seen.add(case_id)
            registered = _boolean(item.get("registered"), f"{prefix}.registered")
            compiled = _boolean(item.get("compiled"), f"{prefix}.compiled")
            if not registered or not compiled:
                blockers.append(f"{case_id} 未注册或未编译")
        facts = {"cases": sorted(seen), "case_count": len(cases)}
        if not legacy:
            facts["case_records"] = sorted(case_records, key=lambda item: item["id"])
    else:
        runs = _objects(result.get("runs"), "result.runs")
        if not runs:
            raise EvidenceContractError("result.runs 不能为空")
        seen: set[tuple[object, ...]] = set()
        run_records: list[dict[str, Any]] = []
        for index, item in enumerate(runs):
            prefix = f"result.runs[{index}]"
            if legacy:
                case_id = _text(item.get("case"), f"{prefix}.case")
                case_digest = ""
                profile_id = ""
                profile_digest = ""
                iteration = 0
            else:
                case_id = _text(item.get("case_id"), f"{prefix}.case_id")
                case_digest = _digest(item.get("case_digest"), f"{prefix}.case_digest")
                profile_id = _text(item.get("submit_profile_id"), f"{prefix}.submit_profile_id")
                if not ID.fullmatch(profile_id):
                    raise EvidenceContractError(f"{prefix}.submit_profile_id 非法")
                profile_digest = _digest(
                    item.get("submit_profile_digest"), f"{prefix}.submit_profile_digest"
                )
                iteration = _integer(item.get("iteration"), f"{prefix}.iteration")
            seed = _seed(item.get("seed"), f"{prefix}.seed")
            key = ((case_id, seed) if legacy else
                   (case_id, case_digest, profile_digest, seed, iteration))
            if key in seen:
                blockers.append(f"重复 targeted run: {case_id}/{seed}/{iteration}")
            seen.add(key)
            verdict = _text(item.get("verdict"), f"{prefix}.verdict")
            errors = _integer(item.get("uvm_error"), f"{prefix}.uvm_error")
            fatals = _integer(item.get("uvm_fatal"), f"{prefix}.uvm_fatal")
            log_digest = _bound_digest(normalized, item.get("log_digest"), f"{prefix}.log_digest")
            checker_engaged = True
            checks = 1
            if not legacy:
                checker_engaged = _boolean(
                    item.get("checker_engaged"), f"{prefix}.checker_engaged"
                )
                checks = _integer(item.get("checks"), f"{prefix}.checks")
            if verdict != "PASS" or errors or fatals:
                blockers.append(f"{case_id}/{seed} targeted run 未通过")
            if not checker_engaged or checks == 0:
                blockers.append(f"{case_id}/{seed} 未证明 checker 已实际参与")
            if not legacy:
                run_records.append({
                    "case_id": case_id, "case_digest": case_digest,
                    "submit_profile_id": profile_id,
                    "submit_profile_digest": profile_digest, "seed": seed,
                    "iteration": iteration, "verdict": verdict,
                    "uvm_error": errors, "uvm_fatal": fatals,
                    "checker_engaged": checker_engaged, "checks": checks,
                    "log_digest": log_digest,
                })
        executed_cases = sorted(
            {str(key[0]) for key in seen}
        )
        facts = {"runs": len(runs), "executed_cases": executed_cases}
        if not legacy:
            facts["run_records"] = run_records
    return _finish(normalized, blockers, facts)


def _regression_batch_manifest(
    evidence_path: Path, normalized: dict[str, Any], artifact_root: Path | None,
    manifest_digest: object, field: str,
) -> dict[str, Any]:
    modern = normalized["schema"] == "RegressionEvidence/3"
    manifest, digest = _json_artifact(
        evidence_path, normalized, artifact_root, manifest_digest,
        "regression-manifest", "RegressionBatchManifest/2" if modern else "RegressionBatchManifest/1", field,
    )
    batch_id = _text(manifest.get("batch_id"), "batch_manifest.batch_id")
    if not ID.fullmatch(batch_id):
        raise EvidenceContractError("batch_manifest.batch_id 非法")
    regression_group = _text(
        manifest.get("regression_group"), "batch_manifest.regression_group"
    )
    if modern and not ID.fullmatch(regression_group):
        raise EvidenceContractError("batch_manifest.regression_group 非法")
    profile = _submit_profile_ref(
        evidence_path, normalized, artifact_root, manifest.get("submit_profile"),
        "batch_manifest.submit_profile",
    )
    caselist = manifest.get("caselist")
    if not isinstance(caselist, dict):
        raise EvidenceContractError("batch_manifest.caselist 必须是对象")
    caselist_path = _text(caselist.get("path"), "batch_manifest.caselist.path")
    caselist_digest = _digest(caselist.get("sha256"), "batch_manifest.caselist.sha256")
    _artifact_file(
        evidence_path, normalized, artifact_root, caselist_path, caselist_digest,
        "regression-manifest", "batch_manifest.caselist",
    )
    cases = _objects(manifest.get("cases"), "batch_manifest.cases")
    if not cases:
        raise EvidenceContractError("batch_manifest.cases 不能为空")
    seen: set[str] = set()
    normalized_cases: list[dict[str, str]] = []
    for index, item in enumerate(cases):
        prefix = f"batch_manifest.cases[{index}]"
        case_id = _text(item.get("case_id"), f"{prefix}.case_id")
        if not re.fullmatch(r"[A-Za-z_]\w*", case_id):
            raise EvidenceContractError(f"{prefix}.case_id 非法")
        if case_id in seen:
            raise EvidenceContractError(f"batch {batch_id} 包含重复 case: {case_id}")
        seen.add(case_id)
        normalized_cases.append({
            "case_id": case_id,
            "case_digest": _digest(item.get("case_digest"), f"{prefix}.case_digest"),
        })
    repeat = _integer(manifest.get("repeat"), "batch_manifest.repeat", 1)
    batch = {
        "schema": manifest["schema"],
        "batch_id": batch_id, "manifest_digest": digest,
        "regression_group": regression_group, "submit_profile": profile,
        "caselist_path": caselist_path, "caselist_digest": caselist_digest,
        "repeat": repeat,
        "timeout_seconds": _integer(
            manifest.get("timeout_seconds"), "batch_manifest.timeout_seconds", 1
        ),
        "cases": normalized_cases,
    }
    if not modern:
        batch["seed"] = _seed(manifest.get("seed"), "batch_manifest.seed")
        return batch
    batch["submit_profile"] = {
        key: profile[key] for key in (
            "schema", "profile_id", "submit_file", "submit_file_digest", "profile_digest",
        )
    }
    batch["submit_profile"]["adapter"] = {
        "name": profile["adapter_name"], "version": profile["adapter_version"],
    }
    seed_mode = _text(manifest.get("seed_mode"), "batch_manifest.seed_mode")
    if seed_mode not in {"random", "fixed"}:
        raise EvidenceContractError("batch_manifest.seed_mode 必须是 random/fixed")
    fixed_seed = None
    if seed_mode == "fixed":
        fixed_seed = _regression_seed(manifest.get("seed"), "batch_manifest.seed")
        batch["seed"] = fixed_seed
    elif "seed" in manifest:
        raise EvidenceContractError("random batch 不得声明固定 seed；实际 seed 必须逐次记录")
    runs = _objects(manifest.get("runs"), "batch_manifest.runs")
    if not runs:
        raise EvidenceContractError("batch_manifest.runs 不能为空")
    normalized_runs = []
    run_ids: set[tuple[str, int]] = set()
    case_seeds: dict[str, set[str]] = {}
    for index, item in enumerate(runs):
        prefix = f"batch_manifest.runs[{index}]"
        if set(item) != {"case_id", "seed", "iteration"}:
            raise EvidenceContractError(f"{prefix} 只接受计划运行字段，失败重跑不得计入 repeat")
        case_id = _text(item.get("case_id"), f"{prefix}.case_id")
        iteration = _integer(item.get("iteration"), f"{prefix}.iteration")
        seed = _regression_seed(item.get("seed"), f"{prefix}.seed")
        key = (case_id, iteration)
        if case_id not in seen or iteration >= repeat:
            raise EvidenceContractError(f"{prefix} 不属于 batch 的 case/repeat 范围")
        if key in run_ids:
            raise EvidenceContractError(f"重复 batch 计划运行：{case_id}/{iteration}")
        run_ids.add(key)
        seeds = case_seeds.setdefault(case_id, set())
        if seed_mode == "random" and seed in seeds:
            raise EvidenceContractError(f"random batch 的 {case_id} 每次 iteration 必须记录新 seed")
        if seed_mode == "fixed" and seed != fixed_seed:
            raise EvidenceContractError(f"fixed batch 的 {case_id} 必须使用批准的同一 seed")
        seeds.add(seed)
        normalized_runs.append({"case_id": case_id, "seed": seed, "iteration": iteration})
    expected_ids = {(case_id, iteration) for case_id in seen for iteration in range(repeat)}
    if run_ids != expected_ids:
        raise EvidenceContractError("batch 计划运行必须完整覆盖每个 case 的全部 repeat 次数")
    batch.update(seed_mode=seed_mode, runs=normalized_runs,
                 execution_binding=_execution_binding(manifest.get("execution_binding"), "batch_manifest.execution_binding"))
    return batch


def _execution_binding(value: object, field: str) -> dict[str, Any]:
    from .vreg_contract import normalize_binding
    try:
        return normalize_binding(value)
    except ValueError as exc:
        raise EvidenceContractError(f"{field}: {exc}") from exc


def _regression_seed(value: object, field: str) -> str:
    from .vreg_contract import seed_value
    try:
        return seed_value(value)
    except ValueError as exc:
        raise EvidenceContractError(f"{field}: {exc}") from exc


def _vreg(path: Path, claim: str, artifact_root: Path | None = None) -> dict[str, Any]:
    _payload, result, normalized = _base(path, "VREG", claim)
    blockers: list[str] = []
    legacy = normalized["schema"] == LEGACY_SCHEMAS["VREG"]
    modern = normalized["schema"] == "RegressionEvidence/3"
    binding = (_execution_binding(result.get("execution_binding"), "result.execution_binding")
               if modern and claim in {"execution-evidence", "triage-evidence", "fresh-evidence"}
               else None)
    if claim == "regression-policy":
        facts = {"policy_digest": _bound_digest(normalized, result.get("policy_digest"), "result.policy_digest"),
                 "manifest_digest": _bound_digest(normalized, result.get("manifest_digest"), "result.manifest_digest"),
                 "review_ref": _text(result.get("review_ref"), "result.review_ref"),
                 "seed_policy": _text(result.get("seed_policy"), "result.seed_policy"),
                 "timeout_policy": _text(result.get("timeout_policy"), "result.timeout_policy"),
                 "rerun_policy": _text(result.get("rerun_policy"), "result.rerun_policy")}
    elif claim == "executor-ready":
        runner_digest = _bound_digest(normalized, result.get("runner_digest"), "result.runner_digest")
        collector_digest = _bound_digest(normalized, result.get("collector_digest"), "result.collector_digest")
        selftest_passed = _boolean(result.get("selftest_passed"), "result.selftest_passed")
        if not selftest_passed:
            blockers.append("regression executor self-test 未通过")
        facts = {"runner_digest": runner_digest, "collector_digest": collector_digest,
                 "selftest_passed": selftest_passed}
    elif claim == "execution-evidence":
        golden_required = _boolean(result.get("golden_required"), "result.golden_required")
        batches: list[dict[str, Any]] = []
        expected_runs: dict[tuple[str, str, str, int], dict[str, Any]] = {}
        if legacy:
            _text(result.get("batch_seed"), "result.batch_seed")
            _bound_digest(normalized, result.get("manifest_digest"), "result.manifest_digest")
        else:
            manifest_digests = _strings(
                result.get("batch_manifest_digests"),
                "result.batch_manifest_digests", unique=True,
            )
            batch_ids: set[str] = set()
            for index, manifest_digest in enumerate(manifest_digests):
                batch = _regression_batch_manifest(
                    path, normalized, artifact_root, manifest_digest,
                    f"result.batch_manifest_digests[{index}]",
                )
                if batch["batch_id"] in batch_ids:
                    blockers.append(f"重复 regression batch: {batch['batch_id']}")
                batch_ids.add(batch["batch_id"])
                batches.append(batch)
                if modern and batch["execution_binding"] != binding:
                    blockers.append(f"batch {batch['batch_id']} 与证据报告的批准方案或执行轮次不一致")
                case_versions = {case["case_id"]: case["case_digest"] for case in batch["cases"]}
                planned_runs = batch["runs"] if modern else [
                    {"case_id": case["case_id"], "seed": batch["seed"], "iteration": iteration}
                    for case in batch["cases"] for iteration in range(batch["repeat"])
                ]
                for run in planned_runs:
                    key = (batch["batch_id"], run["case_id"], run["seed"], run["iteration"])
                    expected_runs[key] = {
                        "case_digest": case_versions[run["case_id"]],
                        "submit_profile_id": batch["submit_profile"]["profile_id"],
                        "submit_profile_digest": batch["submit_profile"]["profile_digest"],
                    }
        results = _objects(result.get("results"), "result.results")
        if not results:
            raise EvidenceContractError("result.results 不能为空")
        seen: set[object] = set()
        acceptable_pass = {"PASS"} if golden_required else {"PASS", "PASS-LIVE"}
        recognized = acceptable_pass | {"FAIL", "ERROR", "TIMEOUT"}
        failed_runs: list[dict[str, Any]] = []
        run_records: list[dict[str, Any]] = []
        for index, item in enumerate(results):
            prefix = f"result.results[{index}]"
            if modern and "rerun_kind" in item:
                raise EvidenceContractError(f"{prefix} 不接受失败重跑，必须单独登记 triage-evidence")
            if legacy:
                test = _text(item.get("test"), f"{prefix}.test")
                run_key: object = test
                batch_id = ""
                iteration = 0
                case_digest = ""
                profile_id = ""
                profile_digest = ""
            else:
                batch_id = _text(item.get("batch_id"), f"{prefix}.batch_id")
                test = _text(item.get("case_id"), f"{prefix}.case_id")
                case_digest = _digest(item.get("case_digest"), f"{prefix}.case_digest")
                profile_id = _text(item.get("submit_profile_id"), f"{prefix}.submit_profile_id")
                if not ID.fullmatch(profile_id):
                    raise EvidenceContractError(f"{prefix}.submit_profile_id 非法")
                profile_digest = _digest(
                    item.get("submit_profile_digest"), f"{prefix}.submit_profile_digest"
                )
                iteration = _integer(item.get("iteration"), f"{prefix}.iteration")
            verdict = _text(item.get("verdict"), f"result.results[{index}].verdict")
            seed = (_regression_seed if modern else _seed)(item.get("seed"), f"{prefix}.seed")
            run_key = test if legacy else (batch_id, test, seed, iteration)
            if run_key in seen:
                blockers.append(
                    f"重复 regression run: {batch_id + '/' if batch_id else ''}{test}/{seed}/{iteration}"
                )
            seen.add(run_key)
            log_digest = _bound_digest(normalized, item.get("log_digest"), f"{prefix}.log_digest")
            if not legacy:
                expected = expected_runs.get(run_key)
                if expected is None:
                    blockers.append(f"{batch_id}/{test}/{seed}/{iteration} 不在 batch manifest 中")
                else:
                    if case_digest != expected["case_digest"]:
                        blockers.append(f"{batch_id}/{test} case digest 与 batch manifest 不一致")
                    if (profile_id != expected["submit_profile_id"] or
                            profile_digest != expected["submit_profile_digest"]):
                        blockers.append(f"{batch_id}/{test} submit profile 与 batch manifest 不一致")
                run_record = {
                    "batch_id": batch_id, "case_id": test, "seed": seed, "iteration": iteration,
                    "case_digest": case_digest, "submit_profile_id": profile_id,
                    "submit_profile_digest": profile_digest, "verdict": verdict, "log_digest": log_digest,
                }
                if modern:
                    run_record["execution_binding"] = binding
                run_records.append(run_record)
            if verdict not in recognized:
                blockers.append(f"{test} verdict 未识别: {verdict}")
            elif verdict not in acceptable_pass:
                failed = {"test": test, "seed": seed, "verdict": verdict}
                if not legacy:
                    failed.update({
                        "batch_id": batch_id, "case_id": test, "iteration": iteration,
                        "case_digest": case_digest, "submit_profile_id": profile_id,
                        "submit_profile_digest": profile_digest,
                    })
                failed_runs.append(failed)
        if not legacy:
            missing = sorted(set(expected_runs) - {key for key in seen if isinstance(key, tuple)})
            if missing:
                blockers.append("回归 batch 缺少执行结果：" + "、".join(
                    f"{batch}/{case}/{seed}/{iteration}"
                    for batch, case, seed, iteration in missing
                ))
        facts = {"tests": len(results), "golden_required": golden_required,
                 "acceptable_pass_verdicts": sorted(acceptable_pass),
                 "failed_runs": failed_runs}
        if not legacy:
            facts.update({"batch_count": len(batches), "batches": batches,
                          "run_records": run_records, "runs": run_records})
    elif claim == "triage-evidence":
        failures = _objects(result.get("failures"), "result.failures")
        normalized_failures: list[dict[str, Any]] = []
        seen_failures: set[tuple[object, ...]] = set()
        for index, item in enumerate(failures):
            prefix = f"result.failures[{index}]"
            if legacy:
                test = _text(item.get("test"), f"{prefix}.test")
                batch_id = ""
                iteration = 0
            else:
                batch_id = _text(item.get("batch_id"), f"{prefix}.batch_id")
                test = _text(item.get("case_id"), f"{prefix}.case_id")
                iteration = _integer(item.get("iteration"), f"{prefix}.iteration")
            original_seed = (_regression_seed if modern else _seed)(item.get("original_seed"), f"{prefix}.original_seed")
            rerun_seed = (_regression_seed if modern else _seed)(item.get("rerun_seed"), f"{prefix}.rerun_seed")
            rerun_kind = ""
            if modern:
                rerun_kind = _text(item.get("rerun_kind"), f"{prefix}.rerun_kind")
                if rerun_kind != "failure-rerun":
                    raise EvidenceContractError(f"{prefix}.rerun_kind 必须是 failure-rerun，不能作为计划 repeat")
            failure_key = ((test, original_seed) if legacy else
                           (batch_id, test, original_seed, iteration))
            if failure_key in seen_failures:
                blockers.append(f"重复 triage failure: {batch_id}/{test}/{original_seed}/{iteration}")
            seen_failures.add(failure_key)
            classification = _text(item.get("classification"), f"{prefix}.classification")
            disposition = _text(item.get("disposition"), f"{prefix}.disposition")
            rerun_verdict = _text(item.get("rerun_verdict"), f"{prefix}.rerun_verdict")
            owner = str(item.get("responsible_workstream") or "").strip().upper()
            next_action = str(item.get("next_action") or "").strip()
            target_key = str(item.get("target_implementation_key") or "").strip()
            rerun_log_digest = _bound_digest(
                normalized, item.get("rerun_log_digest"), f"{prefix}.rerun_log_digest"
            )
            if rerun_seed != original_seed:
                blockers.append(f"{test} 缺少 same-seed rerun")
            if classification == "UNCLASSIFIED":
                blockers.append(f"{test} 尚未分类")
            if disposition not in {"fixed", "accepted-known-fail", "rerun-pass"}:
                blockers.append(f"{test} disposition 未关闭")
                if owner not in FEEDBACK_OWNERS:
                    blockers.append(f"{test} 必须明确反馈责任工作流或 DUT")
                if not next_action:
                    blockers.append(f"{test} 必须说明下一步定位或修复动作")
            if disposition in {"fixed", "rerun-pass"} and rerun_verdict != "PASS":
                blockers.append(f"{test} disposition={disposition} 但 same-seed rerun 未 PASS")
            if disposition == "accepted-known-fail" and rerun_verdict not in {"FAIL", "ERROR", "TIMEOUT"}:
                blockers.append(f"{test} known-fail 的 rerun verdict 非失败结果")
            if disposition == "accepted-known-fail" and not _text(item.get("waiver_ref"), f"{prefix}.waiver_ref"):
                blockers.append(f"{test} 的已知失败缺少负责人例外评审引用")
            failure_record = {
                "test": test, "original_seed": original_seed, "rerun_seed": rerun_seed,
                "classification": classification, "disposition": disposition,
                "rerun_verdict": rerun_verdict, "rerun_log_digest": rerun_log_digest,
                "waiver_ref": str(item.get("waiver_ref") or ""),
                "responsible_workstream": owner, "next_action": next_action,
                "target_implementation_key": target_key,
            }
            if not legacy:
                failure_record.update({
                    "batch_id": batch_id, "case_id": test, "iteration": iteration,
                })
            if modern:
                failure_record.update(rerun_kind=rerun_kind, execution_binding=binding)
            normalized_failures.append(failure_record)
        facts = {"failures": normalized_failures, "failure_count": len(failures)}
    else:
        snapshot_revision = _text(result.get("snapshot_revision"), "result.snapshot_revision")
        facts = {"snapshot_revision": snapshot_revision, "required_nodes": []}
    if binding is not None:
        facts["execution_binding"] = binding
    if modern:
        facts["schema"] = normalized["schema"]
    return _finish(normalized, blockers, facts)


VALIDATORS: dict[str, Callable[[Path, str], dict[str, Any]]] = {
    "VENV": _venv,
    "VSTIM": _vstim,
    "VCHK": _vchk,
    "VCOV": _vcov,
    "VCASE": _vcase,
    "VREG": _vreg,
}


def validate_workstream_evidence(
    path: Path, workstream: str, claim: str, *, artifact_root: Path | None = None,
) -> dict[str, Any]:
    if workstream not in VALIDATORS:
        raise EvidenceContractError(f"{workstream} 没有专用 evidence validator")
    if claim not in CLAIMS[workstream].values():
        raise EvidenceContractError(f"{workstream} 不支持 claim={claim}")
    if workstream == "VCOV":
        return _vcov(path, claim, artifact_root)
    if workstream == "VCASE":
        return _vcase(path, claim, artifact_root)
    if workstream == "VREG":
        return _vreg(path, claim, artifact_root)
    return VALIDATORS[workstream](path, claim)
