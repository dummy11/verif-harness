"""Locate immutable distribution resources in a checkout or installed wheel."""
from pathlib import Path
import json


def root() -> Path:
    source = Path(__file__).resolve().parents[1]
    return source if (source / "skills/verif-harness/SKILL.md").is_file() else Path(__file__).parent / "_bundle"


def release() -> dict:
    return json.loads((root() / "release.json").read_text(encoding="utf-8"))
