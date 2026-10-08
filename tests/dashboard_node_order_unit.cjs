// Stable verification-order sorting and local list filters over one Dashboard snapshot.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const elements = new Map();
const context = vm.createContext({
  assert, console, URL, URLSearchParams,
  window:{location:{search:'',href:'http://example.invalid/?workstream=VCOV'}},
  localStorage:{getItem:() => '',setItem:() => {}},
  document:{
    querySelector:selector => {
      if (!elements.has(selector)) elements.set(selector, {
        content:'test-token',innerHTML:'',dataset:{},
        classList:{add:() => {},remove:() => {},contains:() => false},
      });
      return elements.get(selector);
    },
    querySelectorAll:() => [],
  },
});

vm.runInContext(source.slice(0, source.indexOf("    $('#drawer-backdrop').onclick")), context);
vm.runInContext(String.raw`
(() => {
  const node = (id, role, implementationKey, required=true, parentId=null) => ({
    id, role, implementation_key:implementationKey, required, parent_id:parentId,
    title:id, status:'PENDING', activities:[], outgoing:[],
  });
  const convergenceDelivery = node('conv-delivery','coverage-convergence-deliverable','conv',true,'conv-plan');
  const convergencePlan = node('conv-plan','coverage-convergence-plan','conv');
  const optionalImplementation = node('optional-plan','coverage-implementation-plan','optional',false);
  const implementationDelivery = node('impl-delivery','coverage-implementation-deliverable','impl',true,'impl-plan');
  const implementationPlan = node('impl-plan','coverage-implementation-plan','impl');
  convergencePlan.outgoing = [{source:convergencePlan.id,target:implementationDelivery.id,relation:'DEPENDS_ON'}];
  const shuffled = [convergenceDelivery,convergencePlan,optionalImplementation,implementationDelivery,implementationPlan];
  assert.deepEqual(
    orderWorkNodes(shuffled).map(item => item.id),
    ['impl-plan','impl-delivery','optional-plan','conv-plan','conv-delivery'],
  );

  const regression = [
    node('results-delivery','regression-results-deliverable','results',true,'results-plan'),
    node('results-plan','regression-results-plan','results'),
    node('infra-delivery','regression-infrastructure-deliverable','infra',true,'infra-plan'),
    node('infra-plan','regression-infrastructure-plan','infra'),
  ];
  assert.deepEqual(
    orderWorkNodes(regression).map(item => item.id),
    ['infra-plan','infra-delivery','results-plan','results-delivery'],
  );

  const documentPlanB = {...node('doc-b-plan','document-writing-plan',null),document_key:'doc-b'};
  const documentPlanA = {...node('doc-a-plan','document-writing-plan',null),document_key:'doc-a'};
  const documentDeliveryA = {...node('doc-a-delivery','document-deliverable',null,true,'doc-a-plan'),document_key:'doc-a'};
  const documentDeliveryB = {...node('doc-b-delivery','document-deliverable',null,true,'doc-b-plan'),document_key:'doc-b'};
  assert.deepEqual(
    orderWorkNodes([documentPlanB,documentPlanA,documentDeliveryA,documentDeliveryB]).map(item => item.id),
    ['doc-b-plan','doc-b-delivery','doc-a-plan','doc-a-delivery'],
  );

  // A real dependency wins over proposal order for generic public nodes.
  const dependent = node('dependent','project-goal','dependent');
  const prerequisite = node('prerequisite','project-goal','prerequisite');
  dependent.outgoing = [{source:dependent.id,target:prerequisite.id,relation:'DEPENDS_ON'}];
  assert.deepEqual(orderWorkNodes([dependent,prerequisite]).map(item => item.id), ['prerequisite','dependent']);

  // Dynamic status and timestamps never move a row in the default view.
  const before = orderWorkNodes(shuffled).map(item => item.id);
  for (const [index,item] of shuffled.entries()) {
    item.status = index % 2 ? 'VALID' : 'REVIEW_REQUIRED';
    item.updated_at = '2026-10-08T10:0' + index + ':00+08:00';
  }
  assert.deepEqual(orderWorkNodes(shuffled).map(item => item.id), before);

  state.project = 'project-current';
  const workstream = {
    workstream:'VCOV',nodes:shuffled,
    waiting_for_human:[{source:'closure',target:convergencePlan.id,status:'OPEN'}],
  };
  nodeListFilters.set(nodeListFilterKey(workstream),'human');
  assert.deepEqual(workNodeListView(workstream,shuffled).nodes.map(item => item.id), [convergencePlan.id]);

  implementationDelivery.activities = [{status:'RUNNING',execution_confirmed:true}];
  optionalImplementation.activities = [{status:'PENDING',execution_confirmed:false}];
  convergenceDelivery.activities = [{status:'RUNNING',execution_confirmed:false}];
  nodeListFilters.set(nodeListFilterKey(workstream),'agent');
  assert.deepEqual(
    workNodeListView(workstream,shuffled).nodes.map(item => item.id),
    [implementationDelivery.id,optionalImplementation.id],
  );
  nodeListFilters.set(nodeListFilterKey(workstream),'all');
  assert.deepEqual(workNodeListView(workstream,shuffled).nodes.map(item => item.id), before);

  // Every visible filter button is bound and rerenders the same current workstream.
  const buttons = ['all','human','agent'].map(mode => ({dataset:{nodeListFilter:mode},onclick:null}));
  document.querySelectorAll = selector => selector === '[data-node-list-filter]' ? buttons : [];
  state.snapshot = {workstreams:[workstream]};
  let renderedWorkstream = null;
  const originalRenderWorkstream = renderWorkstream;
  renderWorkstream = current => { renderedWorkstream = current.workstream; };
  bindNodeListTools(workstream);
  buttons[1].onclick({stopPropagation:() => {}});
  assert.equal(nodeListMode(workstream),'human');
  assert.equal(renderedWorkstream,'VCOV');
  renderWorkstream = originalRenderWorkstream;
  console.log('Dashboard work-node verification order and snapshot filters PASS');
})()
`, context);
