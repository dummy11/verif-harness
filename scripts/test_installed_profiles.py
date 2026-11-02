#!/usr/bin/env python3
"""Check Codex/Kimi project configuration and Dashboard without starting Agents."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launcher', type=Path, required=True)
    launcher = parser.parse_args().launcher.resolve()
    with tempfile.TemporaryDirectory(prefix='verif profiles ') as temporary:
        base = Path(temporary).resolve()
        env = dict(os.environ, XDG_CONFIG_HOME=str(base / 'config'),
                   VERIF_HARNESS_DASHBOARD_REGISTRY_DIR=str(base / 'dashboard'))
        for runtime in ('codex', 'kimi'):
            root = base / runtime
            (root / 'rtl').mkdir(parents=True)
            (root / 'rtl/dut.sv').write_text('module dut; endmodule\n')
            (root / 'rtl/rtl.f').write_text('dut.sv\n')
            commands = [
                ['bootstrap', '--runtime', runtime, '--rtl-root', 'rtl', '--rtl-filelist', 'rtl/rtl.f',
                 '--dut-top', 'dut', '--dut-top-file', 'rtl/dut.sv', '--verif-root', runtime + '_verif', '--no-dashboard'],
                ['restart', '--no-agent'], ['restart', '--no-agent'],
            ]
            try:
                for args in commands:
                    result = subprocess.run([str(launcher), *args], cwd=root, env=env, capture_output=True, text=True)
                    if result.returncode:
                        raise RuntimeError(f'{runtime} {args[0]} failed: {result.stderr}')
                skills = '.agents/skills' if runtime == 'codex' else '.kimi-code/skills'
                assert (root / skills / 'verif-harness/SKILL.md').is_file()
                if runtime == 'codex':
                    content = (root / '.codex/config.toml').read_text()
                    assert 'required = true' in content and str(root) in content
                assert (root / '.harness/mcp/xverif.json').is_file()
                # Old source setup created links but no v3 ownership ledger.
                old = base / ('legacy_' + runtime)
                old.mkdir()
                (old / 'SKILL.md').write_text('legacy source setup skill\n')
                link = root / skills / 'verif-harness'
                link.unlink()
                link.symlink_to(old)
                (root / '.verif-harness/managed-profiles.json').unlink()
                migrated = subprocess.run([str(launcher), *commands[0], '--refresh'], cwd=root, env=env,
                                          capture_output=True, text=True)
                if migrated.returncode:
                    raise RuntimeError(f'{runtime} legacy refresh failed: {migrated.stderr}')
                record = json.loads((root / '.verif-harness/managed-profiles.json').read_text())
                assert str(old) in record['prior_links'][skills + '/verif-harness']
                assert (old / 'SKILL.md').is_file()
            finally:
                subprocess.run([str(launcher), 'dashboard', '--stop'], cwd=root, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('Installed profiles PASS: Codex and Kimi bootstrap, Skill/MCP, repeated restart, authorized Dashboard')


if __name__ == '__main__':
    main()
