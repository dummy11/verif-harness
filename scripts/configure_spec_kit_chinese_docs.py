#!/usr/bin/env python3
"""Build a non-executable Simplified Chinese reading mirror for .specify Markdown."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


MIRROR_RELATIVE = Path(".specify/docs/zh-CN")
LANGUAGE_MARKER = "默认使用简体中文"


IMPLEMENT_SUMMARY = """# `speckit.implement` 中文导读

此文件对应英文执行指令，仅供人工阅读，不参与 Spec Kit command discovery。

## 主要职责

- 只执行经过评审并通过 execution gate 的任务。
- 每个任务必须分发到其声明的 `verif-harness mode`，正常路径只分发一次。
- 执行前读取 `AGENTS.md`、`.harness-config.json`、Stage 文档和受影响计划。
- DUT RTL 始终只读；不得绕过组件 ownership 或 Human authority。
- 每个任务必须保留 `REQ/VF/TASK/MODE/ARTIFACT/EVIDENCE` traceability。
- 工具或 Agent 返回 PASS 不等于 Human approval、waiver、sign-off 或 freeze。
- owned outputs、evidence paths 或 validation 缺失时，任务保持 incomplete。
- Stage 0 的 `init` 与其他 mode 遵守相同的一次性分发和 postcondition 规则。

完整可执行语义始终以 manifest 中记录 hash 的英文源文件为准。
"""

CONSTITUTION_SYNC_README_SUMMARY = """# Constitution Template Sync 中文导读

此文件对应上游 `constitution-sync` preset 的英文说明，仅供人工阅读。

该 preset 会在 provenance 证明 constitution 仍是未编辑生成物时，将当前 active
`constitution-template` 同步到 `.specify/memory/constitution.md`。一旦 Human 修改
constitution，自动替换立即停止。它还包装 `speckit.constitution`，允许把已批准治理
规则传播到项目自有模板和命令，但不得修改由 preset/extension 管理的版本化文件。

主要风险是 materialized snapshot 与 runtime resolution 产生漂移或覆盖冲突。因此
项目仍应把 live constitution 和 preset resolution stack 视为权威，不把本中文导读
当作配置、模板或审批证据。
"""

CONSTITUTION_COMMAND_SUMMARY = """# `speckit.constitution` 中文导读

此文件对应英文 constitution command，仅供人工阅读，不参与命令执行。

## 执行边界

- 工作范围只包括项目 constitution 及获准的治理同步，不实现 feature 或修改 DUT RTL。
- 从 active `constitution-template` 开始，并保留仍适用的已有项目决策。
- 所有 placeholder、版本号、批准日期和修订日期必须明确；未知信息不得伪造。
- 修改前分析语义版本变化，修改后生成 Sync Impact Report。
- 只有项目自有的 dependent templates/commands 可以传播更新。
- preset/extension 管理的命令必须通过 resolution stack 重新生成，不能手工编辑。

完整可执行语义始终以 manifest 中记录 hash 的英文源文件为准。
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing to follow symlinked {label}: {path}")


def prepare_destination(mirror_root: Path, destination: Path) -> None:
    """Create destination parents without traversing a symlink."""
    relative = destination.relative_to(mirror_root)
    current = mirror_root
    for part in relative.parts[:-1]:
        current /= part
        reject_symlink(current, "Chinese documentation directory")
        current.mkdir(exist_ok=True)
    reject_symlink(destination, "Chinese documentation destination")


def read_markdown(path: Path) -> bytes:
    reject_symlink(path, "Markdown source")
    if not path.is_file():
        raise ValueError(f"Markdown source is not a regular file: {path}")
    return path.read_bytes()


def summary_for(relative: Path) -> str | None:
    value = relative.as_posix()
    if value.endswith("verif-harness-rtl/commands/speckit.implement.md"):
        return IMPLEMENT_SUMMARY
    if value.endswith("verif-harness-rtl/.composed/speckit.implement.md"):
        return IMPLEMENT_SUMMARY.replace(
            "对应英文执行指令", "对应合成后的英文执行指令"
        )
    if value.endswith("constitution-sync/README.md"):
        return CONSTITUTION_SYNC_README_SUMMARY
    if value.endswith("constitution-sync/commands/speckit.constitution.md"):
        return CONSTITUTION_COMMAND_SUMMARY
    if value.endswith("constitution-sync/.composed/speckit.constitution.md"):
        return CONSTITUTION_COMMAND_SUMMARY.replace(
            "对应英文 constitution command", "对应合成后的英文 constitution command"
        )
    return None


def pending_document(relative: Path) -> str:
    return f"""# 待补充中文导读：`{relative.as_posix()}`

该 Markdown 来自当前 Spec Kit 安装，但 verif-harness 尚未提供经过评审的中文版本。
它不会被自动机翻，以免改变命令、模板或治理语义。请以 manifest 记录 hash 的英文源
文件为准，并在升级评审中补充对应翻译。
"""


def translated_content(
    specify_root: Path, relative: Path, source: bytes
) -> tuple[bytes, str]:
    if relative.parts[:1] == ("templates",):
        translated = (
            specify_root
            / "presets/verif-harness-rtl/templates"
            / relative.name
        )
        if translated.is_file():
            return read_markdown(translated), "full"

    text = source.decode("utf-8")
    if LANGUAGE_MARKER in text or relative == Path("memory/constitution.md"):
        return source, "source-is-chinese"

    summary = summary_for(relative)
    if summary is not None:
        return summary.encode("utf-8"), "summary"
    return pending_document(relative).encode("utf-8"), "pending"


def source_markdown(specify_root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in specify_root.rglob("*.md"):
        relative = path.relative_to(specify_root)
        if relative.parts[:2] == ("docs", "zh-CN"):
            continue
        paths.append(path)
    return sorted(paths)


def mirror_readme() -> str:
    return """# `.specify` 中文阅读镜像

本目录由 verif-harness 管理，仅供人工阅读，不参与 Spec Kit template resolution、
command discovery、workflow 或审批。英文源文件及 active preset 始终是执行事实源。

`manifest.json` 为每个源 Markdown 记录对应中文文件、源文件 SHA-256、中文文件
SHA-256 和翻译状态：

- `full`：经过评审的完整中文对应模板。
- `source-is-chinese`：源文件本身已是中文，镜像保持一致。
- `summary`：英文执行文件的中文导读，不是逐字翻译。
- `pending`：发现新的英文文件，等待人工翻译评审。

Spec Kit 或 preset 升级后应重新生成镜像并检查 `pending` 与 hash 变化。
"""


def build_mirror(project_root: Path, package_root: Path) -> dict[str, object]:
    project_root = project_root.resolve()
    specify_root = project_root / ".specify"
    reject_symlink(specify_root, ".specify directory")
    if not specify_root.is_dir():
        raise ValueError(f"Spec Kit project is missing: {specify_root}")

    docs_root = specify_root / "docs"
    reject_symlink(docs_root, "Spec Kit documentation directory")
    docs_root.mkdir(exist_ok=True)
    mirror_root = docs_root / "zh-CN"
    reject_symlink(mirror_root, "Chinese documentation mirror")
    mirror_root.mkdir(exist_ok=True)

    lock_path = package_root.resolve() / "deps/spec-kit.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    entries: list[dict[str, str]] = []
    for source_path in source_markdown(specify_root):
        relative = source_path.relative_to(specify_root)
        source = read_markdown(source_path)
        translated, status = translated_content(specify_root, relative, source)
        destination = mirror_root / relative
        prepare_destination(mirror_root, destination)
        destination.write_bytes(translated)
        entries.append(
            {
                "source": f".specify/{relative.as_posix()}",
                "translation": str(MIRROR_RELATIVE / relative),
                "source_sha256": digest(source),
                "translation_sha256": digest(translated),
                "status": status,
            }
        )

    readme = mirror_root / "README.md"
    reject_symlink(readme, "Chinese mirror README")
    readme.write_text(mirror_readme(), encoding="utf-8")
    counts = {
        status: sum(entry["status"] == status for entry in entries)
        for status in ("full", "source-is-chinese", "summary", "pending")
    }
    manifest: dict[str, object] = {
        "schema_version": 1,
        "generated_by": "verif-harness",
        "execution_authority": False,
        "spec_kit": {
            "version": lock["version"],
            "commit": lock["commit"],
        },
        "counts": counts,
        "entries": entries,
    }
    manifest_path = mirror_root / "manifest.json"
    reject_symlink(manifest_path, "Chinese mirror manifest")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--package-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = build_mirror(args.project_root, args.package_root)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest["counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
