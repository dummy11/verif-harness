// Compare same-node delivery changes against an actual approval, not a revision.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.VERIF_DASHBOARD_BROWSER_CHANNEL ? {channel:process.env.VERIF_DASHBOARD_BROWSER_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors = [], writes = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('request', request => { if (request.method() === 'POST') writes.push(request.url()); });
    await page.route('**/api/events*', route => route.abort());
    const url = new URL(config.url);
    for (const [key,value] of Object.entries({project:config.project,token:config.token,workstream:config.workstream,node:config.node,'node-view':'full'})) url.searchParams.set(key,value);
    await page.goto(url.toString());
    const main = page.locator('#main');
    await main.locator('[data-node-changes]').getByText(/最近一次批准/).first().waitFor();
    const field = main.locator(`[data-node-change-field="${config.field}"]`);
    for (const disclosure of await main.locator('.node-content-details').all()) {
      if (await disclosure.getAttribute('open') === null) await disclosure.locator(':scope > summary').click();
    }
    assert.deepEqual(await field.locator('mark:visible').allTextContents(), [config.added]);
    assert.ok((await field.innerText()).includes(config.unchanged));
    const button = main.locator(config.field === 'document_body' ? '#node-delivery-complete' : '#node-plan-complete');
    await button.click();
    const modal = page.locator('#modal');
    await modal.getByRole('button', {name:'确认审批完成',exact:true}).waitFor();
    const marks = await modal.locator('[data-node-changes] mark').allTextContents();
    assert.ok(marks.includes(config.added));
    assert.ok(!marks.some(text => text.includes(config.unchanged)));
    await modal.getByRole('button', {name:'取消',exact:true}).click();
    await page.reload();
    await main.locator('[data-node-changes]').getByText(/最近一次批准/).first().waitFor();
    for (const disclosure of await main.locator('.node-content-details').all()) {
      if (await disclosure.getAttribute('open') === null) await disclosure.locator(':scope > summary').click();
    }
    assert.deepEqual(await field.locator('mark:visible').allTextContents(), [config.added]);
    assert.deepEqual(errors, []);
    assert.deepEqual(writes, []);
    if (process.env.VERIF_NODE_CHANGES_SCREENSHOTS) {
      await page.screenshot({path:`${process.env.VERIF_NODE_CHANGES_SCREENSHOTS}/${config.field}.png`,fullPage:true});
    }
    console.log('approval subject browser PASS');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
