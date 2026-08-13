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
        "| Test | Verdict | Seed | UVM_ERROR | UVM_FATAL | Golden | Mismatch | Residual |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in results:
        values = [item.test, item.verdict, item.seed, item.uvm_error, item.uvm_fatal,
                  int(item.golden_engaged), item.mismatch_lanes, item.residual_beats]
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
    results = [scrape(test, args.runs_dir / test / args.logname, banner_re, args.require_golden) for test in tests]
    seed_path = args.runs_dir / "batch_seed.txt"
    seed = seed_path.read_text(encoding="utf-8").strip() if seed_path.is_file() else "unknown"
    out = args.out or args.runs_dir / "report.md"
    atomic_write(out, markdown(results, seed, args.require_golden))
    atomic_write(args.runs_dir / "report.json", json.dumps({"seed": seed, "results": [asdict(item) for item in results]}, indent=2) + "\n")
    acceptable = {"PASS"} if args.require_golden else {"PASS", "PASS-LIVE"}
    failed = [item.test for item in results if item.verdict not in acceptable]
    atomic_write(args.runs_dir / "failed.caselist", "".join(f"{name}\n" for name in failed))
    atomic_write(args.runs_dir / "seed.txt", f"{seed}\n")
    print(out)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
