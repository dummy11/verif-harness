"""Shared dependency checks must not require changing users' Git configuration."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class SharedDependencyTest(unittest.TestCase):
    def test_exact_checkout_is_readable_without_global_trust(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            checkout = base / 'shared source'
            checkout.mkdir()
            subprocess.run(['git', 'init', '-q'], cwd=checkout, check=True)
            (checkout / 'README').write_text('public fixture\n')
            subprocess.run(['git', 'add', 'README'], cwd=checkout, check=True)
            subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                            'commit', '-qm', 'fixture'], cwd=checkout, check=True)
            global_config = base / 'global.gitconfig'
            global_config.write_text('# user preferences remain unchanged\n')
            index = checkout / '.git/index'
            before = (index.read_bytes(), index.stat().st_mtime_ns)
            with patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(global_config),
                                          'GIT_CONFIG_NOSYSTEM': '1',
                                          'GIT_TEST_ASSUME_DIFFERENT_OWNER': '1'}):
                denied = subprocess.run(['git', 'status', '--porcelain'], cwd=checkout,
                                        capture_output=True, text=True)
                self.assertNotEqual(denied.returncode, 0)
                self.assertIn('dubious ownership', denied.stderr)
                for name in ('setup_xverif', 'setup_wavepeek'):
                    with self.subTest(dependency=name):
                        spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        checked = module.git('status', '--porcelain', cwd=checkout)
                        self.assertEqual(checked.returncode, 0, checked.stderr)
                        self.assertEqual(checked.stdout, '')
                        # Scoped trust did not make an ordinary Git call trust it.
                        denied_again = subprocess.run(['git', 'status', '--porcelain'], cwd=checkout,
                                                      capture_output=True, text=True)
                        self.assertNotEqual(denied_again.returncode, 0)
            self.assertEqual(global_config.read_text(), '# user preferences remain unchanged\n')
            self.assertEqual((index.read_bytes(), index.stat().st_mtime_ns), before)


if __name__ == '__main__':
    unittest.main()
