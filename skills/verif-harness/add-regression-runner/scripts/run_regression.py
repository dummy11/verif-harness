#!/usr/bin/env python3
"""Launch isolated planned runs; retain resolved seeds before execution."""

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
    iteration: int = 0


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
            timeout: float | None, command: list[str], iteration: int = 0,
            run_subdir: str | None = None) -> RunResult:
    run_dir = (runs_dir / (run_subdir or test)).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    replacements = {"test": test, "seed": str(seed), "run_dir": str(run_dir),
                    "iteration": str(iteration)}
    argv = [token.format(**replacements) for token in command]
    atomic_write(run_dir / "command.json", json.dumps({"argv": argv, "seed": seed, "test": test,
                                                     "iteration": iteration}, indent=2) + "\n")
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
    return RunResult(test, seed, returncode, round(time.monotonic() - started, 3), timed_out,
                     str(run_dir), iteration)


def planned_runs(tests: list[str], mode: str, repeat: int, seed: int | None) -> list[dict]:
    runs = []
    for test in tests:
        seen: set[int] = set()
        for iteration in range(repeat):
            actual = seed
            if mode == "random":
                actual = resolve_seed("auto", None)
                while actual in seen:
                    actual = resolve_seed("auto", None)
            seen.add(actual)
            runs.append({"test": test, "seed": actual, "iteration": iteration,
                         "run_subdir": test if repeat == 1 else f"{test}/iteration-{iteration:06d}"})
    return runs


def replay_runs(path: Path, tests: list[str]) -> tuple[dict, list[dict]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != "PortableRegressionRunManifest/1":
        raise ValueError("replay manifest has an unsupported schema")
    rows = manifest.get("runs")
    if not isinstance(rows, list) or (not rows and manifest.get("run_kind") != "failure-rerun"):
        raise ValueError("replay manifest must include resolved runs")
    if manifest.get("seed_mode") not in ("fixed", "random"):
        raise ValueError("replay manifest has an unsupported seed mode")
    if manifest.get("run_kind") not in ("planned", "replay", "failure-rerun"):
        raise ValueError("replay manifest has an unsupported run kind")
    repeat = manifest.get("repeat")
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
        raise ValueError("replay repeat must be a positive integer")
    selected = []
    keys = set()
    fixed_seeds = set()
    case_seeds: dict[str, set[int]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("replay run must be an object")
        test = row.get("test")
        if not isinstance(test, str) or not re.fullmatch(r"[A-Za-z_]\w*", test):
            raise ValueError("replay manifest has an unsafe test name")
        if test not in tests:
            continue
        iteration = row.get("iteration")
        if isinstance(iteration, bool) or not isinstance(iteration, int) or not 0 <= iteration < repeat:
            raise ValueError("replay iteration must be a non-negative integer")
        raw_seed = row.get("seed")
        if isinstance(raw_seed, bool) or not isinstance(raw_seed, (int, str)) or str(raw_seed) in {"auto", ""}:
            raise ValueError("replay requires a resolved seed")
        actual = resolve_seed(str(raw_seed), None)
        fixed_seeds.add(actual)
        seen_seeds = case_seeds.setdefault(test, set())
        if manifest["seed_mode"] == "random" and actual in seen_seeds:
            raise ValueError("random replay repeats a seed for the same case")
        seen_seeds.add(actual)
        key = (test, iteration)
        if key in keys:
            raise ValueError("replay manifest contains duplicate planned runs")
        keys.add(key)
        selected.append({"test": test, "iteration": iteration, "seed": actual,
                         "run_subdir": f"{test}/iteration-{iteration:06d}"})
    if manifest["seed_mode"] == "fixed" and len(fixed_seeds) > 1:
        raise ValueError("fixed replay must use one specified seed")
    if {row["test"] for row in selected} != set(tests):
        raise ValueError("replay manifest does not cover the selected caselist")
    if manifest.get("run_kind") != "failure-rerun" and any(
            sum(row["test"] == test for row in selected) != repeat for test in tests):
        raise ValueError("planned manifest does not cover every repeat iteration")
    return manifest, selected


def claim_output_directory(path: Path) -> None:
    """Atomically claim a fresh directory; retain the claim with its history."""
    path.mkdir(parents=True, exist_ok=True)
    claim = path / ".run-claim"
    try:
        claim.mkdir()
    except FileExistsError as exc:
        raise ValueError("runs directory is already claimed; use a new directory") from exc
    if any(entry != claim for entry in path.iterdir()):
        raise ValueError("historical results are never overwritten; use a new empty directory")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caselist", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--seed", default="auto")
    parser.add_argument("--seed-file", type=Path)
    parser.add_argument("--seed-mode", choices=["fixed", "random"], default="fixed")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--replay-manifest", type=Path,
                        help="replay resolved runs, including failed-runs.json, with original seeds")
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
    if not tests and not args.replay_manifest:
        raise SystemExit("ERROR: caselist is empty")
    if len(tests) != len(set(tests)):
        raise SystemExit("ERROR: caselist contains duplicate test names")
    if args.repeat < 1:
        raise SystemExit("ERROR: repeat must be at least 1")
    if args.runs_dir.exists() and any(args.runs_dir.iterdir()):
        raise SystemExit("ERROR: use a new empty runs directory; historical results are never overwritten")
    if args.replay_manifest:
        if args.seed != "auto" or args.seed_file or args.seed_mode != "fixed" or args.repeat != 1:
            raise SystemExit("ERROR: replay cannot override seed mode, seed or repeat")
        original, runs = replay_runs(args.replay_manifest, tests)
        mode, repeat, seed = original.get("seed_mode"), original.get("repeat"), None
        run_kind = "failure-rerun" if original.get("run_kind") == "failure-rerun" else "replay"
    else:
        if args.seed_mode == "random" and (args.seed != "auto" or args.seed_file):
            raise SystemExit("ERROR: random seed mode cannot also specify a seed")
        mode, repeat = args.seed_mode, args.repeat
        seed = resolve_seed(args.seed, args.seed_file) if mode == "fixed" else None
        runs = planned_runs(tests, mode, repeat, seed)
        run_kind = "planned"
    try:
        claim_output_directory(args.runs_dir)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    # This portable launcher manifest is not control-plane evidence. The
    # testbench adapter separately binds it to the approved group and round.
    manifest = {"schema": "PortableRegressionRunManifest/1", "seed_mode": mode,
                "repeat": repeat, "tests": tests, "run_kind": run_kind, "runs": runs}
    atomic_write(args.runs_dir / "run_manifest.json", json.dumps(manifest, indent=2) + "\n")
    if seed is not None:
        atomic_write(args.runs_dir / "batch_seed.txt", f"{seed}\n")
    results: list[RunResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(run_one, row["test"], row["seed"], args.runs_dir, args.logname,
                               args.timeout, command, row["iteration"], row["run_subdir"]) for row in runs]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"{result.test}: rc={result.returncode} elapsed={result.elapsed_seconds}s")
    results.sort(key=lambda item: (tests.index(item.test), item.iteration))
    atomic_write(args.runs_dir / "batch.json", json.dumps({
        "seed": seed,
        "seed_mode": mode, "repeat": repeat, "run_kind": run_kind,
        "tests": tests,
        "results": [asdict(item) for item in results],
    }, indent=2) + "\n")
    return 1 if args.fail_on_command_error and any(item.returncode != 0 for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
