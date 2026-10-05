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
  assert.equal(highlighted()[0].classList.contains('is-current'), true);
  assert.doesNotMatch(highlighted()[0].parentElement.textContent, /当前动作/);
  assert.equal($('current-action'), null);
  assert.equal($('unavailable-current-action').hidden, true);
  $('next-frame').click();
  assert.deepEqual(availableNames(), ['ACTION1', 'ACTION5']);
  assert.equal(highlighted().length, 1);
  assert.equal($('unavailable-current-action').hidden, false);
  assert.equal(highlighted()[0].dataset.availableAction, 'ACTION4');
  assert.match(highlighted()[0].getAttribute('aria-label'), /已执行／当前不可用/);
  assert.doesNotMatch($('unavailable-current-action').textContent, /已执行／当前不可用|当前动作/);
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
  assert.match(app.$('unavailable-current-action').querySelector('button').getAttribute('aria-label'), /已执行／可用性未记录/);
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
  assert.equal($('unavailable-current-action').querySelector('[aria-current="true"]').dataset.availableAction, 'ACTION4'); // intermediate layer belongs to action
  assert.equal($('current-action'), null);
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

const settle = async () => { for (let i = 0; i < 24; i++) await Promise.resolve(); };
const liveConfig = { token: 'test-token', games: [{ game_id: 'sp80-test', alias: 'SP80', win_levels: 3 }, { game_id: 'ls20-test', alias: 'LS20', win_levels: 7 }] };
const view = (snapshot = fixture(), state = 'running') => ({ session_id: 'session-1', state, game_id: snapshot.run.game_id, run_id: snapshot.run.run_id, cleanup_confirmed: false, snapshot, revision: 1 });
const response = (value, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => value });
const idleView = () => ({ session_id: null, state: 'idle', game_id: null, run_id: null, cleanup_confirmed: true, snapshot: null, revision: 0 });
const manualView = (game_id = 'sp80-test', color = 12, version = 0, level = 1) => ({
  session_id: `manual-${game_id}`, game_id, level, state: 'ready', observation_version: version,
  episode_id: 1, action_count: version, last_action: version ? { action: 'ACTION4', data: {}, observation_version: version } : null,
  snapshot: { schema: 'asterion.arc-agi3-p7-console/v1', generated_at: null,
    run: { game_id, run_id: null, status: 'manual', win_levels: game_id === 'ls20-test' ? 7 : 3, completed_level_count: 0, primitive_action_count: version },
    levels: [{ level, status: 'manual', frames: [{ id: `manual-${version}`, grid: [[color, color], [color, color]], available_actions: ['ACTION1', 'ACTION4', 'ACTION6', 'RESET'], state: 'NOT_FINISHED', levels_completed: 0 }], actions: [], decisions: [], cognition: { scope: 'unavailable' } }],
    decisions: [], warnings: [] },
});
const changeGame = (app, game) => { app.$('game-select').value = game; app.$('game-select').dispatchEvent(new app.dom.window.Event('change')); };
const stateWithManual = (manual) => ({ ...idleView(), manual });

test('selected game opens real playable manual session without P7 and idle polls retain it', async () => {
  let manual = null;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/open') { const choice = JSON.parse(options.body); manual = manualView(choice.game_id, choice.game_id === 'ls20-test' ? 9 : 12, 0, choice.level); return response(manual); }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await settle();
    assert.equal(app.$('console-mode').value, 'manual');
    assert.match(app.$('board-title').textContent, /人工试玩/);
    assert.match(app.$('world-guide').textContent, /人工试玩不生成 P7 认知/);
    assert.deepEqual([...app.$('available-actions').querySelectorAll('button')].map((button) => button.dataset.availableAction), ['ACTION1', 'ACTION4', 'ACTION6', 'RESET']);
    assert.ok([...app.$('available-actions').querySelectorAll('button')].every((button) => !button.disabled));
    changeGame(app, 'ls20-test');
    assert.equal(app.$('board-empty').hidden, false);
    assert.equal(app.$('game-title').textContent, 'ls20-test');
    assert.doesNotMatch(app.$('world-guide').textContent, /网格移动游戏/);
    await settle(); app.tick(); await settle();
    assert.equal(app.$('game-title').textContent, 'ls20-test');
    assert.equal(app.$('frame-counter').textContent, '1 / 1');
    assert.equal(app.paints.at(-1), '#1E93FF');
    assert.equal(app.$('run-start').disabled, false);
    app.$('level-2').click();
    assert.equal(app.$('board-empty').hidden, false);
    assert.ok([...app.$('available-actions').querySelectorAll('button')].every((button) => button.disabled));
    await settle();
    const opens = app.requests.filter((entry) => entry.url === '/api/manual/open');
    assert.equal(JSON.parse(opens.at(-1).options.body).level, 2);
    assert.equal(app.$('board-empty').hidden, true);
    assert.equal(app.$('board-kicker').textContent, 'LEVEL 02');
    assert.match(app.$('board-title').textContent, /关卡 2 · 人工试玩/);
    assert.ok([...app.$('available-actions').querySelectorAll('button')].every((button) => !button.disabled));
    assert.equal(app.requests.some((entry) => entry.url === '/api/start'), false);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('startup resumes existing manual game, actual level and observation without opening or resetting it', async () => {
  const manual = manualView('ls20-test', 9, 4, 3);
  const app = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual)) });
  try {
    await settle();
    assert.equal(app.$('console-mode').value, 'manual');
    assert.equal(app.$('game-select').value, 'ls20-test');
    assert.equal(app.$('action-total').textContent, '4');
    assert.equal(app.$('board-kicker').textContent, 'LEVEL 03');
    assert.equal(app.$('level-3').getAttribute('aria-current'), 'true');
    assert.equal(app.$('level-progress').textContent, '0 / 7');
    assert.equal(app.dom.window.__ASTERION_STATE__.levels[0].frames[0].id, 'manual-4');
    assert.equal(app.requests.some((entry) => entry.url === '/api/manual/open'), false);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('fresh server selection restores the saved game and direct level without implying completed levels', async () => {
  const selection = { game_id: 'ls20-test', level: 3 };
  let manual = null;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/open') {
      const body = JSON.parse(options.body); manual = manualView(body.game_id, 9, 0, body.level); return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : { ...stateWithManual(manual), selection });
  } });
  try {
    await settle();
    const opens = app.requests.filter((entry) => entry.url === '/api/manual/open');
    assert.equal(opens.length, 1);
    const body = JSON.parse(opens[0].options.body);
    assert.equal(body.game_id, 'ls20-test'); assert.equal(body.level, 3);
    assert.equal(app.$('game-select').value, 'ls20-test');
    assert.equal(app.$('board-kicker').textContent, 'LEVEL 03');
    assert.equal(app.$('level-progress').textContent, '0 / 7');
    assert.equal(app.$('run-status').textContent, '人工试玩');
    assert.doesNotMatch(app.$('level-list').textContent, /已过关|已成功/);
    assert.match(app.$('level-1').textContent, /可直接试玩/);
    assert.ok([...app.$('available-actions').querySelectorAll('button')].every((button) => !button.disabled));
    app.$('level-3').click(); await settle(); // The actual current observation does not open another engine.
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/open').length, 1);
    app.$('console-mode').value = 'replay'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change'));
    app.$('level-1').click();
    app.$('console-mode').value = 'manual'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change'));
    assert.equal(app.$('board-kicker').textContent, 'LEVEL 03');
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/open').length, 1);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('legacy manual view infers the actual frame level and invalid saved selection falls back to level 1', async () => {
  const legacy = manualView('ls20-test', 9, 2, 3); delete legacy.level;
  const resumed = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [] } : stateWithManual(legacy)) });
  try {
    await settle(); assert.equal(resumed.$('board-kicker').textContent, 'LEVEL 03');
    assert.equal(resumed.requests.some((entry) => entry.url === '/api/manual/open'), false);
    assert.deepEqual(resumed.errors, []);
  } finally { resumed.dom.window.close(); }
  for (const selection of [{ game_id: 'unknown', level: 3 }, { game_id: 'ls20-test', level: 8 }, { game_id: 'ls20-test', level: '3' }, null]) {
    const app = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [] } : url === '/api/manual/open' ? manualView() : { ...idleView(), selection }) });
    try {
      await settle(); const body = JSON.parse(app.requests.find((entry) => entry.url === '/api/manual/open').options.body);
      assert.equal(body.game_id, 'sp80-test'); assert.equal(body.level, 1);
      assert.equal(app.$('board-kicker').textContent, 'LEVEL 01');
      assert.deepEqual(app.errors, []);
    } finally { app.dom.window.close(); }
  }
});

test('direct level opening locks the rail until its exact response and changing game starts at level 1', async () => {
  let manual = manualView(), releaseOpen;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/open') {
      const body = JSON.parse(options.body);
      if (body.level === 3) return new Promise((resolve) => { releaseOpen = resolve; });
      manual = manualView(body.game_id, 9, 0, body.level); return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await settle(); app.$('level-3').click(); await settle();
    const request = app.requests.find((entry) => entry.url === '/api/manual/open');
    assert.equal(JSON.parse(request.options.body).level, 3);
    assert.equal(app.$('board-kicker').textContent, 'LEVEL 03');
    assert.equal(app.$('board-empty').hidden, false);
    assert.ok([...app.dom.window.document.querySelectorAll('.level-button')].every((button) => button.disabled));
    app.$('level-2').dispatchEvent(new app.dom.window.MouseEvent('click', { bubbles: true }));
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/open').length, 1);
    manual = manualView('sp80-test', 9, 0, 3); releaseOpen(response(manual)); await settle();
    assert.equal(app.$('board-empty').hidden, true);
    assert.equal(app.$('level-3').disabled, false);
    assert.equal(app.$('level-progress').textContent, '0 / 3');
    changeGame(app, 'ls20-test'); await settle();
    const next = JSON.parse(app.requests.filter((entry) => entry.url === '/api/manual/open').at(-1).options.body);
    assert.equal(next.game_id, 'ls20-test'); assert.equal(next.level, 1);
    assert.equal(app.$('board-kicker').textContent, 'LEVEL 01');
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('direct level open rejects a different actual level and retry keeps the original choice', async () => {
  let manual = manualView(), wrongLevel = true;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/open') {
      const body = JSON.parse(options.body);
      manual = manualView(body.game_id, 9, 0, wrongLevel ? 1 : body.level); return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await settle(); app.$('level-3').click(); await settle();
    assert.equal(app.$('board-kicker').textContent, 'LEVEL 03');
    assert.equal(app.$('board-empty').hidden, false);
    assert.equal(app.$('retry-command').hidden, false);
    assert.ok([...app.dom.window.document.querySelectorAll('.level-button')].every((button) => button.disabled));
    wrongLevel = false; app.$('retry-command').click(); await settle();
    const requests = app.requests.filter((entry) => entry.url === '/api/manual/open');
    assert.equal(requests.length, 2);
    assert.deepEqual(JSON.parse(requests[0].options.body), JSON.parse(requests[1].options.body));
    assert.equal(app.$('board-kicker').textContent, 'LEVEL 03');
    assert.equal(app.$('board-empty').hidden, true);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('startup with active P7 session never requests manual open', async () => {
  const app = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [] } : view()) });
  try {
    await settle();
    assert.equal(app.$('console-mode').value, 'live');
    assert.equal(app.$('run-id').textContent, 'test-run');
    assert.equal(app.requests.some((entry) => entry.url === '/api/manual/open'), false);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('poll captured before successful manual close cannot reopen the closed observation', async () => {
  let manual = manualView(), hold = false, releasePoll;
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/runs') return response({ runs: [] });
    if (url === '/api/manual/close') { manual = { ...manual, state: 'closed' }; return response(manual); }
    if (hold) { const stale = { ...manual }; return new Promise((resolve) => { releasePoll = () => resolve(response(stateWithManual(stale))); }); }
    return response(stateWithManual(manual));
  } });
  try {
    await settle(); hold = true; app.tick(); await settle();
    app.$('manual-close').click(); await settle(); releasePoll(); await settle();
    assert.match(app.$('service-status').textContent, /试玩已结束/);
    assert.ok([...app.$('available-actions').querySelectorAll('button')].every((button) => button.disabled));
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('manual opening disables selection and active session poll rejects its delayed response', async () => {
  let releaseOpen, current = idleView();
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/manual/open') return new Promise((resolve) => { releaseOpen = resolve; });
    return response(url === '/api/runs' ? { runs: [] } : current);
  } });
  try {
    await settle(); assert.equal(app.$('run-start').disabled, true);
    assert.equal(app.$('game-select').disabled, true);
    assert.ok([...app.dom.window.document.querySelectorAll('.level-button')].every((button) => button.disabled));
    app.$('level-2').dispatchEvent(new app.dom.window.MouseEvent('click', { bubbles: true }));
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/open').length, 1);
    current = view(); app.tick(); await settle(); releaseOpen(response(manualView())); await settle();
    assert.equal(app.$('run-id').textContent, 'test-run');
    assert.equal(app.$('frame-counter').textContent, '3 / 3');
    assert.equal(app.$('console-mode').value, 'live');
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('manual open failure does not prevent independent fresh P7 start', async () => {
  let current = idleView();
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/manual/open') return response({ error: '/private/sentinel' }, 503);
    if (url === '/api/start') { current = view(); return response(current, 202); }
    return response(url === '/api/runs' ? { runs: [] } : current);
  } });
  try {
    await settle(); assert.equal(app.$('run-start').disabled, false);
    assert.equal(app.$('frame-counter').textContent, '0 / 0');
    assert.doesNotMatch(app.$('board-empty').textContent, /private|sentinel/);
    app.$('run-start').click(); await settle();
    assert.equal(app.$('console-mode').value, 'live');
    assert.equal(app.$('run-id').textContent, 'test-run');
    assert.equal(app.$('frame-counter').textContent, '3 / 3');
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('replay rejects pending manual open and returning to manual reopens playable session', async () => {
  const releases = [];
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/manual/open') return new Promise((resolve) => { releases.push(resolve); });
    if (url === '/api/runs') return response({ runs: [{ run_id: 'old-run', game_id: 'sp80-test' }] });
    if (url === '/api/replay/old-run') return response({ ...fixture(), run: { ...fixture().run, run_id: 'old-run' } });
    return response(idleView());
  } });
  try {
    await settle(); app.$('console-mode').value = 'replay'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change'));
    app.$('replay-load').click(); await settle(); releases[0](response(manualView())); await settle();
    assert.equal(app.$('run-id').textContent, 'old-run');
    app.$('console-mode').value = 'manual'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change')); await settle();
    assert.equal(releases.length, 2); releases[1](response(manualView())); await settle(); app.tick(); await settle();
    assert.equal(app.dom.window.__ASTERION_STATE__.run.status, 'manual');
    assert.match(app.$('board-title').textContent, /人工试玩/);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('unchanged manual polls preserve pressed button identity and keyboard focus', async () => {
  const manual = manualView();
  const app = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual)) });
  try {
    await settle();
    const button = app.$('available-actions').querySelector('[data-available-action="ACTION4"]');
    button.focus(); button.dispatchEvent(new app.dom.window.MouseEvent('mousedown', { bubbles: true }));
    app.tick(); await settle();
    assert.equal(app.$('available-actions').querySelector('[data-available-action="ACTION4"]'), button);
    assert.equal(button.isConnected, true);
    assert.equal(app.dom.window.document.activeElement, button);
    button.dispatchEvent(new app.dom.window.MouseEvent('mouseup', { bubbles: true }));
    button.click(); await settle();
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/action').length, 1);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('manual feedback distinguishes pending from acknowledged action and reports actual frame change', async () => {
  let manual = manualView('sp80-test', 12, 1), releaseAction;
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/manual/action') return new Promise((resolve) => { releaseAction = resolve; });
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await settle();
    const button = app.$('available-actions').querySelector('[data-available-action="ACTION1"]');
    button.click(); button.click(); await settle();
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/action').length, 1);
    assert.equal(app.$('available-actions').querySelector('.is-pending'), button);
    assert.equal(button.getAttribute('aria-busy'), 'true');
    assert.equal(app.$('available-actions').querySelector('.is-current').dataset.availableAction, 'ACTION4');
    assert.match(app.$('manual-action-status').textContent, /正在发送.*等待响应/);
    manual = manualView('sp80-test', 9, 2); manual.last_action.action = 'ACTION1';
    releaseAction(response(manual)); await settle();
    assert.equal(app.$('available-actions').querySelector('.is-pending'), null);
    assert.equal(button.hasAttribute('aria-busy'), false);
    assert.equal(app.$('available-actions').querySelector('.is-current'), button);
    assert.match(app.$('manual-action-status').textContent, /已执行.*2.*画面已变化/);
    assert.doesNotMatch(app.$('manual-action-status').textContent, /ACTION/);
    app.tick(); await settle();
    assert.match(app.$('manual-action-status').textContent, /已执行.*2.*画面已变化/);
    button.click(); await settle();
    manual = manualView('sp80-test', 9, 3); manual.last_action.action = 'ACTION1';
    releaseAction(response(manual)); await settle();
    assert.match(app.$('manual-action-status').textContent, /已执行.*3.*画面未变化/);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('manual feedback never reports execution for rejected or unconfirmed responses', async () => {
  for (const outcome of ['disconnected', 'rejected', 'unchanged', 'closed', 'uncertain', 'mismatched', 'later', 'wrong-data']) {
    const manual = manualView();
    const app = launch(fixture(), { liveConfig, fetch: async (url) => {
      if (url === '/api/manual/action') {
        if (outcome === 'disconnected') throw new Error('/private/sentinel');
        if (outcome === 'rejected') return response({ error: '/private/sentinel' }, 409);
        if (outcome === 'mismatched') return response(manualView('sp80-test', 9, 1));
        if (['later', 'wrong-data'].includes(outcome)) {
          const acknowledged = manualView('sp80-test', 9, outcome === 'later' ? 2 : 1);
          acknowledged.last_action.action = 'ACTION1';
          if (outcome === 'wrong-data') acknowledged.last_action.data = { x: 1, y: 0 };
          return response(acknowledged);
        }
        return response({ ...manual, state: ['closed', 'uncertain'].includes(outcome) ? outcome : 'ready' });
      }
      return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
    } });
    try {
      await settle(); app.$('available-actions').querySelector('[data-available-action="ACTION1"]').click(); await settle();
      const feedback = app.$('manual-action-status').textContent;
      assert.doesNotMatch(feedback, /已执行|private|sentinel/, outcome);
      assert.match(feedback, outcome === 'rejected' ? /拒绝/ : outcome === 'closed' ? /结束/ : /未确认/, outcome);
      if (outcome === 'disconnected') { assert.match(feedback, /重试原请求/); assert.equal(app.$('retry-command').hidden, false); }
      if (['unchanged', 'mismatched', 'later', 'wrong-data'].includes(outcome)) {
        assert.ok([...app.$('available-actions').querySelectorAll('button')].every((button) => button.disabled));
        assert.equal(app.$('retry-command').hidden, false);
      }
      assert.deepEqual(app.errors, [], outcome);
    } finally { app.dom.window.close(); }
  }
});

test('manual coordinate acknowledgement checks exact coordinates independently of property order', async () => {
  for (const wrongCoordinate of [false, true]) {
    let manual = manualView();
    const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
      if (url === '/api/manual/action') {
        const body = JSON.parse(options.body); manual = manualView('sp80-test', 9, 1);
        manual.last_action = { action: body.action, observation_version: 1, data: { y: body.data.y, x: body.data.x + Number(wrongCoordinate) } };
        return response(manual);
      }
      return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
    } });
    try {
      await settle(); const canvas = app.$('board-canvas'); canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
      app.$('available-actions').querySelector('[data-available-action="ACTION6"]').click();
      canvas.dispatchEvent(new app.dom.window.MouseEvent('click', { clientX: 75, clientY: 25, bubbles: true })); await settle();
      assert.match(app.$('manual-action-status').textContent, wrongCoordinate ? /未确认/ : /已执行/);
      assert.equal(app.$('retry-command').hidden, !wrongCoordinate);
      assert.equal(app.$('manual-action-history').querySelectorAll('button').length, wrongCoordinate ? 0 : 1);
      assert.deepEqual(app.errors, []);
    } finally { app.dom.window.close(); }
  }
});

test('manual history retains actual no-change and RESET observations; seeking and animation send no actions', async () => {
  let manual = manualView(), version = 0;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/action') {
      const body = JSON.parse(options.body); version += 1;
      manual = manualView('sp80-test', 12, version);
      manual.last_action = { action: body.action, data: body.data, observation_version: version };
      manual.episode_id = body.action === 'RESET' ? 2 : 1;
      return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await settle();
    for (const name of ['ACTION4', 'RESET']) { app.$('available-actions').querySelector(`[data-available-action="${name}"]`).click(); await settle(); }
    assert.equal(app.$('frame-slider').max, '2');
    assert.equal(app.$('frame-counter').textContent, '3 / 3');
    assert.equal(app.$('replay-transport').hidden, false);
    assert.match(app.$('manual-action-history').textContent, /#1 ACTION4.*#2 RESET/);
    assert.match(app.$('frame-caption').textContent, /回合 2/);
    const historyButton = app.$('manual-action-history').querySelector('button'); historyButton.focus();
    app.tick(); await settle();
    assert.equal(app.$('manual-action-history').querySelectorAll('button').length, 2);
    assert.equal(app.$('manual-action-history').querySelector('button'), historyButton);
    assert.equal(app.dom.window.document.activeElement, historyButton);
    app.$('frame-slider').value = '0'; app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
    assert.equal(app.$('frame-counter').textContent, '1 / 3');
    assert.ok([...app.$('available-actions').querySelectorAll('button')].every((button) => button.disabled));
    app.$('board-section').dispatchEvent(new app.dom.window.KeyboardEvent('keydown', { key: '4', bubbles: true }));
    app.tick(); await settle(); assert.equal(app.$('frame-counter').textContent, '1 / 3');
    assert.equal(app.$('manual-return-current').hidden, false);
    app.$('manual-return-current').click();
    assert.equal(app.$('frame-counter').textContent, '3 / 3');
    assert.equal(app.$('available-actions').querySelector('[data-available-action="ACTION4"]').disabled, false);
    app.$('manual-action-history').querySelector('button').click();
    assert.equal(app.$('frame-counter').textContent, '2 / 3');
    assert.equal(app.$('available-actions').querySelector('.is-current').dataset.availableAction, 'ACTION4');
    assert.equal(app.$('manual-action-history').querySelector('[aria-current="true"]').textContent, '#1 ACTION4');
    app.$('play-toggle').click(); app.tick(); await settle();
    assert.equal(app.$('frame-counter').textContent, '3 / 3');
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/action').length, 2);
    assert.equal(app.requests.some((entry) => entry.url === '/api/start'), false);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('manual history crosses actual levels and retains historical selection across new observations and gaps', async () => {
  let manual = manualView(), version = 0;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/action') {
      const body = JSON.parse(options.body); version += 1;
      manual = manualView('sp80-test', 9, version, 2);
      manual.last_action = { action: body.action, data: body.data, observation_version: version };
      return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await settle(); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
    assert.match(app.$('board-title').textContent, /关卡 2/);
    assert.equal(app.$('frame-counter').textContent, '2 / 2');
    const edge = app.dom.window.__ASTERION_STATE__.levels.find((level) => level.level === 2).actions[0];
    assert.equal(edge.before_frame, 'manual-0'); assert.equal(edge.after_frame, 'manual-1');
    app.$('compare-toggle').checked = true; app.$('compare-toggle').dispatchEvent(new app.dom.window.Event('change'));
    assert.equal(app.$('comparison-board').hidden, false);
    app.$('frame-slider').value = '0'; app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
    assert.match(app.$('board-title').textContent, /关卡 1/);
    manual = manualView('sp80-test', 10, 2, 2); app.tick(); await settle();
    assert.equal(app.$('frame-counter').textContent, '1 / 3');
    assert.match(app.$('board-title').textContent, /关卡 1/);
    manual = manualView('sp80-test', 11, 5, 2); app.tick(); await settle();
    assert.equal(app.$('frame-counter').textContent, '1 / 4');
    assert.equal(app.$('manual-action-history').querySelectorAll('button').length, 2);
    assert.match(app.$('manual-history-note').textContent, /缺失/);
    app.$('manual-return-current').click();
    assert.equal(app.$('frame-counter').textContent, '4 / 4');
    assert.match(app.$('board-title').textContent, /关卡 2/);
    assert.equal(app.$('available-actions').querySelector('[data-available-action="ACTION4"]').disabled, false);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('manual history autoplay continues across actual level transitions', async () => {
  let manual = manualView(), version = 0;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/action') {
      const body = JSON.parse(options.body); version += 1;
      manual = manualView('sp80-test', 9, version, 2);
      manual.last_action = { action: body.action, data: body.data, observation_version: version };
      return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await settle();
    for (let i = 0; i < 2; i += 1) { app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle(); }
    app.$('frame-slider').value = '0'; app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
    app.$('play-toggle').click(); app.tick(); await settle();
    assert.match(app.$('board-title').textContent, /关卡 2/);
    assert.equal(app.$('frame-counter').textContent, '2 / 3');
    assert.equal(app.$('play-toggle').textContent, '暂停');
    app.tick(); await settle();
    assert.equal(app.$('frame-counter').textContent, '3 / 3');
    assert.equal(app.$('play-toggle').textContent, '播放');
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/action').length, 2);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('manual feedback cannot survive a different same-game session identity', async () => {
  let manual = manualView();
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/action') {
      const body = JSON.parse(options.body); manual = manualView('sp80-test', 9, 1);
      manual.last_action = { action: body.action, data: body.data, observation_version: 1 }; return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await settle(); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
    assert.match(app.$('manual-action-status').textContent, /已执行 1 次/);
    manual = { ...manualView(), session_id: 'different-session' }; app.tick(); await settle();
    assert.equal(app.$('action-total').textContent, '0');
    assert.equal(app.$('frame-counter').textContent, '1 / 1');
    assert.equal(app.$('manual-action-status').hidden, true);
    assert.doesNotMatch(app.$('manual-action-status').textContent, /已执行/);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('manual history survives same-session mode changes and resets for a newly opened session', async () => {
  let manual = manualView(), opens = 0;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/action') {
      const body = JSON.parse(options.body); manual = manualView('sp80-test', 9, 1);
      manual.last_action = { action: body.action, data: body.data, observation_version: 1 }; return response(manual);
    }
    if (url === '/api/manual/close') { manual = { ...manual, state: 'closed' }; return response(manual); }
    if (url === '/api/manual/open') { opens += 1; manual = { ...manualView(), session_id: `new-session-${opens}` }; return response(manual); }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await settle(); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
    app.$('frame-slider').value = '0'; app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
    app.$('console-mode').value = 'replay'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change')); await settle();
    app.$('console-mode').value = 'manual'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change')); await settle();
    assert.equal(app.$('frame-counter').textContent, '1 / 2');
    assert.equal(app.$('manual-action-history').querySelectorAll('button').length, 1);
    app.$('manual-close').click(); await settle(); app.$('manual-close').click(); await settle();
    assert.equal(app.$('frame-counter').textContent, '1 / 1');
    assert.equal(app.$('manual-action-history').querySelectorAll('button').length, 0);
    assert.equal(opens, 1);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('manual buttons send versioned actions once and transport retry retains exact identity', async () => {
  let manual = manualView(), failAction = true;
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/manual/open') return response(manual);
    if (url === '/api/manual/action') { if (failAction) { failAction = false; throw new Error('/private/secret'); } manual = manualView('sp80-test', 9, 1); return response(manual); }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await settle(); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
    assert.equal(app.$('retry-command').hidden, false);
    assert.ok([...app.$('available-actions').querySelectorAll('button')].every((button) => button.disabled));
    app.$('retry-command').click(); await settle();
    const actions = app.requests.filter((entry) => entry.url === '/api/manual/action');
    assert.equal(actions.length, 2);
    assert.deepEqual(JSON.parse(actions[0].options.body), JSON.parse(actions[1].options.body));
    app.tick(); await settle();
    assert.equal(app.$('frame-counter').textContent, '2 / 2');
    assert.equal(app.$('manual-action-history').querySelectorAll('button').length, 1);
    const body = JSON.parse(actions[0].options.body);
    assert.equal(body.session_id, 'manual-sp80-test'); assert.equal(body.observation_version, 0); assert.equal(body.action, 'ACTION4'); assert.deepEqual(body.data, {});
    assert.equal(app.$('action-total').textContent, '1');
    const current = app.$('available-actions').querySelector('[aria-current="true"]');
    assert.equal(current.dataset.availableAction, 'ACTION4');
    assert.equal(current.classList.contains('is-current'), true);
    assert.equal(app.$('current-action'), null);
    assert.equal(app.$('current-action-strip').hidden, true);
    assert.doesNotMatch(app.$('board-section').textContent, /人工操作 · ACTION4|当前动作/);
    assert.equal(app.paints.at(-1), '#1E93FF');
    assert.equal(app.$('decision-count').textContent, '0');
    assert.equal(app.$('cognition-count').textContent, '0');
    assert.equal(app.requests.some((entry) => entry.url === '/api/start'), false);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('manual action strip only shows real measurements and never suggests a missing P7 association', async () => {
  for (const observations of [[], ['蓝色物件向右移动。']]) {
    const manual = manualView('sp80-test', 9, 1);
    const level = manual.snapshot.levels[0];
    level.frames.unshift({ ...level.frames[0], id: 'manual-before' });
    level.actions = [{ id: 'manual-action', name: 'ACTION4', before_frame: 'manual-before', after_frame: 'manual-1', data: {}, visual_observations: observations }];
    const app = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual)) });
    try {
      await settle();
      assert.equal(app.$('available-actions').querySelector('.is-current').dataset.availableAction, 'ACTION4');
      assert.equal(app.$('current-action-link').hidden, true);
      assert.equal(app.$('current-action-link').textContent, '');
      assert.equal(app.$('current-action-strip').hidden, observations.length === 0);
      assert.equal(app.$('current-action-evidence').hidden, observations.length === 0);
      assert.doesNotMatch(app.$('current-action-strip').textContent, /P7|当前动作|ACTION4/);
      if (observations.length) assert.match(app.$('current-action-evidence').textContent, /蓝色物件向右移动/);
      assert.deepEqual(app.errors, []);
    } finally { app.dom.window.close(); }
  }
});

test('manual ACTION6 waits for board click and sends exact grid coordinates; keyboard stays board-scoped', async () => {
  let manual = manualView('sp80-test', 9, 1);
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/action') {
      const body = JSON.parse(options.body);
      manual = manualView('sp80-test', 9, 2); manual.last_action = { action: body.action, data: body.data, observation_version: 2 };
      return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await settle();
    const canvas = app.$('board-canvas'); canvas.getBoundingClientRect = () => ({ left: 10, top: 20, width: 100, height: 100 });
    app.$('available-actions').querySelector('[data-available-action="ACTION6"]').click(); await settle();
    assert.equal(app.requests.some((entry) => entry.url === '/api/manual/action'), false);
    const armed = app.$('available-actions').querySelector('.is-armed');
    assert.equal(armed.dataset.availableAction, 'ACTION6');
    assert.equal(armed.getAttribute('aria-pressed'), 'true');
    assert.equal(armed.hasAttribute('aria-current'), false);
    assert.equal(app.$('available-actions').querySelector('.is-current').dataset.availableAction, 'ACTION4');
    canvas.dispatchEvent(new app.dom.window.MouseEvent('click', { clientX: 85, clientY: 45, bubbles: true })); await settle();
    const request = app.requests.find((entry) => entry.url === '/api/manual/action');
    assert.deepEqual(JSON.parse(request.options.body).data, { x: 1, y: 0 });
    assert.equal(app.$('available-actions').querySelector('.is-armed'), null);
    app.dom.window.document.body.dispatchEvent(new app.dom.window.KeyboardEvent('keydown', { key: '1', bubbles: true })); await settle();
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/action').length, 1);
    app.$('board-section').dispatchEvent(new app.dom.window.KeyboardEvent('keydown', { key: '1', repeat: true, bubbles: true })); await settle();
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/action').length, 1);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('arming manual ACTION6 exits comparison so the current clickable board is visible', async () => {
  let manual = manualView();
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/action') {
      const body = JSON.parse(options.body); const version = manual.observation_version + 1;
      manual = manualView('sp80-test', 9, version);
      manual.last_action = { action: body.action, data: body.data, observation_version: version };
      return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await settle(); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
    app.$('compare-toggle').checked = true; app.$('compare-toggle').dispatchEvent(new app.dom.window.Event('change'));
    assert.equal(app.$('comparison-board').hidden, false);
    assert.equal(app.$('single-board').hidden, true);
    app.$('available-actions').querySelector('[data-available-action="ACTION6"]').click();
    assert.equal(app.$('compare-toggle').checked, false);
    assert.equal(app.$('comparison-board').hidden, true);
    assert.equal(app.$('single-board').hidden, false);
    const canvas = app.$('board-canvas'); canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
    canvas.dispatchEvent(new app.dom.window.MouseEvent('click', { clientX: 75, clientY: 25, bubbles: true })); await settle();
    const actions = app.requests.filter((entry) => entry.url === '/api/manual/action');
    assert.equal(actions.length, 2);
    assert.equal(JSON.parse(actions[1].options.body).action, 'ACTION6');
    assert.deepEqual(JSON.parse(actions[1].options.body).data, { x: 1, y: 0 });
    app.$('available-actions').querySelector('[data-available-action="ACTION6"]').click();
    assert.match(app.$('actions-note').textContent, /点击画面目标格/);
    app.$('compare-toggle').checked = true; app.$('compare-toggle').dispatchEvent(new app.dom.window.Event('change'));
    assert.equal(app.$('comparison-board').hidden, false);
    assert.equal(app.$('available-actions').querySelector('.is-armed'), null);
    assert.equal(app.$('available-actions').querySelector('[data-available-action="ACTION6"]').getAttribute('aria-pressed'), 'false');
    assert.doesNotMatch(app.$('actions-note').textContent, /点击画面目标格/);
    canvas.dispatchEvent(new app.dom.window.MouseEvent('click', { clientX: 75, clientY: 25, bubbles: true })); await settle();
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/action').length, 2);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('manual busy operation rejects extra clicks and closed or uncertain sessions stay locked', async () => {
  for (const terminal of ['closed', 'uncertain']) {
    let manual = manualView(), releaseAction;
    const app = launch(fixture(), { liveConfig, fetch: async (url) => {
      if (url === '/api/manual/open') return response(manual);
      if (url === '/api/manual/action') return new Promise((resolve) => { releaseAction = resolve; });
      return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
    } });
    try {
      await settle(); const button = app.$('available-actions').querySelector('[data-available-action="ACTION1"]');
      button.click(); button.click(); await settle();
      assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/action').length, 1);
      manual = { ...manual, state: terminal }; releaseAction(response(manual)); await settle(); app.tick(); await settle();
      assert.ok([...app.$('available-actions').querySelectorAll('button')].every((item) => item.disabled), terminal);
      assert.equal(app.$('run-start').disabled, false, terminal);
      assert.equal(app.$('manual-close').disabled, false, terminal);
      assert.equal(app.$('manual-close').textContent, '重新打开试玩', terminal);
      assert.deepEqual(app.errors, []);
    } finally { app.dom.window.close(); }
  }
});

test('closed manual session reopens the selected game and actual level with a fresh command and no P7 start', async () => {
  let manual = manualView('ls20-test', 9, 0, 3), opens = 0;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/runs') return response({ runs: [] });
    if (url === '/api/manual/close') { manual = { ...manual, state: 'closed' }; return response(manual); }
    if (url === '/api/manual/open') { opens += 1; const body = JSON.parse(options.body); manual = manualView(body.game_id, 9, 0, body.level); return response(manual); }
    return response(stateWithManual(manual));
  } });
  try {
    await settle();
    app.$('manual-close').click(); await settle();
    const close = app.requests.find((entry) => entry.url === '/api/manual/close');
    assert.equal(app.$('manual-close').textContent, '重新打开试玩');
    app.$('manual-close').click(); await settle();
    const open = app.requests.find((entry) => entry.url === '/api/manual/open');
    assert.equal(opens, 1);
    assert.equal(JSON.parse(open.options.body).game_id, 'ls20-test');
    assert.equal(JSON.parse(open.options.body).level, 3);
    assert.equal(app.$('board-kicker').textContent, 'LEVEL 03');
    assert.notEqual(JSON.parse(open.options.body).command_id, JSON.parse(close.options.body).command_id);
    assert.equal(app.$('manual-close').textContent, '结束试玩');
    assert.ok([...app.$('available-actions').querySelectorAll('button')].every((button) => !button.disabled));
    assert.equal(app.requests.some((entry) => entry.url === '/api/start'), false);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('live initialization polls without starting, start uses exact game, retry preserves command identity, stop owns session', async () => {
  let current = view(fixture(), 'idle'), rejectStart = true;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/state') return response(current);
    if (url === '/api/manual/open') return response(manualView());
    if (url === '/api/runs') return response({ runs: [] });
    if (url === '/api/start') { if (rejectStart) { rejectStart = false; throw new Error('private-error'); } current = view(); return response(current, 202); }
    if (url === '/api/stop') { current = view(fixture(), 'stopping'); return response(current, 202); }
    throw new Error('unexpected route');
  } });
  await settle();
  assert.equal(app.$('console-mode').value, 'manual');
  assert.equal(app.requests.filter((request) => request.url === '/api/start').length, 0);
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
  assert.match(app.$('manual-note').textContent, /独立于 P7/);
  assert.deepEqual(app.errors, []); app.dom.window.close();
});

test('live replacement follows newest frame; replay preserves historical selection and animation never stops solver', async () => {
  let current = view(), revision = 1;
  const app = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [{run_id:'old-run',game_id:'sp80-test'}] } : url === '/api/replay/old-run' ? {...fixture(), run: {...fixture().run, run_id:'old-run'}} : current) });
  await settle(); assert.equal(app.$('frame-counter').textContent, '3 / 3');
  assert.equal(app.$('unavailable-current-action').querySelector('.is-current').dataset.availableAction, 'ACTION4');
  assert.equal(app.$('unavailable-current-action').querySelector('button').disabled, true);
  assert.equal(app.$('current-action'), null);
  const next = fixture(); next.levels[0].frames.push({ id: 'f3', grid: [[14]], state: 'NOT_FINISHED', levels_completed: 0, available_actions: ['ACTION4'] });
  current = {...view(next), revision: ++revision}; app.tick(); await settle();
  assert.equal(app.$('frame-counter').textContent, '4 / 4');
  assert.equal(app.paints.at(-1), '#4FCC30');
  assert.equal(app.$('available-actions').querySelector('button').disabled, true);
  assert.equal(app.$('available-actions').querySelector('.is-current'), null); // no action links to the new observation
  app.$('console-mode').value = 'replay'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change'));
  app.$('frame-slider').value = '1'; app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
  current = {...view(next), revision: ++revision}; app.tick(); await settle();
  assert.equal(app.$('frame-counter').textContent, '2 / 4');
  assert.equal(app.$('unavailable-current-action').querySelector('[aria-current="true"]').dataset.availableAction, 'ACTION4');
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
    if (url === '/api/manual/open') return response({}, 503);
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
    if (url === '/api/manual/open') return response({}, 503);
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
