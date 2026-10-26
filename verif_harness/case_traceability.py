"""Case design provenance shared by generators and evidence admission.

Source labels describe evidence, never confer owner approval. RTL-derived
expectations require a version-bound answer to an existing node question.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath

SOURCE_KINDS = {
    "specification": "document", "rtl": "source", "coverage-hole": "document",
    "defect": "document", "reference-model": "source", "engineering-decision": "document",
}
AUTHORITATIVE_KINDS = {"specification", "reference-model"}
STATUSES = {"specified", "rtl-derived-unconfirmed", "confirmed"}


class CaseTraceabilityError(ValueError):
    """Missing or inconsistent per-case design evidence."""


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise CaseTraceabilityError(f"{field} 必须填写具体内容")
    return value.strip()


def _keys(value, required, optional, field):
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
        raise CaseTraceabilityError(f"{field} 缺少必需信息或包含未知字段")


def _strings(value, field):
    if not isinstance(value, list) or not value:
        raise CaseTraceabilityError(f"{field} 必须是非空清单")
    result = [_text(item, field) for item in value]
    if len(set(result)) != len(result):
        raise CaseTraceabilityError(f"{field} 包含重复条目")
    return result


def _reference(value, field):
    for key in ("path", "sha256", "version", "locator"):
        _text(value.get(key), field + "." + key)
    path = PurePosixPath(value["path"])
    if path.is_absolute() or ".." in path.parts or "\\" in value["path"] or str(path) in {".", ""}:
        raise CaseTraceabilityError(f"{field} 必须引用项目内的受控文件")
    if not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]):
        raise CaseTraceabilityError(f"{field} 必须绑定来源文件的 SHA-256 版本")


def validate_traceability(value, case_id, check_file=None):
    """Validate design references without fabricating requirement semantics.

    check_file(reference, artifact_kind) verifies bytes in the caller's project.
    Unconfirmed RTL is valid draft data, but never acceptable delivery evidence.
    """
    _keys(value, {"schema", "verification_points", "testcase_list", "sources", "expected_result"}, set(), "用例来源")
    if value["schema"] != "CaseTraceability/1":
        raise CaseTraceabilityError("用例来源必须使用 CaseTraceability/1")
    _strings(value["verification_points"], "验证点")
    listing = value["testcase_list"]
    _keys(listing, {"path", "sha256", "version", "locator"}, set(), "用例清单引用")
    _reference(listing, "用例清单引用")
    if case_id not in listing["locator"]:
        raise CaseTraceabilityError("用例清单位置必须包含当前 case ID")
    if check_file:
        check_file(listing, "document")
    if not isinstance(value["sources"], list) or not value["sources"]:
        raise CaseTraceabilityError("每个 case 必须记录来源")
    sources = {}
    for source in value["sources"]:
        _keys(source, {"id", "kind", "path", "sha256", "version", "locator"}, set(), "用例来源条目")
        identifier = _text(source["id"], "来源编号")
        if identifier in sources:
            raise CaseTraceabilityError("用例来源编号重复")
        kind = _text(source["kind"], "来源类型")
        if kind not in SOURCE_KINDS:
            raise CaseTraceabilityError("未知用例来源类型")
        _reference(source, "来源 " + identifier)
        sources[identifier] = source
        if check_file:
            check_file(source, SOURCE_KINDS[kind])
    expected = value["expected_result"]
    _keys(expected, {"description", "check_method", "basis_source_ids", "status"},
          {"confirmation_question_id"}, "预期结果依据")
    _text(expected["description"], "预期结果")
    _text(expected["check_method"], "检查方法")
    basis = _strings(expected["basis_source_ids"], "预期结果依据")
    if set(basis) - sources.keys():
        raise CaseTraceabilityError("预期结果引用了未登记的来源")
    kinds = {sources[item]["kind"] for item in basis}
    if not kinds & (AUTHORITATIVE_KINDS | {"rtl", "engineering-decision"}):
        raise CaseTraceabilityError("覆盖缺口和缺陷记录不能单独作为预期结果依据")
    status = _text(expected["status"], "预期结果确认状态")
    if status not in STATUSES:
        raise CaseTraceabilityError("未知预期结果确认状态")
    if status == "specified" and not kinds & AUTHORITATIVE_KINDS:
        raise CaseTraceabilityError("仅从 RTL 或工程判断推导的预期不能标记为规格已明确")
    if status == "rtl-derived-unconfirmed" and ("rtl" not in kinds or kinds & AUTHORITATIVE_KINDS):
        raise CaseTraceabilityError("RTL 推导待确认标记与预期结果依据不一致")
    if status == "confirmed":
        _text(expected.get("confirmation_question_id"), "负责人确认问题引用")
    elif "confirmation_question_id" in expected:
        raise CaseTraceabilityError("未确认或规格已明确的预期不得附加确认记录")
    return value


def behavior_digest(traceability):
    """Bind the owner's answer to exact sources and the proposed expectation."""
    expected = traceability["expected_result"]
    return canonical_digest({
        "verification_points": sorted(traceability["verification_points"]),
        "sources": sorted((source for source in traceability["sources"]
                           if source["id"] in expected["basis_source_ids"]), key=lambda source: source["id"]),
        "expected_result": {key: (sorted(value) if key == "basis_source_ids" else value)
                            for key, value in expected.items()
                            if key not in {"status", "confirmation_question_id"}},
    })


def confirmation_context(case_id, traceability):
    return {"schema": "CaseBehaviorConfirmation/1", "case_id": case_id,
            "behavior_digest": behavior_digest(traceability)}
