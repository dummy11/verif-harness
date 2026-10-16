// The approval comparison is fetched for the selected node and visibly marks changed content.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(source);
const elements = new Map();
const context = vm.createContext({
  assert, console, process, URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
  window:{location:{search:'',href:'http://dashboard.test/'}},
  localStorage:{getItem:() => '',setItem:() => {}},
  document:{
    querySelector:selector => {
      if (!elements.has(selector)) elements.set(selector, {content:'test-token',innerHTML:'',dataset:{}});
      return elements.get(selector);
    },
    querySelectorAll:() => [],
  },
  fetch:async url => {
    assert.match(url, /project=project-current/);
    assert.match(url, /node=workstream%3AVENV%3Ar2%3Adesired%3Ainterface-main/);
    assert.match(url, /digest=current-digest/);
    return {ok:true,json:async () => context.response};
  },
});
vm.runInContext(source.slice(0, source.indexOf("    $('#drawer-backdrop').onclick")), context);
vm.runInContext(String.raw`
(async () => {
  const node = {id:'workstream:VENV:r2:desired:interface-main',workstream:'VENV',role:'code-plan',
    plan_review:{definition_digest:'current-digest'}};
  state.project = 'project-current';
  state.snapshot = {workstreams:[{workstream:'VENV',nodes:[node]}]};
  const shell = {innerHTML:''};
  const marked = {dataset:{nodeChangeField:'work_content'},classList:{add(value){this.added=value;}}};
  const root = {id:'drawer',isConnected:true,querySelectorAll:selector =>
    selector === '[data-node-changes]' ? [shell] : selector === '[data-node-change-field]' ? [marked] : []};
  response = {dashboard_project_id:'project-current',result:{node_id:node.id,
    definition_digest:'current-digest',previous_node_id:'old',previous_revision:1,
    changes:[{field:'work_content',before:['旧内容'],after:['新增 <script>']}]}};
  assert.equal(await loadNodeChanges(node, root), true, shell.innerHTML);
  assert.equal(marked.classList.added, 'node-changed-field');
  assert.match(shell.innerHTML, /本版内容变化 · 1 处/);
  assert.match(shell.innerHTML, /新增 &lt;script&gt;/);
  assert.doesNotMatch(shell.innerHTML, /<script>/);
  assert.match(shell.innerHTML, /查看上一版内容/);
  const technical = nodeChangesHtml({previous_node_id:'old',previous_revision:1,
    changes:[{field:'regression_config',before:{profile:'old'},after:{profile:'current'}}]});
  assert.match(technical, /查看本版详细内容/);
  assert.doesNotMatch(technical, /node-change-current/);

  response.result = {...response.result,previous_node_id:null,changes:[]};
  assert.equal(await loadNodeChanges(node, root), true);
  assert.match(shell.innerHTML, /首次提交此工作节点/);

  response.result = {...response.result,definition_digest:'other-digest'};
  assert.equal(await loadNodeChanges(node, root), false);
  assert.match(shell.innerHTML, /无法核对上一版/);
  process.stdout.write('node changes PASS\n');
})().catch(error => { console.error(error); process.exitCode = 1; });
`, context);
