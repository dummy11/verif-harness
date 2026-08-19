#!/usr/bin/env python3
"""Install or validate the release-pinned optional GitHub Spec Kit dependency."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


LOCK_KEYS = {
    "schema_version", "name", "repository", "commit", "ref", "version",
    "license", "license_file_sha256", "pyproject_sha256", "python_requires",
    "package", "executable",
}
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SUPPORTED_INTEGRATIONS = ("codex", "kimi")
REVIEWED_IDENTITY = {
    "repository": "https://github.com/github/spec-kit.git",
    "commit": "d1f50fcbe684a4222059c4ba7f2d7eabcca87402",
    "ref": "refs/tags/v0.16.4",
    "version": "0.16.4",
    "license": "MIT",
    "license_file_sha256": (
        "2510b446bc1f0cf9702453075d20cd88631e20e5642658edb7325d9c1eb534f7"
    ),
    "pyproject_sha256": (
        "dfbc208b1907c4c3a6273e90ddce99c40b3ede58a0dad5a843b2134d33ba91cf"
    ),
    "python_requires": ">=3.11",
    "package": "specify-cli",
    "executable": "specify",
}


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(
    arguments: list[str], cwd: Path | None = None, timeout: int = 900,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments, cwd=cwd, check=False, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        fail(f"command failed or timed out: {arguments[0]}: {exc}")


def git(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return run(["git", *arguments], cwd=cwd, timeout=300)


def load_lock(root: Path) -> dict[str, Any]:
    try:
        value = json.loads((root / "deps/spec-kit.lock.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read Spec Kit lock: {exc}")
    if not isinstance(value, dict) or set(value) != LOCK_KEYS:
        fail(f"Spec Kit lock keys must be exactly {sorted(LOCK_KEYS)}")
    if value["schema_version"] != 2 or value["name"] != "spec-kit":
        fail("unsupported Spec Kit lock identity or schema")
    if not isinstance(value["commit"], str) or not COMMIT.fullmatch(value["commit"]):
        fail("Spec Kit commit must be a lowercase 40-character object ID")
    if not isinstance(value["version"], str) or not VERSION.fullmatch(value["version"]):
        fail("Spec Kit version must be semantic x.y.z")
    if value["ref"] != f"refs/tags/v{value['version']}":
        fail("Spec Kit ref must match the locked version tag")
    if value["license"] != "MIT":
        fail("Spec Kit lock must retain the reviewed MIT identity")
    if value["python_requires"] != ">=3.11":
        fail("Spec Kit lock must require Python 3.11 or newer")
    for key in ("license_file_sha256", "pyproject_sha256"):
        if not isinstance(value[key], str) or not SHA256.fullmatch(value[key]):
            fail(f"{key} must be a lowercase SHA-256")
    for key, expected in REVIEWED_IDENTITY.items():
        if value[key] != expected:
            fail(f"Spec Kit {key} differs from the reviewed dependency identity")
    return value


def under_root(root: Path, raw: Path, label: str) -> Path:
    path = (root / raw).resolve() if not raw.is_absolute() else raw.resolve()
    if path == root or root not in path.parents:
        fail(f"{label} must remain under the verif-harness project root")
    return path


def environment_executable(environment: Path, name: str) -> Path:
    directory = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return environment / directory / f"{name}{suffix}"


def validate_source(source: Path, lock: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not source.is_dir() or not (source / ".git").exists():
        return [f"managed source checkout missing or unmanaged: {source}"]
    remote = git("remote", "get-url", "origin", cwd=source)
    head = git("rev-parse", "HEAD", cwd=source)
    status = git("status", "--porcelain", cwd=source)
    if remote.returncode != 0 or remote.stdout.strip() != lock["repository"]:
        blockers.append("origin does not match the locked repository")
    if head.returncode != 0 or head.stdout.strip() != lock["commit"]:
        blockers.append("HEAD does not match the locked commit")
    if status.returncode != 0 or status.stdout.strip():
        blockers.append("managed source checkout is dirty or unreadable")
    hashes = (("LICENSE", "license_file_sha256"), ("pyproject.toml", "pyproject_sha256"))
    for relative, key in hashes:
        path = source / relative
        if not path.is_file() or sha256_file(path) != lock[key]:
            blockers.append(f"{relative} does not match the reviewed hash")
    return blockers


def validate_runtime(environment: Path, lock: dict[str, Any]) -> tuple[list[str], str | None]:
    python = environment_executable(environment, "python")
    if not python.is_file() or not os.access(python, os.X_OK):
        return [f"managed Spec Kit Python missing: {python}"], None
    checked = run(
        [str(python), "-c", "from specify_cli import main; main()", "--version"],
        timeout=30,
    )
    observed = (checked.stdout + checked.stderr).strip()
    if checked.returncode != 0 or lock["version"] not in observed:
        return [f"Spec Kit version probe mismatch: {observed}"], observed
    integrations = run(
        [
            str(python), "-c",
            (
                "from specify_cli.integrations import get_integration;"
                "c=get_integration('codex');k=get_integration('kimi');"
                "assert c is not None and c.config['folder']=='.agents/';"
                "assert k is not None and k.config['folder']=='.kimi-code/';"
                "assert k.registrar_config['dir']=='.kimi-code/skills'"
            ),
        ],
        timeout=30,
    )
    if integrations.returncode != 0:
        return ["Spec Kit Codex/Kimi integration contract is unavailable"], observed
    return [], observed


def python_version(executable: str) -> tuple[int, int, int]:
    checked = run(
        [
            executable, "-c",
            "import json,sys; print(json.dumps(list(sys.version_info[:3])))",
        ],
        timeout=30,
    )
    if checked.returncode != 0:
        fail(f"cannot execute requested Python: {checked.stderr.strip()}")
    try:
        value = json.loads(checked.stdout)
    except json.JSONDecodeError as exc:
        fail(f"cannot parse Python version: {exc}")
    return tuple(value)


def install(
    source: Path, environment: Path, lock: dict[str, Any], python: str,
) -> None:
    if python_version(python) < (3, 11, 0):
        fail("Spec Kit v0.16.4 requires Python 3.11 or newer")
    source.parent.mkdir(parents=True, exist_ok=True)
    environment.parent.mkdir(parents=True, exist_ok=True)
    temporary_source = source.parent / f".{source.name}.install-{os.getpid()}"
    temporary_env = environment.parent / f".{environment.name}.install-{os.getpid()}"
    for path in (temporary_source, temporary_env):
        if path.exists():
            fail(f"temporary install path already exists: {path}")
    try:
        tag = lock["ref"].removeprefix("refs/tags/")
        cloned = git(
            "clone", "--depth", "1", "--single-branch", "--branch", tag,
            lock["repository"], str(temporary_source),
        )
        if cloned.returncode != 0:
            fail(f"Spec Kit tagged clone failed: {cloned.stderr.strip()}")
        blockers = validate_source(temporary_source, lock)
        if blockers:
            fail("installed Spec Kit source failed validation: " + "; ".join(blockers))
        created = run([python, "-m", "venv", str(temporary_env)], timeout=300)
        if created.returncode != 0:
            fail(f"Spec Kit virtual environment creation failed: {created.stderr.strip()}")
        environment_python = environment_executable(temporary_env, "python")
        installed = run(
            [
                str(environment_python), "-m", "pip", "install",
                "--disable-pip-version-check", str(temporary_source),
            ],
            timeout=900,
        )
        if installed.returncode != 0:
            fail(f"Spec Kit package installation failed: {installed.stderr.strip()}")
        runtime_blockers, _ = validate_runtime(temporary_env, lock)
        if runtime_blockers:
            fail("installed Spec Kit runtime failed validation: " + "; ".join(runtime_blockers))
        os.replace(temporary_source, source)
        os.replace(temporary_env, environment)
    finally:
        for path in (temporary_source, temporary_env):
            if path.is_dir():
                shutil.rmtree(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-dest", type=Path, default=Path(".deps/spec-kit"))
    parser.add_argument("--venv-dest", type=Path, default=Path(".deps/spec-kit-venv"))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.project_root.resolve()
    lock = load_lock(root)
    source = under_root(root, args.source_dest, "Spec Kit source destination")
    environment = under_root(root, args.venv_dest, "Spec Kit environment destination")
    existed = source.exists() or environment.exists()
    if not existed and args.check:
        blockers, observed = [f"managed Spec Kit install missing: {source}"], None
    elif not existed:
        install(source, environment, lock, args.python)
        blockers = validate_source(source, lock)
        runtime_blockers, observed = validate_runtime(environment, lock)
        blockers.extend(runtime_blockers)
    else:
        blockers = validate_source(source, lock)
        runtime_blockers, observed = validate_runtime(environment, lock)
        blockers.extend(runtime_blockers)
    state = "BLOCKED" if blockers else ("READY" if existed else "INSTALLED")
    payload = {
        "schema_version": 1,
        "state": state,
        "source": str(source),
        "environment": str(environment),
        "python": str(environment_executable(environment, "python")),
        "repository": lock["repository"],
        "commit": lock["commit"],
        "version": observed,
        "supported_integrations": list(SUPPORTED_INTEGRATIONS),
        "blockers": blockers,
        "notice": (
            "Spec Kit is an optional agentic specification subsystem; its command "
            "success is not deterministic verification evidence or approval."
        ),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Spec Kit dependency: {state}")
        print(f"source: {source}\nenvironment: {environment}\ncommit: {lock['commit']}")
        for blocker in blockers:
            print(f"ERROR: {blocker}")
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
