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
    const listUrl = new URL(url); listUrl.searchParams.delete('node');
    await page.goto(listUrl.toString());
    const listApproval = page.locator(`[data-approve-plan-node="${initial.id}"]`);
    await listApproval.waitFor();
    assert.equal(await listApproval.innerText(), '批准全部内容');
    await listApproval.click();
    assert.equal(await page.locator('#modal').getAttribute('data-plan-node'), initial.id);
    await page.locator('#modal [data-close-modal]').click();
    await page.goto(url.toString());
    const drawerButton = page.locator('#drawer #node-plan-complete');
    await drawerButton.waitFor();
    assert.equal(await page.locator('#drawer .writing-plan-inputs').getAttribute('open'), null);
    await page.locator('#drawer .writing-plan-inputs > summary').click();
    const drawerText = await page.locator('#drawer .role-node-panel').innerText();
    assert.ok(drawerText.includes('RTL 目录：rtl'));
    assert.doesNotMatch(drawerText, /预计正文交付|方案质量检查|rtl\/dut\.sv/);
    assert.equal(await drawerButton.isEnabled(), true);
    // The drawer and full-page entry both open the same whole-node approval form.
    await drawerButton.click();
    await page.getByRole('heading', {name:'批准当前文档撰写方案', exact:true}).waitFor();
    await page.locator('#modal [data-close-modal]').click();
    assert.equal(planNode(await snapshot()).plan_review.completed, false);
    await page.locator('#expand-node').click();
    if (await page.locator('#main .writing-plan-inputs').getAttribute('open') === null) await page.locator('#main .writing-plan-inputs > summary').click();
    const pageText = await page.locator('#main .role-node-panel').innerText();
    assert.ok(pageText.includes('RTL 目录：rtl'));
    assert.doesNotMatch(pageText, /预计正文交付|方案质量检查|rtl\/dut\.sv/);
    await page.locator('#main #node-plan-complete').click();
    const approval = page.locator('#node-plan-complete-form');
    const confirm = approval.getByRole('button', {name:'确认审批完成', exact:true});
    assert.equal(await approval.locator('[name="reason"]').getAttribute('required'), null);
    await approval.locator('[name="reviewer"]').fill('');
    await confirm.click();
    assert.equal(await approval.locator('[name="reviewer"]').evaluate(e => e.validity.valueMissing), true);
    await approval.locator('[name="reviewer"]').fill('browser-test-reviewer');
    // Rejections remain visible inside the modal and keep the user's input.
    const endpoint = '**/api/reviews/node-plan-complete';
    await page.route(endpoint, route => route.fulfill({status:400, json:{error:'测试：当前方案已变化'}}));
    await confirm.click();
    await approval.locator('[data-submit-status]').filter({hasText:'未提交审批：测试：当前方案已变化'}).waitFor();
    assert.equal(await confirm.isEnabled(), true);
    assert.equal(await approval.locator('[name="reviewer"]').inputValue(), 'browser-test-reviewer');
    await page.unroute(endpoint);
    // A slow write immediately shows progress; even a synthetic double-submit
    // cannot send another approval. The reason deliberately stays empty.
    let releaseWrite, writes = 0;
    const writeGate = new Promise(resolve => releaseWrite = resolve);
    await page.route(endpoint, async route => { writes++; await writeGate; await route.continue(); });
    // Keep the pre-write snapshot visible until the delayed HTTP read finishes;
    // otherwise SSE can hide a blocking-refresh regression.
    await page.evaluate(() => state.stream.close());
    let releaseRefresh, refreshStarted;
    const refreshGate = new Promise(resolve => releaseRefresh = resolve);
    const refreshing = new Promise(resolve => refreshStarted = resolve);
    await page.route('**/api/snapshot?*', async route => {
      if (new URL(route.request().url()).searchParams.get('project') !== config.project) { await route.continue(); return; }
      refreshStarted(); await refreshGate; await route.continue();
    });
    const submitted = page.waitForResponse(r => r.url().includes('/api/reviews/node-plan-complete') && r.request().method() === 'POST');
    await confirm.click();
    await approval.getByRole('button', {name:'正在提交…', exact:true}).waitFor();
    assert.equal(await approval.locator('[type="submit"]').isDisabled(), true);
    await approval.evaluate(form => form.requestSubmit());
    await approval.locator('[data-submit-status]').filter({hasText:'正在保存审批'}).waitFor();
    releaseWrite();
    assert.equal((await submitted).ok(), true);
    await refreshing;
    await page.locator('#modal-backdrop').waitFor({state:'hidden'});
    await page.locator('.node-table').waitFor();
    assert.equal(new URL(page.url()).searchParams.has('node'), false);
    assert.equal(await page.locator('#drawer-backdrop.open').count(), 0);
    const savedRow = page.locator(`[data-approve-plan-node="${initial.id}"]`);
    assert.equal(await savedRow.innerText(), '审批已保存，状态待更新');
    assert.equal(await savedRow.isDisabled(), true);
    assert.equal(await page.locator('#node-plan-complete-form').count(), 0);
    // The saved receipt disables only repeat approval; it does not invent node
    // progress or close the workflow while the authoritative snapshot is stale.
    assert.equal(await page.evaluate(id => findNode(id).plan_review.completed, initial.id), false);
    assert.equal(writes, 1);
    // Browsing remains usable and the eventual response must not navigate back.
    await page.evaluate(() => navigatePrimary('overview'));
    assert.equal(new URL(page.url()).searchParams.has('workstream'), false);
    await page.evaluate(project => navigateUrl(routeUrl({project, workstream:'VDOC'})), config.otherProject);
    const refreshed = page.waitForResponse(r => r.url().includes('/api/snapshot?') && new URL(r.url()).searchParams.get('project') === config.project);
    releaseRefresh();
    await (await refreshed).finished();
    assert.equal(await page.evaluate(() => state.snapshot.dashboard_project_id), config.otherProject);
    assert.equal(new URL(page.url()).searchParams.get('project'), config.otherProject);
    await page.unroute('**/api/snapshot?*');
    await page.unroute(endpoint);
    await page.evaluate(project => navigateUrl(routeUrl({project, workstream:'VDOC'})), config.project);
    await page.locator('.node-table').getByRole('button', {name:'已批准全部内容', exact:true}).waitFor();
    assert.equal(new URL(page.url()).searchParams.has('node'), false);
    assert.equal(await page.locator('#drawer-backdrop.open').count(), 0);
    assert.equal(context.pages().length, 1);
    await page.reload();
    await page.locator('.node-table').getByRole('button', {name:'已批准全部内容', exact:true}).waitFor();
    await page.locator(`.node-table [data-open-node="${initial.id}"]`).click();
    await page.locator('#expand-node').click();
    await page.waitForFunction(() => {
      const button = document.querySelector('#main #node-plan-complete');
      return button?.disabled && getComputedStyle(button).cursor === 'not-allowed';
    });
    const approved = planNode(await snapshot());
    assert.equal(approved.status, 'VALID');
    assert.equal(approved.plan_review.completed, true);
    assert.equal(approved.plan_review.reviews.length, 0);
    assert.equal(approved.plan_review.completion_reviews.length, 1);
    assert.equal(approved.plan_review.completion_reviews[0].reason, '');
    assert.ok(approved.plan_review.sections.every(section => section.status === 'APPROVED'));
    // Changes remain available after approval and invalidate that completion.
    await page.locator('#main .node-plan-approval > summary').click();
    const form = page.locator('#main [data-plan-section-form]');
    assert.equal(await form.count(), 1);
    await form.locator('[name="verdict"]').selectOption('modify');
    await form.locator('[name="reviewer"]').fill('browser-test-reviewer');
    await form.locator('[name="reason"]').fill('补充当前 DUT 的异常场景范围');
    const changed = page.waitForResponse(r => r.url().includes('/api/reviews/node-plan-section') && r.request().method() === 'POST');
    await form.getByRole('button', {name:'添加审批意见', exact:true}).click();
    assert.equal((await changed).ok(), true);
    const feedbackButton = page.locator('#main [data-submit-node-feedback]');
    await feedbackButton.getByText('提交当前 1 条审批意见给 Agent', {exact:true}).waitFor();
    assert.equal(await feedbackButton.isEnabled(), true);
    assert.equal(await page.locator('#main #node-plan-complete').isEnabled(), false);
    const revised = planNode(await snapshot());
    assert.equal(revised.status, 'REVIEW_REQUIRED');
    assert.equal(revised.plan_review.completed, false);
    assert.equal(revised.plan_review.status, 'CHANGES_REQUESTED');
    assert.equal(revised.plan_review.completion_reviews.length, 1);
    assert.equal(revised.plan_review.reviews.length, 1);
    assert.equal(revised.plan_review.feedback.draft_count, 1);
    const feedbackWrite = page.waitForResponse(r => r.url().includes('/api/reviews/node-feedback-submit') && r.request().method() === 'POST');
    await feedbackButton.click();
    const feedbackResponse = await feedbackWrite;
    assert.equal(feedbackResponse.ok(), true);
    const feedbackReceipt = await feedbackResponse.json();
    await page.locator('#main [data-submit-node-feedback]').getByText('已提交 1 条，等待 Agent 处理', {exact:true}).waitFor();
    assert.equal(await page.locator('#main #node-plan-complete').isEnabled(), false);
    assert.equal(await page.locator('#main [data-plan-section-form] button').isEnabled(), false);
    const agentCompletion = await context.request.post(`${config.url}api/reviews/agent-feedback-complete`, {
      headers:{'X-Verif-Token':config.token},
      data:{
        dashboard_project:config.project,
        batch_id:feedbackReceipt.result.batch_id,
        checked_by:'Project Main Agent',
        summary:'已按意见补充当前 DUT 的异常场景范围',
      },
    });
    assert.equal(agentCompletion.ok(), true, await agentCompletion.text());
    await page.evaluate(snapshot => setSnapshot(snapshot), await snapshot());
    await page.locator('#main').getByRole('button', {name:'批准全部内容', exact:true}).waitFor();
    assert.equal(await page.locator('#main #node-plan-complete').isEnabled(), true);
    assert.equal(await page.locator('#main [data-plan-section-form] button').isEnabled(), true);
    // A lost write response is not a rejection: do not enable a blind retry.
    await page.locator('#main #node-plan-complete').click();
    await page.route(endpoint, route => route.abort('failed'));
    await page.locator('#node-plan-complete-form [name="reviewer"]').fill('browser-test-reviewer');
    await page.locator('#node-plan-complete-form [type="submit"]').click();
    await page.locator('[data-submit-status]').filter({hasText:'可能已保存，请勿重复提交'}).waitFor();
    assert.equal(await page.locator('#node-plan-complete-form [type="submit"]').isDisabled(), true);
    const approvalReceipt = page.waitForResponse(r => r.url().includes('/api/approval-status?'));
    await page.getByRole('button', {name:'刷新审批状态', exact:true}).click();
    const receiptResponse = await approvalReceipt;
    assert.equal(receiptResponse.ok(), true);
    assert.equal((await receiptResponse.json()).result.node_id, initial.id);
    await page.locator('#modal-backdrop').waitFor({state:'hidden'});
    assert.equal(planNode(await snapshot()).plan_review.completion_reviews.length, 1);
    await page.unroute(endpoint);
    // Bound an unresponsive write without claiming it failed or retrying it.
    await page.clock.install();
    let writeStarted, releaseTimeout;
    const started = new Promise(resolve => writeStarted = resolve);
    const timeoutGate = new Promise(resolve => releaseTimeout = resolve);
    await page.route(endpoint, async route => { writeStarted(); await timeoutGate; await route.abort(); });
    await page.locator('#main #node-plan-complete').click();
    await page.locator('#node-plan-complete-form [type="submit"]').click();
    await started;
    await page.clock.fastForward(30001);
    await page.locator('[data-submit-status]').filter({hasText:'请求超时'}).waitFor();
    assert.equal(await page.locator('#node-plan-complete-form [type="submit"]').isDisabled(), true);
    releaseTimeout();
    await page.getByRole('button', {name:'刷新审批状态', exact:true}).click();
    await page.locator('#modal-backdrop').waitFor({state:'hidden'});
    assert.equal(planNode(await snapshot()).plan_review.completion_reviews.length, 1);
    await page.unroute(endpoint);
    // A write can commit while its response is lost. Once the read-only receipt
    // confirms it, return to the list even when the full snapshot read fails.
    await page.locator('#main #close-drawer').click();
    await page.evaluate(() => state.stream.close());
    await page.route(endpoint, async route => { writes++; await route.fetch(); await route.abort('failed'); });
    await page.route('**/api/snapshot?*', route => route.fulfill({status:503, json:{error:'测试：页面刷新暂不可用'}}));
    await page.locator(`[data-approve-plan-node="${initial.id}"]`).click();
    await page.locator('#node-plan-complete-form [type="submit"]').click();
    await page.locator('[data-submit-status]').filter({hasText:'可能已保存，请勿重复提交'}).waitFor();
    assert.equal(await page.locator('#node-plan-complete-form [type="submit"]').isDisabled(), true);
    await page.getByRole('button', {name:'刷新审批状态', exact:true}).click();
    await page.locator('#modal-backdrop').waitFor({state:'hidden'});
    await page.locator('#toast').filter({hasText:'审批已保存；页面状态暂未更新'}).waitFor();
    assert.equal(await savedRow.innerText(), '审批已保存，状态待更新');
    assert.equal(await savedRow.isDisabled(), true);
    assert.equal(await page.locator('.node-table').isVisible(), true);
    assert.equal(writes, 2);
    await page.unroute(endpoint);
    await page.unroute('**/api/snapshot?*');
    await page.evaluate(snapshot => setSnapshot(snapshot), await snapshot());
    await page.locator('.node-table').getByRole('button', {name:'已批准全部内容', exact:true}).waitFor();
    assert.equal(context.pages().length, 1);
    assert.equal(new URL(page.url()).searchParams.has('node'), false);
    assert.equal(planNode(await snapshot()).plan_review.completion_reviews.length, 2);
    assert.deepEqual(errors, []);
    console.log('Whole-plan approval: immediate list return, background refresh/failure, optional reason, rejection, lost receipt, timeout, no duplicate writes PASS');
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
