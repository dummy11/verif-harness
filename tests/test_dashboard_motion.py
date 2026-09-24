"""Execute the actual Dashboard renderers; motion must not invent state/progress."""

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DashboardMotionTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Dashboard renderer checks require Node.js")
    def test_motion_follows_state_without_changing_progress(self) -> None:
        result = subprocess.run(
            ["node", "-", str(ROOT / "verif_harness/dashboard.html")],
            input=r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(process.argv[2], 'utf8');
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(source); // Syntax-check even the browser bootstrap omitted below.
const elements = new Map();
const context = vm.createContext({
  assert, URLSearchParams,
  window: {location: {search: ''}},
  document: {
    querySelector: selector => {
      if (!elements.has(selector)) elements.set(selector, {content: 'test-token', innerHTML: ''});
      return elements.get(selector);
    },
    querySelectorAll: () => [],
  },
});
vm.runInContext(source.slice(0, source.indexOf("    $('#drawer-backdrop').onclick")), context);
vm.runInContext(`
  for (const value of ['RUNNING', 'ACTIVE', 'AGENT_CHECKING']) {
    assert.match(statusBadge(value), /data-motion="active"/);
  }
  for (const value of ['REVIEW', 'PENDING', 'WAITING_FOR_HUMAN', 'WAITING_FOR_PARENT']) {
    assert.match(statusBadge(value), /data-motion="waiting"/);
  }
  for (const value of ['CLOSED', 'VALID', 'APPROVED', 'COMPLETED', 'FAILED', 'INVALID', 'CANCELLED', 'STALE', 'EXPIRED', 'SUPERSEDED', 'UNKNOWN']) {
    assert.doesNotMatch(statusBadge(value), /status-pulse/);
  }
  assert.match(planReviewStatusBadge('PENDING'), /data-motion="waiting"/);
  assert.doesNotMatch(planReviewStatusBadge('APPROVED'), /status-pulse/);
  assert.match(deliveryReviewStatusBadge('AGENT_CHECKING'), /data-motion="active"/);
  assert.doesNotMatch(deliveryReviewStatusBadge('APPROVED'), /status-pulse/);

  state.snapshot = {workstreams: [], activities: [{node_id:'project', status:'RUNNING', operation:'plan VDOC'}], project:{}};
  const before = JSON.stringify(state.snapshot);
  renderOverview();
  assert.match($('#main').innerHTML, /0 条已登记工作流/);
  assert.match($('#main').innerHTML, /planning-indicator.*data-motion="active"/);
  assert.doesNotMatch($('#main').innerHTML, /data-workstream=/);
  assert.equal(JSON.stringify(state.snapshot), before);
  state.snapshot.activities[0].status = 'WAITING_FOR_HUMAN';
  renderOverview();
  assert.match($('#main').innerHTML, /planning-indicator.*data-motion="waiting"/);

  const w = {workstream:'VCHK', lifecycle:'ACTIVE', revision:1, nodes:[], progress:{required:4,satisfied:1}, closure:{ready:false,actions:[]}};
  assert.match(wsCard(w), /class="ws-meter" data-motion="active" style="--value:25;/);
  w.waiting_for_human = [{source:'agent-question'}];
  assert.match(wsCard(w), /class="ws-meter" data-motion="waiting" style="--value:25;/);
  w.waiting_for_human = [];
  w.lifecycle = 'REVIEW';
  assert.match(wsCard(w), /class="ws-meter" data-motion="waiting" style="--value:25;/);
  assert.match(workstreamStatusCardHtml(w), /status-pulse/);
  w.lifecycle = 'SATISFIED'; w.closure.ready = true; w.progress.satisfied = 4;
  assert.match(wsCard(w), /class="ws-meter" data-motion="none" style="--value:100;/);
  assert.doesNotMatch(workstreamStatusBadge(w), /status-pulse/);

  const n = {status:'UNKNOWN', workstream:'VCHK', progress_measures:[{id:'checks',label:'检查项',target:4,unit:'项',source:'test'}], progress_observation:{checks:0}, activities:[{status:'RUNNING'}]};
  for (const [count, ratio] of [[0,0],[2,50],[4,100]]) {
    n.progress_observation.checks = count;
    const beforeNode = JSON.stringify(n);
    const rendered = nodeProgressHtml(n);
    assert.match(rendered, /class="node-progress-bar" data-motion="active"/);
    assert.ok(rendered.includes('aria-valuenow="' + ratio + '"'));
    assert.ok(rendered.includes('width:' + ratio + '%'));
    assert.equal(JSON.stringify(n), beforeNode);
  }
  n.agent_questions = [{status:'OPEN',id:'q'}];
  assert.equal(nodeMotion(n), 'waiting');
  n.agent_questions = [];
  n.delivery_review = {status:'AGENT_CHECKING'};
  assert.equal(nodeMotion(n), 'active');
  n.delivery_review.status = 'PENDING';
  assert.equal(nodeMotion(n), 'waiting');
  n.delivery_review.status = 'APPROVED'; n.status = 'VALID';
  assert.match(nodeProgressHtml(n), /class="node-progress-bar" data-motion="none"/);
  assert.doesNotMatch(nodeProgressHtml(n), /status-pulse/);
  for (const status of ['FAILED','INVALID','CANCELLED','STALE','EXPIRED','SUPERSEDED']) {
    assert.equal(nodeMotion({...n,status}), 'none');
  }
  assert.match(progressRing(50, 'Activity', true, 'active'), /data-motion="active"/);
  assert.match(progressRing(100, 'Activity complete'), /data-motion="none"/);
`, context);
console.log('Dashboard motion renderers PASS');
""",
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
