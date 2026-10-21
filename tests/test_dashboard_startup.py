"""Setup must restore Dashboard independently before entering the Agent CLI."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

from tests import test_dashboard as fixtures
from verif_harness.cli import main
from verif_harness import dashboard, dashboard_startup as startup
from verif_harness.store import HarnessError, ProjectStore


ROOT = Path(__file__).resolve().parents[1]


class DashboardStartupTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DashboardTest()
        self.fixture.setUp()
        self.store = self.fixture.store
        self.port = self.fixture.server.server_address[1]
        self.project_id = dashboard.dashboard_project_id(self.store.root)
        dashboard.ensure_dashboard_running(self.store, "127.0.0.1", self.port)

    def tearDown(self):
        self.fixture.tearDown()

    def test_healthy_reuse_uses_actual_authorized_requests_without_plan_reads(self):
        before = self.store.database.read_bytes()
        with (
            mock.patch.object(ProjectStore, "dashboard_snapshot", side_effect=AssertionError("heavy snapshot")),
            mock.patch.object(ProjectStore, "workstream", side_effect=AssertionError("heavy plan")),
            mock.patch.object(dashboard.subprocess, "Popen") as launch,
            mock.patch.object(startup, "_read_endpoint", wraps=startup._read_endpoint) as requests,
        ):
            result = startup.ensure_dashboard_ready(self.store)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["launch_status"], "REUSED")
        self.assertEqual(result["project_id"], self.project_id)
        self.assertIn(f":{self.port}/", result["url"])
        self.assertTrue(all(result["checks"].values()))
        self.assertFalse(result["ssh_forward_checked"])
        self.assertEqual(len(requests.call_args_list), 3 + len(dashboard.DASHBOARD_ASSETS))
        launch.assert_not_called()
        self.assertEqual(self.store.database.read_bytes(), before)

    def test_reuse_keeps_process_start_time_and_invalidates_only_current_projection(self):
        self.fixture.server._snapshot_cache[self.project_id] = ('old', {'version':'old'})
        self.fixture.server._snapshot_cache['another-project'] = ('other', {'version':'other'})
        runtime = self.store.state / dashboard.DASHBOARD_RUNTIME_FILE
        before = json.loads(runtime.read_text())
        self.assertEqual(startup.ensure_dashboard_ready(self.store)['launch_status'], 'REUSED')
        after = json.loads(runtime.read_text())
        self.assertEqual(before['started_at'], after['started_at'])
        self.assertEqual(after['build'], dashboard.dashboard_build_identity())
        self.assertNotIn(self.project_id, self.fixture.server._snapshot_cache)
        self.assertIn('another-project', self.fixture.server._snapshot_cache)

    def test_state_endpoint_requires_authorization_and_current_project(self):
        origin = urllib.parse.urlsplit(self.fixture.url)
        url = urllib.parse.urlunsplit((origin.scheme, origin.netloc, '/api/project-state', '', ''))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(url, timeout=3)
        self.assertEqual(caught.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.fixture.get('/api/project-state?project=' + '0' * 24)
        self.assertEqual(caught.exception.code, 400)

    def test_wrong_database_revision_or_state_version_blocks_setup(self):
        original = startup._read_endpoint
        for field in ('database', 'workstreams', 'state_version'):
            def incorrect(origin, path):
                data, content_type = original(origin, path)
                if path.startswith('/api/project-state?'):
                    body = json.loads(data)
                    if field == 'database':
                        body['result']['database']['inode'] += 1
                    elif field == 'workstreams':
                        body['result']['workstreams'][0]['revision'] += 1
                    else:
                        body['result']['state_version'] += 1
                    data = json.dumps(body).encode()
                return data, content_type
            with self.subTest(field=field), mock.patch.object(startup, '_read_endpoint', side_effect=incorrect):
                with self.assertRaisesRegex(HarnessError, '状态版本不一致'):
                    startup.ensure_dashboard_ready(self.store)

    def test_concurrent_state_write_retries_small_headers_without_plan_reads(self):
        original = startup._read_endpoint
        writes = []
        def changing(origin, path):
            if path.startswith('/api/project-state?') and not writes:
                with self.store.connect() as db:
                    db.execute("UPDATE workstreams SET objective=objective||' updated' WHERE name='VCHK'")
                writes.append(True)
            return original(origin, path)
        with mock.patch.object(ProjectStore, 'workstream', side_effect=AssertionError('large plan read')), \
                mock.patch.object(startup, '_read_endpoint', side_effect=changing) as request:
            self.assertEqual(startup.ensure_dashboard_ready(self.store)['status'], 'READY')
        self.assertEqual(sum(call.args[1].startswith('/api/project-state?') for call in request.call_args_list), 2)

    def test_setup_notifies_open_page_to_reread_unchanged_database(self):
        with self.fixture.get('/api/events?project=' + self.project_id) as response:
            before = self.fixture.read_snapshot_event(response)
            startup.ensure_dashboard_ready(self.store)
            refreshed = self.fixture.read_snapshot_event(response)
        self.assertEqual(refreshed['version'], before['version'])
        self.assertEqual(refreshed['dashboard_project_id'], self.project_id)

    def test_refresh_during_snapshot_read_discards_inflight_projection(self):
        original = ProjectStore.dashboard_snapshot
        calls = []
        def refreshing(store):
            result = original(store)
            calls.append(True)
            if len(calls) == 1:
                self.fixture.server.refresh_project_state(self.project_id)
            return result
        with mock.patch.object(ProjectStore, 'dashboard_snapshot', autospec=True, side_effect=refreshing):
            with self.fixture.get('/api/snapshot') as response:
                self.assertEqual(json.load(response)['dashboard_project_id'], self.project_id)
        self.assertEqual(len(calls), 2)

    def test_continuous_writes_fail_closed_after_bounded_retries(self):
        original = startup._read_endpoint
        def changing(origin, path):
            if path.startswith('/api/project-state?'):
                with self.store.connect() as db:
                    db.execute("UPDATE workstreams SET objective=objective||' updated' WHERE name='VCHK'")
            return original(origin, path)
        with mock.patch.object(startup, '_read_endpoint', side_effect=changing) as request:
            with self.assertRaisesRegex(HarnessError, '状态持续变化'):
                startup.ensure_dashboard_ready(self.store)
        self.assertEqual(sum(call.args[1].startswith('/api/project-state?') for call in request.call_args_list), 3)

    def test_service_health_reports_loaded_build_without_rehashing_files(self):
        with mock.patch.object(dashboard, 'dashboard_build_identity', return_value={'digest': 'changed-on-disk'}):
            health = dashboard._dashboard_health('127.0.0.1', self.port)
        self.assertEqual(health['build'], dashboard.LOADED_DASHBOARD_BUILD)

    def test_upgrade_requires_authorized_access_and_safe_process_before_stopping(self):
        health = dashboard._dashboard_health('127.0.0.1', self.port)
        with mock.patch.object(startup.os, 'kill') as kill, mock.patch.object(startup, 'ensure_dashboard_running') as launch:
            with mock.patch.object(startup, 'dashboard_access_token', return_value='invalid-token'):
                with self.assertRaisesRegex(HarnessError, 'HTTP 403'):
                    startup._upgrade_service(self.store, '127.0.0.1', self.port, health, dashboard.LOADED_DASHBOARD_BUILD)
            with self.assertRaisesRegex(HarnessError, '后台进程'):
                startup._upgrade_service(self.store, '127.0.0.1', self.port, health, dashboard.LOADED_DASHBOARD_BUILD)
            kill.assert_not_called()
            launch.assert_not_called()

    def test_upgrade_blocks_incompatible_shared_database_without_stopping(self):
        health = dashboard._dashboard_health('127.0.0.1', self.port)
        with self.store.connect() as db:
            db.execute("UPDATE meta SET value='incompatible' WHERE key='schema_version'")
        with mock.patch.object(startup.os, 'kill') as kill:
            with self.assertRaisesRegex(HarnessError, '不兼容'):
                startup._upgrade_service(self.store, '127.0.0.1', self.port, health, dashboard.LOADED_DASHBOARD_BUILD)
            kill.assert_not_called()

    def test_failed_upgrade_keeps_existing_project_registration(self):
        health = dashboard._dashboard_health('127.0.0.1', self.port)
        health['pid'] = 123456789
        def failed(*args):
            dashboard.unregister_dashboard_project(self.store)
            return {'status': 'FAILED'}
        with (mock.patch.object(startup, '_dashboard_health', return_value=health),
              mock.patch.object(startup, '_port_accepts_connections', return_value=False),
              mock.patch.object(startup.os, 'kill') as kill,
              mock.patch.object(startup, 'ensure_dashboard_running', side_effect=failed)):
            with self.assertRaisesRegex(HarnessError, '更新后的代码版本或项目注册'):
                startup._upgrade_service(self.store, '127.0.0.1', self.port, health, dashboard.LOADED_DASHBOARD_BUILD)
        kill.assert_called_once()
        self.assertEqual([p['id'] for p in dashboard.registered_dashboard_projects()], [self.project_id])

    def test_older_service_upgrades_on_same_port_preserving_all_projects(self):
        self.check_service_upgrade({'digest': 'old-version'})

    def test_legacy_service_without_build_upgrades_on_same_port(self):
        self.check_service_upgrade(None)

    def check_service_upgrade(self, old_build):
        self.store.review_workstream('VCHK', 'approve', 'test-owner', 'approved test scope')
        self.fixture.server.shutdown()
        self.fixture.server.server_close()
        self.fixture.thread.join(timeout=2)
        other = ProjectStore(self.store.root / 'second-project')
        other.root.mkdir()
        other.bootstrap(project_name='second', runtime='none', rtl_roots=[str(self.store.root / 'rtl')],
                        verif_root='verification', dut_top='dut', dut_top_file=str(self.store.root / 'rtl/dut.sv'))
        dashboard.register_dashboard_project(other)
        def persisted_facts():
            # Reopening a service can change SQLite's physical transaction header;
            # compare every stored row/schema instead of the database file bytes.
            result = []
            for store in (self.store, other):
                with store.read_connect() as db:
                    result.append(sorted(db.iterdump()))
            return result
        originals = persisted_facts()
        program = (
            'import sys,json; from pathlib import Path; from verif_harness.store import ProjectStore; '
            'from verif_harness.dashboard import create_dashboard_server; '
            'server=create_dashboard_server(ProjectStore(Path(sys.argv[1])),"127.0.0.1",int(sys.argv[2])); '
            'server.build_identity=json.loads(sys.argv[3]); server.serve_forever()'
        )
        child = subprocess.Popen([sys.executable, '-c', program, str(self.store.root), str(self.port),
                                  json.dumps(old_build)], cwd=ROOT, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        launches = []
        popen = subprocess.Popen
        def tracked_launch(*args, **kwargs):
            process = popen(*args, **kwargs)
            launches.append(process)
            return process
        try:
            for _attempt in range(60):
                health = dashboard._dashboard_health('127.0.0.1', self.port)
                if health or child.poll() is not None:
                    break
                time.sleep(.05)
            self.assertIsNone(child.poll(), 'old test service failed to start')
            self.assertEqual(health['pid'], child.pid)
            with mock.patch.object(dashboard.subprocess, 'Popen', side_effect=tracked_launch):
                result = startup.ensure_dashboard_ready(self.store, '127.0.0.1', self.port)
            self.assertEqual(result['launch_status'], 'RESTARTED')
            self.assertEqual(urllib.parse.urlsplit(result['url']).port, self.port)
            health = dashboard._dashboard_health('127.0.0.1', self.port)
            self.assertEqual(health['build'], dashboard.dashboard_build_identity())
            self.assertEqual(set(health['projects']), {self.project_id, dashboard.dashboard_project_id(other.root)})
            self.assertEqual(persisted_facts(), originals)
            self.assertEqual(startup.ensure_dashboard_ready(self.store)['launch_status'], 'REUSED')
            child.wait(timeout=3)
        finally:
            health = dashboard._dashboard_health('127.0.0.1', self.port)
            if dashboard._is_owned_dashboard_hub(health) and health['pid'] != os.getpid():
                os.kill(health['pid'], 15)
                deadline = time.monotonic() + 4
                while dashboard._port_accepts_connections('127.0.0.1', self.port) and time.monotonic() < deadline:
                    time.sleep(.05)
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=3)
            for process in launches:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=3)
            dashboard.unregister_dashboard_project(other)

    def test_missing_registration_is_restored_without_duplicate_server(self):
        dashboard.unregister_dashboard_project(self.store)
        self.assertEqual(self.fixture.server.projects(), [])
        with mock.patch.object(dashboard.subprocess, "Popen") as launch:
            result = startup.ensure_dashboard_ready(self.store)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(self.fixture.server.projects()[0]["id"], self.project_id)
        launch.assert_not_called()

    def test_recorded_port_conflict_does_not_switch_or_kill_other_service(self):
        for health, message in (
            (None, "非 Dashboard"),
            ({"schema":dashboard.DASHBOARD_HUB_SCHEMA, "owner_id":"another-account"}, "另一个系统账号"),
        ):
            with (
                self.subTest(health=health),
                mock.patch.object(dashboard, "_dashboard_health", return_value=health) as probe,
                mock.patch.object(dashboard, "_port_accepts_connections", return_value=True),
                mock.patch.object(dashboard.os, "kill") as kill,
                mock.patch.object(dashboard.subprocess, "Popen") as launch,
            ):
                with self.assertRaisesRegex(HarnessError, message):
                    startup.ensure_dashboard_ready(self.store)
                self.assertEqual([call.args[1] for call in probe.call_args_list], [self.port])
                kill.assert_not_called()
                launch.assert_not_called()

    def test_authentication_failure_is_not_reported_as_ready(self):
        with mock.patch.object(startup, "dashboard_access_token", return_value="invalid-token"):
            with self.assertRaisesRegex(HarnessError, "HTTP 403"):
                startup.ensure_dashboard_ready(self.store)

    def test_unreadable_registration_and_malformed_configuration_have_clear_errors(self):
        for error, message in (
            (PermissionError("private details"), "文件权限"),
            (ValueError("private details"), "配置或服务响应格式错误"),
        ):
            with self.subTest(error=error), mock.patch.object(startup, "ensure_dashboard_running", side_effect=error):
                with self.assertRaisesRegex(HarnessError, message) as caught:
                    startup.ensure_dashboard_ready(self.store)
                self.assertNotIn("private details", str(caught.exception))

    def test_wrong_project_cannot_satisfy_readiness(self):
        read = startup._read_endpoint

        def incorrect(origin, path):
            data, content_type = read(origin, path)
            if path == "/api/projects":
                payload = json.loads(data)
                payload["projects"][0]["root"] = str(self.store.root / "another-project")
                data = json.dumps(payload).encode()
            return data, content_type

        with mock.patch.object(startup, "_read_endpoint", side_effect=incorrect):
            with self.assertRaisesRegex(HarnessError, "未返回当前项目"):
                startup.ensure_dashboard_ready(self.store)

    def test_page_errors_and_redirects_are_not_ready(self):
        original = dashboard.DashboardHandler.do_GET
        for path, code in (("/api/projects", 302), ("/?", 500), ("/assets/", 404)):
            def fail(handler):
                if handler.path.startswith(path):
                    handler.send_response(code)
                    handler.send_header("Content-Length", "0")
                    handler.send_header("Location", "http://127.0.0.1:1/do-not-send-token")
                    handler.end_headers()
                else:
                    original(handler)

            with self.subTest(path=path), mock.patch.object(dashboard.DashboardHandler, "do_GET", fail):
                with self.assertRaisesRegex(HarnessError, f"HTTP {code}"):
                    startup.ensure_dashboard_ready(self.store)

    def test_new_project_skips_but_partial_or_bad_database_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(startup, "ensure_dashboard_running") as launch:
            store = ProjectStore(Path(directory))
            self.assertEqual(startup.ensure_dashboard_ready(store)["status"], "SKIPPED")
            self.assertFalse(store.state.exists())
            store.state.mkdir()
            (store.state / "project.json").write_text("{}")
            with self.assertRaisesRegex(HarnessError, "初始化记录不完整"):
                startup.ensure_dashboard_ready(store)
            store.database.write_text("not a database")
            with self.assertRaisesRegex(HarnessError, "数据库无法读取"):
                startup.ensure_dashboard_ready(store)
            launch.assert_not_called()

    def test_cli_explains_remote_access_without_claiming_the_ssh_tunnel(self):
        with mock.patch.dict(os.environ, {"SSH_CONNECTION":"test-session"}), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["dashboard", "--project-root", str(self.store.root), "--ensure-ready"]), 0)
        self.assertIn("Dashboard 已就绪", output.getvalue())
        self.assertIn("已复用现有 Dashboard，未重启服务", output.getvalue())
        self.assertIn(f"{self.port}:127.0.0.1:{self.port}", output.getvalue())
        self.assertIn("本机 SSH 端口转发需要保持连接", output.getvalue())

    def test_crashed_server_is_restored_on_same_port_and_survives_launcher_exit(self):
        self.fixture.server.shutdown()
        self.fixture.server.server_close()
        self.fixture.thread.join(timeout=2)
        runtime_path = self.store.state / dashboard.DASHBOARD_RUNTIME_FILE
        try:
            command = [sys.executable, str(ROOT / "scripts/verif_harness.py"), "dashboard",
                       "--project-root", str(self.store.root), "--ensure-ready"]
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("独立后台运行", result.stdout)
            runtime = json.loads(runtime_path.read_text())
            self.assertEqual(runtime["port"], self.port)
            self.assertNotEqual(runtime["pid"], os.getpid())
            if hasattr(os, "getpgid"):
                self.assertEqual(os.getpgid(runtime["pid"]), runtime["pid"])
            # The setup/launcher has exited; the independent server remains reachable.
            self.assertEqual(startup.ensure_dashboard_ready(self.store)["launch_status"], "REUSED")
        finally:
            health = dashboard._dashboard_health("127.0.0.1", self.port)
            if dashboard._is_owned_dashboard_hub(health) and health["pid"] != os.getpid():
                dashboard.stop_dashboard(self.store, "127.0.0.1", self.port)


if __name__ == "__main__":
    unittest.main()
