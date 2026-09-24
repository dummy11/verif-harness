// Whole-node approval must work with no prior section approvals or change requests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.VERIF_DASHBOARD_BROWSER_CHANNEL ? {channel:process.env.VERIF_DASHBOARD_BROWSER_CHANNEL} : {})});
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  const snapshot = async () => {
    const response = await context.request.get(`${config.url}api/snapshot?project=${config.project}`, {
      headers:{'X-Verif-Token':config.token},
    });
    assert.equal(response.ok(), true);
    return response.json();
  };
  const planNode = snapshot => snapshot.workstreams.find(w => w.workstream === 'VDOC').nodes.find(n => n.plan_review);
  try {
    const initial = planNode(await snapshot());
    assert.equal(initial.plan_review.status, 'PENDING');
    assert.equal(initial.plan_review.reviews.length, 0);
    assert.equal(initial.plan_review.completion_reviews.length, 0);
    const url = new URL(config.url);
    for (const [key, value] of Object.entries({project:config.project, token:config.token, workstream:'VDOC', node:initial.id})) {
      url.searchParams.set(key, value);
    }
    await page.goto(url.toString());
    const drawerButton = page.locator('#drawer #node-plan-complete');
    await drawerButton.waitFor();
    assert.equal(await drawerButton.isEnabled(), true);
    // The drawer and full-page entry both open the same whole-node approval form.
    await drawerButton.click();
    await page.getByRole('heading', {name:'批准当前文档撰写方案', exact:true}).waitFor();
    await page.locator('#modal [data-close-modal]').click();
    assert.equal(planNode(await snapshot()).plan_review.completed, false);
    await page.locator('#expand-node').click();
    await page.locator('#main #node-plan-complete').click();
    await page.locator('#node-plan-complete-form [name="reviewer"]').fill('browser-test-reviewer');
    await page.locator('#node-plan-complete-form [name="reason"]').fill('批准当前文档撰写方案的全部内容');
    const submitted = page.waitForResponse(r => r.url().includes('/api/reviews/node-plan-complete') && r.request().method() === 'POST');
    await page.locator('#node-plan-complete-form').getByRole('button', {name:'确认审批完成', exact:true}).click();
    assert.equal((await submitted).ok(), true);
    await page.locator('#main').getByRole('button', {name:'已批准全部内容', exact:true}).waitFor();
    await page.reload();
    await page.locator('#main').getByRole('button', {name:'已批准全部内容', exact:true}).waitFor();
    await page.waitForFunction(() => {
      const button = document.querySelector('#main #node-plan-complete');
      return button?.disabled && getComputedStyle(button).cursor === 'not-allowed';
    });
    const approved = planNode(await snapshot());
    assert.equal(approved.status, 'VALID');
    assert.equal(approved.plan_review.completed, true);
    assert.equal(approved.plan_review.reviews.length, 0);
    assert.equal(approved.plan_review.completion_reviews.length, 1);
    assert.ok(approved.plan_review.sections.every(section => section.status === 'APPROVED'));
    // Changes remain available after approval and invalidate that completion.
    await page.locator('#main .node-plan-approval > summary').click();
    const form = page.locator('#main [data-plan-section-form]');
    assert.equal(await form.count(), 1);
    await form.locator('[name="verdict"]').selectOption('modify');
    await form.locator('[name="reviewer"]').fill('browser-test-reviewer');
    await form.locator('[name="reason"]').fill('补充当前 DUT 的异常场景范围');
    const changed = page.waitForResponse(r => r.url().includes('/api/reviews/node-plan-section') && r.request().method() === 'POST');
    await form.getByRole('button', {name:'提交审批', exact:true}).click();
    assert.equal((await changed).ok(), true);
    await page.locator('#main').getByRole('button', {name:'审批完成', exact:true}).waitFor();
    assert.equal(await page.locator('#main #node-plan-complete').isEnabled(), true);
    const revised = planNode(await snapshot());
    assert.equal(revised.status, 'REVIEW_REQUIRED');
    assert.equal(revised.plan_review.completed, false);
    assert.equal(revised.plan_review.status, 'CHANGES_REQUESTED');
    assert.equal(revised.plan_review.completion_reviews.length, 1);
    assert.equal(revised.plan_review.reviews.length, 1);
    assert.deepEqual(errors, []);
    console.log('Whole-plan approval: drawer/full-page, zero prior reviews, refresh, subsequent changes PASS');
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
