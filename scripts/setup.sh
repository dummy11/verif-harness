#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install_verilator=false
runtime=auto
launch_agent=true

usage() {
  echo "usage: $0 [--install-verilator] [--runtime codex|kimi] [--no-agent]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-verilator) install_verilator=true ;;
    --runtime)
      shift
      if [[ $# -eq 0 ]]; then
        usage
        exit 2
      fi
      runtime="$1"
      ;;
    --runtime=*) runtime="${1#*=}" ;;
    --no-agent) launch_agent=false ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
  shift
done

if [[ "$runtime" != "auto" && "$runtime" != "codex" && "$runtime" != "kimi" ]]; then
  echo "ERROR: runtime must be codex or kimi." >&2
  exit 2
fi

agent_cli=""

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
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "ERROR: default setup requires Python 3.11 or newer for Spec Kit and xverif MCP." >&2
  exit 2
}
make --version | head -n 1
python3 "$project_root/scripts/check_structure.py"

python3 "$project_root/scripts/setup_xverif.py" --project-root "$project_root"
python3 "$project_root/scripts/check_xverif.py"
python3 -m pip install --disable-pip-version-check "mcp[cli]"
python3 -c 'import mcp'

python3 "$project_root/scripts/setup_wavepeek.py" --project-root "$project_root"
python3 "$project_root/scripts/check_wavepeek.py"

python3 "$project_root/scripts/setup_spec_kit.py" --project-root "$project_root"
python3 "$project_root/scripts/check_spec_kit.py"

if command -v verilator >/dev/null 2>&1; then
  verilator --version
  echo "Setup PASS: run ./scripts/run_example.sh"
else
  echo "Setup completed without Verilator."
  echo "Run ./scripts/setup.sh --install-verilator or install Verilator 5.x."
fi

if [[ "$launch_agent" != true ]]; then
  echo "Agent launch skipped (--no-agent)."
  echo "Start later with: codex   # or: kimi"
  exit 0
fi

codex_cli="$(command -v codex 2>/dev/null || true)"
kimi_cli="$(command -v kimi 2>/dev/null || command -v kimi-cli 2>/dev/null || true)"
if [[ "$runtime" == "auto" ]]; then
  if [[ -n "$codex_cli" && -z "$kimi_cli" ]]; then
    runtime=codex
  elif [[ -z "$codex_cli" && -n "$kimi_cli" ]]; then
    runtime=kimi
  elif [[ -n "$codex_cli" && -n "$kimi_cli" ]]; then
    echo "ERROR: both Codex and Kimi CLIs are installed; pass --runtime codex or --runtime kimi." >&2
    exit 2
  else
    echo "ERROR: dependencies installed, but no Codex/Kimi CLI was found; install one or rerun with --no-agent." >&2
    exit 2
  fi
fi
if [[ "$runtime" == "codex" ]]; then
  agent_cli="$codex_cli"
else
  agent_cli="$kimi_cli"
fi
if [[ -z "$agent_cli" ]]; then
  echo "ERROR: dependencies installed, but the selected $runtime CLI is not on PATH." >&2
  exit 2
fi

skill_parent="$project_root/.agents/skills"
invocation='$verif-harness'
if [[ "$runtime" == "kimi" ]]; then
  skill_parent="$project_root/.kimi-code/skills"
  invocation='/skill:verif-harness'
fi
skill_link="$skill_parent/verif-harness"
skill_target="../../skills/verif-harness"
mkdir -p "$skill_parent"
if [[ -L "$skill_link" ]]; then
  if [[ "$(readlink "$skill_link")" != "$skill_target" ]]; then
    echo "ERROR: refusing to replace existing runtime Skill link: $skill_link" >&2
    exit 2
  fi
elif [[ -e "$skill_link" ]]; then
  echo "ERROR: refusing to overwrite existing runtime Skill path: $skill_link" >&2
  exit 2
else
  ln -s "$skill_target" "$skill_link"
fi

echo "Setup PASS: Spec Kit, xverif CLI/MCP, and WavePeek are installed."
echo "Starting $runtime CLI in $project_root now."
echo "Inside the Agent CLI, invoke: $invocation"
cd "$project_root"
exec "$agent_cli"
