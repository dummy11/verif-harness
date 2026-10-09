"""Node-bound waits and Dashboard actions share authority in isolated projects.

All approval/evidence data is synthetic. No real DUT is approved or executed.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
from contextlib import contextmanager
from unittest import mock

from tests import test_code_workflow as code_fixtures
from tests import test_vcov_workflow as coverage_fixtures
from tests import test_vdoc_artifacts as doc_fixtures
from tests import test_vreg_workflow as regression_fixtures
from verif_harness import workflow_launch
from verif_harness.dashboard import dashboard_project_id
from verif_harness.store import HarnessError


ROOT = Path(__file__).resolve().parents[1]


class HumanCheckpointTest(unittest.TestCase):
    @contextmanager
    def project(self, fixture_type):
        fixture = fixture_type()
        fixture.setUp()
        try:
            yield fixture
        finally:
            fixture.tearDown()

    def snapshot(self, http):
        with http.get('/api/snapshot') as response:
            return json.load(response)

    def cli(self, store, *args):
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/verif_harness.py'), *args,
             '--project-root', str(store.root)], text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def approve_while_waiting(self, fixture, workstream, node, document=False):
        store = fixture.store
        http = fixture.fixture if document else fixture.fixture.fixture
        before = self.snapshot(http)
        view = next(w for w in before['workstreams'] if w['workstream'] == workstream)
        pending = [a for a in view['waiting_for_human'] if a['source'] == 'closure']
        self.assertIn(node['id'], [a['target'] for a in pending])
        self.assertEqual(self.cli(store, 'status', workstream)['closure'], view['closure'])
        responses = []

        def decide(_seconds):
            self.assertFalse(responses, 'one owner approval must suffice')
            state = (store.document_delivery_review_state(node['id']) if document
                     else store.node_plan_review_state(node['id']))
            body = {'node': node['id'], 'definition_digest': state['definition_digest'],
                    'reviewer': 'synthetic-owner'}
            endpoint = '/api/reviews/node-plan-complete'
            if document:
                endpoint = '/api/reviews/document-delivery'
                body.update(document_digest=state['document_digest'], verdict='approve')
            responses.append(http.post(endpoint, body, http.server.write_token)['result'])

        with mock.patch('verif_harness.store.time.sleep', side_effect=decide):
            result = store.await_human_review(workstream, timeout=1, node_ids=[node['id']])
        self.assertEqual(result['status'], 'DECIDED')
        self.assertEqual(result['checkpoint']['node_id'], node['id'])
        self.assertEqual(result['review']['id'], responses[0]['review_id'])
        self.assertTrue(result['resume'])
        after = self.snapshot(http)
        view = next(w for w in after['workstreams'] if w['workstream'] == workstream)
        self.assertNotIn(node['id'], [a['target'] for a in view['waiting_for_human'] if a['source'] == 'closure'])
        self.assertEqual(self.cli(store, 'closure', '--workstream', workstream), view['closure'])
        self.assertEqual(result['closure'], view['closure'])
        return result, view

    def test_venv_plan_and_validated_delivery_wake_from_http_approval(self):
        with self.project(code_fixtures.CodeWorkflowTest) as f:
            self.approve_while_waiting(f, 'VENV', f.plan_node)
            f.implement()
            self.assertTrue(f.validate()['ready'])
            snapshot = self.snapshot(f.fixture.fixture)
            self.assertIn('验证交付验收', snapshot['project_agent']['message'])
            result, view = self.approve_while_waiting(f, 'VENV', f.delivery)
            self.assertEqual(result['next'], 'closure')
            self.assertTrue(view['closure']['ready'])
            self.assertTrue(self.cli(f.store, 'code', 'status', f.delivery['id'])['completed'])

    def test_all_other_code_plan_profiles_wake(self):
        cases = {
            'VSTIM': (['stimulus-implementation', 'reachability-evidence', 'determinism-evidence'],
                      ['cap.doc:verification-plan', 'cap.venv:environment-smoke-evidence']),
            'VCHK': (['scoreboard', 'scoreboard-evidence'],
                     ['cap.doc:verification-plan', 'cap.venv:environment-smoke-evidence', 'cap.vstim:reachability-evidence']),
            'VCASE': (['case-implementation', 'targeted-evidence'],
                      ['cap.doc:verification-plan', 'cap.venv:environment-smoke-evidence',
                       'cap.vstim:reachability-evidence', 'cap.vchk:scoreboard-evidence']),
        }
        for workstream, (claims, inputs) in cases.items():
            with self.subTest(workstream=workstream), self.project(code_fixtures.CodeWorkflowProfileTest) as f:
                f.seed(*inputs[1:])
                plan, _ = f.design(workstream, claims, inputs)
                self.approve_while_waiting(f, workstream, plan['desired_state'][0])

    def test_all_four_coverage_roles_wake_without_bypassing_validation(self):
        with self.project(coverage_fixtures.VcovWorkflowTest) as f:
            for stage in ('implementation', 'convergence'):
                self.approve_while_waiting(f, 'VCOV', f.node('coverage-' + stage + '-plan'))
                node = f.implement(approve=False) if stage == 'implementation' else f.convergence(approve=False)
                self.assertTrue(f.validate(node)['ready'])
                self.approve_while_waiting(f, 'VCOV', node)
            self.assertTrue(f.store.evaluate_closure('VCOV')['ready'])

    def test_all_four_regression_roles_wake_without_bypassing_validation(self):
        with self.project(regression_fixtures.VregWorkflowTest) as f:
            for stage in ('infrastructure', 'results'):
                self.approve_while_waiting(f, 'VREG', f.node('regression-' + stage + '-plan'))
                node = f.infrastructure(approve=False) if stage == 'infrastructure' else f.results(approve=False)
                self.assertTrue(f.validate(node)['ready'])
                self.approve_while_waiting(f, 'VREG', node)
            self.assertTrue(f.store.evaluate_closure('VREG')['ready'])

    def test_vdoc_plan_and_body_waits_do_not_replay_plan_approval_or_skip_agent_check(self):
        with self.project(doc_fixtures.VdocArtifactsTest) as f:
            # Writing plans use the same node approval endpoint as code plans.
            adapter = type('FixtureAdapter', (), {'store': f.store, 'fixture': f})()
            self.approve_while_waiting(adapter, 'VDOC', f.plan)
            f.prepare()
            timed_out = f.store.await_human_review('VDOC', timeout=0)
            self.assertEqual(timed_out['status'], 'TIMEOUT', 'old whole-workflow plan approval is not body acceptance')
            result, view = self.approve_while_waiting(f, 'VDOC', f.delivery, document=True)
            self.assertEqual(result['next'], 'check_document_review')
            self.assertFalse(view['closure']['ready'])
            self.assertIn('CHECK_DOCUMENT_REVIEW', [a['kind'] for a in view['closure']['actions']])
            f.store.complete_review_agent_check(result['review']['id'], 'Project Main Agent', '已检查合成正文及依赖')
            self.assertTrue(f.store.evaluate_closure('VDOC')['ready'])
            with self.assertRaisesRegex(HarnessError, '当前没有等待负责人评审的检查点'):
                f.store.await_human_review('VDOC', timeout=0)

    def test_draft_opinions_do_not_wake_but_submitted_code_feedback_does(self):
        with self.project(code_fixtures.CodeWorkflowTest) as f:
            node = f.plan_node
            state = f.store.node_plan_review_state(node['id'])
            f.store.review_node_plan_section(node['id'], 'writing-plan', state['definition_digest'],
                                             'modify', 'synthetic-owner', '补充接口方向的检查')
            self.assertEqual(f.store.await_human_review('VENV', timeout=0)['status'], 'TIMEOUT')
            with mock.patch('verif_harness.store.time.sleep', side_effect=lambda _: f.store.submit_review_feedback(node['id'], state['definition_digest'])):
                result = f.store.await_human_review('VENV', timeout=1)
            self.assertEqual(result['status'], 'ACTION_REQUIRED')
            self.assertEqual(result['checkpoint']['node_id'], node['id'])
            self.assertEqual(result['next'], 'apply_review_feedback')
            self.assertFalse(f.store.node_plan_review_state(node['id'])['completed'])

    def test_node_scope_multiple_pending_nodes_and_after_review_cursor(self):
        with self.project(code_fixtures.CodeWorkflowTest) as f:
            other = copy.deepcopy(f.item)
            other.update(key='second', implementation_key='interface:second', title='第二接口方案',
                         output_paths=['verification/tb/second.sv'])
            plan = f.design([f.item, other])
            first, second = plan['desired_state']
            with mock.patch('verif_harness.store.time.sleep', side_effect=lambda _: f.approve(first)):
                result = f.store.await_human_review('VENV', timeout=1)
            self.assertFalse(result['closure']['ready'])
            self.assertIn(second['id'], [a['target'] for a in result['closure']['actions'] if a['executor'] == 'human'])
            self.assertEqual(f.store.await_human_review('VENV', timeout=0,
                after_review_id=result['review']['id'], node_ids=[second['id']])['status'], 'TIMEOUT')
            approved = f.approve(second)
            next_result = f.store.await_human_review('VENV', timeout=0, after_review_id=result['review']['id'])
            self.assertEqual(next_result['review']['id'], approved['review_id'])
            with self.assertRaisesRegex(HarnessError, '不属于'):
                f.store.await_human_review('VENV', timeout=0, node_ids=[f.fixture.plan['id']])
            with self.assertRaisesRegex(HarnessError, '同一 Workstream'):
                f.store.await_human_review('VDOC', timeout=0, after_review_id=approved['review_id'])

    def test_revision_and_evidence_changes_invalidate_active_wait(self):
        for change in ('revision', 'evidence'):
            with self.subTest(change=change), self.project(code_fixtures.CodeWorkflowTest) as f:
                f.implement()
                f.validate()
                activity = f.store.create_activity(f.delivery['id'], 'await fixture acceptance', 'Project Main Agent')

                def mutate(_):
                    if change == 'revision':
                        f.design()
                    else:
                        (f.root / 'build.log').write_text('changed synthetic evidence\n')

                with mock.patch('verif_harness.store.time.sleep', side_effect=mutate):
                    with self.assertRaisesRegex(HarnessError, '版本已变化'):
                        f.store.await_human_review('VENV', timeout=1, activity_id=activity['id'])
                self.assertNotEqual(f.store.activity(activity['id'])['status'], 'WAITING_FOR_HUMAN')

    def test_approval_during_initial_binding_is_not_lost(self):
        with self.project(code_fixtures.CodeWorkflowTest) as f:
            original = f.store.node_plan_review_state
            approval = []

            def state_and_approve(identifier):
                state = original(identifier)
                if not approval and identifier == f.plan_node['id']:
                    approval.append(True)
                    f.approve(f.plan_node)
                    state = original(identifier)
                return state

            with mock.patch.object(f.store, 'node_plan_review_state', side_effect=state_and_approve):
                result = f.store.await_human_review('VENV', timeout=0, node_ids=[f.plan_node['id']])
            self.assertEqual(result['status'], 'DECIDED')

    def test_legacy_workflow_approval_during_closure_read_is_not_lost(self):
        with self.project(doc_fixtures.VdocArtifactsTest) as f:
            original = f.store.evaluate_closure
            calls = []
            approval = []

            def closure_and_approve(*args, **kwargs):
                calls.append(True)
                if len(calls) == 2:
                    approval.append(f.store.review_workstream('VDOC', 'approve', 'synthetic-owner', '批准合成方案'))
                return original(*args, **kwargs)

            with mock.patch.object(f.store, 'evaluate_closure', side_effect=closure_and_approve):
                result = f.store.await_human_review('VDOC', timeout=0)
            self.assertEqual(result['status'], 'DECIDED')
            self.assertEqual(result['review']['id'], approval[0]['review_id'])

    def test_changed_document_and_other_project_reviews_cannot_release_wait(self):
        with self.project(doc_fixtures.VdocArtifactsTest) as f:
            f.prepare()

            def change_body(_):
                f.path.write_text('# 已变化的合成正文\n')
                f.store.sync_documents()

            with mock.patch('verif_harness.store.time.sleep', side_effect=change_body):
                with self.assertRaisesRegex(HarnessError, '版本已变化'):
                    f.store.await_human_review('VDOC', timeout=1, node_ids=[f.delivery['id']])
        with self.project(code_fixtures.CodeWorkflowTest) as first:
            review = first.approve(first.plan_node)
            with self.project(code_fixtures.CodeWorkflowTest) as second:
                with self.assertRaisesRegex(HarnessError, '未知 review'):
                    second.store.await_human_review('VENV', after_review_id=review['review_id'], timeout=0)

    def test_stale_waiting_activity_without_owner_action_is_reported_as_conflict(self):
        with self.project(code_fixtures.CodeWorkflowTest) as f:
            f.implement()
            f.validate()
            f.approve(f.delivery)
            f.store.review_workstream('VCHK', 'approve', 'synthetic-owner', '关闭隔离测试的旧式方案待办')
            launch = f.store.dashboard_snapshot()['workflow_launch']
            workflow_launch.choose(f.store, 'parallel', 'synthetic-owner', launch['vdoc_signature'])
            activity = f.store.create_activity(f.delivery['id'], 'stale wait record', 'Project Main Agent')
            f.store.update_activity(activity['id'], 'WAITING_FOR_HUMAN', '旧等待记录')
            snapshot = self.snapshot(f.fixture.fixture)
            self.assertFalse(snapshot['waiting_for_human'])
            self.assertEqual(snapshot['project_agent']['status'], 'UNCONFIRMED')
            self.assertIn('等待状态不一致', snapshot['project_agent']['message'])
            with self.assertRaisesRegex(HarnessError, '当前没有等待负责人评审的检查点'):
                f.store.await_human_review('VENV', timeout=0, activity_id=activity['id'])
            self.assertEqual(f.store.activity(activity['id'])['status'], 'PENDING')

    def test_browser_pending_delivery_navigation_and_cli_checkpoint_resume(self):
        if not shutil.which('node') or subprocess.run(['node', '-e', "require('playwright')"], capture_output=True).returncode:
            self.skipTest('Node.js and Playwright are required')
        with self.project(code_fixtures.CodeWorkflowTest) as f:
            f.implement()
            f.validate()
            http = f.fixture.fixture
            activity = f.store.create_activity(f.delivery['id'], 'synthetic acceptance wait', 'Project Main Agent')
            waiter = subprocess.Popen(
                [sys.executable, str(ROOT / 'scripts/verif_harness.py'), 'await-human', 'VENV',
                 '--node', f.delivery['id'], '--activity', activity['id'], '--timeout', '60',
                 '--project-root', str(f.root)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 10
                while f.store.activity(activity['id'])['status'] != 'WAITING_FOR_HUMAN':
                    self.assertIsNone(waiter.poll())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.05)
                config = {'url': http.url, 'project': dashboard_project_id(f.root),
                          'token': http.server.write_token, 'phase': 'delivery',
                          'node': f.delivery['id'], 'pendingNavigation': True}
                browser = subprocess.run(['node', str(ROOT / 'tests/dashboard_code_workflow.cjs')],
                    input=json.dumps(config), text=True, capture_output=True, timeout=90, env=os.environ.copy())
                self.assertEqual(browser.returncode, 0, browser.stdout + browser.stderr)
                stdout, stderr = waiter.communicate(timeout=10)
                self.assertEqual(waiter.returncode, 0, stdout + stderr)
                self.assertEqual(json.loads(stdout)['status'], 'DECIDED')
                self.assertTrue(self.cli(f.store, 'closure', '--workstream', 'VENV')['ready'])
            finally:
                if waiter.poll() is None:
                    waiter.terminate()
                waiter.communicate(timeout=10)


if __name__ == '__main__':
    unittest.main()
