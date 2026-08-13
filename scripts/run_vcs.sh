#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
filelist="${1:-}"
top="${2:-}"

if [[ -z "$filelist" || -z "$top" ]]; then
  echo "usage: $0 <project-root-relative-filelist> <top-module> [runtime args...]" >&2
  exit 2
fi
shift 2

if ! command -v vcs >/dev/null 2>&1; then
  echo "ERROR: vcs is not available in PATH; installation and licensing are user-managed." >&2
  exit 2
fi

case "$filelist" in
  /*|*..*)
    echo "ERROR: filelist must remain inside the project root." >&2
    exit 2
    ;;
esac

build_dir="$project_root/build/vcs/$top"
mkdir -p "$build_dir"
cd "$project_root"
vcs -full64 -sverilog -ntb_opts uvm-1.2 -f "$filelist" -top "$top" \
  -o "$build_dir/simv"
"$build_dir/simv" "$@"
