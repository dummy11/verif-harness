#!/usr/bin/env python3
"""Build immutable wheel/sdist plus the standalone installer and checksums."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release", action="store_true", help="require clean tagged source")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "release.json").read_text())
    import tomllib
    if tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"] != manifest["version"]:
        raise SystemExit("project version and release manifest differ")
    if args.release:
        if git("status", "--porcelain"):
            raise SystemExit("release requires a clean worktree")
        if git("rev-parse", "v" + manifest["version"] + "^{commit}") != git("rev-parse", "HEAD"):
            raise SystemExit("release tag must identify HEAD")
    destination = args.output.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit("output must be empty; published versions are never overwritten")
    destination.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, SOURCE_DATE_EPOCH=git("show", "-s", "--format=%ct", "HEAD"))
    subprocess.run([sys.executable, "-m", "build", "--no-isolation", "--outdir", str(destination), str(ROOT)], check=True, env=env)
    subprocess.run([sys.executable, str(ROOT / "scripts/check_distribution.py"), str(destination)], check=True)
    for name in ("verif-harness-install.py", "release.json"):
        shutil.copy2(ROOT / name, destination / name)
    (destination / "SHA256SUMS").write_text("".join(
        hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
        for p in sorted(destination.iterdir()) if p.is_file()))
    print(f"Release artifacts: {destination}")


if __name__ == "__main__":
    main()
