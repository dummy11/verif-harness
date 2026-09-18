from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from verif_harness.dashboard import create_dashboard_server, dashboard_url
from verif_harness.store import ProjectStore


class DashboardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "rtl").mkdir()
        (self.root / "rtl/dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
        self.store = ProjectStore(self.root)
        self.store.bootstrap(
            runtime="none", rtl_roots=["rtl"], verif_root="verification",
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
        self.temporary.cleanup()

    def get(self, path: str) -> urllib.request.addinfourl:
        return urllib.request.urlopen(self.url + path.lstrip("/"), timeout=3)

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

    def test_html_is_local_layered_and_snapshot_is_detailed(self) -> None:
        with self.get("/") as response:
            html = response.read().decode("utf-8")
        self.assertIn("验证项目看板", html)
        self.assertIn("项目验证总览", html)
        self.assertIn("等待人工处理", html)
        self.assertIn("工作项", html)
        self.assertIn("要达到什么", html)
        self.assertIn("实际进度", html)
        self.assertIn("完成条件与当前依据", html)
        self.assertIn("评审完成判断", html)
        self.assertIn("查看并评审文档", html)
        self.assertIn("这类验证工作何时算完成", html)
        self.assertNotIn("评审节点完成判断", html)
        self.assertNotIn("__VERIF_DASHBOARD_TOKEN__", html)
        self.assertNotIn("https://", html)
        with self.get("/api/snapshot") as response:
            snapshot = json.loads(response.read())
        self.assertEqual(snapshot["schema"], "VerificationDashboard/1")
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
        self.assertEqual(snapshot["workstreams"][0]["waiting_for_human"], snapshot["waiting_for_human"])
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

    def test_vdoc_questions_are_waiting_and_document_can_be_reviewed_from_node(self) -> None:
        plan = self.store.design_workstream("VDOC", None, [], [], [])
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
        vdoc = next(item for item in snapshot["workstreams"] if item["workstream"] == "VDOC")
        node = next(item for item in vdoc["nodes"] if item["id"] == document["desired_id"])
        self.assertEqual(node["document"]["path"], document["path"])
        self.assertTrue(node["next_actions"])
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
            item["status"] == "OPEN" and "Human MODIFY" in item["details"]
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
