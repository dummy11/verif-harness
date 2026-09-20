from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from verif_harness.dashboard import create_dashboard_server, dashboard_url, ensure_dashboard_running
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

    def test_background_launcher_reuses_same_project_dashboard(self) -> None:
        port = self.server.server_address[1]
        result = ensure_dashboard_running(self.store, "127.0.0.1", port)
        self.assertEqual(result["schema"], "DashboardLaunch/1")
        self.assertEqual(result["status"], "REUSED")
        self.assertEqual(result["project"], str(self.store.root))
        self.assertEqual(result["url"], self.url)
        self.assertFalse(result["browser_opened"])

    def test_background_launcher_reports_other_project_port_conflict(self) -> None:
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
        self.assertEqual(result["status"], "PORT_CONFLICT")
        self.assertEqual(result["observed_project"], str(self.store.root))

    def test_background_launcher_starts_detached_process_and_records_runtime(self) -> None:
        process = mock.Mock(pid=31415)
        process.poll.return_value = None
        healthy = {"status": "ok", "project": str(self.store.root)}
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
        runtime = json.loads(
            (self.root / ".verif-harness/dashboard-runtime.json").read_text(encoding="utf-8")
        )
        self.assertEqual(runtime["schema"], "DashboardRuntime/1")
        self.assertEqual(runtime["port"], 18765)
        self.assertEqual(runtime["pid"], 31415)

    def test_html_is_local_layered_and_snapshot_is_detailed(self) -> None:
        with self.get("/") as response:
            html = response.read().decode("utf-8")
        self.assertIn("验证项目看板", html)
        self.assertIn("验证项目总览", html)
        self.assertIn("快速查看 Agent 状态", html)
        self.assertNotIn('id="global-action"', html)
        self.assertIn("Agent 交互", html)
        self.assertIn("在这里直接回答 Agent", html)
        self.assertIn("无需 SSH 到服务器", html)
        self.assertIn("/api/agent-questions/answer", html)
        self.assertNotIn("function overviewMetrics", html)
        self.assertNotIn('<h2>当前工作</h2><span class="count">实时记录', html)
        self.assertNotIn('<h2>等待人工处理</h2><span class="count">${openHuman.length}', html)
        self.assertIn("overviewEntry('Agent 交互'", html)
        self.assertIn("overviewEntry('待处理事项'", html)
        self.assertIn("<h2>验证工作流</h2>", html)
        self.assertIn("overviewEntry('验证风险与变更'", html)
        self.assertIn("function renderAgentInteractionPage()", html)
        self.assertIn("function renderPendingItemsPage()", html)
        self.assertIn("function renderRiskChangesPage()", html)
        self.assertIn("function openWorkstreamTab(name)", html)
        self.assertIn("function openAgentInteractionTab(questionId=null)", html)
        self.assertIn("@keyframes waiting-breathe", html)
        self.assertIn("@media (prefers-reduced-motion: reduce)", html)
        self.assertIn("<h2>工作节点</h2>", html)
        self.assertIn("个工作节点 · 点击名称查看详情", html)
        self.assertIn("要达到什么", html)
        self.assertIn("实际进度", html)
        self.assertIn("完成条件与当前依据", html)
        self.assertIn("确认节点完成判断", html)
        self.assertIn("在新标签页验收本交付节点", html)
        self.assertIn("审批文档撰写方案", html)
        self.assertIn("调整文档", html)
        self.assertIn("请审批文档撰写方案", html)
        self.assertIn("本次审批对象：工作流实施方案", html)
        self.assertIn("这一步审批的是实施方案，不是实施内容", html)
        self.assertIn("基于当前 DUT 分解的方案节点", html)
        self.assertIn("不作为实施方案节点计数", html)
        self.assertIn("尚未根据当前 DUT", html)
        self.assertIn("整体退出条件", html)
        self.assertIn("批准实施方案并开始工作", html)
        self.assertIn("提交实施方案审批", html)
        self.assertIn("review-plan-node", html)
        self.assertIn("openNodePlanReviewTab", html)
        self.assertIn("data-plan-section-form", html)
        self.assertIn("提交本区块审批", html)
        self.assertIn("/api/reviews/node-plan-section", html)
        self.assertIn("这条工作流何时算完成", html)
        self.assertIn("VDOC Human–Agent–Engine 评审闭环与收敛", html)
        self.assertIn("当前重新评审原因", html)
        self.assertIn("当前收敛条件", html)
        self.assertIn("Agent 分析 → Engine 登记版本 → Human 评审", html)
        self.assertIn("所有必需文档交付节点均已批准（暂定不计）", html)
        self.assertIn("function vdocConvergenceHtml(w, openHuman)", html)
        self.assertIn("项目与验证对象", html)
        self.assertIn("function projectContextHtml(compact=false)", html)
        self.assertNotIn('<details class="detail-group" open><summary>项目与验证对象', html)
        self.assertIn("仅显示评审和意见记录中的身份", html)
        self.assertIn("只校验与聚合，不代替 Human 审批", html)
        self.assertIn("Testbench 目录（可选）", html)
        self.assertIn("参考模型（可选）", html)
        self.assertIn("验证脚本（可选）", html)
        self.assertIn("<th>节点名称</th><th>节点类型</th><th>状态 / 进度</th>", html)
        self.assertIn("function nodeProgressHtml(n)", html)
        self.assertIn("点击名称查看详情", html)
        self.assertIn("'document-writing-plan':'文档撰写方案'", html)
        self.assertIn("'document-deliverable':'文档交付'", html)
        self.assertNotIn("<th>要完成什么</th><th>当前结论</th><th>已有什么</th><th>下一步</th>", html)
        self.assertIn("data-review-workstream", html)
        self.assertIn("button.dataset.reviewWorkstream", html)
        self.assertIn("openWorkstreamReviewTab(button.dataset.reviewWorkstream)", html)
        self.assertIn("window.open(url.toString(), '_blank', 'noopener')", html)
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

    def test_agent_question_can_be_answered_in_dashboard_and_resumes_agent(self) -> None:
        node_id = self.plan["desired_state"][0]["id"]
        activity = self.store.create_activity(
            node_id, "select-reference-model", "Agent", "正在分析候选方案",
        )
        question = self.store.ask_agent_question(
            node_id, "参考模型策略选哪个？", [
                {"id": "dpi", "label": "DPI 直连 cmodel", "description": "逐事务调用现有模型"},
                {"id": "sv", "label": "按规格重写", "description": "在验证环境中自行实现"},
            ], "dpi", "规格要求该场景以 acc_cmodel.c 为准", "Agent", True, activity["id"],
        )
        waiting = self.store.dashboard_snapshot()
        self.assertEqual(waiting["activities"][0]["status"], "WAITING_FOR_HUMAN")
        self.assertEqual(waiting["agent_questions"][0]["id"], question["id"])
        self.assertTrue(any(
            item["source"] == "agent-question" and item["question_id"] == question["id"]
            for item in waiting["waiting_for_human"]
        ))

        response = self.post("/api/agent-questions/answer", {
            "id": question["id"], "option": "dpi", "reviewer": "alice",
            "answer_text": "使用只读 cmodel，并记录版本",
        }, self.server.write_token)
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
        self.assertEqual(vdoc["delivery_node_count"], 3)
        self.assertEqual(vdoc["progress"]["required"], 5)
        self.assertEqual(vdoc["exit_criteria"], [
            "每份必需文档的文档撰写方案节点和文档交付节点均已审批通过；暂定接受不计为完成",
            "所有文档交付节点中的 Human 确认项、修改要求和阻塞问题均已关闭",
        ])
        self.assertEqual(len(plan_nodes), 2)
        self.assertEqual(len(catalog_nodes), 8)
        self.assertEqual(len(delivery_nodes), 3)
        self.assertEqual(
            {node["role"] for node in plan_nodes}, {"document-writing-plan"},
        )
        self.assertEqual(
            {node["role"] for node in catalog_nodes}, {"document-catalog"},
        )
        self.assertTrue(all(node["plan_review"] is None for node in delivery_nodes))
        self.assertEqual(
            len(next(node for node in catalog_nodes if node["key"] == "verification-plan")["document"]["delivery_nodes"]),
            2,
        )
        first = plan_nodes[0]
        self.assertEqual(first["plan_review"]["status"], "PENDING")
        self.assertGreaterEqual(len(first["plan_review"]["sections"]), 3)

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
        final = self.store.dashboard_snapshot()
        final_vdoc = next(item for item in final["workstreams"] if item["workstream"] == "VDOC")
        self.assertEqual(final_vdoc["lifecycle"], "ACTIVE")
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
