#!/usr/bin/env python3
"""Validate managed Spec Kit identity and verif-harness authoring assets."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts/setup_spec_kit.py"
WORKFLOW = ROOT / "integrations/spec-kit/workflows/verif-stage-lifecycle.yml"
BUNDLE = ROOT / "integrations/spec-kit/bundle"
PRESET = ROOT / "integrations/spec-kit/preset/rtl-verification"
CLI = ROOT / "scripts/verif_harness.py"


def validate_runtime_bootstrap(runtime: str, root: Path) -> str | None:
    project = root / runtime
    project.mkdir()
    bootstrapped = subprocess.run(
        [
            sys.executable, str(CLI), "spec-kit", "bootstrap",
            "--project-root", str(project), "--integration", runtime,
            "--ignore-agent-tools",
        ],
        cwd=ROOT, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if bootstrapped.returncode != 0:
        return bootstrapped.stdout + bootstrapped.stderr
    state = json.loads((project / ".specify/integration.json").read_text(encoding="utf-8"))
    if state.get("default_integration") != runtime:
        return f"{runtime} bootstrap recorded the wrong default integration"
    skill_root = ".agents/skills" if runtime == "codex" else ".kimi-code/skills"
    implement = project / skill_root / "speckit-implement/SKILL.md"
    if not implement.is_file():
        return f"{runtime} bootstrap did not install the implement Skill"
    content = implement.read_text(encoding="utf-8")
    if "verif-harness execution guard" not in content:
        return f"{runtime} bootstrap did not apply the verif-harness preset"
    return None


def main() -> int:
    checked = subprocess.run(
        [sys.executable, str(SETUP), "--project-root", str(ROOT), "--check", "--json"],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if checked.returncode != 0:
        print(checked.stdout, end="")
        print(checked.stderr, end="", file=sys.stderr)
        return checked.returncode
    dependency = json.loads(checked.stdout)
    if dependency.get("supported_integrations") != ["codex", "kimi"]:
        print("Spec Kit Codex/Kimi integration contract missing", file=sys.stderr)
        return 1
    python = dependency["python"]
    source = Path(dependency["source"])
    validation = subprocess.run(
        [
            python, "-c",
            (
                "from pathlib import Path;"
                "from specify_cli.workflows.engine import WorkflowEngine,validate_workflow;"
                f"d=WorkflowEngine(Path.cwd()).load_workflow({str(WORKFLOW)!r});"
                "e=validate_workflow(d);"
                "print('\\n'.join(e));"
                "raise SystemExit(bool(e))"
            ),
        ],
        cwd=ROOT, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if validation.returncode != 0:
        print(validation.stdout, end="")
        print(validation.stderr, end="", file=sys.stderr)
        return validation.returncode
    preset = subprocess.run(
        [
            python, "-c",
            (
                "from pathlib import Path;"
                "from specify_cli.presets import PresetManifest;"
                f"PresetManifest(Path({str(PRESET / 'preset.yml')!r}));"
                "print('preset valid')"
            ),
        ],
        cwd=ROOT, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if preset.returncode != 0:
        print(preset.stdout, end="")
        print(preset.stderr, end="", file=sys.stderr)
        return preset.returncode
    bundle = subprocess.run(
        [
            python, "-c", "from specify_cli import main; main()",
            "bundle", "validate", "--path", str(BUNDLE), "--offline",
        ],
        cwd=ROOT, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if bundle.returncode != 0:
        print(bundle.stdout, end="")
        print(bundle.stderr, end="", file=sys.stderr)
        return bundle.returncode
    with tempfile.TemporaryDirectory(prefix="verif-harness-spec-kit-") as temporary:
        smoke_root = Path(temporary)
        for runtime in ("codex", "kimi"):
            failure = validate_runtime_bootstrap(runtime, smoke_root)
            if failure:
                print(failure, end="", file=sys.stderr)
                return 1
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout.strip()
    print(
        "Managed Spec Kit PASS: "
        f"{head}; Codex/Kimi, preset, workflow, and bundle structure validated"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
