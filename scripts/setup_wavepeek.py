#!/usr/bin/env python3
"""Install or validate the commit-pinned optional WavePeek dependency."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path
from typing import Any


LOCK_KEYS = {
    "schema_version", "name", "repository", "commit", "ref", "version", "license",
    "license_file_sha256", "cargo_lock_sha256", "binary", "cargo_features",
    "release_base_url", "release_assets",
}
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
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


def run(
    arguments: list[str], cwd: Path | None = None, timeout: int = 900,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments, cwd=cwd, check=False, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=timeout, env=environment,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        fail(f"command failed or timed out: {arguments[0]}: {exc}")


def git(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return run(["git", *arguments], cwd=cwd, timeout=300)


def load_lock(root: Path) -> dict[str, Any]:
    try:
        value = json.loads((root / "deps/wavepeek.lock.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read WavePeek lock: {exc}")
    if not isinstance(value, dict) or set(value) != LOCK_KEYS:
        fail(f"WavePeek lock keys must be exactly {sorted(LOCK_KEYS)}")
    if value["schema_version"] != 1 or value["name"] != "wavepeek":
        fail("unsupported WavePeek lock identity or schema")
    if not isinstance(value["repository"], str) or not value["repository"]:
        fail("WavePeek repository must be non-empty")
    if not isinstance(value["commit"], str) or not COMMIT.fullmatch(value["commit"]):
        fail("WavePeek commit must be a lowercase 40-character Git object ID")
    if value["ref"] != f"refs/tags/v{value['version']}":
        fail("WavePeek ref must be the locked version tag")
    if not isinstance(value["version"], str) or not VERSION.fullmatch(value["version"]):
        fail("WavePeek version must be semantic x.y.z")
    if value["license"] != "Apache-2.0" or value["binary"] != "wavepeek":
        fail("WavePeek lock must retain reviewed Apache-2.0 identity")
    for key in ("license_file_sha256", "cargo_lock_sha256"):
        if not isinstance(value[key], str) or not SHA256.fullmatch(value[key]):
            fail(f"{key} must be a lowercase SHA-256")
    if value["cargo_features"] != []:
        fail("default WavePeek release must remain VCD/FST-only")
    if value["release_base_url"] != f"https://github.com/kleverhq/wavepeek/releases/download/v{value['version']}":
        fail("WavePeek release base URL does not match the locked version")
    assets = value["release_assets"]
    if not isinstance(assets, dict) or set(assets) != PLATFORMS:
        fail(f"WavePeek release assets must cover exactly {sorted(PLATFORMS)}")
    for target, asset in assets.items():
        expected_name = f"wavepeek-{target}.tar.gz"
        if not isinstance(asset, dict) or set(asset) != {"archive", "sha256"}:
            fail(f"WavePeek asset entry is invalid: {target}")
        if asset["archive"] != expected_name or not isinstance(asset["sha256"], str) or not SHA256.fullmatch(asset["sha256"]):
            fail(f"WavePeek asset identity is invalid: {target}")
    return value


def platform_target() -> str:
    machine = platform.machine().lower()
    architecture = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64" if machine in {"x86_64", "amd64"} else ""
    system = platform.system()
    suffix = "apple-darwin" if system == "Darwin" else "unknown-linux-gnu" if system == "Linux" else ""
    target = f"{architecture}-{suffix}"
    if target not in PLATFORMS:
        fail(f"no reviewed WavePeek release asset for {system}/{machine}")
    return target


def download(url: str, destination: Path) -> None:
    last_error: OSError | TimeoutError | None = None
    request = urllib.request.Request(url, headers={"User-Agent": "verif-harness/0.1"})
    for _ in range(2):
        try:
            with urllib.request.urlopen(request, timeout=300) as response, destination.open("wb") as stream:
                shutil.copyfileobj(response, stream)
            return
        except (OSError, TimeoutError) as exc:
            last_error = exc
    fail(f"WavePeek release download failed after retry: {last_error}")


def extract_binary(archive: Path, destination: Path, binary_name: str) -> None:
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            candidates = []
            for member in bundle.getmembers():
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                    fail("WavePeek release archive contains an unsafe member")
                if member.isfile() and path.name == binary_name:
                    candidates.append(member)
            if len(candidates) != 1:
                fail("WavePeek release archive must contain exactly one executable")
            source = bundle.extractfile(candidates[0])
            if source is None:
                fail("cannot read WavePeek executable from release archive")
            destination.write_bytes(source.read())
            destination.chmod(0o755)
    except tarfile.TarError as exc:
        fail(f"cannot extract WavePeek release archive: {exc}")


def under_root(root: Path, raw: Path, label: str) -> Path:
    path = (root / raw).resolve() if not raw.is_absolute() else raw.resolve()
    if path == root or root not in path.parents:
        fail(f"{label} must remain under the verif-harness project root")
    return path


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
    hashes = (("LICENSE", "license_file_sha256"), ("Cargo.lock", "cargo_lock_sha256"))
    for relative, key in hashes:
        path = source / relative
        if not path.is_file() or sha256_file(path) != lock[key]:
            blockers.append(f"{relative} does not match the reviewed hash")
    return blockers


def validate_binary(binary: Path, lock: dict[str, Any]) -> tuple[list[str], str | None]:
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return [f"managed executable missing or not executable: {binary}"], None
    checked = run([str(binary), "--version"], timeout=15)
    observed = checked.stdout.strip()
    if checked.returncode != 0 or observed != f"wavepeek v{lock['version']}":
        return [f"WavePeek version probe mismatch: {observed or checked.stderr.strip()}"], observed
    return [], observed


def install(
    source: Path, binary: Path, lock: dict[str, Any], archive_override: Path | None
) -> str:
    source.parent.mkdir(parents=True, exist_ok=True)
    binary.parent.parent.mkdir(parents=True, exist_ok=True)
    temporary_source = source.parent / f".{source.name}.install-{os.getpid()}"
    temporary_bin = binary.parent.parent / f".{binary.parent.name}.install-{os.getpid()}"
    temporary_archive = source.parent / f".wavepeek-asset-{os.getpid()}.tar.gz"
    for path in (temporary_source, temporary_bin):
        if path.exists():
            fail(f"temporary install path already exists: {path}")
    try:
        tag = lock["ref"].removeprefix("refs/tags/")
        cloned = git(
            "clone", "--depth", "1", "--single-branch", "--branch", tag,
            lock["repository"], str(temporary_source),
        )
        if cloned.returncode != 0 and temporary_source.is_dir():
            shutil.rmtree(temporary_source)
            cloned = git(
                "clone", "--depth", "1", "--single-branch", "--branch", tag,
                lock["repository"], str(temporary_source),
            )
        if cloned.returncode != 0:
            fail(f"WavePeek tagged clone failed: {cloned.stderr.strip()}")
        blockers = validate_source(temporary_source, lock)
        if blockers:
            fail("installed WavePeek source failed validation: " + "; ".join(blockers))
        target = platform_target()
        asset = lock["release_assets"][target]
        if archive_override is None:
            download(f"{lock['release_base_url']}/{asset['archive']}", temporary_archive)
            archive = temporary_archive
        else:
            archive = archive_override.resolve()
            if not archive.is_file():
                fail(f"WavePeek archive override does not exist: {archive}")
        if sha256_file(archive) != asset["sha256"]:
            fail("WavePeek release archive SHA-256 does not match the lock")
        temporary_bin.mkdir()
        extract_binary(archive, temporary_bin / lock["binary"], lock["binary"])
        blockers, _ = validate_binary(temporary_bin / lock["binary"], lock)
        if blockers:
            fail("built WavePeek failed validation: " + "; ".join(blockers))
        os.replace(temporary_source, source)
        os.replace(temporary_bin, binary.parent)
        return target
    finally:
        for path in (temporary_source, temporary_bin):
            if path.is_dir():
                shutil.rmtree(path)
        if temporary_archive.is_file():
            temporary_archive.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-dest", type=Path, default=Path(".deps/wavepeek"))
    parser.add_argument("--binary-dest", type=Path, default=Path(".deps/wavepeek-bin/wavepeek"))
    parser.add_argument("--archive", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.project_root.resolve()
    lock = load_lock(root)
    source = under_root(root, args.source_dest, "WavePeek source destination")
    binary = under_root(root, args.binary_dest, "WavePeek binary destination")
    selected_target = platform_target()
    existed = source.exists() or binary.exists()
    if not existed and args.check:
        blockers, observed = [f"managed WavePeek install missing: {source}"], None
    elif not existed:
        selected_target = install(source, binary, lock, args.archive)
        blockers = validate_source(source, lock)
        binary_blockers, observed = validate_binary(binary, lock)
        blockers.extend(binary_blockers)
    else:
        selected_target = platform_target()
        blockers = validate_source(source, lock)
        binary_blockers, observed = validate_binary(binary, lock)
        blockers.extend(binary_blockers)
    state = "BLOCKED" if blockers else ("READY" if existed else "INSTALLED")
    payload = {
        "schema_version": 1, "state": state, "source": str(source),
        "binary": str(binary), "binary_sha256": sha256_file(binary) if binary.is_file() else None,
        "repository": lock["repository"], "commit": lock["commit"],
        "version": observed, "platform": selected_target,
        "release_archive": lock["release_assets"][selected_target]["archive"],
        "cargo_features": lock["cargo_features"],
        "blockers": blockers,
        "notice": "WavePeek remains an optional, separately licensed source dependency; FSDB is not enabled.",
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"WavePeek dependency: {state}")
        print(f"source: {source}\nbinary: {binary}\ncommit: {lock['commit']}")
        for blocker in blockers:
            print(f"ERROR: {blocker}")
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
