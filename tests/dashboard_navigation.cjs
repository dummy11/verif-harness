// Exercise the shipped HTML, real DOM events, History API and authorized HTTP APIs.
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
  page.on('dialog', dialog => dialog.accept());
  const url = params => {
    const value = new URL(config.url);
    value.searchParams.set('project', config.project); value.searchParams.set('token', config.token);
    for (const [key, item] of Object.entries(params || {})) value.searchParams.set(key, item);
    return value.toString();
  };
  const heading = text => page.getByRole('heading', {name:text, exact:true}).waitFor();
  const api = async (path, data) => {
    const response = data
      ? await context.request.post(config.url + path, {headers:{'X-Verif-Token':config.token}, data:{dashboard_project:config.project, ...data}})
      : await context.request.get(config.url + path, {headers:{'X-Verif-Token':config.token}});
    assert.equal(response.ok(), true, await response.text());
    return response.json();
  };
  try {
    await page.goto(url());
    await page.locator('[data-workstream="VDOC"]').waitFor();
    await page.locator('[data-workstream="VDOC"]').click();
    await heading('VDOC · 验证文档');
    assert.equal(context.pages().length, 1);
    assert.equal(new URL(page.url()).searchParams.get('project'), config.project);
    assert.equal(new URL(page.url()).searchParams.get('token'), config.token);
    await page.goBack();
    await page.locator('[data-workstream="VDOC"]').waitFor();
    await page.goForward();
    await heading('VDOC · 验证文档');
    if (process.env.VERIF_DASHBOARD_SCREENSHOT_DIR) await page.screenshot({path:process.env.VERIF_DASHBOARD_SCREENSHOT_DIR + '/workflow.png'});
    await page.locator('#search').fill('DUT');
    const link = page.locator('a[data-open-node]').first();
    const node = await link.getAttribute('data-open-node');
    assert.ok((await link.getAttribute('href')).includes('token='));
    await link.click();
    await page.locator('#drawer-backdrop.open').waitFor();
    if (process.env.VERIF_DASHBOARD_SCREENSHOT_DIR) await page.screenshot({path:process.env.VERIF_DASHBOARD_SCREENSHOT_DIR + '/node-drawer.png'});
    assert.equal(context.pages().length, 1);
    assert.ok(await page.locator('#drawer [data-plan-section-form]').count() > 0);
    assert.equal(await page.locator('#drawer .node-plan-approval').getAttribute('open'), null);
    await page.locator('#expand-node').click();
    await page.locator('#main .node-plan-approval').waitFor();
    assert.equal(await page.locator('#drawer-backdrop.open').count(), 0);
    await page.goBack();
    await page.locator('#drawer-backdrop.open').waitFor();
    await page.locator('#close-drawer').click();
    await page.waitForFunction(() => !document.querySelector('#drawer-backdrop.open'));
    assert.equal(await page.locator('#search').inputValue(), 'DUT');
    assert.equal(new URL(page.url()).searchParams.has('node'), false);
    await page.reload();
    await heading('VDOC · 验证文档');
    assert.equal(await page.locator('#drawer-backdrop.open').count(), 0);

    // Explicit new-tab affordance: the ordinary path must never create a tab.
    await page.locator(`[data-open-node="${node}"]`).click();
    const popupPromise = context.waitForEvent('page');
    await page.locator('#drawer .route-bar .open-separate').click();
    const popup = await popupPromise;
    await popup.waitForLoadState();
    assert.equal(new URL(popup.url()).searchParams.get('project'), config.project);
    await popup.close();
    await page.locator('#close-drawer').click();

    await page.locator(`[data-open-node="${node}"]`).click();
    await page.locator('#drawer .node-plan-approval > summary').click();
    await page.locator('#drawer [data-plan-section-form]').first().waitFor();
    if (process.env.VERIF_DASHBOARD_SCREENSHOT_DIR) await page.screenshot({path:process.env.VERIF_DASHBOARD_SCREENSHOT_DIR + '/plan-review.png'});
    assert.equal(await page.locator('#drawer-backdrop.open').count(), 1);
    const form = page.locator('#drawer [data-plan-section-form]').first();
    const section = await form.getAttribute('data-plan-section-form');
    await form.locator('[name="reviewer"]').fill('browser-test-reviewer');
    await form.locator('[name="verdict"]').selectOption('add');
    await form.locator('[name="reason"]').fill('未提交的范围说明');
    assert.equal(await form.locator('[data-change-operation],[data-change-target],[data-change-instruction]').count(), 0);
    // A real HTTP snapshot drives the same path as a live event, without waiting for the SSE interval.
    const snapshot = await api(`/api/snapshot?project=${config.project}`);
    const scrollBefore = await page.evaluate(() => window.scrollY);
    await page.evaluate(snapshot => setSnapshot(snapshot), snapshot);
    assert.ok(Math.abs(await page.evaluate(() => window.scrollY) - scrollBefore) <= 1);
    assert.equal(await page.evaluate(() => document.activeElement.value), '未提交的范围说明');
    assert.equal(await form.locator('[name="reason"]').inputValue(), '未提交的范围说明');
    assert.equal(await form.locator('[name="verdict"]').inputValue(), 'add');
    // Close the modal drawer before using the sidebar, as a user must. The
    // reopened drawer must retain the same draft after leaving this page.
    await page.locator('#close-drawer').click();
    await page.waitForFunction(() => !document.querySelector('#drawer-backdrop.open'));
    await page.locator('[data-nav="agent"]').click();
    await heading('Agent 交互');
    await page.goBack();
    await page.locator(`[data-open-node="${node}"]`).click();
    await page.locator('#drawer .node-plan-approval').waitFor();
    assert.equal(await form.locator('[name="reason"]').inputValue(), '未提交的范围说明');

    // Successful UI submission must write through the API and clear only that draft.
    const written = page.waitForResponse(r => r.url().includes('/api/reviews/node-plan-section') && r.request().method() === 'POST');
    await form.getByRole('button', {name:'提交审批',exact:true}).click();
    assert.equal((await written).ok(), true);
    await page.waitForFunction(() => document.querySelector('[data-plan-section-form] [name="reason"]').value === '');
    const after = await api(`/api/snapshot?project=${config.project}`);
    const stored = after.workstreams.find(w => w.workstream === 'VDOC').nodes.find(n => n.id === node);
    assert.ok(stored.plan_review.sections.find(s => s.section === section).reviews.some(r => r.reason === '未提交的范围说明'));
    const savedReview = stored.plan_review.sections.find(s => s.section === section).current_review;
    assert.equal(savedReview.change_items[0].operation, 'add');
    assert.equal(savedReview.change_items[0].instruction, '未提交的范围说明');

    // Completing the approval changes only this writing-plan node state; approval remains usable.
    const approvedSnapshot = await api(`/api/snapshot?project=${config.project}`);
    await page.evaluate(snapshot => setSnapshot(snapshot), approvedSnapshot);
    const completeButton = page.locator('#drawer #node-plan-complete');
    assert.equal(await completeButton.isEnabled(), true);
    await completeButton.click();
    await page.locator('#node-plan-complete-form [name="reviewer"]').fill('browser-test-reviewer');
    await page.locator('#node-plan-complete-form [name="reason"]').fill('完成本轮文档撰写方案审批');
    const completedWrite = page.waitForResponse(r => r.url().includes('/api/reviews/node-plan-complete') && r.request().method() === 'POST');
    await page.locator('#node-plan-complete-form').getByRole('button', {name:'确认审批完成', exact:true}).click();
    assert.equal((await completedWrite).ok(), true);
    const completedSnapshot = await api(`/api/snapshot?project=${config.project}`);
    const completedNode = completedSnapshot.workstreams.find(w => w.workstream === 'VDOC').nodes.find(n => n.id === node);
    assert.equal(completedNode.status, 'VALID');
    assert.equal(completedNode.plan_review.completed, true);
    if (!(await page.locator('#drawer .node-plan-approval').evaluate(element => element.open))) {
      await page.locator('#drawer .node-plan-approval > summary').click();
    }
    await form.locator('[name="reviewer"]').fill('browser-test-reviewer');
    await form.locator('[name="reason"]').fill('审批完成后继续提交修改意见');
    await form.locator('[name="verdict"]').selectOption('modify');
    const continuedWrite = page.waitForResponse(r => r.url().includes('/api/reviews/node-plan-section') && r.request().method() === 'POST');
    await form.getByRole('button', {name:'提交审批', exact:true}).click();
    assert.equal((await continuedWrite).ok(), true);
    const continuedSnapshot = await api(`/api/snapshot?project=${config.project}`);
    const continuedNode = continuedSnapshot.workstreams.find(w => w.workstream === 'VDOC').nodes.find(n => n.id === node);
    assert.equal(continuedNode.status, 'REVIEW_REQUIRED');
    assert.equal(continuedNode.plan_review.completed, false);

    // Changed digest: never replay an old draft into a new approval form.
    await form.locator('[name="reason"]').fill('只适用于旧版本');
    await page.evaluate(snapshot => {
      state.stream.close();
      const node = snapshot.workstreams.find(w => w.workstream === 'VDOC').nodes.find(n => n.plan_review);
      node.plan_review.definition_digest = 'changed-for-ui-isolation-test';
      setSnapshot(snapshot);
    }, continuedSnapshot);
    await page.getByText('审批对象或版本已变化，旧草稿没有填入当前表单，也未提交。', {exact:true}).waitFor();
    assert.equal(await form.locator('[name="reason"]').inputValue(), '');

    // Registered project switching must not replay another project's draft or return late responses there.
    await page.locator('#project-switcher').selectOption(config.otherProject);
    await page.waitForFunction(() => document.querySelector('#project-name').textContent === 'beta');
    assert.equal(await page.getByText('只适用于旧版本', {exact:true}).count(), 0);
    await page.goBack();
    await page.locator('#drawer .node-plan-approval').waitFor();
    assert.equal(await page.locator('#project-name').textContent(), 'alpha');

    // The delivery page stays in this tab; its document comparison is a separate read-only tab.
    await page.locator('#project-switcher').selectOption(config.otherProject);
    await page.locator('[data-workstream="VDOC"]').click();
    const otherSnapshotResponse = await context.request.get(config.url + `/api/snapshot?project=${config.otherProject}`, {headers:{'X-Verif-Token':config.token}});
    const otherSnapshot = await otherSnapshotResponse.json();
    const delivery = otherSnapshot.workstreams.find(w => w.workstream === 'VDOC').nodes.find(n => n.delivery_review);
    await page.locator(`[data-open-node="${delivery.id}"]`).click();
    await page.locator('#document-delivery-review-tab').click();
    await page.locator('#delivery-review-form').waitFor();
    assert.equal(await page.locator('#drawer-backdrop.open').count(), 0);
    await page.locator('#delivery-review-form [name="notes"]').fill('正文待补充核对');
    const documentPopup = context.waitForEvent('page');
    await page.locator('[data-view-delivery-document]').click();
    const doc = await documentPopup;
    await doc.locator('.document-preview').waitFor();
    assert.equal(await doc.locator('form').count(), 0);
    assert.equal(new URL(doc.url()).searchParams.get('project'), config.otherProject);
    await doc.close();
    await page.evaluate(snapshot => setSnapshot(snapshot), otherSnapshot);
    await page.waitForFunction(() => document.querySelector('#delivery-review-form [name="notes"]')?.value === '正文待补充核对');

    // Delayed document reads cannot replace a subsequently selected page.
    await page.route('**/api/document?*', async route => {
      await new Promise(resolve => setTimeout(resolve, 250));
      await route.continue();
    });
    await page.evaluate(snapshot => setSnapshot(snapshot), otherSnapshot);
    await page.locator('[data-nav="risk"]').click();
    await heading('风险与变更');
    await page.waitForTimeout(450);
    await heading('风险与变更');
    await page.unroute('**/api/document?*');
    await page.locator('#project-switcher').selectOption(config.project);

    for (const [selector, title] of [['pending','需要你处理'],['agent','Agent 交互'],['risk','风险与变更']]) {
      await page.locator(`[data-nav="${selector}"]`).click();
      if (selector === 'pending') await page.locator('.pending-status-card').waitFor();
      else await heading(title);
      assert.equal(context.pages().length, 1);
    }
    await page.goto(url({'agent-interaction':'1','agent-question':config.question}));
    await page.locator(`[data-agent-question-form="${config.question}"]`).waitFor();
    const questionForm = page.locator(`[data-agent-question-form="${config.question}"]`);
    await questionForm.locator('[name="option"][value="other"]').check();
    await questionForm.locator('[name="answer_text"]').fill('保留回答输入');
    await page.evaluate(snapshot => setSnapshot(snapshot), after);
    assert.equal(await questionForm.locator('[name="answer_text"]').inputValue(), '保留回答输入');
    assert.equal(await questionForm.locator('[name="answer_text"]').getAttribute('required'), '');
    for (const params of [{workstream:'missing'},{workstream:'VDOC',node:'missing'},{'review-plan-node':'missing'},{'agent-question':'missing'},{'revise-vdoc-plan':'1','node-id':'missing'}]) {
      await page.goto(url(params));
      await page.getByText('无法打开这个入口', {exact:true}).waitFor();
    }
    await page.goto(url({document:'missing-document'}));
    await page.getByText('无法打开这份文档', {exact:true}).waitFor();

    // Short risky actions stay in a confirmation modal. Draft cancellation keeps route and content aligned.
    await page.goto(url({workstream:'VDOC'}));
    await page.locator('#restart-vdoc-workflow').click();
    await page.locator('#vdoc-restart-form [name="reason"]').fill('测试重启原因草稿');
    page.removeAllListeners('dialog');
    page.once('dialog', dialog => dialog.dismiss());
    const beforeCancel = page.url();
    await page.locator('#modal [data-close-modal]').click();
    assert.equal(page.url(), beforeCancel);
    assert.equal(await page.locator('#vdoc-restart-form [name="reason"]').inputValue(), '测试重启原因草稿');
    page.on('dialog', dialog => dialog.accept());
    await page.locator('#modal [data-close-modal]').click();
    await page.locator('#add-vdoc-node').click();
    await heading('添加工作节点');
    await page.locator('[data-return-vdoc]').first().click();
    await page.locator('#delete-vdoc-node').click();
    await heading('删除工作节点');
    await page.locator('[data-return-vdoc]').first().click();
    await page.locator('#project-unregister').click();
    await page.locator('#project-unregister-form').waitFor();
    await page.locator('#modal [data-close-modal]').click();
    assert.deepEqual(errors, []);
    console.log('Dashboard browser navigation, draft isolation and HTTP writes PASS');
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
