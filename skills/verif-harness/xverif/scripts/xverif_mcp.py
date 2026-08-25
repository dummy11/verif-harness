#!/usr/bin/env python3
"""Install and configure the managed xverif MCP source without secrets."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


TOOLS = ["xbit", "xentry", "xloc", "xsva", "xcov", "xdebug", "xwaveform"]
PROFILE_RELATIVE = Path(".harness/mcp/xverif.json")
PROFILE_KEYS = {
    "schema_version", "server_id", "runtime", "transport", "backend", "source",
    "source_commit", "required_tools", "environment_keys", "registration",
}
PACKAGE_ROOT = Path(__file__).resolve().parents[4]


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def dependency_root(project_root: Path) -> Path:
    """Locate the package checkout while preserving the in-tree legacy layout."""
    if (project_root / "scripts/setup_xverif.py").is_file() and (
        project_root / "deps/xverif.lock.json"
    ).is_file():
        return project_root
    return PACKAGE_ROOT


def managed_state(project_root: Path) -> dict[str, Any]:
    package_root = dependency_root(project_root)
    result = subprocess.run(
        [
            sys.executable,
            str(package_root / "scripts/setup_xverif.py"),
            "--project-root",
            str(package_root),
            "--check",
            "--json",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"state": "BLOCKED", "blockers": [result.stderr.strip() or result.stdout.strip()]}
    payload["returncode"] = result.returncode
    return payload


def profile_path(project_root: Path, raw: Path | None) -> Path:
    path = raw or (project_root / PROFILE_RELATIVE)
    path = path if path.is_absolute() else project_root / path
    path = path.resolve()
    if project_root != path and project_root not in path.parents:
        fail("MCP profile must remain under project root")
    return path


def validate_profile(value: Any, lock_commit: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != PROFILE_KEYS:
        fail(f"MCP profile keys must be exactly {sorted(PROFILE_KEYS)}")
    if value["schema_version"] != 1:
        fail("MCP profile schema_version must be 1")
    if value["server_id"] != "xverif":
        fail("MCP profile server_id must be xverif")
    if value["runtime"] not in {"codex", "kimi"}:
        fail("MCP profile runtime must be codex or kimi")
    if value["transport"] != "stdio":
        fail("xverif MCP currently supports only stdio transport")
    if value["backend"] not in {"direct", "lsf"}:
        fail("MCP backend must be direct or lsf")
    if value["source"] != "managed-xverif-checkout":
        fail("MCP source must be managed-xverif-checkout")
    if not isinstance(value["source_commit"], str) or len(value["source_commit"]) != 40:
        fail("MCP source_commit must be a full Git object ID")
    if lock_commit is not None and value["source_commit"] != lock_commit:
        fail("MCP source_commit does not match deps/xverif.lock.json")
    if value["required_tools"] != TOOLS:
        fail(f"MCP required_tools must match {TOOLS}")
    keys = value["environment_keys"]
    if not isinstance(keys, list) or not all(isinstance(key, str) and key for key in keys):
        fail("environment_keys must contain names only")
    if len(keys) != len(set(keys)):
        fail("environment_keys contains duplicates")
    if value["registration"] != "host-managed":
        fail("MCP registration must be host-managed")
    return value


def lock_commit(project_root: Path) -> str:
    package_root = dependency_root(project_root)
    try:
        lock = json.loads((package_root / "deps/xverif.lock.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read xverif lock: {exc}")
    commit = lock.get("commit")
    if not isinstance(commit, str):
        fail("xverif lock does not contain a commit")
    return commit


def configure(args: argparse.Namespace) -> int:
    project_root = args.project_root.resolve()
    target = profile_path(project_root, args.profile)
    if target.exists():
        fail(f"refusing to overwrite MCP profile: {target}")
    managed = managed_state(project_root)
    if managed.get("state") not in {"READY", "INSTALLED"}:
        fail("managed xverif source is not ready; run 'xverif mcp install' first")
    commit = lock_commit(project_root)
    profile = {
        "schema_version": 1,
        "server_id": "xverif",
        "runtime": args.runtime,
        "transport": "stdio",
        "backend": args.backend,
        "source": "managed-xverif-checkout",
        "source_commit": commit,
        "required_tools": TOOLS,
        "environment_keys": [
            "XVERIF_HOME", "XVERIF_MCP_BACKEND", "VERDI_HOME",
            "LD_LIBRARY_PATH", "PATH", "XVERIF_MCP_STARTUP_TIMEOUT_SEC",
            "XVERIF_MCP_REQUEST_TIMEOUT_SEC", "XDEBUG_SESSION_START_TIMEOUT_SEC",
            "XDEBUG_SESSION_IDLE_TIMEOUT_SEC",
        ],
        "registration": "host-managed",
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": "CONFIGURED", "profile": str(target), "profile_data": profile}, indent=2, sort_keys=True))
    return 0


def status(args: argparse.Namespace) -> int:
    project_root = args.project_root.resolve()
    target = profile_path(project_root, args.profile)
    managed = managed_state(project_root)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "state": "UNCONFIGURED",
        "profile": str(target),
        "managed_xverif": managed,
        "runtime_registration": "host-managed",
        "notice": "This command does not read or mutate Codex/Kimi private MCP settings.",
    }
    if not target.is_file():
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1
    try:
        profile = json.loads(target.read_text(encoding="utf-8"))
        profile = validate_profile(profile, lock_commit(project_root))
    except (OSError, json.JSONDecodeError, SystemExit) as exc:
        payload["state"] = "BLOCKED"
        payload["blockers"] = [str(exc)]
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1
    payload["profile_data"] = profile
    if managed.get("state") not in {"READY", "INSTALLED"}:
        payload["state"] = "BLOCKED"
        payload["blockers"] = managed.get("blockers", ["managed xverif is unavailable"])
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1
    python_executable = args.python or Path(sys.executable)
    sdk_check = subprocess.run(
        [str(python_executable), "-c", "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('mcp') else 1)"],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    sdk_available = sdk_check.returncode == 0
    payload["python"] = str(python_executable)
    payload["mcp_sdk_available"] = sdk_available
    payload["state"] = "READY_FOR_RUNTIME_REGISTRATION" if sdk_available else "MCP_SDK_MISSING"
    if not sdk_available:
        payload["blockers"] = [
            "install the separately managed Python dependency mcp[cli] in the runtime environment (setup.sh installs it by default)"
        ]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if sdk_available else 1


def install(args: argparse.Namespace) -> int:
    project_root = args.project_root.resolve()
    package_root = dependency_root(project_root)
    result = subprocess.run(
        [sys.executable, str(package_root / "scripts/setup_xverif.py"), "--project-root", str(package_root), "--json"],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode
    print(json.dumps({
        "state": "INSTALLED_SOURCE",
        "notice": "xverif_mcp source and launcher are installed; setup.sh installs the separately managed mcp[cli] dependency by default.",
    }, indent=2, sort_keys=True))
    return 0


def probe(args: argparse.Namespace) -> int:
    payload = {
        "state": "RUNTIME_PROBE_REQUIRED",
        "server": "xverif",
        "tool": "xverif_ping",
        "profile": str(profile_path(args.project_root.resolve(), args.profile)),
        "notice": "Run xverif_ping through the configured Codex/Kimi MCP runtime; static CLI checks cannot prove MCP protocol availability.",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "status", "configure", "probe"):
        command = commands.add_parser(name)
        command.add_argument("--project-root", type=Path, default=Path.cwd())
        command.add_argument("--profile", type=Path)
    commands.choices["configure"].add_argument("--runtime", choices=("codex", "kimi"), required=True)
    commands.choices["configure"].add_argument("--backend", choices=("direct", "lsf"), default="direct")
    commands.choices["status"].add_argument("--python", type=Path)
    args = parser.parse_args()
    if args.command == "install":
        return install(args)
    if args.command == "configure":
        return configure(args)
    if args.command == "status":
        return status(args)
    return probe(args)


if __name__ == "__main__":
    raise SystemExit(main())
