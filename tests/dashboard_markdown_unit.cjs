const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const context = vm.createContext({URL, console, atob});
for (const file of ['vendor/markdown-it/markdown-it.min.js', 'dashboard_markdown.js']) {
  vm.runInContext(fs.readFileSync(path.join(root, 'verif_harness', file), 'utf8'), context);
}
const document = {id:'plan', path:'docs/verification_plan.md', exists:true};
const options = {
  document,
  documents:[document, {id:'assertions', path:'docs/assertion_plan.md', exists:true}],
  urlForDocument: id => new URL('http://localhost/?project=alpha&token=test&document=' + id),
};
const source = fs.readFileSync(path.join(__dirname, 'dashboard_markdown_fixture.md'), 'utf8');
const html = context.VerifMarkdown.render(source, options);
assert.match(html, /<h1 id="md-验证计划示例">/);
assert.match(html, /<h2 id="md-dut-范围">/);
assert.match(html, /<h2 id="md-dut-范围-1">/);
assert.match(html, /<table>/);
assert.match(html, /<td>数据保持 a\|b<\/td>/);
assert.match(html, /<strong>ready\/valid<\/strong>/);
assert.match(html, /<s>旧策略<\/s>/);
assert.match(html, /<code class="language-systemverilog">/);
assert.match(html, /<blockquote>/);
assert.match(html, /<ul>/);
assert.match(html, /<ol>/);
assert.match(html, /project=alpha&amp;token=test&amp;document=assertions#md-/);
assert.match(html, /rel="noopener noreferrer"/);
assert.match(html, /查看 Markdown 源码/);
assert.doesNotMatch(html, /<(script|img|form|input|iframe|svg)\b/i);
assert.doesNotMatch(html, /href="(?:javascript|file|data):/i);
assert.match(html, /title="当前项目未登记这份文档，或文件不存在"/);
assert.match(html, /title="链接超出当前项目"/);
assert.equal(context.markdownInjection, undefined);
for (const href of ['data:text/html,attack', '//example.com/x', '%2f%2fexample.com', 'vbscript:attack', '%6aavascript:alert', 'missing.md', '#missing', 'assertion_plan.md?project=other', '..%2f..%2foutside.md']) {
  const output = context.VerifMarkdown.render(`[test](${href})`, options);
  assert.doesNotMatch(output, /<a /, href);
}
// Changing the selected project must change the generated navigation context.
const other = {...options, urlForDocument: id => new URL('http://localhost/?project=beta&document=' + id)};
assert.match(context.VerifMarkdown.render('[link](assertion_plan.md)', other), /project=beta/);
assert.doesNotMatch(context.VerifMarkdown.render('[link](assertion_plan.md)', {...options, documents:[]}), /<a /);
const collisions = context.VerifMarkdown.render('# A\n\n# A\n\n# A-1', options);
assert.equal(new Set([...collisions.matchAll(/ id="([^"]+)"/g)].map(m => m[1])).size, 3);
delete context.markdownit;
assert.match(context.VerifMarkdown.render(source, options), /<details open /);
assert.doesNotMatch(context.VerifMarkdown.render(source, options), /<script>/);
const dashboard = fs.readFileSync(path.join(root, 'verif_harness/dashboard.html'), 'utf8');
new vm.Script(dashboard.match(/<script>([\s\S]*?)<\/script>/)[1]);
assert.doesNotMatch(dashboard, /<pre class="document-preview">\$\{escapeHtml\(body.content\)\}<\/pre><\/section>/);
console.log('Markdown rendering, source fallback, links and injection contracts PASS');
