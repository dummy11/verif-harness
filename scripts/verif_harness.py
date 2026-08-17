#!/usr/bin/env python3
"""Generate an additive DUT integration skeleton from public templates."""

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
        "bootstrap", help="initialize a new Codex Spec Kit project and install the RTL preset"
    )
    bootstrap.add_argument("--project-root", type=Path, default=Path.cwd())
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
    args = parser.parse_args()
    if args.command == "xverif":
        if not args.adapter_args:
            parser.error("xverif requires adapter arguments; use 'xverif probe' or 'xverif run'")
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
            initialized = run_spec_kit(
                [
                    "init", "--here", "--integration", "codex",
                    "--integration-options=--skills", "--script", "py",
                ],
                project_root,
            )
            if initialized != 0:
                return initialized
            return run_spec_kit(
                [
                    "preset", "add", "--dev",
                    str(ROOT / "integrations/spec-kit/preset/rtl-verification"),
                    "--priority", "5",
                ],
                project_root,
            )
        if not (project_root / ".specify").is_dir():
            parser.error("Spec Kit project missing; run 'spec-kit bootstrap' first")
        if args.spec_command == "resume":
            return run_spec_kit(["workflow", "resume", args.run_id], project_root)
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
        return run_spec_kit(
            [
                "workflow", "run",
                str(ROOT / "integrations/spec-kit/workflows/verif-stage-lifecycle.yml"),
                "--input", f"stage={args.stage}",
                "--input", f"objective={args.objective}",
                "--input", "integration=codex",
            ],
            project_root,
        )
    targets = generate(args.dut, args.output.resolve(), args.templates.resolve(), args.dry_run)
    print(json.dumps({"dry_run": args.dry_run, "files": [str(path) for path in targets]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
