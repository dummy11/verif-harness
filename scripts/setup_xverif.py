#!/usr/bin/env python3
"""Install or validate the commit-pinned optional xverif dependency."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


LOCK_KEYS = {
    "schema_version", "name", "repository", "commit", "license",
    "license_file_sha256", "tools",
}
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
TOOL = re.compile(r"x[a-z0-9-]+")
MANAGED_TOOLS = (
    "xbit", "xentry", "xloc", "xsva", "xcov", "xdebug", "xwaveform",
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(
    *arguments: str, cwd: Path | None = None, timeout_seconds: int = 300
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *arguments], cwd=cwd, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        fail(f"git command timed out after {timeout_seconds} seconds: {arguments[0]}")


def load_lock(root: Path) -> dict[str, Any]:
    path = root / "deps/xverif.lock.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read xverif lock: {exc}")
    if not isinstance(value, dict) or set(value) != LOCK_KEYS:
        fail(f"xverif lock keys must be exactly {sorted(LOCK_KEYS)}")
    if value["schema_version"] != 1 or value["name"] != "xverif":
        fail("unsupported xverif lock identity or schema")
    if not isinstance(value["repository"], str) or not value["repository"]:
        fail("xverif repository must be a non-empty string")
    if not isinstance(value["commit"], str) or not COMMIT.fullmatch(value["commit"]):
        fail("xverif commit must be a lowercase 40-character Git object ID")
    if value["license"] != "MIT":
        fail("xverif lock must declare the reviewed MIT license")
    if not isinstance(value["license_file_sha256"], str) or not SHA256.fullmatch(
        value["license_file_sha256"]
    ):
        fail("xverif license_file_sha256 must be a lowercase SHA-256")
    tools = value["tools"]
    if not isinstance(tools, list) or not tools or not all(
        isinstance(tool, str) and TOOL.fullmatch(tool) for tool in tools
    ):
        fail("xverif tools must be a non-empty wrapper-name array")
    if len(tools) != len(set(tools)):
        fail("xverif tools contains duplicates")
    if tuple(tools) != MANAGED_TOOLS:
        fail(f"xverif tools must match the reviewed order {MANAGED_TOOLS}")
    return value


def resolve_destination(root: Path, raw: Path) -> Path:
    destination = (root / raw).resolve() if not raw.is_absolute() else raw.resolve()
    if destination == root or root not in destination.parents:
        fail("xverif destination must remain under the verif-harness project root")
    return destination


def validate_install(destination: Path, lock: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not destination.is_dir():
        return [f"managed checkout missing: {destination}"]
    if not (destination / ".git").exists():
        blockers.append("managed checkout has no Git metadata")
    remote = git("remote", "get-url", "origin", cwd=destination)
    if remote.returncode != 0 or remote.stdout.strip() != lock["repository"]:
        blockers.append("origin does not match the locked repository")
    head = git("rev-parse", "HEAD", cwd=destination)
    if head.returncode != 0 or head.stdout.strip() != lock["commit"]:
        blockers.append("HEAD does not match the locked commit")
    status = git("status", "--porcelain", cwd=destination)
    if status.returncode != 0 or status.stdout.strip():
        blockers.append("managed checkout is dirty or unreadable")
    license_path = destination / "LICENSE"
    if not license_path.is_file() or sha256_file(license_path) != lock["license_file_sha256"]:
        blockers.append("LICENSE does not match the locked MIT license hash")
    for tool in lock["tools"]:
        wrapper = destination / "tools" / tool
        if not wrapper.is_file() or not os.access(wrapper, os.X_OK):
            blockers.append(f"required wrapper missing or not executable: tools/{tool}")
    return blockers


def install(destination: Path, lock: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.install-{os.getpid()}"
    if temporary.exists():
        fail(f"temporary install path already exists: {temporary}")
    try:
        initialized = git("init", str(temporary))
        if initialized.returncode != 0:
            fail(f"xverif git init failed: {initialized.stderr.strip()}")
        remote = git("remote", "add", "origin", lock["repository"], cwd=temporary)
        if remote.returncode != 0:
            fail(f"xverif remote setup failed: {remote.stderr.strip()}")
        fetched = git(
            "fetch", "--depth", "1", "--filter=blob:none", "origin", lock["commit"],
            cwd=temporary,
        )
        if fetched.returncode != 0:
            fail(f"xverif commit fetch failed: {fetched.stderr.strip()}")
        sparse = git("sparse-checkout", "init", "--cone", cwd=temporary)
        if sparse.returncode != 0:
            fail(f"xverif sparse-checkout init failed: {sparse.stderr.strip()}")
        sparse_paths = ["tools", *lock["tools"]]
        sparse_set = git("sparse-checkout", "set", *sparse_paths, cwd=temporary)
        if sparse_set.returncode != 0:
            fail(f"xverif sparse-checkout set failed: {sparse_set.stderr.strip()}")
        checkout = git("checkout", "--detach", "FETCH_HEAD", cwd=temporary)
        if checkout.returncode != 0:
            fail(f"xverif checkout failed: {checkout.stderr.strip()}")
        blockers = validate_install(temporary, lock)
        if blockers:
            fail("installed xverif failed validation: " + "; ".join(blockers))
        os.replace(temporary, destination)
    finally:
        if temporary.is_dir():
            shutil.rmtree(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dest", type=Path, default=Path(".deps/xverif"))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.project_root.resolve()
    lock = load_lock(root)
    destination = resolve_destination(root, args.dest)
    existed = destination.exists()
    if not existed and args.check:
        blockers = [f"managed checkout missing: {destination}"]
    elif not existed:
        install(destination, lock)
        blockers = validate_install(destination, lock)
    else:
        blockers = validate_install(destination, lock)
    state = "BLOCKED" if blockers else ("READY" if existed else "INSTALLED")
    payload = {
        "schema_version": 1,
        "state": state,
        "destination": str(destination),
        "repository": lock["repository"],
        "commit": lock["commit"],
        "tools": lock["tools"],
        "blockers": blockers,
        "notice": "xverif remains an optional, separately licensed source dependency.",
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"xverif dependency: {state}")
        print(f"destination: {destination}")
        print(f"commit: {lock['commit']}")
        for blocker in blockers:
            print(f"ERROR: {blocker}")
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
