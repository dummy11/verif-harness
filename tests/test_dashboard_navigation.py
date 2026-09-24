"""Real DOM navigation against an isolated Dashboard HTTP server.

Requires Node.js + Playwright and an installed browser. Set
VERIF_DASHBOARD_BROWSER_CHANNEL=chrome to use a local Chrome installation.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest

from tests import test_dashboard as fixtures
from verif_harness.dashboard import (
    dashboard_project_id, register_dashboard_project, unregister_dashboard_project,
)
from verif_harness.store import ProjectStore


ROOT = Path(__file__).resolve().parents[1]


class DashboardNavigationTest(unittest.TestCase):
    def test_browser_navigation_drafts_and_http_writes(self) -> None:
        if not shutil.which("node"):
            self.skipTest("Node.js is required for browser navigation tests")
        probe = subprocess.run(
            ["node", "-e", "require('playwright')"], capture_output=True, timeout=20,
        )
        if probe.returncode:
            self.skipTest("Playwright is required for real DOM navigation tests")
        fixture = fixtures.DashboardTest()
        fixture.setUp()
        workers, server_errors = set(), []
        workers_lock = threading.Lock()
        original_error_handler = fixture.server.handle_error
        original_request_thread = fixture.server.process_request_thread

        def process_request_thread(request, address):
            with workers_lock:
                workers.add(threading.current_thread())
            try:
                original_request_thread(request, address)
            finally:
                with workers_lock:
                    workers.discard(threading.current_thread())

        def handle_error(request, address):
            # Chrome closes keep-alive sockets when tabs close. Do not hide product errors.
            if not isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
                server_errors.append(str(sys.exc_info()[1]))
                original_error_handler(request, address)
        fixture.server.handle_error = handle_error
        fixture.server.process_request_thread = process_request_thread
        other = None
        try:
            fixture.design_minimal_vdoc()
            question = fixture.store.ask_agent_question(
                "project", "确认测试范围",
                [
                    {"id": "scope", "label": "当前 DUT", "description": "检查当前验证对象"},
                    {"id": "more", "label": "需要说明", "description": "补充验证范围说明"},
                ],
                context="仅使用公开测试样例",
            )
            other_root = fixture.root / "other"
            other_root.mkdir()
            other = ProjectStore(other_root)
            other.bootstrap(
                project_name="beta", runtime="none", rtl_roots=[str(fixture.root / "rtl")],
                verif_root="verification", dut_top="dut", dut_top_file=str(fixture.root / "rtl/dut.sv"),
            )
            register_dashboard_project(other)
            original_root, original_store = fixture.root, fixture.store
            try:
                fixture.root, fixture.store = other_root, other
                fixture.design_minimal_vdoc()
                vdoc = next(w for w in other.dashboard_snapshot()["workstreams"] if w["workstream"] == "VDOC")
                plan = next(n for n in vdoc["nodes"] if n["plan_review"])
                for section in plan["plan_review"]["sections"]:
                    other.review_node_plan_section(
                        plan["id"], section["section"], plan["plan_review"]["definition_digest"],
                        "approve", "fixture-reviewer", "仅供隔离浏览器测试",
                    )
                fixture.register_minimal_vdoc_delivery()
            finally:
                fixture.root, fixture.store = original_root, original_store
            config = {
                "url": fixture.url,
                "project": dashboard_project_id(fixture.root),
                "otherProject": dashboard_project_id(other_root),
                "token": fixture.server.write_token,
                "question": question["id"],
            }
            result = subprocess.run(
                ["node", str(ROOT / "tests/dashboard_navigation.cjs")],
                input=json.dumps(config), text=True, capture_output=True,
                env=os.environ.copy(), timeout=150,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())
        finally:
            # Stop SSE readers before removing their temporary SQLite databases.
            unregister_dashboard_project(fixture.store, fixture.server.registry_dir)
            if other is not None:
                unregister_dashboard_project(other, fixture.server.registry_dir)
            with workers_lock:
                pending_workers = list(workers)
            for worker in pending_workers:
                worker.join(timeout=3)
            fixture.tearDown()
        self.assertEqual(server_errors, [])


if __name__ == "__main__":
    unittest.main()
