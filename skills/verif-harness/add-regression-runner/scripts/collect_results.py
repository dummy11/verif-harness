#!/usr/bin/env python3
"""Collect harness regression logs into Markdown, JSON, and rerun sidecars."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path


COUNTS_RE = re.compile(r"UVM_ERROR=(\d+)\s+UVM_FATAL=(\d+)")
GOLDEN_RE = re.compile(r"SUMMARY:\s*cfg_events=(\d+)\s+supported_seen=(\d+)\s+mismatch_lanes=(\d+)\s+residual_beats=(\d+)")
SEED_RE = re.compile(r"ntb_random_seed\s*=\s*(\d+)")


@dataclass
class Result:
    test: str
    verdict: str
    seed: int | None
    uvm_error: int | None
    uvm_fatal: int | None
    golden_engaged: bool
    supported_seen: int | None
    mismatch_lanes: int | None
    residual_beats: int | None
    log: str
    iteration: int = 0
    returncode: int | None = None
    timed_out: bool = False


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def tests_from(path: Path) -> list[str]:
    result: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if value:
            test = value.split()[0]
            if not re.fullmatch(r"[A-Za-z_]\w*", test):
                raise ValueError(f"unsafe test name in caselist: {test}")
            result.append(test)
    return result


def scrape(test: str, log: Path, banner_re: re.Pattern[str], require_golden: bool) -> Result:
    if not log.is_file():
        return Result(test, "NOLOG", None, None, None, False, None, None, None, str(log))
    text = log.read_text(encoding="latin-1", errors="replace")
    banners = list(banner_re.finditer(text))
    counts = COUNTS_RE.search(text)
    golden = GOLDEN_RE.search(text)
    seed_match = SEED_RE.search(text)
    verdict = "CRASH"
    if banners:
        banner = banners[-1].group(2)
        if banner == "FAILED":
            verdict = "FAIL"
        elif golden:
            supported = int(golden.group(2))
            mismatch = int(golden.group(3))
            residual = int(golden.group(4))
            if supported == 0:
                verdict = "NO-COMPARE"
            elif mismatch == 0 and residual == 0:
                verdict = "PASS"
            else:
                verdict = "FAIL"
        else:
            verdict = "NO-COMPARE" if require_golden else "PASS-LIVE"
        if banners[-1].group(1) != test or (counts and any(int(counts.group(i)) for i in (1, 2))):
            verdict = "FAIL"
    return Result(
        test=test,
        verdict=verdict,
        seed=int(seed_match.group(1)) if seed_match else None,
        uvm_error=int(counts.group(1)) if counts else None,
        uvm_fatal=int(counts.group(2)) if counts else None,
        golden_engaged=bool(golden),
        supported_seen=int(golden.group(2)) if golden else None,
        mismatch_lanes=int(golden.group(3)) if golden else None,
        residual_beats=int(golden.group(4)) if golden else None,
        log=str(log),
    )


def markdown(results: list[Result], seed: str, require_golden: bool) -> str:
    lines = [
        "# Regression Report", "",
        f"- Seed: `{seed}`",
        f"- Golden required: `{int(require_golden)}`",
        "",
        "| Test | Verdict | Seed | UVM_ERROR | UVM_FATAL | Golden | Mismatch | Residual | Iteration | Returncode | Timeout |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in results:
        values = [item.test, item.verdict, item.seed, item.uvm_error, item.uvm_fatal,
                  int(item.golden_engaged), item.mismatch_lanes, item.residual_beats,
                  item.iteration, item.returncode, int(item.timed_out)]
        lines.append("| " + " | ".join("-" if value is None else str(value) for value in values) + " |")
    passing = sum(item.verdict in ({"PASS"} if require_golden else {"PASS", "PASS-LIVE"}) for item in results)
    lines.extend(["", f"Result: **{passing}/{len(results)} acceptable**.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--caselist", type=Path, required=True)
    parser.add_argument("--result-prefix", required=True)
    parser.add_argument("--result-regex")
    parser.add_argument("--require-golden", action="store_true")
    parser.add_argument("--logname", default="run.log")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    tests = tests_from(args.caselist)
    if len(tests) != len(set(tests)):
        raise SystemExit("ERROR: caselist contains duplicate test names")
    if args.result_regex:
        banner_re = re.compile(args.result_regex)
    else:
        banner_re = re.compile(rf"{re.escape(args.result_prefix)}\s+(\S+)\s*:\s*(PASSED|FAILED)")
    run_manifest_path = args.runs_dir / "run_manifest.json"
    if not tests and not run_manifest_path.is_file():
        raise SystemExit("ERROR: empty caselist is allowed only for a resolved failure-rerun manifest")
    run_manifest = None
    failed_runs = []
    if run_manifest_path.is_file():
        # Validate paths and resolved seeds using the same portable infrastructure
        # helper, not a second control-plane interpretation of submit settings.
        from run_regression import replay_runs
        run_manifest, planned = replay_runs(run_manifest_path, tests)
        results = []
        batch_path = args.runs_dir / "batch.json"
        observed = {}
        if batch_path.is_file():
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
            for execution in batch.get("results", []):
                key = (execution.get("test"), execution.get("iteration"))
                if key in observed:
                    raise SystemExit("ERROR: batch receipt contains duplicate runs")
                observed[key] = execution
        original_by_key = {(row["test"], row["iteration"]): row for row in run_manifest["runs"]}
        for row in planned:
            original = original_by_key[(row["test"], row["iteration"])]
            subdir = Path(original["run_subdir"])
            if subdir.is_absolute() or ".." in subdir.parts:
                raise SystemExit("ERROR: run manifest references an unsafe run directory")
            item = scrape(row["test"], args.runs_dir / subdir / args.logname, banner_re, args.require_golden)
            item.iteration = row["iteration"]
            execution = observed.get((row["test"], row["iteration"]))
            if execution is None:
                item.verdict = "CRASH" if item.verdict != "NOLOG" else "NOLOG"
            else:
                item.returncode = execution.get("returncode")
                item.timed_out = execution.get("timed_out", False)
                if (isinstance(item.returncode, bool) or not isinstance(item.returncode, int)
                        or not isinstance(item.timed_out, bool) or execution.get("seed") != row["seed"]
                        or item.returncode != 0 or item.timed_out):
                    item.verdict = "FAIL"
            if item.seed is not None and item.seed != row["seed"]:
                item.verdict = "FAIL"
            item.seed = row["seed"]
            results.append(item)
            acceptable = {"PASS"} if args.require_golden else {"PASS", "PASS-LIVE"}
            if item.verdict not in acceptable:
                failed_runs.append(row)
        if set(observed) - {(row["test"], row["iteration"]) for row in planned}:
            raise SystemExit("ERROR: batch receipt contains execution outside the selected manifest")
    else:
        results = [scrape(test, args.runs_dir / test / args.logname, banner_re, args.require_golden) for test in tests]
    seed_path = args.runs_dir / "batch_seed.txt"
    seed = seed_path.read_text(encoding="utf-8").strip() if seed_path.is_file() else "unknown"
    if run_manifest is not None and run_manifest["seed_mode"] == "random":
        seed = "per-run; see resolved run manifest"
    out = args.out or args.runs_dir / "report.md"
    atomic_write(out, markdown(results, seed, args.require_golden))
    atomic_write(args.runs_dir / "report.json", json.dumps({"seed": seed, "results": [asdict(item) for item in results]}, indent=2) + "\n")
    acceptable = {"PASS"} if args.require_golden else {"PASS", "PASS-LIVE"}
    failed = list(dict.fromkeys(item.test for item in results if item.verdict not in acceptable))
    atomic_write(args.runs_dir / "failed.caselist", "".join(f"{name}\n" for name in failed))
    atomic_write(args.runs_dir / "seed.txt", f"{seed}\n")
    if run_manifest is not None:
        atomic_write(args.runs_dir / "failed-runs.json", json.dumps({
            "schema": "PortableRegressionRunManifest/1", "seed_mode": run_manifest["seed_mode"],
            "repeat": run_manifest["repeat"], "run_kind": "failure-rerun",
            "tests": failed, "runs": failed_runs,
        }, indent=2) + "\n")
    print(out)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
