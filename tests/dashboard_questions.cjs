// Synthetic public fixture: compact entry, full source, safe formatting, real answer.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.VERIF_DASHBOARD_BROWSER_CHANNEL ? {channel:process.env.VERIF_DASHBOARD_BROWSER_CHANNEL} : {})});
  const context = await browser.newContext({viewport:{width:1280,height:960}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.route('**/api/events*', route => route.abort());
  const url = new URL(config.url);
  for (const [key, value] of Object.entries({project:config.project,token:config.token,workstream:'VENV',node:config.node})) url.searchParams.set(key, value);
  const screenshot = async name => {
    if (process.env.VERIF_DASHBOARD_SCREENSHOT_DIR) await page.screenshot({path:process.env.VERIF_DASHBOARD_SCREENSHOT_DIR + '/' + name + '.png'});
  };
  try {
    await page.goto(url.toString());
    const notice = page.locator('.agent-question-notice').filter({has:page.locator(`[data-agent-question="${config.question}"]`)});
    await notice.waitFor();
    assert.equal(await page.locator('.agent-question-notice').count(), 2);
    assert.equal(await notice.locator('.agent-question-title').innerText(), '请确认接口检查范围');
    assert.equal(await notice.locator('[data-agent-question]').innerText(), '查看并回答');
    assert.equal(await notice.locator('details').getAttribute('open'), null);
    assert.ok((await notice.innerText()).length < 100);
    await notice.scrollIntoViewIfNeeded();
    await screenshot('question-node');
    await notice.locator('summary').click();
    assert.equal((await notice.locator('.agent-message').innerText()).replace(/\s+/g, ''), config.displayPrompt.replace(/\s+/g, ''));
    assert.ok(await notice.locator('.agent-message p').count() > 1);
    assert.equal(await notice.locator('.agent-message').evaluate(el => getComputedStyle(el).fontWeight), '400');
    await notice.locator('[data-agent-question]').click();
    const form = page.locator(`[data-agent-question-form="${config.question}"]`);
    await form.waitFor();
    for (const [key, value] of Object.entries({project:config.project,token:config.token,'agent-question':config.question})) assert.equal(new URL(page.url()).searchParams.get(key), value);
    await page.reload();
    await form.waitFor();
    const card = page.locator('.agent-question-card').filter({has:form});
    assert.equal(await card.locator('h3').innerText(), '请确认接口检查范围');
    assert.equal(await card.locator('.agent-question-context').getAttribute('open'), null);
    await card.locator('.agent-question-context > summary').click();
    assert.equal(await card.locator('.agent-question-context h4').count(), 2);
    assert.equal(await card.locator('.agent-question-context li').count(), 2);
    assert.equal(await card.locator('pre code').innerText(), 'echo "绑定"\n');
    assert.equal(await card.locator('img,script,iframe').count(), 0);
    assert.equal(await page.evaluate(() => window.questionInjected), undefined);
    assert.equal(await form.locator('.agent-option-description li').count(), 2);
    await card.scrollIntoViewIfNeeded();
    await screenshot('question-details');
    await page.setViewportSize({width:390,height:844});
    assert.ok(await card.evaluate(el => el.scrollWidth <= el.clientWidth + 1));
    await screenshot('question-mobile');
    await page.setViewportSize({width:1280,height:960});
    await form.locator('[name="option"][value="current"]').check();
    await form.locator('[name="reviewer"]').fill('fixture-owner');
    const saved = page.waitForResponse(r => r.url().includes('/api/agent-questions/answer') && r.request().method() === 'POST');
    await form.getByRole('button', {name:'提交回答',exact:true}).click();
    assert.equal((await saved).ok(), true);
    await form.waitFor({state:'detached'});
    await page.reload();
    await page.locator(`[data-agent-question-form="${config.second}"]`).waitFor();
    const event = page.locator('.agent-event.question');
    assert.equal(await event.count(), 1);
    await event.locator('.agent-question-details > summary').click();
    assert.equal((await event.locator('.agent-question-details .agent-message').innerText()).replace(/\s+/g, ''), config.displayPrompt.replace(/\s+/g, ''));
    const invalid = new URL(page.url());
    invalid.searchParams.set('agent-question', 'question:missing');
    await page.goto(invalid.toString());
    await page.getByText('当前项目中找不到这个 Agent 问题。', {exact:true}).waitFor();
    assert.equal(await page.locator('[data-agent-question-form]').count(), 0);
    assert.deepEqual(errors, []);
    console.log('Question readability, navigation, source preservation and answer persistence PASS');
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => {console.error(error); process.exit(1);});
