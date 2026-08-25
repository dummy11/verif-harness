#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
check_only=false

usage() {
  echo "usage: $0 [--project-root PATH] [--check]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      shift
      [[ $# -gt 0 ]] || { usage; exit 2; }
      project_root="$1"
      ;;
    --project-root=*) project_root="${1#*=}" ;;
    --check) check_only=true ;;
    --help|-h) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
  shift
done

[[ -d "$project_root" ]] || {
  echo "ERROR: project root does not exist: $project_root" >&2
  exit 2
}
project_root="$(cd "$project_root" && pwd)"

python_version="3.12.11"
python_release="20251007"
case "$(uname -s):$(uname -m)" in
  Darwin:arm64|Darwin:aarch64)
    target="aarch64-apple-darwin"
    archive_sha256="407fa242942a7ba5d91899abc562fc9897f7a0376f8d2060285e8c0560323f19"
    ;;
  Darwin:x86_64|Darwin:amd64)
    target="x86_64-apple-darwin"
    archive_sha256="e0578395f02bb6ac61a0df0f9e280f0317bbb46d8bed66232b3aa9a1477256f8"
    ;;
  Linux:aarch64|Linux:arm64)
    target="aarch64-unknown-linux-gnu"
    archive_sha256="05d9207e41c36fbc2d80a51d9bd5d574ed3eb1c620ead49e7fcd57cc2b64edfd"
    ;;
  Linux:x86_64|Linux:amd64)
    target="x86_64-unknown-linux-gnu"
    archive_sha256="f98121eb1fb2b05a25c1f3d2fe7cf08c3a2468c350785df3d84c2516e7280d3f"
    ;;
  *)
    echo "ERROR: managed runtime has no reviewed asset for $(uname -s)/$(uname -m)." >&2
    exit 2
    ;;
esac

archive="cpython-${python_version}+${python_release}-${target}-install_only_stripped.tar.gz"
url="https://github.com/astral-sh/python-build-standalone/releases/download/${python_release}/${archive//+/%2B}"
runtime_root="$project_root/.deps/runtime"
install_root="$runtime_root/cpython-${python_version}-${target}"
base_python="$install_root/bin/python3"

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "ERROR: managed bootstrap requires sha256sum or shasum." >&2
    exit 2
  fi
}

download_file() {
  if command -v curl >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -fL --retry 2 --output "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$2" "$1"
  else
    echo "ERROR: managed bootstrap requires curl or wget." >&2
    exit 2
  fi
}

for required in awk bash cp dirname git ln mkdir mv readlink rm tar uname; do
  command -v "$required" >/dev/null 2>&1 || {
    echo "ERROR: managed bootstrap host command is missing: $required" >&2
    exit 2
  }
done

if [[ ! -e "$install_root" ]]; then
  if [[ "$check_only" == true ]]; then
    echo "ERROR: managed CPython is missing: $install_root" >&2
    exit 1
  fi
  mkdir -p "$runtime_root"
  temporary="$runtime_root/.cpython.install-$$"
  [[ ! -e "$temporary" ]] || {
    echo "ERROR: managed CPython temporary path already exists: $temporary" >&2
    exit 2
  }
  mkdir "$temporary"
  cleanup() {
    if [[ -d "$temporary" ]]; then
      rm -rf -- "$temporary"
    fi
  }
  trap cleanup EXIT
  echo "Installing managed CPython $python_version for $target." >&2
  download_file "$url" "$temporary/$archive"
  observed_sha256="$(sha256_file "$temporary/$archive")"
  if [[ "$observed_sha256" != "$archive_sha256" ]]; then
    echo "ERROR: managed CPython archive SHA-256 does not match runtime lock." >&2
    exit 2
  fi
  tar -tzf "$temporary/$archive" >/dev/null
  if tar -tzf "$temporary/$archive" | awk '
    /^\// || /(^|\/)\.\.($|\/)/ { unsafe=1 }
    $0 !~ /^python\// { unsafe=1 }
    END { exit unsafe ? 0 : 1 }
  '; then
    echo "ERROR: managed CPython archive contains an unsafe path." >&2
    exit 2
  fi
  tar -xzf "$temporary/$archive" -C "$temporary"
  [[ -x "$temporary/python/bin/python3" ]] || {
    echo "ERROR: managed CPython archive lacks python/bin/python3." >&2
    exit 2
  }
  mv "$temporary/python" "$install_root"
  trap - EXIT
  cleanup
fi

[[ -x "$base_python" ]] || {
  echo "ERROR: managed CPython install is partial or not executable: $base_python" >&2
  exit 2
}

runtime_args=(
  --project-root "$project_root"
  --base-python "$base_python"
  --platform "$target"
)
if [[ "$check_only" == true ]]; then
  runtime_args+=(--check)
fi
exec "$base_python" "$project_root/scripts/setup_managed_runtime.py" "${runtime_args[@]}"
