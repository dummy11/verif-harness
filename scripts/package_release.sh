#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="${1:-}"

if [[ ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 vMAJOR.MINOR.PATCH" >&2
  exit 2
fi

python3 -c 'import json,sys; assert "v"+json.load(open(sys.argv[1]))["version"] == sys.argv[2], "release version differs"' "$project_root/release.json" "$version"
exec python3 "$project_root/scripts/package_release.py" --release --output "$project_root/dist"
