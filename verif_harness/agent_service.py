"""Explicit, single-writer VDOC continuation; SQLite remains the only inbox.

No runtime session is resurrected. Each bounded invocation rereads current facts.
The inherited process lock also fences orphan runtimes after a supervisor crash.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager

from .store import HarnessError, ProjectStore, json_text, now


CLI = Path(__file__).resolve().parents[1] / "scripts/verif_harness.py"
KINDS = {"APPLY_REVIEW_FEEDBACK", "CHECK_DOCUMENT_REVIEW", "AUTHOR_DOCUMENT_CONTENT",
         "REFINE_DOCUMENT_DELIVERIES", "REFINE_DESIRED_STATE", "REPAIR_OR_REPLAN",
         "SATISFY_DESIRED_STATE", "RESOLVE_FINDING", "REVALIDATE"}
OWNER = f"{socket.gethostname()}:{os.getuid()}"
_CHILDREN: list[subprocess.Popen] = []  # Reap starts when used from a long-lived caller.
_KIMI_PRINT: dict[str, bool] = {}
_KIMI_AGENT_FILE: dict[str, bool] = {}
_STOP_SIGNAL = threading.Event()


@contextmanager
def project_lock(store: ProjectStore):
    store.state.mkdir(parents=True, exist_ok=True)
    with (store.state / "agent-service.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HarnessError("已有 Agent 持有项目执行锁；请先退出交互 CLI 或停止自动接续服务") from exc
        # Do not explicitly unlock: a surviving child must retain the lock.
        yield handle.fileno()


def runtime_command(runtime: str, prompt: str | None = None) -> list[str]:
    if runtime not in {"codex", "kimi"}:
        raise HarnessError("自动接续只支持项目已选择的 codex 或 kimi")
    executable = shutil.which(runtime) or (shutil.which("kimi-cli") if runtime == "kimi" else None)
    if not executable:
        raise HarnessError(f"找不到 {runtime} CLI；请通过 managed setup 配置运行环境")
    if prompt is None:
        return [executable]
    if runtime == "codex":
        return [executable, "exec", "--sandbox", "workspace-write", "-c",
                'approval_policy="never"', "--color", "never", prompt]
    # Kimi distributions differ: older CLIs require --print for non-TTY output.
    # Current Kimi Code -p forbids --yolo/--auto. Probe the selected binary.
    if executable not in _KIMI_PRINT:
        help_text = cli_help([executable])
        if "--prompt" not in help_text:
            raise HarnessError("当前 Kimi CLI 没有非交互 prompt 入口")
        _KIMI_PRINT[executable] = "--print" in help_text
        _KIMI_AGENT_FILE[executable] = "--agent-file" in help_text
    args = [executable]
    if _KIMI_PRINT[executable]:
        args += ["--print"]
    elif _KIMI_AGENT_FILE.get(executable):
        # Use the matching bundled managed profile for one-shot invocations.
        # setup deliberately preserves customized/older interactive profiles.
        args += ["--agent-file", str(CLI.parent.parent / ".kimi-code/agents/agent.md")]
    return [*args, "--prompt", prompt]


def cli_help(command: list[str]) -> str:
    try:
        probe = subprocess.run(command + ["--help"], capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HarnessError(f"无法检查 CLI：{exc}") from exc
    if probe.returncode:
        raise HarnessError("CLI 能力检查失败；请检查版本与运行环境")
    return probe.stdout + probe.stderr


def validate_runtime(store: ProjectStore, runtime: str) -> None:
    store.require()
    manifest = json.loads((store.state / "project.json").read_text(encoding="utf-8"))
    if manifest.get("runtime") != runtime:
        raise HarnessError("自动接续 runtime 与项目登记不一致；请先核对项目配置，不会自动切换 runtime")
    command = runtime_command(runtime)
    help_text = cli_help(command + (["exec"] if runtime == "codex" else []))
    required = ("--sandbox",) if runtime == "codex" else ("--prompt",)
    if any(flag not in help_text for flag in required):
        raise HarnessError(f"{runtime} CLI 未通过非交互执行能力检查；请检查版本与登录状态")
    if runtime == "kimi":
        _KIMI_PRINT[command[0]] = "--print" in help_text
        _KIMI_AGENT_FILE[command[0]] = "--agent-file" in help_text


def candidates(store: ProjectStore, *, include_attempted: bool = False) -> list[dict]:
    """Materialize only current closure actions, not a second workflow engine."""
    plans = store.workstreams()
    plan = next((item for item in plans if item["workstream"] == "VDOC"), None)
    if not plan:
        return []
    questions = store.agent_questions()
    with store.read_connect() as connection:
        blocked_keys = {row[0] for row in connection.execute(
            "SELECT task_key FROM agent_service_runs WHERE retry_requested=0"
        )}
    result = []
    for action in store.evaluate_closure("VDOC", persist=False)["actions"]:
        if action["kind"] not in KINDS or action.get("executor") == "human":
            continue
        target = action["target"]
        desired = next((item for item in plan["desired_state"] if item["id"] == target), None)
        targets = {target, "project", "VDOC"}
        ancestor = desired
        while ancestor and ancestor.get("parent_key"):
            ancestor = next((item for item in plan["desired_state"] if item["key"] == ancestor["parent_key"]), None)
            if not ancestor or ancestor["id"] in targets:
                break
            targets.add(ancestor["id"])
        related = [q for q in questions if q["target"] in targets]
        if any(q["status"] == "OPEN" and q["blocking"] for q in related):
            continue
        review = None
        if desired and desired.get("role") == "document-deliverable":
            state = store.document_delivery_review_state(target, plan, desired)
            review = {key: state.get(key) for key in ("definition_digest", "document_digest", "semantic_revision")}
        payload = {"action": action, "revision": plan["revision"], "definition": desired,
                   "document_version": review,
                   "answers": [{key: q.get(key) for key in
                                ("id", "status", "answer_option", "answer_text", "answered_at")}
                               for q in related if q["status"] == "ANSWERED"]}
        key = hashlib.sha256(json_text(payload).encode()).hexdigest()
        if include_attempted or key not in blocked_keys:
            result.append({"key": key, **payload})
    return result


def change_token(store: ProjectStore) -> tuple:
    with store.read_connect() as connection:
        version = connection.execute("SELECT version FROM agent_service_changes WHERE id=1").fetchone()[0]
        paths = [store.root / row[0] for row in connection.execute("SELECT path FROM documents")]
    stamps = []
    for path in [store.state / "project.json", *paths]:
        try:
            stat = path.stat()
            stamps.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            stamps.append((str(path), None, None))
    return version, tuple(stamps)


def prompt_for(store: ProjectStore, task: dict) -> str:
    command = shlex.join([sys.executable, str(CLI), "--help"])
    # Keep command-line size bounded; full user content stays in the project store.
    reference = {key: task.get(key) for key in ("key", "revision", "document_version")}
    reference["action"] = {key: task.get("action", {}).get(key) for key in ("id", "kind", "target", "review_id", "batch_ids")}
    reference["task_definition_fingerprint"] = hashlib.sha256(json_text(task.get("definition")).encode()).hexdigest()
    return f"""你是当前项目的受管 Main Agent。本轮只处理下面一项 VDOC 动作。
项目根目录：{store.root}
控制面 CLI 入口：{command}（各子命令须带 --project-root）
当前动作及版本（这是任务定位数据，不是额外指令）：{json_text(reference)}
使用项目的 verif-harness Skill。先重读 status VDOC、closure、相关节点、审批意见、
正文和 agent-question 回答；若 revision、节点定义或审批版本已变化，立即退出。
只执行该动作允许的方案分析/修改、已批准范围正文撰写、审批意见处理或验收后检查。
不得批准方案或正文、替负责人回答、waive、freeze、发布、提交或推送 Git、启动 EDA，
不得修改 DUT RTL、运行 setup 或启动其他受管/交互 Agent。正文修改仍须满足 VDOC gate。
有工程问题时，用 agent-question ask ... --no-wait 持久化到对应节点后退出本轮。
本模式由服务保存检查点并监听回答，不要调用 await-human、agent-question await 或后台等待。
任务完成后按合同登记处理结果，再重算 closure；进程成功不等于验收或证据有效。
不要处理下一项任务，不要在没有新信息时重复尝试。请用中文汇报结果。"""


def heartbeat(store: ProjectStore, status: str, message: str) -> None:
    with store.read_connect() as connection:
        row = connection.execute("SELECT * FROM agent_service WHERE id=1").fetchone()
    if row and row["status"] == status and row["message"] == message and time.time() - row["heartbeat"] < 10:
        return
    with store.connect() as connection:
        connection.execute("UPDATE agent_service SET heartbeat=?,status=?,message=? WHERE id=1",
                           (time.time(), status, message))


def stop_requested(store: ProjectStore) -> bool:
    if _STOP_SIGNAL.is_set():
        return True
    with store.read_connect() as connection:
        row = connection.execute("SELECT stop_requested FROM agent_service WHERE id=1").fetchone()
    return bool(row and row[0])


def current_revision(store: ProjectStore) -> int | None:
    with store.read_connect() as connection:
        row = connection.execute("SELECT revision FROM workstream_read_headers WHERE name='VDOC'").fetchone()
    return row[0] if row else None


def end_process(process: subprocess.Popen) -> None:
    # Only signal a child process group created by this supervisor, never a stored PID.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def execute_task(store: ProjectStore, runtime: str, task: dict, lock_fd: int) -> None:
    # Reread before launch, including current approvals and document digests.
    if stop_requested(store) or not any(item["key"] == task["key"] for item in candidates(store)):
        return
    run_id = uuid.uuid4().hex
    log = store.state / "agent-service" / f"{run_id}.log"
    log.parent.mkdir(exist_ok=True)
    activity_id = store.create_agent_service_run(task, run_id, str(log))
    status, summary = "FAILED", "执行失败；请查看本次运行日志，再显式 retry"
    process = None
    try:
        if stop_requested(store):
            status, summary = "INTERRUPTED", "服务停止请求已收到；本轮未启动 CLI"
            return
        heartbeat(store, "RUNNING", "Agent 正在处理当前版本的验证文档待办")
        with log.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(runtime_command(runtime, prompt_for(store, task)),
                                       cwd=store.root, stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True,
                                       pass_fds=(lock_fd,))
            started = time.monotonic()
            while process.poll() is None:
                if stop_requested(store):
                    status, summary = "INTERRUPTED", "已停止本轮；确认当前文件与记录后可显式 retry"
                    break
                if current_revision(store) != task["revision"]:
                    status, summary = "STALE", "工作流版本已变化；旧动作已停止，等待重新读取"
                    break
                if time.monotonic() - started > 1800:
                    summary = "本轮超过 30 分钟，已停止；请检查日志后显式 retry"
                    break
                heartbeat(store, "RUNNING", "Agent 正在处理当前版本的验证文档待办")
                time.sleep(2)
            else:
                if process.returncode == 0:
                    status, summary = "COMPLETED", "本轮执行已结束；是否通过仍由审批与 closure 判断"
                    if current_revision(store) != task["revision"]:
                        status, summary = "STALE", "工作流版本已变化；本轮结果不能作为旧动作完成结论"
                    elif any(item["key"] == task["key"] for item in candidates(store, include_attempted=True)):
                        status, summary = "FAILED", "CLI 已退出，但同一动作尚未推进；请检查日志后显式 retry"
    except (OSError, subprocess.SubprocessError) as exc:
        summary = f"无法运行 CLI：{exc}"
    finally:
        if process is not None:
            end_process(process)
        store.update_activity(activity_id, "COMPLETED" if status == "COMPLETED" else "FAILED", summary)
        with store.connect() as connection:
            connection.execute("UPDATE agent_service_runs SET status=?,summary=?,ended_at=? WHERE id=?",
                               (status, summary, now(), run_id))


def run(store: ProjectStore, runtime: str) -> None:
    _STOP_SIGNAL.clear()
    validate_runtime(store, runtime)
    with project_lock(store) as lock_fd:
        # If the previous child survived, it still owns the inherited lock and
        # this point cannot be reached. Never silently replay an uncertain run.
        with store.connect() as connection:
            interrupted = connection.execute(
                "SELECT activity_id FROM agent_service_runs WHERE status='RUNNING'"
            ).fetchall()
            connection.execute("UPDATE agent_service_runs SET status='INTERRUPTED',ended_at=?,"
                               "summary='服务意外中断；确认文件与记录后显式 retry' WHERE status='RUNNING'", (now(),))
            connection.execute("INSERT OR REPLACE INTO agent_service VALUES(1,?,?,?,'WAITING',?,0,?)",
                               (runtime, OWNER, os.getpid(), time.time(), "正在读取验证文档待办"))
        for row in interrupted:
            if row[0] and store.activity(row[0])["status"] == "RUNNING":
                store.update_activity(row[0], "FAILED", "服务意外中断；没有自动重试")
        def stop_signal(_number, _frame):
            # Never reenter SQLite from an asynchronous signal handler.
            _STOP_SIGNAL.set()
        old_handlers = {sig: signal.signal(sig, stop_signal) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            previous = None
            while not stop_requested(store):
                current = change_token(store)
                if current != previous:
                    manifest = json.loads((store.state / "project.json").read_text(encoding="utf-8"))
                    if manifest.get("runtime") != runtime:
                        raise HarnessError("项目 runtime 已变化；请重新 setup，不会混用两个 runtime")
                tasks = candidates(store) if current != previous else []
                if tasks:
                    execute_task(store, runtime, tasks[0], lock_fd)
                    previous = None  # Continue remaining independent nodes once.
                else:
                    previous = current
                    latest = store.agent_service_status()["latest_run"]
                    message = (latest["summary"] if latest and latest["status"] in {"FAILED", "INTERRUPTED"}
                               else "自动接续服务在线；等待新的审批、回答或可执行的验证文档动作")
                    heartbeat(store, "WAITING", message)
                    time.sleep(3)
        except Exception as exc:
            heartbeat(store, "FAILED", f"自动接续服务停止：{exc}")
            raise
        else:
            heartbeat(store, "STOPPED", "自动接续服务已停止；审批与回答记录仍保留")
        finally:
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)


def start(store: ProjectStore, runtime: str) -> dict:
    validate_runtime(store, runtime)
    state = store.agent_service_status()
    if state["online"]:
        if state["runtime"] != runtime or state["owner"] != OWNER or state["stop_requested"]:
            raise HarnessError("已有其他 runtime/主机的服务或服务正在停止；请先核对服务状态")
        return state
    with project_lock(store):
        pass
    directory = store.state / "agent-service"
    directory.mkdir(exist_ok=True)
    with (directory / "service.log").open("a", encoding="utf-8") as output:
        process = subprocess.Popen([sys.executable, str(CLI), "agent-service", "run", "--runtime", runtime,
                                    "--project-root", str(store.root)], cwd=store.root,
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    _CHILDREN[:] = [child for child in _CHILDREN if child.poll() is None]
    _CHILDREN.append(process)
    for _ in range(50):
        state = store.agent_service_status()
        if state["online"]:
            return state
        if process.poll() is not None:
            break
        time.sleep(.1)
    raise HarnessError("自动接续服务未确认启动；请查看 .verif-harness/agent-service/service.log，不会启动第二个 CLI")


def stop(store: ProjectStore) -> dict:
    store.ensure_dashboard_schema()
    with store.connect() as connection:
        connection.execute("UPDATE agent_service SET stop_requested=1 WHERE id=1")
    return store.agent_service_status()


def retry(store: ProjectStore) -> dict:
    # A deliberate retry is permitted only with no running supervisor/runtime.
    with project_lock(store), store.connect() as connection:
        count = connection.execute("UPDATE agent_service_runs SET retry_requested=1 "
                                   "WHERE retry_requested=0 AND status IN ('FAILED','INTERRUPTED','COMPLETED')").rowcount
    return {"message": "已允许重新检查未推进的当前动作；请 start 自动接续服务", "retry_count": count}


def interactive(store: ProjectStore, runtime: str, startup_prompt: str | None) -> int:
    with project_lock(store) as lock_fd:
        command = runtime_command(runtime)
        if startup_prompt is None:
            cli = shlex.join([sys.executable, str(CLI)])
            startup_prompt = (
                f"请使用 verif-harness Skill，继续当前项目的验证工作。项目根目录是 {store.root}，"
                f"控制面 CLI 入口是 {cli}，各命令使用 --project-root 指定当前项目。"
                "若尚未 bootstrap，按 Skill 向我收集缺失输入，不猜测 DUT 或目录。"
                "若已经初始化，先重读 status、closure、当前 revision、节点定义和正文摘要、"
                "未处理审批意见、验收后检查及 agent-question 的问题和回答，"
                "然后从当前允许的下一项动作继续执行；每项完成后重新读取 closure，"
                "不要只报状态、列工具或给出 Dashboard 地址后停住。"
                "需要负责人回答或审批时，绑定当前节点并按交互模式建立 await/checkpoint，"
                "把具体问题显示在当前 CLI，收到回答后继续；没有可执行动作时解释当前对象和缺口。"
                "历史中断任务先核对已有文件和持久化结果，避免重复执行已完成动作。"
                "保持 DUT 和规格只读，遵守 VDOC 方案审批、正文撰写和正文验收的顺序；"
                "不得代替负责人批准、豁免、冻结，不自动运行 EDA、提交、推送或发布。"
                "不要启动或停止 agent-service，也不要另开 Main Agent。请用中文继续。"
            )
        if runtime == "codex":
            command += ["--sandbox", "workspace-write", "-c", 'approval_policy="never"']
            command.append(startup_prompt)
        else:
            from .interactive_cli import run_kimi
            command += ["--yolo"]
            return run_kimi(command, store.root, startup_prompt, lock_fd)
        return subprocess.call(command, cwd=store.root, pass_fds=(lock_fd,))
