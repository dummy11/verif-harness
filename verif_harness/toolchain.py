"""Release selection and project setup. Governance remains in ProjectStore."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import uuid

from .package import root as package_root, release
from .store import HarnessError, atomic_json, atomic_text, SCHEMA_VERSION

PIN = "toolchain.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def discover(start):
    path = Path(start).expanduser().resolve()
    for candidate in (path, *path.parents):
        if os.path.lexists(candidate / ".verif-harness"):
            return candidate
    return path


def selected(store):
    path = store.state / PIN
    return json.loads(path.read_text()) if path.is_file() else None


def verify(store, allow_transition=False):
    if (store.state / "version-transition.json").exists() and not allow_transition:
        raise HarnessError("项目版本切换尚未完成，请使用 switch --recover")
    value = selected(store)
    if value is None:
        return
    manifest = release()
    if (value.get("version") != manifest["version"] or value.get("release_sha256") != sha(package_root() / "release.json")
            or value.get("nsim_version") != manifest["nsim"]["version"]):
        raise HarnessError("当前程序与项目选择的发布版本不一致，请从稳定 verif-harness 启动器进入项目")
    nsim_project = Path(value["nsim_project"])
    pin = nsim_project / ".nsim/.nsim_version"
    if not pin.is_file() or pin.read_text().strip() != manifest["nsim"]["version"]:
        raise HarnessError("项目的 nsim 版本与发布清单不一致，请通过 verif-harness switch 恢复")


def acquire_lease(store):
    """Keep code selection stable for a CLI call or a database operation."""
    if not (store.state / PIN).exists():
        return None
    handle = (store.state / 'tool-use.lock').open('a+')
    try:
        fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        verify(store)
        return handle
    except BaseException as exc:
        handle.close()
        if isinstance(exc, BlockingIOError):
            raise HarnessError('项目正在切换版本，请完成切换后重试') from exc
        raise


def nsim_command():
    manifest = release()["nsim"]
    home = Path(os.environ.get("NSIM_HOME") or "~/.local/share/nsim").expanduser().resolve()
    directory = home / "versions" / manifest["version"]
    receipt = directory / "receipt.json"
    if not receipt.is_file():
        raise HarnessError(f"配套 nsim {manifest['version']} 尚未安装，请先安装当前 verif-harness 发布版本")
    data = json.loads(receipt.read_text())
    if data.get("wheel_sha256") != manifest["wheel_sha256"]:
        raise HarnessError("已安装 nsim 的安装包与发布清单不一致")
    return [str(directory / "venv/bin/nsim")]


def run(command, cwd=None, env=None):
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)
    if result.returncode:
        raise HarnessError(f"操作未完成：{result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def configure_agent(store, runtime, adopt_existing=False):
    if runtime == "none":
        return
    if runtime not in {"codex", "kimi"}:
        raise HarnessError("请明确选择 codex、kimi 或 none")
    package = package_root()
    control = ".codex" if runtime == "codex" else ".kimi-code"
    for directory in (store.root / control, store.root / ".agents", store.root / ".harness", store.root / '.harness/mcp'):
        if directory.is_symlink():
            raise HarnessError(f"项目配置目录不能是符号链接：{directory.name}")
    parent = store.root / (".agents/skills" if runtime == "codex" else ".kimi-code/skills")
    record_path = store.state / "managed-profiles.json"
    previous = json.loads(record_path.read_text()) if record_path.exists() else {"files": {}, "links": {}}
    files, links = dict(previous["files"]), dict(previous["links"])
    prior_links = dict(previous.get('prior_links', {}))
    sources = list((package / control / "agents").glob("*"))
    if runtime == "codex":
        sources += [package / control / "config.toml", package / control / "rules/default.rules"]
    # Preflight every managed replacement before touching any project config.
    updates = []
    for source in sources:
        if not source.is_file():
            continue
        relative = str(source.relative_to(package))
        target = store.root / relative
        if any(parent.is_symlink() for parent in target.parents if parent.is_relative_to(store.root) and parent != store.root):
            raise HarnessError(f"项目配置目录不能是符号链接：{relative}")
        if target.is_symlink():
            raise HarnessError(f"项目配置路径不是普通文件：{relative}")
        content = source.read_text()
        if relative == '.codex/config.toml':
            # The portable repository MCP block has cwd='.' and is optional.
            # Consumer projects need the actual project cwd and required=true.
            block = re.search(r'(?ms)^# BEGIN verif-harness managed xverif MCP\n.*?^# END verif-harness managed xverif MCP\n?', content)
            if target.exists():
                content = target.read_text()
            if block:
                content = content.replace(block.group(), '')
            updates.append((content, target, relative))
            continue
        if target.exists() and sha(target) != sha(source) and files.get(relative) != sha(target):
            # Existing project-owned config is retained, but Agent profiles must
            # remain the selected release's profiles before starting the Agent.
            if "/agents/" in relative:
                raise HarnessError(f"项目 Agent 配置有自行修改的内容，请先合并：{relative}")
            continue
        updates.append((content, target, relative))
    for name in ("verif-harness", "verification-doc-authoring"):
        target = parent / name
        source = package / "skills" / name
        relative = str(target.relative_to(store.root))
        if parent.is_symlink():
            raise HarnessError(f"项目 Skill 目录不能是符号链接：{parent}")
        if os.path.lexists(target):
            if not target.is_symlink():
                raise HarnessError(f"现有 Skill 入口需要先核对：{relative}")
            old = str(target.resolve())
            if old not in {str(source), links.get(relative)}:
                if not adopt_existing or not (target / 'SKILL.md').is_file():
                    raise HarnessError(f"现有 Skill 入口需要通过 bootstrap --refresh 确认迁移：{relative}")
                prior_links.setdefault(relative, []).append(old)
        links[relative] = str(source)
    for content, target, relative in updates:
        atomic_text(target, content)
        files[relative] = sha(target)
    parent.mkdir(parents=True, exist_ok=True)
    for relative, source in links.items():
        target = store.root / relative
        if target.is_symlink():
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source)
    atomic_json(record_path, {"files": files, "links": links, 'prior_links': prior_links})
    if runtime == "kimi":
        local = store.root / ".kimi-code/local.toml"
        if not local.exists():
            atomic_text(local, "[workspace]\nadditional_dir = []\n")
    run([sys.executable, str(package / "scripts/configure_response_language.py"),
         "--project-root", str(store.root), "--runtime", runtime])
    profile = store.root / '.harness/mcp/xverif.json'
    if profile.is_symlink():
        raise HarnessError('项目 MCP 配置不能是符号链接')
    if profile.exists():
        current = json.loads(profile.read_text())
        expected = json.loads((package / 'deps/xverif.lock.json').read_text())['commit']
        if current.get('source_commit') != expected and files.get('.harness/mcp/xverif.json') == sha(profile):
            profile.unlink()  # Replace only a recorded, unchanged managed profile.
    run([sys.executable, str(package / "scripts/verif_harness.py"), "xverif", "mcp", "configure",
         "--project-root", str(store.root), "--runtime", runtime, "--backend", "direct"])
    for name in ('.codex/config.toml', '.kimi-code/mcp.json', '.harness/mcp/xverif.json', '.harness/mcp/xverif-mcp'):
        path = store.root / name
        if path.is_file():
            files[name] = sha(path)
    atomic_json(record_path, {"files": files, "links": links, 'prior_links': prior_links})


def bootstrap_nsim(store, args):
    if not args.dut_top or not args.dut_top_file:
        raise HarnessError("bootstrap 必须先确认 DUT top 和 top file")
    top = (store.root / args.dut_top_file).resolve()
    roots = [(store.root / p).resolve() for p in args.rtl_root]
    if not top.is_file() or not any(top.is_relative_to(p) for p in roots):
        raise HarnessError("DUT top file 必须存在且属于已确认的 RTL 根目录")
    if len(args.rtl_root) != 1:
        raise HarnessError("nsim 工程需要一个明确的 RTL 根目录；请提供包含本次设计输入的共同根目录")
    if not args.rtl_filelist or not Path(args.rtl_filelist).expanduser().is_file():
        raise HarnessError("bootstrap 必须提供可读取的 --rtl-filelist")
    root = (store.root / (args.verif_root or ".")).resolve()
    if root != store.root and store.root not in root.parents:
        raise HarnessError("验证资产目录必须属于当前项目")
    updating = args.refresh and (root / '.nsim').is_dir()
    if updating:
        run(nsim_command() + ['bootstrap', '--verification-root', str(root),
                             '--nsim-version', release()['nsim']['version'], '--json'])
    command = nsim_command() + (["update", "--project", str(root)] if updating else ["bootstrap", "--verification-root", str(root)]) + ["--rtl-root",
                              str(Path(args.rtl_root[0]).expanduser().resolve()), "--rtl-filelist",
                              str(Path(args.rtl_filelist).expanduser().resolve()), "--json"]
    if not updating:
        command += ['--nsim-version', release()['nsim']['version']]
    if args.verification_filelist:
        command += ["--verification-filelist", str((store.root / Path(args.verification_filelist).expanduser()).resolve())]
    for output in args.sim_output_root:
        command += ["--output-root", str((store.root / Path(output).expanduser()).resolve())]
    run(command)
    return root


def wizard(args):
    """Collect one field at a time before creating project or nsim state."""
    fields = [
        ("rtl_root", "只读 RTL 根目录", True, True),
        ("rtl_filelist", "只读 RTL filelist", True, False),
        ("dut_top", "DUT 顶层模块名", True, False),
        ("dut_top_file", "DUT 顶层文件", True, False),
        ("verif_root", "项目内验证资产目录（项目根目录填 .）", True, False),
        ("docs_root", "RTL 规格路径；没有请填 skip", False, True),
        ("testbench_root", "已有 testbench 目录；没有请填 skip", False, False),
        ("reference_model", "参考模型路径；没有请填 skip", False, False),
        ("verification_script", "已有验证脚本路径；没有请填 skip", False, True),
        ("verification_filelist", "已有 testbench filelist；没有请填 skip", False, False),
        ("sim_output_root", "工程源码之外的仿真输出目录；以后配置请填 skip", False, True),
    ]
    for key, prompt, required, many in fields:
        if getattr(args, key):
            continue
        while True:
            answer = input(prompt + "：").strip()
            if not answer or (required and answer.lower() == "skip"):
                print("请明确填写本项；可选项可填写 skip。")
                continue
            if answer.lower() == "skip":
                break
            path = (args.project_root / Path(answer).expanduser()).resolve()
            if key == 'dut_top':
                if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', answer):
                    print('请填写有效的 DUT 模块名。')
                    continue
            elif key == 'verif_root':
                if not path.is_relative_to(args.project_root.resolve()):
                    print('验证资产目录必须属于当前项目。')
                    continue
            elif key == 'sim_output_root':
                pass  # nsim checks output/source separation before writing.
            elif not path.exists() or (key in {'rtl_root', 'testbench_root'} and not path.is_dir()) or (key in {'rtl_filelist', 'dut_top_file', 'verification_filelist'} and not path.is_file()):
                print('路径不存在或类型不符，请重新填写。')
                continue
            break
        setattr(args, key, ([answer] if many else answer) if answer.lower() != "skip" else ([] if many else None))
    if args.runtime == "auto":
        while True:
            args.runtime = input("项目 Agent（codex / kimi / none）：").strip()
            if args.runtime in {"codex", "kimi", "none"}:
                break
    print(json.dumps({key: getattr(args, key) for key, *_ in fields} | {"runtime": args.runtime}, ensure_ascii=False, indent=2))
    if input("确认以上输入并初始化项目？输入 yes：").strip().lower() != "yes":
        raise HarnessError("尚未确认工程输入，未初始化项目")


def record_selection(store, nsim_project):
    nsim_project = Path(nsim_project).resolve()
    manifest = release()
    value = {"schema": 1, "version": manifest["version"], "nsim_version": manifest["nsim"]["version"],
             "release_sha256": sha(package_root() / "release.json"), "nsim_project": str(nsim_project)}
    atomic_json(store.state / PIN, value)
    atomic_json(nsim_project / ".nsim/verif-harness.json", {**value, "project_root": str(store.root)})
    return value


def restart(store, no_agent=False):
    store.require()
    verify(store)
    nsim_command()
    manifest = json.loads((store.state / "project.json").read_text())
    runtime = manifest["runtime"]
    configure_agent(store, runtime)
    from .dashboard_startup import ensure_dashboard_ready
    result = ensure_dashboard_ready(store)
    if no_agent:
        return result
    if runtime not in {"codex", "kimi"}:
        raise HarnessError("项目尚未选择 Agent；请通过 bootstrap --refresh 选择 codex 或 kimi")
    from .cli import display_dashboard_ready
    display_dashboard_ready(result, store)
    from .agent_service import interactive
    os.chdir(store.root)
    return interactive(store, runtime, None)


def switch(store, target, recover=False):
    from .agent_service import project_lock
    transition = store.state / "version-transition.json"
    with project_lock(store), tool_lock(store):
        if recover:
            if not transition.is_file():
                raise HarnessError("没有需要恢复的版本切换")
            journal = json.loads(transition.read_text())
            nsim_project = Path(journal["before"]["nsim_project"])
            allowed = {str(store.state / PIN), str(nsim_project / '.nsim/.nsim_version'),
                       str(nsim_project / '.nsim/verif-harness.json'), str(store.state / 'dashboard-runtime.json')}
            if not set(journal['files']) <= allowed or not set(journal['files']) >= allowed - {str(store.state / 'dashboard-runtime.json')} or (nsim_project != store.root and store.root not in nsim_project.parents):
                raise HarnessError("版本切换恢复记录中的项目路径无效")
            for relative, old in journal['files'].items():
                path = Path(relative)
                current = path.read_text() if path.exists() else None
                if current not in (old, journal.get('after', {}).get(relative, old)):
                    raise HarnessError('版本记录在切换后被另行修改，请先核对，未覆盖现有文件')
            for relative, old in journal["files"].items():
                path = Path(relative)
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_text(path, old)
            transition.unlink()
            return {"status": "RESTORED", "version": journal["before"]["version"]}
        verify(store)
        if not isinstance(target, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?", target):
            raise HarnessError("请指定准确的目标版本号")
        before = selected(store)
        if not before:
            raise HarnessError("请先通过 bootstrap --refresh 登记当前发布版本")
        home = Path(os.environ["VERIF_HARNESS_HOME"])
        target_dir = home / "versions" / target
        receipt_path = target_dir / "receipt.json"
        if not receipt_path.is_file():
            raise HarnessError("目标版本尚未安装；请先 install")
        receipt = json.loads(receipt_path.read_text())
        package = target_dir / "package"
        manifest = json.loads((package / "release.json").read_text())
        if manifest.get('version') != target or receipt.get('version') != target:
            raise HarnessError('目标版本与安装记录不一致')
        if manifest["project_schema"] != SCHEMA_VERSION:
            raise HarnessError("目标版本不兼容当前项目数据库；本版本不自动迁移或降级数据库")
        for name, expected in receipt["files"].items():
            if sha(package / name) != expected:
                raise HarnessError("目标安装内容已变化")
        with sqlite3.connect(f'{store.database.as_uri()}?mode=ro', uri=True) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "regression_execution_rounds" in tables:
                active = db.execute("SELECT count(*) FROM regression_execution_rounds WHERE status IN ('DISPATCHED','RUNNING','INTERRUPTED')").fetchone()[0]
                if active:
                    raise HarnessError("存在未结束或状态尚待核对的回归任务，请先核对原任务")
        nsim_project = Path(before["nsim_project"])
        nsim = Path(receipt["nsim_root"]) / "versions" / manifest["nsim"]["version"]
        nsim_receipt = json.loads((nsim / "receipt.json").read_text())
        if nsim_receipt["wheel_sha256"] != manifest["nsim"]["wheel_sha256"]:
            raise HarnessError("目标 nsim 安装包校验失败")
        if target == before["version"]:
            return {"status": "UNCHANGED", "version": target}
        paths = [store.state / PIN, nsim_project / ".nsim/.nsim_version", nsim_project / ".nsim/verif-harness.json",
                 store.state / 'dashboard-runtime.json']
        journal = {"schema": 1, "id": uuid.uuid4().hex, "before": before, "target": target,
                   "files": {str(p): p.read_text() if p.exists() else None for p in paths}}
        value = {**before, "version": target, "nsim_version": manifest["nsim"]["version"],
                 "release_sha256": sha(package / "release.json")}
        def encoded(data):
            return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
        journal['after'] = {str(paths[0]): encoded(value), str(paths[1]): value['nsim_version'] + '\n',
                            str(paths[2]): encoded({**value, 'project_root': str(store.root)}), str(paths[3]): None}
        # SQLite backup is consistent even when WAL is enabled.
        backup = store.state / "version-backups" / journal["id"]
        backup.mkdir(parents=True)
        with sqlite3.connect(f'{store.database.as_uri()}?mode=ro', uri=True) as source, sqlite3.connect(backup / "model.sqlite3") as destination:
            source.backup(destination)
        atomic_json(transition, journal)
        try:
            from .dashboard import unregister_dashboard_project
            unregister_dashboard_project(store)
            for path in paths[:3]:
                atomic_text(path, journal['after'][str(path)])
            paths[3].unlink(missing_ok=True)
            atomic_json(backup / "switch.json", journal)
            transition.unlink()
        except BaseException:
            # Leave a durable fence. Recovery restores the exact old selection;
            # it never restores a stale database over newly written evidence.
            raise
    return {"status": "SWITCHED", "version": target, "nsim_version": value["nsim_version"],
            "next": "restart", "message": "版本已切换；restart 将更新项目 Agent 入口并准备 Dashboard"}


@contextmanager
def tool_lock(store):
    with (store.state / 'tool-use.lock').open('a+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HarnessError('nsim 或控制面仍在使用当前项目版本，请等待操作结束后切换') from exc
        yield
