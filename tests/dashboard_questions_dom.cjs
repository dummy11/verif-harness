// Real shipped page and HTTP requests; no browser layout claims from this DOM test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM, VirtualConsole} = require('jsdom');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
const errors = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', error => errors.push(String(error)));
let dom;
const waitFor = async predicate => {
  const deadline = Date.now() + 10000;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error('Timed out waiting for page state: ' + predicate + '\n' + errors.join('\n'));
    await new Promise(resolve => setTimeout(resolve, 20));
  }
};
const load = async url => {
  dom?.window.close();
  dom = await JSDOM.fromURL(url, {
    resources:'usable', runScripts:'dangerously', pretendToBeVisual:true, virtualConsole,
    beforeParse(window) {
      window.fetch = (path, options) => fetch(new URL(path, window.location.href), options);
      window.AbortController = AbortController;
      window.EventSource = class {addEventListener() {} close() {}};
      window.scrollTo = () => {};
      window.HTMLElement.prototype.scrollIntoView = () => {};
      window.confirm = () => true;
    },
  });
};
const $ = selector => dom.window.document.querySelector(selector);
const $$ = selector => [...dom.window.document.querySelectorAll(selector)];

(async () => {
  const url = new URL(config.url);
  for (const [key, value] of Object.entries({project:config.project,token:config.token,workstream:'VENV',node:config.node})) url.searchParams.set(key, value);
  try {
    await load(url.toString());
    await waitFor(() => $$('.agent-question-notice').length === 2);
    const notice = $$('.agent-question-notice').find(el => el.querySelector(`[data-agent-question="${config.question}"]`));
    assert.equal(notice.querySelector('.agent-question-title').textContent, '请确认接口检查范围');
    assert.equal(notice.querySelector('[data-agent-question]').textContent, '查看并回答');
    assert.equal(notice.querySelector('details').open, false);
    notice.querySelector('summary').click();
    assert.equal(notice.querySelector('details').open, true);
    assert.equal(notice.querySelector('.agent-message').textContent.trim(), config.prompt);
    assert.equal(dom.window.getComputedStyle(notice.querySelector('.agent-message')).fontWeight, '400');
    assert.equal(notice.querySelector('[data-agent-question]').textContent.includes(config.prompt), false);
    notice.querySelector('[data-agent-question]').click();
    await waitFor(() => $(`[data-agent-question-form="${config.question}"]`));
    for (const [key, value] of Object.entries({project:config.project,token:config.token,'agent-question':config.question})) assert.equal(new URL(dom.window.location.href).searchParams.get(key), value);
    await load(dom.window.location.href);
    await waitFor(() => $(`[data-agent-question-form="${config.question}"]`));
    const form = $(`[data-agent-question-form="${config.question}"]`);
    const card = form.closest('.agent-question-card');
    assert.equal(card.querySelector('h3').textContent, '请确认接口检查范围');
    const background = card.querySelector('.agent-question-context');
    assert.equal(background.open, false);
    background.querySelector('summary').click();
    assert.equal(background.open, true);
    assert.equal(background.querySelectorAll('h4').length, 2);
    assert.equal(background.querySelectorAll('li').length, 2);
    assert.equal(background.querySelector('pre code').textContent, 'echo "<fixture>"\n');
    assert.equal(card.querySelectorAll('img,script,iframe').length, 0);
    assert.equal(dom.window.questionInjected, undefined);
    assert.equal(form.querySelectorAll('.agent-option-description li').length, 2);
    form.querySelector('[name="option"][value="current"]').click();
    form.querySelector('[name="reviewer"]').value = 'fixture-owner';
    form.dispatchEvent(new dom.window.Event('submit', {bubbles:true,cancelable:true}));
    await waitFor(() => !$(`[data-agent-question-form="${config.question}"]`));
    await load(dom.window.location.href);
    await waitFor(() => $(`[data-agent-question-form="${config.second}"]`));
    assert.equal($$('.agent-event.question').length, 1);
    const history = $('.agent-event.question .agent-question-details');
    history.querySelector('summary').click();
    assert.equal(history.querySelector('.agent-message').textContent.trim(), config.prompt);
    const invalid = new URL(dom.window.location.href);
    invalid.searchParams.set('agent-question', 'question:missing');
    await load(invalid.toString());
    await waitFor(() => $('#main').textContent.includes('当前项目中找不到这个 Agent 问题。'));
    assert.equal($$('[data-agent-question-form]').length, 0);
    assert.deepEqual(errors, []);
    console.log('Question DOM clicks, HTTP writes, safe formatting and unchanged source PASS');
  } finally {
    dom?.window.close();
  }
})().catch(error => {console.error(error); process.exit(1);});
