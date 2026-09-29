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
import unittest
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
        self.assertEqual(len(requests.call_args_list), 2 + len(dashboard.DASHBOARD_ASSETS))
        launch.assert_not_called()
        self.assertEqual(self.store.database.read_bytes(), before)

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
