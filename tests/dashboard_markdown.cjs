const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.VERIF_DASHBOARD_BROWSER_CHANNEL ? {channel:process.env.VERIF_DASHBOARD_BROWSER_CHANNEL} : {})});
  const context = await browser.newContext({viewport:{width:1440, height:1000}});
  const page = await context.newPage();
  const errors = [], externalRequests = [];
  context.on('page', tab => tab.on('pageerror', error => errors.push(String(error))));
  page.on('pageerror', error => errors.push(String(error)));
  context.on('request', request => {
    if (new URL(request.url()).origin !== new URL(config.url).origin) externalRequests.push(request.url());
  });
  const url = params => {
    const value = new URL(config.url);
    value.searchParams.set('project', config.otherProject);
    value.searchParams.set('token', config.token);
    for (const [key, item] of Object.entries(params || {})) value.searchParams.set(key, item);
    return value.toString();
  };
  const snapshot = async () => {
    const endpoint = new URL('/api/snapshot', config.url);
    endpoint.searchParams.set('project', config.otherProject);
    const response = await context.request.get(endpoint.toString(), {headers:{'X-Verif-Token':config.token}});
    assert.equal(response.ok(), true);
    return response.json();
  };
  const rendered = async (tab=page, scope='.markdown-body') => {
    // SSE may replace the page between awaits. Observe one complete render in
    // a single browser task; keep all content/security assertions unchanged.
    const handle = await tab.waitForFunction(selector => {
      const body = document.querySelector(selector);
      if (!body?.querySelector('h1')?.textContent.includes('验证计划示例')) return null;
      return {
        rows:body.querySelectorAll('table tbody tr').length,
        code:body.querySelector('pre code')?.textContent || '',
        forbidden:body.querySelectorAll('script, img, form, input').length,
        injection:globalThis.markdownInjection,
        unsafeLinks:body.querySelectorAll('a[href^="javascript:"], a[href^="file:"]').length,
        unavailable:[...body.querySelectorAll('.document-link-unavailable')].filter(el => el.textContent.includes('未登记文档')).length,
      };
    }, scope);
    const observed = await handle.jsonValue();
    await handle.dispose();
    assert.equal(observed.rows, 2);
    assert.ok(observed.code.includes('$stable(payload)'));
    assert.equal(observed.forbidden, 0);
    assert.equal(observed.injection, undefined);
    assert.equal(observed.unsafeLinks, 0);
    assert.equal(observed.unavailable, 1);
  };
  try {
    const before = await snapshot();
    const delivery = before.workstreams.find(w => w.workstream === 'VDOC').nodes.find(n => n.delivery_review);
    const docId = delivery.delivery_review.document_id;
    const document = before.documents.find(d => d.id === docId);
    await page.goto(url({document:docId}));
    await rendered();
    assert.equal(await page.locator('form').count(), 0);
    await page.getByText('查看 Markdown 源码', {exact:true}).click();
    assert.ok((await page.locator('.document-source pre').textContent()).startsWith('# 验证计划示例'));
    await page.getByText('查看 Markdown 源码', {exact:true}).click();
    await page.evaluate(() => window.scrollTo(0, 0));
    if (process.env.VERIF_DASHBOARD_SCREENSHOT_DIR) await page.screenshot({path:process.env.VERIF_DASHBOARD_SCREENSHOT_DIR + '/markdown-dark.png', fullPage:true});
    await page.locator('#theme').click();
    if (process.env.VERIF_DASHBOARD_SCREENSHOT_DIR) await page.screenshot({path:process.env.VERIF_DASHBOARD_SCREENSHOT_DIR + '/markdown-light.png', fullPage:true});
    await page.locator('#theme').click();
    await page.getByRole('link', {name:'当前章节', exact:true}).click();
    await page.waitForURL(value => decodeURIComponent(value.hash) === '#md-dut-范围');
    await page.waitForFunction(() => {
      const top = document.getElementById('md-dut-范围')?.getBoundingClientRect().top;
      return window.scrollY > 0 && top >= 76 && top < innerHeight / 2;
    });
    await page.reload();
    await rendered();
    await page.waitForFunction(() => {
      const top = document.getElementById('md-dut-范围')?.getBoundingClientRect().top;
      return window.scrollY > 0 && top >= 76 && top < innerHeight / 2;
    });
    await page.getByRole('link', {name:'专题断言', exact:true}).click();
    await page.locator('.markdown-body h1').filter({hasText:'断言计划'}).waitFor();
    assert.equal(new URL(page.url()).searchParams.get('project'), config.otherProject);
    assert.equal(new URL(page.url()).searchParams.get('token'), config.token);
    await page.reload();
    await page.locator('.markdown-body h1').filter({hasText:'断言计划'}).waitFor();
    await page.goBack();
    await rendered();
    await page.getByRole('link', {name:'失效章节', exact:true}).click();
    await page.getByText('当前文档中找不到这个章节；已打开整篇正文供核对。', {exact:true}).waitFor();
    await page.goto(url({document:docId}));
    await rendered();
    await page.locator('#project-switcher').selectOption(config.project);
    await page.waitForFunction(() => document.querySelector('#project-name').textContent === 'alpha');
    assert.equal(await page.getByRole('heading', {name:'验证计划示例', exact:true}).count(), 0);
    await page.goto(url({document:'document:vdoc:missing'}));
    await page.getByText('无法打开这份文档', {exact:true}).waitFor();
    assert.ok(before.waiting_for_human.some(a => a.source === 'closure' && a.target === delivery.id));
    await page.goto(url({'pending-items':'1'}));
    await page.locator(`.pending-status-list [data-open-node="${delivery.id}"]`).click();
    await page.waitForURL(value => value.searchParams.get('node') === delivery.id);
    assert.equal(new URL(page.url()).searchParams.get('project'), config.otherProject);
    assert.equal(new URL(page.url()).searchParams.get('token'), config.token);
    await page.reload();
    await page.locator('#document-delivery-review-tab').click();
    await rendered();
    // A snapshot event can rebuild the view just after rendered() returns.
    // Wait for the rebuilt form and assert uniqueness in the same DOM read.
    await page.waitForFunction(() => document.querySelectorAll('#delivery-review-form').length === 1);
    const popupPromise = context.waitForEvent('page');
    await page.locator('[data-view-delivery-document]').click();
    const popup = await popupPromise;
    await rendered(popup);
    assert.equal(new URL(popup.url()).searchParams.get('project'), config.otherProject);
    await popup.close();
    // Legacy document review uses the same renderer, without adding an injected form.
    await page.evaluate(document => openDocumentReviewModal(document), document);
    await rendered(page, '#modal .markdown-body');
    assert.equal(await page.locator('#modal form').count(), 1);
    await page.locator('#modal [data-close-modal]').click();
    const afterRead = await snapshot();
    assert.deepEqual(afterRead.documents.find(d => d.id === docId), document);
    await page.locator('#delivery-review-form [name="reviewer"]').fill('markdown-browser-reviewer');
    await page.locator('#delivery-review-form [name="notes"]').fill('已阅读排版正文并核对源码');
    const written = page.waitForResponse(r => r.url().includes('/api/reviews/document-delivery') && r.request().method() === 'POST');
    await page.locator('#delivery-review-form button[type="submit"], #delivery-review-form button.primary').last().click();
    assert.equal((await written).ok(), true);
    const after = await snapshot();
    const reviewed = after.workstreams.find(w => w.workstream === 'VDOC').nodes.find(n => n.id === delivery.id);
    assert.equal(reviewed.delivery_review.status, 'AGENT_CHECKING');
    assert.equal(reviewed.delivery_review.current_review.document_digest, document.digest);
    assert.ok(!after.waiting_for_human.some(a => a.source === 'closure' && a.target === delivery.id));
    assert.ok(after.workstreams.find(w => w.workstream === 'VDOC').closure.actions.some(a => a.kind === 'CHECK_DOCUMENT_REVIEW' && a.target === delivery.id));
    // Renderer failure leaves readable source, never a blank acceptance surface.
    await page.route('**/assets/markdown-it.min.js?*', route => route.abort());
    await page.goto(url({document:docId}));
    await page.getByText('文档排版暂不可用，请展开 Markdown 源码阅读。', {exact:true}).waitFor();
    assert.equal(await page.locator('.document-source').evaluate(e => e.open), true);
    assert.deepEqual(externalRequests, []);
    assert.deepEqual(errors, []);
    console.log('Markdown browser reading, anchors, project isolation, source fallback and digest-bound review PASS');
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
