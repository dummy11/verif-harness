#!/usr/bin/env python3
"""Run one reviewed xverif CLI request with deterministic evidence capture."""

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


ADAPTER_VERSION = "1"
TOOLS = {"xbit", "xentry", "xloc", "xsva", "xcov", "xdebug", "xwaveform"}
REQUEST_KEYS = {
    "schema_version", "tool", "operation", "arguments", "stdin_path",
    "working_directory", "environment_keys", "timeout_seconds", "output_format",
    "acceptable_exit_codes", "expected_artifacts",
}
IDENT = re.compile(r"[a-z][a-z0-9._-]*")
ENV_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
ALLOWED_PLACEHOLDERS = {"project_root", "output_dir", "request_path", "xverif_root"}
SECRET_VALUE = re.compile(
    r"(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*=|\d+@[^/\s]+"
)


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
    if value["schema_version"] != 1:
        fail("schema_version must be 1")
    if value["tool"] not in TOOLS:
        fail(f"tool must be one of {sorted(TOOLS)}")
    if not isinstance(value["operation"], str) or not IDENT.fullmatch(value["operation"]):
        fail("operation must match [a-z][a-z0-9._-]*")
    arguments = value["arguments"]
    if not isinstance(arguments, list) or not all(
        isinstance(token, str) and token for token in arguments
    ):
        fail("arguments must be a string array")
    for token in arguments:
        if any(character in token for character in ("\x00", "\n", "\r")):
            fail("arguments contain a control character")
        unknown = set(PLACEHOLDER.findall(token)) - ALLOWED_PLACEHOLDERS
        if unknown:
            fail(f"unsupported argument placeholders: {sorted(unknown)}")
        if SECRET_VALUE.search(token):
            fail("arguments contain secret-looking material")
    stdin_path = value["stdin_path"]
    if stdin_path is not None:
        value["stdin_path"] = safe_relative(stdin_path, "stdin_path")
    value["working_directory"] = safe_relative(value["working_directory"], "working_directory")
    env_keys = value["environment_keys"]
    if not isinstance(env_keys, list) or not all(
        isinstance(key, str) and ENV_IDENT.fullmatch(key) for key in env_keys
    ):
        fail("environment_keys must contain names only")
    if len(env_keys) != len(set(env_keys)):
        fail("environment_keys contains duplicates")
    timeout = value["timeout_seconds"]
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 86400:
        fail("timeout_seconds must be an integer in [1, 86400]")
    if value["output_format"] not in {"json", "xout", "text"}:
        fail("output_format must be json, xout, or text")
    codes = value["acceptable_exit_codes"]
    if not isinstance(codes, list) or not codes or not all(
        isinstance(code, int) and not isinstance(code, bool) and 0 <= code <= 255 for code in codes
    ):
        fail("acceptable_exit_codes must be a non-empty integer array in [0, 255]")
    if len(codes) != len(set(codes)):
        fail("acceptable_exit_codes contains duplicates")
    artifacts = value["expected_artifacts"]
    if not isinstance(artifacts, list):
        fail("expected_artifacts must be a string array")
    value["expected_artifacts"] = [
        safe_relative(path, f"expected_artifacts[{index}]")
        for index, path in enumerate(artifacts)
    ]
    if len(artifacts) != len(set(artifacts)):
        fail("expected_artifacts contains duplicates")
    return value


def git_value(root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments], check=False,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace").strip() or None


def git_dirty(root: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"], check=False,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def sanitized_remote(root: Path) -> str | None:
    remote = git_value(root, "remote", "get-url", "origin")
    if remote is None or "://" not in remote:
        return remote
    parsed = urlsplit(remote)
    hostname = parsed.hostname
    if hostname is None:
        return remote
    netloc = hostname
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    if parsed.username is not None:
        netloc = f"<redacted>@{netloc}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def probe(root: Path, tool: str) -> dict[str, Any]:
    wrapper = root / "tools" / tool
    state = "PASS" if wrapper.is_file() and os.access(wrapper, os.X_OK) else "TOOL_NOT_FOUND"
    return {
        "adapter_schema_version": 1,
        "adapter_version": ADAPTER_VERSION,
        "state": state,
        "tool": tool,
        "xverif_root": str(root),
        "wrapper": str(wrapper) if wrapper.is_file() else None,
        "wrapper_sha256": sha256_file(wrapper) if wrapper.is_file() else None,
        "git_commit": git_value(root, "rev-parse", "HEAD"),
        "git_remote": sanitized_remote(root),
        "git_dirty": git_dirty(root),
        "notice": "PASS proves wrapper discovery only; runtime capability is checked by run.",
    }


def controlled_environment(keys: list[str], xverif_root: Path) -> dict[str, str]:
    missing = [key for key in keys if key not in os.environ]
    if missing:
        fail(f"required environment keys are absent: {missing}")
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONHASHSEED": "0",
        "XVERIF_HOME": str(xverif_root),
    }
    for key in keys:
        environment[key] = os.environ[key]
    return environment


def expand_arguments(arguments: list[str], replacements: dict[str, str]) -> list[str]:
    return [token.format(**replacements) for token in arguments]


def artifact_evidence(root: Path, paths: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    evidence, missing = [], []
    for relative in paths:
        path = root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        evidence.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return evidence, missing


def parse_output(stdout: bytes, output_format: str) -> tuple[Any, str | None]:
    if output_format == "text":
        return None, None
    decoded = stdout.decode("utf-8", errors="strict")
    if output_format == "json":
        try:
            return json.loads(decoded), None
        except json.JSONDecodeError as exc:
            return None, f"stdout is not valid JSON: {exc}"
    first = next((line for line in decoded.splitlines() if line.strip()), "")
    if not first.startswith("@"):
        return None, "stdout is not canonical XOUT (missing @ header)"
    return None, None


def run_request(
    project_root: Path, request_path: Path, output_dir: Path, xverif_root: Path
) -> dict[str, Any]:
    if output_dir.exists():
        fail(f"refusing existing output directory: {output_dir}")
    if not project_root.is_dir():
        fail(f"project root does not exist: {project_root}")
    request_bytes = request_path.read_bytes()
    request = validate_request(json.loads(request_bytes.decode("utf-8")))
    workdir = (project_root / request["working_directory"]).resolve()
    if project_root != workdir and project_root not in workdir.parents:
        fail("working_directory escapes project root")
    if not workdir.is_dir():
        fail(f"working_directory does not exist: {workdir}")
    stdin_bytes = None
    stdin_evidence = None
    if request["stdin_path"] is not None:
        stdin_file = project_root / request["stdin_path"]
        if not stdin_file.is_file():
            fail(f"stdin_path does not exist: {stdin_file}")
        stdin_bytes = stdin_file.read_bytes()
        stdin_evidence = {
            "path": request["stdin_path"], "bytes": len(stdin_bytes),
            "sha256": sha256_bytes(stdin_bytes),
        }
    tool = probe(xverif_root, request["tool"])
    output_dir.mkdir(parents=True)
    stdout_path, stderr_path = output_dir / "stdout.log", output_dir / "stderr.log"
    replacements = {
        "project_root": str(project_root), "output_dir": str(output_dir.resolve()),
        "request_path": str(request_path.resolve()), "xverif_root": str(xverif_root),
    }
    arguments = expand_arguments(request["arguments"], replacements)
    argv = [tool["wrapper"], *arguments] if tool["wrapper"] else []
    blockers: list[str] = []
    if tool["state"] != "PASS":
        stdout = stderr = b""
        exit_code = None
        state = tool["state"]
        parsed_stdout = None
        artifacts: list[dict[str, Any]] = []
        blockers.append(f"tool probe state: {state}")
    else:
        try:
            process = subprocess.run(
                argv, cwd=workdir, env=controlled_environment(request["environment_keys"], xverif_root),
                input=stdin_bytes, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=request["timeout_seconds"],
            )
            stdout, stderr, exit_code = process.stdout, process.stderr, process.returncode
            state = "PASS" if exit_code in request["acceptable_exit_codes"] else "FAIL"
            if state == "FAIL":
                blockers.append(f"exit code {exit_code} is not accepted")
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = exc.stdout or b"", exc.stderr or b""
            exit_code, state = None, "TIMEOUT"
            blockers.append(f"operation exceeded {request['timeout_seconds']} seconds")
        parsed_stdout = None
        if state != "TIMEOUT":
            try:
                parsed_stdout, protocol_error = parse_output(stdout, request["output_format"])
            except UnicodeDecodeError as exc:
                protocol_error = f"stdout is not UTF-8: {exc}"
            if protocol_error is not None:
                state = "PROTOCOL_ERROR"
                blockers.append(protocol_error)
        artifacts, missing = artifact_evidence(project_root, request["expected_artifacts"])
        if missing:
            state = "MISSING_ARTIFACT"
            blockers.extend(f"missing expected artifact: {path}" for path in missing)
    atomic_write(stdout_path, stdout)
    atomic_write(stderr_path, stderr)
    result = {
        "adapter_schema_version": 1,
        "adapter_version": ADAPTER_VERSION,
        "state": state,
        "tool": request["tool"],
        "operation": request["operation"],
        "request_sha256": sha256_bytes(request_bytes),
        "tool_identity": tool,
        "argv": argv,
        "cwd": str(workdir),
        "environment_keys": request["environment_keys"],
        "stdin": stdin_evidence,
        "exit_code": exit_code,
        "output_format": request["output_format"],
        "stdout": {"path": "stdout.log", "bytes": len(stdout), "sha256": sha256_bytes(stdout)},
        "stderr": {"path": "stderr.log", "bytes": len(stderr), "sha256": sha256_bytes(stderr)},
        "parsed_stdout": parsed_stdout,
        "artifacts": artifacts,
        "blockers": blockers,
        "notice": "CLI PASS is deterministic operation evidence, not verification approval.",
    }
    atomic_write(
        output_dir / "result.json",
        (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return result


def xverif_root_argument(value: Path | None) -> Path:
    raw = value or (Path(os.environ["XVERIF_HOME"]) if "XVERIF_HOME" in os.environ else None)
    if raw is None:
        fail("set XVERIF_HOME or pass --xverif-root")
    root = raw.expanduser().resolve()
    if not root.is_dir():
        fail(f"xverif root does not exist: {root}")
    return root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    probe_parser = commands.add_parser("probe")
    probe_parser.add_argument("--xverif-root", type=Path)
    probe_parser.add_argument("--tool", choices=sorted(TOOLS), required=True)
    probe_parser.add_argument("--out", type=Path)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--project-root", type=Path, required=True)
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--xverif-root", type=Path)
    run_parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    root = xverif_root_argument(args.xverif_root)
    if args.command == "probe":
        payload = probe(root, args.tool)
        output = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.out:
            if args.out.exists():
                fail(f"refusing to overwrite: {args.out}")
            atomic_write(args.out, output.encode("utf-8"))
        else:
            print(output, end="")
        return 0 if payload["state"] == "PASS" else 1
    result = run_request(
        args.project_root.resolve(), args.request.resolve(), args.out_dir.resolve(), root
    )
    print(args.out_dir / "result.json")
    return 0 if result["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
