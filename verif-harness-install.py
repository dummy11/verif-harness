#!/usr/bin/env python3
"""Install immutable releases and dispatch each project to its selected version.

This standalone script uses Python's standard library. It is also the stable
verif-harness launcher; project operations run in the selected release.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
import urllib.request
import venv
import zipfile

USER_ROOT = Path("~/.local/share/verif-harness")
SYSTEM_ROOT = Path("/opt/verif-harness")
VERSION = re.compile(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?")
REPO = "dummy11/verif-harness"
PIN = ".verif-harness/toolchain.json"


class InstallError(ValueError):
    pass


def version(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise InstallError("版本号必须是准确版本，例如 3.0.0")
    return value


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic(path, value, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def environment(**values):
    result = {k: v for k, v in os.environ.items()
              if k not in {"PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "VERIF_HARNESS_PYTHON"}}
    return dict(result, PYTHONNOUSERSITE="1", **values)


def default_root():
    here = Path(__file__).resolve()
    if here.parent.name == "bin" and (here.parent.parent / "versions").is_dir():
        return here.parent.parent
    return Path(os.environ.get("VERIF_HARNESS_HOME") or USER_ROOT).expanduser().resolve()


def find_project(start=None):
    here = Path(start or Path.cwd()).expanduser().resolve()
    for parent in (here, *here.parents):
        if os.path.lexists(parent / ".verif-harness"):
            return parent
    return None


def project_arg(args):
    for i, arg in enumerate(args):
        if arg.startswith("--project-root="):
            return Path(arg.split("=", 1)[1]).expanduser().resolve()
        if arg == "--project-root":
            if i + 1 == len(args):
                raise InstallError("--project-root 缺少目录")
            return Path(args[i + 1]).expanduser().resolve()
    return find_project()


def installed(root, selected):
    selected = version(selected)
    path = root / "versions" / selected
    receipt = path / "receipt.json"
    if not receipt.is_file():
        raise InstallError(f"verif-harness {selected} 尚未完整安装；请先 install")
    data = json.loads(receipt.read_text())
    if data.get("version") != selected or data.get("schema") != 1:
        raise InstallError("安装记录无效")
    for name, expected in data["files"].items():
        target = path / "package" / name
        if not target.is_file() or digest(target) != expected:
            raise InstallError(f"安装内容已变化，请恢复发布版本：{name}")
    if not Path(data["python"]).is_file():
        raise InstallError("该版本的 Python 运行环境缺失")
    return data


def versions(root):
    directory = root / "versions"
    values = []
    for path in directory.iterdir() if directory.is_dir() else []:
        if VERSION.fullmatch(path.name) and (path / "receipt.json").is_file():
            installed(root, path.name)
            values.append(path.name)
    return sorted(values, key=lambda x: (tuple(map(int, x.split(".")[:2])), int(re.match(r"\d+", x.split(".")[2])[0]), not bool(re.search("[a-z]", x)), x))


def latest(root):
    stable = [v for v in versions(root) if not re.search("[a-z]", v)]
    if not stable:
        raise InstallError("没有完整安装的稳定版本；请先 install")
    return stable[-1]


def launch(root, args):
    project = project_arg(args)
    command = args[0] if args else "--help"
    if project and (project / ".verif-harness/version-transition.json").exists() and command != "switch":
        raise InstallError("项目版本切换尚未完成，请运行 switch --recover")
    if project and (project / PIN).is_file():
        selected = json.loads((project / PIN).read_text())["version"]
    elif command == "bootstrap" or command in {"--help", "-h", "version", "--version"}:
        selected = latest(root)
    elif project:
        raise InstallError("现有项目尚未登记发布版本；请用 bootstrap --refresh 明确确认工程参数")
    else:
        raise InstallError("当前目录不属于验证项目；请先 bootstrap 或指定 --project-root")
    if command == "bootstrap":
        for i, arg in enumerate(args):
            if arg == "--tool-version":
                if i + 1 == len(args):
                    raise InstallError('--tool-version 缺少版本号')
                selected = version(args[i + 1])
            elif arg.startswith('--tool-version='):
                selected = version(arg.split('=', 1)[1])
    record = installed(root, selected)
    package = root / "versions" / selected / "package"
    env = environment(VERIF_HARNESS_HOME=str(root), VERIF_HARNESS_RELEASE=selected,
                      NSIM_HOME=record["nsim_root"], VERIF_HARNESS_PYTHON=record["python"])
    env["PATH"] = os.pathsep.join([str(Path(record["python"]).parent), str(root / "bin"),
                                  str(Path(record["nsim_root"]) / "bin"), env.get("PATH", "")])
    os.execve(record["python"], [record["python"], str(package / "scripts/verif_harness.py"), *args], env)


def download(url, target, expected=None):
    if not url.startswith("https://"):
        raise InstallError("发布物必须使用 HTTPS")
    with urllib.request.urlopen(url, timeout=60) as response, target.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    if expected and digest(target) != expected:
        raise InstallError(f"发布物校验失败：{target.name}")
    return target


def wheel_release(wheel):
    with zipfile.ZipFile(wheel) as archive:
        from email.parser import BytesParser
        entries = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(entries) != 1:
            raise InstallError("安装包缺少唯一的包元数据")
        metadata = BytesParser().parsebytes(archive.read(entries[0]))
        value = json.loads(archive.read("verif_harness/_bundle/release.json"))
        if (metadata['Name'] != 'verif-harness' or metadata['Version'] != value['version']
                or value.get('schema') != 1):
            raise InstallError("安装包身份与发布清单不一致")
        for name, expected in value['dependencies'].items():
            if '/' in name or hashlib.sha256(archive.read('verif_harness/_bundle/deps/' + name)).hexdigest() != expected:
                raise InstallError("运行依赖与发布清单不一致")
        return value


def extract(wheel, package):
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise InstallError("安装包包含重复文件")
        for entry in archive.infolist():
            name = Path(entry.filename)
            if name.is_absolute() or ".." in name.parts or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise InstallError("安装包包含不安全路径")
        archive.extractall(package)
        for entry in archive.infolist():
            if not entry.is_dir() and entry.external_attr >> 16 & 0o111:
                (package / entry.filename).chmod(0o755)
    bundle = package / "verif_harness/_bundle"
    for item in bundle.iterdir():
        shutil.move(str(item), package / item.name)
    bundle.rmdir()


def install(options):
    root = Path(options.root or (SYSTEM_ROOT if options.system else USER_ROOT)).expanduser().resolve()
    nsim_root = Path(options.nsim_root or ("/opt/nsim" if options.system else "~/.local/share/nsim")).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".install.lock").open("a+") as lock, tempfile.TemporaryDirectory(dir=root) as temp:
        fcntl.flock(lock, fcntl.LOCK_EX)
        temp = Path(temp)
        if options.wheel:
            wheel = Path(options.wheel).resolve()
        else:
            selected = version(options.version)
            base = f"https://github.com/{REPO}/releases/download/v{selected}"
            sums = download(base + "/SHA256SUMS", temp / "SHA256SUMS")
            name = f"verif_harness-{selected}-py3-none-any.whl"
            entries = dict((line.split()[1].lstrip("*"), line.split()[0]) for line in sums.read_text().splitlines())
            wheel = download(base + "/" + name, temp / name, entries[name])
        if options.sha256 and digest(wheel) != options.sha256:
            raise InstallError("verif-harness 安装包校验失败")
        manifest = wheel_release(wheel)
        if not options.nsim_root and not options.system:
            shared = Path("/opt/nsim")
            candidate = shared / "versions" / manifest["nsim"]["version"] / "receipt.json"
            if candidate.is_file() and json.loads(candidate.read_text()).get("wheel_sha256") == manifest["nsim"]["wheel_sha256"]:
                nsim_root = shared
        selected = version(manifest["version"])
        if options.version and selected != options.version:
            raise InstallError("安装包版本与请求不一致")
        destination = root / "versions" / selected
        if (destination / "receipt.json").exists():
            record = installed(root, selected)
            if record["wheel_sha256"] != digest(wheel):
                raise InstallError("相同版本已从另一份安装包安装，不能覆盖")
            check_nsim(Path(record['nsim_root']), manifest['nsim'])
            print(f"复用 verif-harness {selected}：{destination}")
            return
        if destination.exists():
            raise InstallError(f"发现未完成的安装目录，请检查后移走再安装：{destination}")
        package = destination / "package"
        package.mkdir(parents=True)
        try:
            extract(wheel, package)
            if options.python:
                python = Path(options.python).resolve()
                subprocess.run([str(python), "-c", "import sys; assert sys.version_info >= (3, 11)"], check=True)
                subprocess.run([str(python), "-m", "venv", str(package / ".deps/runtime/venv")], check=True)
                python = package / ".deps/runtime/venv/bin/python"
                if not options.core_only:
                    subprocess.run([str(python), "-m", "pip", "install", "--require-hashes", "-r",
                                    str(package / "deps/runtime-requirements.lock")], check=True, env=environment())
            else:
                subprocess.run(["bash", str(package / "scripts/setup_managed.sh"), "--project-root", str(package)], check=True)
                python = package / ".deps/runtime/venv/bin/python"
            nsim = manifest["nsim"]
            if not (nsim_root / 'versions' / nsim['version'] / 'receipt.json').exists():
                wheel_path = Path(options.nsim_wheel).resolve() if options.nsim_wheel else download(nsim["wheel_url"], temp / nsim["wheel"], nsim["wheel_sha256"])
                installer = Path(options.nsim_installer).resolve() if options.nsim_installer else download(nsim["installer_url"], temp / "nsim-install.py", nsim["installer_sha256"])
                if digest(wheel_path) != nsim["wheel_sha256"] or digest(installer) != nsim["installer_sha256"]:
                    raise InstallError("nsim 安装文件与 verif-harness 发布清单不一致")
                command = [str(python), str(installer), "install", nsim["version"], "--root", str(nsim_root),
                           "--wheel", str(wheel_path), "--sha256", nsim["wheel_sha256"]]
                if options.wheelhouse:
                    command += ["--wheelhouse", str(Path(options.wheelhouse).resolve())]
                else:
                    subprocess.run([str(python), "-m", "pip", "download", "--dest", str(temp), str(wheel_path)], check=True, env=environment())
                    command += ["--wheelhouse", str(temp)]
                subprocess.run(command, check=True, env=environment())
            check_nsim(nsim_root, nsim)
            if not options.core_only:
                for tool in ("xverif", "wavepeek"):
                    subprocess.run([str(python), str(package / f"scripts/setup_{tool}.py"), "--project-root", str(package)], check=True, env=environment())
            files = {str(p.relative_to(package)): digest(p) for p in package.rglob("*") if p.is_file()
                     and ".deps" not in p.parts and "__pycache__" not in p.parts and not p.name.endswith(".pyc")}
            write_json(destination / "receipt.json", {"schema": 1, "version": selected, "wheel_sha256": digest(wheel),
                       "python": str(python), "nsim_root": str(nsim_root), "tools_ready": not options.core_only,
                       "files": files})
            launcher = b"#!/usr/bin/env python3\n" + Path(__file__).read_bytes().partition(b"\n")[2]
            for name in ("verif-harness", "verif-harness-install"):
                atomic(root / "bin" / name, launcher, 0o755)
        except BaseException:
            shutil.rmtree(destination)
            raise
    print(f"已安装 verif-harness {selected}，配套 nsim {manifest['nsim']['version']}；启动器：{root / 'bin/verif-harness'}")


def check_nsim(root, expected):
    directory = root / 'versions' / expected['version']
    receipt = json.loads((directory / 'receipt.json').read_text())
    if receipt.get('version') != expected['version'] or receipt.get('wheel_sha256') != expected['wheel_sha256']:
        raise InstallError('已安装 nsim 与发布清单不一致')
    result = subprocess.run([str(directory / 'venv/bin/nsim'), 'version', '--json'],
                            text=True, capture_output=True, check=True, env=environment(NSIM_HOME=str(root)))
    if json.loads(result.stdout).get('version') != expected['version']:
        raise InstallError('nsim 运行版本与发布清单不一致')


def bundle(args):
    parser = argparse.ArgumentParser(description='制作控制面与 nsim 的平台对应离线包；目标机需 Python 3.11+')
    parser.add_argument('action', choices=['create'])
    for name in ('wheel', 'nsim-wheel', 'nsim-installer', 'wheelhouse', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    options = parser.parse_args(args)
    manifest = wheel_release(options.wheel)
    if digest(options.nsim_wheel) != manifest['nsim']['wheel_sha256'] or digest(options.nsim_installer) != manifest['nsim']['installer_sha256']:
        raise InstallError('nsim 文件与发布清单不一致')
    if options.output.exists():
        raise InstallError('离线包已经存在，不能覆盖')
    files = {options.wheel.name: options.wheel, options.nsim_wheel.name: options.nsim_wheel,
             'nsim-install.py': options.nsim_installer, 'verif-harness-install.py': Path(__file__)}
    for path in options.wheelhouse.glob('*.whl'):
        if path.name not in files:
            files['wheelhouse/' + path.name] = path
    info = {'schema': 1, 'scope': 'core', 'version': manifest['version'], 'wheel': options.wheel.name,
            'nsim_wheel': options.nsim_wheel.name, 'files': {name: digest(path) for name, path in files.items()}}
    import io
    with tarfile.open(options.output, 'w:gz') as archive:
        for name, path in files.items():
            archive.add(path, arcname=name, recursive=False)
        content = json.dumps(info, sort_keys=True).encode()
        entry = tarfile.TarInfo('bundle.json')
        entry.size = len(content)
        archive.addfile(entry, io.BytesIO(content))
    atomic(str(options.output) + '.sha256', (digest(options.output) + '  ' + options.output.name + '\n').encode())


def install_bundle(options):
    if not options.core_only or not options.python:
        raise InstallError('控制面离线包需要 --core-only 和目标机 --python；分析工具仍由独立安装器管理')
    if options.wheel or options.nsim_wheel or options.nsim_installer or options.wheelhouse:
        raise InstallError('--bundle 不能同时指定独立 wheel 或 wheelhouse')
    if options.sha256 and digest(options.bundle) != options.sha256:
        raise InstallError('离线包校验失败')
    with tempfile.TemporaryDirectory() as temporary, tarfile.open(options.bundle, 'r:gz') as archive:
        temporary = Path(temporary)
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or 'bundle.json' not in names:
            raise InstallError('离线包文件清单无效')
        for member in members:
            if not member.isfile() or Path(member.name).is_absolute() or '..' in Path(member.name).parts:
                raise InstallError('离线包包含不安全路径')
        info = json.load(archive.extractfile('bundle.json'))
        if info.get('schema') != 1 or info.get('scope') != 'core' or set(names) != set(info['files']) | {'bundle.json'}:
            raise InstallError('离线包范围或清单不一致')
        for name, expected in info['files'].items():
            content = archive.extractfile(name).read()
            if hashlib.sha256(content).hexdigest() != expected:
                raise InstallError('离线包内容校验失败')
            atomic(temporary / name, content)
        options.wheel = temporary / info['wheel']
        options.nsim_wheel = temporary / info['nsim_wheel']
        options.nsim_installer = temporary / 'nsim-install.py'
        options.wheelhouse = temporary / 'wheelhouse'
        options.sha256 = None
        install(options)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    root = default_root()
    try:
        if args and args[0] == 'bundle':
            bundle(args[1:])
        elif args and args[0] == "install":
            parser = argparse.ArgumentParser(description=__doc__)
            parser.add_argument("command")
            parser.add_argument("version", nargs="?")
            scopes = parser.add_mutually_exclusive_group()
            scopes.add_argument("--user", action="store_true")
            scopes.add_argument("--system", action="store_true")
            scopes.add_argument("--root")
            for name in ("wheel", "bundle", "sha256", "nsim-root", "nsim-wheel", "nsim-installer", "wheelhouse", "python"):
                parser.add_argument("--" + name)
            parser.add_argument("--core-only", action="store_true", help="只安装控制面和 nsim，稍后单独准备可选分析工具")
            options = parser.parse_args(args)
            if not options.wheel and not options.version and not options.bundle:
                parser.error("需要版本号或 --wheel")
            install_bundle(options) if options.bundle else install(options)
        elif args and args[0] == "versions":
            print(json.dumps({"root": str(root), "versions": versions(root)}, ensure_ascii=False))
        else:
            launch(root, args)
        return 0
    except (InstallError, OSError, ValueError, KeyError, subprocess.CalledProcessError, zipfile.BadZipFile, tarfile.TarError) as exc:
        print(f"verif-harness：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
