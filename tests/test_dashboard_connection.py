"""Exercise the Dashboard event-stream connection indicator in isolation."""

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DashboardConnectionTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Dashboard connection checks require Node.js")
    def test_connection_indicator_tracks_event_stream_lifecycle(self) -> None:
        html = (ROOT / "verif_harness/dashboard.html").read_text()
        self.assertIn("@keyframes connection-breathe", html)
        self.assertIn('id="connection-dot" class="dot connecting"', html)
        self.assertIn(
            ".dot.connecting, .dot.syncing { animation: none !important; }",
            html,
        )

        result = subprocess.run(
            ["node", "-", str(ROOT / "verif_harness/dashboard.html")],
            input=r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
(async () => {
const html = fs.readFileSync(process.argv[2], 'utf8');
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(source);
const elements = new Map();
const context = vm.createContext({
  assert, URL, URLSearchParams,
  window: {
    location: {search: '', href: 'http://dashboard.test/'},
    history: {state: {}, replaceState: () => {}},
  },
  localStorage: {getItem: () => '', setItem: () => {}},
  document: {
    querySelector: selector => {
      if (!elements.has(selector)) elements.set(selector, {content: 'test-token', innerHTML: ''});
      return elements.get(selector);
    },
    querySelectorAll: () => [],
  },
});
vm.runInContext(source.slice(0, source.indexOf("    $('#drawer-backdrop').onclick")), context);
vm.runInContext(`
  setConnection('connecting');
  assert.equal(state.connectionState, 'connecting');
  assert.equal(state.connected, false);
  assert.equal($('#connection-dot').className, 'dot connecting');
  assert.equal($('#connection-text').textContent, '连接中');

  setConnection('live');
  assert.equal(state.connectionState, 'live');
  assert.equal(state.connected, true);
  assert.equal($('#connection-dot').className, 'dot live');
  assert.equal($('#connection-text').textContent, '实时连接正常');

  setConnection('syncing');
  assert.equal(state.connectionState, 'syncing');
  assert.equal(state.connected, true);
  assert.equal($('#connection-dot').className, 'dot syncing');
  assert.equal($('#connection-text').textContent, '连接正常 · 状态同步重试中');

  setConnection('offline');
  assert.equal(state.connectionState, 'offline');
  assert.equal(state.connected, false);
  assert.equal($('#connection-dot').className, 'dot offline');
  assert.equal($('#connection-text').textContent, '连接中断 · 显示最后状态');

  const streams = [];
  globalThis.EventSource = class {
    constructor(url) { this.url = url; this.listeners = {}; streams.push(this); }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    close() { this.closed = true; }
  };
  state.project = 'project-1';
  state.snapshot = {version:'unchanged'};
  connectProjectStream('project-1');
  const stream = streams[0];
  assert.equal(state.connectionState, 'connecting');
  assert.match(stream.url, /project=project-1/);

  stream.onopen();
  assert.equal(state.connectionState, 'live');
  assert.equal(state.connected, true);
  stream.listeners['sync-retry']({data:'{}'});
  assert.equal(state.connectionState, 'syncing');
  assert.equal(state.connected, true);
  stream.listeners['sync-restored']({data:'{}'});
  assert.equal(state.connectionState, 'live');
  setSnapshot = snapshot => { state.snapshot = snapshot; };
  stream.listeners.snapshot({data:'{"version":"updated"}'});
  assert.equal(state.snapshot.version, 'updated');
  assert.equal(state.connectionState, 'live');
  stream.onerror();
  assert.equal(state.connectionState, 'offline');
  assert.equal(state.connected, false);

  state.stream = {replacement:true};
  stream.onopen();
  assert.equal(state.connectionState, 'offline');
`, context);

await vm.runInContext(`(async () => {
  state.stream = null;
  state.projects = [{id:'project-2', name:'project-2', dut_top:'dut'}];
  globalThis.fetch = async () => { throw new Error('snapshot unavailable'); };
  await assert.rejects(selectProject('project-2', false), /snapshot unavailable/);
  assert.equal(state.connectionState, 'offline');
  assert.equal(state.connected, false);
})()`, context);
})().catch(error => { console.error(error); process.exitCode = 1; });
""",
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
