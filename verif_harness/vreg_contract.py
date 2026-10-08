"""Approved regression scope and execution binding, never a seed generator.

The testbench owns command construction, seed generation and execution. These
pure helpers validate the control-plane contract without reading site settings.
"""

import hashlib
import json
from pathlib import PurePosixPath
import re


_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")
_CASE = re.compile(r"^[A-Za-z_]\w*$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _text(value, label, pattern=None):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + "必须是非空字符串")
    value = value.strip()
    if pattern is not None and not pattern.fullmatch(value):
        raise ValueError(label + "格式不正确")
    return value


def _keys(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(label + "包含未支持的字段或不是对象")


def seed_value(value):
    """Return a resolved positive numeric seed, never the sentinel 'random'."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("指定 seed 必须是正整数")
    if isinstance(value, str) and not re.fullmatch(r"[0-9]+", value):
        raise ValueError("指定 seed 必须是正整数")
    number = int(value)
    if number < 1:
        raise ValueError("指定 seed 必须是正整数")
    return str(number)


def normalize_config(value):
    """Normalize the exact group and parameters covered by owner approval."""
    _keys(value, {"regression_group", "cases", "submit_profile", "seed_mode", "seed", "repeat"},
          "回归结果方案配置")
    group = _text(value.get("regression_group"), "回归组名称", _ID)
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("回归组必须包含至少一个 case")
    normalized_cases = []
    for case in cases:
        _keys(case, {"case_id", "case_digest"}, "回归 case")
        normalized_cases.append({
            "case_id": _text(case.get("case_id"), "case 名称", _CASE),
            "case_digest": _text(case.get("case_digest"), "case 版本摘要", _SHA),
        })
    if len({case["case_id"] for case in normalized_cases}) != len(normalized_cases):
        raise ValueError("同一回归组不能重复列出 case")
    profile = value.get("submit_profile")
    _keys(profile, {"schema", "profile_id", "submit_file", "submit_file_digest", "profile_digest", "adapter"},
          "submit profile 引用")
    if profile.get("schema") != "SubmitProfileRef/1":
        raise ValueError("submit profile 必须引用 SubmitProfileRef/1")
    submit_file = _text(profile.get("submit_file"), "submit 配置路径")
    path = PurePosixPath(submit_file)
    if path.is_absolute() or ".." in path.parts or "\\" in submit_file or ":" in submit_file:
        raise ValueError("submit 配置必须是项目内相对路径")
    adapter = profile.get("adapter")
    _keys(adapter, {"name", "version"}, "submit adapter")
    normalized_profile = {
        "schema": "SubmitProfileRef/1",
        "profile_id": _text(profile.get("profile_id"), "submit profile 名称", _ID),
        "submit_file": str(path),
        "submit_file_digest": _text(profile.get("submit_file_digest"), "submit 文件摘要", _SHA),
        "profile_digest": _text(profile.get("profile_digest"), "submit profile 摘要", _SHA),
        "adapter": {"name": _text(adapter.get("name"), "submit adapter 名称"),
                    "version": _text(adapter.get("version"), "submit adapter 版本")},
    }
    mode = value.get("seed_mode")
    if mode not in ("random", "fixed"):
        raise ValueError("seed 模式必须是每次随机生成或指定 seed")
    repeat = value.get("repeat", 1)
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
        raise ValueError("repeat 必须是正整数，默认 1 次")
    result = {"regression_group": group,
              "cases": sorted(normalized_cases, key=lambda item: item["case_id"]),
              "submit_profile": normalized_profile, "seed_mode": mode, "repeat": repeat}
    if mode == "fixed":
        result["seed"] = seed_value(value.get("seed"))
    elif "seed" in value:
        raise ValueError("随机 seed 模式不能同时指定 seed 值")
    return result


def group_identity(config):
    """Scope uniqueness excludes seed/count and code revision, not profile ID."""
    config = normalize_config(config)
    payload = {"case_ids": [case["case_id"] for case in config["cases"]],
               "submit_file": config["submit_profile"]["submit_file"],
               "profile_id": config["submit_profile"]["profile_id"]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def normalize_binding(value):
    _keys(value, {"round_id", "plan_node_id", "plan_revision", "plan_digest"}, "执行轮次绑定")
    revision = value.get("plan_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("执行轮次必须绑定有效的方案版本")
    node = _text(value.get("plan_node_id"), "回归结果方案节点", _ID)
    if not node.startswith("workstream:VREG:"):
        raise ValueError("执行轮次必须绑定 VREG 回归结果方案")
    return {"round_id": _text(value.get("round_id"), "执行轮次", _ID),
            "plan_node_id": node, "plan_revision": revision,
            "plan_digest": _text(value.get("plan_digest"), "批准方案摘要", _SHA)}


def execution_blockers(config, batches, binding):
    """Compare testbench-emitted batch facts against the approved current run."""
    config, binding = normalize_config(config), normalize_binding(binding)
    blockers = []
    expected = {case["case_id"]: case["case_digest"] for case in config["cases"]}
    iterations = {name: set() for name in expected}
    seeds = {name: set() for name in expected}
    batch_ids = set()
    if not isinstance(batches, list) or not batches:
        return ["当前回归结果缺少执行批次"]
    for batch in batches:
        if batch.get("schema") != "RegressionBatchManifest/2":
            blockers.append("旧回归批次缺少当前方案和执行轮次合同，请重新生成执行证据")
            continue
        identifier = batch.get("batch_id")
        if identifier in batch_ids:
            blockers.append("当前轮次包含重复执行批次")
        batch_ids.add(identifier)
        if batch.get("execution_binding") != binding:
            blockers.append("执行批次不属于当前已批准方案和执行轮次")
        if batch.get("regression_group") != config["regression_group"]:
            blockers.append("回归结果不能混入其他 group")
        actual_profile = batch.get("submit_profile", {})
        if actual_profile != config["submit_profile"]:
            blockers.append("回归执行配置与批准的 submit profile 不一致")
        if batch.get("seed_mode") != config["seed_mode"] or batch.get("repeat") != config["repeat"]:
            blockers.append("执行 seed 模式或 repeat 与已批准方案不一致")
        if config["seed_mode"] == "fixed" and batch.get("seed") != config["seed"]:
            blockers.append("指定 seed 与已批准方案不一致")
        cases = batch.get("cases", [])
        for case in cases:
            if expected.get(case.get("case_id")) != case.get("case_digest"):
                blockers.append("执行 case 范围或版本与已批准方案不一致")
        for run in batch.get("runs", []):
            name, iteration = run.get("case_id"), run.get("iteration")
            if name not in expected:
                blockers.append("执行批次包含方案外 case")
                continue
            if (isinstance(iteration, bool) or not isinstance(iteration, int)
                    or not 0 <= iteration < config["repeat"]):
                blockers.append("执行次数编号超出已批准 repeat")
                continue
            if iteration in iterations[name]:
                blockers.append(name + " 包含重复的计划执行次数")
            iterations[name].add(iteration)
            seed = seed_value(run.get("seed"))
            if config["seed_mode"] == "fixed" and seed != config["seed"]:
                blockers.append(name + " 没有使用已批准的指定 seed")
            if config["seed_mode"] == "random" and seed in seeds[name]:
                blockers.append(name + " 的随机执行重复使用 seed")
            seeds[name].add(seed)
    for name, seen in iterations.items():
        if len(seen) != config["repeat"]:
            blockers.append(name + " 未完成已批准的全部计划执行次数")
    return list(dict.fromkeys(blockers))
