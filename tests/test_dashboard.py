from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from verif_harness.cli import bootstrap_dashboard, main
from verif_harness.dashboard import (
    DASHBOARD_HUB_SCHEMA, DASHBOARD_REGISTRY_ENV, create_dashboard_server,
    dashboard_owner_id, dashboard_project_id, dashboard_status, dashboard_url,
    ensure_dashboard_running, register_dashboard_project, stop_dashboard,
)
from verif_harness.store import HarnessError, ProjectStore


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/verif_harness.py"


class DashboardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.registry = self.root / "dashboard-registry"
        self.environment = mock.patch.dict(os.environ, {
            DASHBOARD_REGISTRY_ENV: str(self.registry),
        })
        self.environment.start()
        (self.root / "rtl").mkdir()
        (self.root / "rtl/dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
        self.store = ProjectStore(self.root)
        self.store.bootstrap(
            project_name="alpha", runtime="none", rtl_roots=["rtl"], verif_root="verification",
            dut_top="dut", dut_top_file="rtl/dut.sv",
        )
        self.plan = self.store.design_workstream("VCHK", None, [], [], [])
        self.server = create_dashboard_server(self.store, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = dashboard_url(self.server)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.environment.stop()
        self.temporary.cleanup()

    def get(self, path: str) -> urllib.request.addinfourl:
        request = urllib.request.Request(
            self.url + path.lstrip("/"), headers={"X-Verif-Token": self.server.write_token},
        )
        return urllib.request.urlopen(request, timeout=3)

    def post(self, path: str, payload: dict, token: str | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Verif-Token"] = token
        request = urllib.request.Request(
            self.url + path.lstrip("/"), data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.loads(response.read())

    @staticmethod
    def read_snapshot_event(response: urllib.request.addinfourl) -> dict:
        event = ""
        data: list[str] = []
        while True:
            raw = response.readline()
            if not raw:
                raise AssertionError("Dashboard event stream closed before the next snapshot")
            line = raw.decode("utf-8").rstrip("\r\n")
            if not line:
                if event == "snapshot" and data:
                    return json.loads("\n".join(data))
                event = ""
                data = []
            elif line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data.append(line.split(":", 1)[1].lstrip())

    def design_minimal_vdoc(self) -> dict:
        def node(
            key: str, title: str, role: str, parent_key: str, statement: str,
        ) -> dict:
            return {
                "key": key, "title": title, "role": role,
                "parent_key": parent_key, "document_key": "verification-plan",
                "required": True, "statement": statement,
                "purpose": "明确当前 DUT 的验证范围并支持独立评审。",
                "scope": ["当前 DUT 的接口与验证边界"],
                "acceptance_criteria": ["范围、依据和验证责任均明确"],
                "source_refs": ["rtl/dut.sv", "verification_plan.md#dut-scope"],
                "work_content": ["当前 DUT 的接口、范围和验证责任"],
                "implementation_approach": ["对照 DUT 顶层和验证计划逐项核对"],
                "deliverables": ["验证计划中的 DUT 范围说明"],
                "progress_measures": [{
                    "id": f"{key}-reviewed", "label": "已确认范围",
                    "unit": "项", "target": "全部", "source": "verification_plan.md",
                }],
                "quality_checks": ["没有遗漏必需接口或验证责任"],
                "suggested_mode": "review", "evidence_claim": "document-review",
            }

        proposal = {
            "schema": "DesiredStateProposal/1", "workstream": "VDOC",
            "nodes": [
                node(
                    "dut-scope-plan", "DUT 验证范围撰写方案",
                    "document-writing-plan", "verification-plan",
                    "验证计划将明确当前 DUT 的接口和验证边界。",
                ),
            ],
        }
        path = self.root / "minimal-vdoc-plan.json"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        return self.store.design_workstream(
            "VDOC", None, [], [], [], desired_file=str(path),
        )

    def register_minimal_vdoc_delivery(self) -> dict:
        proposal = {
            "schema": "DesiredStateProposal/1", "workstream": "VDOC",
            "nodes": [{
                "key": "dut-scope-content", "title": "DUT 验证范围正文",
                "role": "document-deliverable", "parent_key": "dut-scope-plan",
                "document_key": "verification-plan", "required": True,
                "statement": "验证计划正文已经明确当前 DUT 的接口和验证边界。",
                "purpose": "明确当前 DUT 的验证范围并支持独立评审。",
                "scope": ["当前 DUT 的接口与验证边界"],
                "acceptance_criteria": ["范围、依据和验证责任均明确"],
                "source_refs": ["rtl/dut.sv", "verification_plan.md#dut-scope"],
                "work_content": ["当前 DUT 的接口、范围和验证责任"],
                "implementation_approach": ["对照 DUT 顶层和验证计划逐项核对"],
                "deliverables": ["验证计划中的 DUT 范围说明"],
                "progress_measures": [{
                    "id": "dut-scope-content-reviewed", "label": "已确认范围",
                    "unit": "项", "target": "全部", "source": "verification_plan.md",
                }],
                "quality_checks": ["没有遗漏必需接口或验证责任"],
                "suggested_mode": "review", "evidence_claim": "document-review",
            }],
        }
        path = self.root / "minimal-vdoc-delivery.json"
        path.write_text(json.dumps(proposal), encoding="utf-8")
        return self.store.design_workstream(
            "VDOC", None, [], [], [], desired_file=str(path),
        )

    def test_background_launcher_reuses_same_project_dashboard(self) -> None:
        port = self.server.server_address[1]
        result = ensure_dashboard_running(self.store, "127.0.0.1", port)
        self.assertEqual(result["schema"], "DashboardLaunch/1")
        self.assertEqual(result["status"], "REUSED")
        self.assertEqual(result["project"], str(self.store.root))
        self.assertTrue(result["url"].startswith(self.url + "?project="))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(result["url"]).query)
        self.assertEqual(query["token"], [self.server.write_token])
        self.assertTrue(result["shared_service"])
        self.assertFalse(result["browser_opened"])

    def test_explicit_port_rejects_another_os_users_dashboard(self) -> None:
        foreign = {
            "schema": DASHBOARD_HUB_SCHEMA, "status": "ok", "pid": 27182,
            "owner_id": "f" * 24, "projects": [],
        }
        with mock.patch("verif_harness.dashboard._dashboard_health", return_value=foreign):
            result = ensure_dashboard_running(self.store, "127.0.0.1", 8765)
        self.assertEqual(result["status"], "PORT_CONFLICT")
        self.assertEqual(result["conflict"], "OTHER_USER_DASHBOARD")
        self.assertIn("另一个系统账号", result["message"])

    def test_automatic_port_skips_other_os_users_dashboard(self) -> None:
        project_id = dashboard_project_id(self.store.root)
        foreign = {
            "schema": DASHBOARD_HUB_SCHEMA, "status": "ok", "pid": 27182,
            "owner_id": "f" * 24, "projects": [],
        }
        owned = {
            "schema": DASHBOARD_HUB_SCHEMA, "status": "ok", "pid": 31415,
            "owner_id": dashboard_owner_id(), "projects": [project_id],
        }
        process = mock.Mock(pid=31415)
        process.poll.return_value = None
        started = False

        def health(_host: str, port: int):
            if port == 8765:
                return foreign
            if port == 8766 and started:
                return owned
            return None

        def launch(*_args: object, **_kwargs: object) -> mock.Mock:
            nonlocal started
            started = True
            return process

        with (
            mock.patch("verif_harness.dashboard._dashboard_health", side_effect=health),
            mock.patch("verif_harness.dashboard._port_accepts_connections", return_value=False),
            mock.patch("verif_harness.dashboard.subprocess.Popen", side_effect=launch) as popen,
        ):
            result = ensure_dashboard_running(self.store)
        self.assertEqual(result["status"], "STARTED")
        self.assertTrue(result["auto_selected_port"])
        self.assertEqual(result["skipped_ports"], [
            {"port": 8765, "reason": "OTHER_USER_DASHBOARD"},
        ])
        self.assertIn("127.0.0.1:8766", result["url"])
        self.assertIn("8766", popen.call_args.args[0])

    def test_background_launcher_registers_other_project_on_same_fixed_port(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            other_root = Path(directory)
            (other_root / "rtl").mkdir()
            (other_root / "rtl/dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
            other = ProjectStore(other_root)
            other.bootstrap(
                runtime="none", rtl_roots=["rtl"], verif_root="verification",
                dut_top="dut", dut_top_file="rtl/dut.sv",
            )
            result = ensure_dashboard_running(other, "127.0.0.1", self.server.server_address[1])
            with self.get("/api/projects") as response:
                projects = json.loads(response.read())["projects"]
        self.assertEqual(result["status"], "REUSED")
        self.assertEqual({item["id"] for item in projects}, {
            dashboard_project_id(self.store.root), dashboard_project_id(other.root),
        })

    def test_background_launcher_starts_detached_process_and_records_runtime(self) -> None:
        process = mock.Mock(pid=31415)
        process.poll.return_value = None
        healthy = {
            "schema": DASHBOARD_HUB_SCHEMA, "status": "ok", "pid": 31415,
            "owner_id": dashboard_owner_id(),
            "projects": [dashboard_project_id(self.store.root)],
        }
        with (
            mock.patch("verif_harness.dashboard._dashboard_health", side_effect=[None, healthy]),
            mock.patch("verif_harness.dashboard._port_accepts_connections", return_value=False),
            mock.patch("verif_harness.dashboard.subprocess.Popen", return_value=process) as popen,
        ):
            result = ensure_dashboard_running(self.store, "127.0.0.1", 18765)
        self.assertEqual(result["status"], "STARTED")
        self.assertEqual(result["pid"], 31415)
        self.assertFalse(result["browser_opened"])
        invocation = popen.call_args.args[0]
        self.assertIn("dashboard", invocation)
        self.assertIn("--project-root", invocation)
        self.assertIn("--foreground", invocation)
        runtime_path = self.root / ".verif-harness/dashboard-runtime.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        self.assertEqual(runtime["schema"], "DashboardRuntime/3")
        self.assertEqual(runtime["port"], 18765)
        self.assertEqual(runtime["pid"], 31415)
        self.assertEqual(runtime["owner_id"], dashboard_owner_id())
        self.assertNotIn("token", urllib.parse.parse_qs(
            urllib.parse.urlsplit(runtime["url"]).query,
        ))
        self.assertNotIn(self.server.write_token, runtime_path.read_text(encoding="utf-8"))

    def test_background_launcher_rejects_old_single_project_dashboard(self) -> None:
        legacy = {"status": "ok", "project": "/tmp/legacy-project"}
        with mock.patch("verif_harness.dashboard._dashboard_health", return_value=legacy):
            result = ensure_dashboard_running(self.store, "127.0.0.1", 18765)
        self.assertEqual(result["status"], "PORT_CONFLICT")
        self.assertEqual(result["observed_project"], "/tmp/legacy-project")
        self.assertIn("旧版单项目 Dashboard", result["message"])

    def test_direct_dashboard_and_bootstrap_use_the_same_background_launcher(self) -> None:
        launched = {
            "schema": "DashboardLaunch/1", "status": "REUSED",
            "project": str(self.root), "url": "http://127.0.0.1:8765/",
        }
        with mock.patch(
            "verif_harness.dashboard.ensure_dashboard_running", return_value=launched,
        ) as ensure:
            with mock.patch("builtins.print"):
                self.assertEqual(main([
                    "dashboard", "--project-root", str(self.root),
                ]), 0)
            direct_call = ensure.call_args
            ensure.reset_mock()
            bootstrap_result = bootstrap_dashboard(
                self.store, "codex", True, False, None,
            )
            bootstrap_call = ensure.call_args
        self.assertEqual(bootstrap_result, launched)
        self.assertEqual(direct_call.args[1:], bootstrap_call.args[1:])

    def test_remote_bootstrap_access_url_preserves_selected_project(self) -> None:
        project_id = dashboard_project_id(self.store.root)
        access_url = (
            f"http://127.0.0.1:8765/?project={project_id}&token=example-account-token"
        )
        launched = {
            "schema": "DashboardLaunch/1", "status": "REUSED",
            "project": str(self.root),
            "url": access_url,
        }
        with (
            mock.patch("verif_harness.dashboard.ensure_dashboard_running", return_value=launched),
            mock.patch.dict(os.environ, {"SSH_CONNECTION": "client server"}),
        ):
            result = bootstrap_dashboard(self.store, "codex", True, False, None)
        self.assertEqual(result["access"]["url"], access_url)
        self.assertEqual(
            result["access"]["command"],
            "ssh -N -L 8765:127.0.0.1:8765 <remote-user>@<remote-host>",
        )
        self.assertEqual(result["access"]["single_hop"]["command"], result["access"]["command"])
        self.assertIn(
            "Host verification-server-direct",
            result["access"]["single_hop"]["ssh_config"],
        )
        self.assertIn(
            "LocalForward 8765 127.0.0.1:8765",
            result["access"]["single_hop"]["ssh_config"],
        )
        self.assertIn("Host verification-jump", result["access"]["double_hop"]["ssh_config"])
        self.assertIn("ProxyJump verification-jump", result["access"]["double_hop"]["ssh_config"])
        self.assertIn(
            "LocalForward 8765 127.0.0.1:8765",
            result["access"]["double_hop"]["ssh_config"],
        )
        self.assertEqual(result["access"]["double_hop"]["command"], "ssh -N verification-server")
        required = result["access"]["required_agent_output"]
        self.assertTrue(required["must_print"])
        self.assertEqual(required["items"], [
            "single_hop.ssh_config", "single_hop.command",
            "double_hop.ssh_config", "double_hop.command", "url",
        ])
        self.assertIn(result["access"]["single_hop"]["ssh_config"], required["message"])
        self.assertIn(result["access"]["double_hop"]["ssh_config"], required["message"])
        self.assertIn(access_url, required["message"])

    def test_remote_access_templates_use_the_selected_account_port(self) -> None:
        project_id = dashboard_project_id(self.store.root)
        launched = {
            "schema": "DashboardLaunch/1", "status": "STARTED",
            "project": str(self.root),
            "url": f"http://127.0.0.1:8766/?project={project_id}",
        }
        with (
            mock.patch("verif_harness.dashboard.ensure_dashboard_running", return_value=launched),
            mock.patch.dict(os.environ, {"SSH_CONNECTION": "client server"}),
        ):
            result = bootstrap_dashboard(self.store, "codex", True, False, None)
        self.assertEqual(result["access"]["remote_dashboard_port"], 8766)
        self.assertIn("8766:127.0.0.1:8766", result["access"]["single_hop"]["command"])
        self.assertIn(
            "LocalForward 8766 127.0.0.1:8766",
            result["access"]["single_hop"]["ssh_config"],
        )
        self.assertIn(
            "LocalForward 8766 127.0.0.1:8766",
            result["access"]["double_hop"]["ssh_config"],
        )

    def test_dashboard_status_and_stop_use_managed_runtime(self) -> None:
        runtime_path = self.root / ".verif-harness/dashboard-runtime.json"
        runtime_path.write_text(json.dumps({
            "schema": "DashboardRuntime/1", "pid": 31415,
            "host": "127.0.0.1", "port": 18765,
            "url": "http://127.0.0.1:18765/", "project": str(self.store.root),
            "log": str(self.root / ".verif-harness/dashboard.log"),
            "started_at": "2026-09-20T00:00:00+00:00",
        }) + "\n", encoding="utf-8")
        healthy = {
            "schema": DASHBOARD_HUB_SCHEMA, "status": "ok", "pid": 31415,
            "owner_id": dashboard_owner_id(),
            "projects": [dashboard_project_id(self.store.root)],
        }
        with mock.patch("verif_harness.dashboard._dashboard_health", return_value=healthy):
            observed = dashboard_status(self.store)
        self.assertEqual(observed["status"], "RUNNING")
        self.assertEqual(observed["pid"], 31415)

        with (
            mock.patch("verif_harness.dashboard._dashboard_health", side_effect=[healthy, healthy, None]),
            mock.patch("verif_harness.dashboard.os.kill") as kill,
        ):
            stopped = stop_dashboard(self.store)
        kill.assert_called_once_with(31415, signal.SIGTERM)
        self.assertEqual(stopped["status"], "STOPPED")
        self.assertFalse(runtime_path.exists())

    def test_project_switching_routes_reads_and_writes_to_separate_stores(self) -> None:
        other_root = self.root / "beta"
        (other_root / "rtl").mkdir(parents=True)
        (other_root / "rtl/dut_b.sv").write_text("module dut_b; endmodule\n", encoding="utf-8")
        other = ProjectStore(other_root)
        other.bootstrap(
            project_name="beta", runtime="none", rtl_roots=["rtl"],
            verif_root="verification", dut_top="dut_b", dut_top_file="rtl/dut_b.sv",
        )
        other.design_workstream("VCHK", None, [], [], [])
        other_registration = register_dashboard_project(other)
        current_id = dashboard_project_id(self.store.root)

        with self.get("/api/projects") as response:
            listed = json.loads(response.read())
        self.assertEqual({item["id"] for item in listed["projects"]}, {
            current_id, other_registration["id"],
        })

        with self.get(f"/api/snapshot?project={current_id}") as response:
            current_snapshot = json.loads(response.read())
        with self.get(f"/api/snapshot?project={other_registration['id']}") as response:
            other_snapshot = json.loads(response.read())
        self.assertEqual(current_snapshot["project"]["name"], "alpha")
        self.assertEqual(other_snapshot["project"]["name"], "beta")
        self.assertEqual(other_snapshot["project"]["dut"]["top_module"], "dut_b")

        changed = self.post("/api/human-actions", {
            "dashboard_project": current_id,
            "target": "VCHK", "action": "COMMENT", "reviewer": "alice",
            "reason": "只记录在 alpha 项目",
        }, self.server.write_token)
        self.assertEqual(changed["snapshot"]["dashboard_project_id"], current_id)
        self.assertEqual(len(self.store.human_actions()), 1)
        self.assertEqual(other.human_actions(), [])

        removed = self.post("/api/registrations/remove", {
            "dashboard_project": current_id,
        }, self.server.write_token)
        self.assertEqual(removed["result"]["status"], "UNREGISTERED")
        self.assertEqual(
            [item["id"] for item in removed["projects"]], [other_registration["id"]],
        )
        self.assertEqual(len(self.store.human_actions()), 1)
        self.assertEqual(other.human_actions(), [])

    def test_stopping_one_registered_project_keeps_shared_service_running(self) -> None:
        other_root = self.root / "remaining"
        (other_root / "rtl").mkdir(parents=True)
        (other_root / "rtl/dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
        other = ProjectStore(other_root)
        other.bootstrap(
            project_name="remaining", runtime="none", rtl_roots=["rtl"],
            verif_root="verification", dut_top="dut", dut_top_file="rtl/dut.sv",
        )
        other_registration = register_dashboard_project(other)
        current_id = dashboard_project_id(self.store.root)
        healthy = {
            "schema": DASHBOARD_HUB_SCHEMA, "status": "ok", "pid": 31415,
            "owner_id": dashboard_owner_id(),
            "projects": [current_id, other_registration["id"]],
        }
        with (
            mock.patch("verif_harness.dashboard._dashboard_health", return_value=healthy),
            mock.patch("verif_harness.dashboard.os.kill") as kill,
        ):
            stopped = stop_dashboard(self.store, "127.0.0.1", 18765)
        self.assertEqual(stopped["status"], "UNREGISTERED")
        self.assertEqual(stopped["remaining_projects"], 1)
        kill.assert_not_called()
        with self.get(f"/api/snapshot?project={other_registration['id']}") as response:
            remaining_snapshot = json.loads(response.read())
        self.assertEqual(remaining_snapshot["project"]["name"], "remaining")

    def test_dashboard_stop_rejects_runtime_from_another_project(self) -> None:
        runtime_path = self.root / ".verif-harness/dashboard-runtime.json"
        runtime_path.write_text(json.dumps({
            "schema": "DashboardRuntime/1", "pid": 31415,
            "host": "127.0.0.1", "port": 18765,
            "url": "http://127.0.0.1:18765/", "project": "/tmp/other-project",
            "log": str(self.root / ".verif-harness/dashboard.log"),
            "started_at": "2026-09-20T00:00:00+00:00",
        }) + "\n", encoding="utf-8")
        with mock.patch("verif_harness.dashboard.os.kill") as kill:
            with self.assertRaisesRegex(HarnessError, "不属于当前项目"):
                stop_dashboard(self.store)
        kill.assert_not_called()

    def test_dashboard_stop_never_stops_another_os_users_dashboard(self) -> None:
        foreign = {
            "schema": DASHBOARD_HUB_SCHEMA, "status": "ok", "pid": 27182,
            "owner_id": "f" * 24, "projects": [dashboard_project_id(self.store.root)],
        }
        with (
            mock.patch("verif_harness.dashboard._dashboard_health", return_value=foreign),
            mock.patch("verif_harness.dashboard.os.kill") as kill,
        ):
            stopped = stop_dashboard(self.store, "127.0.0.1", 18765)
        self.assertEqual(stopped["status"], "PORT_CONFLICT")
        self.assertIn("拒绝", stopped["message"])
        kill.assert_not_called()

    def test_html_is_local_layered_and_snapshot_is_detailed(self) -> None:
        with self.get("/") as response:
            html = response.read().decode("utf-8")
        self.assertIn("验证项目看板", html)
        self.assertIn('<html lang="zh-CN" data-theme="dark">', html)
        self.assertNotIn("验证项目总览", html)
        self.assertIn('id="home"', html)
        self.assertIn('aria-label="返回首页"', html)
        self.assertIn('id="project-switcher"', html)
        self.assertIn('id="project-unregister"', html)
        self.assertIn("fetch('/api/projects', {headers:{'X-Verif-Token':token}})", html)
        self.assertIn("&token=${encodeURIComponent(token)}", html)
        self.assertIn("data.dashboard_project = state.project", html)
        self.assertIn("/api/registrations/remove", html)
        self.assertNotIn('data-nav="overview"', html)
        self.assertNotIn("state.agentInteraction", html)
        self.assertNotIn("agent-focus", html)
        self.assertNotIn("overview-focus", html)
        self.assertIn('id="sidebar-toggle"', html)
        self.assertIn("localStorage.setItem('verif-sidebar'", html)
        self.assertIn("function currentProjectWorkstream", html)
        self.assertIn("function projectStatusCardHtml", html)
        self.assertIn('<div class="project-status-label">当前项目状态</div>', html)
        self.assertIn("VDOC · 文档撰写方案", html)
        self.assertIn("const revisionLabel = value =>", html)
        self.assertIn("方案 ${escapeHtml(revisionLabel(w.revision))}", html)
        self.assertIn("已批准 ${approvedPlans} / ${writingPlans.length} 项", html)
        self.assertIn("全部批准后可以开始撰写正文，但不代表正文已经通过", html)
        self.assertIn("function overviewPendingGroupsHtml", html)
        self.assertIn('class="card overview-owner-panel"', html)
        self.assertIn("function overviewAgentDetailsHtml", html)
        self.assertIn('class="overview-agent-details"', html)
        overview = html[
            html.index("function renderOverview()"):
            html.index("function wsCard(w)")
        ]
        self.assertLess(
            overview.index("${projectStatusCardHtml(s)}"),
            overview.index("<h2>验证工作流</h2>"),
        )
        self.assertLess(
            overview.index("<h2>验证工作流</h2>"),
            overview.index('<aside class="overview-side">'),
        )
        self.assertNotIn('id="global-action"', html)
        self.assertNotIn("项目状态和评审记录保存在本地数据库中", html)
        self.assertNotIn("Agent 交互", html)
        self.assertIn("整个验证项目", html)
        self.assertIn("无需你处理", html)
        self.assertIn("Dashboard 也没有收到 Agent 正在处理验证工作的记录", html)
        self.assertNotIn("项目级 Agent 当前空闲，没有已登记活动", html)
        self.assertIn("你也可以在当前主 Agent 对话中回答，两处会自动同步", html)
        self.assertIn("回答只用于继续当前工作", html)
        self.assertIn("WAITING_FOR_HUMAN:'等待你处理'", html)
        self.assertIn("function pendingItemStatusLabel(item, targetNode)", html)
        self.assertIn("return '待审批'", html)
        self.assertIn("return '待验收'", html)
        self.assertIn("return '待评审'", html)
        self.assertIn("pendingItemStatusBadge(a, targetNode)", html)
        self.assertIn("s.project_agent", html)
        self.assertIn("s.agent_collaboration", html)
        self.assertIn("/api/agent-questions/answer", html)
        self.assertIn("主 Agent 正在等待你的工程判断", html)
        self.assertNotIn("<h2>协同执行</h2>", html)
        self.assertIn("<strong>子 Agent 工作状态</strong>", html)
        self.assertIn("<strong>运行与回答记录</strong>", html)
        self.assertIn("<h2>需要你回答</h2>", html)
        self.assertIn("Agent 运行详情", html)
        self.assertIn("主 Agent 工作状态", html)
        self.assertIn("查看验证对象与范围", html)
        self.assertNotIn("上下文", html)
        pending_page = html[
            html.index("function renderPendingItemsPage()"):
            html.index("function renderRiskChangesPage()")
        ]
        self.assertLess(pending_page.index("${questionSection}"), pending_page.index("${otherSection}"))
        self.assertLess(pending_page.index("${otherSection}"), pending_page.index("${runDetails}"))
        run_details = html[
            html.index("function agentRunDetailsHtml"):
            html.index("function renderPendingItemsPage()")
        ]
        self.assertLess(run_details.index("${agentWorkStatusHtml"), run_details.index("${subagentWorkStatusHtml"))
        self.assertLess(run_details.index("${subagentWorkStatusHtml"), run_details.index("${history}"))
        self.assertIn('class="card agent-readonly-details agent-run-details"', html)
        self.assertIn('class="card agent-readonly-details agent-subagents"', html)
        self.assertIn('class="card agent-readonly-details agent-history"', html)
        self.assertNotIn('class="card agent-readonly-details agent-run-details" open', html)
        self.assertNotIn('class="card agent-readonly-details agent-subagents" open', html)
        self.assertNotIn('class="card agent-readonly-details agent-history" open', html)
        self.assertIn("提交回答", html)
        self.assertIn("按时间查看主 Agent、子 Agent 的进展", html)
        self.assertNotIn("<h2>最近 Agent 状态</h2>", html)
        self.assertNotIn("agent_question_history || s.agent_questions || [])}${projectContextHtml(true)", html)
        self.assertNotIn("function overviewMetrics", html)
        self.assertNotIn('<h2>当前工作</h2><span class="count">实时记录', html)
        self.assertNotIn('<h2>等待人工处理</h2><span class="count">${openHuman.length}', html)
        self.assertNotIn("overviewTile(", html)
        self.assertNotIn("overview-action-grid", html)
        self.assertIn("<h2>验证工作流</h2>", html)
        self.assertIn("data-open-risk-changes>风险与变更 ${risks.length}", html)
        self.assertIn("function progressRing(value, label, small=false)", html)
        self.assertIn("@keyframes progress-breathe", html)
        self.assertIn('class="node-progress-bar"', html)
        self.assertNotIn('class="progress"', html)
        self.assertNotIn('class="status-strip', html)
        self.assertNotIn("function renderAgentInteractionPage()", html)
        self.assertIn("function agentRunDetailsHtml(", html)
        self.assertNotIn("function agentInteractionSummaryHtml", html)
        self.assertNotIn("${agentInteractionSummaryHtml(", html)
        self.assertIn("function renderPendingItemsPage()", html)
        self.assertIn("function renderRiskChangesPage()", html)
        self.assertIn("function openWorkstreamTab(name)", html)
        self.assertNotIn("function openAgentInteractionTab", html)
        self.assertIn("function openPendingItemsTab(questionId=null)", html)
        self.assertIn("@keyframes waiting-breathe", html)
        self.assertIn("@media (prefers-reduced-motion: reduce)", html)
        self.assertIn("<h2>工作节点</h2>", html)
        self.assertIn("个工作节点 · 点击名称后在新标签页查看详情", html)
        self.assertNotIn("<div class=\"label\">需要你处理</div>", html)
        self.assertNotIn("<h2>等待负责人处理</h2>", html)
        self.assertNotIn("humanRows(openHuman)", html)
        self.assertNotIn("是否需要负责人处理", html)
        self.assertIn("function workstreamStatusCardHtml(w)", html)
        self.assertIn("function vdocPlanReviewState(workstream)", html)
        self.assertIn("REFINE_DESIRED_STATE:'由 Agent 完善当前 DUT 的工作节点'", html)
        self.assertIn("文档撰写方案尚未形成", html)
        self.assertIn("当前没有可供负责人审批的完整方案", html)
        self.assertIn("Agent 形成 DUT 级方案 → 负责人审批方案", html)
        self.assertIn("if ($('#review-ws'))", html)
        self.assertNotIn("当前只有固定分类，还没有按本项目 DUT 分解出实施节点", html)
        self.assertIn("当前工作流状态", html)
        self.assertNotIn('class="grid summary-grid"', html)
        self.assertNotIn("当前阶段", html)
        self.assertNotIn("当前还要处理", html)
        self.assertIn("Agent 当前工作", html)
        self.assertIn("还要完成什么", html)
        self.assertIn("当前工作节点状态", html)
        self.assertNotIn('class="node-summary-grid"', html)
        self.assertIn("实际进度", html)
        self.assertIn("完成条件与当前判断", html)
        self.assertIn("确认工作节点判断", html)
        self.assertIn("在新标签页验收文档内容", html)
        self.assertIn("审批文档撰写方案", html)
        self.assertIn("调整文档", html)
        self.assertIn("请审批文档撰写方案", html)
        self.assertIn("本次审批对象：${planName}", html)
        self.assertIn("这一步审批的是${planName}，不是已经完成的内容", html)
        self.assertIn("这份方案包含的工作节点", html)
        self.assertIn("不作为方案工作节点计数", html)
        self.assertIn("尚未根据当前 DUT", html)
        self.assertIn("这份方案何时完成", html)
        self.assertIn("批准方案并开始相关工作", html)
        self.assertIn("提交审批", html)
        self.assertIn("review-plan-node", html)
        self.assertIn("openNodePlanReviewTab", html)
        self.assertIn("data-plan-section-form", html)
        self.assertIn("提交这部分审批", html)
        self.assertIn("planReviewStatusBadge(review.status)", html)
        self.assertIn("本撰写方案仍待审批", html)
        self.assertIn("当前没有额外工程问题；仍需审批这部分内容", html)
        self.assertIn("/api/reviews/node-plan-section", html)
        self.assertNotIn("这条工作流何时算完成", html)
        self.assertIn("文档审批与验收进展", html)
        self.assertNotIn('<details class="detail-group" open><summary>文档审批与验收进展', html)
        self.assertIn("为什么还没完成", html)
        self.assertIn("完成前还要满足", html)
        self.assertIn("负责人审批方案 → Agent 撰写或修改 → 负责人验收正文", html)
        self.assertIn("所有文档内容均已验收通过（暂定不算通过）", html)
        self.assertIn("function vdocReviewProgressHtml(w)", html)
        self.assertNotIn("收敛", html)
        self.assertNotIn("退出条件", html)
        self.assertNotIn("区块", html)
        self.assertNotIn("计划快照", html)
        self.assertNotIn("VDOC proposal", html)
        self.assertIn("项目与验证对象", html)
        self.assertIn("function projectContextHtml(compact=false)", html)
        self.assertNotIn('<details class="detail-group" open><summary>项目与验证对象', html)
        self.assertIn("仅显示评审和意见记录中的身份", html)
        self.assertIn("不代替负责人作工程判断", html)
        self.assertIn("等待负责人审批文档撰写方案", html)
        self.assertIn("等待负责人确认验证环境方案", html)
        self.assertIn("本节点验收的正文内容", html)
        self.assertNotIn("等待计划评审", html)
        self.assertNotIn("Human 交互入口", html)
        self.assertNotIn("必需节点", html)
        self.assertNotIn("必须完成的节点", html)
        self.assertNotIn("证据", html)
        self.assertIn("Testbench 目录（可选）", html)
        self.assertIn("参考模型（可选）", html)
        self.assertIn("验证脚本（可选）", html)
        self.assertIn("<th>节点名称</th><th>节点类型</th><th>状态 / 进度</th>", html)
        self.assertIn("function nodeProgressHtml(n)", html)
        self.assertIn("function nodeProgressState(n)", html)
        self.assertIn("const WORKSTREAM_NODE_PROFILES = {", html)
        self.assertIn("const NODE_ROLE_PROFILES = {", html)
        self.assertIn("function nodeRolePanelHtml(n)", html)
        self.assertIn('data-node-role="${escapeHtml(n.role || \'unknown\')}"', html)
        for role, title in {
            "capability": "验证能力分解",
            "closure-evidence": "运行结果与支持材料范围",
            "project-goal": "验证目标与退出边界",
            "environment-component": "Testbench 组件与连接",
            "interface": "DUT 接口接入",
            "clock-reset-domain": "时钟与复位域",
            "observation-path": "DUT 观测路径",
            "stimulus-feature": "功能激励",
            "stimulus-scenario": "场景与边界激励",
            "checking-goal": "结果检查目标",
            "checker": "Checker / Scoreboard",
            "reference-path": "参考结果路径",
            "assertion-group": "断言与规则检查",
            "coverage-goal": "功能覆盖目标",
            "coverage-scope": "覆盖采集与范围",
            "case-mapping": "验证点与用例映射",
            "testcase": "Testcase 定义与运行",
            "regression-profile": "回归配置与执行策略",
            "regression-run-set": "回归批次与逐项结果",
            "failure-group": "失败分组与复现分析",
        }.items():
            self.assertIn(f"'{role}':{{panelTitle:'{title}'", html)
        self.assertIn("方案审批或正文验收条件", html)
        self.assertIn("环境可用条件与当前判断", html)
        self.assertIn("场景可达条件与当前判断", html)
        self.assertIn("检查有效性条件与当前判断", html)
        self.assertIn("覆盖目标完成条件与当前判断", html)
        self.assertIn("用例完成条件与当前判断", html)
        self.assertIn("回归完成条件与当前判断", html)
        self.assertNotIn("具体工作、实现方式和交付物", html)
        self.assertIn("方案审批：${approved}/${planSections.length} 项已通过", html)
        self.assertIn("内容验收：${approved}/1 项已通过", html)
        self.assertIn("完成条件：${satisfied}/${criteria.length} 项已满足", html)
        self.assertIn('role="progressbar"', html)
        self.assertIn('aria-valuenow="${progress.ratio}"', html)
        self.assertNotIn("const bar = ratio === null ? ''", html)
        self.assertIn("点击名称后在新标签页查看详情", html)
        self.assertIn('data-open-node="${escapeHtml(n.id)}"', html)
        self.assertIn("openNodeTab(button.dataset.openNode)", html)
        self.assertNotIn(
            '<button class="node-link" data-node="${escapeHtml(n.id)}">'
            '${escapeHtml(humanText(n.title))}</button>', html,
        )
        self.assertNotIn('class="node-link" data-node=', html)
        self.assertNotIn("button.dataset.node; renderDrawer", html)
        node_tab = html[
            html.index("function openNodeTab(nodeId)"):
            html.index("function runtimeLabel")
        ]
        self.assertIn("url.searchParams.set('workstream', node.workstream)", node_tab)
        self.assertIn("url.searchParams.set('node', nodeId)", node_tab)
        self.assertIn("window.open(url.toString(), '_blank', 'noopener')", node_tab)
        self.assertIn("'document-writing-plan':'文档撰写方案'", html)
        self.assertIn("'document-deliverable':'文档内容验收'", html)
        self.assertIn("<h1>风险与变更</h1>", html)
        self.assertIn("需要重新检查的内容", html)
        self.assertIn("选择文档、内容类型和调整方式", html)
        self.assertIn("<h1>验收文档内容</h1>", html)
        self.assertIn("本次验收内容", html)
        self.assertIn("验收前需要你确认", html)
        self.assertIn("评论或要求调整", html)
        self.assertIn('type="hidden" name="target"', html)
        self.assertNotIn('<label>目标</label><input name="target"', html)
        self.assertNotIn("<th>要完成什么</th><th>当前结论</th><th>已有什么</th><th>下一步</th>", html)
        self.assertIn("data-review-workstream", html)
        self.assertIn("button.dataset.reviewWorkstream", html)
        self.assertIn("openWorkstreamReviewTab(button.dataset.reviewWorkstream)", html)
        self.assertIn("window.open(url.toString(), '_blank', 'noopener')", html)
        standalone_url = html[
            html.index("function standaloneUrl()"):
            html.index("function openPendingItemsTab")
        ]
        self.assertIn("url.searchParams.set('project', state.project)", standalone_url)
        self.assertIn("url.searchParams.set('token', token)", standalone_url)
        select_project = html[
            html.index("async function selectProject"):
            html.index("async function initialLoad")
        ]
        self.assertIn("url.searchParams.set('token', token)", select_project)
        self.assertIn("renderWorkstreamReview(workstream(state.reviewWorkstream))", html)
        self.assertIn("$('#review-ws').onclick = () => openWorkstreamReviewTab(w.workstream)", html)
        self.assertIn("review-page-form", html)
        self.assertNotIn("function openReviewModal", html)
        self.assertNotIn("评审节点完成判断", html)
        self.assertIn("w.workstream === 'VDOC'", html)
        self.assertNotIn("__VERIF_DASHBOARD_TOKEN__", html)
        self.assertNotIn("https://", html)
        with self.get("/api/snapshot") as response:
            snapshot = json.loads(response.read())
        self.assertEqual(snapshot["schema"], "VerificationDashboard/1")
        self.assertEqual(snapshot["project"]["dut"], {"top_module": "dut", "top_file": "rtl/dut.sv"})
        self.assertEqual(snapshot["project"]["rtl_roots"], ["rtl"])
        self.assertEqual(snapshot["project"]["verif_root"], "verification")
        self.assertEqual(snapshot["project"]["verification_inputs"], {
            "testbench_root": None, "reference_model": None, "scripts": [],
        })
        self.assertEqual(snapshot["workstreams"][0]["workstream"], "VCHK")
        self.assertTrue(snapshot["workstreams"][0]["nodes"])
        self.assertIn("closure", snapshot["workstreams"][0])
        self.assertIn("closure_assessment", snapshot["workstreams"][0]["nodes"][0])
        self.assertIn("next_actions", snapshot["workstreams"][0]["nodes"][0])
        node = snapshot["workstreams"][0]["nodes"][0]
        self.assertNotIn("current revision", node["statement"])
        self.assertNotIn("required 对象", node["statement"])
        self.assertIn("仅有文件", node["statement"])
        self.assertEqual(node["progress_measures"][0]["unit"], "项")
        self.assertEqual(snapshot["waiting_for_human"][0]["action"], "HUMAN_REVIEW")
        self.assertEqual(snapshot["waiting_for_human"][0]["source"], "closure")
        self.assertEqual(snapshot["waiting_for_human"][0]["target_type"], "workstream")
        self.assertEqual(snapshot["waiting_for_human"][0]["target"], "workstream:VCHK")
        self.assertEqual(snapshot["workstreams"][0]["waiting_for_human"], snapshot["waiting_for_human"])
        self.assertEqual(snapshot["project_agent"]["open_question_count"], 0)
        self.assertEqual(snapshot["project_agent"]["pending_review_count"], 1)
        self.assertEqual(snapshot["project_agent"]["pending_confirmation_count"], 0)
        self.assertIn("1 项评审", snapshot["project_agent"]["message"])
        self.assertNotIn("回答 1 个问题", snapshot["project_agent"]["message"])
        self.assertEqual(snapshot["version"], self.store.dashboard_snapshot()["version"])

    def test_human_can_comment_and_review_without_waiting_for_closure(self) -> None:
        node_id = self.plan["desired_state"][0]["id"]
        action = self.post("/api/human-actions", {
            "target": node_id, "action": "REQUEST_CHANGE", "reviewer": "alice",
            "reason": "请先确认 compare tolerance",
        }, self.server.write_token)["result"]
        self.assertEqual(action["status"], "OPEN")
        reviewed = self.post("/api/reviews/workstream", {
            "workstream": "VCHK", "verdict": "modify", "reviewer": "alice",
            "reason": "compare policy 需要修改",
        }, self.server.write_token)["result"]
        self.assertEqual(reviewed["lifecycle"], "REVISE")
        self.assertEqual(self.store.workstream("VCHK")["lifecycle"], "REVISE")
        snapshot = self.store.dashboard_snapshot()
        self.assertEqual(
            {item["source"] for item in snapshot["waiting_for_human"]},
            {"closure", "human-action"},
        )

    def test_write_api_requires_dashboard_token(self) -> None:
        node_id = self.plan["desired_state"][0]["id"]
        with self.assertRaises(urllib.error.HTTPError) as captured:
            self.post("/api/human-actions", {
                "target": node_id, "action": "COMMENT", "reviewer": "alice", "reason": "note",
            })
        self.assertEqual(captured.exception.code, 403)

    def test_read_api_and_page_require_account_access_token(self) -> None:
        for path in ("/", "/api/projects"):
            with self.subTest(path=path):
                with self.assertRaises(urllib.error.HTTPError) as captured:
                    urllib.request.urlopen(self.url + path.lstrip("/"), timeout=3)
                self.assertEqual(captured.exception.code, 403)
        with urllib.request.urlopen(self.url + "healthz", timeout=3) as response:
            health = json.loads(response.read())
        self.assertEqual(health["owner_id"], dashboard_owner_id())
        token_path = self.registry / "access-token"
        self.assertTrue(token_path.is_file())
        if os.name != "nt":
            self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)

    def test_agent_question_can_be_answered_in_dashboard_and_resumes_agent(self) -> None:
        node_id = self.plan["desired_state"][0]["id"]
        activity = self.store.create_activity(
            node_id, "select-reference-model", "Agent", "正在分析候选方案",
        )
        question = self.store.ask_agent_question(
            node_id, "参考模型策略选哪个？", [
                {"id": "dpi", "label": "DPI 直连 cmodel", "description": "逐事务调用现有模型"},
                {"id": "sv", "label": "按规格重写", "description": "在验证环境中自行实现"},
            ], "dpi", "规格要求该场景以 acc_cmodel.c 为准", "Project Main Agent", True, activity["id"],
        )
        waiting = self.store.dashboard_snapshot()
        self.assertEqual(waiting["activities"][0]["status"], "WAITING_FOR_HUMAN")
        self.assertEqual(waiting["agent_questions"][0]["id"], question["id"])
        self.assertTrue(any(
            item["source"] == "agent-question" and item["question_id"] == question["id"]
            for item in waiting["waiting_for_human"]
        ))

        environment = os.environ.copy()
        environment["GIT_AUTHOR_NAME"] = "test-user"
        environment.pop("USER", None)
        waiter = subprocess.Popen(
            [
                sys.executable, str(CLI), "agent-question", "await", question["id"],
                "--timeout", "5", "--project-root", str(self.root),
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
        )

        def stop_waiter() -> None:
            if waiter.poll() is None:
                waiter.terminate()
                waiter.communicate(timeout=5)

        self.addCleanup(stop_waiter)
        time.sleep(0.2)
        self.assertIsNone(waiter.poll(), "CLI 后台 checkpoint 应等待 Dashboard 回答")

        response = self.post("/api/agent-questions/answer", {
            "id": question["id"], "option": "dpi", "reviewer": "alice",
            "answer_text": "使用只读 cmodel，并记录版本",
        }, self.server.write_token)
        stdout, stderr = waiter.communicate(timeout=5)
        self.assertEqual(waiter.returncode, 0, stdout + stderr)
        checkpoint = json.loads(stdout)
        self.assertTrue(checkpoint["resume"])
        self.assertEqual(checkpoint["question"]["answer_option"], "dpi")
        answered = response["result"]
        self.assertEqual(answered["status"], "ANSWERED")
        self.assertEqual(answered["answer_option"], "dpi")
        self.assertEqual(response["snapshot"]["activities"][0]["status"], "RUNNING")
        self.assertFalse(any(
            item["source"] == "agent-question"
            for item in response["snapshot"]["waiting_for_human"]
        ))
        node = response["snapshot"]["workstreams"][0]["nodes"][0]
        self.assertEqual(node["status"], "UNKNOWN")

        with self.assertRaises(urllib.error.HTTPError) as captured:
            self.post("/api/agent-questions/answer", {
                "id": question["id"], "option": "sv", "reviewer": "bob",
            }, self.server.write_token)
        self.assertEqual(captured.exception.code, 400)

    def test_cli_answer_is_pushed_to_dashboard_event_stream(self) -> None:
        node_id = self.plan["desired_state"][0]["id"]
        activity = self.store.create_activity(
            node_id, "select-reference-model", "Agent", "正在分析候选方案",
        )
        question = self.store.ask_agent_question(
            node_id, "参考模型策略选哪个？", [
                {"id": "dpi", "label": "DPI 直连 cmodel", "description": "逐事务调用现有模型"},
                {"id": "sv", "label": "按规格重写", "description": "在验证环境中自行实现"},
            ], "dpi", "规格要求该场景以 acc_cmodel.c 为准", "Project Main Agent", True,
            activity["id"],
        )
        environment = os.environ.copy()
        environment["GIT_AUTHOR_NAME"] = "test-user"
        environment.pop("USER", None)

        with self.get("/api/events") as events:
            before = self.read_snapshot_event(events)
            result = subprocess.run(
                [
                    sys.executable, str(CLI), "agent-question", "answer", question["id"],
                    "--option", "dpi", "--reviewer", "alice",
                    "--project-root", str(self.root),
                ],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            after = self.read_snapshot_event(events)

        self.assertNotEqual(before["version"], after["version"])
        answered = next(
            item for item in after["agent_question_history"] if item["id"] == question["id"]
        )
        self.assertEqual(answered["status"], "ANSWERED")
        self.assertEqual(after["activities"][0]["status"], "RUNNING")
        self.assertFalse(any(
            item["source"] == "agent-question" and item["question_id"] == question["id"]
            for item in after["waiting_for_human"]
        ))

    def test_vdoc_questions_are_waiting_and_document_can_be_reviewed_from_node(self) -> None:
        plan = self.store.design_workstream("VDOC", None, [], [], [])
        before_review = self.store.dashboard_snapshot()
        vdoc_before_review = next(
            item for item in before_review["workstreams"] if item["workstream"] == "VDOC"
        )
        self.assertEqual(vdoc_before_review["plan_node_count"], 0)
        self.assertEqual(vdoc_before_review["progress"]["required"], 0)
        self.assertFalse(any(node["plan_review"] for node in vdoc_before_review["nodes"]))
        self.assertEqual(vdoc_before_review["waiting_for_human"], [])
        self.assertTrue(any(
            action["kind"] == "REFINE_DESIRED_STATE"
            for action in vdoc_before_review["closure"]["actions"]
        ))
        with self.assertRaisesRegex(HarnessError, "尚未.*形成文档撰写方案"):
            self.store.review_workstream("VDOC", "approve", "alice", "同意当前文档范围")
        self.design_minimal_vdoc()
        self.store.review_workstream("VDOC", "approve", "alice", "同意当前文档范围")
        document = self.store.documents()[0]
        self.store.track_document_item(
            document["id"], "ACC-Q-01", "human-decision",
            "选择结果对比容差", "PENDING", None, None, [], None,
        )
        snapshot = self.store.dashboard_snapshot()
        waiting = [item for item in snapshot["waiting_for_human"] if item["source"] == "document-item"]
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0]["item_id"], "ACC-Q-01")
        self.assertEqual(waiting[0]["item_kind"], "human-decision")
        vdoc = next(item for item in snapshot["workstreams"] if item["workstream"] == "VDOC")
        node = next(item for item in vdoc["nodes"] if item["id"] == document["desired_id"])
        self.assertEqual(node["document"]["path"], document["path"])
        self.assertEqual(node["role"], "document-catalog")
        self.assertEqual(node["next_actions"], [])
        self.assertIn("负责人已确认", node["acceptance_criteria"][0])

        selector = urllib.parse.quote(document["id"], safe="")
        with self.get(f"/api/document?selector={selector}") as response:
            preview = json.loads(response.read())
        self.assertEqual(preview["document"]["id"], document["id"])
        self.assertIn("#", preview["content"])

        reviewed = self.post("/api/reviews/document", {
            "document": document["id"], "verdict": "modify", "reviewer": "alice",
            "notes": "先回答 ACC-Q-01，再更新正文",
        }, self.server.write_token)["result"]
        self.assertEqual(reviewed["verdict"], "MODIFY")

        with self.assertRaises(urllib.error.HTTPError) as captured:
            self.post("/api/reviews/document", {
                "document": document["id"], "verdict": "approve", "reviewer": "alice",
                "notes": "试图忽略待回答问题",
            }, self.server.write_token)
        self.assertEqual(captured.exception.code, 400)

    def test_vdoc_plan_sections_are_reviewed_independently_and_aggregate(self) -> None:
        proposal = {
            "schema": "DesiredStateProposal/1", "workstream": "VDOC",
            "nodes": [
                {
                    "key": "dut-interface-scope", "title": "DUT 接口验证范围",
                    "role": "document-writing-plan", "parent_key": "verification-plan",
                    "document_key": "verification-plan",
                    "required": True,
                    "statement": "当前 DUT 的接口、协议角色和验证边界已在验证计划中明确。",
                    "purpose": "让环境、激励和检查节点使用同一组 DUT 接口边界。",
                    "scope": ["当前 DUT 顶层接口、时钟复位域和协议角色"],
                    "acceptance_criteria": ["每个必需接口都有规格来源和验证责任"],
                    "source_refs": ["rtl/dut.sv", "verification_plan.md#dut-interface-scope"],
                    "work_content": ["逐项列出 DUT 端口、方向、位宽、协议角色和验证责任"],
                    "implementation_approach": ["从 DUT 顶层和已确认规格提取接口并交叉核对"],
                    "deliverables": ["验证计划中的 DUT 接口范围表"],
                    "progress_measures": [{
                        "id": "interfaces-reviewed", "label": "已确认接口",
                        "unit": "接口", "target": "全部必需接口", "source": "verification_plan.md",
                    }],
                    "quality_checks": ["不存在无规格来源或无验证责任的必需接口"],
                    "suggested_mode": "review", "evidence_claim": "document-review",
                },
                {
                    "key": "dut-error-flow", "title": "DUT 错误响应验证方案",
                    "role": "document-writing-plan", "parent_key": "feature-matrix",
                    "document_key": "feature-matrix",
                    "required": True,
                    "statement": "当前 DUT 的错误输入、错误响应和检查方式已明确。",
                    "purpose": "避免只覆盖正常数据流而遗漏 DUT 错误行为。",
                    "scope": ["DUT 可报告或恢复的错误条件"],
                    "acceptance_criteria": ["每类错误都有激励、检查和覆盖映射"],
                    "source_refs": ["feature_matrix.md#error-flow"],
                    "work_content": ["列出错误触发条件、预期响应和观测位置"],
                    "implementation_approach": ["按错误类别建立验证点并关联 testcase/checker/coverage"],
                    "deliverables": ["错误流验证点及其验证映射"],
                    "progress_measures": [{
                        "id": "error-flows-mapped", "label": "已映射错误流",
                        "unit": "场景", "target": "全部必需错误流", "source": "feature_matrix.md",
                    }],
                    "quality_checks": ["错误响应与 DUT 规格一致且可观测"],
                    "suggested_mode": "review", "evidence_claim": "document-review",
                },
                {
                    "key": "dut-interface-table", "title": "DUT 接口范围表",
                    "role": "document-deliverable", "parent_key": "dut-interface-scope",
                    "document_key": "verification-plan", "required": True,
                    "statement": "验证计划正文已经列出当前 DUT 的必需接口和验证责任。",
                    "purpose": "独立验收验证计划中的接口范围语义。",
                    "scope": ["verification_plan.md 的 DUT 接口范围表"],
                    "acceptance_criteria": ["每个必需接口均有方向、位宽、协议角色和验证责任"],
                    "source_refs": ["verification_plan.md#dut-interface-scope", "rtl/dut.sv"],
                    "work_content": ["正文中的 DUT 接口、方向、位宽、协议角色和验证责任"],
                    "implementation_approach": ["对照当前正文与 DUT 顶层接口逐项验收"],
                    "deliverables": ["DUT 接口范围语义的独立验收结论"],
                    "progress_measures": [{
                        "id": "interfaces-accepted", "label": "已验收接口",
                        "unit": "接口", "target": "全部必需接口", "source": "verification_plan.md",
                    }],
                    "quality_checks": ["不存在遗漏、方向错误或验证责任缺失"],
                    "suggested_mode": "review", "evidence_claim": "document-review",
                },
                {
                    "key": "dut-interface-boundary", "title": "DUT 接口验证边界",
                    "role": "document-deliverable", "parent_key": "dut-interface-scope",
                    "document_key": "verification-plan", "required": True,
                    "statement": "验证计划正文已经明确当前 DUT 的接口验证边界。",
                    "purpose": "独立验收纳入和排除范围。",
                    "scope": ["verification_plan.md 的接口验证边界"],
                    "acceptance_criteria": ["纳入范围、排除范围和理由均明确"],
                    "source_refs": ["verification_plan.md#dut-interface-scope"],
                    "work_content": ["正文中的接口纳入范围、排除范围及其理由"],
                    "implementation_approach": ["阅读当前正文并核对范围是否覆盖计划对象"],
                    "deliverables": ["接口验证边界语义的独立验收结论"],
                    "progress_measures": [{
                        "id": "boundaries-accepted", "label": "已验收边界",
                        "unit": "项", "target": "全部边界", "source": "verification_plan.md",
                    }],
                    "quality_checks": ["范围边界没有含糊或相互矛盾"],
                    "suggested_mode": "review", "evidence_claim": "document-review",
                },
                {
                    "key": "dut-error-semantics", "title": "DUT 错误响应语义",
                    "role": "document-deliverable", "parent_key": "dut-error-flow",
                    "document_key": "feature-matrix", "required": True,
                    "statement": "验证点矩阵正文已经描述当前 DUT 的错误响应语义。",
                    "purpose": "独立验收错误触发、响应、检查和覆盖映射。",
                    "scope": ["feature_matrix.md 的错误流验证点"],
                    "acceptance_criteria": ["每类错误都有触发、预期响应、checker 和 coverage"],
                    "source_refs": ["feature_matrix.md#error-flow"],
                    "work_content": ["正文中的错误触发条件、预期响应、观测位置和验证映射"],
                    "implementation_approach": ["按错误类别逐项阅读并核对语义闭环"],
                    "deliverables": ["错误响应语义的独立验收结论"],
                    "progress_measures": [{
                        "id": "error-semantics-accepted", "label": "已验收错误流",
                        "unit": "场景", "target": "全部必需错误流", "source": "feature_matrix.md",
                    }],
                    "quality_checks": ["错误流语义与 DUT 规格一致且可验证"],
                    "suggested_mode": "review", "evidence_claim": "document-review",
                },
            ],
        }
        delivery_specs = proposal["nodes"][2:]
        proposal["nodes"] = proposal["nodes"][:2]
        proposal_path = self.root / "vdoc-plan.json"
        proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
        self.store.design_workstream(
            "VDOC", None, [], [], [], desired_file=str(proposal_path),
        )
        snapshot = self.store.dashboard_snapshot()
        vdoc = next(item for item in snapshot["workstreams"] if item["workstream"] == "VDOC")
        plan_nodes = [node for node in vdoc["nodes"] if node["plan_review"]]
        catalog_nodes = [node for node in vdoc["nodes"] if node["role"] == "document-catalog"]
        delivery_nodes = [node for node in vdoc["nodes"] if node["delivery_review"]]
        self.assertEqual(vdoc["plan_node_count"], 2)
        self.assertEqual(vdoc["delivery_node_count"], 0)
        self.assertEqual(vdoc["progress"]["required"], 2)
        self.assertEqual(vdoc["exit_criteria"], [
            "每份必需文档的文档撰写方案节点和文档交付节点均已审批通过；暂定接受不计为完成",
            "所有文档交付节点中等待负责人确认的事项、修改要求和阻塞问题均已关闭",
        ])
        self.assertEqual(len(plan_nodes), 2)
        self.assertEqual(len(catalog_nodes), 8)
        self.assertEqual(len(delivery_nodes), 0)
        self.assertEqual(
            {node["role"] for node in plan_nodes}, {"document-writing-plan"},
        )
        self.assertEqual(
            {node["role"] for node in catalog_nodes}, {"document-catalog"},
        )
        self.assertTrue(all(node["plan_review"] is None for node in delivery_nodes))
        self.assertEqual(
            len(next(node for node in catalog_nodes if node["key"] == "verification-plan")["document"]["delivery_nodes"]),
            0,
        )
        first = plan_nodes[0]
        self.assertEqual(first["plan_review"]["status"], "PENDING")
        self.assertGreaterEqual(len(first["plan_review"]["sections"]), 3)
        vdoc_pending_reviews = [
            item for item in vdoc["waiting_for_human"] if item["source"] == "closure"
        ]
        all_pending_reviews = [
            item for item in snapshot["waiting_for_human"] if item["source"] == "closure"
        ]
        self.assertEqual(len(vdoc_pending_reviews), 2)
        self.assertEqual(snapshot["project_agent"]["open_question_count"], 0)
        self.assertEqual(
            snapshot["project_agent"]["pending_review_count"], len(all_pending_reviews),
        )
        self.assertIn("项评审", snapshot["project_agent"]["message"])
        self.assertNotIn("个问题", snapshot["project_agent"]["message"])

        section = first["plan_review"]["sections"][0]["section"]
        changed = self.post("/api/reviews/node-plan-section", {
            "node": first["id"], "section": section,
            "definition_digest": first["plan_review"]["definition_digest"],
            "verdict": "modify", "reviewer": "alice",
            "reason": "需要绑定当前 DUT 的接口和验证点",
        }, self.server.write_token)["snapshot"]
        changed_vdoc = next(item for item in changed["workstreams"] if item["workstream"] == "VDOC")
        changed_first = next(item for item in changed_vdoc["nodes"] if item["id"] == first["id"])
        self.assertEqual(changed_first["plan_review"]["status"], "CHANGES_REQUESTED")

        for node in changed_vdoc["nodes"]:
            if not node["plan_review"]:
                continue
            for item in node["plan_review"]["sections"]:
                self.post("/api/reviews/node-plan-section", {
                    "node": node["id"], "section": item["section"],
                    "definition_digest": node["plan_review"]["definition_digest"],
                    "verdict": "approve", "reviewer": "alice",
                    "reason": "该区块已经结合当前 DUT 验证对象确认",
                }, self.server.write_token)
        approved = self.store.dashboard_snapshot()
        approved_vdoc = next(item for item in approved["workstreams"] if item["workstream"] == "VDOC")
        self.assertEqual(approved_vdoc["lifecycle"], "ACTIVE")
        self.assertEqual(approved_vdoc["delivery_node_count"], 0)
        self.assertTrue(any(
            item["kind"] == "AUTHOR_DOCUMENT_CONTENT"
            for item in approved_vdoc["closure"]["actions"]
        ))
        approved_revision = approved_vdoc["revision"]

        delivery_proposal = {
            "schema": "DesiredStateProposal/1", "workstream": "VDOC",
            "nodes": delivery_specs,
        }
        delivery_path = self.root / "vdoc-deliveries.json"
        delivery_path.write_text(json.dumps(delivery_proposal), encoding="utf-8")
        registered = self.store.design_workstream(
            "VDOC", None, [], [], [], desired_file=str(delivery_path),
        )
        self.assertEqual(registered["revision"], approved_revision)
        self.assertEqual(registered["vdoc_phase"], "CONTENT_REVIEW")

        final = self.store.dashboard_snapshot()
        final_vdoc = next(item for item in final["workstreams"] if item["workstream"] == "VDOC")
        self.assertEqual(final_vdoc["lifecycle"], "ACTIVE")
        self.assertEqual(final_vdoc["delivery_node_count"], 3)
        self.assertEqual(final_vdoc["progress"]["required"], 5)
        self.assertTrue(all(
            node["plan_review"]["status"] == "APPROVED"
            for node in final_vdoc["nodes"] if node["plan_review"] and node["required"]
        ))
        interface_scope = next(
            node for node in final_vdoc["nodes"] if node["key"] == "dut-interface-scope"
        )
        self.assertTrue(any("端口" in item for item in interface_scope["work_content"]))
        self.assertFalse(any(
            "完成本节点所描述的实际工作" in item
            for item in interface_scope["work_content"]
        ))

        refreshed_delivery = [
            node for node in final_vdoc["nodes"]
            if node["document_key"] == "verification-plan"
            and node["role"] == "document-deliverable"
        ]
        confirmation = self.store.add_human_action(
            refreshed_delivery[0]["id"], "CLARIFY", "agent-analysis",
            "请确认接口 sideband 是否属于本次验证范围",
            {"source": "agent-delivery-analysis"},
        )
        with self.assertRaises(urllib.error.HTTPError) as captured:
            self.post("/api/reviews/document-delivery", {
                "node": refreshed_delivery[0]["id"],
                "definition_digest": refreshed_delivery[0]["delivery_review"]["definition_digest"],
                "document_digest": refreshed_delivery[0]["delivery_review"]["document_digest"],
                "verdict": "approve", "reviewer": "alice", "notes": "尚未处理确认项",
            }, self.server.write_token)
        self.assertEqual(captured.exception.code, 400)
        self.post("/api/human-actions/resolve", {
            "id": confirmation["id"], "reviewer": "alice",
            "resolution": "sideband 纳入范围并按接口表验收", "status": "RESOLVED",
        }, self.server.write_token)

        first_review = self.post("/api/reviews/document-delivery", {
            "node": refreshed_delivery[0]["id"],
            "definition_digest": refreshed_delivery[0]["delivery_review"]["definition_digest"],
            "document_digest": refreshed_delivery[0]["delivery_review"]["document_digest"],
            "verdict": "approve", "reviewer": "alice", "notes": "接口语义符合当前 DUT",
        }, self.server.write_token)["snapshot"]
        first_vdoc = next(item for item in first_review["workstreams"] if item["workstream"] == "VDOC")
        verification_catalog = next(
            node for node in first_vdoc["nodes"] if node["key"] == "verification-plan"
        )
        self.assertEqual(verification_catalog["document"]["effective_status"], "REVIEW_REQUIRED")
        second = next(
            node for node in first_vdoc["nodes"]
            if node["key"] == "dut-interface-boundary"
        )
        second_review = self.post("/api/reviews/document-delivery", {
            "node": second["id"],
            "definition_digest": second["delivery_review"]["definition_digest"],
            "document_digest": second["delivery_review"]["document_digest"],
            "verdict": "approve", "reviewer": "alice", "notes": "验证边界明确",
        }, self.server.write_token)["snapshot"]
        second_vdoc = next(item for item in second_review["workstreams"] if item["workstream"] == "VDOC")
        verification_catalog = next(
            node for node in second_vdoc["nodes"] if node["key"] == "verification-plan"
        )
        self.assertEqual(verification_catalog["document"]["effective_status"], "VALID")

        error_delivery = next(
            node for node in second_vdoc["nodes"] if node["key"] == "dut-error-semantics"
        )
        provisional = self.post("/api/reviews/document-delivery", {
            "node": error_delivery["id"],
            "definition_digest": error_delivery["delivery_review"]["definition_digest"],
            "document_digest": error_delivery["delivery_review"]["document_digest"],
            "verdict": "provisional", "reviewer": "alice",
            "notes": "错误码定义尚未冻结，暂按当前规格推进",
            "provisional_owner": "bob", "review_trigger": "错误码规格冻结",
        }, self.server.write_token)["snapshot"]
        provisional_vdoc = next(
            item for item in provisional["workstreams"] if item["workstream"] == "VDOC"
        )
        provisional_node = next(
            node for node in provisional_vdoc["nodes"] if node["key"] == "dut-error-semantics"
        )
        self.assertEqual(provisional_node["status"], "PROVISIONAL")
        self.assertEqual(provisional_node["delivery_review"]["status"], "PROVISIONAL")
        self.assertEqual(
            provisional_node["delivery_review"]["current_review"]["provisional"],
            {"review_id": provisional_node["delivery_review"]["current_review"]["id"],
             "owner": "bob", "review_trigger": "错误码规格冻结"},
        )
        self.assertEqual(provisional_node["document"]["effective_status"], "PROVISIONAL")
        self.assertTrue(any(
            action["target"] == provisional_node["id"]
            for action in provisional_vdoc["closure"]["actions"]
        ))

        for removed_role in (
            "project-goal", "closure-evidence", "capability", "document-goal",
            "document-section", "engineering-decision",
        ):
            proposal["nodes"][0]["role"] = removed_role
            proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "role 必须是"):
                self.store.design_workstream(
                    "VDOC", None, [], [], [], desired_file=str(proposal_path),
                )

    def test_human_can_review_current_node_closure_assessment(self) -> None:
        node = self.store.dashboard_snapshot()["workstreams"][0]["nodes"][0]
        assessment = node["closure_assessment"]
        reviewed = self.post("/api/reviews/node-closure", {
            "node": node["id"], "assessment_digest": assessment["digest"],
            "verdict": "approve", "reviewer": "alice",
            "reason": "当前 NOT_SATISFIED 结论与缺失证据一致",
        }, self.server.write_token)["result"]
        self.assertEqual(reviewed["verdict"], "APPROVE")
        refreshed = self.store.dashboard_snapshot()["workstreams"][0]["nodes"][0]
        self.assertEqual(refreshed["closure_assessment"]["reviews"][-1]["reviewer"], "alice")
        # A Human review confirms the explanation; it must not fabricate evidence validity.
        self.assertNotEqual(refreshed["status"], "VALID")

    def test_disputed_node_closure_reopens_node_and_rejects_stale_assessment(self) -> None:
        node = self.store.dashboard_snapshot()["workstreams"][0]["nodes"][0]
        assessment = node["closure_assessment"]
        reviewed = self.post("/api/reviews/node-closure", {
            "node": node["id"], "assessment_digest": assessment["digest"],
            "verdict": "modify", "reviewer": "alice",
            "reason": "满足条件没有逐项引用证据",
        }, self.server.write_token)["result"]
        self.assertEqual(reviewed["node_status"], "REVIEW_REQUIRED")
        refreshed = self.store.dashboard_snapshot()["workstreams"][0]["nodes"][0]
        self.assertTrue(any(
            item["status"] == "OPEN" and "负责人对节点完成判断的结论为 MODIFY" in item["details"]
            for item in refreshed["findings"]
        ))
        self.assertNotEqual(
            assessment["digest"], refreshed["closure_assessment"]["digest"],
        )
        with self.assertRaises(urllib.error.HTTPError) as captured:
            self.post("/api/reviews/node-closure", {
                "node": node["id"], "assessment_digest": assessment["digest"],
                "verdict": "approve", "reviewer": "alice",
                "reason": "attempt to reuse stale assessment",
            }, self.server.write_token)
        self.assertEqual(captured.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
