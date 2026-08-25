#!/usr/bin/env python3
"""Report required and observed managed-runtime and host-tool versions."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


VERSION = re.compile(r"(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)")
LOCKED_REQUIREMENT = re.compile(
    r"^([A-Za-z0-9_.-]+)==([^\s;]+)(?:\s*;\s*(.+?))?\s*\\?$"
)
MARKER_CLAUSE = re.compile(
    r"^(implementation_name|platform_python_implementation|sys_platform)\s*"
    r"(==|!=)\s*'([^']+)'$"
)
READY_STATES = {"READY", "INSTALLED"}


@dataclass(frozen=True)
class VersionRow:
    category: str
    component: str
    required: str
    current: str
    status: str
    source: str | None = None


def parsed_version(value: str) -> tuple[int, ...] | None:
    match = VERSION.search(value)
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def at_least(observed: str, minimum: str) -> bool:
    current = parsed_version(observed)
    required = parsed_version(minimum)
    if current is None or required is None:
        return False
    width = max(len(current), len(required))
    return current + (0,) * (width - len(current)) >= required + (0,) * (width - len(required))


def first_line(value: str) -> str:
    return next((line.strip() for line in value.splitlines() if line.strip()), "")


def run(arguments: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            arguments, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def command_probe(
    component: str,
    category: str,
    required: str,
    candidates: list[tuple[str, list[str]]],
    minimum: str | None = None,
    required_major: int | None = None,
) -> VersionRow:
    for command, arguments in candidates:
        executable = shutil.which(command)
        if executable is None:
            continue
        checked = run([executable, *arguments])
        if checked is None:
            return VersionRow(category, component, required, "probe timed out", "FAIL", executable)
        observed = first_line(checked.stdout + checked.stderr)
        if checked.returncode != 0:
            return VersionRow(category, component, required, observed or "probe failed", "WARN", executable)
        compatible = True
        if minimum is not None:
            compatible = at_least(observed, minimum)
        if required_major is not None:
            version = parsed_version(observed)
            compatible = version is not None and version[0] == required_major
        status = "PASS" if compatible else ("FAIL" if category == "required" else "WARN")
        return VersionRow(category, component, required, observed or "available", status, executable)
    status = "FAIL" if category == "required" else "NOT_INSTALLED"
    return VersionRow(category, component, required, "not installed", status)


def presence_probe(component: str, commands: list[str]) -> VersionRow:
    resolved = {command: shutil.which(command) for command in commands}
    missing = [command for command, path in resolved.items() if path is None]
    current = "all available" if not missing else "missing: " + ", ".join(missing)
    sources = ", ".join(path for path in resolved.values() if path is not None)
    return VersionRow(
        "required", component, "presence only: " + ", ".join(commands), current,
        "PASS" if not missing else "FAIL", sources or None,
    )


def marker_applies(marker: str | None) -> bool:
    if marker is None:
        return True
    environment = {
        "implementation_name": sys.implementation.name,
        "platform_python_implementation": platform.python_implementation(),
        "sys_platform": sys.platform,
    }
    for raw_clause in marker.split(" and "):
        match = MARKER_CLAUSE.fullmatch(raw_clause.strip())
        if match is None:
            return True
        key, operator, expected = match.groups()
        equal = environment[key] == expected
        if not (equal if operator == "==" else not equal):
            return False
    return True


def package_lock_row(root: Path, runtime_lock: dict[str, Any]) -> VersionRow:
    relative = runtime_lock["python_packages"]["requirements"]
    path = root / relative
    expected: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return VersionRow(
            "required", "Python package lock", relative, "unreadable", "FAIL", str(path),
        )
    for line in lines:
        match = LOCKED_REQUIREMENT.fullmatch(line.strip())
        if match is not None and marker_applies(match.group(3)):
            expected[match.group(1)] = match.group(2)
    mismatches = []
    for name, version in expected.items():
        try:
            observed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            observed = "missing"
        if observed != version:
            mismatches.append(f"{name}={observed} (locked {version})")
    current = (
        f"{len(expected)} exact versions installed"
        if not mismatches else "; ".join(mismatches)
    )
    return VersionRow(
        "required", "Python package lock", f"{len(expected)} applicable exact pins",
        current, "PASS" if not mismatches else "FAIL", str(path),
    )


def json_probe(root: Path, script: str) -> dict[str, Any]:
    checked = run([
        sys.executable, str(root / "scripts" / script), "--project-root", str(root),
        "--check", "--json",
    ], timeout=120)
    if checked is None:
        return {"state": "BLOCKED", "blockers": [f"{script} timed out"]}
    try:
        return json.loads(checked.stdout)
    except json.JSONDecodeError:
        detail = first_line(checked.stderr + checked.stdout) or f"{script} returned invalid JSON"
        return {"state": "BLOCKED", "blockers": [detail]}


def managed_rows(root: Path, runtime_lock: dict[str, Any]) -> tuple[list[VersionRow], dict[str, Any]]:
    rows: list[VersionRow] = []
    python_lock = runtime_lock["python"]
    package_lock = runtime_lock["python_packages"]
    observed_python = ".".join(str(part) for part in sys.version_info[:3])
    expected_python = python_lock["version"]
    descriptor_path = root / ".deps/runtime/managed-runtime.json"
    descriptor: dict[str, Any] = {}
    try:
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    expected_executable = descriptor.get("environment_python")
    executable_match = (
        isinstance(expected_executable, str)
        and Path(expected_executable).resolve() == Path(sys.executable).resolve()
    )
    python_ok = observed_python == expected_python and executable_match
    rows.append(VersionRow(
        "required", "Managed CPython", expected_python, observed_python,
        "PASS" if python_ok else "FAIL", sys.executable,
    ))
    try:
        observed_mcp = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        observed_mcp = "not installed"
    rows.append(VersionRow(
        "required", "MCP Python SDK", package_lock["mcp_version"], observed_mcp,
        "PASS" if observed_mcp == package_lock["mcp_version"] else "FAIL",
        str(Path(sys.executable).parent),
    ))
    rows.append(package_lock_row(root, runtime_lock))

    xverif = json_probe(root, "setup_xverif.py")
    xverif_lock = json.loads((root / "deps/xverif.lock.json").read_text(encoding="utf-8"))
    rows.append(VersionRow(
        "required", "xverif", xverif_lock["commit"],
        str(xverif.get("commit", "unavailable")),
        "PASS" if xverif.get("state") in READY_STATES else "FAIL",
        xverif.get("destination"),
    ))
    mcp_source = root / ".deps/xverif/xverif_mcp/src"
    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(mcp_source))
        sys.path.insert(1, str(root / ".deps/xverif"))
        importlib.import_module("mcp.server.fastmcp")
        importlib.import_module("xverif_mcp.server")
        xverif_mcp_current, xverif_mcp_status = "importable", "PASS"
    except (ImportError, OSError) as exc:
        xverif_mcp_current, xverif_mcp_status = f"unavailable: {exc}", "FAIL"
    finally:
        sys.path[:] = old_path
    rows.append(VersionRow(
        "required", "xverif MCP API", "FastMCP 1.x API", xverif_mcp_current,
        xverif_mcp_status, str(mcp_source),
    ))

    wavepeek = json_probe(root, "setup_wavepeek.py")
    wavepeek_lock = json.loads((root / "deps/wavepeek.lock.json").read_text(encoding="utf-8"))
    observed_wavepeek = str(wavepeek.get("version") or "unavailable")
    rows.append(VersionRow(
        "required", "WavePeek", wavepeek_lock["version"], observed_wavepeek,
        "PASS" if wavepeek.get("state") in READY_STATES else "FAIL",
        wavepeek.get("binary"),
    ))
    if platform.system() == "Linux":
        private_required = bool(wavepeek.get("private_glibc_required"))
        host_glibc = str(wavepeek.get("host_glibc") or "unknown")
        if private_required:
            private_state = str(wavepeek.get("private_glibc_state") or "MISSING")
            current = f"host {host_glibc}; private 2.34 {private_state}"
            glibc_ok = private_state in READY_STATES
            source = wavepeek.get("private_glibc_root")
        else:
            current = f"host {host_glibc}"
            glibc_ok = at_least(host_glibc, "2.34")
            source = "/lib64/libc.so.6"
        rows.append(VersionRow(
            "required", "WavePeek glibc", "host >=2.34 or private 2.34",
            current, "PASS" if glibc_ok else "FAIL", source,
        ))
    else:
        rows.append(VersionRow(
            "informational", "WavePeek glibc", "Linux only", "not applicable", "N/A",
        ))

    spec_kit = json_probe(root, "setup_spec_kit.py")
    spec_lock = json.loads((root / "deps/spec-kit.lock.json").read_text(encoding="utf-8"))
    observed_spec = str(spec_kit.get("version") or "unavailable")
    rows.append(VersionRow(
        "required", "GitHub Spec Kit", spec_lock["version"], observed_spec,
        "PASS" if spec_kit.get("state") in READY_STATES and spec_lock["version"] in observed_spec else "FAIL",
        spec_kit.get("environment"),
    ))
    return rows, wavepeek


def host_rows(runtime_lock: dict[str, Any], wavepeek: dict[str, Any]) -> list[VersionRow]:
    versions = runtime_lock["host_contract"]["version_requirements"]
    rows = [
        presence_probe(
            "POSIX bootstrap tools",
            runtime_lock["host_contract"]["required_commands"],
        ),
        command_probe("Bash", "required", versions["bash"], [("bash", ["--version"])], minimum="3.2"),
        command_probe("Git", "required", versions["git"], [("git", ["--version"])], minimum="2.25"),
        command_probe("tar", "required", "gzip-capable", [("tar", ["--version"])]),
        command_probe(
            "HTTPS downloader", "required", "TLS-capable curl or wget",
            [("curl", ["--version"]), ("wget", ["--version"])],
        ),
        command_probe(
            "SHA-256 tool", "required", "sha256sum or shasum",
            [("sha256sum", ["--version"]), ("shasum", ["--version"])],
        ),
    ]
    if platform.system() == "Linux":
        conditional_category = "required" if wavepeek.get("private_glibc_required") else "conditional"
        rows.extend([
            command_probe("glibc build assembler", conditional_category, versions["private_glibc_binutils"], [("as", ["--version"])], minimum="2.25"),
            command_probe("glibc build GCC", conditional_category, versions["private_glibc_gcc"], [("gcc", ["--version"])], minimum="6.2"),
            command_probe("glibc build Make", conditional_category, versions["private_glibc_make"], [("make", ["--version"])], minimum="4.0"),
            command_probe("glibc build binutils", conditional_category, versions["private_glibc_binutils"], [("ld", ["--version"])], minimum="2.25"),
            command_probe("glibc build gawk", conditional_category, versions["private_glibc_gawk"], [("gawk", ["--version"])], minimum="3.1.2"),
            command_probe("glibc build bison", conditional_category, versions["private_glibc_bison"], [("bison", ["--version"])], minimum="2.7"),
            command_probe("glibc build texinfo", conditional_category, versions["private_glibc_texinfo"], [("makeinfo", ["--version"])], minimum="4.7"),
            command_probe("glibc build GNU sed", conditional_category, versions["private_glibc_sed"], [("sed", ["--version"])], minimum="3.02"),
        ])
        if wavepeek.get("private_glibc_required"):
            python_version = ".".join(str(part) for part in sys.version_info[:3])
            rows.append(VersionRow(
                "required", "glibc build Python", versions["private_glibc_python"],
                python_version,
                "PASS" if at_least(python_version, versions["private_glibc_python"]) else "FAIL",
                sys.executable,
            ))
    rows.append(command_probe(
        "Verilator", "optional", versions["verilator"],
        [("verilator", ["--version"])], required_major=5,
    ))
    rows.append(command_probe("Synopsys VCS", "optional", "user-validated", [("vcs", ["-ID"])]))
    rows.append(command_probe("LSF bsub", "optional", "site-provided", [("bsub", ["-V"])]))
    verdi_home = os.environ.get("VERDI_HOME")
    rows.append(VersionRow(
        "optional", "Verdi/NPI SDK", "site-licensed for xdebug/FSDB",
        verdi_home or "not configured", "AVAILABLE" if verdi_home else "NOT_CONFIGURED",
        verdi_home,
    ))
    rows.append(VersionRow(
        "informational", "UVM", "IEEE 1800.2-compatible",
        "simulator/project provided", "NOT_PROBED",
    ))
    return rows


def agent_rows(runtime: str, require_agent: bool) -> list[VersionRow]:
    codex = command_probe("Codex CLI", "optional", "selected Agent runtime", [("codex", ["--version"])])
    kimi = command_probe(
        "Kimi CLI", "optional", "selected Agent runtime",
        [("kimi", ["--version"]), ("kimi-cli", ["--version"])],
    )
    rows = [codex, kimi]
    if not require_agent:
        return rows
    available = [row for row in rows if row.status == "PASS"]
    if runtime == "auto":
        current = ", ".join(row.component for row in available) or "none"
        status = "PASS" if len(available) == 1 else "FAIL"
        rows.append(VersionRow("required", "Agent selection", "exactly one CLI or explicit --runtime", current, status))
    else:
        selected = codex if runtime == "codex" else kimi
        rows.append(VersionRow(
            "required", "Selected Agent CLI", runtime,
            selected.current, "PASS" if selected.status == "PASS" else "FAIL", selected.source,
        ))
    return rows


def clipped(value: str, width: int) -> str:
    return value if len(value) <= width else value[: width - 3] + "..."


def print_table(rows: list[VersionRow], verbose: bool) -> None:
    columns = (("CLASS", 13), ("COMPONENT", 23), ("REQUIRED", 31), ("CURRENT", 43), ("STATUS", 14))
    print("  ".join(label.ljust(width) for label, width in columns))
    print("  ".join("-" * width for _, width in columns))
    for row in rows:
        values = (row.category, row.component, row.required, row.current, row.status)
        print("  ".join(clipped(value, width).ljust(width) for value, (_, width) in zip(values, columns)))
    if verbose:
        sources = [row for row in rows if row.source]
        if sources:
            print("\nResolved sources:")
            for row in sources:
                print(f"  {row.component}: {row.source}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--runtime", choices=("auto", "codex", "kimi"), default="auto")
    parser.add_argument("--require-agent", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    root = args.project_root.resolve()
    try:
        runtime_lock = json.loads((root / "deps/runtime.lock.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: cannot read runtime lock: {exc}")

    managed, wavepeek = managed_rows(root, runtime_lock)
    rows = managed + host_rows(runtime_lock, wavepeek) + agent_rows(args.runtime, args.require_agent)
    blockers = [row.component for row in rows if row.category == "required" and row.status != "PASS"]
    payload = {
        "schema_version": 1,
        "state": "BLOCKED" if blockers else "READY",
        "backend": "managed",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "rows": [asdict(row) for row in rows],
        "blockers": blockers,
        "notice": (
            "Optional and conditional rows are informational unless their feature is selected; "
            "tool presence does not prove simulator support or verification approval."
        ),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Runtime/version check: {payload['state']} ({payload['platform']}, {payload['machine']})")
        print_table(rows, args.verbose)
        if blockers:
            print("\nRequired blockers: " + ", ".join(blockers), file=sys.stderr)
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
