#!/usr/bin/env bash
set -euo pipefail

package_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
workspace_root="$package_root"
python_cmd="${VERIF_HARNESS_PYTHON:-python3}"
install_verilator=false
runtime=auto
launch_agent=true

usage() {
  echo "usage: $0 [--workspace-root PATH] [--install-verilator] [--runtime codex|kimi] [--no-agent]" >&2
  echo "       workspace-root receives runtime/spec/workflow files; RTL is selected later in Stage 0." >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace-root|--project-root)
      shift
      if [[ $# -eq 0 ]]; then
        usage
        exit 2
      fi
      workspace_root="$1"
      ;;
    --workspace-root=*|--project-root=*) workspace_root="${1#*=}" ;;
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

if [[ ! -d "$workspace_root" ]]; then
  echo "ERROR: workspace root does not exist or is not a directory: $workspace_root" >&2
  exit 2
fi
workspace_root="$(cd "$workspace_root" && pwd)"
if [[ ! -x "$python_cmd" ]]; then
  if ! command -v "$python_cmd" >/dev/null 2>&1; then
    echo "ERROR: configured Python executable is not available: $python_cmd" >&2
    exit 2
  fi
  python_cmd="$(command -v "$python_cmd")"
fi

if [[ "$runtime" != "auto" && "$runtime" != "codex" && "$runtime" != "kimi" ]]; then
  echo "ERROR: runtime must be codex or kimi." >&2
  exit 2
fi

agent_cli=""
agent_args=()

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

echo "Using Python: $python_cmd"
"$python_cmd" --version
"$python_cmd" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "ERROR: default setup requires Python 3.11 or newer for Spec Kit and xverif MCP." >&2
  exit 2
}
make --version | sed -n '1p'
"$python_cmd" "$package_root/scripts/check_structure.py"

"$python_cmd" "$package_root/scripts/setup_xverif.py" --project-root "$package_root"
"$python_cmd" "$package_root/scripts/check_xverif.py"
"$python_cmd" -m pip install --disable-pip-version-check "mcp[cli]"
"$python_cmd" -c 'import mcp'

"$python_cmd" "$package_root/scripts/setup_wavepeek.py" --project-root "$package_root"
"$python_cmd" "$package_root/scripts/check_wavepeek.py"

"$python_cmd" "$package_root/scripts/setup_spec_kit.py" --project-root "$package_root"
"$python_cmd" "$package_root/scripts/check_spec_kit.py"

if command -v verilator >/dev/null 2>&1; then
  verilator --version
  echo "Setup PASS: run ./scripts/run_example.sh"
else
  echo "Setup completed without Verilator."
  echo "Run ./scripts/setup.sh --install-verilator or install Verilator 5.x."
fi

if [[ "$launch_agent" != true && "$runtime" == "auto" ]]; then
  echo "Setup PASS: managed dependencies are installed under $package_root/.deps."
  echo "Agent launch and target runtime configuration skipped (--no-agent with runtime auto)."
  echo "To configure a target without launching it, pass --runtime codex or --runtime kimi."
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
  elif [[ "$launch_agent" == true ]]; then
    echo "ERROR: dependencies installed, but no Codex/Kimi CLI was found; install one or rerun with --no-agent." >&2
    exit 2
  fi
fi
if [[ "$launch_agent" == true ]]; then
  if [[ "$runtime" == "codex" && -z "$codex_cli" ]]; then
    echo "ERROR: selected codex CLI is not on PATH." >&2
    exit 2
  fi
  if [[ "$runtime" == "kimi" && -z "$kimi_cli" ]]; then
    echo "ERROR: selected kimi CLI is not on PATH." >&2
    exit 2
  fi
fi
if [[ "$runtime" == "codex" ]]; then
  agent_cli="$codex_cli"
  if [[ "$workspace_root" == "$package_root" ]]; then
    if [[ ! -f "$package_root/.codex/config.toml" || ! -f "$package_root/.codex/rules/default.rules" ]]; then
      echo "ERROR: package Codex config is missing: $package_root/.codex/config.toml" >&2
      echo "       Refusing to fall back to global Codex settings." >&2
      exit 2
    fi
  else
    mkdir -p "$workspace_root/.codex/rules"
    if [[ -L "$workspace_root/.codex/config.toml" || -L "$workspace_root/.codex/rules/default.rules" ]]; then
      echo "ERROR: refusing to follow a symlink in project Codex config paths." >&2
      exit 2
    fi
    if [[ ! -e "$workspace_root/.codex/config.toml" ]]; then
      cp "$package_root/.codex/config.toml" "$workspace_root/.codex/config.toml"
      echo "Created workspace Codex config: $workspace_root/.codex/config.toml"
    fi
    if [[ ! -e "$workspace_root/.codex/rules/default.rules" ]]; then
      cp "$package_root/.codex/rules/default.rules" "$workspace_root/.codex/rules/default.rules"
      echo "Created workspace Codex rules: $workspace_root/.codex/rules/default.rules"
    fi
  fi
else
  agent_cli="$kimi_cli"
  # Kimi Code's project-local file currently supports workspace settings only;
  # permission rules remain a host-level Kimi configuration concern.  Do not
  # create or modify ~/.kimi-code/config.toml here.
  if [[ -L "$workspace_root/.kimi-code/local.toml" ]]; then
    echo "ERROR: refusing to follow a symlink at $workspace_root/.kimi-code/local.toml" >&2
    exit 2
  elif [[ -f "$workspace_root/.kimi-code/local.toml" ]]; then
    echo "Using workspace Kimi config: $workspace_root/.kimi-code/local.toml"
  else
    mkdir -p "$workspace_root/.kimi-code"
    printf '%s\n' \
      '# Project-scoped Kimi Code workspace settings for verif-harness.' \
      '# Kimi Code currently accepts workspace options in this file; permission' \
      '# rules are intentionally not duplicated here because they are host-level.' \
      '[workspace]' \
      'additional_dir = []' > "$workspace_root/.kimi-code/local.toml"
    echo "Created workspace Kimi config: $workspace_root/.kimi-code/local.toml"
  fi
  agent_args+=(--yolo)
fi
skill_parent="$workspace_root/.agents/skills"
invocation='$verif-harness'
if [[ "$runtime" == "kimi" ]]; then
  skill_parent="$workspace_root/.kimi-code/skills"
  invocation='/skill:verif-harness'
fi
skill_link="$skill_parent/verif-harness"
if [[ "$workspace_root" == "$package_root" ]]; then
  skill_target="../../skills/verif-harness"
else
  skill_target="$package_root/skills/verif-harness"
fi
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
if [[ "$launch_agent" != true ]]; then
  echo "Agent launch skipped (--no-agent)."
  echo "Workspace configured at: $workspace_root"
  echo "Start later with: (cd \"$workspace_root\" && codex) or (cd \"$workspace_root\" && kimi)"
  exit 0
fi
if [[ ! -d "$workspace_root" ]]; then
  echo "ERROR: workspace disappeared before Agent launch: $workspace_root" >&2
  exit 2
fi
echo "Changing directory to workspace: $workspace_root"
cd "$workspace_root"
echo "Starting $runtime CLI here: $(pwd)"
echo "Inside the Agent CLI, invoke: $invocation"
exec "$agent_cli" "${agent_args[@]}"
