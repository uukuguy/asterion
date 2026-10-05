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

function launch(snapshot = fixture(), { liveConfig = null, fetch = null } = {}) {
  const errors = [], requests = [], paints = [], outlines = [], pointers = [], timers = new Map();
  const substitutions = {
    __CONSOLE_CSP__: '', __CONSOLE_CSS__: fs.readFileSync(path.join(assets, 'styles.css'), 'utf8'),
    __CONSOLE_DATA__: JSON.stringify(snapshot).replace(/</g, '\\u003c'),
    __CONSOLE_CONFIG__: JSON.stringify(liveConfig).replace(/</g, '\\u003c'),
    __CONSOLE_JS__: fs.readFileSync(path.join(assets, 'app.js'), 'utf8'),
  };
  const html = fs.readFileSync(path.join(assets, 'index.html'), 'utf8')
    .replace(/__CONSOLE_(CSP|CSS|DATA|CONFIG|JS)__/g, (marker) => substitutions[marker]);
  const vc = new VirtualConsole();
  vc.on('jsdomError', (error) => errors.push(error));
  class NoNetwork extends ResourceLoader { fetch(url) { requests.push(url); return null; } }
  const dom = new JSDOM(html, { url: 'http://localhost:8765/', runScripts: 'dangerously', resources: new NoNetwork(), virtualConsole: vc,
    beforeParse(window) {
      window.HTMLCanvasElement.prototype.getContext = function () {
        return { fillRect() { paints.push(this.fillStyle); }, strokeRect() { outlines.push(this.strokeStyle); }, beginPath() {}, arc() { pointers.push(this.strokeStyle); }, stroke() {} };
      };
      window.fetch = async (url, options = {}) => { requests.push({ url, options }); if (!fetch) throw new Error('unexpected network'); return fetch(url, options); };
      window.matchMedia = () => ({ matches: true, addEventListener() {} });
      let next = 0;
      window.setInterval = (fn) => { timers.set(++next, fn); return next; };
      window.clearInterval = (id) => timers.delete(id);
    } });
  const $ = (id) => dom.window.document.getElementById(id);
  return { dom, $, errors, requests, paints, outlines, pointers, tick: () => [...timers.values()].forEach((fn) => fn()), timers };
}

test('replay markers are opt-in and the legend follows visible game colors', () => {
  const snapshot = fixture(); snapshot.levels[0].actions[0].data = { x: 2, y: 3 };
  const app = launch(snapshot); const { dom, $, outlines, pointers } = app;
  const change = (id, checked) => {
    $(id).checked = checked; $(id).dispatchEvent(new dom.window.Event('change'));
  };
  const legendIds = () => [...$('palette-colors').children].map((item) => item.dataset.color);
  assert.equal($('diff-toggle').checked, false);
  assert.equal($('highlight-toggle').checked, false);
  assert.equal($('overlay-note').hidden, true);
  assert.deepEqual(legendIds(), ['12']);
  assert.match($('palette-colors').textContent, /橙色（12）/);
  assert.equal($('palette-colors').querySelector('.palette-swatch').style.backgroundColor, 'rgb(255, 133, 27)');
  $('next-action').click();
  assert.deepEqual(outlines, []);
  assert.deepEqual(pointers, []);
  assert.deepEqual(legendIds(), ['9']);
  assert.match($('palette-colors').textContent, /蓝色（9）/);
  change('diff-toggle', true);
  assert.equal(outlines.length, 4096);
  assert.equal(outlines[0], '#FFD84D');
  assert.match($('overlay-note').textContent, /黄色方框为回放标记，不属于游戏画面/);
  assert.equal($('overlay-note').hidden, false);
  assert.match($('board-canvas').getAttribute('aria-label'), /不属于游戏画面/);
  change('diff-toggle', false);
  change('highlight-toggle', true);
  assert.equal(pointers.length, 1);
  assert.match($('overlay-note').textContent, /圆圈为点击位置回放标记/);
  change('highlight-toggle', false);
  assert.equal($('overlay-note').hidden, true);
  change('compare-toggle', true);
  assert.deepEqual(legendIds(), ['9', '12']);
  $('level-2').click();
  assert.equal($('palette-legend').hidden, true);
  assert.deepEqual(legendIds(), []);
  assert.deepEqual(app.errors, []);
  dom.window.close();
});

test('action frame measurements remain separate from unavailable P7 conclusions', () => {
  const snapshot = fixture();
  snapshot.levels[0].actions[0].visual_observations = ['蓝色（9）连通块向右移动 4 格。', '<b>原样测量文本</b>'];
  const app = launch(snapshot); const { dom, $ } = app;
  assert.match($('panel-actions').textContent, /画面对比（自动测量）/);
  assert.match($('panel-actions').textContent, /f0 → f2 · 起始帧到结算帧/);
  assert.match($('panel-actions').textContent, /蓝色（9）连通块向右移动 4 格。/);
  assert.match($('panel-actions').textContent, /P7 认知结论：该动作未保存可关联的分析记录。/);
  assert.equal($('current-action-evidence').hidden, true);
  $('next-action').click();
  assert.equal($('current-action-evidence').hidden, false);
  assert.match($('current-action-evidence').textContent, /蓝色（9）连通块向右移动 4 格。/);
  assert.match($('current-action-evidence').textContent, /f0 → f2/);
  assert.match($('current-action-evidence').textContent, /<b>原样测量文本<\/b>/);
  assert.equal($('current-action-evidence').querySelector('b'), null);
  assert.deepEqual(app.errors, []);
  dom.window.close();
});

test('read-only action panel follows frame availability and preserves final meaning statuses', () => {
  const snapshot = fixture();
  const level = snapshot.levels[0];
  level.frames[0].available_actions = ['ACTION1', 'ACTION4', 'ACTION5'];
  level.frames[1].available_actions = ['ACTION1', 'ACTION4'];
  level.frames[2].available_actions = ['ACTION1', 'ACTION5'];
  level.cognition.action_meanings = {
    ACTION1: [{ status: 'certain', claim: 'ACTION1使画面物件向上移动。' }],
    ACTION4: [{ status: 'undetermined', claim: 'ACTION4可能向右移动。' }, { status: 'falsified', claim: '不会直接完成关卡。' }],
  };
  const app = launch(snapshot); const { dom, $ } = app;
  const availableNames = () => [...$('available-actions').querySelectorAll('[data-available-action]')].map((card) => card.dataset.availableAction);
  const highlighted = () => dom.window.document.querySelectorAll('.available-action[aria-current="true"]');
  assert.deepEqual(availableNames(), ['ACTION1', 'ACTION4', 'ACTION5']);
  assert.equal(highlighted().length, 0);
  assert.match($('available-actions').textContent, /ACTION1上移已识别/);
  assert.match($('available-actions').textContent, /ACTION4右移推测/);
  assert.match($('available-actions').textContent, /ACTION5未识别\?/);
  assert.equal($('available-actions').querySelectorAll('button').length, 3);
  assert.equal($('available-actions').querySelector('p, details'), null);
  assert.equal($('available-actions').querySelector('[data-available-action="ACTION1"]').disabled, true);
  assert.equal($('available-actions').querySelector('[data-available-action="ACTION4"]').disabled, false);
  assert.match(dom.window.document.querySelector('.available-actions-note').textContent, /点击定位已录动作/);
  assert.match($('panel-cognition').textContent, /含义来自最终认知，未与历史帧对齐/);
  assert.match($('panel-cognition').textContent, /已否定不会直接完成关卡/);
  $('next-frame').click();
  assert.deepEqual(availableNames(), ['ACTION1', 'ACTION4']);
  assert.equal(highlighted().length, 1);
  assert.equal(highlighted()[0].dataset.availableAction, 'ACTION4');
  assert.match(highlighted()[0].parentElement.textContent, /当前动作/);
  assert.equal($('unavailable-current-action').hidden, true);
  $('next-frame').click();
  assert.deepEqual(availableNames(), ['ACTION1', 'ACTION5']);
  assert.equal(highlighted().length, 1);
  assert.equal($('unavailable-current-action').hidden, false);
  assert.match($('unavailable-current-action').textContent, /已执行／当前不可用/);
  assert.equal($('unavailable-current-action').querySelector('button').disabled, true);
  $('level-2').click();
  assert.deepEqual(availableNames(), []);
  assert.match($('available-actions').textContent, /未记录可用动作/);
  assert.equal(highlighted().length, 0);
  assert.equal($('unavailable-current-action').hidden, true);
  assert.deepEqual(app.errors, []);
  dom.window.close();
});

test('action panel does not invent availability or use cognition without final scope', () => {
  const snapshot = fixture();
  snapshot.levels[0].frames[0].available_actions = ['ACTION4'];
  snapshot.levels[0].cognition = { scope: 'unavailable', action_meanings: { ACTION4: [{ status: 'certain', claim: '不得展示的记录。' }] } };
  const app = launch(snapshot);
  assert.match(app.$('available-actions').textContent, /ACTION4未识别\?/);
  assert.doesNotMatch(app.$('available-actions').textContent, /不得展示/);
  app.$('next-frame').click();
  assert.match(app.$('available-actions').textContent, /未记录可用动作/);
  assert.match(app.$('unavailable-current-action').textContent, /已执行／可用性未记录/);
  assert.deepEqual(app.errors, []);
  app.dom.window.close();
});

test('compact keys leave full original and conflicting claims in the cognition tab', () => {
  const snapshot = fixture();
  snapshot.levels[0].frames[0].available_actions = ['ACTION4'];
  const entries = [
    { status: 'undetermined', claim: 'ACTION4可能向右移动。' },
    { status: 'falsified', claim: 'ACTION4向左移动。' },
    { status: 'certain', claim: 'ACTION4使蓝色物件向右移动四格。' },
    { status: 'certain', claim: '在这个位置，ACTION4向右移动。' },
  ];
  snapshot.levels[0].cognition.action_meanings = { ACTION4: entries };
  const app = launch(snapshot);
  const card = app.$('available-actions').querySelector('[data-available-action="ACTION4"]');
  assert.equal(card.textContent, 'ACTION4右移已识别');
  assert.equal(card.querySelector('p, details'), null);
  const details = app.$('panel-cognition').querySelector('[data-meaning-action="ACTION4"] details');
  assert.equal(details.open, false);
  assert.equal(details.querySelector('summary').textContent, '认知依据（4）');
  assert.equal(details.querySelectorAll('.claim-list li').length, entries.length);
  entries.forEach((entry) => assert.ok(details.textContent.includes(entry.claim)));
  assert.equal(app.$('available-actions').querySelector('.is-current'), null);
  assert.deepEqual(app.errors, []);
  app.dom.window.close();
});

test('compact action keys seek recorded actions, wrap, pause, and keep unsupported meanings unknown', () => {
  const snapshot = fixture(); const level = snapshot.levels[0];
  level.frames.forEach((frame) => { frame.available_actions = ['ACTION4', 'ACTION5', 'ACTION6', 'ACTION7']; });
  level.actions = [
    { id: 'a1', name: 'ACTION4', before_frame: 'f0', after_frame: 'f1', data: {} },
    { id: 'a2', name: 'ACTION4', before_frame: 'f1', after_frame: 'f2', data: {} },
  ];
  level.cognition.action_meanings = {
    ACTION4: [{ status: 'certain', claim: 'ACTION4使对象向右移动。' }],
    ACTION5: [{ status: 'falsified', claim: 'ACTION5向上移动。' }],
    ACTION6: [{ status: 'certain', claim: 'ACTION6不会向左移动。' }],
    ACTION7: [{ status: 'certain', claim: 'ACTION7向左移动。' }, { status: 'undetermined', claim: 'ACTION7可能向右移动。' }],
  };
  const app = launch(snapshot); const { dom, $ } = app;
  const key = (name) => $('available-actions').querySelector(`[data-available-action="${name}"]`);
  ['ACTION5', 'ACTION6', 'ACTION7'].forEach((name) => {
    assert.equal(key(name).textContent, `${name}未识别?`);
    assert.equal(key(name).disabled, true);
  });
  $('play-toggle').click(); assert.equal(app.timers.size, 1);
  key('ACTION4').click(); assert.equal($('frame-counter').textContent, '2 / 3');
  assert.equal(app.timers.size, 0);
  key('ACTION4').click(); assert.equal($('frame-counter').textContent, '3 / 3');
  key('ACTION4').click(); assert.equal($('frame-counter').textContent, '2 / 3');
  assert.deepEqual(app.requests, []); assert.deepEqual(app.errors, []);
  dom.window.close();
});

test('compact directional labels support Chinese neighbors and explicit movement abbreviations', () => {
  for (const [claim, expected] of [
    ['当前位置ACTION4使蓝色（9）横条向右移动四格。', '右移已识别'],
    ['ACTION4在空地将横条右移四格。', '右移已识别'],
    ['ACTION4在空地无法右移四格。', '未识别?'],
    ['CUSTOM_ACTION4使横条右移四格。', '未识别?'],
  ]) {
    const snapshot = fixture();
    snapshot.levels[0].frames[0].available_actions = ['ACTION4'];
    snapshot.levels[0].cognition.action_meanings = { ACTION4: [{ status: 'certain', claim }] };
    const app = launch(snapshot);
    assert.equal(app.$('available-actions').querySelector('button').textContent, `ACTION4${expected}`, claim);
    assert.deepEqual(app.errors, []);
    app.dom.window.close();
  }
});

test('explicit directional denials constrain compact meanings without reversing falsified negatives', () => {
  for (const [entries, expected] of [
    [[{ status: 'certain', claim: 'ACTION4向右移动。' }, { status: 'certain', claim: 'ACTION4不会向右移动。' }], '未识别?'],
    [[{ status: 'certain', claim: 'ACTION4右移。' }, { status: 'certain', claim: 'ACTION4无法右移。' }], '未识别?'],
    [[{ status: 'certain', claim: 'ACTION4向右移动。' }, { status: 'undetermined', claim: 'ACTION4可能不会向右移动。' }], '未识别?'],
    [[{ status: 'falsified', claim: 'ACTION4不会向右移动。' }], '未识别?'],
    [[{ status: 'certain', claim: 'ACTION4向右移动。' }, { status: 'certain', claim: 'ACTION4不会向左移动。' }], '右移已识别'],
  ]) {
    const snapshot = fixture();
    snapshot.levels[0].frames[0].available_actions = ['ACTION4'];
    snapshot.levels[0].cognition.action_meanings = { ACTION4: entries };
    const app = launch(snapshot);
    assert.equal(app.$('available-actions').querySelector('button').textContent, `ACTION4${expected}`, JSON.stringify(entries));
    assert.deepEqual(app.errors, []);
    app.dom.window.close();
  }
});

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

const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const liveConfig = { token: 'test-token', games: [{ game_id: 'sp80-test', alias: 'SP80', win_levels: 3 }, { game_id: 'ls20-test', alias: 'LS20', win_levels: 7 }] };
const view = (snapshot = fixture(), state = 'running') => ({ session_id: 'session-1', state, game_id: snapshot.run.game_id, run_id: snapshot.run.run_id, cleanup_confirmed: false, snapshot, revision: 1 });
const response = (value, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => value });

test('live initialization polls without starting, start uses exact game, retry preserves command identity, stop owns session', async () => {
  let current = view(fixture(), 'idle'), rejectStart = true;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/state') return response(current);
    if (url === '/api/runs') return response({ runs: [] });
    if (url === '/api/start') { if (rejectStart) { rejectStart = false; throw new Error('private-error'); } current = view(); return response(current, 202); }
    if (url === '/api/stop') { current = view(fixture(), 'stopping'); return response(current, 202); }
    throw new Error('unexpected route');
  } });
  await settle();
  assert.equal(app.$('console-mode').value, 'live');
  assert.equal(app.requests.filter((request) => request.options.method === 'POST').length, 0);
  app.$('game-select').value = 'ls20-test'; app.$('run-start').click(); await settle();
  assert.match(app.$('service-status').textContent, /连接中断/);
  assert.equal(app.$('retry-command').hidden, false);
  app.$('retry-command').click(); await settle();
  const starts = app.requests.filter((request) => request.url === '/api/start');
  assert.equal(starts.length, 2);
  assert.deepEqual(JSON.parse(starts[0].options.body), JSON.parse(starts[1].options.body));
  assert.equal(JSON.parse(starts[0].options.body).game_id, 'ls20-test');
  assert.equal(starts[0].options.headers['X-P7-Console-Token'], 'test-token');
  assert.equal(starts[0].options.headers['Content-Type'], 'application/json');
  app.$('run-stop').click(); await settle();
  const stop = app.requests.find((request) => request.url === '/api/stop');
  assert.equal(JSON.parse(stop.options.body).session_id, 'session-1');
  assert.match(app.$('service-status').textContent, /结束中/);
  assert.match(app.$('manual-note').textContent, /尚未实现/);
  assert.deepEqual(app.errors, []); app.dom.window.close();
});

test('live replacement follows newest frame; replay preserves historical selection and animation never stops solver', async () => {
  let current = view(), revision = 1;
  const app = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [{run_id:'old-run',game_id:'sp80-test'}] } : url === '/api/replay/old-run' ? {...fixture(), run: {...fixture().run, run_id:'old-run'}} : current) });
  await settle(); assert.equal(app.$('frame-counter').textContent, '3 / 3');
  const next = fixture(); next.levels[0].frames.push({ id: 'f3', grid: [[14]], state: 'NOT_FINISHED', levels_completed: 0, available_actions: ['ACTION4'] });
  current = {...view(next), revision: ++revision}; app.tick(); await settle();
  assert.equal(app.$('frame-counter').textContent, '4 / 4');
  assert.equal(app.paints.at(-1), '#4FCC30');
  assert.equal(app.$('available-actions').querySelector('button').disabled, true);
  app.$('console-mode').value = 'replay'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change'));
  app.$('frame-slider').value = '1'; app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
  current = {...view(next), revision: ++revision}; app.tick(); await settle();
  assert.equal(app.$('frame-counter').textContent, '2 / 4');
  app.$('play-toggle').click(); app.$('play-toggle').click();
  assert.equal(app.requests.some((request) => request.url === '/api/stop'), false);
  assert.equal(app.$('replay-run').options.length, 1);
  app.$('replay-load').click(); await settle();
  assert.ok(app.requests.some((request) => request.url === '/api/replay/old-run'));
  assert.equal(app.$('run-id').textContent, 'old-run');
  current = {...view(next), revision: ++revision}; app.tick(); await settle();
  assert.equal(app.$('run-id').textContent, 'old-run');
  assert.deepEqual(app.errors, []); app.dom.window.close();
});

test('disconnected or malformed live state retains frame and shows public safe status', async () => {
  let result = view();
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/runs') return response({runs:[]});
    if (result instanceof Error) throw result;
    return response(result);
  } });
  await settle(); const original = app.$('frame-caption').textContent;
  result = new Error('/private/secret'); app.tick(); await settle();
  assert.equal(app.$('frame-caption').textContent, original);
  assert.match(app.$('service-status').textContent, /连接中断/);
  result = { ...view(), snapshot: { schema: 'asterion.arc-agi3-p7-console/v1', levels: 'private-malformed' } };
  app.tick(); await settle();
  assert.equal(app.$('frame-caption').textContent, original);
  assert.match(app.$('service-status').textContent, /响应无效/);
  assert.doesNotMatch(app.$('service-status').textContent, /private|secret/);
  assert.deepEqual(app.errors, []); app.dom.window.close();
});

test('cognition timeline follows source frames and explicit decisions expose goal, basis, expected and actual result', () => {
  const snapshot = fixture(); const level = snapshot.levels[0];
  level.cognition_timeline = [
    { scope: 'observation', cognition_revision: 1, source_action_sequence: 0, observation_sha256: 'h0', frame_id: 'f0', action_id: null, stable_description: '游戏类型：初始观察认知。\n画面物件：蓝色物件。\n动作操作：观察按键。', cognition_narrative_zh: '初始证据', session: {state:'active',episode:1,episode_actions:0} },
    { scope: 'observation', cognition_revision: 2, source_action_sequence: 1, observation_sha256: 'h1', frame_id: 'f2', action_id:'a1', stable_description: '游戏类型：动作后认知。', cognition_narrative_zh: '移动后更新', session: {state:'active',episode:1,episode_actions:1} },
  ];
  level.decisions = [{ id:'p1',source:'p7_decision',goal:'移到出口',basis:'出口位于右方',expected:'向右一格',action_ids:['a1'],source_action_sequence:0 }];
  level.actions[0].decision_id = 'p1';
  const app = launch(snapshot);
  assert.match(app.$('world-guide').textContent, /初始观察认知/);
  assert.equal(app.$('world-guide').querySelector('.guide-section p').textContent, '初始观察认知。');
  assert.match(app.$('world-guide').textContent, /画面物件蓝色物件/);
  assert.match(app.$('world-guide').textContent, /动作操作观察按键/);
  assert.doesNotMatch(app.$('world-guide').textContent, /动作后认知/);
  assert.equal(app.$('panel-decisions').querySelector('h3').textContent, 'P7 决策 1');
  assert.match(app.$('panel-decisions').textContent, /目标：移到出口/);
  assert.match(app.$('panel-decisions').textContent, /依据：出口位于右方/);
  assert.match(app.$('panel-decisions').textContent, /预期：向右一格/);
  assert.match(app.$('panel-decisions').textContent, /实际结果.*f0 → f2/);
  app.$('next-frame').click();
  assert.match(app.$('world-guide').textContent, /初始观察认知/);
  app.$('next-frame').click();
  assert.match(app.$('world-guide').textContent, /动作后认知/);
  assert.match(app.$('panel-cognition').textContent, /移动后更新/);
  assert.deepEqual(app.errors, []); app.dom.window.close();
});

test('late polling response cannot revert a successful start to an idle session', async () => {
  let releasePoll, hold = false;
  const idle = {...view(fixture(), 'idle'), revision: 0};
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/runs') return response({runs:[]});
    if (url === '/api/start') return response(view(), 202);
    if (hold) return new Promise((resolve) => { releasePoll = () => resolve(response(idle)); });
    return response(idle);
  } });
  await settle(); hold = true; app.tick(); await settle();
  app.$('run-start').click(); await settle();
  assert.match(app.$('service-status').textContent, /运行中/);
  releasePoll(); await settle();
  assert.match(app.$('service-status').textContent, /运行中/);
  assert.equal(app.$('run-start').disabled, true);
  assert.deepEqual(app.errors, []); app.dom.window.close();
});

test('new live session with no observation clears previous session frame and cognition', async () => {
  let current = view();
  const app = launch(fixture(), {liveConfig, fetch:async(url)=>response(url==='/api/runs'?{runs:[]}:current)});
  await settle(); assert.equal(app.$('board-empty').hidden,true);
  current={...view(),session_id:'session-2',run_id:'new-run',game_id:'ls20-test',snapshot:null,state:'starting',revision:2};
  app.tick(); await settle();
  assert.equal(app.$('frame-counter').textContent,'0 / 0');
  assert.equal(app.$('board-empty').hidden,false);
  assert.equal(app.$('game-title').textContent,'ls20-test');
  assert.doesNotMatch(app.$('world-guide').textContent,/网格移动游戏/);
  assert.equal(app.$('session-id').textContent,'会话 session-2');
  assert.deepEqual(app.errors,[]); app.dom.window.close();
});

test('late replay response after mode switch cannot replace live frame at an unchanged revision', async () => {
  let releaseReplay;
  const current = view(), replay = {...fixture(), run:{...fixture().run,run_id:'old-run'}};
  const app = launch(fixture(),{liveConfig,fetch:async(url)=>{
    if(url==='/api/runs') return response({runs:[{run_id:'old-run',game_id:'sp80-test'}]});
    if(url==='/api/replay/old-run') return new Promise(resolve=>{releaseReplay=()=>resolve(response(replay));});
    return response(current);
  }});
  try {
    await settle();
    app.$('console-mode').value='replay'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change'));
    app.$('replay-load').click(); await settle();
    app.$('console-mode').value='live'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change'));
    releaseReplay(); await settle(); app.tick(); await settle();
    assert.equal(app.$('run-id').textContent,'test-run');
    assert.equal(app.$('frame-counter').textContent,'3 / 3');
    assert.equal(app.dom.window.__ASTERION_STATE__.run.run_id,'test-run');
    assert.match(app.$('service-status').textContent,/运行中/);
    assert.deepEqual(app.errors,[]);
  } finally { app.dom.window.close(); }
});

test('superseded replay response cannot replace a newer selected run', async () => {
  const releases = {};
  const app = launch(fixture(),{liveConfig,fetch:async(url)=>{
    if(url==='/api/runs') return response({runs:['old-run','new-run'].map(run_id=>({run_id,game_id:'sp80-test'}))});
    if(url.startsWith('/api/replay/')) {
      const run_id=url.split('/').at(-1);
      return new Promise(resolve=>{releases[run_id]=()=>resolve(response({...fixture(),run:{...fixture().run,run_id}}));});
    }
    return response(view());
  }});
  try {
    await settle();
    app.$('console-mode').value='replay'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change'));
    app.$('replay-load').click(); await settle();
    app.$('replay-run').value='new-run'; app.$('replay-run').dispatchEvent(new app.dom.window.Event('change'));
    app.$('replay-load').click(); await settle();
    releases['new-run'](); await settle(); releases['old-run'](); await settle();
    assert.equal(app.$('run-id').textContent,'new-run');
    app.tick(); await settle(); assert.equal(app.$('run-id').textContent,'new-run');
    assert.deepEqual(app.errors,[]);
  } finally { app.dom.window.close(); }
});

const malformedCollections = [
  ['global decisions',snapshot=>{snapshot.decisions=[null];}],
  ['level decisions',snapshot=>{snapshot.levels[0].decisions=[null];}],
  ['cognition timeline',snapshot=>{snapshot.levels[0].cognition_timeline=[null];}],
  ['cognition updates',snapshot=>{snapshot.levels[0].cognition.updates=[null];}],
  ['cognition changes',snapshot=>{snapshot.levels[0].cognition.updates=[{sequence:1,changes:[null]}];}],
  ['action metadata',snapshot=>{snapshot.levels[0].actions[0].trace_sequence={toString:'invalid'};}],
  ['cognition type',snapshot=>{snapshot.levels[0].cognition.updates=[{sequence:1,type:{toString:'invalid'},changes:[]}];}],
];
for (const [name,poison] of malformedCollections) test(`malformed ${name} rejects before committing and a valid same-revision snapshot recovers`, async () => {
  let current=view();
  const app=launch(fixture(),{liveConfig,fetch:async(url)=>response(url==='/api/runs'?{runs:[]}:current)});
  try {
    await settle(); const previous=app.dom.window.__ASTERION_STATE__, previousCaption=app.$('frame-caption').textContent, previousPaintCount=app.paints.length;
    const malformed=fixture(); poison(malformed); current={...view(malformed),revision:2};
    app.tick(); await settle();
    assert.strictEqual(app.dom.window.__ASTERION_STATE__,previous);
    assert.equal(app.$('frame-caption').textContent,previousCaption);
    assert.equal(app.paints.length,previousPaintCount);
    assert.match(app.$('service-status').textContent,/响应无效/);
    const valid=fixture(); valid.levels[0].frames.push({id:'f3',grid:[[14]],state:'NOT_FINISHED'});
    current={...view(valid),revision:2}; app.tick(); await settle();
    assert.equal(app.$('frame-counter').textContent,'4 / 4');
    assert.equal(app.dom.window.__ASTERION_STATE__.levels[0].frames.at(-1).id,'f3');
    assert.match(app.$('service-status').textContent,/运行中/);
    assert.deepEqual(app.errors,[]);
  } finally { app.dom.window.close(); }
});

test('render failure rolls back snapshot and leaves accepted revision available for recovery', async () => {
  let current=view();
  const app=launch(fixture(),{liveConfig,fetch:async(url)=>response(url==='/api/runs'?{runs:[]}:current)});
  try {
    await settle(); const previous=app.dom.window.__ASTERION_STATE__, previousCaption=app.$('frame-caption').textContent;
    const original=app.dom.window.HTMLCanvasElement.prototype.getContext; let fail=true;
    app.dom.window.HTMLCanvasElement.prototype.getContext=function(){if(fail){fail=false;throw new Error('private-render-detail');}return original.call(this);};
    const valid=fixture(); valid.levels[0].frames.push({id:'f3',grid:[[14]],state:'NOT_FINISHED'});
    current={...view(valid),revision:2}; app.tick(); await settle();
    assert.strictEqual(app.dom.window.__ASTERION_STATE__,previous);
    assert.equal(app.$('frame-caption').textContent,previousCaption);
    assert.match(app.$('service-status').textContent,/响应无效/);
    assert.doesNotMatch(app.$('service-status').textContent,/private/);
    app.tick(); await settle();
    assert.equal(app.$('frame-counter').textContent,'4 / 4');
    assert.equal(app.dom.window.__ASTERION_STATE__.levels[0].frames.at(-1).id,'f3');
    assert.deepEqual(app.errors,[]);
  } finally { app.dom.window.close(); }
});
