#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="$project_root/build/simple_fifo"

if ! command -v verilator >/dev/null 2>&1; then
  echo "ERROR: Verilator 5.x is required for the executable example." >&2
  echo "See docs/tool_versions.md for installation guidance." >&2
  exit 2
fi

mkdir -p "$build_dir"
cd "$project_root"
verilator \
  -f filelists/sim_options.f \
  -f examples/simple_fifo/filelists/simple_fifo.f \
  --Mdir "$build_dir/obj_dir" \
  -o simple_fifo_smoke

"$build_dir/obj_dir/simple_fifo_smoke" | tee "$build_dir/run.log"
grep -Fq "SIMPLE_FIFO_SMOKE PASS" "$build_dir/run.log"
