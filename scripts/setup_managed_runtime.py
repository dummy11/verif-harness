#!/usr/bin/env python3
"""Install or validate the hash-locked managed Python runtime environment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


LOCK_KEYS = {"schema_version", "name", "python", "python_packages", "host_contract"}
PYTHON_KEYS = {"implementation", "version", "distribution", "release", "licenses", "assets"}
PACKAGE_KEYS = {
    "requirements", "requirements_sha256", "mcp_requirement", "mcp_version", "resolver",
}
HOST_KEYS = {
    "required_commands", "download_commands", "sha256_commands",
    "conditional_private_glibc_build_commands", "version_requirements",
}
PLATFORMS = {
    "aarch64-apple-darwin", "x86_64-apple-darwin",
    "aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu",
}


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_lock(root: Path) -> dict[str, Any]:
    try:
        value = json.loads((root / "deps/runtime.lock.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read managed runtime lock: {exc}")
    if not isinstance(value, dict) or set(value) != LOCK_KEYS:
        fail(f"managed runtime lock keys must be exactly {sorted(LOCK_KEYS)}")
    if value["schema_version"] != 1 or value["name"] != "verif-harness-managed-runtime":
        fail("unsupported managed runtime identity or schema")
    python = value["python"]
    packages = value["python_packages"]
    host = value["host_contract"]
    if not isinstance(python, dict) or set(python) != PYTHON_KEYS:
        fail(f"managed Python lock keys must be exactly {sorted(PYTHON_KEYS)}")
    if not isinstance(packages, dict) or set(packages) != PACKAGE_KEYS:
        fail(f"managed package lock keys must be exactly {sorted(PACKAGE_KEYS)}")
    if not isinstance(host, dict) or set(host) != HOST_KEYS:
        fail(f"managed host contract keys must be exactly {sorted(HOST_KEYS)}")
    if (
        python["implementation"] != "cpython"
        or python["version"] != "3.12.11"
        or python["distribution"] != "astral-sh/python-build-standalone"
        or python["release"] != "20251007"
        or python["licenses"] != ["MPL-2.0", "PSF-2.0"]
    ):
        fail("managed Python identity differs from the reviewed runtime")
    if not isinstance(python["assets"], dict) or set(python["assets"]) != PLATFORMS:
        fail("managed Python assets do not cover the reviewed platforms")
    for platform, asset in python["assets"].items():
        expected = f"cpython-3.12.11+20251007-{platform}-install_only_stripped.tar.gz"
        if not isinstance(asset, dict) or set(asset) != {"archive", "sha256"}:
            fail(f"managed Python asset entry is invalid: {platform}")
        if asset["archive"] != expected or not isinstance(asset["sha256"], str) or len(asset["sha256"]) != 64:
            fail(f"managed Python asset identity is invalid: {platform}")
    if (
        packages["requirements"] != "deps/runtime-requirements.lock"
        or packages["mcp_requirement"] != "mcp[cli]==1.29.1"
        or packages["mcp_version"] != "1.29.1"
        or packages["resolver"] != "uv==0.12.5"
    ):
        fail("managed Python package identity differs from review")
    expected_host = {
        "required_commands": [
            "awk", "bash", "cp", "dirname", "git", "ln", "mkdir", "mv",
            "readlink", "rm", "tar", "uname",
        ],
        "download_commands": ["curl", "wget"],
        "sha256_commands": ["sha256sum", "shasum"],
        "conditional_private_glibc_build_commands": [
            "as", "bison", "gcc", "gawk", "ld", "make", "sed",
        ],
        "version_requirements": {
            "bash": ">=3.2",
            "git": ">=2.25",
            "private_glibc_binutils": ">=2.25",
            "private_glibc_bison": ">=2.7",
            "private_glibc_gawk": ">=3.1.2",
            "private_glibc_gcc": ">=6.2",
            "private_glibc_make": ">=4.0",
            "private_glibc_python": ">=3.4",
            "private_glibc_sed": ">=3.02",
            "private_glibc_texinfo": ">=4.7",
            "verilator": "5.x",
        },
    }
    if host != expected_host:
        fail("managed host contract differs from review")
    return value


def environment_python(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(arguments: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        fail(f"managed runtime command failed or timed out: {arguments[0]}: {exc}")


def validate_python(executable: Path, expected: str) -> list[str]:
    if not executable.is_file() or not os.access(executable, os.X_OK):
        return [f"managed Python missing or not executable: {executable}"]
    checked = run([
        str(executable), "-c",
        (
            "import json,ssl,sqlite3,ctypes,lzma,venv,sys;"
            "print(json.dumps({'version':'.'.join(map(str,sys.version_info[:3])),"
            "'implementation':sys.implementation.name}))"
        ),
    ], timeout=30)
    if checked.returncode != 0:
        return [f"managed Python capability probe failed: {checked.stderr.strip()}"]
    try:
        payload = json.loads(checked.stdout)
    except json.JSONDecodeError as exc:
        return [f"managed Python capability output is invalid: {exc}"]
    blockers = []
    if payload.get("version") != expected:
        blockers.append(f"managed Python version is {payload.get('version')}, expected {expected}")
    if payload.get("implementation") != "cpython":
        blockers.append("managed Python implementation is not CPython")
    return blockers


def validate_environment(environment: Path, lock: dict[str, Any]) -> list[str]:
    python = environment_python(environment)
    blockers = validate_python(python, lock["python"]["version"])
    if blockers:
        return blockers
    checked = run([
        str(python), "-c",
        "import importlib.metadata,json,mcp; print(json.dumps({'mcp':importlib.metadata.version('mcp')}))",
    ], timeout=30)
    if checked.returncode != 0:
        return [f"managed MCP import failed: {checked.stderr.strip()}"]
    try:
        observed = json.loads(checked.stdout)["mcp"]
    except (json.JSONDecodeError, KeyError) as exc:
        return [f"managed MCP version output is invalid: {exc}"]
    if observed != lock["python_packages"]["mcp_version"]:
        return [f"managed MCP version is {observed}, expected {lock['python_packages']['mcp_version']}"]
    return []


def descriptor_value(
    base_python: Path, environment: Path, platform: str,
    lock: dict[str, Any], requirements_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "backend": "managed",
        "platform": platform,
        "python": str(base_python),
        "python_version": lock["python"]["version"],
        "python_executable_sha256": sha256_file(base_python),
        "python_archive_sha256": lock["python"]["assets"][platform]["sha256"],
        "environment": str(environment),
        "environment_python": str(environment_python(environment)),
        "requirements_sha256": requirements_sha256,
        "mcp_version": lock["python_packages"]["mcp_version"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base-python", type=Path, required=True)
    parser.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = args.project_root.resolve()
    base_python = args.base_python.resolve()
    runtime_root = (root / ".deps/runtime").resolve()
    if root not in runtime_root.parents or runtime_root == root:
        fail("managed runtime root must remain under the project root")
    expected_base = runtime_root / f"cpython-3.12.11-{args.platform}/bin/python3"
    if base_python != expected_base.resolve():
        fail(f"managed base Python differs from the locked path: {expected_base}")

    lock = load_lock(root)
    requirements = (root / lock["python_packages"]["requirements"]).resolve()
    if root not in requirements.parents or not requirements.is_file():
        fail("managed requirements lock is missing or outside the project root")
    requirements_sha256 = sha256_file(requirements)
    if requirements_sha256 != lock["python_packages"]["requirements_sha256"]:
        fail("managed requirements SHA-256 does not match runtime.lock.json")

    blockers = validate_python(base_python, lock["python"]["version"])
    environment = runtime_root / "venv"
    descriptor = runtime_root / "managed-runtime.json"
    existed = environment.exists() or descriptor.exists()
    created = False
    if not blockers and not existed and args.check:
        blockers.append(f"managed Python environment is missing: {environment}")
    elif not blockers and not existed:
        environment.parent.mkdir(parents=True, exist_ok=True)
        print(f"Creating managed Python environment: {environment}", file=sys.stderr)
        created_venv = run([str(base_python), "-m", "venv", str(environment)], timeout=300)
        if created_venv.returncode != 0:
            fail(f"managed Python environment creation failed: {created_venv.stderr.strip()}")
        python = environment_python(environment)
        installed = run([
            str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "--require-hashes", "--only-binary=:all:", "--requirement", str(requirements),
        ], timeout=1200)
        if installed.returncode != 0:
            fail(f"managed Python package installation failed: {installed.stderr.strip()}")
        blockers.extend(validate_environment(environment, lock))
        if blockers:
            fail("installed managed Python environment failed validation: " + "; ".join(blockers))
        value = descriptor_value(base_python, environment, args.platform, lock, requirements_sha256)
        temporary = descriptor.with_name(f".{descriptor.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, descriptor)
        created = True
    elif not blockers:
        blockers.extend(validate_environment(environment, lock))
        if not descriptor.is_file():
            blockers.append(f"managed runtime descriptor is missing: {descriptor}")
        else:
            try:
                observed = json.loads(descriptor.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                blockers.append(f"managed runtime descriptor is unreadable: {exc}")
            else:
                expected = descriptor_value(
                    base_python, environment, args.platform, lock, requirements_sha256
                )
                if observed != expected:
                    blockers.append("managed runtime descriptor has drifted")

    state = "BLOCKED" if blockers else ("INSTALLED" if created else "READY")
    payload = {
        "schema_version": 1,
        "state": state,
        "backend": "managed",
        "platform": args.platform,
        "base_python": str(base_python),
        "python": str(environment_python(environment)),
        "python_version": lock["python"]["version"],
        "mcp_version": lock["python_packages"]["mcp_version"],
        "descriptor": str(descriptor),
        "blockers": blockers,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif blockers:
        for blocker in blockers:
            print(f"ERROR: {blocker}", file=sys.stderr)
    else:
        print(payload["python"])
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
