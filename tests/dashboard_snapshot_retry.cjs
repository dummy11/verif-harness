// A retryable conflict during the first snapshot must keep the page connected
// and recover through the authoritative event stream without a manual reload.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
  const browser = await chromium.launch({
    headless:true,
    ...(process.env.VERIF_DASHBOARD_BROWSER_CHANNEL
      ? {channel:process.env.VERIF_DASHBOARD_BROWSER_CHANNEL} : {}),
  });
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  let snapshotRequests = 0;
  let releaseEvents;
  const eventGate = new Promise(resolve => { releaseEvents = resolve; });
  await page.route('**/api/snapshot?*', async route => {
    snapshotRequests += 1;
    if (snapshotRequests === 1) {
      await route.fulfill({
        status:409,
        json:{
          error:'读取期间项目状态仍在更新；Dashboard 将自动同步最新结果',
          code:'SNAPSHOT_CHANGING',
          retryable:true,
        },
      });
      return;
    }
    await route.continue();
  });
  await page.route('**/api/events?*', async route => {
    await eventGate;
    await route.continue();
  });
  try {
    const url = new URL(config.url);
    url.searchParams.set('project', config.project);
    url.searchParams.set('token', config.token);
    await page.goto(url.toString());
    await page.getByRole('status').filter({hasText:'项目状态正在更新'}).waitFor();
    assert.equal(await page.locator('#connection-text').innerText(), '连接正常 · 状态同步重试中');
    assert.match(await page.locator('#main').innerText(), /无需刷新或重复提交审批/);
    releaseEvents();
    await page.locator('[aria-label="当前项目状态"]').waitFor();
    assert.equal(await page.locator('#connection-text').innerText(), '实时连接正常');
    assert.equal(snapshotRequests, 1);
    assert.equal(errors.length, 0, errors.join('\n'));
    console.log('initial snapshot retry PASS');
  } finally {
    releaseEvents();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
