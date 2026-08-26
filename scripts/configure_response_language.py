#!/usr/bin/env python3
"""Configure project-scoped response-language defaults for Agent CLIs."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


DEFAULT_INSTRUCTION = (
    "面向用户的说明、问题和总结默认使用简体中文。代码、标识符、命令、路径、"
    "配置键、协议名和原始日志保持原文；仅在准确性需要时补充英文术语。"
    "用户明确指定其他语言时，遵循用户要求。"
)
KIMI_BLOCK_BEGIN = "<!-- BEGIN verif-harness managed response language -->"
KIMI_BLOCK_END = "<!-- END verif-harness managed response language -->"


def configure_codex(project_root: Path) -> str:
    path = project_root / ".codex/config.toml"
    if path.is_symlink():
        raise ValueError(f"refusing to follow a symlink at {path}")
    if not path.is_file():
        raise ValueError(f"Codex config is not a regular file: {path}")

    source = path.read_text(encoding="utf-8")
    if re.search(r"(?m)^\s*developer_instructions\s*=", source):
        return f"Using existing Codex developer instructions: {path}"

    escaped = DEFAULT_INSTRUCTION.replace("\\", "\\\\").replace('"', '\\"')
    path.write_text(
        f'developer_instructions = "{escaped}"\n\n{source}',
        encoding="utf-8",
    )
    return f"Added default Chinese responses to Codex project config: {path}"


def configure_kimi(project_root: Path) -> str:
    path = project_root / ".kimi-code/AGENTS.md"
    if path.is_symlink():
        raise ValueError(f"refusing to follow a symlink at {path}")
    if path.exists() and not path.is_file():
        raise ValueError(f"Kimi instruction path is not a regular file: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    source = path.read_text(encoding="utf-8") if path.exists() else ""
    block = f"{KIMI_BLOCK_BEGIN}\n{DEFAULT_INSTRUCTION}\n{KIMI_BLOCK_END}"
    if KIMI_BLOCK_BEGIN in source or KIMI_BLOCK_END in source:
        if source.count(KIMI_BLOCK_BEGIN) != 1 or source.count(KIMI_BLOCK_END) != 1:
            raise ValueError(f"malformed managed language block: {path}")
        before, remainder = source.split(KIMI_BLOCK_BEGIN, 1)
        _, after = remainder.split(KIMI_BLOCK_END, 1)
        source = f"{before}{block}{after}"
    else:
        separator = "\n\n" if source and not source.endswith("\n\n") else ""
        source = f"{source}{separator}{block}\n"
    path.write_text(source, encoding="utf-8")
    return f"Configured default Chinese responses for Kimi: {path}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--runtime", choices=("codex", "kimi"), required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    try:
        message = (
            configure_codex(project_root)
            if args.runtime == "codex"
            else configure_kimi(project_root)
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
