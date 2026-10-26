// Real node routes and approval confirmation against an isolated ProjectStore.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.VERIF_DASHBOARD_BROWSER_CHANNEL ? {channel:process.env.VERIF_DASHBOARD_BROWSER_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1050}});
    const errors = [], writes = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('request', request => { if (request.method() === 'POST') writes.push(request.url()); });
    await page.route('**/api/events*', route => route.abort());
    const url = new URL(config.url);
    for (const [key,value] of Object.entries({project:config.project,token:config.token,workstream:config.workstream})) url.searchParams.set(key,value);
    await page.goto(url.toString());
    await page.locator(`#main [data-open-node="${config.node}"]`).click();
    const check = async root => {
      const summary = root.locator('[data-node-changes]');
      await summary.locator(':scope > details:not([open]) > summary').click();
      await summary.getByText('查看完整差异对照', {exact:true}).first().waitFor();
      assert.ok((await summary.innerText()).includes('新增 1 项，修改 1 项'));
      assert.ok((await summary.locator('.node-change-summary').allTextContents()).join('').includes('新增边界检查'));
      const content = root.locator('[data-node-change-field="work_content"]');
      const disclosure = content.locator('..');
      if (await disclosure.getAttribute('open') === null) await disclosure.locator(':scope > summary').click();
      assert.deepEqual(await content.locator('mark').allTextContents(), ['5','新增边界检查']);
      assert.equal(await content.locator('li').first().innerText(), '接口保持不变');
      assert.equal(await content.locator('li').first().locator('mark').count(), 0);
      assert.equal(await root.locator('.node-changed-field').count(), 0);
      assert.equal(await root.locator('[data-node-change-field="implementation_approach"] mark').count(), 0);
      const order = await summary.evaluate(element => Boolean(element.compareDocumentPosition(document.querySelector('[data-node-change-field="work_content"]')) & Node.DOCUMENT_POSITION_FOLLOWING));
      assert.equal(order, true, 'summary precedes current content');
    };
    const drawer = page.locator('#drawer');
    await check(drawer);
    // Re-reading the same comparison must not duplicate highlights or change text.
    await page.evaluate(async node => loadNodeChanges(findNode(node), document.querySelector('#drawer')), config.node);
    await check(drawer);
    await drawer.locator('#node-plan-complete').click();
    const modal = page.locator('#modal');
    await modal.getByRole('button', {name:'确认审批完成',exact:true}).waitFor();
    await modal.locator('[data-node-changes] > details > summary').click();
    assert.ok((await modal.locator('[data-node-changes]').innerText()).includes('新增边界检查'));
    const highlights = await modal.locator('[data-node-changes] mark').allTextContents();
    assert.ok(highlights.includes('5'));
    assert.ok(!highlights.some(text => text.includes('复位后检查') || text.includes('个周期') || text.includes('接口保持不变')));
    await modal.getByRole('button', {name:'取消',exact:true}).click();
    await drawer.locator('#expand-node').click();
    await check(page.locator('#main'));
    await page.reload();
    await check(page.locator('#main'));
    assert.equal(new URL(page.url()).searchParams.get('project'), config.project);
    if (process.env.VERIF_NODE_CHANGES_SCREENSHOTS) {
      for (const theme of ['dark','light']) {
        await page.evaluate(value => document.documentElement.dataset.theme = value, theme);
        await page.screenshot({path:`${process.env.VERIF_NODE_CHANGES_SCREENSHOTS}/${config.workstream}-${theme}.png`,fullPage:true});
      }
    }
    // A stale API response still blocks the approval confirmation.
    await page.route('**/api/node-changes?*', async route => {
      const response = await route.fetch();
      const body = await response.json();
      body.result.definition_digest = 'stale-test-version';
      await route.fulfill({response,json:body});
    });
    await page.locator('#main #node-plan-complete').click();
    await modal.getByText(/无法核对最近一次批准内容/).waitFor();
    assert.equal(await modal.locator('[type="submit"]').isDisabled(), true);
    assert.deepEqual(writes, [], 'comparison must never approve or change project state');
    assert.deepEqual(errors, []);
    console.log('node changes browser PASS');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
