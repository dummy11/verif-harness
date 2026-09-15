"""Deterministic validators for standard Workstream evidence contracts."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Callable


SHA256 = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[A-Za-z0-9_.:-]+$")

CLAIMS: dict[str, dict[str, str]] = {
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
    "VSTIM": "StimulusCapabilityEvidence/1",
    "VCHK": "CheckingEvidence/1",
    "VCOV": "CoverageEvidence/1",
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
    if payload.get("schema") != expected_schema:
        raise EvidenceContractError(f"schema 必须是 {expected_schema}")
    claim = _text(payload.get("claim"), "claim")
    if claim != expected_claim:
        raise EvidenceContractError(f"claim 必须是 {expected_claim}")
    revision = _text(payload.get("revision"), "revision")
    tool = _text(payload.get("tool"), "tool")
    artifact_items = _objects(payload.get("artifacts"), "artifacts")
    if not artifact_items:
        raise EvidenceContractError("artifacts 不能为空")
    artifacts: list[dict[str, str]] = []
    artifact_paths: set[str] = set()
    for index, artifact in enumerate(artifact_items):
        artifact_path = _text(artifact.get("path"), f"artifacts[{index}].path")
        if artifact_path in artifact_paths:
            raise EvidenceContractError(f"artifacts path 重复: {artifact_path}")
        artifact_paths.add(artifact_path)
        artifacts.append({"path": artifact_path,
                          "sha256": _digest(artifact.get("sha256"), f"artifacts[{index}].sha256")})
    result = payload.get("result")
    if not isinstance(result, dict):
        raise EvidenceContractError("result 必须是对象")
    normalized = {
        "schema": expected_schema, "workstream": workstream, "claim": claim,
        "revision": revision, "tool": tool, "artifacts": artifacts,
    }
    return payload, result, normalized


def _finish(normalized: dict[str, Any], blockers: list[str], facts: dict[str, Any]) -> dict[str, Any]:
    normalized.update({"ready": not blockers, "blockers": blockers, "facts": facts})
    return normalized


def _bound_digest(normalized: dict[str, Any], value: object, field: str) -> str:
    digest = _digest(value, field)
    artifact_digests = {artifact["sha256"] for artifact in normalized["artifacts"]}
    if digest not in artifact_digests:
        raise EvidenceContractError(f"{field} 未绑定到 artifacts 中的 native artifact")
    return digest


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


def _vcov(path: Path, claim: str) -> dict[str, Any]:
    _payload, result, normalized = _base(path, "VCOV", claim)
    blockers: list[str] = []
    if claim == "coverage-model":
        planned = _integer(result.get("planned_items"), "result.planned_items", 1)
        mapped = _integer(result.get("mapped_items"), "result.mapped_items")
        compiled = _boolean(result.get("compiled"), "result.compiled")
        facts = {"plan_digest": _bound_digest(normalized, result.get("plan_digest"), "result.plan_digest"),
                 "model_digest": _bound_digest(normalized, result.get("model_digest"), "result.model_digest"),
                 "planned_items": planned, "mapped_items": mapped, "compiled": compiled}
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
            _text(item.get("plan_ref"), f"{prefix}.plan_ref")
            counts[status] += 1
            if status == "covered" and hits == 0:
                blockers.append(f"{item_id} 声明 covered 但 hits=0")
            elif status == "uncovered":
                blockers.append(f"{item_id} 尚未覆盖")
            elif status == "excluded" and not _valid_waiver(item.get("waiver")):
                blockers.append(f"{item_id} exclusion 缺少完整 Human waiver metadata")
        facts = {**counts, "items": len(items)}
    return _finish(normalized, blockers, facts)


def _vcase(path: Path, claim: str) -> dict[str, Any]:
    _payload, result, normalized = _base(path, "VCASE", claim)
    blockers: list[str] = []
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
        for index, item in enumerate(cases):
            prefix = f"result.cases[{index}]"
            case_id = _text(item.get("id"), f"{prefix}.id")
            if case_id in seen:
                blockers.append(f"重复 testcase: {case_id}")
            seen.add(case_id)
            _bound_digest(normalized, item.get("source_digest"), f"{prefix}.source_digest")
            registered = _boolean(item.get("registered"), f"{prefix}.registered")
            compiled = _boolean(item.get("compiled"), f"{prefix}.compiled")
            if not registered or not compiled:
                blockers.append(f"{case_id} 未注册或未编译")
        facts = {"cases": sorted(seen), "case_count": len(cases)}
    else:
        runs = _objects(result.get("runs"), "result.runs")
        if not runs:
            raise EvidenceContractError("result.runs 不能为空")
        seen: set[tuple[str, str]] = set()
        for index, item in enumerate(runs):
            prefix = f"result.runs[{index}]"
            case_id = _text(item.get("case"), f"{prefix}.case")
            seed = _seed(item.get("seed"), f"{prefix}.seed")
            key = (case_id, seed)
            if key in seen:
                blockers.append(f"重复 targeted run: {case_id}/{seed}")
            seen.add(key)
            verdict = _text(item.get("verdict"), f"{prefix}.verdict")
            errors = _integer(item.get("uvm_error"), f"{prefix}.uvm_error")
            fatals = _integer(item.get("uvm_fatal"), f"{prefix}.uvm_fatal")
            _bound_digest(normalized, item.get("log_digest"), f"{prefix}.log_digest")
            if verdict != "PASS" or errors or fatals:
                blockers.append(f"{case_id}/{seed} targeted run 未通过")
        facts = {"runs": len(runs), "executed_cases": sorted({case for case, _seed_value in seen})}
    return _finish(normalized, blockers, facts)


def _vreg(path: Path, claim: str) -> dict[str, Any]:
    _payload, result, normalized = _base(path, "VREG", claim)
    blockers: list[str] = []
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
        _text(result.get("batch_seed"), "result.batch_seed")
        _bound_digest(normalized, result.get("manifest_digest"), "result.manifest_digest")
        results = _objects(result.get("results"), "result.results")
        if not results:
            raise EvidenceContractError("result.results 不能为空")
        seen: set[str] = set()
        acceptable_pass = {"PASS"} if golden_required else {"PASS", "PASS-LIVE"}
        recognized = acceptable_pass | {"FAIL", "ERROR", "TIMEOUT"}
        failed_runs: list[dict[str, str]] = []
        for index, item in enumerate(results):
            test = _text(item.get("test"), f"result.results[{index}].test")
            if test in seen:
                blockers.append(f"重复 regression test: {test}")
            seen.add(test)
            verdict = _text(item.get("verdict"), f"result.results[{index}].verdict")
            seed = _seed(item.get("seed"), f"result.results[{index}].seed")
            _bound_digest(normalized, item.get("log_digest"), f"result.results[{index}].log_digest")
            if verdict not in recognized:
                blockers.append(f"{test} verdict 未识别: {verdict}")
            elif verdict not in acceptable_pass:
                failed_runs.append({"test": test, "seed": seed, "verdict": verdict})
        facts = {"tests": len(results), "golden_required": golden_required,
                 "acceptable_pass_verdicts": sorted(acceptable_pass),
                 "failed_runs": failed_runs}
    elif claim == "triage-evidence":
        failures = _objects(result.get("failures"), "result.failures")
        normalized_failures: list[dict[str, str]] = []
        for index, item in enumerate(failures):
            prefix = f"result.failures[{index}]"
            test = _text(item.get("test"), f"{prefix}.test")
            original_seed = _seed(item.get("original_seed"), f"{prefix}.original_seed")
            rerun_seed = _seed(item.get("rerun_seed"), f"{prefix}.rerun_seed")
            classification = _text(item.get("classification"), f"{prefix}.classification")
            disposition = _text(item.get("disposition"), f"{prefix}.disposition")
            rerun_verdict = _text(item.get("rerun_verdict"), f"{prefix}.rerun_verdict")
            rerun_log_digest = _bound_digest(
                normalized, item.get("rerun_log_digest"), f"{prefix}.rerun_log_digest"
            )
            if rerun_seed != original_seed:
                blockers.append(f"{test} 缺少 same-seed rerun")
            if classification == "UNCLASSIFIED":
                blockers.append(f"{test} 尚未分类")
            if disposition not in {"fixed", "accepted-known-fail", "rerun-pass"}:
                blockers.append(f"{test} disposition 未关闭")
            if disposition in {"fixed", "rerun-pass"} and rerun_verdict != "PASS":
                blockers.append(f"{test} disposition={disposition} 但 same-seed rerun 未 PASS")
            if disposition == "accepted-known-fail" and rerun_verdict not in {"FAIL", "ERROR", "TIMEOUT"}:
                blockers.append(f"{test} known-fail 的 rerun verdict 非失败结果")
            if disposition == "accepted-known-fail" and not _text(item.get("waiver_ref"), f"{prefix}.waiver_ref"):
                blockers.append(f"{test} known-fail 缺少 Human waiver reference")
            normalized_failures.append({
                "test": test, "original_seed": original_seed, "rerun_seed": rerun_seed,
                "classification": classification, "disposition": disposition,
                "rerun_verdict": rerun_verdict, "rerun_log_digest": rerun_log_digest,
                "waiver_ref": str(item.get("waiver_ref") or ""),
            })
        facts = {"failures": normalized_failures, "failure_count": len(failures)}
    else:
        snapshot_revision = _text(result.get("snapshot_revision"), "result.snapshot_revision")
        facts = {"snapshot_revision": snapshot_revision, "required_nodes": []}
    return _finish(normalized, blockers, facts)


VALIDATORS: dict[str, Callable[[Path, str], dict[str, Any]]] = {
    "VSTIM": _vstim,
    "VCHK": _vchk,
    "VCOV": _vcov,
    "VCASE": _vcase,
    "VREG": _vreg,
}


def validate_workstream_evidence(path: Path, workstream: str, claim: str) -> dict[str, Any]:
    if workstream not in VALIDATORS:
        raise EvidenceContractError(f"{workstream} 没有专用 evidence validator")
    if claim not in CLAIMS[workstream].values():
        raise EvidenceContractError(f"{workstream} 不支持 claim={claim}")
    return VALIDATORS[workstream](path, claim)
