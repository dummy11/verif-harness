#!/usr/bin/env python3
"""Launch isolated regression jobs with one reproducible batch seed."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import secrets
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class RunResult:
    test: str
    seed: int
    returncode: int
    elapsed_seconds: float
    timed_out: bool
    run_dir: str


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def tests_from(path: Path) -> list[str]:
    tests: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if value:
            test = value.split()[0]
            if not re.fullmatch(r"[A-Za-z_]\w*", test):
                raise ValueError(f"unsafe test name in caselist: {test}")
            tests.append(test)
    return tests


def resolve_seed(value: str | None, seed_file: Path | None) -> int:
    if seed_file:
        value = seed_file.read_text(encoding="utf-8").strip()
    if value in {None, "", "auto"}:
        return secrets.randbelow(2_147_483_646) + 1
    seed = int(value)
    if not 1 <= seed <= 2_147_483_647:
        raise ValueError("seed must be in [1, 2147483647]")
    return seed


def run_one(test: str, seed: int, runs_dir: Path, logname: str,
            timeout: float | None, command: list[str]) -> RunResult:
    run_dir = (runs_dir / test).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    replacements = {"test": test, "seed": str(seed), "run_dir": str(run_dir)}
    argv = [token.format(**replacements) for token in command]
    atomic_write(run_dir / "command.json", json.dumps({"argv": argv, "seed": seed, "test": test}, indent=2) + "\n")
    started = time.monotonic()
    timed_out = False
    with (run_dir / logname).open("wb") as log:
        try:
            result = subprocess.run(argv, cwd=run_dir, stdout=log, stderr=subprocess.STDOUT,
                                    check=False, timeout=timeout)
            returncode = result.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = 124
    return RunResult(test, seed, returncode, round(time.monotonic() - started, 3), timed_out, str(run_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caselist", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--seed", default="auto")
    parser.add_argument("--seed-file", type=Path)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--logname", default="run.log")
    parser.add_argument("--fail-on-command-error", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise SystemExit("ERROR: provide simulator command after --")
    if not any("{test}" in token for token in command) or not any("{seed}" in token for token in command):
        raise SystemExit("ERROR: command must contain {test} and {seed} placeholders")
    tests = tests_from(args.caselist)
    if not tests:
        raise SystemExit("ERROR: caselist is empty")
    if len(tests) != len(set(tests)):
        raise SystemExit("ERROR: caselist contains duplicate test names")
    seed = resolve_seed(args.seed, args.seed_file)
    args.runs_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(args.runs_dir / "batch_seed.txt", f"{seed}\n")
    results: list[RunResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(run_one, test, seed, args.runs_dir, args.logname,
                               args.timeout, command) for test in tests]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"{result.test}: rc={result.returncode} elapsed={result.elapsed_seconds}s")
    results.sort(key=lambda item: tests.index(item.test))
    atomic_write(args.runs_dir / "batch.json", json.dumps({
        "seed": seed,
        "tests": tests,
        "results": [asdict(item) for item in results],
    }, indent=2) + "\n")
    return 1 if args.fail_on_command_error and any(item.returncode != 0 for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
