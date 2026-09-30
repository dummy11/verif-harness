// Real code-workflow routes, code preview and owner approval against an isolated project.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
const workstream = config.workstream || 'VENV';
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.VERIF_DASHBOARD_BROWSER_CHANNEL ? {channel:process.env.VERIF_DASHBOARD_BROWSER_CHANNEL} : {})});
  const context = await browser.newContext({viewport:{width:1440,height:1000}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  // No persistent SSE readers are needed for this click + refresh test.
  await page.route('**/api/events*', route => route.abort());
  const url = new URL(config.url);
  for (const [key,value] of Object.entries({project:config.project,token:config.token,workstream})) url.searchParams.set(key,value);
  try {
    await page.goto(url.toString());
    const table = page.locator('.work-node-table');
    await table.waitFor();
    assert.deepEqual(await table.locator('th').allTextContents(), ['节点名称','节点类型','进度','状态 / 操作']);
    assert.equal(await page.locator('#review-ws').count(), 0);
    if (config.phase === 'changes') {
      for (const name of ['添加节点', '删除节点', '重新启动工作流']) {
        await page.getByRole('button', {name, exact:true}).click();
        const change = page.locator('#code-workflow-change');
        await change.locator('[name="reviewer"]').fill('browser-owner');
        await change.locator('[name="reason"]').fill('重新划分当前 DUT 的验证工作范围');
        const saved = page.waitForResponse(r => r.url().includes('/api/code/workflow-change') && r.request().method() === 'POST');
        await change.getByRole('button', {name:'确认' + name,exact:true}).click();
        assert.equal((await saved).ok(), true);
        await page.locator('#modal-backdrop').waitFor({state:'hidden'});
        if (name !== '重新启动工作流') assert.equal(await table.locator('tbody tr').count(), 2);
      }
      await page.reload();
      await page.locator('.project-status-card').waitFor();
      assert.equal(await page.locator('#main [data-open-node]').count(), 0);
      assert.deepEqual(errors, []);
      return;
    }
    await table.locator(`[data-open-node="${config.node}"]`).click();
    await page.locator('#drawer #node-plan-complete').waitFor();
    if (config.expectedRole) {
      assert.ok((await page.locator('#drawer .drawer-head').innerText()).includes(config.expectedRole));
      assert.equal(await page.locator('#drawer').getByText('工作包', {exact:true}).count(), 0);
    }
    assert.ok((await page.locator('#drawer .drawer-head').innerText()).includes(config.phase === 'plan' ? '等待负责人审批方案' : '等待负责人验收交付'));
    assert.equal(await page.locator('#drawer .writing-plan-inputs').getAttribute('open'), null);
    assert.doesNotMatch(await page.locator('#drawer .role-node-panel').innerText(), /待确认问题|预计正文交付|方案质量检查/);
    if (config.phase === 'plan') {
      assert.deepEqual(await page.locator('#drawer .role-node-panel h4').allTextContents(), ['目标','工作范围','具体工作','实现方式','如何验证','输出','交付条件']);
    } else {
      assert.ok((await page.locator('#drawer .role-node-panel').innerText()).includes('检查结论'));
      if (config.expectedFileHeading) {
        assert.equal(await page.locator('#drawer .role-node-panel').getByRole('heading', {name:config.expectedFileHeading, exact:true}).count(), 1);
        if (config.expectedFileHeading === '交付文件') assert.equal(await page.locator('#drawer .role-node-panel').getByRole('heading', {name:'交付代码', exact:true}).count(), 0);
      }
      await page.locator('#drawer [data-code-file]').first().click();
      await page.locator('#modal pre').waitFor();
      assert.ok((await page.locator('#modal pre').innerText()).includes(config.previewText || 'fixture_interface'));
      await page.locator('#modal [data-close-modal]').click();
    }
    // Full-node route and reload preserve the same project and code object.
    await page.locator('#expand-node').click();
    await page.reload();
    await page.locator('#main #node-plan-complete').waitFor();
    if (process.env.VERIF_DASHBOARD_SCREENSHOT_DIR) {
      await page.screenshot({path:process.env.VERIF_DASHBOARD_SCREENSHOT_DIR + '/' + workstream.toLowerCase() + '-' + config.phase + '.png', fullPage:true});
    }
    await page.locator('#main #node-plan-complete').click();
    const form = page.locator('#node-plan-complete-form');
    assert.equal(await form.locator('[name="reason"]').getAttribute('required'), null);
    await form.locator('[name="reviewer"]').fill('browser-owner');
    const response = page.waitForResponse(r => r.url().includes('/api/reviews/node-plan-complete') && r.request().method() === 'POST');
    await form.getByRole('button', {name:'确认审批完成',exact:true}).click();
    assert.equal((await response).ok(), true);
    await page.locator('#modal-backdrop').waitFor({state:'hidden'});
    await page.locator('.work-node-table').waitFor();
    assert.equal(page.isClosed(), false);
    assert.equal(new URL(page.url()).searchParams.get('workstream'), workstream);
    assert.equal(new URL(page.url()).searchParams.get('project'), config.project);
    await page.reload();
    const approved = page.locator(`[data-approve-plan-node="${config.node}"]`);
    await approved.waitFor();
    assert.equal(await approved.innerText(), '已批准全部内容');
    assert.equal(await approved.isDisabled(), true);
    assert.ok((await approved.locator('xpath=ancestor::tr').innerText()).includes(config.phase === 'plan' ? '方案已批准' : '已验收通过'));
    if (config.phase === 'plan') assert.ok((await table.innerText()).includes('等待 Agent 验证通过'));
    assert.deepEqual(errors, []);
    console.log(workstream + ' ' + config.phase + ' browser routes, preview, approval and reload PASS');
  } finally { await context.close(); await browser.close(); }
})().catch(e => {console.error(e);process.exit(1);});
