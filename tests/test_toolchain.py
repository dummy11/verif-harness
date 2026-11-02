"""Version selection must not change verification history or mix tool releases."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from verif_harness import toolchain
from verif_harness.cli import build_parser
from verif_harness.package import release, root as package_root
from verif_harness.store import ProjectStore, HarnessError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vh_install", ROOT / "verif-harness-install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ToolchainTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "project"
        (self.root / "rtl").mkdir(parents=True)
        (self.root / "rtl/dut.sv").write_text("module dut; endmodule\n")
        (self.root / "rtl/rtl.f").write_text("dut.sv\n")
        self.store = ProjectStore(self.root)
        self.store.bootstrap(runtime="none", rtl_roots=["rtl"], dut_top="dut",
                             dut_top_file="rtl/dut.sv", rtl_filelist="rtl/rtl.f")
        (self.root / ".nsim").mkdir()
        (self.root / ".nsim/.nsim_version").write_text(release()["nsim"]["version"] + "\n")
        toolchain.record_selection(self.store, self.root)

    def test_subdirectory_and_nearest_invalid_project(self):
        nested = self.root / "a/b"
        nested.mkdir(parents=True)
        self.assertEqual(installer.find_project(nested), self.root)
        (self.root / "a/.verif-harness").mkdir()
        self.assertEqual(installer.find_project(nested), self.root / "a")
        self.assertEqual(toolchain.discover(nested), self.root / "a")

    def test_nsim_drift_blocks_store_and_cli(self):
        toolchain.verify(self.store)
        (self.root / ".nsim/.nsim_version").write_text("9.9.9\n")
        with self.assertRaises(HarnessError):
            self.store.require()

    def test_release_digest_drift_is_not_an_upgrade(self):
        value = toolchain.selected(self.store)
        value["release_sha256"] = "0" * 64
        (self.store.state / "toolchain.json").write_text(json.dumps(value))
        with self.assertRaises(HarnessError):
            toolchain.verify(self.store)

    def test_switch_failure_restores_only_version_files(self):
        before = toolchain.selected(self.store)
        transition = self.store.state / "version-transition.json"
        paths = [self.store.state / "toolchain.json", self.root / ".nsim/.nsim_version",
                 self.root / ".nsim/verif-harness.json"]
        journal = {"before": before, "files": {str(p): p.read_text() for p in paths},
                   "after": {str(paths[1]): "9.9.9\n"}}
        transition.write_text(json.dumps(journal))
        with self.assertRaises(HarnessError):
            toolchain.verify(self.store)
        paths[1].write_text("9.9.9\n")
        database = self.store.database.read_bytes()
        result = toolchain.switch(self.store, None, recover=True)
        self.assertEqual(result["status"], "RESTORED")
        self.assertEqual(database, self.store.database.read_bytes())
        toolchain.verify(self.store)

    def test_recovery_rejects_paths_outside_project(self):
        outside = Path(self.temp.name) / "keep"
        outside.write_text("unchanged")
        (self.store.state / "version-transition.json").write_text(json.dumps({
            "before": toolchain.selected(self.store), "files": {str(outside): "bad"}}))
        with self.assertRaises(HarnessError):
            toolchain.switch(self.store, None, recover=True)
        self.assertEqual(outside.read_text(), "unchanged")

    def test_recovery_preserves_unexpected_version_edits(self):
        paths = [self.store.state / 'toolchain.json', self.root / '.nsim/.nsim_version',
                 self.root / '.nsim/verif-harness.json']
        journal = {'before': toolchain.selected(self.store), 'files': {str(p): p.read_text() for p in paths}}
        (self.store.state / 'version-transition.json').write_text(json.dumps(journal))
        paths[1].write_text('unexpected\n')
        with self.assertRaisesRegex(HarnessError, '另行修改'):
            toolchain.switch(self.store, None, recover=True)
        self.assertEqual(paths[1].read_text(), 'unexpected\n')

    def test_switch_rejects_path_traversal(self):
        with self.assertRaises(HarnessError):
            toolchain.switch(self.store, "../../another")

    def test_switch_changes_pair_without_rewriting_database(self):
        home = Path(self.temp.name) / 'tools'
        target = home / 'versions/3.0.1'
        package = target / 'package'
        package.mkdir(parents=True)
        manifest = {**release(), 'version': '3.0.1',
                    'nsim': {**release()['nsim'], 'version': '0.2.0'}}
        (package / 'release.json').write_text(json.dumps(manifest))
        nsim_root = Path(self.temp.name) / 'nsim'
        nsim = nsim_root / 'versions' / manifest['nsim']['version']
        nsim.mkdir(parents=True)
        (nsim / 'receipt.json').write_text(json.dumps({'wheel_sha256': manifest['nsim']['wheel_sha256']}))
        (target / 'receipt.json').write_text(json.dumps({'version': '3.0.1', 'files': {
            'release.json': toolchain.sha(package / 'release.json')}, 'nsim_root': str(nsim_root)}))
        database = self.store.database.read_bytes()
        with patch.dict(os.environ, {'VERIF_HARNESS_HOME': str(home)}), \
                patch('verif_harness.dashboard.unregister_dashboard_project'):
            result = toolchain.switch(self.store, '3.0.1')
        self.assertEqual(result['status'], 'SWITCHED')
        self.assertEqual(toolchain.selected(self.store)['version'], '3.0.1')
        self.assertEqual(toolchain.selected(self.store)['nsim_version'], '0.2.0')
        self.assertEqual((self.root / '.nsim/.nsim_version').read_text(), '0.2.0\n')
        guard = json.loads((self.root / '.nsim/verif-harness.json').read_text())
        self.assertEqual(guard['version'], '3.0.1')
        self.assertEqual(guard['nsim_version'], '0.2.0')
        self.assertEqual(database, self.store.database.read_bytes())
        self.assertEqual(len(list((self.store.state / 'version-backups').glob('*/model.sqlite3'))), 1)
        self.assertFalse((self.store.state / 'version-transition.json').exists())

    def test_active_nsim_lease_blocks_switch(self):
        import fcntl
        with (self.store.state / 'tool-use.lock').open('a+') as nsim:
            fcntl.flock(nsim, fcntl.LOCK_SH | fcntl.LOCK_NB)
            with self.assertRaisesRegex(HarnessError, 'nsim'):
                toolchain.switch(self.store, '3.0.1')

    def test_control_operation_and_open_database_block_switch(self):
        for context in (self.store.operation, self.store.connect, self.store.read_connect):
            with self.subTest(context=context.__name__), context():
                with self.assertRaisesRegex(HarnessError, '控制面'):
                    toolchain.switch(self.store, '3.0.1')
        # All leases were released on context exit.
        with toolchain.tool_lock(self.store):
            pass

    def test_transition_blocks_new_database_connections(self):
        with toolchain.tool_lock(self.store):
            with self.assertRaisesRegex(HarnessError, '切换版本'):
                self.store.connect()

    def test_codex_registration_does_not_copy_repository_cwd(self):
        config = self.root / '.codex/config.toml'
        config.parent.mkdir()
        config.write_text((ROOT / '.codex/config.toml').read_text() + '\n# user preference\n')
        with patch.object(toolchain, 'run'):
            toolchain.configure_agent(self.store, 'codex')
            self.assertNotIn('[mcp_servers.xverif]', config.read_text())
            self.assertIn('# user preference', config.read_text())
            toolchain.configure_agent(self.store, 'codex')
        self.assertTrue((self.root / '.agents/skills/verif-harness/SKILL.md').is_file())

    def test_profile_setup_does_not_follow_external_directories(self):
        external = Path(self.temp.name) / 'external'
        external.mkdir()
        (self.root / '.agents').mkdir()
        (self.root / '.agents/skills').symlink_to(external)
        with patch.object(toolchain, 'run'), self.assertRaisesRegex(HarnessError, '符号链接'):
            toolchain.configure_agent(self.store, 'codex')
        self.assertEqual(list(external.iterdir()), [])

    def test_explicit_refresh_adopts_legacy_skill_links_and_records_old_paths(self):
        parent = self.root / '.agents/skills'
        parent.mkdir(parents=True)
        old = Path(self.temp.name) / 'old-checkout/verif-harness'
        old.mkdir(parents=True)
        (old / 'SKILL.md').write_text('legacy skill\n')
        target = parent / 'verif-harness'
        target.symlink_to(old)
        with patch.object(toolchain, 'run'):
            with self.assertRaisesRegex(HarnessError, 'bootstrap --refresh'):
                toolchain.configure_agent(self.store, 'codex')
            toolchain.configure_agent(self.store, 'codex', adopt_existing=True)
        self.assertEqual(target.resolve(), ROOT / 'skills/verif-harness')
        self.assertEqual((old / 'SKILL.md').read_text(), 'legacy skill\n')
        record = json.loads((self.store.state / 'managed-profiles.json').read_text())
        self.assertEqual(record['prior_links']['.agents/skills/verif-harness'], [str(old.resolve())])

    def test_restart_prepares_dashboard_then_enters_configured_agent(self):
        value = json.loads((self.store.state / 'project.json').read_text())
        value['runtime'] = 'codex'
        (self.store.state / 'project.json').write_text(json.dumps(value))
        calls = []
        with patch.object(toolchain, 'nsim_command'), patch.object(toolchain, 'configure_agent', side_effect=lambda *a: calls.append('profiles')), \
                patch('verif_harness.dashboard_startup.ensure_dashboard_ready', side_effect=lambda *a: calls.append('dashboard') or {'status': 'READY', 'message': 'Ready', 'url': 'http://localhost', 'launch_status': 'REUSED'}), \
                patch('verif_harness.agent_service.interactive', side_effect=lambda *a: calls.append('agent') or 0), \
                patch('os.chdir'), patch('verif_harness.cli.display_dashboard_ready'):
            self.assertEqual(toolchain.restart(self.store), 0)
        self.assertEqual(calls, ['profiles', 'dashboard', 'agent'])

    def test_installed_bytes_are_verified(self):
        home = Path(self.temp.name) / "installation"
        destination = home / "versions/3.0.0"
        (destination / "package").mkdir(parents=True)
        source = destination / "package/entry.py"
        source.write_text("pass\n")
        receipt = {"schema": 1, "version": "3.0.0", "python": __import__('sys').executable,
                   "files": {"entry.py": installer.digest(source)}}
        (destination / "receipt.json").write_text(json.dumps(receipt))
        self.assertEqual(installer.versions(home), ["3.0.0"])
        source.write_text("changed")
        with self.assertRaises(installer.InstallError):
            installer.installed(home, "3.0.0")

    def test_project_pin_controls_dispatch_despite_environment(self):
        with patch.dict(os.environ, {"VERIF_HARNESS_VERSION": "9.9.9"}), \
                patch.object(installer, "installed", side_effect=RuntimeError("selected")) as load:
            with self.assertRaises(RuntimeError):
                installer.launch(Path(self.temp.name), ["status", "--project-root", str(self.root)])
            self.assertEqual(load.call_args.args[1], release()["version"])

    def test_restart_and_bootstrap_options(self):
        parser = build_parser()
        self.assertTrue(parser.parse_args(["restart", "--no-agent"]).no_agent)
        self.assertEqual(parser.parse_args(["bootstrap", "--rtl-filelist", "rtl.f"]).rtl_filelist, "rtl.f")

    def test_wizard_collects_filelist_before_dut_and_requires_confirmation(self):
        args = build_parser().parse_args(["bootstrap", "--runtime", "none", '--project-root', str(self.root)])
        with patch("builtins.input", side_effect=["rtl", "rtl/rtl.f", "dut", "rtl/dut.sv", ".",
                                                  "skip", "skip", "skip", "skip", "skip", "skip", "no"]), \
                patch("builtins.print"):
            with self.assertRaises(HarnessError):
                toolchain.wizard(args)
        self.assertEqual(args.rtl_filelist, "rtl/rtl.f")


if __name__ == "__main__":
    unittest.main()
