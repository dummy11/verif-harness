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
    if (config.phase === 'regression-progress' || config.phase === 'regression-rerun') {
      const incomplete = config.phase === 'regression-progress';
      const summary = await page.locator('.project-status-card').innerText();
      assert.ok(summary.includes('回归基础设施：2/2'));
      assert.ok(summary.includes(incomplete ? '回归结果：尚未形成必需方案' : '回归结果：2/2'));
      await page.locator('[data-nav="overview"]').click();
      const card = page.locator('.ws-card[data-workstream="VREG"]');
      await card.waitFor();
      assert.equal(await card.locator('.ws-meter strong').innerText(), incomplete ? '待完善' : '100%');
      if (incomplete) {
        assert.ok((await card.innerText()).includes('回归结果方案'));
        assert.doesNotMatch(await card.locator('.ws-meter').getAttribute('style'), /--value:100/);
        await page.reload();
        await card.waitFor();
        assert.equal(await card.locator('.ws-meter strong').innerText(), '待完善');
      }
      await card.click();
      await table.waitFor();
      assert.equal(new URL(page.url()).searchParams.get('project'), config.project);
      assert.equal(new URL(page.url()).searchParams.get('workstream'), 'VREG');
      if (incomplete) {
        assert.deepEqual(errors, []);
        console.log('VREG incomplete scope has no overall percentage; navigation and reload PASS');
        return;
      }
    }
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
    if (config.pendingNavigation) {
      const pendingNav = page.locator('[data-nav="pending"]');
      assert.ok(Number(await pendingNav.locator('.nav-count').innerText()) > 0);
      await pendingNav.click();
      await page.locator('.pending-status-card').waitFor();
      assert.equal(new URL(page.url()).searchParams.get('project'), config.project);
      const pendingNode = page.locator(`#main [data-open-node="${config.node}"]`);
      assert.ok((await pendingNode.innerText()).startsWith('验收：'));
      assert.ok((await pendingNode.locator('xpath=ancestor::div[contains(@class,"list-row")]').innerText()).includes('待验收'));
      await pendingNode.click();
    } else {
      await table.locator(`[data-open-node="${config.node}"]`).click();
    }
    await page.locator('#drawer #node-plan-complete').waitFor();
    const expandContent = async () => {
      for (const details of await page.locator('#drawer .node-content-details, #drawer .coverage-delivery-part, #drawer .delivery-summary').all()) {
        if (await details.getAttribute('open') === null) await details.locator(':scope > summary').click();
      }
    };
    await expandContent();
    if (config.expectedRole) {
      assert.ok((await page.locator('#drawer .drawer-head').innerText()).includes(config.expectedRole));
      assert.equal(await page.locator('#drawer').getByText('工作包', {exact:true}).count(), 0);
    }
    if (config.expectedRegressionConfig) {
      const parameters = config.expectedRegressionConfig;
      const range = page.locator('#drawer .regression-config');
      for (const value of [parameters.regression_group,parameters.submit_profile.profile_id,parameters.submit_profile.submit_file,
        ...parameters.cases.map(item => item.case_id)]) assert.ok((await range.innerText()).includes(value));
      assert.ok((await range.innerText()).includes(parameters.seed_mode === 'random' ? '随机 seed' : '指定 seed：' + parameters.seed));
      assert.ok((await range.innerText()).includes(String(parameters.repeat ?? 1)));
      if (config.phase === 'plan') assert.equal(await page.locator('#drawer #regression-rerun').count(), 0);
    }
    if (config.phase === 'regression-rerun') {
      const button = page.locator('#drawer #regression-rerun');
      assert.equal(await button.isEnabled(), true);
      const posts = [];
      page.on('request', request => {
        if (request.method() === 'POST' && request.url().includes('/api/code/regression-rerun')) posts.push(request.postDataJSON());
      });
      await button.click();
      const form = page.locator('#regression-rerun-form');
      await form.waitFor();
      assert.ok((await page.locator('#modal').innerText()).includes('不批准新结果'));
      assert.equal(await form.locator('[name="seed"],[name="seed_mode"],[name="repeat"]').count(), 0);
      await form.locator('[name="reviewer"]').fill('browser-owner');
      await form.locator('[name="reason"]').fill('按当前批准的 FIFO 回归范围重新执行');
      await form.locator('[name="confirm"]').check();
      const saved = page.waitForResponse(response => response.url().includes('/api/code/regression-rerun') && response.request().method() === 'POST');
      await form.evaluate(element => {
        element.dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}));
        element.dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}));
      });
      const response = await saved;
      assert.equal(response.ok(), true);
      const receipt = await response.json();
      assert.equal(receipt.dashboard_project_id, config.project);
      assert.equal(receipt.result.node_id, config.node);
      assert.equal(posts.length, 1);
      for (const field of ['cases','submit_profile','seed','seed_mode','repeat']) assert.ok(!Object.hasOwn(posts[0], field));
      await page.locator('#modal-backdrop').waitFor({state:'hidden'});
      const round = page.locator('#drawer .regression-execution');
      assert.ok((await round.innerText()).includes('第 ' + receipt.result.round.round_number + ' 轮'));
      assert.ok((await round.innerText()).includes('执行请求已登记'));
      assert.equal(await page.locator('#drawer #regression-rerun').isDisabled(), true);
      assert.equal(await page.locator('#drawer #node-plan-complete').isDisabled(), true);
      assert.ok(!(await page.locator('#drawer .drawer-head').innerText()).includes('已验收通过'));
      await page.reload();
      await page.locator('#drawer .regression-execution').waitFor();
      assert.equal(await page.locator('#drawer #regression-rerun').isDisabled(), true);
      assert.equal(await page.locator('#drawer #node-plan-complete').isDisabled(), true);
      await page.locator('#drawer .regression-history summary').click();
      const historicalReport = page.locator('#drawer [data-regression-history-file]').first();
      await historicalReport.click();
      await page.locator('#modal pre').waitFor();
      assert.ok((await page.locator('#modal').innerText()).includes('历史轮次的只读报告'));
      assert.ok((await page.locator('#modal pre').innerText()).includes(config.historyPreviewText || 'schema'));
      await page.locator('#modal [data-close-modal]').click();
      await page.locator('#close-drawer').click();
      assert.ok((await page.locator('.project-status-card').innerText()).includes('回归结果：1/2'));
      await page.locator('[data-nav="overview"]').click();
      const card = page.locator('.ws-card[data-workstream="VREG"]');
      await card.waitFor();
      assert.equal(await card.locator('.ws-meter strong').innerText(), '75%');
      assert.ok((await card.innerText()).includes('第 ' + receipt.result.round.round_number + ' 轮 · 执行请求已登记'));
      await page.reload();
      await card.waitFor();
      assert.equal(await card.locator('.ws-meter strong').innerText(), '75%');
      await card.click();
      await table.waitFor();
      assert.equal(new URL(page.url()).searchParams.get('project'), config.project);
      assert.deepEqual(errors, []);
      console.log('VREG rerun confirmation, one request, authoritative round readback and historical report PASS');
      return;
    }
    const expectedReviewStatus = config.phase === 'plan' ? '等待负责人审批方案'
      : config.phase === 'exclusions' ? '等待 Agent 验证通过' : '等待负责人验收交付';
    const reviewStatus = await page.locator('#drawer .drawer-head').innerText();
    assert.ok(reviewStatus.includes(expectedReviewStatus), reviewStatus);
    if (config.expectedCoverageConfig?.schema === 'CoverageImplementationConfig/1') {
      const coverageConfig = page.locator('#drawer .coverage-implementation-config');
      const text = await coverageConfig.innerText();
      assert.ok(text.includes('Code coverage 对象'));
      assert.ok(text.includes('DUT'));
    } else if (config.expectedCoverageConfig?.schema === 'CoverageCollectionConfig/1') {
      const coverageConfig = page.locator('#drawer .coverage-collection-config');
      const text = await coverageConfig.innerText();
      assert.ok(text.includes('被检查的设计'));
      assert.ok(text.includes(config.expectedCoverageConfig.dut_build_fingerprint.dut_design_id));
      assert.ok(text.includes('使用的回归测试组'));
    }
    if (config.phase === 'exclusions') assert.equal(await page.locator('#drawer #node-plan-complete').isDisabled(), true);
    assert.equal(await page.locator('#drawer .writing-plan-inputs').getAttribute('open'), null);
    assert.doesNotMatch(await page.locator('#drawer .role-node-panel').innerText(), /待确认问题|预计正文交付|方案质量检查/);
    if (config.phase === 'exclusions') {
      await page.locator('#drawer #provide-coverage-exclusions').click();
      const form = page.locator('#coverage-exclusion-form');
      await form.locator('[name="file"]').setInputFiles({name:'browser-owner.el', mimeType:'text/plain', buffer:Buffer.from('exclude C.DEMO.2\n')});
      await form.locator('[name="reviewer"]').fill('browser-owner');
      await form.locator('[name="reason"]').fill('已核对空边界不可达');
      await form.locator('[name="confirm"]').check();
      const saved = page.waitForResponse(r => r.url().includes('/api/code/coverage-exclusions') && r.request().method() === 'POST');
      await form.getByRole('button', {name:'提供并登记审批', exact:true}).click();
      assert.equal((await saved).ok(), true);
      await page.locator('#modal-backdrop').waitFor({state:'hidden'});
      await page.reload();
      // Refresh preserves the node route and reopens its drawer; do not click
      // the obscured workstream row behind that already-open drawer.
      await page.locator('#drawer .coverage-exclusion-card').waitFor({state:'attached'});
      await expandContent();
      assert.ok((await page.locator('#drawer .coverage-exclusion-card').innerText()).includes('文件中的排除范围已由负责人审批'));
      assert.equal(await page.locator('#drawer #node-plan-complete').isDisabled(), true);
      await page.locator('#drawer [data-code-exclusion-file]').click();
      await page.locator('#modal pre').waitFor();
      assert.ok((await page.locator('#modal pre').innerText()).includes('C.DEMO.2'));
      assert.deepEqual(errors, []);
      return;
    }
    if (config.phase === 'plan') {
      const panel = page.locator('#drawer .role-node-panel');
      const headings = ['目标','工作范围','具体工作','实现方式','如何验证','输出','交付条件'];
      if (workstream === 'VCOV' && config.expectedRole === '覆盖率实现方案') {
        assert.equal(config.expectedCoverageScope?.schema, 'CoverageScope/1');
        const shownHeadings = await panel.locator('.node-content-details > summary > h4').allTextContents();
        assert.deepEqual(shownHeadings.filter(title => [...headings,'负责人批准的覆盖范围'].includes(title)), [...headings,'负责人批准的覆盖范围']);
        const coverageHeading = panel.getByRole('heading', {name:'负责人批准的覆盖范围',exact:true});
        const scopeRows = await coverageHeading.locator('xpath=ancestor::details[1]').locator(':scope > .detail-group-body > ul > li').allTextContents();
        assert.ok(scopeRows.some(row => row.includes('Code coverage')));
        assert.ok(scopeRows.some(row => row.includes('Functional coverage')));
      } else {
        const shownHeadings = await panel.locator('.node-content-details > summary > h4').allTextContents();
        assert.deepEqual(shownHeadings.filter(title => headings.includes(title)), headings);
      }
    } else {
      assert.ok((await page.locator('#drawer .role-node-panel').innerText()).includes(config.expectedRole === '覆盖率收敛交付' ? '检查与验收' : '检查结论'));
      if (config.expectedFileHeading) {
        assert.equal(await page.locator('#drawer .role-node-panel').getByRole('heading', {name:config.expectedFileHeading, exact:true}).count(), 1);
        if (config.expectedFileHeading === '交付文件') assert.equal(await page.locator('#drawer .role-node-panel').getByRole('heading', {name:'交付代码', exact:true}).count(), 0);
      }
      const previewPath = config.previewPath || (config.expectedRole === '覆盖率实现交付' && config.previewText === 'fixture_coverage'
        ? 'verification/coverage/model.sv' : null);
      const previewButton = previewPath ? page.locator('#drawer [data-code-file]').filter({hasText:previewPath}).first()
        : page.locator('#drawer [data-code-file]').first();
      if (previewPath) assert.equal(await previewButton.innerText(), previewPath);
      await previewButton.click();
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
    await page.locator('#node-plan-complete-form').waitFor();
    assert.equal(await page.locator('#modal').getAttribute('data-plan-node'), config.node);
    await page.locator('#modal [data-close-modal]').click();
    const approvalList = new URL(page.url());
    for (const key of ['node','node-view']) approvalList.searchParams.delete(key);
    await page.goto(approvalList.toString());
    const listApproval = page.locator(`[data-approve-plan-node="${config.node}"]`);
    await listApproval.waitFor();
    assert.equal(await listApproval.isEnabled(), true);
    await listApproval.click();
    const form = page.locator('#node-plan-complete-form');
    await form.waitFor();
    assert.equal(await page.locator('#modal').getAttribute('data-plan-node'), config.node);
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
    assert.equal(await approved.evaluate(element => getComputedStyle(element).cursor), 'not-allowed');
    if (config.pendingNavigation) {
      await page.locator('[data-nav="pending"]').click();
      await page.locator('.pending-status-card').waitFor();
      assert.equal(await page.locator(`#main [data-open-node="${config.node}"]`).count(), 0);
      await page.locator(`[data-nav-workstream="${workstream}"]`).click();
      await approved.waitFor();
    }
    assert.ok((await approved.locator('xpath=ancestor::tr').innerText()).includes(config.phase === 'plan' ? '方案已批准' : '已验收通过'));
    if (config.phase === 'plan') assert.ok((await table.innerText()).includes('等待 Agent 验证通过'));
    assert.deepEqual(errors, []);
    console.log(workstream + ' ' + config.phase + ' browser routes, preview, approval and reload PASS');
  } finally { await context.close(); await browser.close(); }
})().catch(e => {console.error(e);process.exit(1);});
