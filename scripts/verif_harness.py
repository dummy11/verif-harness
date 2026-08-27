#!/usr/bin/env python3
"""Run verif-harness generators and managed integrations."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import task_runner


IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")
WORKFLOW_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
FILES = {
    "dut_if.sv.tmpl": "interfaces/{dut}_if.sv",
    "dut_tb_harness.sv.tmpl": "tb/harness/{dut}_tb_harness.sv",
    "dut_tb_top.sv.tmpl": "tb/{dut}_tb_top.sv",
    "dut_checker.sv.tmpl": "sva/{dut}_checker.sv",
    "dut_bind.sv.tmpl": "bind/{dut}_bind.sv",
    "dut.f.tmpl": "filelists/{dut}.f",
}

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_RUNTIMES = ("codex", "kimi")
COMMAND_ALIASES = {
    "probe": ("spec-kit", "probe"),
    "bootstrap": ("spec-kit", "bootstrap"),
    "stage": ("spec-kit", "stage"),
    "workflow-status": ("spec-kit", "status"),
    "workflow-resume": ("spec-kit", "resume"),
    "workflow-recover": ("spec-kit", "recover"),
    "status": ("spec-kit", "status"),
    "resume": ("spec-kit", "resume"),
    "block": ("spec-kit", "block"),
    "recover": ("spec-kit", "recover"),
    "docs": ("spec-kit", "docs-zh"),
    "evidence": ("xverif",),
    "waveform": ("wavepeek",),
}
RUNTIME_PROFILES = {
    "codex": {
        "markers": (".agents", ".codex"),
        "skill_dir": ".agents/skills",
        "invocation": "$verif-harness",
    },
    "kimi": {
        "markers": (".kimi-code",),
        "skill_dir": ".kimi-code/skills",
        "invocation": "/skill:verif-harness",
    },
}
INTEGRATION_STATE = Path(".specify/integration.json")
GATE_VERDICT_INPUTS = {
    "review-constitution": "review_constitution_verdict",
    "review-spec": "review_spec_verdict",
    "review-clarification": "review_clarification_verdict",
    "review-plan": "review_plan_verdict",
    "review-checklist": "review_checklist_verdict",
    "review-tasks": "review_tasks_verdict",
    "authorize-execution": "authorize_execution_verdict",
    "review-implementation": "review_implementation_verdict",
    "review-convergence": "review_convergence_verdict",
}
AGENT_LAUNCH_ENV = "VERIF_HARNESS_AGENT_CLI"
WORKER_METADATA = "verif-harness-worker.json"
WORKER_LOG = "verif-harness-worker.log"
STALE_RUN_MIN_AGE_SECONDS = 30


class RuntimeSelectionError(ValueError):
    """Raised when the project runtime cannot be resolved safely."""


def read_runtime_state(project_root: Path) -> dict[str, object] | None:
    """Read the Spec Kit integration state without inventing fallback state."""
    path = project_root / INTEGRATION_STATE
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeSelectionError(f"cannot read {INTEGRATION_STATE}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeSelectionError(f"{INTEGRATION_STATE} must contain a JSON object")
    schema = value.get("integration_state_schema", 1)
    if not isinstance(schema, int) or isinstance(schema, bool) or schema > 1:
        raise RuntimeSelectionError(
            f"unsupported {INTEGRATION_STATE} schema: {schema!r}"
        )
    runtime = value.get("default_integration") or value.get("integration")
    if runtime not in SUPPORTED_RUNTIMES:
        raise RuntimeSelectionError(
            f"active Spec Kit integration must be one of {SUPPORTED_RUNTIMES}, got {runtime!r}"
        )
    installed = value.get("installed_integrations", [runtime])
    if not isinstance(installed, list) or not all(
        isinstance(item, str) for item in installed
    ):
        raise RuntimeSelectionError(
            f"{INTEGRATION_STATE} installed_integrations must be a string array"
        )
    return {
        "runtime": runtime,
        "installed_integrations": installed,
        "source": str(INTEGRATION_STATE),
    }


def resolve_runtime(project_root: Path, requested: str = "auto") -> dict[str, object]:
    """Resolve an explicit, recorded, or uniquely detected Agent runtime."""
    if requested in SUPPORTED_RUNTIMES:
        return {
            "runtime": requested,
            "installed_integrations": [],
            "source": "command-line",
        }
    if requested != "auto":
        raise RuntimeSelectionError(
            f"runtime must be auto or one of {SUPPORTED_RUNTIMES}, got {requested!r}"
        )
    recorded = read_runtime_state(project_root)
    if recorded is not None:
        return recorded
    detected = [
        runtime
        for runtime, profile in RUNTIME_PROFILES.items()
        if any((project_root / marker).exists() for marker in profile["markers"])
    ]
    if len(detected) == 1:
        return {
            "runtime": detected[0],
            "installed_integrations": [],
            "source": "project-markers",
        }
    if detected:
        raise RuntimeSelectionError(
            "multiple Agent runtime markers found; pass --integration codex or kimi"
        )
    raise RuntimeSelectionError(
        "no Agent runtime marker found; pass --integration codex or kimi"
    )


def refresh_spec_kit_chinese_docs(project_root: Path) -> int:
    """Refresh the non-executable Chinese mirror for an initialized project."""
    script = ROOT / "scripts/configure_spec_kit_chinese_docs.py"
    return subprocess.run(
        [sys.executable, str(script), "--project-root", str(project_root)],
        check=False,
    ).returncode


def runtime_payload(project_root: Path, requested: str = "auto") -> dict[str, object]:
    resolved = resolve_runtime(project_root, requested)
    runtime = str(resolved["runtime"])
    skill_path = project_root / str(RUNTIME_PROFILES[runtime]["skill_dir"]) / "verif-harness"
    return {
        **resolved,
        "project_root": str(project_root),
        "skill_dir": RUNTIME_PROFILES[runtime]["skill_dir"],
        "skill_path": str(skill_path),
        "skill_present": (skill_path / "SKILL.md").is_file(),
        "invocation": RUNTIME_PROFILES[runtime]["invocation"],
    }


def managed_spec_kit() -> tuple[str, dict[str, object]]:
    checked = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/setup_spec_kit.py"),
            "--project-root",
            str(ROOT),
            "--check",
            "--json",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if checked.returncode != 0:
        sys.stdout.write(checked.stdout)
        sys.stderr.write(checked.stderr)
        raise SystemExit(checked.returncode)
    payload = json.loads(checked.stdout)
    return str(payload["python"]), payload


def spec_kit_command(arguments: list[str]) -> list[str]:
    """Build one command for the commit-pinned managed Spec Kit runtime."""
    python, _ = managed_spec_kit()
    return [python, "-c", "from specify_cli import main; main()", *arguments]


def agent_exec_args(runtime: str, prompt: str) -> list[str]:
    """Build the pinned Spec Kit integration's native noninteractive argv."""
    python, _ = managed_spec_kit()
    built = subprocess.run(
        [
            python,
            "-c",
            (
                "import json,sys;"
                "from specify_cli.integrations import get_integration;"
                "impl=get_integration(sys.argv[1]);"
                "args=impl.build_exec_args(sys.argv[2], output_json=False) if impl else None;"
                "print(json.dumps(args))"
            ),
            runtime,
            prompt,
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if built.returncode != 0:
        raise task_runner.TaskRunnerError(
            built.stderr.strip() or f"cannot resolve {runtime} Agent command"
        )
    try:
        payload = json.loads(built.stdout)
    except json.JSONDecodeError as exc:
        raise task_runner.TaskRunnerError(
            f"managed Spec Kit returned invalid Agent argv: {exc}"
        ) from exc
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        raise task_runner.TaskRunnerError(f"runtime {runtime} cannot execute task prompts")
    return payload


def run_task_execution(
    project_root: Path,
    run_id: str,
    runtime: str,
    *,
    answer: str | None = None,
) -> dict[str, object]:
    """Advance only the current reviewed task until DONE or a real BLOCKED state."""
    invocation = str(RUNTIME_PROFILES[runtime]["invocation"])
    return task_runner.run_tasks(
        project_root,
        workflow_run_dir(project_root, run_id),
        run_id,
        runtime,
        invocation,
        agent_exec_args,
        answer=answer,
    )


def run_spec_kit(
    arguments: list[str], project_root: Path, *, noninteractive: bool = False
) -> int:
    """Run Spec Kit, optionally preventing a PTY from consuming gate choices."""
    return subprocess.run(
        spec_kit_command(arguments),
        cwd=project_root,
        stdin=subprocess.DEVNULL if noninteractive else None,
        check=False,
    ).returncode


def spec_kit_run_status(run_id: str, project_root: Path) -> dict[str, object]:
    """Return the stable JSON status payload for one workflow run."""
    inspected = subprocess.run(
        spec_kit_command(["workflow", "status", run_id, "--json"]),
        cwd=project_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if inspected.returncode != 0:
        sys.stdout.write(inspected.stdout)
        sys.stderr.write(inspected.stderr)
        raise RuntimeSelectionError(f"cannot inspect Spec Kit workflow run {run_id!r}")
    try:
        payload = json.loads(inspected.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeSelectionError(
            f"Spec Kit returned invalid JSON while inspecting run {run_id!r}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeSelectionError(
            f"Spec Kit status for run {run_id!r} must be a JSON object"
        )
    return payload


def workflow_run_dir(project_root: Path, run_id: str) -> Path:
    """Return one workflow run directory after rejecting path traversal."""
    if not WORKFLOW_RUN_ID.fullmatch(run_id):
        raise RuntimeSelectionError(f"invalid workflow run ID {run_id!r}")
    return project_root / ".specify/workflows/runs" / run_id


def atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    """Write JSON atomically so status readers never observe partial metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def utc_now() -> str:
    """Return one stable UTC timestamp for worker and recovery evidence."""
    return dt.datetime.now(dt.timezone.utc).isoformat()


def process_is_running(pid: object) -> bool:
    """Best-effort check that a non-zombie process still owns *pid*."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    if os.name != "posix":
        return True
    inspected = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    status = inspected.stdout.strip()
    return inspected.returncode == 0 and bool(status) and not status.startswith("Z")


def matching_workflow_processes(run_id: str) -> list[int]:
    """Find visible stage/resume processes associated with one workflow run."""
    if not WORKFLOW_RUN_ID.fullmatch(run_id) or os.name != "posix":
        return []
    inspected = subprocess.run(
        ["ps", "eww", "-axo", "pid=,command="],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if inspected.returncode != 0:
        inspected = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    matches: list[int] = []
    for line in inspected.stdout.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        pid, command = int(fields[0]), fields[1]
        if pid == os.getpid():
            continue
        has_run_id = (
            f"SPECKIT_WORKFLOW_RUN_ID={run_id}" in command
            or re.search(rf"(?:resume|status)\s+{re.escape(run_id)}(?:\s|$)", command)
            is not None
        )
        is_workflow = "verif_harness.py" in command or "specify_cli" in command
        if has_run_id and is_workflow:
            matches.append(pid)
    return matches


def worker_metadata(project_root: Path, run_id: str) -> dict[str, object] | None:
    """Read optional detached-worker metadata for one run."""
    path = workflow_run_dir(project_root, run_id) / WORKER_METADATA
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeSelectionError(
            f"cannot read worker metadata for workflow run {run_id!r}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeSelectionError(
            f"worker metadata for workflow run {run_id!r} must be a JSON object"
        )
    return payload


def active_workflow_processes(project_root: Path, run_id: str) -> list[int]:
    """Return tracked or discoverable processes that may still mutate a run."""
    active = set(matching_workflow_processes(run_id))
    metadata = worker_metadata(project_root, run_id)
    if metadata is not None and process_is_running(metadata.get("pid")):
        active.add(int(metadata["pid"]))
    try:
        task_state = task_runner.read_state(workflow_run_dir(project_root, run_id))
    except task_runner.TaskRunnerError as exc:
        raise RuntimeSelectionError(str(exc)) from exc
    if task_state is not None and process_is_running(task_state.get("task_worker_pid")):
        active.add(int(task_state["task_worker_pid"]))
    return sorted(active)


def should_detach(args: argparse.Namespace) -> bool:
    """Detach Agent-launched stage/resume commands unless foreground is explicit."""
    return bool(
        getattr(args, "detach", False)
        or (
            os.environ.get(AGENT_LAUNCH_ENV) == "1"
            and not getattr(args, "foreground", False)
        )
    )


def reserve_workflow_run(project_root: Path) -> tuple[str, Path]:
    """Reserve a collision-free run directory before launching a worker."""
    runs = project_root / ".specify/workflows/runs"
    runs.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        run_id = uuid.uuid4().hex[:8]
        run_dir = runs / run_id
        try:
            run_dir.mkdir()
        except FileExistsError:
            continue
        return run_id, run_dir
    raise RuntimeSelectionError("cannot reserve a unique Spec Kit workflow run ID")


def launch_detached_workflow(
    project_root: Path,
    run_id: str,
    operation: str,
    wrapper_arguments: list[str],
) -> int:
    """Launch a stage/resume worker that survives the Agent's outer task timeout."""
    run_dir = workflow_run_dir(project_root, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    active = active_workflow_processes(project_root, run_id)
    if active:
        raise RuntimeSelectionError(
            f"workflow run {run_id!r} already has an active process: {active}"
        )
    log_path = run_dir / WORKER_LOG
    environment = os.environ.copy()
    environment[AGENT_LAUNCH_ENV] = "0"
    environment["SPECKIT_WORKFLOW_RUN_ID"] = run_id
    command = [sys.executable, str(Path(__file__).resolve()), *wrapper_arguments]
    popen_options: dict[str, object] = {
        "cwd": project_root,
        "env": environment,
        "stdin": subprocess.DEVNULL,
        "stdout": None,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "posix":
        popen_options["start_new_session"] = True
    elif os.name == "nt":  # pragma: no cover - exercised only on Windows
        popen_options["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    with log_path.open("a", encoding="utf-8") as log:
        popen_options["stdout"] = log
        process = subprocess.Popen(command, **popen_options)
    metadata = {
        "schema_version": 1,
        "run_id": run_id,
        "operation": operation,
        "pid": process.pid,
        "started_at": utc_now(),
        "log": str(log_path),
        "command": wrapper_arguments,
    }
    atomic_write_json(run_dir / WORKER_METADATA, metadata)
    print(
        json.dumps(
            {
                "run_id": run_id,
                "status": "starting",
                "worker_pid": process.pid,
                "log": str(log_path),
                "next": f"status {run_id}",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def recover_stale_workflow(
    project_root: Path, run_id: str, *, confirmed: bool
) -> dict[str, object]:
    """Mark an externally interrupted running workflow resumable after review."""
    if not confirmed:
        raise RuntimeSelectionError(
            "stale-run recovery requires --confirm-stale after checking no worker is alive"
        )
    run_dir = workflow_run_dir(project_root, run_id)
    task_state = task_runner.read_state(run_dir)
    if task_state is not None and task_state.get("status") == "RUNNING":
        if process_is_running(task_state.get("task_worker_pid")):
            raise RuntimeSelectionError(
                f"refusing recovery while task process {task_state.get('task_worker_pid')} is active"
            )
        active = active_workflow_processes(project_root, run_id)
        if active:
            raise RuntimeSelectionError(
                f"refusing recovery while workflow process(es) are active: {active}"
            )
        try:
            recovered_task = task_runner.recover_running_task(
                project_root, run_dir, run_id
            )
        except task_runner.TaskRunnerError as exc:
            raise RuntimeSelectionError(str(exc)) from exc
        if recovered_task is None:
            raise RuntimeSelectionError("RUNNING task state could not be recovered")
        return {
            "schema_version": 1,
            "run_id": run_id,
            "recovered_at": utc_now(),
            "scope": "task",
            "current_task_id": recovered_task.get("current_task_id"),
            "task_status": recovered_task.get("status"),
            "reason": (
                "Reconciled interrupted task from reviewed postconditions; "
                "resume continues at the exact unfinished task"
            ),
        }
    state_path = run_dir / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeSelectionError(
            f"cannot read workflow state for run {run_id!r}: {exc}"
        ) from exc
    if not isinstance(state, dict) or state.get("run_id") != run_id:
        raise RuntimeSelectionError(f"invalid workflow state for run {run_id!r}")
    if state.get("status") != "running":
        raise RuntimeSelectionError(
            f"workflow run {run_id!r} has status {state.get('status')!r}; "
            "only an interrupted 'running' run can be recovered"
        )
    age_seconds = time.time() - state_path.stat().st_mtime
    if age_seconds < STALE_RUN_MIN_AGE_SECONDS:
        raise RuntimeSelectionError(
            f"workflow run {run_id!r} was updated {age_seconds:.1f}s ago; "
            f"wait at least {STALE_RUN_MIN_AGE_SECONDS}s before stale recovery"
        )
    active = active_workflow_processes(project_root, run_id)
    if active:
        raise RuntimeSelectionError(
            f"refusing recovery while workflow process(es) are active: {active}"
        )
    recovered_at = utc_now()
    reason = (
        "Recovered after confirmed external worker interruption; resume retries "
        "the current step"
    )
    previous_updated_at = state.get("updated_at")
    state["status"] = "failed"
    state["error"] = reason
    state["updated_at"] = recovered_at
    atomic_write_json(state_path, state)
    evidence = {
        "schema_version": 1,
        "run_id": run_id,
        "recovered_at": recovered_at,
        "previous_status": "running",
        "previous_updated_at": previous_updated_at,
        "current_step_index": state.get("current_step_index"),
        "current_step_id": state.get("current_step_id"),
        "reason": reason,
    }
    atomic_write_json(run_dir / "verif-harness-recovery.json", evidence)
    return evidence


def spec_kit_run_inputs(run_id: str, project_root: Path) -> set[str]:
    """Read the declared inputs persisted with a safely named workflow run."""
    path = workflow_run_dir(project_root, run_id) / "inputs.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeSelectionError(
            f"cannot read persisted inputs for workflow run {run_id!r}: {exc}"
        ) from exc
    inputs = payload.get("inputs") if isinstance(payload, dict) else None
    if not isinstance(inputs, dict):
        raise RuntimeSelectionError(
            f"persisted inputs for workflow run {run_id!r} must be a JSON object"
        )
    return set(inputs)


def resume_verdict_input(
    payload: dict[str, object], verdict: str, available_inputs: set[str]
) -> str:
    """Bind a reviewed verdict to exactly the gate where a run is paused."""
    if payload.get("status") != "paused":
        raise RuntimeSelectionError(
            f"workflow run {payload.get('run_id')!r} is not paused"
        )
    gate = payload.get("gate")
    if not isinstance(gate, dict) or not isinstance(gate.get("step_id"), str):
        raise RuntimeSelectionError(
            f"workflow run {payload.get('run_id')!r} is not paused at a review gate"
        )
    step_id = gate["step_id"]
    input_name = GATE_VERDICT_INPUTS.get(step_id)
    if input_name is None:
        raise RuntimeSelectionError(
            f"review gate {step_id!r} has no safe verdict binding; "
            "the run may predate this workflow version and must be restarted"
        )
    if input_name not in available_inputs:
        raise RuntimeSelectionError(
            f"workflow run {payload.get('run_id')!r} predates safe gate verdict "
            "binding and must be restarted"
        )
    return f"{input_name}={verdict}"


def generate(dut: str, output: Path, templates: Path, dry_run: bool) -> list[Path]:
    if not IDENTIFIER.fullmatch(dut):
        raise SystemExit("ERROR: DUT name must match [a-z][a-z0-9_]*")
    if not templates.is_dir():
        raise SystemExit(f"ERROR: template directory missing: {templates}")
    targets = [output / pattern.format(dut=dut) for pattern in FILES.values()]
    existing = [path for path in targets if path.exists()]
    if existing:
        raise SystemExit("ERROR: refusing to overwrite: " + ", ".join(map(str, existing)))
    if dry_run:
        return targets
    for template_name, pattern in FILES.items():
        source = templates / template_name
        if not source.is_file():
            raise SystemExit(f"ERROR: template missing: {source}")
        target = output / pattern.format(dut=dut)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8").replace("<DUT>", dut), encoding="utf-8")
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init", help="generate a DUT integration skeleton")
    init.add_argument("dut")
    init.add_argument("--output", type=Path, default=Path.cwd())
    init.add_argument("--templates", type=Path,
                      default=Path(__file__).resolve().parents[1] / "templates/dut")
    init.add_argument("--dry-run", action="store_true")
    xverif = subparsers.add_parser(
        "xverif", help="delegate a reviewed request through the deterministic xverif adapter"
    )
    xverif.add_argument("adapter_args", nargs=argparse.REMAINDER)
    wavepeek = subparsers.add_parser(
        "wavepeek", help="delegate a reviewed request through the deterministic WavePeek adapter"
    )
    wavepeek.add_argument("adapter_args", nargs=argparse.REMAINDER)
    spec_kit = subparsers.add_parser(
        "spec-kit", help="manage specification workflows through pinned GitHub Spec Kit"
    )
    spec_subparsers = spec_kit.add_subparsers(dest="spec_command", required=True)
    spec_subparsers.add_parser("probe", help="validate the managed Spec Kit dependency")
    bootstrap = spec_subparsers.add_parser(
        "bootstrap", help="initialize Spec Kit for a detected or selected Agent runtime"
    )
    bootstrap.add_argument("--project-root", type=Path, default=Path.cwd())
    bootstrap.add_argument(
        "--integration", choices=("auto", *SUPPORTED_RUNTIMES), default="auto",
        help="Agent runtime; auto requires exactly one project marker",
    )
    bootstrap.add_argument(
        "--ignore-agent-tools", action="store_true",
        help="skip Agent CLI discovery for CI/scaffold validation",
    )
    stage = spec_subparsers.add_parser(
        "stage", help="run the reviewed Spec Kit lifecycle for one verification stage"
    )
    stage.add_argument("--project-root", type=Path, default=Path.cwd())
    stage.add_argument("--stage", choices=["0", "1", "2", "3", "4", "5"], required=True)
    stage.add_argument("--objective", required=True)
    stage_execution = stage.add_mutually_exclusive_group()
    stage_execution.add_argument(
        "--detach", action="store_true",
        help="run in a detached, logged worker and return the run ID immediately",
    )
    stage_execution.add_argument(
        "--foreground", action="store_true",
        help="run synchronously even when invoked through the Agent Skill launcher",
    )
    resume = spec_subparsers.add_parser(
        "resume", help="resume a paused Stage workflow at its next review gate"
    )
    resume.add_argument("run_id")
    resume.add_argument("--project-root", type=Path, default=Path.cwd())
    resume.add_argument(
        "--verdict", choices=("approve", "reject"),
        help="review verdict for the run's current gate",
    )
    resume.add_argument(
        "--answer",
        help="answer or authority record for the current BLOCKED task",
    )
    resume_execution = resume.add_mutually_exclusive_group()
    resume_execution.add_argument(
        "--detach", action="store_true",
        help="resume in a detached, logged worker and return immediately",
    )
    resume_execution.add_argument(
        "--foreground", action="store_true",
        help="resume synchronously even when invoked through the Agent Skill launcher",
    )
    status = spec_subparsers.add_parser(
        "status", help="show one or all Spec Kit workflow run states"
    )
    status.add_argument("run_id", nargs="?")
    status.add_argument("--project-root", type=Path, default=Path.cwd())
    recover = spec_subparsers.add_parser(
        "recover",
        help="make a confirmed externally interrupted 'running' run resumable",
    )
    recover.add_argument("run_id")
    recover.add_argument("--project-root", type=Path, default=Path.cwd())
    recover.add_argument(
        "--confirm-stale", action="store_true",
        help="confirm the outer worker ended and authorize the state repair",
    )
    block = spec_subparsers.add_parser(
        "block", help="persist a task-level blocker for the current running task"
    )
    block.add_argument("run_id")
    block.add_argument("task_id")
    block.add_argument("--project-root", type=Path, default=Path.cwd())
    block.add_argument("--kind", choices=sorted(task_runner.BLOCK_KINDS), required=True)
    block.add_argument("--question", required=True)
    docs_zh = spec_subparsers.add_parser(
        "docs-zh", help="refresh the non-executable Simplified Chinese .specify mirror"
    )
    docs_zh.add_argument("--project-root", type=Path, default=Path.cwd())
    runtime = subparsers.add_parser(
        "runtime", help="inspect or switch the project Agent runtime"
    )
    runtime_subparsers = runtime.add_subparsers(dest="runtime_command", required=True)
    runtime_status = runtime_subparsers.add_parser(
        "status", help="show the resolved runtime and native Skill invocation"
    )
    runtime_status.add_argument("--project-root", type=Path, default=Path.cwd())
    runtime_switch = runtime_subparsers.add_parser(
        "switch", help="switch the active Spec Kit integration"
    )
    runtime_switch.add_argument("--project-root", type=Path, default=Path.cwd())
    runtime_switch.add_argument("--to", choices=SUPPORTED_RUNTIMES, required=True)
    raw_arguments = sys.argv[1:]
    if raw_arguments and raw_arguments[0] in COMMAND_ALIASES:
        raw_arguments = [*COMMAND_ALIASES[raw_arguments[0]], *raw_arguments[1:]]
    args = parser.parse_args(raw_arguments)
    if args.command == "xverif":
        if not args.adapter_args:
            parser.error("xverif requires adapter arguments; use 'xverif probe', 'xverif run', or 'xverif mcp ...'")
        if args.adapter_args[0] == "mcp":
            adapter = (
                Path(__file__).resolve().parents[1]
                / "skills/verif-harness/xverif/scripts/xverif_mcp.py"
            )
            return subprocess.run(
                [sys.executable, str(adapter), *args.adapter_args[1:]], check=False
            ).returncode
        adapter = (
            Path(__file__).resolve().parents[1]
            / "skills/verif-harness/xverif/scripts/xverif_adapter.py"
        )
        return subprocess.run(
            [sys.executable, str(adapter), *args.adapter_args], check=False
        ).returncode
    if args.command == "wavepeek":
        if not args.adapter_args:
            parser.error("wavepeek requires adapter arguments; use 'wavepeek probe' or 'wavepeek run'")
        adapter = (
            Path(__file__).resolve().parents[1]
            / "skills/verif-harness/wavepeek/scripts/wavepeek_adapter.py"
        )
        return subprocess.run([sys.executable, str(adapter), *args.adapter_args], check=False).returncode
    if args.command == "runtime":
        project_root = args.project_root.resolve()
        if not project_root.is_dir():
            parser.error(f"project root is not a directory: {project_root}")
        try:
            if args.runtime_command == "status":
                print(json.dumps(runtime_payload(project_root), indent=2, sort_keys=True))
                return 0
            if not (project_root / ".specify").is_dir():
                parser.error("Spec Kit project missing; run 'spec-kit bootstrap' first")
            current = read_runtime_state(project_root)
            if current is None:
                parser.error(f"Spec Kit runtime state missing: {INTEGRATION_STATE}")
            if current["runtime"] != args.to:
                switched = run_spec_kit(
                    ["integration", "switch", args.to, "--script", "py"],
                    project_root,
                )
                if switched != 0:
                    return switched
            observed = runtime_payload(project_root)
            if observed["runtime"] != args.to:
                parser.error(
                    f"runtime switch did not activate {args.to}: {observed['runtime']}"
                )
            print(json.dumps(observed, indent=2, sort_keys=True))
            return 0
        except RuntimeSelectionError as exc:
            parser.error(str(exc))
    if args.command == "spec-kit":
        if args.spec_command == "probe":
            _, payload = managed_spec_kit()
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        project_root = args.project_root.resolve()
        if not project_root.is_dir():
            parser.error(f"Spec Kit project root is not a directory: {project_root}")
        if args.spec_command == "bootstrap":
            if (project_root / ".specify").exists():
                parser.error(
                    "refusing to overwrite an existing .specify project; review and add "
                    "the verif-harness preset separately"
                )
            try:
                runtime = str(resolve_runtime(project_root, args.integration)["runtime"])
            except RuntimeSelectionError as exc:
                parser.error(str(exc))
            init_arguments = [
                "init", "--here", "--integration", runtime,
                "--integration-options=--skills", "--script", "py",
            ]
            if args.ignore_agent_tools:
                init_arguments.append("--ignore-agent-tools")
            initialized = run_spec_kit(init_arguments, project_root)
            if initialized != 0:
                return initialized
            installed = run_spec_kit(
                [
                    "preset", "add", "--dev",
                    str(ROOT / "integrations/spec-kit/preset/rtl-verification"),
                    "--priority", "5",
                ],
                project_root,
            )
            if installed != 0:
                return installed
            synchronized = run_spec_kit(
                ["preset", "add", "constitution-sync", "--priority", "6"],
                project_root,
            )
            if synchronized != 0:
                return synchronized
            documented = refresh_spec_kit_chinese_docs(project_root)
            if documented != 0:
                return documented
            try:
                observed = runtime_payload(project_root)
            except RuntimeSelectionError as exc:
                parser.error(str(exc))
            if observed["runtime"] != runtime:
                parser.error(
                    f"Spec Kit recorded {observed['runtime']} after {runtime} bootstrap"
                )
            print(json.dumps(observed, indent=2, sort_keys=True))
            return 0
        if not (project_root / ".specify").is_dir():
            parser.error("Spec Kit project missing; run 'spec-kit bootstrap' first")
        if args.spec_command == "docs-zh":
            return refresh_spec_kit_chinese_docs(project_root)
        if args.spec_command == "block":
            try:
                blocked = task_runner.block_task(
                    workflow_run_dir(project_root, args.run_id),
                    args.run_id,
                    args.task_id,
                    args.kind,
                    args.question,
                )
            except task_runner.TaskRunnerError as exc:
                parser.error(str(exc))
            print(json.dumps(blocked, indent=2, sort_keys=True, ensure_ascii=False))
            return 0
        if args.spec_command == "recover":
            try:
                recovered = recover_stale_workflow(
                    project_root, args.run_id, confirmed=args.confirm_stale
                )
            except RuntimeSelectionError as exc:
                parser.error(str(exc))
            print(json.dumps(recovered, indent=2, sort_keys=True))
            print(
                f"NEXT: resume {args.run_id}",
                file=sys.stderr,
            )
            return 0
        try:
            runtime = str(resolve_runtime(project_root)["runtime"])
        except RuntimeSelectionError as exc:
            parser.error(str(exc))
        if args.spec_command == "resume":
            try:
                run_status = spec_kit_run_status(args.run_id, project_root)
                task_state = task_runner.read_state(
                    workflow_run_dir(project_root, args.run_id)
                )
                if run_status.get("status") == "running":
                    parser.error(
                        f"run {args.run_id!r} is still marked running; inspect its worker "
                        "and log first, then use recover --confirm-stale only if "
                        "the process is no longer alive"
                    )
                if task_state is not None and task_state.get("status") == "BLOCKED":
                    if args.verdict is not None:
                        parser.error(
                            "the current task is BLOCKED; use --answer, not --verdict"
                        )
                    if (
                        task_runner.blocked_task_requires_answer(task_state)
                        and not (args.answer or "").strip()
                    ):
                        parser.error(
                            "the current Human/authority/specification blocker requires --answer"
                        )
                    if should_detach(args):
                        wrapper_arguments = [
                            "spec-kit", "resume", args.run_id,
                            "--project-root", str(project_root), "--foreground",
                        ]
                        if args.answer is not None:
                            wrapper_arguments.extend(["--answer", args.answer])
                        return launch_detached_workflow(
                            project_root, args.run_id, "task-resume", wrapper_arguments
                        )
                    advanced = run_task_execution(
                        project_root, args.run_id, runtime, answer=args.answer
                    )
                    print(json.dumps(advanced, indent=2, sort_keys=True, ensure_ascii=False))
                    return 0
                if task_state is not None and task_state.get("status") == "READY":
                    if args.verdict is not None or args.answer is not None:
                        parser.error(
                            "task execution is READY; resume it without --verdict/--answer"
                        )
                    if should_detach(args):
                        return launch_detached_workflow(
                            project_root,
                            args.run_id,
                            "task-resume",
                            [
                                "spec-kit", "resume", args.run_id,
                                "--project-root", str(project_root), "--foreground",
                            ],
                        )
                    advanced = run_task_execution(project_root, args.run_id, runtime)
                    print(
                        json.dumps(
                            advanced, indent=2, sort_keys=True, ensure_ascii=False
                        )
                    )
                    return 0
                if args.answer is not None:
                    parser.error("--answer is valid only when the current task is BLOCKED")
                gate = run_status.get("gate")
                if isinstance(gate, dict) and args.verdict is None:
                    parser.error(
                        f"run {args.run_id!r} is paused at gate "
                        f"{gate.get('step_id')!r}; review its artifact, then pass "
                        "--verdict approve or --verdict reject"
                    )
                gate_step = gate.get("step_id") if isinstance(gate, dict) else None
                if (
                    gate_step in {"review-tasks", "authorize-execution"}
                    and args.verdict == "approve"
                ):
                    try:
                        if gate_step == "review-tasks":
                            task_runner.record_reviewed_contract(
                                project_root,
                                workflow_run_dir(project_root, args.run_id),
                                args.run_id,
                            )
                        else:
                            task_runner.require_reviewed_contract(
                                project_root,
                                workflow_run_dir(project_root, args.run_id),
                                args.run_id,
                            )
                    except task_runner.TaskRunnerError as exc:
                        parser.error(str(exc))
                resume_arguments = ["workflow", "resume", args.run_id]
                if args.verdict is not None:
                    resume_arguments.extend(
                        [
                            "--input",
                            resume_verdict_input(
                                run_status,
                                args.verdict,
                                spec_kit_run_inputs(args.run_id, project_root),
                            ),
                        ]
                    )
                if should_detach(args):
                    wrapper_arguments = [
                        "spec-kit", "resume", args.run_id,
                        "--project-root", str(project_root), "--foreground",
                    ]
                    if args.verdict is not None:
                        wrapper_arguments.extend(["--verdict", args.verdict])
                    return launch_detached_workflow(
                        project_root,
                        args.run_id,
                        "resume",
                        wrapper_arguments,
                    )
            except RuntimeSelectionError as exc:
                parser.error(str(exc))
            resumed = run_spec_kit(
                resume_arguments, project_root, noninteractive=True
            )
            if resumed == 0:
                if gate_step == "authorize-execution" and args.verdict == "approve":
                    try:
                        advanced = run_task_execution(
                            project_root, args.run_id, runtime
                        )
                    except task_runner.TaskRunnerError as exc:
                        parser.error(str(exc))
                    print(
                        json.dumps(
                            advanced, indent=2, sort_keys=True, ensure_ascii=False
                        )
                    )
                return refresh_spec_kit_chinese_docs(project_root)
            return resumed
        if args.spec_command == "status":
            if args.run_id:
                try:
                    state_path = workflow_run_dir(project_root, args.run_id) / "state.json"
                    metadata = worker_metadata(project_root, args.run_id)
                    if metadata is not None and not state_path.exists():
                        active = active_workflow_processes(project_root, args.run_id)
                        print(
                            json.dumps(
                                {
                                    "run_id": args.run_id,
                                    "status": "starting" if active else "worker-exited",
                                    "worker_active": bool(active),
                                    "worker_pid": metadata.get("pid"),
                                    "log": metadata.get("log"),
                                },
                                indent=2,
                                sort_keys=True,
                            )
                        )
                        return 0 if active else 1
                except RuntimeSelectionError as exc:
                    parser.error(str(exc))
            if args.run_id:
                try:
                    workflow_state = spec_kit_run_status(args.run_id, project_root)
                    task_state = task_runner.read_state(
                        workflow_run_dir(project_root, args.run_id)
                    )
                    if task_state is not None:
                        workflow_state["task_execution"] = task_state
                        if task_state.get("status") == "BLOCKED":
                            workflow_state["effective_status"] = "task-blocked"
                        elif task_state.get("status") == "RUNNING":
                            workflow_state["effective_status"] = "task-running"
                        elif task_state.get("status") == "DONE":
                            workflow_state["effective_status"] = "implementation-review"
                    print(
                        json.dumps(
                            workflow_state, indent=2, sort_keys=True, ensure_ascii=False
                        )
                    )
                    status_result = 0
                except (RuntimeSelectionError, task_runner.TaskRunnerError) as exc:
                    parser.error(str(exc))
            else:
                status_result = run_spec_kit(["workflow", "status"], project_root)
            if status_result == 0 and args.run_id:
                try:
                    metadata = worker_metadata(project_root, args.run_id)
                    active = active_workflow_processes(project_root, args.run_id)
                    state_path = workflow_run_dir(project_root, args.run_id) / "state.json"
                    if metadata is not None:
                        print(
                            f"verif-harness worker: pid={metadata.get('pid')} "
                            f"active={bool(active)} log={metadata.get('log')}",
                            file=sys.stderr,
                        )
                    if state_path.is_file():
                        state = json.loads(state_path.read_text(encoding="utf-8"))
                        if isinstance(state, dict) and state.get("status") == "running" and not active:
                            print(
                                "WARNING: run is marked running but no workflow worker was found; "
                                "inspect the log, then use recover "
                                f"{args.run_id} --confirm-stale if the worker was interrupted.",
                                file=sys.stderr,
                            )
                    observed_tasks = task_runner.read_state(
                        workflow_run_dir(project_root, args.run_id)
                    )
                    if (
                        observed_tasks is not None
                        and observed_tasks.get("status") == "RUNNING"
                        and not active
                    ):
                        print(
                            "WARNING: current task is RUNNING but no worker was found; "
                            f"inspect its log, then use recover {args.run_id} "
                            "--confirm-stale if it was interrupted.",
                            file=sys.stderr,
                        )
                except (
                    RuntimeSelectionError,
                    task_runner.TaskRunnerError,
                    OSError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                ) as exc:
                    print(f"WARNING: cannot inspect worker metadata: {exc}", file=sys.stderr)
            return status_result
        python, _ = managed_spec_kit()
        preset = subprocess.run(
            [
                python, "-c",
                (
                    "from pathlib import Path;"
                    "from specify_cli.presets import PresetManager;"
                    "raise SystemExit("
                    "PresetManager(Path.cwd()).get_pack('verif-harness-rtl') is None)"
                ),
            ],
            cwd=project_root, check=False,
        )
        if preset.returncode != 0:
            parser.error(
                "verif-harness-rtl preset is not installed; run 'spec-kit bootstrap' "
                "for a new project or add the reviewed local preset explicitly"
            )
        if should_detach(args):
            try:
                run_id, _ = reserve_workflow_run(project_root)
                return launch_detached_workflow(
                    project_root,
                    run_id,
                    "stage",
                    [
                        "spec-kit", "stage",
                        "--project-root", str(project_root),
                        "--stage", args.stage,
                        "--objective", args.objective,
                        "--foreground",
                    ],
                )
            except RuntimeSelectionError as exc:
                parser.error(str(exc))
        staged = run_spec_kit(
            [
                "workflow", "run",
                str(ROOT / "integrations/spec-kit/workflows/verif-stage-lifecycle.yml"),
                "--input", f"stage={args.stage}",
                "--input", f"objective={args.objective}",
                "--input", f"integration={runtime}",
            ],
            project_root,
            noninteractive=True,
        )
        if staged == 0:
            return refresh_spec_kit_chinese_docs(project_root)
        return staged
    targets = generate(args.dut, args.output.resolve(), args.templates.resolve(), args.dry_run)
    print(json.dumps({"dry_run": args.dry_run, "files": [str(path) for path in targets]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
