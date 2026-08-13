#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="${1:-}"

if [[ ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 vMAJOR.MINOR.PATCH" >&2
  exit 2
fi

mkdir -p "$project_root/dist"
git -C "$project_root" archive \
  --format=tar.gz \
  --prefix="verif-harness-${version#v}/" \
  -o "$project_root/dist/verif-harness-${version#v}.tar.gz" \
  "$version"

cd "$project_root/dist"
shasum -a 256 "verif-harness-${version#v}.tar.gz" > "verif-harness-${version#v}.sha256"
