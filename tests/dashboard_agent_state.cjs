// A persisted RUNNING record is not proof of a currently executing CLI.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.VERIF_DASHBOARD_BROWSER_CHANNEL ? {channel:process.env.VERIF_DASHBOARD_BROWSER_CHANNEL} : {})});
  const context = await browser.newContext();
  const headers = {'X-Verif-Token':config.token};
  const snapshotUrl = new URL(`/api/snapshot?project=${config.otherProject}`, config.url).toString();
  const url = new URL(config.url);
  url.searchParams.set('project', config.otherProject);
  url.searchParams.set('token', config.token);
  url.searchParams.set('workstream', 'VDOC');
  try {
    let response = await context.request.get(snapshotUrl, {headers});
    assert.ok(response.ok());
    const snapshot = await response.json();
    const node = snapshot.workstreams.find(w => w.workstream === 'VDOC').nodes.find(n => n.delivery_review);
    response = await context.request.post(new URL('/api/reviews/document-delivery', config.url).toString(), {
      headers, data:{dashboard_project:config.otherProject, node:node.id,
        definition_digest:node.delivery_review.definition_digest, document_digest:node.delivery_review.document_digest,
        verdict:'approve', reviewer:'fixture-owner', notes:'', include_snapshot:false},
    });
    assert.ok(response.ok(), await response.text());

    for (let reopen = 0; reopen < 2; reopen++) {
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(String(error)));
      await page.goto(url.toString());
      const row = page.locator('.work-node-table tr').filter({has:page.locator(`[data-open-node="${node.id}"]`)});
      await row.waitFor();
      assert.match(await row.textContent(), /等待 Agent 检查审批/);
      assert.doesNotMatch(await row.textContent(), /Agent 正在/);
      assert.equal(await row.locator('[data-motion="active"]').count(), 0);
      await page.locator('[data-nav="agent"]').click();
      await page.getByRole('heading', {name:'Agent 工作状态', exact:true}).waitFor();
      assert.doesNotMatch(await page.locator('#main').textContent(), /Agent 正在处理|Agent 正在检查/);
      assert.equal(new URL(page.url()).searchParams.get('project'), config.otherProject);
      assert.deepEqual(errors, []);
      await page.close();
      const current = await (await context.request.get(snapshotUrl, {headers})).json();
      const activity = current.activities.find(a => a.node_id === node.id);
      assert.equal(activity.recorded_status, 'RUNNING');
      assert.equal(activity.status, 'UNCONFIRMED');
      assert.equal(activity.execution_confirmed, false);
      assert.equal(current.project_agent.service.online, false);
      assert.notEqual(current.project_agent.status, 'RUNNING');
    }
    console.log('Dashboard reopen: acceptance, idle Agent, preserved audit state and authorized navigation PASS');
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => {console.error(error); process.exit(1);});
