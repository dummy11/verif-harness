#!/usr/bin/env python3
"""Read-only structural audit for a harness-style RTL verification project."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Finding:
    severity: str
    code: str
    message: str


class Audit:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.findings: list[Finding] = []
        self.config: dict = {}
        self.next_mode = "init"

    def add(self, severity: str, code: str, message: str) -> None:
        self.findings.append(Finding(severity, code, message))

    def path(self, value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else self.root / candidate

    def load_config(self) -> bool:
        config_path = self.root / ".harness-config.json"
        if not config_path.is_file():
            self.add("INFO", "CONFIG_ABSENT", "No .harness-config.json; init is the next mode.")
            return False
        try:
            self.config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.add("ERROR", "CONFIG_INVALID", f"Cannot parse .harness-config.json: {exc}")
            return False
        for key in ("project_name", "rtl", "verif"):
            if key not in self.config:
                self.add("ERROR", "CONFIG_KEY", f"Missing required config key: {key}")
        return not any(f.severity == "ERROR" for f in self.findings)

    def check_instruction_migration(self) -> None:
        agents = self.root / "AGENTS.md"
        claude = self.root / "CLAUDE.md"
        if not agents.is_file():
            self.add("ERROR", "AGENTS_MISSING", "AGENTS.md is missing.")
        if claude.is_file() and agents.is_file():
            self.add("WARNING", "LEGACY_CLAUDE_MD", "CLAUDE.md remains beside AGENTS.md; verify AGENTS.md is authoritative.")
        if (self.root / ".claude").exists():
            self.add(
                "WARNING", "LEGACY_CLAUDE_DIR",
                ".claude/ remains; review Agent runtime migration status.",
            )

    def check_agent_runtime(self) -> None:
        specify = self.root / ".specify"
        state_path = specify / "integration.json"
        if not specify.exists():
            self.add(
                "INFO", "RUNTIME_UNMANAGED",
                "No Spec Kit project; Agent runtime state is not managed.",
            )
            return
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.add(
                "ERROR", "RUNTIME_STATE_MISSING",
                ".specify/integration.json is missing.",
            )
            return
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.add("ERROR", "RUNTIME_STATE_INVALID", f"Cannot read runtime state: {exc}")
            return
        if not isinstance(state, dict):
            self.add("ERROR", "RUNTIME_STATE_INVALID", "Runtime state must be a JSON object.")
            return
        runtime = state.get("default_integration") or state.get("integration")
        if runtime not in ("codex", "kimi"):
            self.add(
                "ERROR", "RUNTIME_UNSUPPORTED",
                f"Active Spec Kit integration is unsupported: {runtime!r}.",
            )
            return
        self.add("INFO", "RUNTIME_ACTIVE", f"Active Agent runtime: {runtime}.")

    def check_paths(self) -> tuple[Path | None, Path | None]:
        rtl_cfg = self.config.get("rtl", {})
        verif_cfg = self.config.get("verif", {})
        rtl_root = self.path(rtl_cfg.get("root", "")) if rtl_cfg.get("root") else None
        verif_root = self.path(verif_cfg.get("root", "")) if verif_cfg.get("root") else None
        top_file = self.path(rtl_cfg.get("top_file", "")) if rtl_cfg.get("top_file") else None
        for code, label, candidate in (
            ("RTL_ROOT", "RTL root", rtl_root),
            ("VERIF_ROOT", "verification root", verif_root),
            ("TOP_FILE", "DUT top file", top_file),
        ):
            if candidate is None or not candidate.exists():
                self.add("ERROR", f"{code}_MISSING", f"{label} does not exist: {candidate}")
        return rtl_root, verif_root

    def required_docs(self) -> list[Path]:
        verif = self.config.get("verif", {})
        docs_value = verif.get("docs_root")
        if not docs_value:
            self.add("ERROR", "DOCS_CONFIG", "verif.docs_root is missing.")
            return []
        docs = self.path(docs_value)
        vsub = verif.get("verification_subdir", "verification")
        gsub = verif.get("governance_subdir", "governance")
        paths = [
            docs / gsub / "verification_workflow.md",
            docs / "plan.md",
            docs / "roadmap.md",
            docs / "harness_style_methodology.md",
            docs / vsub / "verification_plan.md",
            docs / vsub / "feature_matrix.md",
            docs / vsub / "tb_architecture.md",
            docs / vsub / "assertion_plan.md",
            docs / vsub / "coverage_plan.md",
            docs / vsub / "testcase_list.md",
        ]
        if self.config.get("reference_model", {}).get("enabled"):
            paths.append(docs / vsub / "reference_model_spec.md")
        return paths

    def check_docs(self) -> None:
        statuses: dict[str, int] = {}
        for path in self.required_docs():
            if not path.is_file():
                self.add("ERROR", "DOC_MISSING", f"Required document is missing: {path.relative_to(self.root)}")
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            match = re.search(r"### Review Metadata.*?^- Status:\s*(.+?)\s*$", text, re.MULTILINE | re.DOTALL)
            status = match.group(1).strip() if match else "UNKNOWN"
            statuses[status] = statuses.get(status, 0) + 1
            for heading in ("## Lifecycle", "## Review Trace", "## Revision Log", "### Approval Decision"):
                if heading not in text:
                    self.add("ERROR", "REVIEW_BLOCK", f"{path.relative_to(self.root)} lacks {heading}")
        if statuses:
            summary = ", ".join(f"{key}={value}" for key, value in sorted(statuses.items()))
            self.add("INFO", "DOC_STATUS", f"Document review metadata: {summary}")

    def check_workflow_tool(self) -> None:
        checker = self.root / ".harness" / "check_ai_workflow.py"
        if not checker.is_file():
            self.add("ERROR", "WORKFLOW_CHECKER", ".harness/check_ai_workflow.py is missing.")
            return
        text = checker.read_text(encoding="utf-8", errors="replace")
        if "CLAUDE.md" in text and "AGENTS.md" not in text:
            self.add("WARNING", "CHECKER_LEGACY", "Workflow checker still targets CLAUDE.md instead of AGENTS.md.")

    def git_paths(self, args: list[str]) -> list[str]:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return [line for line in result.stdout.splitlines() if line.strip()] if result.returncode == 0 else []

    def check_rtl_clean(self, rtl_root: Path | None) -> None:
        if rtl_root is None:
            return
        try:
            rel = rtl_root.relative_to(self.root)
        except ValueError:
            self.add("WARNING", "RTL_EXTERNAL", f"RTL root is outside project root: {rtl_root}")
            return
        changed = set(self.git_paths(["diff", "--name-only", "--", str(rel)]))
        changed.update(self.git_paths(["diff", "--cached", "--name-only", "--", str(rel)]))
        changed.update(self.git_paths(["ls-files", "--others", "--exclude-standard", "--", str(rel)]))
        if changed:
            self.add("ERROR", "RTL_DIRTY", "RTL root has local changes: " + ", ".join(sorted(changed)))
        else:
            self.add("INFO", "RTL_CLEAN", "No tracked, staged, or untracked RTL changes detected.")

    def infer_next_mode(self, verif_root: Path | None) -> None:
        if verif_root is None or not verif_root.exists():
            self.next_mode = "doctor after fixing configuration"
            return
        tb = verif_root / "testbench"
        interfaces = list((tb / "top" / "if").glob("*_if.sv")) if (tb / "top" / "if").exists() else []
        packages = list((tb / "pkg").glob("*_pkg.sv")) if (tb / "pkg").exists() else []
        uvc_pkgs = list((tb / "uvc").glob("*/*_agent_pkg.sv")) if (tb / "uvc").exists() else []
        harness = list((tb / "top" / "harness" / "dut_harness").glob("*.sv")) if (tb / "top" / "harness" / "dut_harness").exists() else []
        env_pkgs = list((tb / "env").glob("*_env_pkg.sv")) if (tb / "env").exists() else []
        tb_filelist = verif_root / "filelist" / "tb.f"
        regress_make = verif_root / "regress" / "Makefile"
        if not interfaces:
            self.next_mode = "add-interface"
        elif not packages:
            self.next_mode = "add-shared-pkg"
        elif not uvc_pkgs:
            self.next_mode = "add-uvc-skeleton"
        elif not harness:
            self.next_mode = "add-harness-layer"
        elif not env_pkgs:
            self.next_mode = "add-env-layer"
        elif not tb_filelist.is_file():
            self.next_mode = "finalize-filelist-and-make"
        elif not regress_make.is_file():
            self.next_mode = "add-regression-runner"
        else:
            self.next_mode = "audit-traceability or stage-gate-review (human selects stage)"
        self.add(
            "INFO",
            "SCAFFOLD_COUNTS",
            f"interfaces={len(interfaces)}, shared_packages={len(packages)}, "
            f"uvc_packages={len(uvc_pkgs)}, harness_sv={len(harness)}, env_packages={len(env_pkgs)}",
        )

    def run(self) -> None:
        if not self.load_config():
            return
        self.check_instruction_migration()
        self.check_agent_runtime()
        rtl_root, verif_root = self.check_paths()
        self.check_docs()
        self.check_workflow_tool()
        self.check_rtl_clean(rtl_root)
        self.infer_next_mode(verif_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    audit = Audit(args.project_root)
    audit.run()
    counts = {severity: sum(f.severity == severity for f in audit.findings) for severity in ("ERROR", "WARNING", "INFO")}
    if args.json:
        print(json.dumps({
            "project_root": str(audit.root),
            "counts": counts,
            "next_mode": audit.next_mode,
            "findings": [asdict(f) for f in audit.findings],
        }, indent=2))
    else:
        for finding in audit.findings:
            print(f"{finding.severity:<7} {finding.code:<20} {finding.message}")
        print(f"SUMMARY errors={counts['ERROR']} warnings={counts['WARNING']} info={counts['INFO']}")
        print(f"NEXT    {audit.next_mode}")
    return 1 if counts["ERROR"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
