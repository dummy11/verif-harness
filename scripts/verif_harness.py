#!/usr/bin/env python3
"""Run verif-harness generators and managed integrations."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")
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


def run_spec_kit(arguments: list[str], project_root: Path) -> int:
    python, _ = managed_spec_kit()
    command = [python, "-c", "from specify_cli import main; main()", *arguments]
    return subprocess.run(command, cwd=project_root, check=False).returncode


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
    resume = spec_subparsers.add_parser(
        "resume", help="resume a paused Stage workflow at its next review gate"
    )
    resume.add_argument("run_id")
    resume.add_argument("--project-root", type=Path, default=Path.cwd())
    status = spec_subparsers.add_parser(
        "status", help="show one or all Spec Kit workflow run states"
    )
    status.add_argument("run_id", nargs="?")
    status.add_argument("--project-root", type=Path, default=Path.cwd())
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
        try:
            runtime = str(resolve_runtime(project_root)["runtime"])
        except RuntimeSelectionError as exc:
            parser.error(str(exc))
        if args.spec_command == "resume":
            resumed = run_spec_kit(["workflow", "resume", args.run_id], project_root)
            if resumed == 0:
                return refresh_spec_kit_chinese_docs(project_root)
            return resumed
        if args.spec_command == "status":
            arguments = ["workflow", "status"]
            if args.run_id:
                arguments.append(args.run_id)
            return run_spec_kit(arguments, project_root)
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
        staged = run_spec_kit(
            [
                "workflow", "run",
                str(ROOT / "integrations/spec-kit/workflows/verif-stage-lifecycle.yml"),
                "--input", f"stage={args.stage}",
                "--input", f"objective={args.objective}",
                "--input", f"integration={runtime}",
            ],
            project_root,
        )
        if staged == 0:
            return refresh_spec_kit_chinese_docs(project_root)
        return staged
    targets = generate(args.dut, args.output.resolve(), args.templates.resolve(), args.dry_run)
    print(json.dumps({"dry_run": args.dry_run, "files": [str(path) for path in targets]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
