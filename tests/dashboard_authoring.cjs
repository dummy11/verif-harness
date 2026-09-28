// Exercise the real renderers with all eight generated plans, without changing them.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const proposal = JSON.parse(fs.readFileSync(0, 'utf8'));
const html = fs.readFileSync(path.join(__dirname, '../verif_harness/dashboard.html'), 'utf8');
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(source);
const context = vm.createContext({
  assert, proposal, URLSearchParams,
  window:{location:{search:''}}, localStorage:{getItem:() => '', setItem:() => {}},
  document:{querySelector:() => ({content:'test-token'}), querySelectorAll:() => []},
});
vm.runInContext(source.slice(0, source.indexOf("    $('#drawer-backdrop').onclick")), context);
vm.runInContext(`
  state.snapshot = {project:{root:'/project',rtl_roots:['rtl']},workstreams:[]};
  assert.equal(proposal.nodes.length, 8);
  for (const node of proposal.nodes) {
    const before = JSON.stringify(node);
    const rendered = nodeRolePanelHtml(node);
    assert.match(rendered, /计划写入的内容/);
    assert.match(rendered, /撰写和修改方法/);
    assert.match(rendered, /RTL 目录：rtl/);
    assert.match(rendered, /<details class="detail-group writing-plan-inputs"><summary>输入依据/);
    assert.doesNotMatch(rendered, /writing-plan-inputs" open/);
    assert.match(rendered, /查看详细撰写要求/);
    assert.match(rendered, /查看输入文件版本记录/);
    assert.doesNotMatch(rendered, /预计正文交付|方案质量检查|工业级文档撰写合同/);
    assert.doesNotMatch(rendered, /authoring node|source gap|source inventory|required tables|Property intent|DUT-specific|fabricate/);
    const primary = rendered.split('<details class="detail-group">')[0];
    assert.doesNotMatch(primary, /rtl\\/dut\\.sv|VerificationDocumentAuthoringContract/);
    // File provenance remains available in the collapsed audit record.
    assert.match(rendered, /rtl\\/dut\\.sv/);
    assert.equal(JSON.stringify(node), before);
  }
  const legacy = {
    role:'document-writing-plan', source_refs:['rtl/dut.sv','rtl/sub/child.v','spec.md#reset','tb/tb_top.sv','gap:source:design-spec'],
    authoring_contract:{source_snapshot:[{kind:'verification-testbench',path:'tb/tb_top.sv'}]},
  };
  const beforeLegacy = JSON.stringify(legacy);
  assert.equal(JSON.stringify(writingPlanSources(legacy)), JSON.stringify(['RTL 目录：rtl','spec.md#reset','验证环境目录：tb']));
  assert.equal(JSON.stringify(legacy), beforeLegacy);
  state.snapshot.project.rtl_roots = ['/external/top.sv','rtl'];
  assert.equal(JSON.stringify(writingPlanSources({source_refs:['/external/top.sv','/project/rtl/dut.sv']})), JSON.stringify(['RTL 目录：/external','RTL 目录：rtl']));
  state.snapshot.project.verification_inputs = {testbench_root:'tb',reference_model:'model',scripts:['scripts/run.py']};
  const mixed = {source_refs:['tb/a.sv','tb/sub/b.sv','tb/README.md','model/src/ref.cpp','model/spec.pdf','scripts/run.py','specs/api.md'],
    authoring_contract:{source_snapshot:[{path:'tb/a.sv',kind:'verification-testbench'},{path:'tb/sub/b.sv',kind:'verification-testbench'},
      {path:'model/src/ref.cpp',kind:'reference-model-implementation'},{path:'scripts/run.py',kind:'verification-script'}]}};
  assert.equal(JSON.stringify(writingPlanSources(mixed)), JSON.stringify(['验证环境目录：tb','tb/README.md','参考模型目录：model','model/spec.pdf','验证脚本目录：scripts','specs/api.md']));
`, context);
console.log('All eight authoring plans: readable text, directory-only RTL inputs and immutable provenance PASS');
