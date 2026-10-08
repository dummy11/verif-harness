// Every governed public node uses the same list/detail approval policy.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const elements = new Map();
const rowButtons = [];
const context = vm.createContext({
  assert, console, URL, URLSearchParams, rowButtons,
  window:{location:{search:'',href:'http://example.invalid/?workstream=VDOC'}},
  localStorage:{getItem:() => '',setItem:() => {}},
  document:{
    querySelector:selector => {
      if (!elements.has(selector)) elements.set(selector, {
        content:'test-token',innerHTML:'',dataset:{},
        classList:{add:() => {},remove:() => {},contains:() => false},
      });
      return elements.get(selector);
    },
    querySelectorAll:selector => selector === '[data-approve-plan-node]' ? rowButtons : [],
  },
});
vm.runInContext(source.slice(0, source.indexOf("    $('#drawer-backdrop').onclick")), context);
vm.runInContext(String.raw`
(async () => {
  const emptyFeedback = () => ({draft_count:0,processing_count:0,unresolved_count:0,can_approve:true});
  const types = [
    ['VDOC','document-writing-plan'],['VDOC','document-deliverable'],
    ...['VENV','VSTIM','VCHK','VCASE'].flatMap(w => [[w,'code-plan'],[w,'code-deliverable']]),
    ...['coverage-implementation-plan','coverage-implementation-deliverable',
      'coverage-convergence-plan','coverage-convergence-deliverable'].map(role => ['VCOV',role]),
    ...['regression-infrastructure-plan','regression-infrastructure-deliverable',
      'regression-results-plan','regression-results-deliverable'].map(role => ['VREG',role]),
  ];
  const nodes = types.map(([workstream,role], index) => ({
    id:'node-' + index,workstream,role,title:'FIFO 验证节点',required:true,status:'PENDING',
    source_refs:[],next_actions:[],activities:[],
    plan_review:{definition_digest:'plan-current',completed:false,can_approve:true,status:'PENDING',feedback:emptyFeedback()},
  }));
  const writing = nodes[0], delivery = nodes[1];
  delete delivery.plan_review;
  delivery.document = {id:'document-current',path:'docs/verification_plan.md',title:'验证总计划'};
  delivery.delivery_review = {document_id:'document-current',document_digest:'body-current',
    definition_digest:'delivery-current',document_available:true,status:'PENDING',reviews:[],feedback:emptyFeedback()};
  state.project = 'project-current';
  state.snapshot = {project:{},agent_questions:[],activities:[],model:{nodes:[],edges:[]},
    workstreams:['VDOC','VENV','VSTIM','VCHK','VCASE','VCOV','VREG'].map(workstream => ({
      workstream,revision:1,lifecycle:'ACTIVE',nodes:nodes.filter(n => n.workstream === workstream),closure:{actions:[]},
    }))};
  writing.plan_review.status = 'APPROVED'; writing.plan_review.completed = true;
  const compare = n => {
    const policy = nodeApprovalState(n);
    const row = nodeRows([n]).match(/<button[^>]*data-approve-plan-node="[^\"]+"[^>]*>[^<]*<\/button>/)[0];
    const panel = n.delivery_review ? deliveryApprovalPanelHtml(n) : nodePlanApprovalPanelHtml(n,planApprovalAvailable(n));
    const detail = panel.match(/<button[^>]*id="node-(?:plan|delivery)-complete"[^>]*>[^<]*<\/button>/)[0];
    assert.equal(row.includes(' disabled'), !policy.enabled, n.workstream + '/' + n.role);
    assert.equal(detail.includes(' disabled'), !policy.enabled, n.workstream + '/' + n.role);
    assert.ok(row.endsWith('>' + policy.label + '</button>'));
    assert.ok(detail.endsWith('>' + policy.label + '</button>'));
  };
  for (const n of nodes) {
    writing.plan_review.status = n === writing ? 'PENDING' : 'APPROVED';
    writing.plan_review.completed = n !== writing;
    compare(n);
    assert.equal(nodeApprovalState(n).enabled,true, n.workstream + '/' + n.role + ' ready');
    const review = n.delivery_review || n.plan_review;
    review.feedback = {draft_count:1,processing_count:0,unresolved_count:1,can_approve:false};
    compare(n); assert.equal(nodeApprovalState(n).enabled,false);
    review.feedback = {draft_count:0,processing_count:1,unresolved_count:1,can_approve:false};
    compare(n); assert.equal(nodeApprovalState(n).enabled,false);
    review.feedback = emptyFeedback();
    if (n.delivery_review) {
      for (const status of ['AGENT_CHECKING','WAITING_FOR_HUMAN','APPROVED']) {
        review.status = status; review.current_review = {verdict:'APPROVE'};
        compare(n); assert.equal(nodeApprovalState(n).enabled,false);
      }
      review.status = 'PENDING'; delete review.current_review;
    } else {
      review.completed = true; compare(n); assert.equal(nodeApprovalState(n).enabled,false);
      review.completed = false; review.can_approve = false;
      if (n !== writing) { compare(n); assert.equal(nodeApprovalState(n).enabled,false); }
      review.can_approve = true;
    }
  }
  writing.plan_review.completed = true; writing.plan_review.status = 'APPROVED';
  const vdoc = workstream('VDOC');
  for (const change of [
    () => { writing.plan_review.status = 'PENDING'; },
    () => { vdoc.lifecycle = 'DESIGNED'; },
    () => { delivery.next_actions = [{kind:'WAIT_FOR_DEPENDENCY'}]; },
    () => { vdoc.closure.actions = [{kind:'REFINE_DOCUMENT_DELIVERIES'}]; },
  ]) {
    change(); compare(delivery); assert.equal(nodeApprovalState(delivery).enabled,false);
    writing.plan_review.status = 'APPROVED'; vdoc.lifecycle = 'ACTIVE';
    delivery.next_actions = []; vdoc.closure.actions = [];
  }
  for (const unavailable of [
    {document_available:false}, {acceptance_blockers:['仍有待确认问题']},
  ]) {
    Object.assign(delivery.delivery_review,unavailable);
    compare(delivery); assert.equal(nodeApprovalState(delivery).enabled,false);
    delivery.delivery_review.document_available = true; delivery.delivery_review.acceptance_blockers = [];
  }
  const results = nodes.find(n => n.role === 'regression-results-deliverable');
  for (const status of ['REQUESTED','DISPATCHED','RUNNING','INTERRUPTED','FAILED']) {
    results.plan_review.regression_execution = {current:{status}};
    compare(results); assert.equal(nodeApprovalState(results).enabled,false);
  }
  results.plan_review.regression_execution.current.status = 'VALIDATED';
  compare(results); assert.equal(nodeApprovalState(results).enabled,true);
  for (const role of ['document-catalog','capability','closure-evidence']) {
    const internal = {id:'internal',role,title:'内部产物',workstream:'VDOC',status:'PENDING'};
    assert.equal(nodeApprovalState(internal),null);
    assert.ok(!nodeRows([internal]).includes('data-approve-plan-node'));
  }

  // A real list click is bound to the same current node and controlled body.
  const opened = [], warnings = [], reads = [];
  openNodePlanCompletionModal = n => opened.push(n.id);
  toast = message => warnings.push(message);
  const body = {document:{id:'document-current',digest:'body-current',content_changed:false},content:'# FIFO 验证计划'};
  const button = () => ({dataset:{approvePlanNode:delivery.id},disabled:false,textContent:'批准全部内容'});
  rowButtons.push(button()); bindNodeLinks();
  approvalRequest = async url => { reads.push(url); return body; };
  await rowButtons[0].onclick({stopPropagation:() => {}});
  assert.deepEqual(opened,[delivery.id]);
  assert.ok(reads[0].includes('project=project-current&selector=document-current'));
  assert.equal(warnings.length,0);
  for (const response of [
    {...body,document:{...body.document,digest:'changed'}},
    {...body,document:{...body.document,id:'wrong-document'}},
    {...body,document:{...body.document,content_changed:true}},
    {...body,content:undefined},
  ]) {
    opened.length = 0; approvalRequest = async () => response;
    await openNodeApprovalFromList(button()); assert.equal(opened.length,0);
  }
  approvalRequest = async () => { throw new Error('正文不可读'); };
  await openNodeApprovalFromList(button());
  assert.equal(opened.length,0); assert.ok(warnings.at(-1).includes('正文不可读'));

  let release;
  approvalRequest = () => new Promise(resolve => { release = resolve; });
  const pending = openNodeApprovalFromList(button());
  assert.ok(nodeRows([delivery]).includes('正在核对正文…'));
  await openNodeApprovalFromList(button()); // SSE-created replacement button cannot duplicate the read.
  state.project = 'other-project'; release(body); await pending;
  assert.equal(opened.length,0); assert.equal(pendingNodeApprovalReads.size,0);
  state.project = 'project-current';
  for (const change of [
    () => { delivery.delivery_review.definition_digest = 'new-definition'; },
    () => { delivery.delivery_review.feedback.can_approve = false; },
    () => { window.location.href = 'http://example.invalid/?pending-items=1'; },
  ]) {
    const pending = openNodeApprovalFromList(button()); change(); release(body); await pending;
    assert.equal(opened.length,0);
    delivery.delivery_review.definition_digest = 'delivery-current';
    delivery.delivery_review.feedback = emptyFeedback();
    window.location.href = 'http://example.invalid/?workstream=VDOC';
  }
  console.log('Seven-workstream list/detail approval policy and document preflight PASS');
})()
`,context).catch(error => { console.error(error); process.exitCode = 1; });
