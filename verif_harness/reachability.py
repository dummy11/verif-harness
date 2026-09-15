"""Deterministic validation for VSTIM-owned reachability evidence."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SCHEMA = "StimulusReachabilityEvidence/1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
BOUNDARIES = {"dut-input-accepted", "driver-monitor-boundary"}


class ReachabilityError(ValueError):
    """A malformed or semantically insufficient reachability report."""


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReachabilityError(f"{field} 必须是非空字符串")
    return value.strip()


def _count(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ReachabilityError(f"{field} 必须是非负整数")
    return value


def validate_reachability(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReachabilityError(f"无法读取 reachability JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ReachabilityError(f"schema 必须是 {SCHEMA}")
    revision = _nonempty(payload.get("revision"), "revision")
    artifact_items = payload.get("artifacts")
    if not isinstance(artifact_items, list) or not artifact_items:
        raise ReachabilityError("artifacts 必须是非空对象数组")
    artifacts: list[dict[str, str]] = []
    artifact_paths: set[str] = set()
    for index, artifact in enumerate(artifact_items):
        if not isinstance(artifact, dict):
            raise ReachabilityError(f"artifacts[{index}] 必须是对象")
        artifact_path = _nonempty(artifact.get("path"), f"artifacts[{index}].path")
        artifact_digest = _nonempty(artifact.get("sha256"), f"artifacts[{index}].sha256")
        if not SHA256.fullmatch(artifact_digest):
            raise ReachabilityError(f"artifacts[{index}].sha256 必须是小写 SHA-256")
        if artifact_path in artifact_paths:
            raise ReachabilityError(f"artifacts path 重复: {artifact_path}")
        artifact_paths.add(artifact_path)
        artifacts.append({"path": artifact_path, "sha256": artifact_digest})

    producer = payload.get("producer")
    if not isinstance(producer, dict):
        raise ReachabilityError("producer 必须是对象")
    if producer.get("kind") != "vstim-probe":
        raise ReachabilityError(
            "VSTIM closure 只接受 producer.kind=vstim-probe；functional coverage/cover property 只能作为旁证"
        )
    producer_name = _nonempty(producer.get("name"), "producer.name")
    producer_version = _nonempty(producer.get("version"), "producer.version")

    observation = payload.get("observation")
    if not isinstance(observation, dict):
        raise ReachabilityError("observation 必须是对象")
    boundary = observation.get("boundary")
    if boundary not in BOUNDARIES:
        raise ReachabilityError("observation.boundary 必须是 dut-input-accepted 或 driver-monitor-boundary")
    point = _nonempty(observation.get("point"), "observation.point")
    predicate = _nonempty(observation.get("predicate"), "observation.predicate")

    runs = payload.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ReachabilityError("runs 必须是非空数组")

    normalized_runs: list[dict[str, Any]] = []
    run_ids: set[str] = set()
    required_scenarios: set[str] = set()
    reached_scenarios: set[str] = set()
    reproduction: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for run_index, run in enumerate(runs):
        prefix = f"runs[{run_index}]"
        if not isinstance(run, dict):
            raise ReachabilityError(f"{prefix} 必须是对象")
        run_id = _nonempty(run.get("id"), f"{prefix}.id")
        if run_id in run_ids:
            raise ReachabilityError(f"run id 重复: {run_id}")
        run_ids.add(run_id)
        test = _nonempty(run.get("test"), f"{prefix}.test")
        seed_value = run.get("seed")
        if not isinstance(seed_value, (str, int)) or isinstance(seed_value, bool) or str(seed_value).strip() == "":
            raise ReachabilityError(f"{prefix}.seed 必须是字符串或整数")
        seed = str(seed_value)
        config_digest = _nonempty(run.get("config_digest"), f"{prefix}.config_digest")
        stimulus_digest = _nonempty(run.get("stimulus_digest"), f"{prefix}.stimulus_digest")
        if not SHA256.fullmatch(config_digest) or not SHA256.fullmatch(stimulus_digest):
            raise ReachabilityError(f"{prefix} 的 config_digest/stimulus_digest 必须是小写 SHA-256")
        errors = _count(run.get("errors"), f"{prefix}.errors")
        timeouts = _count(run.get("timeouts"), f"{prefix}.timeouts")
        scenarios = run.get("scenarios")
        if not isinstance(scenarios, list) or not scenarios:
            raise ReachabilityError(f"{prefix}.scenarios 必须是非空数组")
        normalized_scenarios: list[dict[str, Any]] = []
        seen: set[str] = set()
        for scenario_index, scenario in enumerate(scenarios):
            scenario_prefix = f"{prefix}.scenarios[{scenario_index}]"
            if not isinstance(scenario, dict):
                raise ReachabilityError(f"{scenario_prefix} 必须是对象")
            scenario_id = _nonempty(scenario.get("id"), f"{scenario_prefix}.id")
            if scenario_id in seen:
                raise ReachabilityError(f"{prefix} 中 scenario id 重复: {scenario_id}")
            seen.add(scenario_id)
            required = scenario.get("required")
            if not isinstance(required, bool):
                raise ReachabilityError(f"{scenario_prefix}.required 必须是布尔值")
            counts = {
                key: _count(scenario.get(key), f"{scenario_prefix}.{key}")
                for key in ("generated", "driven", "accepted", "hits")
            }
            if required:
                required_scenarios.add(scenario_id)
            clean_reach = errors == 0 and timeouts == 0 and all(value > 0 for value in counts.values())
            if required and clean_reach:
                reached_scenarios.add(scenario_id)
            normalized_scenarios.append({"id": scenario_id, "required": required, **counts})
        normalized = {
            "id": run_id, "test": test, "seed": seed, "config_digest": config_digest,
            "stimulus_digest": stimulus_digest, "errors": errors, "timeouts": timeouts,
            "scenarios": normalized_scenarios,
        }
        normalized_runs.append(normalized)
        reproduction.setdefault((test, seed, config_digest), []).append(normalized)

    if not required_scenarios:
        raise ReachabilityError("至少需要一个 required scenario")
    missing = sorted(required_scenarios - reached_scenarios)
    reachability_ready = not missing

    deterministic_scenarios: set[str] = set()
    mismatched_groups: list[str] = []
    for key, group in reproduction.items():
        if len(group) < 2:
            continue
        digests = {run["stimulus_digest"] for run in group}
        label = "/".join(key[:2])
        if len(digests) != 1:
            mismatched_groups.append(label)
            continue
        reached_in_every_run: set[str] | None = None
        for run in group:
            reached_in_run = set()
            if not run["errors"] and not run["timeouts"]:
                reached_in_run = {
                    scenario["id"] for scenario in run["scenarios"]
                    if scenario["required"]
                    and all(scenario[name] > 0 for name in ("generated", "driven", "accepted", "hits"))
                }
            reached_in_every_run = (
                reached_in_run if reached_in_every_run is None else reached_in_every_run & reached_in_run
            )
        deterministic_scenarios.update(reached_in_every_run or set())
    non_deterministic = sorted(required_scenarios - deterministic_scenarios)
    determinism_ready = reachability_ready and not non_deterministic and not mismatched_groups
    return {
        "schema": SCHEMA,
        "revision": revision,
        "artifacts": artifacts,
        "producer": {"kind": "vstim-probe", "name": producer_name, "version": producer_version},
        "observation": {"boundary": boundary, "point": point, "predicate": predicate},
        "run_count": len(normalized_runs),
        "required_scenarios": sorted(required_scenarios),
        "missing_scenarios": missing,
        "non_deterministic_scenarios": non_deterministic,
        "mismatched_reproduction_groups": sorted(mismatched_groups),
        "reachability_ready": reachability_ready,
        "determinism_ready": determinism_ready,
    }
