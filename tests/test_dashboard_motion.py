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
  localStorage: {getItem: () => '', setItem: () => {}},
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

  const sectionNames = ['writing-plan'];
  const planNode = {
    id:'vdoc-plan', key:'vdoc-plan', title:'当前 DUT 文档撰写方案', role:'document-writing-plan',
    status:'REVIEW_REQUIRED', workstream:'VDOC', required:true, purpose:'定义正文撰写范围',
    document_key:'verification-plan', document:{title:'验证计划',path:'docs/verification_plan.md'},
    work_content:['写入接口和验证点'], implementation_approach:['按已确认范围增量撰写'],
    source_refs:['当前 DUT 规格'], scope:['当前 DUT'], deliverables:['验证计划正文'], quality_checks:[],
    human_actions:[], agent_questions:[], outgoing:[], incoming:[],
    plan_review:{status:'APPROVED',completed:false,definition_digest:'digest',completion_reviews:[],sections:sectionNames.map(section => ({section,status:'APPROVED',reviews:[]}))},
  };
  state.snapshot.workstreams = [{workstream:'VDOC',nodes:[planNode],closure:{actions:[]}}];
  const planHtml = documentWritingPlanNodeHtml(planNode, true);
  assert.ok(planHtml.indexOf('文档撰写方案</h3>') < planHtml.indexOf('plan-approval-controls'));
  assert.ok(planHtml.indexOf('审批文档撰写方案') > planHtml.indexOf('plan-approval-controls'));
  assert.ok(planHtml.indexOf('id="node-plan-complete"') > planHtml.indexOf('审批文档撰写方案'));
  assert.match(planHtml, /data-plan-section-form=/);
  assert.match(planHtml, /审批历史记录/);
  assert.doesNotMatch(planHtml, /审批尚未完成|当前工作节点状态|问题和支持材料记录/);
  assert.doesNotMatch(planHtml, /额外待确认的工程问题|审批当前方案，不是验收正文|human-confirmations/);
  assert.doesNotMatch(planHtml, /变更动作|影响范围|具体要求|data-review-change-fields|data-review-impact-preview/);
  assert.doesNotMatch(planHtml, /计划写入的具体内容|输入依据、范围和交付对象|依赖和影响/);
  assert.equal(planHtml.split('data-plan-section-form=').length - 1, 1);
  assert.doesNotMatch(planReviewFormHtml(planNode), /value="approve"|value="clarify"|value="reject"/);
  for (const verdict of ['add','delete','modify']) {
    assert.ok(planHtml.includes('value="' + verdict + '"'));
    const payload = planSectionReviewPayload(planNode, 'writing-plan', planNode.title, {verdict, reviewer:'alice', reason:'审批内容'});
    assert.equal(payload.node, planNode.id);
    assert.equal(payload.definition_digest, 'digest');
    if (['add','modify','delete'].includes(verdict)) {
      assert.equal(payload.verdict, 'modify');
      assert.equal(payload.change_items[0].operation, verdict);
      assert.equal(payload.change_items[0].instruction, '审批内容');
      assert.equal(payload.change_items[0].target, planNode.title);
      assert.equal(planReviewVerdictLabel({verdict:'MODIFY',change_items:payload.change_items}), {add:'新增',modify:'修改',delete:'删除'}[verdict]);
    } else {
      assert.equal(payload.verdict, verdict);
      assert.equal(payload.change_items.length, 0);
    }
  }
  assert.ok(!planHtml.includes('<strong>审批完成</strong>'));
  planNode.plan_review.completed = true;
  const completedPlanHtml = documentWritingPlanNodeHtml(planNode, true);
  assert.match(completedPlanHtml, /id="node-plan-complete" disabled/);
  assert.match(completedPlanHtml, /data-plan-section-form=/);
`, context);
console.log('Dashboard motion renderers PASS');
""",
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
