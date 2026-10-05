/* Optional DOM integration: NODE_PATH=<jsdom install>/node_modules node --test this-file.
 * Runs the shipped JS, without a browser connection, network, model or game engine.
 * Canvas calls are captured; this does not claim browser pixel/layout verification.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM, ResourceLoader, VirtualConsole } = require('jsdom');
const assets = path.resolve(__dirname, '../src/asterion/applications/prime/p7/console_assets');

function fixture() {
  const grid = (color) => Array.from({ length: 64 }, () => Array(64).fill(color));
  return {
    schema: 'asterion.arc-agi3-p7-console/v1', generated_at: '2026-10-05T00:00:00Z',
    run: { game_id: 'sp80-test', run_id: 'test-run', win_levels: 3,
      completed_level_count: 0, primitive_action_count: 1, status: 'incomplete' },
    levels: [{ level: 1, status: 'incomplete',
      frames: [12, 10, 9].map((color, i) => ({ id: `f${i}`, grid: grid(color), state: 'NOT_FINISHED', levels_completed: 0 })),
      actions: [{ id: 'a1', name: 'ACTION4', before_frame: 'f0', after_frame: 'f2', changed_cells: 4096, data: {}, levels_completed: 0 }],
      decisions: [{ id: 'd1', round_index: 0, prompt_signals: ['application-state'], output_signals: ['plan', 'action'], action_ids: [] }],
      cognition: { scope: 'final', stable_description: '游戏类型：网格移动游戏。\n动作操作：ACTION4 使物件向右移动。\n规划推断：目标尚未确定。', updates: [] } },
      { level: 2, status: 'not-run', frames: [], actions: [], decisions: [], cognition: { scope: 'unavailable' } },
      { level: 3, status: 'not-run', frames: [], actions: [], decisions: [], cognition: { scope: 'unavailable' } }],
    warnings: [],
  };
}

function launch(snapshot = fixture()) {
  const errors = [], requests = [], paints = [], timers = new Map();
  const substitutions = {
    __CONSOLE_CSP__: '', __CONSOLE_CSS__: fs.readFileSync(path.join(assets, 'styles.css'), 'utf8'),
    __CONSOLE_DATA__: JSON.stringify(snapshot).replace(/</g, '\\u003c'),
    __CONSOLE_JS__: fs.readFileSync(path.join(assets, 'app.js'), 'utf8'),
  };
  const html = fs.readFileSync(path.join(assets, 'index.html'), 'utf8')
    .replace(/__CONSOLE_(CSP|CSS|DATA|JS)__/g, (marker) => substitutions[marker]);
  const vc = new VirtualConsole();
  vc.on('jsdomError', (error) => errors.push(error));
  class NoNetwork extends ResourceLoader { fetch(url) { requests.push(url); return null; } }
  const dom = new JSDOM(html, { runScripts: 'dangerously', resources: new NoNetwork(), virtualConsole: vc,
    beforeParse(window) {
      window.HTMLCanvasElement.prototype.getContext = function () {
        return { fillRect() { paints.push(this.fillStyle); }, strokeRect() {}, beginPath() {}, arc() {}, stroke() {} };
      };
      window.matchMedia = () => ({ matches: true, addEventListener() {} });
      let next = 0;
      window.setInterval = (fn) => { timers.set(++next, fn); return next; };
      window.clearInterval = (id) => timers.delete(id);
    } });
  const $ = (id) => dom.window.document.getElementById(id);
  return { dom, $, errors, requests, paints, tick: () => [...timers.values()].forEach((fn) => fn()), timers };
}

test('real assets: slider, animation/action link, tabs, compare, level switch, playback', () => {
  const app = launch(); const { dom, $, errors, requests, paints } = app;
  assert.deepEqual(errors, []);
  assert.deepEqual(requests, []);
  assert.equal(dom.window.document.querySelectorAll('.level-button').length, 3);
  assert.match($('level-2').textContent, /未运行/);
  assert.match($('world-guide').textContent, /网格移动游戏/);
  assert.match($('cognition-scope').textContent, /最终/);
  assert.equal($('frame-counter').textContent, '1 / 3');
  assert.equal(paints[0], '#FF851B');
  $('frame-slider').value = '1'; $('frame-slider').dispatchEvent(new dom.window.Event('input'));
  assert.equal($('current-action').textContent, 'ACTION4'); // intermediate layer belongs to action
  $('next-frame').click();
  assert.equal($('frame-counter').textContent, '3 / 3');
  assert.equal(paints.at(-1), '#1E93FF');
  $('tab-actions').click(); assert.equal($('panel-actions').hidden, false);
  assert.equal($('panel-decisions').hidden, true);
  $('compare-toggle').checked = true; $('compare-toggle').dispatchEvent(new dom.window.Event('change'));
  assert.equal($('comparison-board').hidden, false);
  $('play-toggle').click(); assert.equal($('play-toggle').textContent, '暂停');
  app.tick(); assert.equal($('frame-counter').textContent, '2 / 3');
  app.tick(); assert.equal($('play-toggle').textContent, '播放');
  $('play-toggle').click(); $('level-2').click();
  assert.equal(app.timers.size, 0);
  assert.equal($('board-empty').hidden, false);
  assert.equal($('play-toggle').disabled, true);
  assert.doesNotMatch($('world-guide').textContent, /网格移动游戏/);
  assert.deepEqual(errors, []); dom.window.close();
});

test('unknown/no-data run does not invent game levels or crash', () => {
  const snapshot = fixture(); snapshot.run.win_levels = null; snapshot.levels = [];
  const app = launch(snapshot);
  assert.deepEqual(app.errors, []);
  assert.equal(app.dom.window.document.querySelectorAll('.level-button').length, 0);
  assert.equal(app.$('play-toggle').disabled, true);
  app.dom.window.close();
});

test('evidence remains text and keyboard shortcuts leave form controls alone', () => {
  const snapshot = fixture(); snapshot.run.game_id = '<img src=x onerror="alert(1)">';
  const app = launch(snapshot); const { dom, $ } = app;
  assert.equal($('game-title').textContent, snapshot.run.game_id);
  assert.equal($('game-title').querySelector('img'), null);
  $('frame-slider').dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
  assert.equal($('frame-counter').textContent, '1 / 3');
  dom.window.document.body.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
  assert.equal($('frame-counter').textContent, '2 / 3');
  assert.deepEqual(app.requests, []); assert.deepEqual(app.errors, []);
  dom.window.close();
});

test('exported real HTML loads with zero external resource requests', { skip: !process.env.P7_CONSOLE_HTML }, () => {
  const requests = [], errors = [];
  const vc = new VirtualConsole(); vc.on('jsdomError', (error) => errors.push(error));
  class NoNetwork extends ResourceLoader { fetch(url) { requests.push(url); return null; } }
  const dom = new JSDOM(fs.readFileSync(process.env.P7_CONSOLE_HTML, 'utf8'), {
    runScripts: 'dangerously', resources: new NoNetwork(), virtualConsole: vc,
    beforeParse(window) {
      window.HTMLCanvasElement.prototype.getContext = () => ({ fillRect() {}, strokeRect() {}, beginPath() {}, arc() {}, stroke() {} });
    },
  });
  assert.deepEqual(errors, []);
  assert.deepEqual(requests, []);
  assert.equal(dom.window.__ASTERION_STATE__.schema, 'asterion.arc-agi3-p7-console/v1');
  assert.match(dom.window.document.getElementById('frame-counter').textContent, /\d+ \/ \d+/);
  dom.window.close();
});
