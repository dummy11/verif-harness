// Exercise the shipped node renderers and approval preflight in a real DOM.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {JSDOM} = require('jsdom');
const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'verif_harness/dashboard.html'), 'utf8');
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const dom = new JSDOM(html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, ''), {
  url:'http://dashboard.invalid/?project=fixture', runScripts:'outside-only',
});
const {window} = dom;
window.assert = assert;
window.scrollTo = () => {};
window.HTMLElement.prototype.scrollIntoView = () => {};
window.eval(fs.readFileSync(path.join(root, 'verif_harness/vendor/markdown-it/markdown-it.min.js'), 'utf8'));
window.eval(fs.readFileSync(path.join(root, 'verif_harness/dashboard_markdown.js'), 'utf8'));
vm.runInContext(source.slice(0, source.indexOf("    $('#drawer-backdrop').onclick")), dom.getInternalVMContext());

(async () => {
  try {
    await vm.runInContext(`(async () => {
      const longText = '本节点的详细内容，展开后阅读。'.repeat(30);
      const review = {completed:false,can_approve:true,status:'PENDING',definition_digest:'current'};
      const nodes = [];
      for (const stream of ['VENV','VSTIM','VCHK','VCASE']) {
        for (const role of ['code-plan','code-deliverable']) nodes.push({workstream:stream,role});
      }
      for (const role of ['coverage-implementation-plan','coverage-implementation-deliverable',
        'coverage-convergence-plan','coverage-convergence-deliverable']) nodes.push({workstream:'VCOV',role});
      for (const role of ['regression-infrastructure-plan','regression-infrastructure-deliverable',
        'regression-results-plan','regression-results-deliverable']) nodes.push({workstream:'VREG',role});
      nodes.push({workstream:'VDOC',role:'document-writing-plan'});
      for (const [index,node] of nodes.entries()) Object.assign(node, {
        id:'node-' + index,title:node.role,required:true,status:'PENDING',statement:longText,
        purpose:longText,scope:[longText],work_content:[longText],implementation_approach:[longText],
        validation_methods:[longText],deliverables:[longText],acceptance_criteria:[longText],source_refs:[],
        plan_review:{...review,validation:{current:true,ready:true,summary:longText,
          code_files:[{path:'results/current.json',sha256:'file-current'}],files:[],checks:[
            {criterion:longText,method:longText,actual:longText,expected:longText,validation:{ready:true}},
          ]}},
      });
      nodes.find(node => node.role === 'coverage-convergence-deliverable').title =
        '全量覆盖项合并采集、缺口分析与排除管理';
      for (const node of nodes.filter(n => n.workstream === 'VCOV')) {
        if (node.role.includes('implementation')) {
          node.coverage_scope = {schema:'CoverageScope/1',code:{metrics:['line'],hierarchy_selectors:['dut']}};
          node.coverage_implementation_config = {schema:'CoverageImplementationConfig/1',
            configuration_refs:[{role:'collection',path:'coverage.json'}],toolchain:[]};
        } else node.coverage_collection_config = {schema:'CoverageCollectionConfig/1',
          regression_sources:[{}],merge_profile:{path:'merge.json'},dut_build_fingerprint:{dut_design_id:'demo'}};
      }
      for (const node of nodes.filter(n => n.role.startsWith('regression-results-'))) {
        node.regression_config = {regression_group:'demo',cases:[{case_id:'case-a',case_digest:'case-current'}],
          submit_profile:{profile_id:'local',submit_file:'submit.json',submit_file_digest:'submit-current',
            profile_digest:'profile-current',adapter:{name:'fixture',version:'1'}},seed_mode:'fixed',seed:'17',repeat:1};
        node.plan_review.regression_execution = {can_rerun:true,current:{status:'VALIDATED',round_number:1,
          execution_binding:{plan_node_id:'plan',plan_revision:1,plan_digest:'plan-current'}}};
      }
      const plan = nodes.at(-1);
      const delivery = {id:'document-delivery',title:'验证计划正文',workstream:'VDOC',role:'document-deliverable',
        required:true,status:'PENDING',source_refs:[],document:{id:'doc',title:'验证计划',path:'docs/plan.md'},
        delivery_review:{status:'PENDING',document_available:true,document_id:'doc',document_digest:'body-current',
          definition_digest:'definition-current',reviews:[]}};
      const generic = {id:'legacy-checker',title:'接口检查',workstream:'VCHK',role:'checker',status:'PENDING',
        statement:'核对接口输出',purpose:'核对接口输出',scope:[longText],work_content:[longText],
        implementation_approach:[longText],deliverables:[longText],source_refs:[],quality_checks:[longText]};
      nodes.push(delivery, generic);
      state.snapshot = {project:{},activities:[],agent_questions:[],documents:[],
        model:{nodes:[],edges:[],evidence:[],findings:[]},workstreams:
        ['VDOC','VENV','VSTIM','VCHK','VCASE','VCOV','VREG'].map(workstream => ({
          workstream,lifecycle:'ACTIVE',revision:1,closure:{ready:false,actions:[]},
          nodes:nodes.filter(n => n.workstream === workstream),
        }))};
      state.project = 'fixture';
      const body = {document:{id:'doc',digest:'body-current',content_changed:false},content:'# 正文内容\\n\\n' + longText};
      let reads = 0, failure = false, stale = false;
      approvalRequest = async url => {
        assert.ok(url.startsWith('/api/document?'), 'only the controlled body read is expected');
        reads++;
        if (failure) throw new Error('测试正文不可读');
        return stale ? {...body,document:{...body.document,digest:'changed'}} : body;
      };
      loadNodeChanges = async () => true;
      const closedAncestor = el => el.closest('details:not([open])');
      for (const full of [false,true]) {
        for (const node of nodes) {
          if (node === delivery) Object.assign(plan.plan_review, {status:'APPROVED',completed:true});
          else Object.assign(plan.plan_review, {status:'PENDING',completed:false});
          await renderDrawer(node.id, full);
          const panel = document.querySelector(full ? '#main' : '#drawer');
          if (node.role === 'coverage-convergence-deliverable') {
            assert.doesNotMatch(panel.querySelector('.drawer-head h2').textContent, /全量|缺口/);
            assert.equal(node.title, '全量覆盖项合并采集、缺口分析与排除管理');
          }
          const details = [...panel.querySelectorAll('.node-content-details,.coverage-delivery-part,.delivery-summary')];
          assert.ok(details.length > 0, node.role);
          assert.ok(details.every(el => !el.open), node.role + ' must start collapsed');
          const approval = panel.querySelector('#node-plan-complete,#node-delivery-complete');
          if (approval) assert.equal(closedAncestor(approval), null, 'approval stays outside collapsed content');
          if (node.role === 'regression-results-deliverable') {
            assert.equal(closedAncestor(panel.querySelector('.regression-execution')), null);
            assert.equal(closedAncestor(panel.querySelector('#regression-rerun')), null);
            assert.equal(panel.querySelector('#regression-rerun').disabled, false);
          }
          const first = details[0];
          first.querySelector(':scope > summary').click();
          assert.equal(first.open, true, 'summary opens the existing content');
          first.querySelector(':scope > summary').click();
          assert.equal(first.open, false);
          assert.ok(panel.textContent.includes(longText), 'folding retains the complete source');
          if (node === delivery) {
            assert.equal(approval.disabled, false);
            assert.ok(closedAncestor(panel.querySelector('[data-delivery-body]')));
            assert.ok(panel.querySelector('[data-delivery-body]').textContent.includes('正文内容'));
          }
          const file = panel.querySelector('[data-code-file]');
          if (file) {
            let target;
            showCodeFile = (...args) => {target = args;};
            let parent;
            while ((parent = closedAncestor(file))) parent.querySelector(':scope > summary').click();
            file.click();
            assert.equal(target[0].id, node.id);
            assert.equal(target[1], 'results/current.json');
            assert.equal(target[2], 'file-current');
          }
        }
      }
      Object.assign(plan.plan_review, {status:'APPROVED',completed:true});
      for (const mode of ['failed','stale']) {
        failure = mode === 'failed'; stale = mode === 'stale';
        await renderDrawer(delivery.id, true);
        const panel = document.querySelector('#main');
        assert.equal(panel.querySelector('#node-delivery-complete').disabled, true);
        assert.equal(panel.querySelector('[data-delivery-opinion-form] button').disabled, true);
        const status = panel.querySelector('[data-delivery-read-status]');
        assert.equal(closedAncestor(status), null);
        assert.match(status.textContent, mode === 'failed' ? /无法读取文档正文/ : /正文版本已变化/);
        assert.ok(closedAncestor(panel.querySelector('[data-delivery-body]')));
      }
      assert.equal(reads, 4, 'body preflight runs even while the body is collapsed');
      return nodes.length;
    })()`, dom.getInternalVMContext());
    console.log('Seven workflows: collapsed drawer/full-page content, file actions and document preflight PASS');
  } finally {
    window.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
