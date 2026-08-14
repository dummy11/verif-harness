#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install_verilator=false
with_xverif=false

for argument in "$@"; do
  case "$argument" in
    --install-verilator) install_verilator=true ;;
    --with-xverif) with_xverif=true ;;
    *)
      echo "usage: $0 [--install-verilator] [--with-xverif]" >&2
      exit 2
      ;;
  esac
done

if [[ "$install_verilator" == true ]] && ! command -v verilator >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install verilator
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y verilator
  else
    echo "ERROR: automatic Verilator installation supports Homebrew or apt." >&2
    exit 2
  fi
fi

python3 --version
make --version | head -n 1
python3 "$project_root/scripts/check_structure.py"

if [[ "$with_xverif" == true ]]; then
  python3 "$project_root/scripts/setup_xverif.py" --project-root "$project_root"
  python3 "$project_root/scripts/check_xverif.py"
fi

if command -v verilator >/dev/null 2>&1; then
  verilator --version
  echo "Setup PASS: run ./scripts/run_example.sh"
else
  echo "Setup completed without Verilator."
  echo "Run ./scripts/setup.sh --install-verilator or install Verilator 5.x."
fi

if [[ "$with_xverif" != true ]]; then
  echo "Optional xverif setup: ./scripts/setup.sh --with-xverif"
fi
