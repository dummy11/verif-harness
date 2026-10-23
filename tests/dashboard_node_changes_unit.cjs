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
  const root = {id:'drawer',isConnected:true,querySelectorAll:selector =>
    selector === '[data-node-changes]' ? [shell] : []};
  response = {dashboard_project_id:'project-current',result:{node_id:node.id,
    definition_digest:'current-digest',previous_node_id:'old',previous_revision:1,
    changes:[{field:'work_content',before:['旧内容'],after:['新增 <script>']}]}};
  assert.equal(await loadNodeChanges(node, root), true, shell.innerHTML);
  assert.match(shell.innerHTML, /本版内容变化 · 1 项内容/);
  assert.match(shell.innerHTML, /&lt;script&gt;/);
  assert.doesNotMatch(shell.innerHTML, /<script>/);
  assert.match(shell.innerHTML, /查看完整差异对照/);
  const technical = nodeChangesHtml({previous_node_id:'old',previous_revision:1,
    changes:[{field:'regression_config',before:{profile:'old'},after:{profile:'current'}}]});
  assert.match(technical, /配置内容/);
  assert.doesNotMatch(technical, /node-change-current/);

  const diff = nodeTextDiff('复位后检查3个周期，并检查接口', '复位后检查5个周期，并检查接口');
  assert.equal(nodeDiffHtml(diff, 'after'), '复位后检查<mark class="node-change-added">5</mark>个周期，并检查接口');
  assert.equal(nodeDiffHtml(diff, 'before'), '复位后检查<del class="node-change-removed">3</del>个周期，并检查接口');
  assert.equal(nodeDiffHtml(nodeTextDiff('保持不变', '保持不变'), 'after'), '保持不变');
  assert.equal(nodeDiffHtml(nodeTextDiff('复位🔴正常', '复位🟢正常'), 'after'), '复位<mark class="node-change-added">🟢</mark>正常');
  const list = nodeChangeItems(['接口保持不变', '检查3次'], ['接口保持不变', '检查5次', '边界检查']);
  assert.equal(list.length, 2);
  assert.deepEqual(list.map(item => item.kind), ['modified', 'added']);
  assert.equal(nodeChangeItems(['删除此项','保持不变'], ['保持不变'])[0].kind, 'removed');
  assert.deepEqual(nodeChangePairs(['A','B','A'], ['A','A','B']), [
    {beforeIndex:0,afterIndex:0},{beforeIndex:2,afterIndex:1},{beforeIndex:1,afterIndex:2}]);
  const reordered = nodeChangeItems(['A','B'], ['B','A']);
  assert.equal(reordered[0].kind, 'reordered');
  assert.doesNotMatch(nodeChangeItemHtml(reordered[0], false, true), /<mark|<del/);
  assert.match(nodeChangeItemHtml(reordered[0], false, true), /上一版/);
  const config = nodeChangesHtml({previous_node_id:'old',previous_revision:1,changes:[{
    field:'regression_config',before:{repeat:1,seed_mode:'fixed',seed:42},after:{repeat:3,seed_mode:'fixed',seed:42}}]});
  assert.match(config, /每个 case 的重复次数/);
  assert.match(config, /node-change-removed">1/);
  assert.match(config, /node-change-added">3/);
  assert.doesNotMatch(config, /fixed|42/);
  const large = nodeTextDiff('甲'.repeat(1100), '乙'.repeat(1100));
  assert.equal(large.precise, false);
  assert.doesNotMatch(nodeDiffHtml(large, 'after'), /<mark/);
  const excerpt = nodeDiffHtml(nodeTextDiff('相'.repeat(200)+'甲'+'同'.repeat(200), '相'.repeat(200)+'乙'+'同'.repeat(200)), 'after', true);
  assert.match(excerpt, /node-change-added">乙/);
  assert.ok(excerpt.startsWith('…') && excerpt.endsWith('…'));
  for (const [before, after] of [['abac','baca'], ['', '<img>'], ['删除',''], ['\nA\nB', '\nA\nC']]) {
    const result = nodeTextDiff(before, after);
    assert.equal(result.parts.filter(p => p.kind !== 'added').map(p => p.text).join(''), before);
    assert.equal(result.parts.filter(p => p.kind !== 'removed').map(p => p.text).join(''), after);
  }

  response.result = {...response.result,previous_node_id:null,changes:[]};
  assert.equal(await loadNodeChanges(node, root), true);
  assert.match(shell.innerHTML, /尚无已批准版本/);

  response.result = {...response.result,previous_node_id:'old'};
  assert.equal(await loadNodeChanges(node, root), true);
  assert.match(shell.innerHTML, /审批内容没有变化/);
  assert.doesNotMatch(shell.innerHTML, /<mark|<del/);

  response.result = {...response.result,definition_digest:'other-digest'};
  assert.equal(await loadNodeChanges(node, root), false);
  assert.match(shell.innerHTML, /无法核对最近一次批准内容/);
  process.stdout.write('node changes PASS\n');
})().catch(error => { console.error(error); process.exitCode = 1; });
`, context);
