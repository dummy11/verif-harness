// Real layout, click targets and HTTP-backed document identity in an isolated project.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.VERIF_DASHBOARD_BROWSER_CHANNEL ? {channel:process.env.VERIF_DASHBOARD_BROWSER_CHANNEL} : {})});
  const context = await browser.newContext({viewport:{width:1440, height:1000}, reducedMotion:'no-preference'});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  const url = new URL(config.url);
  url.searchParams.set('project', config.otherProject);
  url.searchParams.set('token', config.token);
  url.searchParams.set('workstream', 'VDOC');
  const table = page.locator('.work-node-table');
  const capture = async name => {
    if (process.env.VERIF_DASHBOARD_SCREENSHOT_DIR) {
      await page.screenshot({path:process.env.VERIF_DASHBOARD_SCREENSHOT_DIR + '/' + name + '.png', fullPage:true});
    }
  };
  const checkAlignment = async () => {
    const layout = await table.evaluate(element => {
      const headers = [...element.querySelectorAll('th')].map(el => {
        const rect = el.getBoundingClientRect();
        return {left:rect.left, right:rect.right};
      });
      const rows = [...element.querySelectorAll('tbody tr')].map(row => {
        const cells = [...row.cells].map(el => {
          const rect = el.getBoundingClientRect();
          return {left:rect.left, right:rect.right, top:rect.top, bottom:rect.bottom};
        });
        const ring = row.querySelector('.node-progress-ring').getBoundingClientRect();
        const link = row.querySelector('[data-open-node]').getBoundingClientRect();
        return {cells, nameX:link.left, ringX:ring.left + ring.width/2, ringY:ring.top + ring.height/2};
      });
      return {headers, rows};
    });
    assert.ok(layout.rows.length >= 2);
    for (const row of layout.rows) {
      assert.ok(Math.abs(row.nameX - layout.rows[0].nameX) < 1, 'parent and child names share a left edge');
      row.cells.forEach((cell, index) => {
        assert.ok(Math.abs(cell.left - layout.headers[index].left) < 1, 'cell aligns with header');
        assert.ok(Math.abs(cell.right - layout.headers[index].right) < 1, 'column width is stable');
      });
      assert.ok(Math.abs(row.ringX - (row.cells[2].left + row.cells[2].right)/2) < 1);
      assert.ok(Math.abs(row.ringY - (row.cells[2].top + row.cells[2].bottom)/2) < 1);
    }
  };
  try {
    const response = await context.request.get(new URL(`/api/snapshot?project=${config.otherProject}`, config.url).toString(), {
      headers:{'X-Verif-Token':config.token},
    });
    assert.equal(response.ok(), true);
    const snapshot = await response.json();
    const nodes = snapshot.workstreams.find(w => w.workstream === 'VDOC').nodes;
    const plan = nodes.find(n => n.plan_review);
    const delivery = nodes.find(n => n.delivery_review);
    await page.goto(url.toString());
    await table.locator('.node-progress-ring').first().waitFor();
    assert.deepEqual(await table.locator('th').allTextContents(), ['节点名称','节点类型','进度','状态 / 操作']);
    assert.equal(await table.locator('tbody tr').count(), 2);
    assert.equal(await table.locator('.node-progress-bar').count(), 0);
    const planRow = table.locator('tr').filter({has:page.locator(`[data-open-node="${plan.id}"]`)});
    const bodyRow = table.locator('tr').filter({has:page.locator(`[data-open-node="${delivery.id}"]`)});
    const docLabel = await bodyRow.locator('.work-node-document').textContent();
    assert.equal(delivery.document_key, 'verification-plan');
    assert.ok(docLabel.includes('验证总计划'));
    assert.ok(docLabel.includes(delivery.document.path.split('/').pop()));
    assert.equal(await bodyRow.getByRole('progressbar').getAttribute('aria-valuenow'), '0');
    assert.equal(await bodyRow.getByRole('progressbar').textContent(), '0%');
    assert.equal(await planRow.getByRole('progressbar').textContent(), '100%');
    assert.equal(await planRow.locator('[data-approve-plan-node]').isDisabled(), true);
    assert.equal(await planRow.locator('.node-progress-ring').evaluate(el => getComputedStyle(el).animationName), 'none');
    assert.equal(await bodyRow.locator('.node-progress-ring').evaluate(el => getComputedStyle(el).animationName), 'progress-breathe');
    assert.ok(await bodyRow.getByRole('progressbar').getAttribute('title'));
    await checkAlignment();
    await capture('node-list-dark');

    // The labelled node still resolves to the same authorized Markdown body.
    const bodyRequest = page.waitForResponse(r => r.url().includes('/api/document?'));
    await bodyRow.locator('[data-open-node]').click();
    assert.equal((await bodyRequest).ok(), true);
    await page.locator('#drawer .markdown-body').waitFor();
    assert.equal(new URL(page.url()).searchParams.get('node'), delivery.id);
    assert.equal(new URL(page.url()).searchParams.get('project'), config.otherProject);
    await page.locator('#close-drawer').click();
    await page.locator('#drawer-backdrop').waitFor({state:'hidden'});

    const toggle = table.locator(`[data-toggle-node="${plan.id}"]`);
    await toggle.click();
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
    assert.equal(await table.locator('tbody tr').count(), 1);
    await page.locator('#search').fill(delivery.document.path.split('/').pop());
    assert.equal(await table.locator('tbody tr').count(), 1);
    assert.equal(await table.locator('[data-open-node]').getAttribute('data-open-node'), delivery.id);
    await page.locator('#search').fill('');
    await toggle.click();
    assert.equal(await table.locator('tbody tr').count(), 2);
    await checkAlignment();

    await page.emulateMedia({reducedMotion:'reduce'});
    assert.equal(await bodyRow.locator('.node-progress-ring').evaluate(el => getComputedStyle(el).animationName), 'none');
    assert.equal(await bodyRow.getByRole('progressbar').textContent(), '0%');
    await page.locator('#theme').click();
    await checkAlignment();
    await capture('node-list-light');

    // Long labels wrap within fixed columns instead of shifting status/progress.
    await bodyRow.locator('.work-node-copy [data-open-node]').evaluate(el => {
      el.textContent += '：跨时钟域复位和接口背压场景的正文内容验收'.repeat(3);
    });
    await bodyRow.locator('.work-node-document').evaluate(el => {
      el.textContent += ' / very_long_document_name_without_breaks'.repeat(4);
    });
    await checkAlignment();
    await capture('node-list-long-labels');
    await page.reload();
    await table.locator('.node-progress-ring').first().waitFor();
    await page.setViewportSize({width:390, height:844});
    await checkAlignment();
    const overflow = await table.evaluate(el => ({
      wrapper:el.parentElement.clientWidth, table:el.getBoundingClientRect().width,
      scrollable:getComputedStyle(el.parentElement).overflowX,
      page:document.documentElement.scrollWidth, viewport:innerWidth,
    }));
    assert.ok(overflow.table > overflow.wrapper);
    assert.equal(overflow.scrollable, 'auto');
    assert.ok(overflow.page <= overflow.viewport + 1, 'only the table scrolls horizontally');
    await capture('node-list-mobile');
    assert.deepEqual(errors, []);
    console.log('Dashboard node list: alignment, document labels, rings, motion, responsive layout and node routes PASS');
  } finally {
    await context.close();
    await browser.close();
  }
})().catch(error => {console.error(error); process.exit(1);});
