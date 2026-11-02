#!/usr/bin/env python3
"""Verify that released wheels contain current code and reviewed resource bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def check(directory):
    release = json.loads((ROOT / "release.json").read_text())
    wheels = list(Path(directory).glob(f"verif_harness-{release['version']}-*.whl"))
    if len(wheels) != 1:
        raise ValueError("expected exactly one wheel for the release")
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        for name in names:
            if any(part in {".git", ".deps", ".venv", "__pycache__", ".verif-harness", ".nsim"} for part in Path(name).parts):
                raise ValueError(f"private/generated content in wheel: {name}")
            if name.startswith("verif_harness/_bundle/"):
                source = ROOT / name.removeprefix("verif_harness/_bundle/")
            elif name.startswith("verif_harness/"):
                source = ROOT / name
            else:
                continue
            if not source.is_file():
                raise ValueError(f"wheel contains unknown resource: {name}")
            if archive.read(name) != source.read_bytes():
                raise ValueError(f"wheel differs from source: {source.relative_to(ROOT)}")
        for source in (ROOT / "verif_harness").glob("*.py"):
            if str(source.relative_to(ROOT)) not in names:
                raise ValueError(f"wheel lacks {source.name}")
        for item in ("release.json", "skills/verif-harness/SKILL.md", "scripts/verif_harness.py",
                     "deps/runtime.lock.json", "skills/verification-doc-authoring/core/common-rules.json"):
            if "verif_harness/_bundle/" + item not in names:
                raise ValueError(f"wheel lacks resource: {item}")
    for name, expected in release["dependencies"].items():
        if hashlib.sha256((ROOT / "deps" / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"release dependency drift: {name}")
    sources = list(Path(directory).glob(f"verif_harness-{release['version']}.tar.gz"))
    if len(sources) != 1:
        raise ValueError('expected exactly one source distribution')
    with tarfile.open(sources[0]) as archive:
        seen = set()
        for member in archive.getmembers():
            path = Path(member.name)
            if (path.is_absolute() or '..' in path.parts or not path.parts
                    or path.parts[0] != f"verif_harness-{release['version']}"):
                raise ValueError('unsafe source distribution path')
            if member.isdir():
                continue
            if not member.isfile() or member.name in seen:
                raise ValueError('source distribution contains links or duplicates')
            seen.add(member.name)
            relative = Path(*path.parts[1:])
            if any(part in {'.git', '.deps', '.venv', '__pycache__', '.verif-harness', '.nsim'} for part in relative.parts):
                raise ValueError(f'private/generated source content: {relative}')
            if relative.name in {'PKG-INFO', 'setup.cfg'} or any(part.endswith('.egg-info') for part in relative.parts):
                continue
            source = ROOT / relative
            if not source.is_file() or archive.extractfile(member).read() != source.read_bytes():
                raise ValueError(f'source distribution differs from checkout: {relative}')
    print("Distribution PASS: code, resources and dependency locks match")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    check(parser.parse_args().directory)
