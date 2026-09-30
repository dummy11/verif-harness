"""VCOV node-type gates at assignment, freshness and exceptional-state boundaries."""

import json
import unittest

from tests import test_vcov_workflow as fixtures
from verif_harness import code_workflow as code
from verif_harness.store import HarnessError, now


class VcovDependencyTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.VcovWorkflowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.store = self.fixture.store

    def persist(self, plan):
        with self.store.connect() as db:
            db.execute("UPDATE workstreams SET desired_json=? WHERE name='VCOV'", (json.dumps(plan['desired_state']),))
            for node in plan['desired_state']:
                db.execute("UPDATE nodes SET data_json=? WHERE id=?", (json.dumps(node), node['id']))

    def test_required_delivery_cannot_be_skipped_as_optional(self):
        delivery = self.fixture.finish_all()
        plan = self.store.workstream('VCOV')
        next(n for n in plan['desired_state'] if n['id'] == delivery['id'])['required'] = False
        self.persist(plan)
        closure = self.store.evaluate_closure('VCOV')
        self.assertFalse(closure['ready'])
        self.assertTrue(any(a['kind'] == 'REFINE_DESIRED_STATE' and '必需交付' in a['reason']
                            for a in closure['actions']))
        self.assertNotEqual(self.fixture.head('cap.vcov:hole-analysis-evidence')['status'], 'VALID')
        progress = self.fixture.view()['progress']
        self.assertEqual(progress['required'], 4)
        self.assertLess(progress['satisfied'], progress['required'])

    def test_legacy_missing_item_scope_requests_replanning_not_permanent_wait(self):
        plan = self.store.workstream('VCOV')
        node = next(n for n in plan['desired_state'] if code.vcov_stage(n) == 'implementation')
        node.pop('coverage_item_ids')
        self.persist(plan)
        state = self.store.node_plan_review_state(node['id'])
        self.assertFalse(state['can_approve'])
        action = next(a for a in self.store.evaluate_closure('VCOV')['actions'] if a['target'] == node['id'])
        self.assertEqual(action['kind'], 'REFINE_DESIRED_STATE')
        self.assertEqual(action['executor'], 'reasoning')

    def test_fresh_evidence_derives_both_typed_deliveries_and_rejects_stale_outputs(self):
        self.fixture.finish_all()
        revision = json.loads((self.store.state / 'project.json').read_text()).get('baseline_revision') or 'fixture'
        summary = {'revision': revision, 'facts': {'snapshot_revision': revision}}
        with self.store.read_connect() as db:
            blockers = self.store._derive_fresh_evidence(db, 'fixture:fresh', summary, self.store._current_desired_nodes(db))
        # This fixture also has unimplemented historical VCHK goals; they must
        # remain blockers, but both current VCOV deliveries are admitted here.
        self.assertFalse(any('代码交付' in blocker for blocker in blockers), blockers)
        expected = {n['id'] for n in self.store.workstream('VCOV')['desired_state'] if code.is_delivery(n)}
        self.assertEqual({n['id'] for n in summary['facts']['required_nodes']}, expected)
        self.fixture.write('verification/coverage/model.sv', 'module changed_coverage; endmodule\n')
        code.refresh(self.store)
        with self.store.read_connect() as db:
            blockers = self.store._derive_fresh_evidence(db, 'fixture:fresh', summary, self.store._current_desired_nodes(db))
        self.assertTrue(blockers)
        self.assertEqual(summary['facts']['required_nodes'], [])

    def test_typed_delivery_assignment_is_bounded_and_plan_writes_are_rejected(self):
        manifest_path = self.store.state / 'project.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['runtime'] = 'codex'
        manifest_path.write_text(json.dumps(manifest))
        delivery = self.fixture.implement()
        action = next(a for a in self.store.evaluate_closure('VCOV')['actions'] if a['target'] == delivery['id'])
        assignment = self.store.claim_agent_work(action['id'], 'coverage-worker', 'CoverageEngineer',
                                                  '实现覆盖率模型', write_scope=delivery['output_paths'])
        self.assertEqual(assignment['node_id'], delivery['id'])
        plan = self.fixture.node('coverage-implementation-plan')
        state = self.store.node_plan_review_state(plan['id'])
        self.store.review_node_plan_section(plan['id'], 'writing-plan', state['definition_digest'],
                                            'modify', 'fixture-owner', '请完善覆盖项说明')
        state = self.store.node_plan_review_state(plan['id'])
        self.store.submit_review_feedback(plan['id'], state['definition_digest'])
        action = next(a for a in self.store.evaluate_closure('VCOV')['actions'] if a['target'] == plan['id'])
        with self.assertRaisesRegex(HarnessError, '只能绑定交付节点'):
            self.store.claim_agent_work(action['id'], 'coverage-planner', 'CoverageEngineer',
                                        '修改方案', write_scope=plan['output_paths'])

    def test_waiver_for_a_longer_item_id_does_not_approve_a_prefix(self):
        self.fixture.finish_implementation()
        delivery = self.fixture.convergence()
        timestamp = now()
        with self.store.connect() as db:
            db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',
                       ('fixture-waiver', 'VCOV', self.store.workstream('VCOV')['revision'], 'WAIVE',
                        'fixture-owner', 'C.DEMO.10: fixture approved exception', timestamp))
        items = [
            {'id': 'C.DEMO.1', 'status': 'excluded', 'hits': 0, 'plan_ref': 'coverage-plan.md',
             'waiver': {'id': 'fixture-waiver', 'reviewer': 'fixture-owner',
                        'decision_date': timestamp[:10], 'rationale': 'fixture exception', 'status': 'Approved'}},
            {'id': 'C.DEMO.2', 'status': 'covered', 'hits': 1, 'plan_ref': 'coverage-plan.md'},
        ]
        result = self.fixture.validate(delivery, items=items)
        self.assertFalse(result['ready'])
        self.assertTrue(any('负责人例外批准记录' in reason for reason in result['blockers']))


if __name__ == '__main__':
    unittest.main()
