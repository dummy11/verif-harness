"""Public VENV gates and artifact dependency contracts, using synthetic DUT data."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import urllib.error
from unittest import mock

from tests import test_vdoc_artifacts as vdoc_fixture
from verif_harness import code_workflow as code
from verif_harness.store import HarnessError, ProjectStore, Validity


class CodeWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.fixture = vdoc_fixture.VdocArtifactsTest()
        self.fixture.setUp()
        self.fixture.prepare()
        self.fixture.finish()
        self.store = self.fixture.store
        self.root = self.store.root
        self.item = {
            "key": "interface-main", "implementation_key": "interface:main", "role": "code-plan",
            "title": "主接口实现方案", "statement": "连接当前 DUT 的主接口",
            "scope": ["主接口连接"], "work_content": ["编写接口并连接 DUT"],
            "implementation_approach": ["使用明确方向的端口连接"],
            "validation_methods": ["编译并检查接口连接"], "deliverables": ["接口代码和构建报告"],
            "acceptance_criteria": ["编译和装载通过"], "source_refs": ["rtl/", "verification_plan.md"],
            "inputs": ["cap.doc:verification-plan"], "input_files": ["rtl/dut.sv"],
            "output_paths": ["verification/tb/main.sv"], "capabilities": ["build-ready"],
        }
        self.design()

    def tearDown(self):
        self.fixture.tearDown()

    def design(self, items=None):
        self.proposal = self.root / "code-proposal.json"
        self.proposal.write_text(json.dumps({"schema": "DesiredStateProposal/1", "workstream": "VENV", "nodes": items or [self.item]}))
        plan = self.store.design_workstream("VENV", None, [], [], [], desired_file=self.proposal.name)
        self.plan_node = plan["desired_state"][0]
        return plan

    def approve(self, node):
        state = self.store.node_plan_review_state(node["id"])
        return self.store.complete_node_plan_review(node["id"], state["definition_digest"], "fixture-owner")

    def implement(self):
        if not self.store.node_plan_review_state(self.plan_node['id'])['completed']:
            self.approve(self.plan_node)
        self.delivery = next(n for n in self.store.workstream("VENV")["desired_state"] if n["role"] == "code-deliverable")
        self.output = self.root / self.item["output_paths"][0]
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text("module fixture_interface; endmodule\n")
        return self.delivery

    def validate(self, errors=0, register=True):
        state = self.store.node_plan_review_state(self.delivery["id"])
        log = self.root / "build.log"
        log.write_text("synthetic fixture build report\n")
        evidence = self.root / "build-evidence.json"
        evidence.write_text(json.dumps({"schema": "EnvironmentEvidence/1", "claim": "build-ready",
            "revision": json.loads((self.store.state / "project.json").read_text()).get("baseline_revision") or "fixture-revision",
            "tool": "fixture-build", "artifacts": [
                {"path": self.item["output_paths"][0], "sha256": self.store._digest(self.output), "kind": "source", "analyzed_by": ["xverif"]},
                {"path": "build.log", "sha256": self.store._digest(log), "kind": "build-log", "analyzed_by": ["xverif"]},
            ], "result": {"compiled": True, "elaborated": True, "errors": errors,
                           "environment_digest": self.store._digest(self.output), "build_log_digest": self.store._digest(log)}}))
        self.report = {"schema": "CodeValidation/1", "node_id": self.delivery["id"], "revision": state["revision"],
            "input_signature": state["input_signature"], "code_files": state["code_files"],
            "checked_by": "Project Main Agent", "summary": "已检查当前接口的构建结果",
            "checks": [{"criterion": "编译和装载通过", "method": "编译和装载检查", "expected": "无错误",
                        "actual": str(errors) + " 个错误", "report": evidence.name, "claim": "build-ready"}]}
        self.report_path = self.root / "code-validation.json"
        self.report_path.write_text(json.dumps(self.report))
        return code.validate(self.store, self.delivery["id"], self.report_path.name) if register else None

    def head(self, identifier):
        return next(n for n in code.artifacts(self.store)["heads"] if n["id"] == identifier)

    def test_two_roles_three_gates_and_read_only_queries(self):
        self.assertEqual([n["role"] for n in self.store.workstream("VENV")["desired_state"]], ["code-plan"])
        self.assertFalse((self.root / self.item["output_paths"][0]).exists())
        self.implement()
        self.assertEqual(self.head("art.code_plan:interface:main")["status"], "VALID")
        with self.assertRaisesRegex(HarnessError, "验证"):
            self.approve(self.delivery)
        self.assertTrue(self.validate()["ready"])
        self.assertNotEqual(self.head("cap.venv:interface:main")["status"], "VALID")
        self.approve(self.delivery)
        self.assertEqual(self.head("cap.venv:build-ready")["status"], "VALID")
        self.assertTrue(self.store.evaluate_closure("VENV")["ready"])
        self.assertEqual(self.store.node_closure_assessment(self.delivery["id"])["conclusion"], "CLOSED")
        before = code.artifacts(self.store)["versions"]
        for _ in range(3):
            snapshot = self.store.dashboard_snapshot()
        self.assertEqual(code.artifacts(self.store)["versions"], before)
        view = next(w for w in snapshot["workstreams"] if w["workstream"] == "VENV")
        self.assertEqual(view["progress"]["satisfied"], 2)
        self.assertEqual(view["progress"]["required"], 2)

    def test_unsynced_code_and_evidence_revoke_delivery_not_plan(self):
        self.implement(); self.validate(); self.approve(self.delivery)
        previous = self.head("art.code_plan:interface:main")["data"]["current"]
        self.output.write_text("module changed; endmodule\n")
        self.assertNotEqual(self.head("cap.venv:interface:main")["status"], "VALID")
        self.assertEqual(self.head("art.code_plan:interface:main")["data"]["current"], previous)
        self.assertFalse(self.store.node_plan_review_state(self.delivery["id"])["can_approve"])
        self.validate(); self.approve(self.delivery)
        (self.root / "build.log").write_text("changed log\n")
        self.assertFalse(self.store.node_plan_review_state(self.delivery["id"])["can_approve"])

    def test_identical_validation_receipt_preserves_owner_acceptance_and_capability(self):
        self.implement()
        first = self.validate()
        self.approve(self.delivery)
        before = self.store.node_plan_review_state(self.delivery["id"])
        versions = code.artifacts(self.store)["versions"]

        second = self.validate()
        after = self.store.node_plan_review_state(self.delivery["id"])
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(after["definition_digest"], before["definition_digest"])
        self.assertTrue(after["completed"])
        self.assertEqual(code.artifacts(self.store)["versions"], versions)
        self.assertTrue(self.store.evaluate_closure("VENV")["ready"])

        self.output.write_text("module changed_interface; endmodule\n")
        self.validate()
        changed = self.store.node_plan_review_state(self.delivery["id"])
        self.assertFalse(changed["completed"])
        self.assertTrue(changed["can_approve"])
        self.assertIn("HUMAN_REVIEW", {a["kind"] for a in self.store.evaluate_closure("VENV")["actions"]})

    def test_legacy_receipt_bound_approval_survives_identical_revalidation(self):
        self.implement()
        first = self.validate()
        approval = self.approve(self.delivery)
        state = self.store.node_plan_review_state(self.delivery["id"])
        old_digest = code.digest({"definition": state["input_signature"], "validation": first["id"]})
        with self.store.connect() as db:
            db.execute("UPDATE node_plan_reviews SET definition_digest=? WHERE id=?",
                       (old_digest, approval["review_id"]))
        self.assertTrue(self.store.node_plan_review_state(self.delivery["id"])["completed"])
        self.validate()
        self.assertTrue(self.store.node_plan_review_state(self.delivery["id"])["completed"])

    def test_plan_status_only_change_keeps_approval(self):
        self.approve(self.plan_node)
        before = self.store.node_plan_review_state(self.plan_node["id"])
        self.store.set_status(self.plan_node["id"], Validity.REVALIDATION_REQUIRED)
        after = self.store.node_plan_review_state(self.plan_node["id"])
        self.assertEqual(after["definition_digest"], before["definition_digest"])
        self.assertTrue(after["completed"])

    def test_identical_proposal_does_not_create_revision_or_repeat_approval(self):
        self.implement(); self.validate(); self.approve(self.delivery)
        before = self.store.workstream("VENV")
        versions = code.artifacts(self.store, "VENV")["versions"]
        with self.store.read_connect() as db:
            approvals = db.execute("SELECT COUNT(*) FROM node_plan_reviews WHERE workstream='VENV'").fetchone()[0]
            replans = db.execute("SELECT COUNT(*) FROM events WHERE kind='venv-replan'").fetchone()[0]

        repeated = self.design()
        self.assertEqual(repeated["revision"], before["revision"])
        self.assertEqual(repeated["desired_state"], before["desired_state"])
        self.assertTrue(self.store.node_plan_review_state(self.plan_node["id"])["completed"])
        self.assertTrue(self.store.node_plan_review_state(self.delivery["id"])["completed"])
        self.assertEqual(code.artifacts(self.store, "VENV")["versions"], versions)
        with self.store.read_connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM node_plan_reviews WHERE workstream='VENV'").fetchone()[0], approvals)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='venv-replan'").fetchone()[0], replans)

        code.request_change(self.store, {"workstream": "VENV", "kind": "add",
                                         "revision": before["revision"], "reviewer": "fixture-owner",
                                         "reason": "增加复位验证工作包"})
        with self.assertRaisesRegex(HarnessError, "变更要求"):
            self.design()
        self.assertEqual(self.store.workstream("VENV")["revision"], before["revision"])

    def test_upstream_document_and_rtl_revoke_plan_and_delivery(self):
        self.implement(); self.validate(); self.approve(self.delivery)
        self.fixture.path.write_text("# Different approved-document input\n")
        self.assertNotEqual(self.head("art.code_plan:interface:main")["status"], "VALID")
        self.assertNotEqual(self.head("cap.venv:interface:main")["status"], "VALID")

    def test_adding_package_preserves_unchanged_node_versions_and_acceptance(self):
        self.implement(); self.validate(); self.approve(self.delivery)
        before = self.store.workstream("VENV")
        accepted = self.store.node_plan_review_state(self.delivery["id"])
        versions = code.artifacts(self.store, "VENV")["versions"]
        extra = {**copy.deepcopy(self.item), "key": "reset-extra",
                 "implementation_key": "reset:extra", "title": "新增复位检查方案",
                 "output_paths": ["verification/tb/extra.sv"]}
        current = self.design([self.item, extra])
        self.assertEqual(current["revision"], before["revision"] + 1)
        self.assertIn(self.delivery, current["desired_state"])
        state = self.store.node_plan_review_state(self.delivery["id"])
        self.assertEqual(state["revision"], before["revision"])
        self.assertEqual(state["workstream_revision"], current["revision"])
        self.assertEqual(state["current_completion"], accepted["current_completion"])
        self.assertEqual(state["definition_digest"], accepted["definition_digest"])
        self.assertTrue(state["completed"])
        self.assertTrue(all(version in code.artifacts(self.store, "VENV")["versions"] for version in versions))
        snapshot = self.store.dashboard_snapshot()
        view = next(w for w in snapshot["workstreams"] if w["workstream"] == "VENV")
        self.assertNotIn(self.delivery["id"], [a["target"] for a in view["closure"]["actions"]])
        self.assertEqual(view["progress"]["satisfied"], 2)
        self.assertEqual(view["progress"]["required"], 4)
        self.assertTrue(self.validate()["ready"])
        self.assertTrue(self.store.node_plan_review_state(self.delivery["id"])["completed"])

        # A changed native artifact still invalidates that retained delivery.
        self.output.write_text("module changed_interface; endmodule\n")
        changed = self.store.node_plan_review_state(self.delivery["id"])
        self.assertFalse(changed["completed"])
        self.assertFalse(changed["can_approve"])

        self.assertTrue(self.validate()["ready"])
        current = self.store.node_plan_review_state(self.delivery["id"])
        self.store.review_node_plan_section(self.delivery["id"], "writing-plan", current["definition_digest"],
                                           "modify", "fixture-owner", "核对复位后接口状态")
        current = self.store.node_plan_review_state(self.delivery["id"])
        with mock.patch("verif_harness.store.time.sleep", side_effect=lambda _: self.store.submit_review_feedback(
                self.delivery["id"], current["definition_digest"])):
            checkpoint = self.store.await_human_review("VENV", timeout=1, node_ids=[self.delivery["id"]])
        self.assertEqual(checkpoint["status"], "ACTION_REQUIRED")
        batch = checkpoint["feedback_batch"]
        self.assertEqual(len(batch["items"]), 1)
        self.store.complete_review_feedback(batch["batch_id"], "Project Main Agent", "已核对当前受控证据")
        self.approve(self.delivery)
        self.assertTrue(self.store.node_plan_review_state(self.delivery["id"])["completed"])

    def test_changed_package_and_explicit_restart_create_new_node_versions(self):
        self.implement(); self.validate(); self.approve(self.delivery)
        original = self.delivery
        changed = {**copy.deepcopy(self.item), "statement": "增加复位期间接口检查"}
        current = self.design([changed])
        self.assertNotIn(original["id"], {n["id"] for n in current["desired_state"]})
        self.assertEqual(len(current["desired_state"]), 1)
        self.assertFalse(self.store.node_plan_review_state(current["desired_state"][0]["id"])["completed"])
        self.approve(current["desired_state"][0])
        restarted = code.request_change(self.store, {
            "workstream": "VENV", "kind": "restart", "revision": current["revision"],
            "reviewer": "fixture-owner", "reason": "显式重启", "confirm": True,
        })
        self.assertEqual(restarted["revision"], current["revision"] + 1)
        self.assertEqual(restarted["desired_state"], [])

    def test_feedback_reopens_approval_and_waits_for_agent(self):
        self.implement()
        state = self.store.node_plan_review_state(self.plan_node["id"])
        self.store.review_node_plan_section(self.plan_node["id"], "writing-plan", state["definition_digest"], "modify", "fixture-owner", "说明端口方向")
        state = self.store.node_plan_review_state(self.plan_node["id"])
        self.assertFalse(state["completed"])
        self.assertFalse(state["can_approve"])
        batch = self.store.submit_review_feedback(self.plan_node["id"], state["definition_digest"])
        self.assertEqual(batch["count"], 1)
        self.store.complete_review_feedback(batch["batch_id"], "Project Main Agent", "已核对，现有方案已明确端口方向，无需修改")
        self.assertTrue(self.store.node_plan_review_state(self.plan_node["id"])["can_approve"])
        self.approve(self.plan_node)

    def test_failed_validation_never_enables_approval(self):
        self.implement()
        self.assertFalse(self.validate(errors=1)["ready"])
        self.assertFalse(self.store.node_plan_review_state(self.delivery["id"])["can_approve"])

    def test_outdated_approval_and_report_rejected(self):
        self.implement(); self.validate()
        state = self.store.node_plan_review_state(self.delivery["id"])
        self.output.write_text("module changed; endmodule\n")
        with self.assertRaisesRegex(HarnessError, "版本已变化"):
            self.store.complete_node_plan_review(self.delivery["id"], state["definition_digest"], "fixture-owner")
        with self.assertRaisesRegex(HarnessError, "绑定"):
            code.validate(self.store, self.delivery["id"], self.report_path.name)

    def test_downstream_default_dependencies_use_capabilities(self):
        plan = self.store._design_workstream("VCASE", None, [], [], [])
        node = next(n for n in plan["desired_state"] if n["key"] == "case-implementation")
        edges = self.store.trace(node["id"])["outgoing"]
        targets = {e["target"] for e in edges if e["relation"] == "DEPENDS_ON"}
        self.assertIn("cap.venv:build-ready", targets)
        with self.assertRaisesRegex(HarnessError, "cap.venv"):
            self.store.add_dependency(node["id"], self.plan_node["id"])

    def test_invalid_cycle_and_unapproved_input_kind(self):
        bad = copy.deepcopy(self.item)
        bad["inputs"] = ["art.doc:verification-plan"]
        with self.assertRaisesRegex(HarnessError, "cap.doc"):
            self.design([bad])
        bad["inputs"] = ["cap.doc:verification-plan", "cap.venv:interface:main"]
        with self.assertRaisesRegex(HarnessError, "自己"):
            self.design([bad])

    def test_restart_retains_history_and_files(self):
        self.implement(); self.validate(); self.approve(self.delivery)
        old = self.store.workstream("VENV")["revision"]
        result = code.request_change(self.store, {"kind": "restart", "revision": old, "reviewer": "fixture-owner", "reason": "调整实现范围", "confirm": True})
        self.assertEqual(result["revision"], old + 1)
        self.assertTrue(self.output.exists())
        self.assertTrue(code.artifacts(self.store)["versions"])
        self.assertEqual(result["desired_state"], [])
        with self.assertRaises(HarnessError):
            self.approve(self.delivery)

    def test_project_scoped_file_preview_and_stale_files(self):
        self.implement(); self.validate()
        item = self.report["code_files"][0]
        self.assertIn("fixture_interface", code.content(self.store, self.delivery["id"], item["path"], item["sha256"])["content"])
        with self.assertRaises(HarnessError):
            code.content(self.store, self.delivery["id"], "../outside", item["sha256"])
        self.output.write_text("changed\n")
        with self.assertRaises(HarnessError):
            code.content(self.store, self.delivery["id"], item["path"], item["sha256"])

    def cli(self, *args):
        process = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/verif_harness.py'),
                                  *args, '--project-root', str(self.root)], text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def test_new_cli_planning_never_creates_legacy_work_nodes(self):
        result = self.cli('plan', 'VENV')
        self.assertEqual(result['desired_state'], self.store.workstream('VENV')['desired_state'])
        self.assertFalse(result['auto_closure']['ready'])
        fresh = ProjectStore(self.root / 'fresh')
        fresh.root.mkdir()
        fresh.bootstrap(project_name='new-code-project', runtime='none', rtl_roots=[str(self.root / 'rtl')],
                        verif_root='verification', dut_top='dut', dut_top_file=str(self.root / 'rtl/dut.sv'))
        initial = fresh.design_workstream('VENV', None, [], [], [])
        self.assertEqual(initial['desired_state'], [])
        self.assertEqual(initial['auto_closure']['actions'][0]['kind'], 'REFINE_DESIRED_STATE')

    def test_http_approval_and_cli_validation_share_authority(self):
        f = self.fixture.fixture
        state = self.cli('code', 'status', self.plan_node['id'])
        response = f.post('/api/reviews/node-plan-complete', {'node': self.plan_node['id'],
                         'definition_digest': state['definition_digest'], 'reviewer': 'http-owner'}, token=f.server.write_token)
        self.assertTrue(response['result']['plan_review']['completed'])
        self.assertTrue(self.cli('code', 'status', self.plan_node['id'])['completed'])
        self.implement(); self.validate()
        state = self.cli('code', 'status', self.delivery['id'])
        response = f.post('/api/reviews/node-plan-complete', {'node': self.delivery['id'],
                         'definition_digest': state['definition_digest'], 'reviewer': 'http-owner'}, token=f.server.write_token)
        self.assertTrue(response['result']['plan_review']['completed'])
        self.assertTrue(self.cli('closure', '--workstream', 'VENV')['ready'])
        self.output.write_text('changed\n')
        with f.get('/api/snapshot') as response:
            view = next(w for w in json.load(response)['workstreams'] if w['workstream'] == 'VENV')
        self.assertFalse(view['closure']['ready'])
        self.assertFalse(self.cli('code', 'status', self.delivery['id'])['can_approve'])

    def test_package_dependency_waits_for_acceptance_and_revokes_transitively(self):
        dependent = copy.deepcopy(self.item)
        dependent.update(key='integration-main', implementation_key='integration:main',
                         title='集成方案', inputs=[*dependent['inputs'], 'cap.venv:interface:main'],
                         output_paths=['verification/tb/top.sv'])
        plan = self.design([self.item, dependent])
        downstream = plan['desired_state'][1]
        self.assertFalse(self.store.node_plan_review_state(downstream['id'])['can_approve'])
        self.implement(); self.validate()
        self.assertFalse(self.store.node_plan_review_state(downstream['id'])['can_approve'])
        self.approve(self.delivery)
        self.approve(downstream)
        self.assertEqual(self.head('art.code_plan:integration:main')['status'], 'VALID')
        self.output.write_text('changed\n')
        self.assertNotEqual(self.head('art.code_plan:integration:main')['status'], 'VALID')
        self.assertEqual(self.head('art.code_plan:interface:main')['status'], 'VALID')

    def test_native_reports_must_bind_current_code_and_baseline(self):
        self.implement(); self.validate()
        evidence = self.root / 'build-evidence.json'
        data = json.loads(evidence.read_text())
        data['artifacts'][0]['path'] = 'rtl/dut.sv'
        data['artifacts'][0]['sha256'] = self.store._digest(self.root / 'rtl/dut.sv')
        data['result']['environment_digest'] = data['artifacts'][0]['sha256']
        evidence.write_text(json.dumps(data))
        with self.assertRaisesRegex(HarnessError, '直接引用'):
            code.validate(self.store, self.delivery['id'], self.report_path.name)
        self.validate()
        manifest = self.store.state / 'project.json'
        data = json.loads(manifest.read_text()); data['baseline_revision'] = 'new-baseline'
        manifest.write_text(json.dumps(data))
        self.assertFalse(self.store.node_plan_review_state(self.delivery['id'])['can_approve'])
        self.approve(self.plan_node)
        state = self.store.node_plan_review_state(self.delivery['id'])
        self.report['input_signature'] = state['input_signature']
        self.report_path.write_text(json.dumps(self.report))
        result = code.validate(self.store, self.delivery['id'], self.report_path.name)
        self.assertFalse(result['ready'])
        self.assertFalse(self.store.node_plan_review_state(self.delivery['id'])['can_approve'])

    def test_smoke_must_match_build_within_integration_delivery(self):
        from tests import test_v1_control_plane as legacy_fixture
        self.item['capabilities'].append('environment-smoke-evidence')
        self.design(); self.implement(); self.validate(register=False)
        fixture = legacy_fixture.V1ControlPlaneTest()
        fixture.root = self.root
        smoke = fixture.write_typed_report('smoke.json', 'EnvironmentEvidence/1', 'environment-smoke-evidence', {
            'clock_edges': 10, 'reset_assertions': 1, 'reset_deassertions': 1, 'observations': 3,
            'errors': 0, 'fatals': 0, 'timeout': False, 'clean_exit': True,
            'environment_digest': '$ARTIFACT_DIGEST', 'log_digest': '$ARTIFACT_DIGEST'})
        self.report['checks'].append({**self.report['checks'][0], 'report': smoke.name, 'claim': 'environment-smoke-evidence'})
        self.report_path.write_text(json.dumps(self.report))
        self.assertFalse(code.validate(self.store, self.delivery['id'], self.report_path.name)['ready'])
        payload = json.loads(smoke.read_text())
        payload['result']['environment_digest'] = self.store._digest(self.output)
        payload['artifacts'].append({'path': self.item['output_paths'][0], 'sha256': self.store._digest(self.output),
                                     'kind': 'source', 'analyzed_by': ['xverif']})
        smoke.write_text(json.dumps(payload))
        self.assertTrue(code.validate(self.store, self.delivery['id'], self.report_path.name)['ready'])

    def test_snapshot_reuses_node_reviews_and_downstream_detects_unsynced_change(self):
        self.implement(); self.validate(); self.approve(self.delivery)
        downstream = self.store._design_workstream('VCASE', None, [], [], [])
        node = next(n for n in downstream['desired_state'] if n['key'] == 'case-implementation')
        self.store.dashboard_snapshot()
        with mock.patch.object(code, 'identity', wraps=code.identity) as identities:
            self.store.dashboard_snapshot()
        self.assertLessEqual(identities.call_count, 4)
        self.output.write_text('changed\n')
        self.assertTrue(any('cap.venv:build-ready' in s for s in self.store._evidence_dependency_blockers(node['id'])))

    def test_source_digest_and_open_question_block_plan(self):
        self.implement()
        (self.root / 'rtl/dut.sv').write_text('module dut(input a); endmodule\n')
        self.assertFalse(self.store.node_plan_review_state(self.plan_node['id'])['completed'])
        q = self.store.ask_agent_question(self.plan_node['id'], '请确认接口范围',
                                         [{'id':'yes', 'label':'确认', 'description':'确认当前接口'},
                                          {'id':'revise', 'label':'修改', 'description':'需要调整接口范围'}])
        self.assertFalse(self.store.node_plan_review_state(self.plan_node['id'])['can_approve'])
        self.assertEqual(q['target'], self.plan_node['id'])

    def test_answering_new_question_requires_new_validation_and_acceptance(self):
        self.implement(); self.validate(); self.approve(self.delivery)
        question = self.store.ask_agent_question(self.delivery['id'], '请确认接口连接范围', [
            {'id': 'yes', 'label': '确认', 'description': '当前范围正确'},
            {'id': 'no', 'label': '修改', 'description': '需要调整范围'},
        ])
        self.assertNotEqual(self.head('cap.venv:interface:main')['status'], 'VALID')
        self.store.answer_agent_question(question['id'], 'yes', 'fixture-owner')
        state = self.store.node_plan_review_state(self.delivery['id'])
        self.assertFalse(state['completed'])
        self.assertFalse(state['can_approve'])
        self.validate()
        self.assertTrue(self.store.node_plan_review_state(self.delivery['id'])['can_approve'])
        self.assertNotEqual(self.head('cap.venv:interface:main')['status'], 'VALID')
        self.approve(self.delivery)
        self.assertEqual(self.head('cap.venv:interface:main')['status'], 'VALID')

    def test_agent_service_uses_venv_revision_and_never_dispatches_owner_review(self):
        from verif_harness import agent_service, workflow_launch
        self.assertFalse(any(t['workstream'] == 'VENV' for t in agent_service.candidates(self.store)))
        launch = workflow_launch.status(self.store)
        workflow_launch.choose(self.store, 'parallel', 'fixture-owner', launch['vdoc_signature'])
        self.implement()
        task = next(t for t in agent_service.candidates(self.store) if t['workstream'] == 'VENV')
        self.assertEqual(task['action']['kind'], 'IMPLEMENT_AND_VALIDATE')
        self.assertIn('code validate', agent_service.prompt_for(self.store, task))
        self.assertEqual(agent_service.current_revision(self.store, 'VENV'), task['revision'])
        activity = self.store.create_agent_service_run(task, 'code-test-run', '.verif-harness/code-test.log')
        self.assertEqual(self.store.activity(activity)['workstream'], 'VENV')
        self.assertEqual(self.store.agent_service_status()['latest_run']['workstream'], 'VENV')
        self.assertTrue(agent_service.task_is_current(self.store, task))
        self.validate()
        self.assertFalse(any(t['workstream'] == 'VENV' for t in agent_service.candidates(self.store)))
        self.fixture.path.write_text('# changed upstream document\n')
        self.assertFalse(agent_service.task_is_current(self.store, task))

    def test_cli_status_matches_snapshot_after_unsynced_invalidation(self):
        self.implement(); self.validate(); self.approve(self.delivery)
        self.output.write_text('changed\n')
        state = self.cli('status', 'VENV')
        self.assertFalse(state['closure']['ready'])
        self.assertEqual(state['plan']['lifecycle'], state['closure']['lifecycle'])
        snapshot = self.store.dashboard_snapshot()
        view = next(w for w in snapshot['workstreams'] if w['workstream'] == 'VENV')
        self.assertEqual(view['lifecycle'], state['plan']['lifecycle'])
        self.assertEqual(view['closure'], state['closure'])

    def test_file_digest_cache_avoids_reopening_unchanged_large_code(self):
        self.implement(); self.validate()
        code.file_snapshot(self.store, [self.item['output_paths'][0]])
        with mock.patch.object(Path, 'open', side_effect=AssertionError('unchanged code reread')):
            code.file_snapshot(self.store, [self.item['output_paths'][0]])

    def test_legacy_dependency_migration_preserves_history(self):
        legacy = self.store._design_workstream('VENV', None, [], [], [])
        old = next(n for n in legacy['desired_state'] if n['key'] == 'build-ready')
        downstream = self.store._design_workstream('VCASE', None, [], [], [])['desired_state'][1]
        self.store.add_dependency(downstream['id'], old['id'])
        self.design()
        self.assertIsNone(self.store.model(old['id'])['nodes'][0]['workstream'])
        edges = self.store.trace(downstream['id'])['outgoing']
        self.assertIn('cap.venv:build-ready', [e['target'] for e in edges])
        self.assertNotIn(old['id'], [e['target'] for e in edges])
        self.assertNotEqual(self.head('cap.venv:build-ready')['status'], 'VALID')
        with self.store.read_connect() as db:
            event = json.loads(db.execute("SELECT payload_json FROM events WHERE kind='venv-replan' ORDER BY rowid DESC LIMIT 1").fetchone()[0])
        self.assertIn(old['id'], [n['id'] for n in event['previous_nodes']])

    def test_workflow_change_api_rejects_stale_or_unauthorized_requests(self):
        f = self.fixture.fixture
        revision = self.store.workstream('VENV')['revision']
        data = {'kind': 'add', 'revision': revision, 'reviewer': 'owner', 'reason': '添加新的接口工作包'}
        for payload, token, status in ((data, None, 403), ({**data, 'revision': revision - 1}, f.server.write_token, 400)):
            with self.assertRaises(urllib.error.HTTPError) as error:
                f.post('/api/code/workflow-change', payload, token=token)
            self.assertEqual(error.exception.code, status)
            error.exception.close()
        response = f.post('/api/code/workflow-change', data, token=f.server.write_token)
        self.assertEqual(response['result']['payload']['next_revision_only'], True)
        self.assertEqual(self.store.workstream('VENV')['revision'], revision)
        self.assertEqual(len(self.store.workstream('VENV')['desired_state']), 1)
        self.assertIn('APPLY_WORKFLOW_CHANGE', [a['kind'] for a in self.store.evaluate_closure('VENV')['actions']])

    def test_completed_code_workflow_change_fails_progress_closed(self):
        self.implement()
        self.validate()
        self.approve(self.delivery)
        plan = self.store.workstream("VENV")
        change = code.request_change(self.store, {
            "workstream": "VENV", "kind": "add", "revision": plan["revision"],
            "reviewer": "fixture-owner", "reason": "增加异常复位恢复工作包",
        })
        view = next(
            item for item in self.store.dashboard_snapshot()["workstreams"]
            if item["workstream"] == "VENV"
        )
        self.assertEqual((view["progress"]["satisfied"], view["progress"]["required"]), (2, 2))
        self.assertFalse(view["closure"]["ready"])
        self.assertIsNone(view["progress"]["percentage"])
        self.assertIn("异常复位恢复", "；".join(view["progress"]["percentage_reasons"]))
        self.assertNotIn(change["id"], {
            item["id"] for item in self.store.dashboard_snapshot()["waiting_for_human"]
        })

    def test_browser_code_plan_and_delivery_approval(self):
        if not shutil.which('node') or subprocess.run(['node', '-e', "require('playwright')"], capture_output=True).returncode:
            self.skipTest('Node.js and Playwright are required for real browser testing')
        from verif_harness.dashboard import dashboard_project_id
        f = self.fixture.fixture
        for phase in ('plan', 'delivery'):
            if phase == 'delivery':
                self.implement(); self.validate()
            config = {'url': f.url, 'project': dashboard_project_id(self.root), 'token': f.server.write_token,
                      'phase': phase, 'node': (self.plan_node if phase == 'plan' else self.delivery)['id']}
            result = subprocess.run(['node', str(Path(__file__).with_name('dashboard_code_workflow.cjs'))],
                                    input=json.dumps(config), text=True, capture_output=True, timeout=90,
                                    env=os.environ.copy())
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(self.cli('code', 'status', config['node'])['completed'])
        self.assertTrue(self.cli('closure', '--workstream', 'VENV')['ready'])
        config['phase'] = 'changes'
        previous = self.store.workstream('VENV')['revision']
        result = subprocess.run(['node', str(Path(__file__).with_name('dashboard_code_workflow.cjs'))],
                                input=json.dumps(config), text=True, capture_output=True, timeout=90,
                                env=os.environ.copy())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.store.workstream('VENV')['revision'], previous + 1)
        self.assertTrue(self.output.is_file())


class CodeWorkflowProfileTest(unittest.TestCase):
    """All downstream workstreams share lifecycle gates without sharing semantics."""

    def setUp(self):
        self.fixture = vdoc_fixture.VdocArtifactsTest()
        self.fixture.setUp()
        self.fixture.prepare()
        self.fixture.finish()
        self.store = self.fixture.store
        self.root = self.store.root

    def tearDown(self):
        self.fixture.tearDown()

    def seed(self, *identifiers):
        with self.store.connect() as connection:
            for identifier in identifiers:
                self.store.upsert_node(
                    connection, identifier, "capability", identifier, Validity.VALID,
                    data={"derived": True, "current": {"fixture": identifier}},
                )

    def proposal(self, workstream, capabilities, inputs):
        key = workstream.lower() + ":main"
        item = {
            "key": workstream.lower() + "-main", "implementation_key": key,
            "role": "code-plan", "title": workstream + " 主验证范围",
            "statement": "实现并验证当前 DUT 的 " + workstream + " 能力",
            "scope": ["当前 DUT 必需验证点"], "work_content": ["实现批准范围内的验证代码"],
            "implementation_approach": ["保持 DUT RTL 只读并使用受控验证入口"],
            "validation_methods": ["执行专用合同检查并核对原始证据"],
            "deliverables": ["验证代码和当前版本证据"],
            "acceptance_criteria": ["实现和运行证据均满足专用合同"],
            "source_refs": ["rtl/", "verification_plan.md"], "inputs": inputs,
            "input_files": ["rtl/dut.sv"],
            "output_paths": [f"verification/{workstream.lower()}/main.sv"],
            "capabilities": capabilities,
        }
        if workstream == "VCOV" and "coverage-model" in capabilities:
            coverage_config = self.root / "verification/config/coverage.toml"
            coverage_config.parent.mkdir(parents=True, exist_ok=True)
            coverage_config.write_text("coverage = true\n", encoding="utf-8")
            item["input_files"].append(str(coverage_config.relative_to(self.root)))
            item["coverage_scope"] = {
                "schema": "CoverageScope/1",
                "code": {"metrics": ["line"], "hierarchy_selectors": ["dut"]},
            }
            item["coverage_implementation_config"] = {
                "schema": "CoverageImplementationConfig/1", "code_coverage_target": "dut",
                "configuration_refs": [{
                    "role": "collection", "path": str(coverage_config.relative_to(self.root)),
                    "sha256": self.store._digest(coverage_config),
                }],
                "compatible_submit_profile_digests": ["b" * 64],
                "toolchain": [{"role": "coverage", "name": "synthetic", "version": "1"}],
            }
        path = self.root / (workstream.lower() + "-code-proposal.json")
        path.write_text(json.dumps({
            "schema": "DesiredStateProposal/1", "workstream": workstream, "nodes": [item],
        }))
        return path, item

    def design(self, workstream, capabilities, inputs):
        path, item = self.proposal(workstream, capabilities, inputs)
        plan = self.store.design_workstream(
            workstream, None, [], [], [], desired_file=path.name,
        )
        return plan, item

    def test_each_code_workstream_uses_only_plan_and_delivery_nodes(self):
        cases = {
            "VSTIM": (
                ["stimulus-implementation", "reachability-evidence", "determinism-evidence"],
                ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence"],
            ),
            "VCHK": (
                ["scoreboard", "scoreboard-evidence"],
                ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence", "cap.vstim:reachability-evidence"],
            ),
            "VCASE": (
                ["case-implementation", "targeted-evidence"],
                ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence", "cap.vstim:reachability-evidence", "cap.vchk:scoreboard-evidence"],
            ),
            "VCOV": (
                ["coverage-model", "coverage-collection"],
                ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence", "cap.vreg:executor-ready"],
            ),
            "VREG": (
                ["regression-policy", "executor-ready"],
                ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence"],
            ),
        }
        # Each subtest uses a fresh project because modern summary capabilities
        # deliberately supersede manually seeded upstream fixtures.
        for index, (workstream, (claims, inputs)) in enumerate(cases.items()):
            if index:
                self.tearDown()
                self.setUp()
            self.seed(*inputs[1:])
            plan, item = self.design(workstream, claims, inputs)
            self.assertTrue(code.modern(plan))
            expected_plan_role = ("coverage-implementation-plan" if workstream == "VCOV" else
                                  "regression-infrastructure-plan" if workstream == "VREG" else "code-plan")
            expected_delivery_role = ("coverage-implementation-deliverable" if workstream == "VCOV" else
                                      "regression-infrastructure-deliverable" if workstream == "VREG" else "code-deliverable")
            self.assertEqual([node["role"] for node in plan["desired_state"]], [expected_plan_role])
            node = plan["desired_state"][0]
            if workstream == "VCOV":
                self.assertIn("覆盖率实现方案", node["role_description"])
                self.assertNotIn("闭环", node["role_description"])
            state = self.store.node_plan_review_state(node["id"])
            self.assertTrue(state["can_approve"], state["blockers"])
            self.store.complete_node_plan_review(node["id"], state["definition_digest"], "fixture-owner")
            current = self.store.workstream(workstream)
            self.assertEqual({node["role"] for node in current["desired_state"]}, {expected_plan_role, expected_delivery_role})
            self.assertEqual(code.ids(item["implementation_key"], workstream)[0],
                             f"art.code_plan:{workstream.lower()}:{item['implementation_key']}")
            view = next(value for value in self.store.dashboard_snapshot()["workstreams"]
                        if value["workstream"] == workstream)
            self.assertTrue(view["code_model"])
            self.assertEqual(view["progress"]["required"], 2)

    def test_dependency_status_recovery_does_not_cascade_plan_reapproval(self):
        cases = (
            ("VSTIM", ["stimulus-implementation", "reachability-evidence", "determinism-evidence"],
             ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence"],
             "cap.venv:environment-smoke-evidence"),
            ("VCOV", ["coverage-model", "coverage-collection"],
             ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence", "cap.vreg:executor-ready"],
             "cap.vreg:executor-ready"),
        )
        for index, (workstream, claims, inputs, dependency) in enumerate(cases):
            if index:
                self.tearDown()
                self.setUp()
            self.seed(*inputs[1:])
            plan, _ = self.design(workstream, claims, inputs)
            node = plan["desired_state"][0]
            state = self.store.node_plan_review_state(node["id"])
            self.store.complete_node_plan_review(node["id"], state["definition_digest"], "fixture-owner")
            approved = self.store.node_plan_review_state(node["id"])
            self.assertTrue(approved["completed"])

            with self.store.connect() as db:
                db.execute("UPDATE nodes SET status='REVALIDATION_REQUIRED' WHERE id=?", (dependency,))
            unavailable = self.store.node_plan_review_state(node["id"])
            self.assertEqual(unavailable["definition_digest"], approved["definition_digest"])
            self.assertFalse(unavailable["completed"])
            self.assertFalse(unavailable["can_approve"])

            self.seed(dependency)
            restored = self.store.node_plan_review_state(node["id"])
            self.assertEqual(restored["definition_digest"], approved["definition_digest"])
            self.assertTrue(restored["completed"])
            same = self.design(workstream, claims, inputs)[0]
            self.assertEqual(same["revision"], plan["revision"])
            self.assertTrue(self.store.node_plan_review_state(node["id"])["completed"])

            with self.store.connect() as db:
                self.store.upsert_node(db, dependency, "capability", dependency, Validity.VALID,
                                       data={"derived": True, "current": {"fixture": "new-version"}})
            changed = self.store.node_plan_review_state(node["id"])
            self.assertNotEqual(changed["definition_digest"], approved["definition_digest"])
            self.assertFalse(changed["completed"])
            self.assertTrue(changed["can_approve"])
            self.assertEqual(self.design(workstream, claims, inputs)[0]["revision"], plan["revision"])
            self.assertFalse(self.store.node_plan_review_state(node["id"])["completed"])

    def test_profile_specific_gates_fail_closed(self):
        with self.assertRaisesRegex(HarnessError, "同配置同 seed"):
            self.design(
                "VSTIM", ["stimulus-implementation", "reachability-evidence"],
                ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence"],
            )
        with self.assertRaisesRegex(HarnessError, "对应的运行证据"):
            self.design(
                "VCHK", ["scoreboard"],
                ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence", "cap.vstim:reachability-evidence"],
            )
        with self.assertRaisesRegex(HarnessError, "下游结果"):
            self.design(
                "VCASE", ["case-implementation", "targeted-evidence"],
                ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence", "cap.vstim:reachability-evidence", "cap.vchk:scoreboard-evidence", "cap.vcov:coverage-collection-evidence"],
            )
        with self.assertRaisesRegex(HarnessError, "两类节点的验证要求不能混在一起"):
            self.design(
                "VCOV", ["coverage-model", "coverage-collection", "hole-analysis-evidence"],
                ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence", "cap.vreg:executor-ready"],
            )
        with self.assertRaisesRegex(HarnessError, "两类节点的验证要求不能混在一起"):
            self.design(
                "VREG", ["regression-policy", "executor-ready", "execution-evidence"],
                ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence"],
            )

    def test_downstream_workflows_only_accept_regression_executor_capability(self):
        cases = {
            "VSTIM": (
                ["stimulus-implementation", "reachability-evidence", "determinism-evidence"],
                ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence"],
            ),
            "VCASE": (
                ["case-implementation", "targeted-evidence"],
                ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence",
                 "cap.vstim:reachability-evidence", "cap.vchk:scoreboard-evidence"],
            ),
            "VCOV": (
                ["coverage-model", "coverage-collection"],
                ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence",
                 "cap.vreg:executor-ready"],
            ),
        }
        for workstream, (claims, inputs) in cases.items():
            with self.subTest(workstream=workstream):
                invalid = [
                    value for value in inputs if value != "cap.vreg:executor-ready"
                ]
                invalid.append("cap.vreg:fresh-evidence")
                with self.assertRaisesRegex(HarnessError, "executor-ready"):
                    self.design(workstream, claims, invalid)

    def test_project_dependency_graph_rejects_cycle_from_persisted_plan(self):
        plan, _ = self.design(
            "VSTIM",
            ["stimulus-implementation", "reachability-evidence", "determinism-evidence"],
            ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence"],
        )
        corrupted = copy.deepcopy(plan["desired_state"])
        corrupted[0]["inputs"].append("cap.vreg:fresh-evidence")
        with self.store.connect() as connection:
            connection.execute(
                "UPDATE workstreams SET desired_json=? WHERE name='VSTIM'",
                (json.dumps(corrupted),),
            )
        proposed = [
            {
                "implementation_key": "dut:infrastructure",
                "role": "regression-infrastructure-plan",
                "title": "DUT 回归基础设施方案",
                "required": True,
                "inputs": ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence"],
                "capabilities": ["regression-policy", "executor-ready"],
            },
            {
                "implementation_key": "dut:results",
                "role": "regression-results-plan",
                "title": "DUT 回归结果方案",
                "required": True,
                "inputs": ["cap.vstim:reachability-evidence", "cap.vreg:dut:infrastructure"],
                "capabilities": ["execution-evidence", "triage-evidence", "fresh-evidence"],
            },
        ]
        with self.assertRaisesRegex(HarnessError, "跨工作流能力依赖形成循环"):
            code._validate_project_dependency_graph(self.store, "VREG", proposed)

    def test_vreg_progress_rejects_ready_closure_with_incomplete_node_count(self):
        infrastructure = {
            "id": "infra", "implementation_key": "dut:infrastructure",
            "role": "regression-infrastructure-plan", "title": "回归基础设施",
            "required": True, "inputs": [],
            "capabilities": ["regression-policy", "executor-ready"],
        }
        results = {
            "id": "results", "implementation_key": "dut:results",
            "role": "regression-results-plan", "title": "回归结果",
            "required": True, "inputs": ["cap.vreg:dut:infrastructure"],
            "capabilities": ["execution-evidence", "triage-evidence", "fresh-evidence"],
        }
        progress = code.workflow_progress(
            {"workstream": "VREG", "desired_state": [infrastructure, results]},
            [infrastructure, results], {"ready": True, "actions": []},
            {"required": 4, "satisfied": 3},
        )
        self.assertIsNone(progress["percentage"])
        self.assertIn("不一致", "；".join(progress["percentage_reasons"]))

    def test_vcase_requires_environment_stimulus_and_checking_not_coverage(self):
        path, _ = self.proposal(
            "VCASE", ["case-implementation", "targeted-evidence"],
            ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence", "cap.vstim:reachability-evidence"],
        )
        with self.assertRaisesRegex(HarnessError, "cap.vchk"):
            self.store.design_workstream("VCASE", None, [], [], [], desired_file=path.name)

    def test_vcase_hole_filling_scope_keeps_existing_case_plan_version(self):
        inputs = ["cap.doc:verification-plan", "cap.venv:environment-smoke-evidence",
                  "cap.vstim:reachability-evidence", "cap.vchk:scoreboard-evidence"]
        self.seed(*inputs[1:])
        plan, item = self.design("VCASE", ["case-implementation", "targeted-evidence"], inputs)
        node = plan["desired_state"][0]
        state = self.store.node_plan_review_state(node["id"])
        self.store.complete_node_plan_review(node["id"], state["definition_digest"], "fixture-owner")
        delivery = next(n for n in self.store.workstream("VCASE")["desired_state"] if code.is_delivery(n))
        extra = {**copy.deepcopy(item), "key": "case-hole-filling",
                 "implementation_key": "case:hole-filling", "title": "新增覆盖率补洞用例",
                 "output_paths": ["verification/vcase/hole_filling.sv"]}
        path = self.root / "vcase-extra.json"
        path.write_text(json.dumps({"schema": "DesiredStateProposal/1", "workstream": "VCASE",
                                    "nodes": [item, extra]}))
        current = self.store.design_workstream("VCASE", None, [], [], [], desired_file=path.name)
        self.assertEqual(current["revision"], plan["revision"] + 1)
        self.assertTrue(self.store.node_plan_review_state(node["id"])["completed"])
        self.assertIn(delivery, current["desired_state"])
        self.assertFalse(self.store.node_plan_review_state(delivery["id"])["can_approve"])
        self.assertFalse(self.store.node_plan_review_state(delivery["id"])["completed"])
        with self.store.read_connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM node_plan_reviews WHERE node_id=?",
                                        (delivery["id"],)).fetchone()[0], 0)

    def test_coverage_and_regression_findings_route_without_mutating_upstream(self):
        coverage = code._feedback_routes("VCOV", "hole-analysis-evidence", {
            "holes": [{"object_key": "code:line:demo.sv:1", "status": "uncovered",
                       "responsible_workstream": "VCASE", "next_action": "增加定向用例"}],
        })
        regression = code._feedback_routes("VREG", "triage-evidence", {
            "failures": [{"test": "demo_test", "disposition": "replan",
                          "responsible_workstream": "VCHK", "next_action": "修正 scoreboard"}],
        })
        self.assertEqual(coverage[0]["responsible_workstream"], "VCASE")
        self.assertEqual(regression[0]["responsible_workstream"], "VCHK")
        self.assertNotIn("VCASE", {plan["workstream"] for plan in self.store.workstreams()})


if __name__ == "__main__":
    unittest.main()
