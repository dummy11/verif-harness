#!/usr/bin/env python3
"""Install or validate the commit-pinned optional WavePeek dependency."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any


LOCK_KEYS = {
    "schema_version", "name", "repository", "commit", "ref", "version", "license",
    "license_file_sha256", "cargo_lock_sha256", "binary", "cargo_features",
    "private_glibc", "release_base_url", "release_assets",
}
PRIVATE_GLIBC_KEYS = {
    "minimum_host_version", "version", "source_url", "source_sha256",
    "license", "license_file", "license_file_sha256", "licenses_file",
    "licenses_file_sha256", "configure_args",
}
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SHORT_VERSION = re.compile(r"[0-9]+\.[0-9]+")
TOOL_VERSION = re.compile(r"(?<![0-9])([0-9]+(?:\.[0-9]+){1,3})(?![0-9])")
PRIVATE_GLIBC_BUILD_REQUIREMENTS = {
    "as": "2.25",
    "bison": "2.7",
    "gcc": "6.2",
    "gawk": "3.1.2",
    "ld": "2.25",
    "make": "4.0",
    "sed": "3.02",
}
PLATFORMS = {
    "aarch64-apple-darwin", "x86_64-apple-darwin",
    "aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu",
}
LINUX_LOADERS = {
    "aarch64-unknown-linux-gnu": "ld-linux-aarch64.so.1",
    "x86_64-unknown-linux-gnu": "ld-linux-x86-64.so.2",
}
RUNTIME_DESCRIPTOR = "wavepeek-runtime.json"


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
    if value["schema_version"] != 2 or value["name"] != "wavepeek":
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
    private_glibc = value["private_glibc"]
    if not isinstance(private_glibc, dict) or set(private_glibc) != PRIVATE_GLIBC_KEYS:
        fail(f"WavePeek private_glibc keys must be exactly {sorted(PRIVATE_GLIBC_KEYS)}")
    if (
        private_glibc["minimum_host_version"] != "2.34"
        or private_glibc["version"] != "2.34"
        or private_glibc["source_url"]
        != "https://ftp.gnu.org/gnu/glibc/glibc-2.34.tar.xz"
        or private_glibc["source_sha256"]
        != "44d26a1fe20b8853a48f470ead01e4279e869ac149b195dda4e44a195d981ab2"
        or private_glibc["license"] != "LGPL-2.1-or-later"
        or private_glibc["license_file"] != "COPYING.LIB"
        or private_glibc["license_file_sha256"]
        != "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551"
        or private_glibc["licenses_file"] != "LICENSES"
        or private_glibc["licenses_file_sha256"]
        != "b33d0bd9f685b46853548814893a6135e74430d12f6d94ab3eba42fc591f83bc"
        or private_glibc["configure_args"] != ["--disable-werror"]
    ):
        fail("WavePeek private glibc differs from the reviewed 2.34 identity")
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
    if not url.startswith("https://"):
        fail(f"managed dependency URL must use HTTPS: {url}")
    curl = shutil.which("curl")
    wget = shutil.which("wget")
    if curl is not None:
        downloader = "curl"
        arguments = [
            curl, "--proto", "=https", "--tlsv1.2", "--fail", "--location",
            "--retry", "2", "--user-agent", "verif-harness/0.1",
            "--output", str(destination), url,
        ]
    elif wget is not None:
        downloader = "wget"
        arguments = [
            wget, "--https-only", "--tries=3", "--user-agent=verif-harness/0.1",
            "--output-document", str(destination), url,
        ]
    else:
        fail("managed dependency download requires curl or wget")
    checked = run(arguments, timeout=900)
    if checked.returncode != 0:
        if destination.is_file():
            destination.unlink()
        detail = checked.stderr.strip() or checked.stdout.strip() or "unknown error"
        fail(
            f"managed dependency HTTPS download failed using {downloader}: {detail}; "
            "configure the host CA trust without disabling TLS verification"
        )
    if not destination.is_file():
        fail(f"managed dependency downloader produced no file: {downloader}")


def parsed_version(value: str) -> tuple[int, ...]:
    if not SHORT_VERSION.fullmatch(value):
        fail(f"invalid glibc version: {value}")
    return tuple(int(part) for part in value.split("."))


def tool_version_at_least(observed: str, minimum: str) -> bool:
    match = TOOL_VERSION.search(observed)
    if match is None:
        return False
    current = tuple(int(part) for part in match.group(1).split("."))
    required = tuple(int(part) for part in minimum.split("."))
    width = max(len(current), len(required))
    return current + (0,) * (width - len(current)) >= required + (0,) * (width - len(required))


def validate_private_glibc_build_tools() -> None:
    problems: list[str] = []
    for tool, minimum in PRIVATE_GLIBC_BUILD_REQUIREMENTS.items():
        executable = shutil.which(tool)
        if executable is None:
            problems.append(f"{tool} is missing (requires >={minimum})")
            continue
        checked = run([executable, "--version"], timeout=30)
        observed = next(
            (line.strip() for line in (checked.stdout + checked.stderr).splitlines() if line.strip()),
            "version unavailable",
        )
        if checked.returncode != 0 or not tool_version_at_least(observed, minimum):
            problems.append(f"{tool} requires >={minimum}; observed {observed}")
    if sys.version_info < (3, 4):
        problems.append(
            "Python requires >=3.4; observed "
            + ".".join(str(part) for part in sys.version_info[:3])
        )
    if problems:
        fail("private glibc build prerequisites are not satisfied: " + "; ".join(problems))


def host_glibc_version() -> str | None:
    if platform.system() != "Linux":
        return None
    try:
        observed = os.confstr("CS_GNU_LIBC_VERSION")
    except (AttributeError, OSError, ValueError):
        observed = None
    if observed:
        match = re.search(r"(?:glibc\s+)?([0-9]+\.[0-9]+)", observed)
        if match:
            return match.group(1)
    family, version = platform.libc_ver()
    if family.lower() == "glibc" and SHORT_VERSION.fullmatch(version):
        return version
    return None


def requires_private_glibc(target: str, observed: str | None, minimum: str) -> bool:
    if target not in LINUX_LOADERS:
        return False
    return observed is None or parsed_version(observed) < parsed_version(minimum)


def safe_extract_source(archive: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive, "r:xz") as bundle:
            for member in bundle.getmembers():
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts:
                    fail("glibc source archive contains an unsafe member path")
                if member.issym() or member.islnk():
                    target = posixpath.normpath(
                        posixpath.join(posixpath.dirname(member.name), member.linkname)
                    )
                    if target == ".." or target.startswith("../") or target.startswith("/"):
                        fail("glibc source archive contains an unsafe link")
            bundle.extractall(destination)
    except tarfile.TarError as exc:
        fail(f"cannot extract private glibc source archive: {exc}")


def private_glibc_loader(root: Path, target: str) -> Path | None:
    name = LINUX_LOADERS.get(target)
    if name is None:
        return None
    candidates = sorted(path for path in root.rglob(name) if path.is_file())
    return candidates[0] if len(candidates) == 1 else None


def validate_private_glibc(
    root: Path, target: str, contract: dict[str, Any]
) -> tuple[list[str], dict[str, Any] | None]:
    root = root.resolve()
    blockers: list[str] = []
    license_path = root / "share/licenses/glibc" / contract["license_file"]
    if (
        not license_path.is_file()
        or sha256_file(license_path) != contract["license_file_sha256"]
    ):
        blockers.append("private glibc license file does not match the reviewed hash")
    licenses_path = root / "share/licenses/glibc" / contract["licenses_file"]
    if (
        not licenses_path.is_file()
        or sha256_file(licenses_path) != contract["licenses_file_sha256"]
    ):
        blockers.append("private glibc LICENSES file does not match the reviewed hash")
    loader = private_glibc_loader(root, target)
    if loader is None or not os.access(loader, os.X_OK):
        blockers.append(f"private glibc loader missing for {target}")
        return blockers, None
    checked = run([str(loader), "--version"], timeout=30)
    observed = (checked.stdout + checked.stderr).strip()
    if checked.returncode != 0 or not re.search(
        rf"\b{re.escape(contract['version'])}\b", observed
    ):
        blockers.append(f"private glibc loader version mismatch: {observed}")
    libc_paths = [path for path in root.rglob("libc.so.6") if path.is_file()]
    if not libc_paths:
        blockers.append("private glibc libc.so.6 is missing")
    library_dirs = sorted(
        {loader.parent.resolve(), *(path.parent.resolve() for path in libc_paths)}
    )
    if blockers:
        return blockers, None
    descriptor = {
        "schema_version": 1,
        "kind": "private-glibc",
        "version": contract["version"],
        "root": f"../glibc-{contract['version']}",
        "loader": loader.relative_to(root).as_posix(),
        "loader_sha256": sha256_file(loader),
        "library_dirs": [path.relative_to(root).as_posix() for path in library_dirs],
        "license": contract["license"],
        "license_file_sha256": contract["license_file_sha256"],
        "licenses_file_sha256": contract["licenses_file_sha256"],
    }
    return [], descriptor


def install_private_glibc(
    root: Path, target: str, contract: dict[str, Any]
) -> dict[str, Any]:
    if target not in LINUX_LOADERS:
        fail(f"private glibc is unsupported for platform target: {target}")
    validate_private_glibc_build_tools()
    root.parent.mkdir(parents=True, exist_ok=True)
    temporary = root.parent / f".{root.name}.install-{os.getpid()}"
    if temporary.exists():
        fail(f"temporary private glibc install path already exists: {temporary}")
    try:
        temporary.mkdir()
        archive = temporary / f"glibc-{contract['version']}.tar.xz"
        print(
            f"Host glibc is below {contract['minimum_host_version']}; "
            f"installing private glibc {contract['version']} for WavePeek.",
            file=sys.stderr,
        )
        download(contract["source_url"], archive)
        if sha256_file(archive) != contract["source_sha256"]:
            fail("private glibc source archive SHA-256 does not match the lock")
        unpack = temporary / "unpack"
        unpack.mkdir()
        safe_extract_source(archive, unpack)
        source = unpack / f"glibc-{contract['version']}"
        if not source.is_dir():
            fail("private glibc source archive lacks the expected top directory")
        source_license = source / contract["license_file"]
        if (
            not source_license.is_file()
            or sha256_file(source_license) != contract["license_file_sha256"]
        ):
            fail("private glibc source license does not match the reviewed hash")
        source_licenses = source / contract["licenses_file"]
        if (
            not source_licenses.is_file()
            or sha256_file(source_licenses) != contract["licenses_file_sha256"]
        ):
            fail("private glibc source LICENSES does not match the reviewed hash")
        build = temporary / "build"
        stage = temporary / "stage"
        build.mkdir()
        stage.mkdir()
        print("Configuring private glibc (system libc is unchanged).", file=sys.stderr)
        configured = run(
            [
                str(source / "configure"), f"--prefix={root}",
                *contract["configure_args"],
            ],
            cwd=build,
            timeout=600,
        )
        if configured.returncode != 0:
            fail(f"private glibc configure failed: {configured.stderr.strip()}")
        print("Building private glibc; this may take several minutes.", file=sys.stderr)
        built = run(
            ["make", "-j", str(min(os.cpu_count() or 1, 8))],
            cwd=build,
            timeout=3600,
        )
        if built.returncode != 0:
            fail(f"private glibc build failed: {built.stderr.strip()}")
        print("Publishing private glibc under .deps for WavePeek only.", file=sys.stderr)
        installed = run(
            ["make", "install", f"install_root={stage}"],
            cwd=build,
            timeout=1800,
        )
        if installed.returncode != 0:
            fail(f"private glibc install failed: {installed.stderr.strip()}")
        staged_root = stage / str(root).lstrip(os.sep)
        if not staged_root.is_dir():
            fail(f"private glibc staged prefix is missing: {staged_root}")
        installed_license = staged_root / "share/licenses/glibc" / contract["license_file"]
        installed_license.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_license, installed_license)
        shutil.copy2(
            source_licenses,
            installed_license.parent / contract["licenses_file"],
        )
        blockers, _ = validate_private_glibc(staged_root, target, contract)
        if blockers:
            fail("built private glibc failed validation: " + "; ".join(blockers))
        os.replace(staged_root, root)
    finally:
        if temporary.is_dir():
            shutil.rmtree(temporary)
    blockers, descriptor = validate_private_glibc(root, target, contract)
    if blockers or descriptor is None:
        fail("installed private glibc failed validation: " + "; ".join(blockers))
    return descriptor


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


def runtime_descriptor_path(binary: Path) -> Path:
    return binary.parent / RUNTIME_DESCRIPTOR


def write_runtime_descriptor(binary: Path, descriptor: dict[str, Any]) -> None:
    destination = runtime_descriptor_path(binary)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(descriptor, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, destination)


def load_runtime_descriptor(binary: Path) -> dict[str, Any] | None:
    path = runtime_descriptor_path(binary)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read WavePeek runtime descriptor: {exc}")
    keys = {
        "schema_version", "kind", "version", "root", "loader",
        "loader_sha256", "library_dirs", "license", "license_file_sha256",
        "licenses_file_sha256",
    }
    if not isinstance(value, dict) or set(value) != keys:
        fail(f"WavePeek runtime descriptor keys must be exactly {sorted(keys)}")
    if value["version"] != "2.34":
        fail("WavePeek runtime descriptor version is invalid")
    if (
        value["schema_version"] != 1
        or value["kind"] != "private-glibc"
        or value["root"] != f"../glibc-{value['version']}"
        or value["license"] != "LGPL-2.1-or-later"
        or not isinstance(value["loader"], str)
        or not isinstance(value["loader_sha256"], str)
        or not SHA256.fullmatch(value["loader_sha256"])
        or value["license_file_sha256"]
        != "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551"
        or value["licenses_file_sha256"]
        != "b33d0bd9f685b46853548814893a6135e74430d12f6d94ab3eba42fc591f83bc"
    ):
        fail("WavePeek runtime descriptor identity is invalid")
    if (
        not isinstance(value["library_dirs"], list)
        or not value["library_dirs"]
        or not all(isinstance(item, str) and item for item in value["library_dirs"])
    ):
        fail("WavePeek runtime descriptor library_dirs must be non-empty")
    for raw_path in (value["loader"], *value["library_dirs"]):
        path_value = Path(raw_path)
        if path_value.is_absolute() or ".." in path_value.parts:
            fail("WavePeek runtime descriptor contains an unsafe relative path")
    return value


def binary_command(binary: Path) -> tuple[list[str], dict[str, Any] | None]:
    descriptor = load_runtime_descriptor(binary)
    if descriptor is None:
        return [str(binary)], None
    root = (binary.parent / descriptor["root"]).resolve()
    expected_root = binary.parent.parent / f"glibc-{descriptor['version']}"
    if root != expected_root.resolve():
        fail("WavePeek private glibc root differs from the managed location")
    loader = (root / descriptor["loader"]).resolve()
    if (
        root not in loader.parents
        or not loader.is_file()
        or not os.access(loader, os.X_OK)
        or sha256_file(loader) != descriptor["loader_sha256"]
    ):
        fail("WavePeek private glibc loader is missing or has drifted")
    library_dirs = [(root / relative).resolve() for relative in descriptor["library_dirs"]]
    if any(root not in path.parents or not path.is_dir() for path in library_dirs):
        fail("WavePeek private glibc library path is missing or unsafe")
    return [
        str(loader), "--library-path", ":".join(str(path) for path in library_dirs),
        str(binary),
    ], descriptor


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
    try:
        command, _ = binary_command(binary)
    except SystemExit as exc:
        return [str(exc)], None
    checked = run([*command, "--version"], timeout=15)
    observed = checked.stdout.strip()
    if checked.returncode != 0 or observed != f"wavepeek v{lock['version']}":
        return [f"WavePeek version probe mismatch: {observed or checked.stderr.strip()}"], observed
    return [], observed


def install(
    source: Path, binary: Path, lock: dict[str, Any], archive_override: Path | None,
    runtime_descriptor: dict[str, Any] | None,
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
        if runtime_descriptor is not None:
            write_runtime_descriptor(
                temporary_bin / lock["binary"], runtime_descriptor
            )
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
    parser.add_argument(
        "--glibc-dest", type=Path, default=Path(".deps/glibc-2.34")
    )
    parser.add_argument("--archive", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.project_root.resolve()
    lock = load_lock(root)
    source = under_root(root, args.source_dest, "WavePeek source destination")
    binary = under_root(root, args.binary_dest, "WavePeek binary destination")
    private_glibc_root = under_root(
        root, args.glibc_dest, "WavePeek private glibc destination"
    )
    selected_target = platform_target()
    observed_host_glibc = host_glibc_version()
    glibc_contract = lock["private_glibc"]
    private_required = requires_private_glibc(
        selected_target, observed_host_glibc, glibc_contract["minimum_host_version"]
    )
    expected_private_root = (
        binary.parent.parent / f"glibc-{glibc_contract['version']}"
    ).resolve()
    if private_required and private_glibc_root != expected_private_root:
        fail(
            "WavePeek private glibc destination must remain adjacent to the "
            f"managed binary directory: {expected_private_root}"
        )
    existed = source.exists() or binary.exists()
    source_blockers = validate_source(source, lock) if existed else []
    if existed and (not binary.is_file() or not os.access(binary, os.X_OK)):
        source_blockers.append(
            f"managed executable missing or not executable: {binary}"
        )
    private_blockers: list[str] = []
    runtime_descriptor: dict[str, Any] | None = None
    private_state = "NOT_REQUIRED"
    if private_required and not source_blockers:
        if private_glibc_root.exists():
            private_blockers, runtime_descriptor = validate_private_glibc(
                private_glibc_root, selected_target, glibc_contract
            )
            private_state = "BLOCKED" if private_blockers else "READY"
        elif args.check:
            private_blockers = [
                f"managed private glibc missing: {private_glibc_root}"
            ]
            private_state = "BLOCKED"
        else:
            runtime_descriptor = install_private_glibc(
                private_glibc_root, selected_target, glibc_contract
            )
            private_state = "INSTALLED"
    if not existed and args.check:
        blockers, observed = [f"managed WavePeek install missing: {source}"], None
        blockers.extend(private_blockers)
    elif not existed:
        if private_blockers:
            blockers, observed = private_blockers, None
        else:
            selected_target = install(
                source, binary, lock, args.archive, runtime_descriptor
            )
            blockers = validate_source(source, lock)
            binary_blockers, observed = validate_binary(binary, lock)
            blockers.extend(binary_blockers)
    else:
        selected_target = platform_target()
        blockers = list(source_blockers)
        blockers.extend(private_blockers)
        if private_required and not blockers and runtime_descriptor is not None:
            existing_descriptor = load_runtime_descriptor(binary)
            if existing_descriptor is None:
                if args.check:
                    blockers.append(
                        f"WavePeek private glibc descriptor missing: "
                        f"{runtime_descriptor_path(binary)}"
                    )
                else:
                    write_runtime_descriptor(binary, runtime_descriptor)
            elif existing_descriptor != runtime_descriptor:
                blockers.append("WavePeek private glibc descriptor has drifted")
        if blockers:
            observed = None
        else:
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
        "host_glibc": observed_host_glibc,
        "private_glibc_required": private_required,
        "private_glibc_state": private_state,
        "private_glibc_root": str(private_glibc_root) if private_required else None,
        "runtime_descriptor": (
            str(runtime_descriptor_path(binary)) if runtime_descriptor is not None else None
        ),
        "blockers": blockers,
        "notice": "WavePeek remains an optional, separately licensed source dependency; FSDB is not enabled.",
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"WavePeek dependency: {state}")
        print(f"source: {source}\nbinary: {binary}\ncommit: {lock['commit']}")
        if selected_target in LINUX_LOADERS:
            print(f"host glibc: {observed_host_glibc or 'UNKNOWN'}")
            if private_required:
                print(
                    f"private glibc: {private_state} at {private_glibc_root}"
                )
        for blocker in blockers:
            print(f"ERROR: {blocker}")
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
