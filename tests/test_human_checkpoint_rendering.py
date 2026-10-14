"""Current owner actions, not old activities or generic criteria, drive prompts."""
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HumanCheckpointRenderingTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Dashboard rendering tests require Node.js')
    def test_current_owner_actions_and_blocked_delivery_labels(self):
        result = subprocess.run(['node', '-', str(ROOT / 'verif_harness/dashboard.html')],
            input=r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(process.argv[2], 'utf8');
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(source);
const context = vm.createContext({assert, URLSearchParams,
  window:{location:{search:''}}, localStorage:{getItem:()=>'',setItem:()=>{}},
  document:{querySelector:()=>({content:'synthetic-token'}),querySelectorAll:()=>[]}});
vm.runInContext(source.slice(0, source.indexOf("    $('#drawer-backdrop').onclick")), context);
vm.runInContext(`
  state.snapshot = {workstreams:[]};
  for (const role of ['document-writing-plan','document-deliverable',...CODE_PLAN_ROLES,...CODE_DELIVERY_ROLES]) {
    const node = {id:'fixture', role, status:'REVALIDATION_REQUIRED', next_actions:[],
      activities:[{status:'WAITING_FOR_HUMAN'}],
      closure_assessment:{acceptance_results:[{status:'HUMAN_REVIEW_REQUIRED'}]}};
    assert.equal(humanNeed(node), '当前不需要负责人处理');
    node.next_actions = [{kind:'HUMAN_REVIEW',executor:'human',reason:'请审阅当前接口方案'}];
    assert.equal(humanNeed(node), '请审阅当前接口方案');
    node.agent_questions = [{id:'question',status:'OPEN'}];
    assert.match(humanNeed(node), /等待你回答/);
    if (isCodeNode(node)) {
      assert.equal(pendingItemStatusLabel({source:'closure',action:'HUMAN_REVIEW'}, node),
        isCodePlanNode(node) ? '待审批' : '待验收');
      assert.equal(pendingItemStatusLabel({source:'closure',action:'SUBMIT_REVIEW_FEEDBACK'}, node), '待提交意见');
    }
  }
  const body = {id:'body',role:'document-deliverable',status:'UNKNOWN',
    delivery_review:{status:'PENDING'},next_actions:[{kind:'WAIT_FOR_DEPENDENCY',executor:'agent'}]};
  assert.match(nodeStatusHtml(body), /等待前置工作完成/);
  assert.doesNotMatch(nodeStatusHtml(body), /待验收|需要负责人阅读/);
  body.next_actions = [{kind:'HUMAN_REVIEW',executor:'human',reason:'请审阅当前正文'}];
  assert.match(nodeStatusHtml(body), /待验收/);
  assert.match(nodeStatusHtml(body), /请审阅当前正文/);
  body.next_actions = [];
  assert.match(nodeStatusHtml(body), /等待 Agent 核对正文验收条件/);
  assert.doesNotMatch(nodeStatusHtml(body), /待验收/);

  const codeDelivery = {id:'vreg-delivery',role:'regression-infrastructure-deliverable',
    title:'回归策略交付',status:'REVALIDATION_REQUIRED',work_content:['核对当前回归策略与证据'],
    plan_review:{sections:[{section:'writing-plan',status:'PENDING'}]},
    delivery_review:{status:'PENDING'}};
  state.snapshot = {workstreams:[{workstream:'VREG',nodes:[codeDelivery]}]};
  const deliveryRow = humanRows([{source:'closure',target:codeDelivery.id,target_type:'node',
    action:'HUMAN_REVIEW',status:'OPEN',reason:'等待负责人验收回归基础设施交付'}]);
  assert.match(deliveryRow, /验收：回归策略交付/);
  assert.match(deliveryRow, /验收内容：核对当前回归策略与支持材料/);
  assert.doesNotMatch(deliveryRow, /待审批：|方案内容：/);
`, context);
""", text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
