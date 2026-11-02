#!/usr/bin/env python3
"""Exercise actual release installs and project dispatch outside the checkout.

Uses temporary installation roots, a public synthetic DUT and no Agent execution.
The second verif-harness version is a local fixture, never a published release.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--nsim-wheel', type=Path, required=True)
    parser.add_argument('--nsim-installer', type=Path, required=True)
    parser.add_argument('--wheelhouse', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='verif release smoke ') as temporary:
        base = Path(temporary).resolve()
        tools = base / 'shared tools'
        nsim = base / 'shared nsim'
        env = dict(os.environ, XDG_CONFIG_HOME=str(base / 'config'),
                   VERIF_HARNESS_DASHBOARD_REGISTRY_DIR=str(base / 'dashboard'))
        for key in ('PYTHONPATH', 'VERIF_HARNESS_HOME', 'VERIF_HARNESS_RELEASE', 'NSIM_HOME'):
            env.pop(key, None)

        def run(command, cwd=base, success=True):
            result = subprocess.run(list(map(str, command)), cwd=cwd, env=env, text=True, capture_output=True)
            if (result.returncode == 0) != success:
                raise RuntimeError(f'Unexpected command result: {command[0:3]}\n{result.stdout}\n{result.stderr}')
            return result

        installer = [sys.executable, ROOT / 'verif-harness-install.py']
        options = ['--root', tools, '--nsim-root', nsim, '--python', sys.executable, '--core-only']
        install = installer + ['install', '--wheel', args.wheel.resolve(), '--nsim-wheel', args.nsim_wheel.resolve(),
                               '--nsim-installer', args.nsim_installer.resolve(), '--wheelhouse', args.wheelhouse.resolve(), *options]
        run(install)
        run(install)  # Same bytes must reuse both installations.
        # Exercise --user/--system selection without writing to the host's homes
        # or /opt. Only the default destination constants are redirected.
        scoped = ('import importlib.util, pathlib, sys; '
                  's=importlib.util.spec_from_file_location("installer",sys.argv[1]); '
                  'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
                  'm.USER_ROOT=pathlib.Path(sys.argv[2]); m.SYSTEM_ROOT=pathlib.Path(sys.argv[3]); '
                  'sys.exit(m.main(sys.argv[4:]))')
        for scope in ('--user', '--system'):
            run([sys.executable, '-c', scoped, ROOT / 'verif-harness-install.py', tools, base / 'system tools',
                 'install', '--wheel', args.wheel.resolve(), scope, '--nsim-root', nsim,
                 '--python', sys.executable, '--core-only'])
        assert json.loads(run([base / 'system tools/bin/verif-harness', 'version']).stdout)['version']
        cli = tools / 'bin/verif-harness'
        current = json.loads(run([cli, 'version']).stdout)['version']
        projects = []
        for name in ('project one', 'project two'):
            project = base / name
            (project / 'rtl').mkdir(parents=True)
            (project / 'rtl/dut.sv').write_text('module dut; endmodule\n')
            (project / 'rtl/rtl.f').write_text('dut.sv\n')
            verification = 'verification_' + name.split()[-1]
            inputs = [cli, 'bootstrap', '--runtime', 'none', '--rtl-root', 'rtl', '--rtl-filelist', 'rtl/rtl.f',
                      '--dut-top', 'dut', '--dut-top-file', 'rtl/dut.sv', '--verif-root', verification, '--no-dashboard']
            run(inputs, project)
            database = project / '.verif-harness/model.sqlite3'
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            run(inputs, project)
            assert hashlib.sha256(database.read_bytes()).hexdigest() == before
            run(inputs + ['--runtime', 'codex'], project, success=False)
            (project / 'rtl/rtl2.f').write_text('dut.sv\n')
            changed = [str(p) if str(p) != 'rtl/rtl.f' else 'rtl/rtl2.f' for p in inputs]
            run(changed + ['--refresh', '--docs-root', 'missing-spec'], project, success=False)
            assert 'rtl2.f' not in (project / verification / '.nsim/nsim.toml').read_text()
            run(changed + ['--refresh'], project)
            assert 'rtl2.f' in (project / verification / '.nsim/nsim.toml').read_text()
            run(inputs + ['--refresh'], project)
            run([nsim / 'bin/nsim', 'switch', current], project / verification, success=False)
            nested = project / 'nested/deeper'
            nested.mkdir(parents=True)
            run([cli, 'status'], nested)
            assert json.loads(run([cli, 'version'], nested).stdout)['version'] == current
            projects.append(project)
        assert len(list((nsim / 'versions').iterdir())) == 1

        # Test two installed releases with real code and stable launchers.
        target = '999.0.0rc1'
        fixture = base / f'verif_harness-{target}-py3-none-any.whl'
        with zipfile.ZipFile(args.wheel) as source, zipfile.ZipFile(fixture, 'w') as dest:
            for info in source.infolist():
                content = source.read(info.filename)
                name = info.filename.replace(f'-{current}.dist-info/', f'-{target}.dist-info/')
                if name.endswith('/METADATA'):
                    content = content.replace(f'Version: {current}\n'.encode(), f'Version: {target}\n'.encode())
                if name == 'verif_harness/_bundle/release.json':
                    manifest = json.loads(content)
                    manifest['version'] = target
                    content = json.dumps(manifest).encode()
                info.filename = name
                dest.writestr(info, content)
        run(installer + ['install', '--wheel', fixture, *options])
        for project in projects:
            assert json.loads(run([cli, 'restart', '--no-agent'], project / 'nested/deeper').stdout)['status'] == 'READY'
        run([cli, 'switch', target], projects[0])
        assert json.loads(run([cli, 'version'], projects[0]).stdout)['version'] == target
        assert json.loads(run([cli, 'version'], projects[1]).stdout)['version'] == current
        run([cli, 'status'], projects[0])
        try:
            assert json.loads(run([cli, 'restart', '--no-agent'], projects[0]).stdout)['status'] == 'READY'
        finally:
            run([cli, 'dashboard', '--stop'], projects[0])
        run([cli, 'switch', current], projects[0])
        run([cli, 'status'], projects[0])
        try:
            assert json.loads(run([cli, 'restart', '--no-agent'], projects[0]).stdout)['status'] == 'READY'
            assert json.loads(run([cli, 'restart', '--no-agent'], projects[1]).stdout)['status'] == 'READY'
        finally:
            run([cli, 'dashboard', '--stop'], projects[1])

        # Bundle import must not access package indexes or any network fallback.
        bundle = base / 'core.tar.gz'
        run(installer + ['bundle', 'create', '--wheel', args.wheel.resolve(), '--nsim-wheel', args.nsim_wheel.resolve(),
                         '--nsim-installer', args.nsim_installer.resolve(), '--wheelhouse', args.wheelhouse.resolve(), '--output', bundle])
        env.update(PIP_NO_INDEX='1', HTTPS_PROXY='http://127.0.0.1:1', HTTP_PROXY='http://127.0.0.1:1')
        run(installer + ['install', '--bundle', bundle, '--root', base / 'offline tools', '--nsim-root', base / 'offline nsim',
                         '--python', sys.executable, '--core-only', '--sha256', hashlib.sha256(bundle.read_bytes()).hexdigest()])
        # Immutable installation content must fail closed after an accidental edit.
        entry = tools / 'versions' / current / 'package/verif_harness/cli.py'
        entry.write_text(entry.read_text() + '\n# changed\n')
        run([cli, 'status'], projects[1], success=False)
    print('Distribution install PASS: shared reuse, project pins, subdirectories, switch/rollback, offline import, tamper rejection')


if __name__ == '__main__':
    main()
