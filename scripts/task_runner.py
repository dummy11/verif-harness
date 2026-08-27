#!/usr/bin/env python3
"""Persistent, one-task-at-a-time execution for verif-harness Spec Kit runs."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


TASK_STATE_FILE = "verif-harness-tasks.json"
TASK_REVIEW_FILE = "verif-harness-task-review.json"
TASK_STATE_SCHEMA = 1
TASK_TIMEOUT_SECONDS = 1800
VALIDATION_TIMEOUT_SECONDS = 600
TASK_LINE = re.compile(
    r"^- \[([ xX])\] (T\d{3,})(?:\s+\[P\])?(?:\s+\[([^]]+)\])?\s+(.+)$"
)
BLOCKER_LINE = re.compile(
    r"^- (B\d{3,})\s+\[(OPEN|RESOLVED)\]\s+(.+)$", re.IGNORECASE
)
META_LINE = re.compile(r"^\s{2,}-\s+(.+?)\s*$")
META_ITEM = re.compile(r"^([a-z]+):\s*(.*?)\s*$")
ALLOWED_META = {"mode", "outputs", "evidence", "validate", "needs", "interaction"}
BLOCK_KINDS = {"human", "authority", "specification", "execution"}


class TaskRunnerError(ValueError):
    """Raised when a reviewed task document or runner transition is unsafe."""


@dataclass(frozen=True)
class TaskContract:
    """The compact, reviewed contract for one executable task."""

    task_id: str
    checked: bool
    trace: str
    description: str
    mode: str
    outputs: tuple[str, ...]
    evidence: tuple[str, ...]
    validate: str
    needs: tuple[str, ...]
    interaction: str
    line_number: int

    def as_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "checked": self.checked,
            "trace": self.trace,
            "description": self.description,
            "mode": self.mode,
            "outputs": list(self.outputs),
            "evidence": list(self.evidence),
            "validate": self.validate,
            "needs": list(self.needs),
            "interaction": self.interaction,
            "line_number": self.line_number,
        }


def _csv(value: str) -> tuple[str, ...]:
    value = value.strip().strip("`")
    if value.lower() in {"", "none", "无"}:
        return ()
    items = []
    for item in value.split(","):
        item = item.strip()
        if len(item) >= 2 and item[0] == "`" and item[-1] == "`":
            item = item[1:-1]
        if item:
            items.append(item)
    return tuple(items)


def parse_tasks(path: Path) -> tuple[list[TaskContract], list[dict[str, str]]]:
    """Parse the compact tasks.md format and reject ambiguous execution data."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise TaskRunnerError(f"cannot read task document {path}: {exc}") from exc

    tasks: list[TaskContract] = []
    blockers: list[dict[str, str]] = []
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        blocker_match = BLOCKER_LINE.match(line)
        if blocker_match:
            blockers.append(
                {
                    "blocker_id": blocker_match.group(1).upper(),
                    "status": blocker_match.group(2).upper(),
                    "question": blocker_match.group(3).strip(),
                }
            )
            index += 1
            continue
        task_match = TASK_LINE.match(line)
        if not task_match:
            index += 1
            continue
        task_id = task_match.group(2)
        if task_id in seen:
            raise TaskRunnerError(f"duplicate task ID {task_id} in {path}")
        seen.add(task_id)
        metadata: dict[str, str] = {}
        cursor = index + 1
        while cursor < len(lines):
            meta_match = META_LINE.match(lines[cursor])
            if not meta_match:
                break
            for segment in re.split(r";\s*(?=[a-z]+:\s*)", meta_match.group(1)):
                item_match = META_ITEM.match(segment.strip())
                if not item_match:
                    raise TaskRunnerError(
                        f"malformed metadata for {task_id} at {path}:{cursor + 1}"
                    )
                key, value = item_match.group(1).lower(), item_match.group(2).strip()
                if key not in ALLOWED_META:
                    raise TaskRunnerError(
                        f"unsupported metadata {key!r} for {task_id} at {path}:{cursor + 1}"
                    )
                if key in metadata:
                    raise TaskRunnerError(f"duplicate {key!r} metadata for {task_id}")
                metadata[key] = value
            cursor += 1
        required = {"mode", "outputs", "evidence", "validate", "interaction"}
        missing = sorted(required - metadata.keys())
        if missing:
            raise TaskRunnerError(f"task {task_id} is missing metadata: {', '.join(missing)}")
        interaction = metadata["interaction"].strip().strip("`").lower()
        if interaction != "none":
            raise TaskRunnerError(
                f"task {task_id} interaction must be 'none'; represent Human work as an OPEN B### blocker"
            )
        outputs = _csv(metadata["outputs"])
        evidence = _csv(metadata["evidence"])
        if not outputs:
            raise TaskRunnerError(f"task {task_id} must declare at least one owned output")
        if not evidence:
            raise TaskRunnerError(f"task {task_id} must declare at least one evidence path")
        mode = metadata["mode"].strip().strip("`")
        validation = metadata["validate"].strip().strip("`")
        if not mode:
            raise TaskRunnerError(f"task {task_id} mode must not be empty")
        if not validation:
            raise TaskRunnerError(f"task {task_id} validation must not be empty")
        tasks.append(
            TaskContract(
                task_id=task_id,
                checked=task_match.group(1).lower() == "x",
                trace=(task_match.group(3) or "").strip(),
                description=task_match.group(4).strip(),
                mode=mode,
                outputs=outputs,
                evidence=evidence,
                validate=validation,
                needs=_csv(metadata.get("needs", "none")),
                interaction=interaction,
                line_number=index + 1,
            )
        )
        index = cursor

    if not tasks:
        raise TaskRunnerError(f"no executable T### tasks found in {path}")
    known = {task.task_id for task in tasks}
    for task in tasks:
        unknown = sorted(set(task.needs) - known)
        if unknown:
            raise TaskRunnerError(
                f"task {task.task_id} has unknown dependencies: {', '.join(unknown)}"
            )
    return tasks, blockers


def resolve_tasks_path(project_root: Path) -> Path:
    """Resolve the active feature's tasks.md from Spec Kit's persisted feature state."""
    feature_state = project_root / ".specify/feature.json"
    try:
        payload = json.loads(feature_state.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskRunnerError(f"cannot resolve active feature from {feature_state}: {exc}") from exc
    feature_dir = payload.get("feature_directory") if isinstance(payload, dict) else None
    if not isinstance(feature_dir, str) or not feature_dir.strip():
        raise TaskRunnerError(f"{feature_state} must declare feature_directory")
    resolved = Path(feature_dir)
    if not resolved.is_absolute():
        resolved = project_root / resolved
    try:
        resolved.resolve().relative_to(project_root.resolve())
    except (OSError, ValueError) as exc:
        raise TaskRunnerError("active feature directory escapes the project root") from exc
    tasks_path = resolved / "tasks.md"
    if not tasks_path.is_file():
        raise TaskRunnerError(f"active task document is missing: {tasks_path}")
    return tasks_path


def atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def state_path(run_dir: Path) -> Path:
    return run_dir / TASK_STATE_FILE


def read_state(run_dir: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(state_path(run_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskRunnerError(f"cannot read task runner state: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != TASK_STATE_SCHEMA:
        raise TaskRunnerError("unsupported or malformed task runner state")
    return payload


def validate_document(project_root: Path) -> tuple[Path, list[TaskContract]]:
    """Fail closed before task review/execution when blockers or schema errors remain."""
    tasks_path = resolve_tasks_path(project_root)
    tasks, blockers = parse_tasks(tasks_path)
    open_blockers = [item for item in blockers if item["status"] == "OPEN"]
    if open_blockers:
        detail = "; ".join(
            f"{item['blocker_id']}: {item['question']}" for item in open_blockers
        )
        raise TaskRunnerError(f"unresolved task blockers prevent execution approval: {detail}")
    return tasks_path, tasks


def contract_fingerprint(tasks: list[TaskContract]) -> str:
    """Hash reviewed execution semantics while ignoring runner-owned checkboxes."""
    payload = []
    for task in tasks:
        item = task.as_dict()
        item.pop("checked", None)
        item.pop("line_number", None)
        payload.append(item)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def record_reviewed_contract(
    project_root: Path, run_dir: Path, run_id: str
) -> dict[str, object]:
    """Bind task-review approval to the exact executable contract."""
    tasks_path, tasks = validate_document(project_root)
    payload: dict[str, object] = {
        "schema_version": 1,
        "run_id": run_id,
        "tasks_file": str(tasks_path),
        "task_contract_sha256": contract_fingerprint(tasks),
        "reviewed_at": _utc_now(),
    }
    atomic_write_json(run_dir / TASK_REVIEW_FILE, payload)
    return payload


def require_reviewed_contract(
    project_root: Path, run_dir: Path, run_id: str
) -> dict[str, object]:
    """Reject execution authorization when tasks changed after task review."""
    path = run_dir / TASK_REVIEW_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskRunnerError(f"cannot read reviewed task contract {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("run_id") != run_id:
        raise TaskRunnerError("reviewed task contract does not match this workflow run")
    tasks_path, tasks = validate_document(project_root)
    if str(tasks_path) != payload.get("tasks_file") or contract_fingerprint(
        tasks
    ) != payload.get("task_contract_sha256"):
        raise TaskRunnerError("tasks.md changed after review-tasks; review it again")
    return payload


def initialize_state(
    project_root: Path, run_dir: Path, run_id: str, runtime: str
) -> dict[str, object]:
    existing = read_state(run_dir)
    if existing is not None:
        return existing
    tasks_path, tasks = validate_document(project_root)
    prechecked = [task.task_id for task in tasks if task.checked]
    if prechecked:
        raise TaskRunnerError(
            "tasks are pre-checked without state bound to this workflow run: "
            + ", ".join(prechecked)
        )
    entries = []
    for task in tasks:
        entry = task.as_dict()
        entry.update(
            {
                "status": "READY",
                "attempts": 0,
                "blocker": None,
                "answer": None,
                "started_at": None,
                "finished_at": None,
                "pid": None,
                "log": str(run_dir / f"task-{task.task_id}.log"),
            }
        )
        entries.append(entry)
    state: dict[str, object] = {
        "schema_version": TASK_STATE_SCHEMA,
        "run_id": run_id,
        "runtime": runtime,
        "tasks_file": str(tasks_path),
        "task_contract_sha256": contract_fingerprint(tasks),
        "status": "READY",
        "current_task_id": None,
        "task_worker_pid": None,
        "tasks": entries,
        "updated_at": _utc_now(),
    }
    atomic_write_json(state_path(run_dir), state)
    return state


def _utc_now() -> str:
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc).isoformat()


def _task_entries(state: dict[str, object]) -> list[dict[str, object]]:
    entries = state.get("tasks")
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise TaskRunnerError("task runner state has no valid tasks array")
    return entries


def block_task(
    run_dir: Path, run_id: str, task_id: str, kind: str, question: str
) -> dict[str, object]:
    """Persist a real task-level pause that the parent runner can observe."""
    if kind not in BLOCK_KINDS:
        raise TaskRunnerError(f"block kind must be one of {sorted(BLOCK_KINDS)}")
    if not question.strip():
        raise TaskRunnerError("block question must not be empty")
    state = read_state(run_dir)
    if state is None or state.get("run_id") != run_id:
        raise TaskRunnerError(f"task state for run {run_id!r} does not exist")
    if state.get("status") != "RUNNING" or state.get("current_task_id") != task_id:
        raise TaskRunnerError(f"task {task_id} is not the current RUNNING task")
    task = next((item for item in _task_entries(state) if item.get("task_id") == task_id), None)
    if task is None or task.get("status") != "RUNNING":
        raise TaskRunnerError(f"task {task_id} is not RUNNING")
    blocker = {"kind": kind, "question": question.strip(), "created_at": _utc_now()}
    task["status"] = "BLOCKED"
    task["blocker"] = blocker
    state["status"] = "BLOCKED"
    state["updated_at"] = blocker["created_at"]
    atomic_write_json(state_path(run_dir), state)
    return state


def resume_blocked(state: dict[str, object], answer: str | None) -> dict[str, object]:
    if state.get("status") != "BLOCKED":
        raise TaskRunnerError("task runner is not BLOCKED")
    task_id = state.get("current_task_id")
    task = next((item for item in _task_entries(state) if item.get("task_id") == task_id), None)
    if task is None or task.get("status") != "BLOCKED":
        raise TaskRunnerError("blocked current task is missing")
    blocker = task.get("blocker")
    kind = blocker.get("kind") if isinstance(blocker, dict) else None
    if kind in {"human", "authority", "specification"} and not (answer or "").strip():
        raise TaskRunnerError(f"blocked task {task_id} requires --answer")
    task["answer"] = (answer or "").strip() or None
    task["status"] = "READY"
    state["status"] = "READY"
    state["updated_at"] = _utc_now()
    return state


def blocked_task_requires_answer(state: dict[str, object]) -> bool:
    """Return whether the current persisted blocker crosses a Human boundary."""
    if state.get("status") != "BLOCKED":
        return False
    task_id = state.get("current_task_id")
    task = next(
        (item for item in _task_entries(state) if item.get("task_id") == task_id), None
    )
    blocker = task.get("blocker") if isinstance(task, dict) else None
    return isinstance(blocker, dict) and blocker.get("kind") in {
        "human",
        "authority",
        "specification",
    }


def _ready_task(state: dict[str, object]) -> dict[str, object] | None:
    entries = _task_entries(state)
    done = {str(item.get("task_id")) for item in entries if item.get("status") == "DONE"}
    for task in entries:
        if task.get("status") != "READY":
            continue
        needs = task.get("needs", [])
        if isinstance(needs, list) and all(str(item) in done for item in needs):
            return task
    remaining = [item for item in entries if item.get("status") != "DONE"]
    if remaining:
        waiting = ", ".join(str(item.get("task_id")) for item in remaining)
        raise TaskRunnerError(f"no READY task has satisfied dependencies: {waiting}")
    return None


def _contract_drift(project_root: Path, state: dict[str, object]) -> str | None:
    try:
        tasks_path, tasks = validate_document(project_root)
    except TaskRunnerError as exc:
        return str(exc)
    if str(tasks_path) != state.get("tasks_file") or contract_fingerprint(
        tasks
    ) != state.get("task_contract_sha256"):
        return "tasks.md execution contract changed after authorization"
    return None


def _prompt(run_id: str, task: dict[str, object], invocation: str) -> str:
    answer = task.get("answer")
    answer_text = f"\n已获得的人工回答/授权：{answer}\n" if answer else ""
    outputs = ", ".join(f"`{item}`" for item in task.get("outputs", []))
    evidence = ", ".join(f"`{item}`" for item in task.get("evidence", []))
    return f"""使用简体中文执行 verif-harness 已评审任务；只执行当前任务，不扫描或执行其他 T###。

当前 task：{task['task_id']} {task['description']}
追踪：{task.get('trace', '')}
mode：{task['mode']}
owned outputs：{outputs}
evidence：{evidence}
validation：`{task['validate']}`
interaction：none{answer_text}
通过 {invocation} 调度上面的 mode。不要修改 DUT RTL，不要 commit/push，不要授予 approval/waiver。
若遇到未预先授权的人工作业、权限边界、规格歧义或必须询问用户的问题，立即运行：
{invocation} block {run_id} {task['task_id']} --kind <human|authority|specification|execution> --question "<具体问题>"
block 命令成功后立即退出；不得等待终端输入，也不得继续其他任务。
若完成，确保 owned outputs 和 evidence 已落盘；task runner 会独立运行 validation 并更新 checkbox。
"""


def _terminate(process: subprocess.Popen[object]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:  # pragma: no cover - Windows only
            process.terminate()
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            process.kill()


def _check_paths(project_root: Path, values: object) -> list[str]:
    missing: list[str] = []
    if not isinstance(values, list):
        return ["invalid path list"]
    for value in values:
        if not isinstance(value, str):
            missing.append(repr(value))
            continue
        path = Path(value)
        if not path.is_absolute():
            path = project_root / path
        try:
            path.resolve().relative_to(project_root.resolve())
        except (OSError, ValueError):
            missing.append(f"{value} (escapes project root)")
            continue
        if not path.exists():
            missing.append(value)
    return missing


def _validate(
    project_root: Path,
    task: dict[str, object],
    log_path: Path,
    timeout_seconds: int = VALIDATION_TIMEOUT_SECONDS,
) -> str | None:
    missing_outputs = _check_paths(project_root, task.get("outputs"))
    missing_evidence = _check_paths(project_root, task.get("evidence"))
    if missing_outputs or missing_evidence:
        return (
            f"missing outputs={missing_outputs or 'none'}; "
            f"missing evidence={missing_evidence or 'none'}"
        )
    command = task.get("validate")
    if not isinstance(command, str) or not command.strip():
        return "validation command is empty"
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n$ {command}\n")
        popen_options: dict[str, object] = {
            "cwd": project_root,
            "shell": True,
            "executable": "/bin/sh" if os.name == "posix" else None,
            "stdin": subprocess.DEVNULL,
            "stdout": log,
            "stderr": subprocess.STDOUT,
            "text": True,
        }
        if os.name == "posix":
            popen_options["start_new_session"] = True
        process = subprocess.Popen(
            command,
            **popen_options,
        )
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _terminate(process)
            return f"validation exceeded {timeout_seconds}s; see {log_path}"
    if return_code != 0:
        return f"validation exited with code {return_code}; see {log_path}"
    return None


def _mark_checkbox(tasks_path: Path, task_id: str) -> None:
    source = tasks_path.read_text(encoding="utf-8")
    completed = re.compile(rf"(?m)^- \[[xX]\] ({re.escape(task_id)}\b)")
    if len(completed.findall(source)) == 1:
        return
    pattern = re.compile(rf"(?m)^- \[ \] ({re.escape(task_id)}\b)")
    updated, count = pattern.subn(r"- [x] \1", source, count=1)
    if count != 1:
        raise TaskRunnerError(f"cannot mark exactly one checkbox for {task_id}")
    tasks_path.write_text(updated, encoding="utf-8")


def run_tasks(
    project_root: Path,
    run_dir: Path,
    run_id: str,
    runtime: str,
    invocation: str,
    build_exec_args: Callable[[str, str], list[str]],
    *,
    answer: str | None = None,
    timeout_seconds: int = TASK_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Run tasks serially until all are DONE or one becomes BLOCKED."""
    state = initialize_state(project_root, run_dir, run_id, runtime)
    if state.get("run_id") != run_id or state.get("runtime") != runtime:
        raise TaskRunnerError("task runner state does not match this run/runtime")
    current_tasks_path, current_tasks = validate_document(project_root)
    if str(current_tasks_path) != state.get("tasks_file") or contract_fingerprint(
        current_tasks
    ) != state.get("task_contract_sha256"):
        raise TaskRunnerError(
            "tasks.md execution contract changed after authorization; return to task review"
        )
    if state.get("status") == "DONE":
        return state
    if state.get("status") == "RUNNING":
        raise TaskRunnerError("task runner already has a RUNNING task")
    if state.get("status") == "BLOCKED":
        state = resume_blocked(state, answer)
        atomic_write_json(state_path(run_dir), state)
    elif answer:
        raise TaskRunnerError("--answer is valid only when the current task is BLOCKED")

    while True:
        task = _ready_task(state)
        if task is None:
            state["status"] = "DONE"
            state["current_task_id"] = None
            state["updated_at"] = _utc_now()
            atomic_write_json(state_path(run_dir), state)
            return state
        task_id = str(task["task_id"])
        state["status"] = "RUNNING"
        state["current_task_id"] = task_id
        task["status"] = "RUNNING"
        task["attempts"] = int(task.get("attempts", 0)) + 1
        task["started_at"] = _utc_now()
        task["blocker"] = None
        state["updated_at"] = task["started_at"]
        atomic_write_json(state_path(run_dir), state)

        prompt = _prompt(run_id, task, invocation)
        argv = build_exec_args(runtime, prompt)
        if not argv:
            block_task(
                run_dir, run_id, task_id, "execution",
                f"runtime {runtime} did not provide an executable Agent command",
            )
            return read_state(run_dir) or state
        log_path = Path(str(task["log"]))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        popen_options: dict[str, object] = {
            "cwd": project_root,
            "stdin": subprocess.DEVNULL,
            "stdout": None,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "posix":
            popen_options["start_new_session"] = True
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n[{_utc_now()}] attempt {task['attempts']}\n")
            log.write("argv: " + shlex.join(argv[:2] + ["<task-prompt>"]) + "\n")
            log.flush()
            popen_options["stdout"] = log
            process = subprocess.Popen(argv, **popen_options)

        observed = read_state(run_dir)
        if observed is not None and observed.get("status") == "BLOCKED":
            _terminate(process)
            observed["task_worker_pid"] = None
            blocked_task = next(
                (
                    item
                    for item in _task_entries(observed)
                    if item.get("task_id") == task_id
                ),
                None,
            )
            if blocked_task is not None:
                blocked_task["pid"] = None
            atomic_write_json(state_path(run_dir), observed)
            return observed
        if observed is not None:
            state = observed
            task = next(
                item for item in _task_entries(state) if item.get("task_id") == task_id
            )
        state["task_worker_pid"] = process.pid
        task["pid"] = process.pid
        state["updated_at"] = _utc_now()
        atomic_write_json(state_path(run_dir), state)

        deadline = time.monotonic() + timeout_seconds
        blocked = False
        while process.poll() is None:
            observed = read_state(run_dir)
            if observed is not None and observed.get("status") == "BLOCKED":
                blocked = True
                _terminate(process)
                observed["task_worker_pid"] = None
                blocked_task = next(
                    (
                        item
                        for item in _task_entries(observed)
                        if item.get("task_id") == task_id
                    ),
                    None,
                )
                if blocked_task is not None:
                    blocked_task["pid"] = None
                atomic_write_json(state_path(run_dir), observed)
                break
            if time.monotonic() >= deadline:
                _terminate(process)
                timed_out = block_task(
                    run_dir, run_id, task_id, "execution",
                    f"task exceeded {timeout_seconds}s safety timeout; inspect {log_path}",
                )
                timed_out["task_worker_pid"] = None
                timed_out_task = next(
                    item
                    for item in _task_entries(timed_out)
                    if item.get("task_id") == task_id
                )
                timed_out_task["pid"] = None
                atomic_write_json(state_path(run_dir), timed_out)
                blocked = True
                break
            time.sleep(0.2)
        if blocked:
            return read_state(run_dir) or state

        return_code = process.returncode
        observed = read_state(run_dir)
        if observed is not None and observed.get("status") == "BLOCKED":
            observed["task_worker_pid"] = None
            atomic_write_json(state_path(run_dir), observed)
            return observed
        state["task_worker_pid"] = None
        task["pid"] = None
        atomic_write_json(state_path(run_dir), state)
        if return_code != 0:
            block_task(
                run_dir, run_id, task_id, "execution",
                f"Agent exited with code {return_code}; inspect {log_path}",
            )
            return read_state(run_dir) or state
        drift = _contract_drift(project_root, state)
        if drift is not None:
            block_task(run_dir, run_id, task_id, "specification", drift)
            return read_state(run_dir) or state
        reason = _validate(project_root, task, log_path)
        if reason is not None:
            block_task(run_dir, run_id, task_id, "execution", reason)
            return read_state(run_dir) or state
        drift = _contract_drift(project_root, state)
        if drift is not None:
            block_task(run_dir, run_id, task_id, "specification", drift)
            return read_state(run_dir) or state

        tasks_path = Path(str(state["tasks_file"]))
        _mark_checkbox(tasks_path, task_id)
        task["status"] = "DONE"
        task["finished_at"] = _utc_now()
        task["answer"] = None
        state["status"] = (
            "DONE"
            if all(item.get("status") == "DONE" for item in _task_entries(state))
            else "READY"
        )
        state["current_task_id"] = None
        state["task_worker_pid"] = None
        state["updated_at"] = task["finished_at"]
        atomic_write_json(state_path(run_dir), state)


def recover_running_task(
    project_root: Path, run_dir: Path, run_id: str
) -> dict[str, object] | None:
    """Reconcile an interrupted task from postconditions before allowing retry."""
    state = read_state(run_dir)
    if state is None or state.get("status") != "RUNNING":
        return None
    current_tasks_path, current_tasks = validate_document(project_root)
    if str(current_tasks_path) != state.get("tasks_file") or contract_fingerprint(
        current_tasks
    ) != state.get("task_contract_sha256"):
        raise TaskRunnerError(
            "tasks.md execution contract changed after authorization; return to task review"
        )
    task_id = state.get("current_task_id")
    if not isinstance(task_id, str):
        raise TaskRunnerError("RUNNING task state has no current_task_id")
    task = next(
        (item for item in _task_entries(state) if item.get("task_id") == task_id), None
    )
    if task is None:
        raise TaskRunnerError(f"RUNNING task {task_id} is missing")
    task["pid"] = None
    state["task_worker_pid"] = None
    atomic_write_json(state_path(run_dir), state)
    log_path = Path(str(task.get("log", run_dir / f"task-{task_id}.log")))
    reason = _validate(project_root, task, log_path)
    if reason is None:
        drift = _contract_drift(project_root, state)
        if drift is not None:
            return block_task(run_dir, run_id, task_id, "specification", drift)
        _mark_checkbox(Path(str(state["tasks_file"])), task_id)
        task["status"] = "DONE"
        task["finished_at"] = _utc_now()
        state["status"] = (
            "DONE"
            if all(item.get("status") == "DONE" for item in _task_entries(state))
            else "READY"
        )
        state["current_task_id"] = None
        state["updated_at"] = task["finished_at"]
        atomic_write_json(state_path(run_dir), state)
        return state
    return block_task(
        run_dir,
        run_id,
        task_id,
        "execution",
        "task worker was externally interrupted and postconditions are incomplete: "
        + reason,
    )
