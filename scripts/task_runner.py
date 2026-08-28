#!/usr/bin/env python3
"""Persistent, one-task-at-a-time execution for verif-harness Spec Kit runs."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


TASK_STATE_FILE = "verif-harness-tasks.json"
TASK_REVIEW_FILE = "verif-harness-task-review.json"
TASK_REVISIONS_FILE = "verif-harness-task-revisions.json"
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
SHELL_BUILTINS = {
    ".", ":", "[", "break", "cd", "command", "continue", "eval", "exec",
    "exit", "export", "false", "getopts", "hash", "pwd", "read", "readonly",
    "return", "set", "shift", "test", "times", "trap", "true", "type", "ulimit",
    "umask", "unset", "wait",
}
SHELL_KEYWORDS = {
    "case", "do", "done", "elif", "else", "esac", "fi", "for", "if", "then",
    "until", "while",
}
MUTATING_VALIDATION_OPTIONS = {"--fix", "--write", "--update", "--in-place"}


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
    value = value.strip()
    if value.strip("`").lower() in {"", "none", "无"}:
        return ()
    items = []
    for item in value.split(","):
        item = item.strip()
        if len(item) >= 2 and item[0] == "`" and item[-1] == "`":
            item = item[1:-1]
        if item:
            items.append(item)
    return tuple(items)


def _comma_list(value: str, task_id: str, field: str) -> tuple[str, ...]:
    """Parse compact list fields and reject ambiguous prose-style separators."""
    if ";" in value:
        raise TaskRunnerError(
            f"task {task_id} {field} must use commas between items; semicolons "
            "separate task metadata fields"
        )
    items = _csv(value)
    for item in items:
        if not item or "`" in item or "\n" in item or "\x00" in item:
            raise TaskRunnerError(f"task {task_id} has malformed {field} item: {item!r}")
        if re.fullmatch(r"\[[^]]+\]", item):
            raise TaskRunnerError(f"task {task_id} {field} still contains a template placeholder")
        if field in {"outputs", "evidence"}:
            candidate = Path(item)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise TaskRunnerError(
                    f"task {task_id} {field} path must stay project-relative: {item!r}"
                )
    return items


def _validation_command(value: str, task_id: str, mode: str) -> str:
    """Reject prose/placeholders before review binds a task contract."""
    command = value.strip().strip("`").strip()
    if not command:
        raise TaskRunnerError(f"task {task_id} validation must not be empty")
    if "\n" in command or "\x00" in command:
        raise TaskRunnerError(f"task {task_id} validation must be one shell command line")
    if re.fullmatch(r"\[[^]]+\]", command):
        raise TaskRunnerError(f"task {task_id} validation still contains a template placeholder")
    syntax = subprocess.run(
        ["/bin/sh", "-n", "-c", command],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if syntax.returncode != 0:
        detail = syntax.stderr.strip() or "invalid shell syntax"
        raise TaskRunnerError(f"task {task_id} validation is not valid /bin/sh syntax: {detail}")
    try:
        words = shlex.split(command, posix=True)
    except ValueError as exc:
        raise TaskRunnerError(f"task {task_id} validation cannot be parsed: {exc}") from exc
    mutating_options = sorted(MUTATING_VALIDATION_OPTIONS.intersection(words))
    if mutating_options:
        raise TaskRunnerError(
            f"task {task_id} validation must be check-only; remove mutating option(s): "
            + ", ".join(mutating_options)
        )
    try:
        mode_words = shlex.split(mode, posix=True)
    except ValueError as exc:
        raise TaskRunnerError(f"task {task_id} mode cannot be parsed: {exc}") from exc
    mode_name = mode_words[0] if mode_words else ""
    if mode_name == "doctor":
        if "doctor" not in words:
            raise TaskRunnerError(
                f"task {task_id} doctor validation must invoke doctor directly"
            )
        if "|" in command or ";" in command:
            raise TaskRunnerError(
                f"task {task_id} doctor validation must preserve its direct exit code"
            )
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
        words.pop(0)
    if not words:
        raise TaskRunnerError(f"task {task_id} validation has no executable command")
    executable = words[0]
    if executable not in SHELL_BUILTINS | SHELL_KEYWORDS and "/" not in executable:
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+", executable) or shutil.which(executable) is None:
            raise TaskRunnerError(
                f"task {task_id} validation must start with an executable shell command; "
                f"{executable!r} is not available"
            )
    return command


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
        outputs = _comma_list(metadata["outputs"], task_id, "outputs")
        evidence = _comma_list(metadata["evidence"], task_id, "evidence")
        needs = _comma_list(metadata.get("needs", "none"), task_id, "needs")
        if not outputs:
            raise TaskRunnerError(f"task {task_id} must declare at least one owned output")
        if not evidence:
            raise TaskRunnerError(f"task {task_id} must declare at least one evidence path")
        mode = metadata["mode"].strip().strip("`")
        if not mode:
            raise TaskRunnerError(f"task {task_id} mode must not be empty")
        validation = _validation_command(metadata["validate"], task_id, mode)
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
                needs=needs,
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


def atomic_write_json(path: Path, payload: object) -> None:
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
    config_path = project_root / ".harness-config.json"
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TaskRunnerError(f"cannot validate DUT read-only boundary: {exc}") from exc
        rtl_value = config.get("rtl", {}).get("root") if isinstance(config, dict) else None
        if isinstance(rtl_value, str) and rtl_value.strip():
            rtl_path = Path(rtl_value)
            rtl_root = (
                rtl_path.resolve()
                if rtl_path.is_absolute()
                else (project_root / rtl_path).resolve()
            )
            for task in tasks:
                for field, values in (("outputs", task.outputs), ("evidence", task.evidence)):
                    for value in values:
                        candidate = (project_root / value).resolve()
                        if candidate == rtl_root or candidate.is_relative_to(rtl_root):
                            raise TaskRunnerError(
                                f"task {task.task_id} {field} path enters read-only DUT RTL: {value}"
                            )
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
只读探查优先使用 rg/rg --files，并把每个探查作为独立命令执行。shell 正则若包含 Verilog
反引号（`）必须放在单引号中，绝不能放在双引号中；路径放在 -- 之后并单独引用。
禁止用分号拼接 grep/ls/head 等长探查命令；某个只读探查失败时修正该命令，不得把它误判为任务失败。
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


def approve_revised_contract(
    project_root: Path, run_dir: Path, run_id: str, reason: str
) -> dict[str, object]:
    """Rebind a corrected contract for a blocked run with explicit audit provenance."""
    if not reason.strip():
        raise TaskRunnerError("task contract revision requires a review reason")
    state = read_state(run_dir)
    if state is None or state.get("run_id") != run_id:
        raise TaskRunnerError(f"task state for run {run_id!r} does not exist")
    if state.get("status") != "BLOCKED":
        raise TaskRunnerError("task contract revision is allowed only while a task is BLOCKED")
    if state.get("task_worker_pid") is not None:
        raise TaskRunnerError("task worker is still active; stop and inspect it before revision")
    old_entries = _task_entries(state)
    completed = [str(item.get("task_id")) for item in old_entries if item.get("status") == "DONE"]
    if completed:
        raise TaskRunnerError(
            "cannot revise a contract after tasks are DONE; start a new workflow to preserve "
            f"review provenance: {', '.join(completed)}"
        )

    tasks_path, tasks = validate_document(project_root)
    prechecked = [task.task_id for task in tasks if task.checked]
    if prechecked:
        raise TaskRunnerError(
            "revised task contract contains pre-checked tasks: " + ", ".join(prechecked)
        )
    old_hash = state.get("task_contract_sha256")
    new_hash = contract_fingerprint(tasks)
    if old_hash == new_hash:
        raise TaskRunnerError("task contract did not change; resume the blocked task instead")
    revisions_path = run_dir / TASK_REVISIONS_FILE
    try:
        revisions = json.loads(revisions_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        revisions = []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskRunnerError(f"cannot read task revision audit {revisions_path}: {exc}") from exc
    if not isinstance(revisions, list):
        raise TaskRunnerError(f"task revision audit is malformed: {revisions_path}")

    old_by_id = {str(item.get("task_id")): item for item in old_entries}
    entries: list[dict[str, object]] = []
    for contract in tasks:
        previous = old_by_id.get(contract.task_id, {})
        entry = contract.as_dict()
        entry.update(
            {
                "status": "READY",
                "attempts": int(previous.get("attempts", 0)),
                "blocker": None,
                "answer": None,
                "started_at": None,
                "finished_at": None,
                "pid": None,
                "log": str(previous.get("log") or run_dir / f"task-{contract.task_id}.log"),
            }
        )
        entries.append(entry)

    blocked_task_id = state.get("current_task_id")
    state.update(
        {
            "tasks_file": str(tasks_path),
            "task_contract_sha256": new_hash,
            "status": "READY",
            "current_task_id": None,
            "task_worker_pid": None,
            "tasks": entries,
            "updated_at": _utc_now(),
        }
    )

    reconciled = False
    reconcile_reason = "blocked task was removed from the revised contract"
    current = next(
        (item for item in entries if item.get("task_id") == blocked_task_id), None
    )
    if current is not None:
        log_path = Path(str(current["log"]))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        reconcile_reason = _validate(project_root, current, log_path) or ""
        if not reconcile_reason:
            _mark_checkbox(tasks_path, str(blocked_task_id))
            current["status"] = "DONE"
            current["finished_at"] = _utc_now()
            reconciled = True
            state["status"] = (
                "DONE" if all(item.get("status") == "DONE" for item in entries) else "READY"
            )
            state["updated_at"] = current["finished_at"]

    review_payload: dict[str, object] = {
        "schema_version": 1,
        "run_id": run_id,
        "tasks_file": str(tasks_path),
        "task_contract_sha256": new_hash,
        "reviewed_at": _utc_now(),
        "review_kind": "task-contract-revision",
        "review_reason": reason.strip(),
    }
    revision = {
        "run_id": run_id,
        "reviewed_at": review_payload["reviewed_at"],
        "reason": reason.strip(),
        "blocked_task_id": blocked_task_id,
        "old_task_contract_sha256": old_hash,
        "new_task_contract_sha256": new_hash,
        "blocked_task_reconciled": reconciled,
        "reconciliation_gap": reconcile_reason or None,
    }
    revisions.append(revision)
    atomic_write_json(revisions_path, revisions)
    atomic_write_json(run_dir / TASK_REVIEW_FILE, review_payload)
    atomic_write_json(state_path(run_dir), state)
    return {"revision": revision, "task_execution": state}


def approve_pre_execution_revision(
    project_root: Path, run_dir: Path, run_id: str, reason: str
) -> dict[str, object]:
    """Rebind a corrected contract after legacy analyze but before execution."""
    if not reason.strip():
        raise TaskRunnerError("task contract revision requires a review reason")
    if read_state(run_dir) is not None:
        raise TaskRunnerError(
            "pre-execution task revision is unavailable after task execution state exists"
        )
    review_path = run_dir / TASK_REVIEW_FILE
    try:
        previous = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskRunnerError(f"cannot read reviewed task contract {review_path}: {exc}") from exc
    if not isinstance(previous, dict) or previous.get("run_id") != run_id:
        raise TaskRunnerError("reviewed task contract does not match this workflow run")

    tasks_path, tasks = validate_document(project_root)
    prechecked = [task.task_id for task in tasks if task.checked]
    if prechecked:
        raise TaskRunnerError(
            "revised task contract contains pre-checked tasks: " + ", ".join(prechecked)
        )
    old_hash = previous.get("task_contract_sha256")
    new_hash = contract_fingerprint(tasks)
    if old_hash == new_hash:
        raise TaskRunnerError("task contract did not change; review execution authorization")

    revisions_path = run_dir / TASK_REVISIONS_FILE
    try:
        revisions = json.loads(revisions_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        revisions = []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskRunnerError(f"cannot read task revision audit {revisions_path}: {exc}") from exc
    if not isinstance(revisions, list):
        raise TaskRunnerError(f"task revision audit is malformed: {revisions_path}")

    reviewed_at = _utc_now()
    revision = {
        "run_id": run_id,
        "reviewed_at": reviewed_at,
        "review_kind": "pre-execution-task-contract-revision",
        "reason": reason.strip(),
        "old_task_contract_sha256": old_hash,
        "new_task_contract_sha256": new_hash,
    }
    revisions.append(revision)
    review_payload: dict[str, object] = {
        "schema_version": 1,
        "run_id": run_id,
        "tasks_file": str(tasks_path),
        "task_contract_sha256": new_hash,
        "reviewed_at": reviewed_at,
        "review_kind": revision["review_kind"],
        "review_reason": reason.strip(),
    }
    atomic_write_json(revisions_path, revisions)
    atomic_write_json(review_path, review_payload)
    return {"revision": revision, "reviewed_contract": review_payload}


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
        task_id = state.get("current_task_id")
        blocked = next(
            (item for item in _task_entries(state) if item.get("task_id") == task_id),
            None,
        )
        blocker = blocked.get("blocker") if isinstance(blocked, dict) else None
        kind = blocker.get("kind") if isinstance(blocker, dict) else None
        reconciled = False
        if kind == "execution" and isinstance(blocked, dict):
            log_path = Path(
                str(blocked.get("log") or run_dir / f"task-{task_id}.log")
            )
            log_path.parent.mkdir(parents=True, exist_ok=True)
            reason = _validate(project_root, blocked, log_path)
            if reason is None:
                _mark_checkbox(Path(str(state["tasks_file"])), str(task_id))
                blocked["status"] = "DONE"
                blocked["blocker"] = None
                blocked["answer"] = None
                blocked["finished_at"] = _utc_now()
                state["status"] = (
                    "DONE"
                    if all(item.get("status") == "DONE" for item in _task_entries(state))
                    else "READY"
                )
                state["current_task_id"] = None
                state["updated_at"] = blocked["finished_at"]
                atomic_write_json(state_path(run_dir), state)
                reconciled = True
        if not reconciled:
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
