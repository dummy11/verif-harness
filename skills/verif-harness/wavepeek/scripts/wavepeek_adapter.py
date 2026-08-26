#!/usr/bin/env python3
"""Run one reviewed WavePeek CLI request with deterministic evidence capture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


ADAPTER_VERSION = "2"
REQUEST_KEYS = {
    "schema_version", "operation", "arguments", "working_directory",
    "environment_keys", "timeout_seconds", "output_format",
    "acceptable_exit_codes", "expected_artifacts",
}
OPERATIONS = {"version", "info", "scope", "signal", "value", "change", "property", "extract", "schema", "docs", "skill", "help"}
ENV_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
ALLOWED_PLACEHOLDERS = {"project_root", "output_dir", "request_path", "wavepeek_root", "wavepeek_binary"}
SECRET_VALUE = re.compile(r"(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*=|\d+@[^/\s]+")
SHA256 = re.compile(r"[0-9a-f]{64}")
RUNTIME_DESCRIPTOR = "wavepeek-runtime.json"
LIBGCC_LICENSE = "GPL-3.0-or-later WITH GCC-exception-3.1"


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{where} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        fail(f"{where} must remain under project root: {value}")
    return path.as_posix()


def validate_request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != REQUEST_KEYS:
        fail(f"request keys must be exactly {sorted(REQUEST_KEYS)}")
    if value["schema_version"] != 1 or value["operation"] not in OPERATIONS:
        fail(f"schema_version must be 1 and operation one of {sorted(OPERATIONS)}")
    arguments = value["arguments"]
    if not isinstance(arguments, list) or not arguments or not all(isinstance(token, str) and token for token in arguments):
        fail("arguments must be a non-empty string array")
    expected_first = "--version" if value["operation"] == "version" else value["operation"]
    if arguments[0] != expected_first:
        fail(f"arguments[0] must be {expected_first!r} for this operation")
    for token in arguments:
        if any(character in token for character in ("\x00", "\n", "\r")):
            fail("arguments contain a control character")
        unknown = set(PLACEHOLDER.findall(token)) - ALLOWED_PLACEHOLDERS
        if unknown:
            fail(f"unsupported argument placeholders: {sorted(unknown)}")
        if SECRET_VALUE.search(token):
            fail("arguments contain secret-looking material")
    value["working_directory"] = safe_relative(value["working_directory"], "working_directory")
    keys = value["environment_keys"]
    if not isinstance(keys, list) or not all(isinstance(key, str) and ENV_IDENT.fullmatch(key) for key in keys) or len(keys) != len(set(keys)):
        fail("environment_keys must contain unique names only")
    timeout = value["timeout_seconds"]
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 86400:
        fail("timeout_seconds must be an integer in [1, 86400]")
    if value["output_format"] not in {"json", "jsonl", "text"}:
        fail("output_format must be json, jsonl, or text")
    codes = value["acceptable_exit_codes"]
    if not isinstance(codes, list) or not codes or not all(isinstance(code, int) and not isinstance(code, bool) and 0 <= code <= 255 for code in codes) or len(codes) != len(set(codes)):
        fail("acceptable_exit_codes must be unique integers in [0, 255]")
    artifacts = value["expected_artifacts"]
    if not isinstance(artifacts, list):
        fail("expected_artifacts must be a string array")
    value["expected_artifacts"] = [safe_relative(path, f"expected_artifacts[{index}]") for index, path in enumerate(artifacts)]
    if len(artifacts) != len(set(artifacts)):
        fail("expected_artifacts contains duplicates")
    return value


def git_value(root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), *arguments], check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return result.stdout.decode(errors="replace").strip() or None if result.returncode == 0 else None


def sanitized_remote(root: Path) -> str | None:
    remote = git_value(root, "remote", "get-url", "origin")
    if remote is None or "://" not in remote:
        return remote
    parsed = urlsplit(remote)
    host = parsed.hostname
    if host is None:
        return remote
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    if parsed.username:
        netloc = f"<redacted>@{netloc}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def git_dirty(root: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"], check=False,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return bool(result.stdout.strip()) if result.returncode == 0 else None


def resolve_install(project_root: Path, root_arg: Path | None, binary_arg: Path | None) -> tuple[Path, Path]:
    roots = [root_arg] if root_arg else ([Path(os.environ["WAVEPEEK_HOME"])] if "WAVEPEEK_HOME" in os.environ else [project_root / ".deps/wavepeek", Path.cwd() / ".deps/wavepeek", Path(__file__).resolve().parents[4] / ".deps/wavepeek"])
    root = next((item.expanduser().resolve() for item in roots if item is not None and item.expanduser().resolve().is_dir()), None)
    if root is None:
        fail("WavePeek source root not found; run scripts/setup.sh --no-agent, set WAVEPEEK_HOME, or pass --wavepeek-root")
    binaries = [binary_arg] if binary_arg else ([Path(os.environ["WAVEPEEK_BIN"])] if "WAVEPEEK_BIN" in os.environ else [root.parent / "wavepeek-bin/wavepeek"])
    binary = next((item.expanduser().resolve() for item in binaries if item is not None and item.expanduser().resolve().is_file()), None)
    if binary is None:
        fail("WavePeek executable not found; run scripts/setup.sh --no-agent, set WAVEPEEK_BIN, or pass --wavepeek-binary")
    return root, binary


def wavepeek_command(binary: Path) -> tuple[list[str], dict[str, Any] | None]:
    descriptor_path = binary.parent / RUNTIME_DESCRIPTOR
    if not descriptor_path.is_file():
        return [str(binary)], None
    try:
        value = json.loads(descriptor_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read WavePeek runtime descriptor: {exc}")
    keys = {
        "schema_version", "kind", "version", "root", "loader",
        "loader_sha256", "library_dirs", "license", "license_file_sha256",
        "licenses_file_sha256", "libgcc_s", "libgcc_s_sha256",
        "libgcc_license",
    }
    if not isinstance(value, dict) or set(value) != keys:
        fail(f"WavePeek runtime descriptor keys must be exactly {sorted(keys)}")
    version = value["version"]
    library_dirs = value["library_dirs"]
    if (
        value["schema_version"] != 2
        or value["kind"] != "private-glibc"
        or version != "2.34"
        or value["root"] != f"../glibc-{version}"
        or value["license"] != "LGPL-2.1-or-later"
        or not isinstance(value["loader"], str)
        or not isinstance(value["loader_sha256"], str)
        or not SHA256.fullmatch(value["loader_sha256"])
        or value["license_file_sha256"]
        != "dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551"
        or value["licenses_file_sha256"]
        != "b33d0bd9f685b46853548814893a6135e74430d12f6d94ab3eba42fc591f83bc"
        or value["libgcc_license"] != LIBGCC_LICENSE
        or not isinstance(value["libgcc_s"], str)
        or not isinstance(value["libgcc_s_sha256"], str)
        or not SHA256.fullmatch(value["libgcc_s_sha256"])
        or not isinstance(library_dirs, list)
        or not library_dirs
        or not all(isinstance(item, str) and item for item in library_dirs)
    ):
        fail("WavePeek runtime descriptor identity is invalid")
    for raw_path in (value["loader"], value["libgcc_s"], *library_dirs):
        path = Path(raw_path)
        if path.is_absolute() or ".." in path.parts:
            fail("WavePeek runtime descriptor contains an unsafe relative path")
    root = (binary.parent / value["root"]).resolve()
    expected_root = (binary.parent.parent / f"glibc-{version}").resolve()
    if root != expected_root:
        fail("WavePeek private glibc root differs from the managed location")
    loader = (root / value["loader"]).resolve()
    if (
        root not in loader.parents
        or not loader.is_file()
        or not os.access(loader, os.X_OK)
        or sha256_file(loader) != value["loader_sha256"]
    ):
        fail("WavePeek private glibc loader is missing or has drifted")
    libgcc = (root / value["libgcc_s"]).resolve()
    if (
        root not in libgcc.parents
        or not libgcc.is_file()
        or sha256_file(libgcc) != value["libgcc_s_sha256"]
    ):
        fail("WavePeek private libgcc is missing or has drifted")
    resolved_libraries = [(root / relative).resolve() for relative in library_dirs]
    if any(root not in path.parents or not path.is_dir() for path in resolved_libraries):
        fail("WavePeek private glibc library path is missing or unsafe")
    runtime = {
        "kind": value["kind"],
        "version": version,
        "loader": str(loader),
        "loader_sha256": value["loader_sha256"],
        "libgcc_s": str(libgcc),
        "libgcc_s_sha256": value["libgcc_s_sha256"],
        "libgcc_license": value["libgcc_license"],
        "descriptor": str(descriptor_path),
    }
    return [
        str(loader), "--library-path",
        ":".join(str(path) for path in resolved_libraries), str(binary),
    ], runtime


def probe(root: Path, binary: Path) -> dict[str, Any]:
    executable = binary.is_file() and os.access(binary, os.X_OK)
    version = None
    runtime = None
    if executable:
        try:
            command, runtime = wavepeek_command(binary)
            checked = subprocess.run([*command, "--version"], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
            version = checked.stdout.strip() if checked.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            executable = False
    return {
        "adapter_schema_version": 1, "adapter_version": ADAPTER_VERSION,
        "state": "PASS" if executable and version else "TOOL_NOT_FOUND",
        "wavepeek_root": str(root), "binary": str(binary) if binary.is_file() else None,
        "binary_sha256": sha256_file(binary) if binary.is_file() else None,
        "runtime": runtime,
        "version": version, "git_commit": git_value(root, "rev-parse", "HEAD"),
        "git_remote": sanitized_remote(root),
        "git_dirty": git_dirty(root),
        "notice": "PASS proves executable discovery and version only; each operation is checked by run.",
    }


def controlled_environment(keys: list[str], root: Path) -> dict[str, str]:
    missing = [key for key in keys if key not in os.environ]
    if missing:
        fail(f"required environment keys are absent: {missing}")
    environment = {"PATH": os.environ.get("PATH", ""), "LANG": "C", "LC_ALL": "C", "WAVEPEEK_HOME": str(root)}
    for key in keys:
        environment[key] = os.environ[key]
    return environment


def parse_stdout(stdout: bytes, output_format: str) -> tuple[Any, str | None]:
    if output_format == "text":
        return None, None
    try:
        decoded = stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, f"stdout is not UTF-8: {exc}"
    try:
        if output_format == "json":
            return json.loads(decoded), None
        records = [json.loads(line) for line in decoded.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        return None, f"stdout is not valid {output_format}: {exc}"
    if not records or records[0].get("type") != "begin" or records[-1].get("type") != "end":
        return None, "JSONL stream is incomplete (begin/end required)"
    if [record.get("seq") for record in records] != list(range(len(records))):
        return None, "JSONL sequence numbers are not contiguous"
    return records, None


def run_request(project_root: Path, request_path: Path, output_dir: Path, root: Path, binary: Path) -> dict[str, Any]:
    if output_dir.exists():
        fail(f"refusing existing output directory: {output_dir}")
    request_bytes = request_path.read_bytes()
    request = validate_request(json.loads(request_bytes.decode("utf-8")))
    workdir = (project_root / request["working_directory"]).resolve()
    if (workdir != project_root and project_root not in workdir.parents) or not workdir.is_dir():
        fail("working_directory escapes project root or does not exist")
    output_dir.mkdir(parents=True)
    replacements = {"project_root": str(project_root), "output_dir": str(output_dir), "request_path": str(request_path), "wavepeek_root": str(root), "wavepeek_binary": str(binary)}
    arguments = [token.format(**replacements) for token in request["arguments"]]
    identity = probe(root, binary)
    command, _ = wavepeek_command(binary)
    argv = [*command, *arguments]
    blockers: list[str] = []
    if identity["state"] != "PASS":
        stdout, stderr, exit_code, state = b"", b"", None, identity["state"]
        blockers.append(f"tool probe state: {state}")
    else:
        try:
            process = subprocess.run(argv, cwd=workdir, env=controlled_environment(request["environment_keys"], root), check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=request["timeout_seconds"])
            stdout, stderr, exit_code = process.stdout, process.stderr, process.returncode
            state = "PASS" if exit_code in request["acceptable_exit_codes"] else "FAIL"
            if state == "FAIL":
                blockers.append(f"exit code {exit_code} is not accepted")
        except (OSError, subprocess.TimeoutExpired) as exc:
            if isinstance(exc, subprocess.TimeoutExpired):
                stdout, stderr, state = exc.stdout or b"", exc.stderr or b"", "TIMEOUT"
                blockers.append(f"operation exceeded {request['timeout_seconds']} seconds")
            else:
                stdout, stderr, state = b"", str(exc).encode(), "TOOL_ERROR"
                blockers.append(f"cannot execute WavePeek: {exc}")
            exit_code = None
    parsed = None
    if exit_code is not None:
        parsed, protocol_error = parse_stdout(stdout, request["output_format"])
        if protocol_error:
            state = "PROTOCOL_ERROR"
            blockers.append(protocol_error)
    artifacts: list[dict[str, Any]] = []
    artifact_paths = request["expected_artifacts"] if identity["state"] == "PASS" else []
    for relative in artifact_paths:
        path = project_root / relative
        if not path.is_file():
            state = "MISSING_ARTIFACT"
            blockers.append(f"missing expected artifact: {relative}")
        else:
            artifacts.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    atomic_write(output_dir / "stdout.log", stdout)
    atomic_write(output_dir / "stderr.log", stderr)
    result = {
        "adapter_schema_version": 1, "adapter_version": ADAPTER_VERSION,
        "state": state, "operation": request["operation"],
        "request_sha256": sha256_bytes(request_bytes), "tool_identity": identity,
        "argv": argv, "cwd": str(workdir), "environment_keys": request["environment_keys"],
        "exit_code": exit_code, "output_format": request["output_format"],
        "stdout": {"path": "stdout.log", "bytes": len(stdout), "sha256": sha256_bytes(stdout)},
        "stderr": {"path": "stderr.log", "bytes": len(stderr), "sha256": sha256_bytes(stderr)},
        "parsed_stdout": parsed, "artifacts": artifacts, "blockers": blockers,
        "notice": "WavePeek PASS is deterministic waveform-query evidence, not verification approval.",
    }
    atomic_write(output_dir / "result.json", (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("probe", "run"):
        command = commands.add_parser(name)
        command.add_argument("--project-root", type=Path, required=name == "run", default=Path.cwd())
        command.add_argument("--wavepeek-root", type=Path)
        command.add_argument("--wavepeek-binary", type=Path)
        if name == "run":
            command.add_argument("--request", type=Path, required=True)
            command.add_argument("--out-dir", type=Path, required=True)
        else:
            command.add_argument("--out", type=Path)
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    root, binary = resolve_install(project_root, args.wavepeek_root, args.wavepeek_binary)
    if args.command == "probe":
        payload = probe(root, binary)
        output = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.out:
            if args.out.exists():
                fail(f"refusing to overwrite: {args.out}")
            atomic_write(args.out, output.encode())
        else:
            print(output, end="")
        return 0 if payload["state"] == "PASS" else 1
    result = run_request(project_root, args.request.resolve(), args.out_dir.resolve(), root, binary)
    print(args.out_dir / "result.json")
    return 0 if result["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
