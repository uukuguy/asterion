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

const actorLabel = (action, label, purpose, confidence = 'certain', evidence_sequences = [0]) =>
  ({ action, label, purpose, confidence, evidence_sequences });

test('original level rail emphasizes passed steps and separates attempts from unloaded or unplayed levels', () => {
  for (const [status, count, unloaded, expected] of [
    ['successful', 13, false, '13 动作'], ['incomplete', 2, false, '2 动作'],
    ['successful', 13, true, '13 动作'], ['incomplete', 0, false, '无动作记录'],
    ['not_run', 0, false, null], ['preview', 0, false, null], ['loading', 0, true, null],
  ]) {
    const snapshot = fixture(), level = snapshot.levels[0];
    level.status = status;
    level.actions = unloaded ? [] : Array.from({length: count}, (_, i) => ({...level.actions[0], id: `a${i}`}));
    if (unloaded) Object.assign(level, {replay_unloaded: true, action_count: count, frame_count: count ? 15 : 0, frames: []});
    else if (!count) level.frames = level.frames.slice(0, 1);
    const app = launch(snapshot, {replayConfig: {games: [{game_id: 'sp80-test', alias: 'SP80', win_levels: 3, baseline_actions: [20, 21, 22]}]}});
    try {
      const row = app.$('level-1');
      assert.equal(row.querySelector('.level-step-count')?.textContent ?? null, expected);
      assert.equal(row.querySelectorAll('.level-item-detail').length, expected ? 2 : 1);
      assert.doesNotMatch(row.textContent, /已保存|按需读取|关卡效率/);
      assert.equal(row.querySelector('.level-item-efficiency').textContent, status === 'successful' ? '基准 20 · 115.00 分' : '基准 20 · 待完成');
      assert.match(row.title, /基准 20/);
      if (status === 'successful') {
        assert.match(row.title, /已过关/);
        assert.equal(row.textContent.match(/已过关/g).length, 1);
        assert.match(row.title, /13 动作.*关卡效率 115.00 分/);
        assert.match(app.$('level-efficiency').textContent, /115.00 分/);
      } else assert.doesNotMatch(row.textContent, /已过关/);
      assert.equal(row.querySelector('.level-number').textContent, '01');
      assert.equal(row.querySelector('.level-item-heading strong').textContent, '关卡 1');
      if (expected) {
        assert.equal(row.querySelector('.level-step-count').parentElement.className, 'level-item-detail');
        assert.equal(row.querySelector('.level-step-count').tagName, count ? 'STRONG' : 'SPAN');
        assert.equal(app.dom.window.getComputedStyle(row.querySelector('.level-item-detail')).fontSize, '10px');
      }
      assert.equal(app.dom.window.getComputedStyle(row).minHeight, '0');
      assert.equal(app.dom.window.getComputedStyle(row).paddingTop, '8px');
      assert.doesNotMatch(row.textContent, /—|无动作记录 · 1 帧/);
      if (status === 'incomplete' && count) assert.match(row.querySelector('.level-item-detail').textContent, /尝试 2 动作/);
      assert.deepEqual(app.errors, []);
    } finally { app.dom.window.close(); }
  }
});

test('structured actor labels display verbatim at the selected cognition cursor without parsing rules or responses', () => {
  const snapshot = fixture(), level = snapshot.levels[0];
  level.frames.forEach(frame => { frame.available_actions = ['ACTION1', 'ACTION5', 'ACTION6', 'ACTION7']; });
  level.actions[0].name = 'ACTION5';
  level.actions[0].visual_observations = ['画面向上移动四格。'];
  level.cognition = { scope: 'unavailable' };
  level.cognition_timeline = [
    { scope: 'observation', frame_id: 'f0', event_sequence: 93, cognition_revision: 101, source_action_sequence: 35,
      stable_description: 'G50T 第二关认知', action_labels: [
        actorLabel('ACTION1', '上移 ↑', '使当前角色向上移动一步。', 'certain', [0, 35]),
        actorLabel('ACTION5', '特殊用途', '复位白色对象并进入下一个记录槽。', 'certain', [35]),
        actorLabel('ACTION6', null, '尚不知道点击如何影响本关。', 'unknown', [35]),
        actorLabel('ACTION7', null, '用途仍有冲突。', 'conflict', [35]),
      ] },
    { scope: 'observation', frame_id: 'f1', event_sequence: 124, cognition_revision: 102, source_action_sequence: 36,
      stable_description: '下一观察', action_labels: [actorLabel('ACTION5', '回放候选', '可能回放旧轨迹。', 'hypothesis', [36])] },
  ];
  level.research_timeline = [{ kind: 'model_revision', level: 1, frame_id: 'f0', event_sequence: 93,
    payload: { rule_summaries: ['ACTION7向左移动。'] } }];
  snapshot.levels[1].cognition.action_labels = [actorLabel('ACTION5', '旋转', '另一关的用途。')];
  const app = launch(snapshot), key = name => app.$('available-actions').querySelector(`[data-available-action="${name}"]`);
  try {
    assert.equal(key('ACTION1').querySelector('strong').textContent, 'ACTION1');
    assert.equal(key('ACTION1').querySelector('.action-key-meaning').textContent, '上移 ↑');
    assert.equal(key('ACTION5').querySelector('.action-key-meaning').textContent, '特殊用途');
    assert.match(key('ACTION5').title, /复位白色对象并进入下一个记录槽/);
    assert.match(key('ACTION5').title, /P7 的动作理解/);
    assert.doesNotMatch(key('ACTION5').title, /事后整理/);
    assert.doesNotMatch(key('ACTION5').title, /另一关/);
    assert.equal(key('ACTION6').querySelector('.action-key-meaning').textContent, '未识别');
    assert.equal(key('ACTION7').querySelector('strong').textContent, 'ACTION7');
    assert.equal(key('ACTION7').querySelector('.action-key-status').textContent, '有冲突');
    app.$('next-frame').click();
    assert.equal(key('ACTION5').querySelector('strong').textContent, 'ACTION5');
    assert.equal(key('ACTION5').querySelector('.action-key-meaning').textContent, '回放候选');
    assert.equal(key('ACTION5').querySelector('.action-key-status').textContent, '推测');
    assert.equal(key('ACTION1').querySelector('.action-key-meaning').textContent, '未记录');
    app.$('previous-frame').click();
    assert.match(key('ACTION1').textContent, /上移 ↑/);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

function overviewFixture(config) {
  const games = config.games.map((game) => ({ ...game, completed_levels: 0, score: '0.000000', status: 'unplayed',
    best_run_id: null, resume_run_id: null, route_actions: 0, runs: [] }));
  return { guest_busy: false, start_ready: true, start_block_reason: null, scope: { model_id: 'gpt-6.1-sol', seed: 0, score_kind: 'saved-route-rhae', catalog_id: 'test-catalog' },
    totals: { score: '0.000000', completed_games: 0, total_games: games.length, completed_levels: 0,
      total_levels: games.reduce((sum, game) => sum + game.win_levels, 0), primitive_actions: 0, restoration_actions: 0, new_solver_actions: 0 }, games };
}

function launch(snapshot = fixture(), { liveConfig = null, replayConfig = null, fetch = null, overview = undefined, countFrameLookups = false } = {}) {
  const errors = [], requests = [], paints = [], outlines = [], pointers = [], timers = new Map();
  const frameLookups = { visits: 0 };
  const substitutions = {
    __CONSOLE_CSP__: '', __CONSOLE_CSS__: fs.readFileSync(path.join(assets, 'styles.css'), 'utf8'),
    __CONSOLE_DATA__: JSON.stringify(snapshot).replace(/</g, '\\u003c'),
    __CONSOLE_CONFIG__: JSON.stringify(liveConfig || replayConfig).replace(/</g, '\\u003c'),
    __CONSOLE_JS__: fs.readFileSync(path.join(assets, 'app.js'), 'utf8'),
  };
  const html = fs.readFileSync(path.join(assets, 'index.html'), 'utf8')
    .replace(/__CONSOLE_(CSP|CSS|DATA|CONFIG|JS)__/g, (marker) => substitutions[marker]);
  const vc = new VirtualConsole();
  vc.on('jsdomError', (error) => errors.push(error));
  class NoNetwork extends ResourceLoader { fetch(url) { requests.push(url); return null; } }
  const dom = new JSDOM(html, { url: 'http://localhost:8765/', runScripts: 'dangerously', resources: new NoNetwork(), virtualConsole: vc,
    beforeParse(window) {
      if (countFrameLookups) ['findIndex', 'some'].forEach(name => {
        const original = window.Array.prototype[name];
        window.Array.prototype[name] = function (predicate, ...rest) {
          const frames = this.length >= 300 && Array.isArray(this[0]?.grid);
          return original.call(this, function (...args) {
            if (frames) frameLookups.visits += 1;
            return predicate.apply(this, args);
          }, ...rest);
        };
      });
      window.HTMLCanvasElement.prototype.getContext = function () {
        return { fillRect() { paints.push(this.fillStyle); }, strokeRect() { outlines.push(this.strokeStyle); }, beginPath() {}, arc() { pointers.push(this.strokeStyle); }, stroke() {} };
      };
      window.fetch = async (url, options = {}) => { requests.push({ url, options }); if (!fetch) throw new Error('unexpected network'); if (url === '/api/overview' && overview === undefined) return response(overviewFixture(liveConfig)); if (url === '/api/overview' && overview !== null) return response(typeof overview === 'function' ? overview() : overview); return fetch(url, options); };
      window.matchMedia = () => ({ matches: true, addEventListener() {} });
      let next = 0;
      window.setInterval = (fn, ms) => { fn.intervalMs = ms; timers.set(++next, fn); return next; };
      window.clearInterval = (id) => timers.delete(id);
    } });
  const $ = (id) => dom.window.document.getElementById(id);
  return { dom, $, errors, requests, paints, outlines, pointers, frameLookups, tick: () => [...timers.values()].forEach((fn) => fn()), timers };
}

test('dense replay event selection remains bounded and preserves exact frame and cognition cursors', () => {
  const snapshot = fixture(), level = snapshot.levels[0];
  level.frames = Array.from({length: 362}, (_, i) => ({id: `dense-${i}`, grid: [[i % 16]], available_actions: ['ACTION1', 'ACTION5']}));
  level.actions = [{id: 'last-action', name: 'ACTION5', before_frame: 'dense-360', after_frame: 'dense-361'}];
  snapshot.process_events = level.frames.map((frame, i) => ({kind: 'compute_task', level: 1, frame_id: frame.id,
    event_sequence: i + 1, payload: {status: 'completed', summary: `记录 ${i}`}}));
  level.cognition_timeline = [0, 180, 361].map(i => ({scope: 'observation', frame_id: `dense-${i}`, event_sequence: i + 1,
    source_action_sequence: i, stable_description: `精确认知 ${i}`, action_labels: [actorLabel('ACTION1', `认知${i}`, `来自观察 ${i}`, 'certain', [i])]}));
  const app = launch(snapshot, {countFrameLookups: true});
  try {
    assert.match(app.$('world-guide').textContent, /精确认知 0/);
    app.$('frame-slider').value = '361';app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
    assert.equal(app.$('event-counter').textContent, '事件 362');
    assert.match(app.$('world-guide').textContent, /精确认知 361/);
    assert.equal(app.$('available-actions').querySelector('.action-key-meaning').textContent, '认知361');
    app.$('event-slider').value = '180';app.$('event-slider').dispatchEvent(new app.dom.window.Event('input'));
    assert.equal(app.$('event-counter').textContent, '事件 181');
    assert.match(app.$('world-guide').textContent, /精确认知 180/);
    assert.equal(app.$('frame-counter').textContent, '181 / 362');
    assert.ok(app.frameLookups.visits < 1000000, `frame lookup visits: ${app.frameLookups.visits}`);
    assert.deepEqual(app.errors, []);
  } finally {app.dom.window.close();}
});

test('per-level efficiency uses exact baseline actions and remains separate from game aggregate', () => {
  for (const [actual, baseline, status, expected] of [
    [11, 7, 'successful', '关卡效率 40.50 分'],
    [7, 7, 'successful', '关卡效率 100.00 分'],
    [4, 7, 'successful', '关卡效率 115.00 分'],
    [11, null, 'successful', '关卡效率未知'],
    [11, 7, 'incomplete', '关卡效率待完成'],
  ]) {
    const snapshot = fixture(), level = snapshot.levels[0];
    snapshot.run.game_id = 'vc33-test';
    level.status = status;
    level.actions = Array.from({length: actual}, (_, index) => ({...level.actions[0], id: `a${index + 1}`}));
    level.receipt = {partial_game_score: '100.00'};
    const game = {game_id: 'vc33-test', alias: 'vc33', win_levels: 3};
    if (baseline !== null) game.baseline_actions = [baseline, 11, 12];
    const app = launch(snapshot, {replayConfig: {games: [game]}});
    assert.match(app.$('level-efficiency').textContent, new RegExp(expected));
    assert.match(app.$('level-1').title, new RegExp(expected));
    assert.match(app.$('level-efficiency').textContent, new RegExp(`基准 ${baseline ?? '未知'} / ${actual} 动作`));
    assert.match(app.$('receipt-content').textContent, /游戏综合分（局部）：100.00/);
    assert.equal(app.$('level-efficiency').classList.contains('efficiency-low'), status === 'successful' && baseline === 7 && actual === 11);
    assert.equal(app.$('level-1').querySelector('.level-item-efficiency').textContent,
      `基准 ${baseline ?? '未知'} · ${status === 'successful' ? baseline === null ? '分数未知' : expected.replace('关卡效率 ', '') : '待完成'}`);
    assert.equal(app.$('level-1').querySelector('.level-item-efficiency').classList.contains('efficiency-low'), status === 'successful' && baseline === 7 && actual === 11);
    assert.deepEqual(app.requests, []);
    assert.deepEqual(app.errors, []);
    app.dom.window.close();
  }
});

test('diff markers are opt-in, clicks default visible, and the legend follows visible game colors', () => {
  const snapshot = fixture();
  Object.assign(snapshot.levels[0].actions[0], {name: 'ACTION6', data: { x: 2, y: 3 }});
  const app = launch(snapshot); const { dom, $, outlines, pointers } = app;
  const change = (id, checked) => {
    $(id).checked = checked; $(id).dispatchEvent(new dom.window.Event('change'));
  };
  const legendIds = () => [...$('palette-colors').children].map((item) => item.dataset.color);
  assert.equal($('diff-toggle').checked, false);
  assert.equal($('highlight-toggle').checked, true);
  assert.equal($('overlay-note').hidden, true);
  assert.deepEqual(legendIds(), ['12']);
  assert.match($('palette-colors').textContent, /橙色（12）/);
  assert.equal($('palette-colors').querySelector('.palette-swatch').style.backgroundColor, 'rgb(255, 133, 27)');
  $('next-action').click();
  assert.deepEqual(outlines, []);
  assert.deepEqual(pointers, []);
  assert.equal($('board-canvas-click-marker').hidden, false);
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
  assert.deepEqual(pointers, []);
  assert.equal($('board-canvas-click-marker').hidden, false);
  assert.match($('overlay-note').textContent, /圆圈与十字为点击位置标记/);
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

test('recorded click marker defaults on, follows scaled edge coordinates, and leaves canvas pixels alone', () => {
  for (const [name, x, y, visible] of [['ACTION6', 0, 63, true], ['ACTION6', 63, 0, true], ['ACTION4', 0, 63, false]]) {
    const snapshot = fixture();
    Object.assign(snapshot.levels[0].actions[0], {name, data: {x, y}});
    const app = launch(snapshot), canvas = app.$('board-canvas');
    const bounds = () => ({left: 10, top: 20, width: 320, height: 320});
    canvas.getBoundingClientRect = bounds;
    canvas.parentElement.getBoundingClientRect = bounds;
    app.$('next-action').click();
    const marker = app.$('board-canvas-click-marker');
    assert.equal(marker.hidden, !visible);
    assert.deepEqual(app.pointers, []);
    if (visible) {
      assert.equal(marker.style.left, `${(x + 0.5) * 5}px`);
      assert.equal(marker.style.top, `${(y + 0.5) * 5}px`);
      assert.equal(marker.dataset.action, 'ACTION6');
      assert.equal(marker.dataset.status, 'recorded');
      assert.match(app.$('overlay-note').textContent, /已记录点击/);
      app.$('highlight-toggle').checked = false;
      app.$('highlight-toggle').dispatchEvent(new app.dom.window.Event('change'));
      assert.equal(marker.hidden, true);
    }
    assert.deepEqual(app.errors, []);
    app.dom.window.close();
  }
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
  level.cognition.action_labels = [actorLabel('ACTION1', '↑', '上移'), actorLabel('ACTION4', '右移', '右移', 'hypothesis')];
  const app = launch(snapshot); const { dom, $ } = app;
  const availableNames = () => [...$('available-actions').querySelectorAll('[data-available-action]')].map((card) => card.dataset.availableAction);
  const highlighted = () => dom.window.document.querySelectorAll('.available-action[aria-current="true"]');
  assert.deepEqual(availableNames(), ['ACTION1', 'ACTION4', 'ACTION5']);
  assert.equal(highlighted().length, 0);
  assert.match($('available-actions').textContent, /ACTION1↑已识别/);
  assert.match($('available-actions').textContent, /ACTION4右移推测/);
  assert.match($('available-actions').textContent, /ACTION5未记录本关未使用/);
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
  assert.match(app.$('available-actions').textContent, /ACTION4未记录/);
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
  snapshot.levels[0].cognition.action_labels = [actorLabel('ACTION4', '→', '右移')];
  const app = launch(snapshot);
  const card = app.$('available-actions').querySelector('[data-available-action="ACTION4"]');
  assert.equal(card.textContent, 'ACTION4→已识别');
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
  ['ACTION5', 'ACTION7'].forEach((name) => {
    assert.equal(key(name).querySelector('strong').textContent,name);
    assert.equal(key(name).querySelector('.action-key-meaning').textContent,'未记录');
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

test('action headings use same-level learned movements as labeled background, keep unknown keys and define native clicks and RESET',()=>{
  const snapshot=fixture(),level=snapshot.levels[0];
  level.frames.forEach(frame=>{frame.available_actions=['ACTION1','ACTION2','ACTION6','RESET'];});
  level.cognition.action_meanings={ACTION1:[{status:'certain',claim:'ACTION1向左移动。'}]};
  level.actions=[
    {id:'left',name:'ACTION1',before_frame:'f0',after_frame:'f1',data:{},visual_observations:['蓝色（9）像素整体向左4格；形状和数量不变。']},
    {id:'point',name:'ACTION6',before_frame:'f1',after_frame:'f2',data:{x:2,y:3},visual_observations:[]},
  ];
  level.cognition.action_labels = [actorLabel('ACTION1', '←', '左移')];
  const app=launch(snapshot),key=name=>app.$('available-actions').querySelector(`[data-available-action="${name}"]`);
  try {
    assert.equal(key('ACTION1').querySelector('.action-key-meaning').textContent,'←');assert.match(key('ACTION1').title,/规划背景，不表示当前帧当时已知/);
    assert.equal(key('ACTION2').querySelector('strong').textContent,'ACTION2');
    assert.equal(key('RESET').querySelector('.action-key-meaning').textContent,'重置');
    assert.equal(key('RESET').querySelector('.action-key-status').textContent,'固定含义');
    app.$('next-frame').click();assert.equal(key('ACTION1').querySelector('.action-key-meaning').textContent,'←');
    assert.equal(key('ACTION6').querySelector('.action-key-meaning').textContent,'点击');assert.equal(key('ACTION6').querySelector('.action-key-status').textContent,'固定含义');
    app.$('next-frame').click();assert.equal(key('ACTION6').querySelector('.action-key-meaning').textContent,'点击');
    assert.match(key('ACTION6').title,/固定含义：点击/);
    app.$('previous-frame').click();app.$('previous-frame').click();
    assert.equal(key('ACTION1').querySelector('.action-key-meaning').textContent,'←');assert.match(key('ACTION1').title,/规划背景，不表示当前帧当时已知/);
    assert.equal(key('ACTION6').querySelector('.action-key-meaning').textContent,'点击');assert.equal(key('ACTION6').querySelector('.action-key-status').textContent,'固定含义');
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('action labels distinguish unused keys from used unknown effects and explain fixed and observed meanings',()=>{
  const snapshot=fixture(),level=snapshot.levels[0];
  level.frames.forEach(frame=>{frame.available_actions=['ACTION1','ACTION4','ACTION5','ACTION6','ACTION7','RESET'];});
  level.actions.push({id:'unclear',name:'ACTION5',before_frame:'f0',after_frame:'f1',data:{},visual_observations:[]});
  level.cognition.action_meanings={ACTION5:[{status:'certain',claim:'ACTION5将可控对象旋转90度。'}],
    ACTION7:[{status:'certain',claim:'ACTION7与ACTION5一起完成过关。'},{status:'falsified',claim:'ACTION7直接过关。'}]};
  level.cognition.action_labels=[actorLabel('ACTION5', '特殊用途', 'ACTION5将可控对象旋转90度。')];
  level.actions[0].visual_observations=['蓝色（9）像素整体向右4格；形状和数量不变。'];
  const app=launch(snapshot),key=name=>app.$('available-actions').querySelector(`[data-available-action="${name}"]`);
  try {
    assert.equal(key('ACTION7').querySelector('.action-key-meaning').textContent,'未记录');assert.equal(key('ACTION7').querySelector('.action-key-status').textContent,'本关未使用');
    assert.equal(key('ACTION5').querySelector('.action-key-meaning').textContent,'特殊用途');assert.equal(key('ACTION5').querySelector('.action-key-status').textContent,'已识别');
    assert.match(key('ACTION5').title,/ACTION5将可控对象旋转90度/);
    assert.match(key('ACTION7').title,/未记录动作含义/);
    assert.doesNotMatch(key('ACTION7').title,/一起完成过关|直接过关/);
    assert.equal(key('ACTION4').querySelector('.action-key-meaning').textContent,'未记录');assert.equal(key('ACTION4').querySelector('strong').textContent,'ACTION4');
    for(const name of ['ACTION6','RESET'])assert.equal(key(name).querySelector('.action-key-status').textContent,'固定含义');
    for(const [name,count] of [['ACTION1',0],['ACTION4',1],['ACTION5',1],['ACTION6',0],['ACTION7',0],['RESET',0]]) {
      assert.ok(key(name).title.includes(`本关已记录 ${count} 次`));
      assert.ok(key(name).getAttribute('aria-label').includes(`本关已记录 ${count} 次`));
    }
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('legacy prose and pixel responses remain evidence and never become action labels', () => {
  const snapshot = fixture(), level = snapshot.levels[0];
  level.frames[0].available_actions = ['ACTION4', 'ACTION5'];
  level.cognition.action_meanings = { ACTION4: [{ status: 'certain', claim: 'ACTION4向右移动。' }] };
  level.actions[0].visual_observations = ['物件向上移动四格。'];
  level.research_timeline = [{ kind: 'model_revision', level: 1, frame_id: 'f0', event_sequence: 1,
    payload: { rule_summaries: ['ACTION5提交布局。', '1/2/3/4为上/下/左/右。'] } }];
  const app = launch(snapshot);
  try {
    for (const button of app.$('available-actions').querySelectorAll('button')) {
      assert.equal(button.querySelector('strong').textContent, button.dataset.availableAction);
      assert.equal(button.querySelector('.action-key-meaning').textContent, '未记录');
    }
    assert.match(app.$('panel-cognition').textContent, /ACTION4向右移动/);
    assert.match(app.$('available-actions').querySelector('[data-available-action="ACTION4"]').title, /动作响应：.*向上移动/);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('invalid structured labels fail closed for confidence, identity and evidence boundaries', () => {
  const base = actorLabel('ACTION4', '右移 →', '向右移动。', 'certain', [0, 1]);
  for (const labels of [
    [{ ...base, confidence: 'unknown' }], [{ ...base, label: null }],
    [{ ...base, action: 'CUSTOM_ACTION4' }], [base, base],
    [{ ...base, evidence_sequences: [1, 0] }], [{ ...base, evidence_sequences: [2] }],
    [{ ...base, purpose: 'x'.repeat(601) }], [{ ...base, label: 'x'.repeat(25) }],
    [{ ...base, label: ' ' }], [{ ...base, purpose: ' ' }], [{ ...base, evidence_sequences: [] }],
  ]) {
    const snapshot = fixture();
    snapshot.levels[0].cognition.source_action_sequence = 1;
    snapshot.levels[0].cognition.action_labels = labels;
    const app = launch(snapshot);
    try {
      assert.match(app.$('evidence-warning').textContent, /控制台快照无法读取/);
      assert.equal(app.$('available-actions').querySelector('button'), null);
      assert.deepEqual(app.errors, []);
    } finally { app.dom.window.close(); }
  }
});

test('restored actor labels retain authenticated original evidence coordinates under provenance', () => {
  for (const [sequence, accepted] of [[68, true], [1000000001, false]]) {
    const snapshot = fixture(), level = snapshot.levels[0];
    const provenance = { run_id: 'original-actor-run', event_sequence: 93 };
    const labels = [actorLabel('ACTION4', '右移 →', '向右移动。', 'certain', [sequence])];
    level.frames[0].available_actions = ['ACTION4'];
    level.cognition_timeline = [{ scope: 'observation', frame_id: 'f0', event_sequence: 1,
      source_action_sequence: 59, provenance, action_labels: labels }];
    snapshot.process_events = [{ kind: 'model_revision', frame_id: 'f0', level: 1, event_sequence: 1,
      source_action_sequence: 59, provenance, payload: { action_labels: labels } }];
    const app = launch(snapshot);
    try {
      if (accepted) {
        const button = app.$('available-actions').querySelector('button');
        assert.equal(button.querySelector('.action-key-meaning').textContent, '右移 →');
        assert.match(button.title, /来源 original-actor-run/);
      } else assert.match(app.$('evidence-warning').textContent, /控制台快照无法读取/);
      assert.deepEqual(app.errors, []);
    } finally { app.dom.window.close(); }
  }
});

test('real assets: slider, animation/action link, tabs, compare, level switch, playback', () => {
  const app = launch(); const { dom, $, errors, requests, paints } = app;
  assert.deepEqual(errors, []);
  assert.deepEqual(requests, []);
  assert.equal(dom.window.document.querySelectorAll('.level-button').length, 3);
  assert.match($('level-2').textContent, /未开始/);
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

test('exported real HTML loads with zero external resource requests', { skip: !process.env.P7_CONSOLE_HTML }, async () => {
  const requests = [], errors = [];
  const vc = new VirtualConsole(); vc.on('jsdomError', (error) => errors.push(error));
  class NoNetwork extends ResourceLoader { fetch(url) { requests.push(url); return null; } }
  const dom = new JSDOM(fs.readFileSync(process.env.P7_CONSOLE_HTML, 'utf8'), {
    runScripts: 'dangerously', resources: new NoNetwork(), virtualConsole: vc,
    beforeParse(window) {
      window.HTMLCanvasElement.prototype.getContext = () => ({ fillRect() {}, strokeRect() {}, beginPath() {}, arc() {}, stroke() {} });
      window.fetch = async (url) => { requests.push(url); throw new Error('unexpected network'); };
    },
  });
  assert.deepEqual(errors, []);
  assert.deepEqual(requests, []);
  const snapshot=dom.window.__ASTERION_STATE__;
  assert.ok(['asterion.arc-agi3-p7-console/v1','asterion.arc-agi3-p7-console/v2'].includes(snapshot.schema));
  assert.match(dom.window.document.getElementById('frame-counter').textContent, /\d+ \/ \d+/);
  const paged=snapshot.levels.find(level=>level.frame_page && level.frame_count>32);
  if (paged) {
    assert.equal(snapshot.offline_frames,true);
    const $=id=>dom.window.document.getElementById(id),last=paged.frame_count-1,start=Math.floor(last/32)*32;
    $(`level-${paged.level}`).click();$('frame-slider').value=String(last);
    $('frame-slider').dispatchEvent(new dom.window.Event('input'));await settleReplay();
    const page=JSON.parse($(`console-frame-page-${paged.level}-${start}`).textContent);
    assert.equal($('frame-counter').textContent,`${paged.frame_count} / ${paged.frame_count}`);
    assert.match($('frame-caption').textContent,new RegExp(page.frames.find(frame=>frame.index===last).id));
    assert.equal($('board-empty').hidden,true);assert.deepEqual(requests,[]);assert.deepEqual(errors,[]);
  }
  dom.window.close();
});

const settle = async () => { for (let i = 0; i < 24; i++) await Promise.resolve(); };
const enterManual = async (app) => {
  await settle(); app.$('console-mode').value='manual'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change')); await settle();
};
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

test('idle startup selects the first catalog game instead of the embedded replay or remembered manual choice', async () => {
  const config = {token:'test-token', games:[{game_id:'ar25-test',alias:'AR25',win_levels:3}, liveConfig.games[0]]};
  const preview = {schema:'asterion.arc-agi3-p7-console/v1',generated_at:null,
    run:{game_id:'ar25-test',run_id:null,status:'preview',seed:0,win_levels:3,completed_level_count:0,
      primitive_action_count:0,target_level:1,replay_verified:false,sealed_trace:false},
    levels:[{level:1,status:'preview',frames:[{id:'initial-ar25',grid:[[12]],state:'NOT_FINISHED',levels_completed:0}],
      actions:[],decisions:[],cognition:{scope:'unavailable'},receipt:null}],decisions:[],warnings:[]};
  const app = launch(fixture(), {liveConfig:config, fetch:async url => response(url==='/api/preview/ar25-test' ? preview :
    {...idleView(),selection:{game_id:'sp80-test',level:2}})});
  try {
    await settle();
    assert.equal(app.$('game-select').value,'ar25-test');
    assert.equal(app.$('game-title').textContent,'ar25-test');
    app.tick(); await settle();
    assert.equal(app.$('game-select').value,'ar25-test');
    assert.equal(app.requests.some(entry=>entry.url==='/api/manual/open'),false);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('selected game opens real playable manual session without P7 and idle polls retain it', async () => {
  let manual = null;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/open') { const choice = JSON.parse(options.body); manual = manualView(choice.game_id, choice.game_id === 'ls20-test' ? 9 : 12, 0, choice.level); return response(manual); }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await enterManual(app);
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
    await enterManual(app);
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
    await enterManual(app);
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
    await enterManual(resumed); assert.equal(resumed.$('board-kicker').textContent, 'LEVEL 03');
    assert.equal(resumed.requests.some((entry) => entry.url === '/api/manual/open'), false);
    assert.deepEqual(resumed.errors, []);
  } finally { resumed.dom.window.close(); }
  for (const selection of [{ game_id: 'unknown', level: 3 }, { game_id: 'ls20-test', level: 8 }, { game_id: 'ls20-test', level: '3' }, null]) {
    const app = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [] } : url === '/api/manual/open' ? manualView() : { ...idleView(), selection }) });
    try {
      await enterManual(app); const body = JSON.parse(app.requests.find((entry) => entry.url === '/api/manual/open').options.body);
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
    await enterManual(app); app.$('level-3').click(); await settle();
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
    await enterManual(app); app.$('level-3').click(); await settle();
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
    await enterManual(app); hold = true; app.tick(); await settle();
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
    await enterManual(app); assert.equal(app.$('run-start').disabled, true);
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
    await enterManual(app); assert.equal(app.$('run-start').disabled, false);
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
  const app = launch(fixture(), { liveConfig, overview:replayOverview(['old-run']), fetch: async (url) => {
    if (url === '/api/manual/open') return new Promise((resolve) => { releases.push(resolve); });
    if (url === '/api/runs') return response({ runs: [{ run_id: 'old-run', game_id: 'sp80-test' }] });
    if (url === '/api/replay/old-run') return response({ ...fixture(), run: { ...fixture().run, run_id: 'old-run' } });
    return response(idleView());
  } });
  try {
    await enterManual(app); app.$('console-mode').value = 'replay'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change'));
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
    await enterManual(app);
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
    await enterManual(app);
    const button = app.$('available-actions').querySelector('[data-available-action="ACTION1"]');
    assert.doesNotMatch(app.$('available-actions').textContent,/本关未使用/);assert.match(button.textContent,/未记录/);
    assert.doesNotMatch(button.title,/本关已记录/);
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
      await enterManual(app); app.$('available-actions').querySelector('[data-available-action="ACTION1"]').click(); await settle();
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
      await enterManual(app); const canvas = app.$('board-canvas'); canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
      app.$('available-actions').querySelector('[data-available-action="ACTION6"]').click();
      canvas.dispatchEvent(new app.dom.window.MouseEvent('click', { clientX: 75, clientY: 25, bubbles: true })); await settle();
      assert.match(app.$('manual-action-status').textContent, wrongCoordinate ? /未确认/ : /已执行/);
      assert.equal(app.$('retry-command').hidden, !wrongCoordinate);
      assert.equal(app.$('manual-action-history').querySelectorAll('button').length, wrongCoordinate ? 0 : 1);
      assert.deepEqual(app.errors, []);
    } finally { app.dom.window.close(); }
  }
});

function savedManualView(game = 'sp80-test', level = 1, session = 'restored-session') {
  const observations = [manualView(game, 12, 0, level), manualView(game, 12, 1, level), manualView(game, 9, 2, level)];
  observations[2].episode_id = 2;
  observations[2].last_action = { action: 'RESET', data: {}, observation_version: 2 };
  return { ...observations[2], session_id: session, saved_levels: [1, 2], save_status: 'saved', restored: true,
    history: observations.map((view) => ({ observation_version: view.observation_version, episode_id: view.episode_id,
      action_count: view.action_count, level, frame: view.snapshot.levels[0].frames[0], last_action: view.last_action })) };
}

function restartedManualView(previous, session = 'restarted-session', save_status = 'saved') {
  const fresh = { ...manualView(previous.game_id, 12, 0, previous.level), session_id: session,
    saved_levels: previous.saved_levels, save_status, restored: false };
  fresh.history = [{ observation_version: 0, episode_id: 1, action_count: 0, level: fresh.level,
    frame: fresh.snapshot.levels[0].frames[0], last_action: null }];
  return fresh;
}

test('explicit HUMAN restart clears current history and counters, preserves actual level and other saved levels', async () => {
  let manual = savedManualView('sp80-test', 2), stale = manual;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/restart') { manual = restartedManualView(manual); return response(manual); }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await enterManual(app);
    const restart = app.$('manual-restart');
    assert.ok(restart, 'HUMAN offers an explicit clear and restart button');
    assert.equal(restart.textContent, '清空并重新开始'); assert.equal(restart.hidden, false); assert.equal(restart.disabled, false);
    restart.click(); await settle();
    const command = JSON.parse(app.requests.find((entry) => entry.url === '/api/manual/restart').options.body);
    assert.deepEqual(Object.keys(command).sort(), ['command_id', 'observation_version', 'session_id']);
    assert.equal(command.session_id, stale.session_id); assert.equal(command.observation_version, 2);
    assert.equal(typeof command.command_id, 'string');
    assert.equal(app.$('frame-counter').textContent, '1 / 1'); assert.equal(app.$('action-total').textContent, '0');
    assert.equal(app.$('manual-action-history').querySelectorAll('button').length, 0);
    assert.match(app.$('frame-caption').textContent, /观察 0 · 回合 1/);
    assert.match(app.$('board-title').textContent, /关卡 2/); assert.match(app.$('level-1').textContent, /已保存/);
    assert.match(app.$('session-id').textContent, /restarted-session/);
    assert.doesNotMatch(app.$('manual-save-status').textContent, /已恢复/);
    manual = stale; app.tick(); await settle();
    assert.equal(app.$('frame-counter').textContent, '1 / 1'); assert.equal(app.$('action-total').textContent, '0');
    assert.match(app.$('session-id').textContent, /restarted-session/);
    assert.equal(app.requests.some((entry) => entry.url === '/api/start' || entry.url === '/api/manual/action'), false);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('HUMAN restart disables historical and busy controls and stays hidden in P7', async () => {
  let manual = savedManualView(), resolveRestart;
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/manual/restart') return new Promise((resolve) => { resolveRestart = resolve; });
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await enterManual(app); assert.ok(app.$('manual-restart'));
    app.$('manual-action-history').querySelector('button').click();
    assert.equal(app.$('manual-restart').disabled, true); app.$('manual-restart').click();
    assert.equal(app.requests.some((entry) => entry.url === '/api/manual/restart'), false);
    app.$('manual-return-current').click(); app.$('manual-restart').click(); await settle();
    assert.equal(app.$('manual-restart').disabled, true); assert.equal(app.$('console-mode').disabled, true);
    app.$('manual-restart').click(); assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/restart').length, 1);
    manual = restartedManualView(manual); resolveRestart(response(manual)); await settle();
    app.$('console-mode').value = 'live'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change')); await settle();
    assert.equal(app.$('manual-restart').hidden, true); app.$('manual-restart').click(); await settle();
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/restart').length, 1);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('restart transport and failed-save responses keep exact retry identity and clear history only when saved', async () => {
  let manual = savedManualView(), calls = 0;
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/manual/restart') {
      calls += 1;
      if (calls === 1) { manual = restartedManualView(manual, 'restarted-session', 'failed'); throw new Error('lost response'); }
      manual = { ...manual, save_status: calls === 2 ? 'failed' : 'saved' }; return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await enterManual(app); assert.ok(app.$('manual-restart')); app.$('manual-restart').click(); await settle();
    assert.equal(app.$('frame-counter').textContent, '3 / 3'); assert.equal(app.$('retry-command').textContent, '重试原请求');
    app.tick(); await settle(); assert.equal(app.$('frame-counter').textContent, '3 / 3');
    app.$('retry-command').click(); await settle();
    assert.equal(app.$('frame-counter').textContent, '3 / 3'); assert.equal(app.$('retry-command').textContent, '重试原请求');
    assert.equal(app.$('manual-restart').disabled, true); assert.equal(app.$('level-2').disabled, true);
    app.$('retry-command').click(); await settle();
    assert.equal(app.$('frame-counter').textContent, '1 / 1'); assert.equal(app.$('retry-command').hidden, true);
    assert.equal(app.$('manual-action-history').querySelectorAll('button').length, 0);
    const requests = app.requests.filter((entry) => entry.url === '/api/manual/restart');
    assert.equal(requests.length, 3); assert.equal(requests[0].options.body, requests[1].options.body); assert.equal(requests[1].options.body, requests[2].options.body);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('uncertain last confirmed HUMAN frame permits restart and rejected startup remains exactly retryable', async () => {
  let manual = { ...savedManualView(), state: 'uncertain' }, calls = 0;
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/manual/restart') {
      calls += 1;
      if (calls === 1) return response({ error: 'manual-save-failed' }, 409);
      manual = restartedManualView(manual); return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await enterManual(app); assert.ok(app.$('manual-restart')); assert.equal(app.$('console-mode').value, 'manual');
    assert.equal(app.$('manual-restart').disabled, false);
    assert.ok([...app.$('available-actions').querySelectorAll('button')].every((button) => button.disabled));
    app.$('manual-restart').click(); await settle();
    assert.equal(app.$('frame-counter').textContent, '3 / 3'); assert.equal(app.$('retry-command').hidden, false);
    app.$('retry-command').click(); await settle();
    assert.equal(app.$('frame-counter').textContent, '1 / 1'); assert.equal(app.$('manual-restart').disabled, false);
    const requests = app.requests.filter((entry) => entry.url === '/api/manual/restart');
    assert.equal(requests[0].options.body, requests[1].options.body);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('restart can replace an unsaved HUMAN pose and retires its earlier save retry', async () => {
  let manual = savedManualView();
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/action') {
      const body = JSON.parse(options.body);
      manual = { ...manualView('sp80-test', 9, 3), session_id: manual.session_id, episode_id: 2,
        saved_levels: [1, 2], save_status: 'failed', restored: true, last_action: { action: body.action, data: body.data, observation_version: 3 } };
      return response(manual);
    }
    if (url === '/api/manual/restart') { manual = restartedManualView(manual); return response(manual); }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await enterManual(app); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
    assert.equal(app.$('retry-command').textContent, '重试保存');
    assert.equal(app.$('manual-restart').disabled, false); app.$('manual-restart').click(); await settle();
    assert.equal(app.$('frame-counter').textContent, '1 / 1'); assert.equal(app.$('retry-command').hidden, true);
    app.$('retry-command').click(); await settle();
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/action').length, 1);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('restart recovers the last confirmed frame after an ordinary action rejection becomes uncertain', async () => {
  let manual = savedManualView();
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/manual/action') { manual = { ...manual, state: 'uncertain' }; return response({ error: 'manual-uncertain' }, 409); }
    if (url === '/api/manual/restart') { manual = restartedManualView(manual); return response(manual); }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await enterManual(app); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
    app.tick(); await settle();
    assert.equal(app.$('frame-counter').textContent, '3 / 3'); assert.equal(app.$('manual-restart').disabled, false);
    app.$('manual-restart').click(); await settle();
    assert.equal(app.$('frame-counter').textContent, '1 / 1');
    assert.equal(app.$('available-actions').querySelector('[data-available-action="ACTION4"]').disabled, false);
    assert.equal(app.$('manual-action-status').hidden, true); assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('an old restart retry response cannot replace a later active P7 session', async () => {
  let manual = savedManualView(), current = stateWithManual(manual), resolveRetry, calls = 0;
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/manual/restart') {
      calls += 1;
      if (calls === 1) throw new Error('response lost');
      return new Promise((resolve) => { resolveRetry = resolve; });
    }
    return response(url === '/api/runs' ? { runs: [] } : current);
  } });
  try {
    await enterManual(app); app.$('manual-restart').click(); await settle(); app.$('retry-command').click(); await settle();
    current = view(); app.tick(); await settle();
    assert.equal(app.$('console-mode').value, 'live'); assert.match(app.$('session-id').textContent, /session-1/);
    resolveRetry(response(restartedManualView(manual))); await settle();
    assert.equal(app.$('console-mode').value, 'live'); assert.match(app.$('session-id').textContent, /session-1/);
    assert.equal(app.$('manual-restart').hidden, true); assert.equal(app.$('retry-command').hidden, true);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('permanent stale or expired restart rejections release controls and refresh the actual session', async () => {
  for (const code of ['observation-stale', 'session-mismatch', 'session-busy', 'manual-expired']) {
    let manual = savedManualView();
    const app = launch(fixture(), { liveConfig, fetch: async (url) => {
      if (url === '/api/manual/restart') { manual = { ...manual, state: 'expired' }; return response({ error: code }, 409); }
      return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
    } });
    try {
      await enterManual(app); app.$('manual-restart').click(); await settle();
      assert.equal(app.$('retry-command').hidden, true, code);
      assert.equal(app.$('console-mode').disabled, false, code); assert.equal(app.$('game-select').disabled, false, code);
      assert.equal(app.$('manual-close').disabled, false, code); assert.equal(app.$('manual-restart').disabled, true, code);
      assert.equal(app.$('frame-counter').textContent, '3 / 3'); assert.deepEqual(app.errors, []);
    } finally { app.dom.window.close(); }
  }
});

test('restart rejects reused identity, wrong level and uncleared counters or history', async () => {
  for (const mutate of [
    (next, previous) => { next.session_id = previous.session_id; },
    (next) => { next.level = 2; next.snapshot.levels[0].level = 2; next.history[0].level = 2; },
    (next) => { next.observation_version = 1; next.action_count = 1; next.history[0].observation_version = 1; next.history[0].action_count = 1; },
    (next) => { next.episode_id = 2; next.history[0].episode_id = 2; },
    (next) => { next.restored = true; },
    (next) => { delete next.history; },
    (next) => { next.snapshot.run.completed_level_count = 1; },
    (next) => { next.snapshot.levels[0].frames[0].state = 'WIN'; },
    (next) => { next.snapshot.levels[0].frames[0].levels_completed = 1; },
  ]) {
    let manual = savedManualView();
    const app = launch(fixture(), { liveConfig, fetch: async (url) => {
      if (url === '/api/manual/restart') { const next = restartedManualView(manual); mutate(next, manual); return response(next); }
      return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
    } });
    try {
      await enterManual(app); assert.ok(app.$('manual-restart')); app.$('manual-restart').click(); await settle();
      assert.equal(app.$('frame-counter').textContent, '3 / 3'); assert.match(app.$('session-id').textContent, /restored-session/);
      assert.equal(app.$('retry-command').hidden, false); assert.equal(app.$('manual-restart').disabled, true);
      assert.deepEqual(app.errors, []);
    } finally { app.dom.window.close(); }
  }
});

test('empty idle manual history permits saved selection to open and hydrate a resumed pose', async () => {
  const selection = { game_id: 'sp80-test', level: 1 };
  const empty = { session_id: null, game_id: null, level: null, state: 'idle', observation_version: 0,
    episode_id: 0, action_count: 0, snapshot: null, last_action: null, history: [], saved_levels: [], save_status: 'saved', restored: false };
  const app = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [] } : url === '/api/manual/open' ? savedManualView() : { ...stateWithManual(empty), selection }) });
  try {
    await enterManual(app);
    assert.equal(app.requests.filter((entry) => entry.url === '/api/manual/open').length, 1);
    assert.equal(app.$('frame-counter').textContent, '3 / 3');
    assert.match(app.$('manual-save-status').textContent, /已恢复/);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('saved manual history hydrates reload with exact edges and stable read-only historical selection', async () => {
  let manual = savedManualView();
  const app = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual)) });
  try {
    await enterManual(app);
    assert.equal(app.$('frame-counter').textContent, '3 / 3');
    assert.match(app.$('manual-action-history').textContent, /#1 ACTION4.*#2 RESET/);
    assert.match(app.$('manual-save-status').textContent, /自动保存.*已恢复/);
    assert.match(app.$('level-2').textContent, /已保存/);
    const edges = app.dom.window.__ASTERION_STATE__.levels[0].actions;
    assert.equal(edges[0].before_frame, 'manual-0'); assert.equal(edges[0].after_frame, 'manual-1');
    assert.equal(edges[0].changed_cells, 0); assert.equal(edges[1].name, 'RESET');
    const historyButton = app.$('manual-action-history').querySelector('button'); historyButton.click(); historyButton.focus();
    assert.equal(app.$('frame-counter').textContent, '2 / 3');
    app.tick(); await settle();
    assert.equal(app.$('manual-action-history').querySelector('button'), historyButton);
    assert.equal(app.dom.window.document.activeElement, historyButton);
    assert.equal(app.$('frame-counter').textContent, '2 / 3');
    assert.ok([...app.$('available-actions').querySelectorAll('button')].every((button) => button.disabled));
    manual = { ...manualView('sp80-test', 10, 3), session_id: manual.session_id, episode_id: 2, saved_levels: [1, 2], save_status: 'saved', restored: true };
    app.tick(); await settle();
    assert.equal(app.$('frame-counter').textContent, '2 / 4');
    assert.equal(app.$('manual-action-history').querySelector('button'), historyButton);
    app.$('manual-return-current').click(); assert.equal(app.$('frame-counter').textContent, '4 / 4');
    assert.equal(app.requests.some((entry) => entry.url === '/api/manual/open' || entry.url === '/api/manual/action' || entry.url === '/api/start'), false);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('switching back to a saved manual level resumes history in the new session and continues its count', async () => {
  let manual = savedManualView(), opens = 0;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/open') {
      const body = JSON.parse(options.body); opens += 1;
      manual = body.level === 1 ? savedManualView(body.game_id, 1, `restored-${opens}`) : { ...manualView(body.game_id, 10, 0, 2), session_id: `fresh-${opens}`, saved_levels: [1, 2], save_status: 'saved', restored: false };
      return response(manual);
    }
    if (url === '/api/manual/action') {
      const body = JSON.parse(options.body); manual = { ...manualView('sp80-test', 10, 3), session_id: body.session_id, episode_id: 2,
        last_action: { action: body.action, data: body.data, observation_version: 3 }, saved_levels: [1, 2], save_status: 'failed', restored: true };
      return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await enterManual(app); app.$('level-2').click(); await settle(); app.$('level-1').click(); await settle();
    assert.equal(opens, 2); assert.equal(app.$('frame-counter').textContent, '3 / 3');
    assert.match(app.$('manual-action-history').textContent, /#2 RESET/);
    app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
    const action = JSON.parse(app.requests.find((entry) => entry.url === '/api/manual/action').options.body);
    assert.equal(action.session_id, 'restored-2'); assert.equal(action.observation_version, 2);
    assert.equal(app.$('frame-counter').textContent, '4 / 4');
    assert.match(app.$('manual-save-status').textContent, /保存失败/);
    assert.doesNotMatch(app.$('manual-save-status').textContent, /自动保存/);
    assert.equal(app.requests.some((entry) => entry.url === '/api/start'), false);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('manual save status changes preserve the live buttons and explain preserved advance saves', async () => {
  let manual = { ...savedManualView(), save_status: 'pending' };
  const app = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual)) });
  try {
    await enterManual(app);
    assert.match(app.$('manual-save-status').textContent, /已保留该关原存档；继续操作后更新/);
    assert.doesNotMatch(app.$('manual-save-status').textContent, /自动保存/);
    const button = app.$('available-actions').querySelector('[data-available-action="ACTION4"]'); button.focus();
    manual = { ...manual, save_status: 'failed', saved_levels: [] }; app.tick(); await settle();
    assert.match(app.$('manual-save-status').textContent, /保存失败/);
    assert.doesNotMatch(app.$('level-1').textContent, /已保存/);
    manual = { ...manual, save_status: 'saved', saved_levels: [1, 2] }; app.tick(); await settle();
    assert.match(app.$('manual-save-status').textContent, /自动保存/);
    assert.match(app.$('level-1').textContent, /已保存/);
    assert.equal(app.$('available-actions').querySelector('[data-available-action="ACTION4"]'), button);
    assert.equal(app.dom.window.document.activeElement, button);
    assert.equal(app.$('frame-counter').textContent, '3 / 3');
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('failed automatic save retains the pose and exposes exact save retry before level or game switching', async () => {
  let manual = { ...savedManualView(), save_status: 'saved' }, calls = 0;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/action') {
      const body = JSON.parse(options.body); calls += 1;
      manual = { ...manualView('sp80-test', 10, 3), session_id: 'restored-session', episode_id: 2, saved_levels: [1, 2], restored: true,
        save_status: calls === 1 ? 'failed' : 'saved', last_action: { action: body.action, data: body.data, observation_version: 3 } };
      return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await enterManual(app); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
    assert.equal(app.$('frame-counter').textContent, '4 / 4');
    assert.match(app.$('manual-action-status').textContent, /已执行 3 次/);
    assert.equal(app.$('level-2').disabled, true); assert.equal(app.$('game-select').disabled, true);
    assert.equal(app.$('retry-command').hidden, false); assert.equal(app.$('retry-command').textContent, '重试保存');
    app.$('level-2').click(); assert.equal(app.requests.some((entry) => entry.url === '/api/manual/open'), false);
    app.$('retry-command').click(); await settle();
    const actions = app.requests.filter((entry) => entry.url === '/api/manual/action');
    assert.equal(actions.length, 2); assert.equal(actions[0].options.body, actions[1].options.body);
    assert.equal(app.$('frame-counter').textContent, '4 / 4');
    assert.equal(app.$('manual-action-history').querySelectorAll('button').length, 3);
    assert.equal(app.$('retry-command').hidden, true);
    assert.equal(app.$('level-2').disabled, false); assert.equal(app.$('game-select').disabled, false);
    assert.match(app.$('manual-save-status').textContent, /自动保存/);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('failed-save retry waits for HUMAN mode and cannot strand controls in P7 mode', async () => {
  let manual = { ...manualView(), save_status: 'saved', saved_levels: [1], restored: false }, calls = 0;
  const app = launch(fixture(), { liveConfig, fetch: async (url, options) => {
    if (url === '/api/manual/action') {
      const body = JSON.parse(options.body); calls += 1;
      manual = { ...manualView('sp80-test', 10, 1), save_status: calls === 1 ? 'failed' : 'saved', saved_levels: [1], restored: false,
        last_action: { action: body.action, data: body.data, observation_version: 1 } };
      return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await enterManual(app); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
    app.$('console-mode').value = 'live'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change')); await settle();
    assert.equal(app.$('retry-command').hidden, true);
    app.$('retry-command').click(); await settle(); assert.equal(calls, 1);
    app.$('console-mode').value = 'manual'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change')); await settle();
    assert.equal(app.$('retry-command').hidden, false); app.$('retry-command').click(); await settle();
    assert.equal(calls, 2); assert.equal(app.$('retry-command').hidden, true);
    assert.equal(app.$('game-select').disabled, false);
    assert.equal(app.$('available-actions').querySelector('[data-available-action="ACTION4"]').disabled, false);
    const actions = app.requests.filter((entry) => entry.url === '/api/manual/action');
    assert.equal(actions[0].options.body, actions[1].options.body);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('initial save failure retries the exact open without replacing its confirmed frame or session', async () => {
  let manual = null, opens = 0;
  const app = launch(fixture(), { liveConfig, fetch: async (url) => {
    if (url === '/api/manual/open') {
      opens += 1; manual = { ...manualView(), saved_levels: opens > 1 ? [1] : [], save_status: opens > 1 ? 'saved' : 'failed', restored: false };
      return response(manual);
    }
    return response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual));
  } });
  try {
    await enterManual(app); assert.equal(app.$('frame-counter').textContent, '1 / 1');
    assert.equal(app.$('retry-command').textContent, '重试保存'); assert.equal(app.$('level-2').disabled, true);
    app.$('retry-command').click(); await settle();
    const requests = app.requests.filter((entry) => entry.url === '/api/manual/open');
    assert.equal(requests.length, 2); assert.equal(requests[0].options.body, requests[1].options.body);
    assert.equal(app.$('frame-counter').textContent, '1 / 1'); assert.equal(app.$('session-id').textContent, '试玩 manual-sp80-test');
    assert.equal(app.$('retry-command').hidden, true); assert.equal(app.$('level-2').disabled, false);
    assert.equal(app.requests.some((entry) => entry.url === '/api/manual/action' || entry.url === '/api/start'), false);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('same-version full history fills actual gaps without moving historical seek or fabricating missing edges', async () => {
  const full = savedManualView();
  let manual = { ...full, history: [full.history[0], full.history[2]] };
  const app = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual)) });
  try {
    await enterManual(app); assert.equal(app.$('frame-counter').textContent, '2 / 2');
    assert.equal(app.$('manual-action-history').querySelectorAll('button').length, 0);
    assert.match(app.$('manual-history-note').textContent, /缺失/);
    app.$('frame-slider').value = '0'; app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
    manual = full; app.tick(); await settle();
    assert.equal(app.$('frame-counter').textContent, '1 / 3');
    assert.match(app.$('manual-action-history').textContent, /#1 ACTION4.*#2 RESET/);
    assert.doesNotMatch(app.$('manual-history-note').textContent, /缺失/);
    assert.ok([...app.$('available-actions').querySelectorAll('button')].every((button) => button.disabled));
    app.$('manual-return-current').click(); assert.equal(app.$('frame-counter').textContent, '3 / 3');
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('invalid saved history cannot partially replace the accepted pose or history and old replies cannot erase it', async () => {
  let manual = savedManualView();
  const app = launch(fixture(), { liveConfig, fetch: async (url) => response(url === '/api/runs' ? { runs: [] } : stateWithManual(manual)) });
  try {
    await enterManual(app); const accepted = app.dom.window.__ASTERION_STATE__;
    for (const mutate of [
      (view) => { view.history[1].frame.grid = [[99]]; },
      (view) => { view.history[1].observation_version = 0; },
      (view) => { view.history[2].frame.grid = [[1]]; },
      (view) => { view.history[2].level = 2; },
      (view) => { view.history[2].action_count = 3; },
      (view) => { view.saved_levels = [2, 1]; },
    ]) {
      manual = savedManualView(); mutate(manual); app.tick(); await settle();
      assert.equal(app.dom.window.__ASTERION_STATE__, accepted);
      assert.equal(app.$('frame-counter').textContent, '3 / 3');
      assert.match(app.$('service-status').textContent, /响应无效/);
    }
    manual = { ...manualView('sp80-test', 12, 1), session_id: 'restored-session', history: [], saved_levels: [], save_status: 'saved', restored: true };
    app.tick(); await settle();
    assert.equal(app.dom.window.__ASTERION_STATE__, accepted);
    assert.equal(app.$('frame-counter').textContent, '3 / 3');
    assert.match(app.$('level-2').textContent, /已保存/);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
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
    await enterManual(app);
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
    await enterManual(app); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
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
    await enterManual(app);
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
    await enterManual(app); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
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
    await enterManual(app); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
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
    await enterManual(app); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
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
      await enterManual(app);
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
    await enterManual(app);
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

test('manual click shows its real location immediately as pending and rejection never becomes executed', async () => {
  for (const rejected of [false, true]) {
    let release, requestBody;
    const grid64 = (view) => {
      view.snapshot.levels[0].frames[0].grid = Array.from({length: 64}, () => Array(64).fill(9));
      return view;
    };
    const manual = grid64(manualView());
    const app = launch(fixture(), {liveConfig, fetch: async (url, options) => {
      if (url === '/api/manual/action') {
        requestBody = JSON.parse(options.body);
        return new Promise((resolve) => { release = resolve; });
      }
      return response(stateWithManual(manual));
    }});
    try {
      await enterManual(app);
      const canvas = app.$('board-canvas');
      const bounds = () => ({left: 200, top: 100, width: 400, height: 400});
      canvas.getBoundingClientRect = bounds; canvas.parentElement.getBoundingClientRect = bounds;
      app.$('available-actions').querySelector('[data-available-action="ACTION6"]').click();
      assert.equal(app.$('board-canvas-click-marker').hidden, true);
      canvas.dispatchEvent(new app.dom.window.MouseEvent('click', {clientX: 201, clientY: 499, bubbles: true}));
      const marker = app.$('board-canvas-click-marker');
      assert.deepEqual(requestBody.data, {x: 0, y: 63});
      assert.equal(marker.hidden, false);
      assert.equal(marker.dataset.status, 'pending');
      assert.equal(marker.style.left, '3.125px'); assert.equal(marker.style.top, '396.875px');
      assert.match(app.$('overlay-note').textContent, /等待确认/);
      const accepted = grid64(manualView('sp80-test', 9, 1));
      accepted.last_action = {action: 'ACTION6', data: requestBody.data, observation_version: 1};
      release(rejected ? response({error: 'action-invalid'}, 409) : response(accepted));
      await settle();
      assert.equal(marker.hidden, rejected);
      if (!rejected) assert.equal(marker.dataset.status, 'recorded');
      assert.deepEqual(app.pointers, []);
      assert.deepEqual(app.errors, []);
    } finally { app.dom.window.close(); }
  }
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
    await enterManual(app); app.$('available-actions').querySelector('[data-available-action="ACTION4"]').click(); await settle();
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
      await enterManual(app); const button = app.$('available-actions').querySelector('[data-available-action="ACTION1"]');
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
    await enterManual(app);
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
  await enterManual(app);
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
  const app = launch(fixture(), { liveConfig, overview: replayOverview(['old-run']), fetch: async (url) => response(url === '/api/runs' ? { runs: [{run_id:'old-run',game_id:'sp80-test'}] } : url === '/api/replay/old-run' ? {...fixture(), run: {...fixture().run, run_id:'old-run'}} : current) });
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
  app.$('console-mode').value = 'replay'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change')); await settle();
  app.$('overview-game-list').querySelector('[data-overview-attempt]').click(); await settle();
  app.$('frame-slider').value = '1'; app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
  current = {...view(next), revision: ++revision}; app.tick(); await settle();
  assert.equal(app.$('frame-counter').textContent, '2 / 3');
  assert.equal(app.$('unavailable-current-action').querySelector('[aria-current="true"]').dataset.availableAction, 'ACTION4');
  app.$('play-toggle').click(); app.$('play-toggle').click();
  assert.equal(app.requests.some((request) => request.url === '/api/stop'), false);
  assert.equal(app.$('replay-run').hidden, true);
  assert.equal(app.$('replay-load').hidden, true);
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
  const app = launch(fixture(),{liveConfig,overview:replayOverview(['old-run']),fetch:async(url)=>{
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
  const overview=replayOverview(['old-run']);overview.games[1].runs=replayOverview(['new-run']).games[0].runs;
  const app = launch(fixture(),{liveConfig,overview,fetch:async(url)=>{
    if(url==='/api/runs') return response({runs:['old-run','new-run'].map(run_id=>({run_id,game_id:'sp80-test'}))});
    if(url.startsWith('/api/replay/')) {
      const run_id=url.split('/').at(-1);
      return new Promise(resolve=>{releases[run_id]=()=>resolve(response({...fixture(),run:{...fixture().run,run_id,game_id:run_id==='new-run'?'ls20-test':'sp80-test'}}));});
    }
    return response(view());
  }});
  try {
    await settle();
    app.$('console-mode').value='replay'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change'));
    await settle();
    app.$('overview-game-list').querySelector('[data-game-id="sp80-test"] [data-overview-attempt]').click();await settle();
    app.$('overview-game-list').querySelector('[data-game-id="ls20-test"] [data-overview-attempt]').click();await settle();
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

function researchStory() {
  const snapshot = fixture();
  snapshot.levels[0].frames = [snapshot.levels[0].frames[0]];
  snapshot.levels[0].actions = [];
  const common = { source_action_sequence: 0, observation_sha256: `sha256:${'a'.repeat(64)}`,
    level: 1, workspace_revision: 'model-1', task_id: 'task-1', origin: 'actor' };
  const entries = [
    ['compute_task', { ...common, status: 'started', operation: 'search', goal: '先打开门', obstacles: ['门未打开'], question: '开关是否持续有效', summary: '', elapsed_ms: null, completed_units: null }],
    ['model_revision', { ...common, revision: 'model-1', parent_revision: null, description_zh: '游戏规则：门保持开放。', state_summary: '角色在门外', rule_summaries: [], unknowns: ['终点条件'], coverage_summary: '只覆盖门附近', validation_summary: '已检查观察0', correction_summary: '', evidence_sequences: [0] }],
    ['plan', { ...common, plan_id: 'plan-1', status: 'proposed', goal: '进入门内', assumptions: ['门保持开放'], actions: [{name:'ACTION4',data:{}},{name:'ACTION1',data:{}}], applied_count: 0, stop_reason: null }],
    ['feedback', { ...common, origin: 'environment', plan_id: 'plan-1', expected_summary: '角色进入门内', actual_summary: '角色仍在门外', mismatch_kind: 'dynamics', unexecuted_count: 1, counterexample_sequence: 0 }],
    ['model_revision', { ...common, workspace_revision: 'model-2', revision: 'model-2', parent_revision: 'model-1', description_zh: '游戏规则：门仅开放一步。', state_summary: '角色仍在门外', rule_summaries: [], unknowns: ['终点条件'], coverage_summary: '只覆盖门附近', validation_summary: '反例观察0', correction_summary: '动作后门立即关闭', evidence_sequences: [0] }],
    ['compute_task', { ...common, workspace_revision: 'model-2', origin: 'calculation', status: 'completed', operation: 'search', goal: '先打开门', obstacles: ['门未打开'], question: '开关是否持续有效', summary: '找到一条待检验路线', elapsed_ms: 12, completed_units: 8 }],
  ];
  snapshot.process_events = entries.map(([kind,payload],i) => ({event_sequence:i+1,kind,payload,source_action_sequence:0,frame_id:'f0',level:1}));
  return snapshot;
}

test('actual event cursor distinguishes model revisions at one frame and incomplete task remains incomplete', () => {
  const app = launch(researchStory()); const { dom, $ } = app;
  const seek = (index) => { $('event-slider').value=String(index); $('event-slider').dispatchEvent(new dom.window.Event('input')); };
  assert.equal($('event-counter').textContent, '事件 6');
  assert.match($('world-guide').textContent, /门仅开放一步/);
  assert.match($('research-events').textContent, /模型预期：角色进入门内/);
  assert.match($('research-events').textContent, /实际结果：角色仍在门外/);
  assert.match($('research-events').textContent, /未执行后缀 1/);
  assert.match($('research-events').textContent, /实际用时 12 ms/);
  seek(1);
  assert.equal($('frame-counter').textContent, '1 / 1');
  assert.match($('world-guide').textContent, /门保持开放/);
  assert.doesNotMatch($('world-guide').textContent, /门仅开放一步/);
  assert.doesNotMatch($('research-events').textContent, /真实反馈|实际用时 12/);
  assert.match($('research-events').textContent, /尚无结束记录/);
  seek(0);
  assert.doesNotMatch($('world-guide').textContent, /使物件向右移动|门保持开放|门仅开放一步/);
  assert.equal($('research-revision').textContent, '模型版本未关联');
  seek(4);
  assert.equal($('research-revision').textContent, '模型 model-2');
  assert.match($('research-events').textContent, /差异类别：dynamics/);
  assert.deepEqual(app.errors, []); dom.window.close();
});

test('live historical event cursor stays read-only across polls and pause/resume requires acknowledged lifecycle', async () => {
  let current = { ...view(researchStory()), state: 'running', revision: 1 };
  const app = launch(researchStory(), { liveConfig, fetch: async (url, options={}) => {
    if (url === '/api/runs') return response({ runs: [] });
    if (['/api/pause','/api/resume','/api/stop'].includes(url)) {
      const body = JSON.parse(options.body);
      assert.equal(body.session_id, 'session-1');
      current = {...current, revision: current.revision+1, state: url==='/api/pause' ? 'pause_requested' : url==='/api/resume' ? 'resume_requested' : 'stopping'};
      return response(current);
    }
    return response(current);
  }});
  await settle();
  app.$('event-slider').value='1'; app.$('event-slider').dispatchEvent(new app.dom.window.Event('input'));
  assert.equal(app.$('run-pause').disabled, true);
  assert.equal(app.$('event-return-current').hidden, false);
  current={...current,revision:2}; app.tick(); await settle();
  assert.equal(app.$('event-counter').textContent,'事件 2');
  assert.match(app.$('world-guide').textContent,/门保持开放/);
  assert.equal(app.requests.some((request)=>request.url==='/api/pause'), false);
  app.$('event-return-current').click();
  assert.equal(app.$('event-counter').textContent,'事件 6');
  assert.equal(app.$('run-pause').disabled,false);
  app.$('run-pause').click(); await settle();
  assert.match(app.$('service-status').textContent,/暂停已请求/);
  assert.equal(app.$('run-resume').disabled,true);
  assert.equal(app.$('run-start').disabled,true);
  app.$('console-mode').value='manual'; app.$('console-mode').dispatchEvent(new app.dom.window.Event('change'));
  assert.equal(app.$('console-mode').value,'live');
  current={...current,state:'paused',revision:current.revision+1}; app.tick(); await settle();
  assert.equal(app.$('run-resume').disabled,false);
  app.$('run-resume').click(); await settle();
  assert.match(app.$('service-status').textContent,/继续已请求/);
  current={...current,state:'running',revision:current.revision+1}; app.tick(); await settle();
  app.$('event-slider').value='1'; app.$('event-slider').dispatchEvent(new app.dom.window.Event('input'));
  app.$('run-stop').click(); await settle();
  assert.equal(app.requests.filter((request)=>request.url==='/api/stop').length,1);
  assert.deepEqual(app.errors,[]);app.dom.window.close();
});


const catalog25 = { token: 'test-token', games: Array.from({length:25}, (_, i) => ({game_id:`game${i}-catalog`,alias:`G${i}`,win_levels:i+2})) };
function replayOverview(ids) { const overview=overviewFixture(liveConfig); overview.games[0].runs=ids.map(run_id=>({run_id,status:'incomplete',completed_levels:0,primitive_actions:0,restoration_actions:0,new_solver_actions:0,verified:false}));return overview; }
const catalogRun = (run_id, status='incomplete', verified=true) => ({run_id,status,completed_levels:1,primitive_actions:12,restoration_actions:4,new_solver_actions:8,verified});
const overviewRow = (app, game=0) => app.$('overview-game-list').querySelector(`[data-game-id="game${game}-catalog"]`);

test('unplayed game shows a readonly initial preview and a late preview cannot replace another selection', async () => {
  const config = {token:'test-token',games:[{game_id:'first-test',alias:'first',win_levels:2},
                                         {game_id:'second-test',alias:'second',win_levels:2}]};
  const preview = (game_id, color, level=1) => ({schema:'asterion.arc-agi3-p7-console/v1',generated_at:null,
    run:{game_id,run_id:null,status:'preview',seed:0,win_levels:2,completed_level_count:0,
         target_level:level,primitive_action_count:0,replay_verified:false,sealed_trace:false},
    levels:[{level,status:'preview',frames:[{id:'preview-initial',grid:Array.from({length:64},()=>Array(64).fill(color)),
      available_actions:['ACTION1','ACTION6','RESET'],state:'NOT_FINISHED',levels_completed:level-1}],
      actions:[],decisions:[],cognition:{scope:'unavailable'},receipt:null}],decisions:[],warnings:[]});
  let release, releaseLevel;
  const app = launch(fixture(), {liveConfig:config,fetch:async url=>{
    if(url==='/api/preview/first-test')return new Promise(resolve=>{release=resolve;});
    if(url==='/api/preview/second-test')return response(preview('second-test',9));
    if(url==='/api/preview/second-test/2')return new Promise(resolve=>{releaseLevel=resolve;});
    return response(idleView());
  }});
  try {
    await settle(); assert.ok(release);
    changeGame(app,'second-test'); await settle();
    assert.equal(app.$('game-title').textContent,'second-test');
    assert.equal(app.$('board-empty').hidden,true);
    assert.match(app.$('frame-caption').textContent,/关卡初始预览 · 尚未开始/);
    assert.match(app.$('run-id').textContent,/尚未启动 P7/);
    assert.equal(app.$('board-canvas').width,512);
    assert.equal(app.$('action-total').textContent,'0');
    assert.equal(app.$('console-mode').value,'replay');
    assert.ok([...app.$('available-actions').querySelectorAll('button')].every(button=>button.disabled));
    app.$('level-2').click(); await settle();
    assert.ok(releaseLevel);
    assert.equal(app.$('board-empty').hidden,false);
    assert.match(app.$('level-2').getAttribute('aria-label'),/尚未开始/);
    app.$('level-1').click(); await settle();
    releaseLevel(response(preview('second-test',12,2))); await settle();
    assert.equal(app.$('level-1').getAttribute('aria-current'),'true');
    assert.equal(app.paints.at(-1),'#1E93FF');
    app.$('level-2').click(); await settle();
    assert.equal(app.$('board-empty').hidden,true);
    assert.equal(app.paints.at(-1),'#FF851B');
    assert.equal(app.dom.window.__ASTERION_STATE__.run.completed_level_count,0);
    assert.equal(app.dom.window.__ASTERION_STATE__.run.target_level,2);
    assert.equal(app.dom.window.__ASTERION_STATE__.levels[1].frames[0].levels_completed,1);
    assert.equal(app.$('action-total').textContent,'0');
    assert.ok([...app.$('available-actions').querySelectorAll('button')].every(button=>button.disabled));
    app.$('level-1').click(); await settle();
    release(response(preview('first-test',12))); await settle();
    assert.equal(app.$('game-title').textContent,'second-test');
    assert.equal(app.paints.at(-1),'#1E93FF');
    assert.equal(app.requests.some(entry=>['/api/manual/open','/api/manual/action','/api/start'].includes(entry.url)),false);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('recorded games load readonly previews for missing levels without replacing their attempt', async () => {
  for (const [gameId, winLevels, selectedLevel, controller] of [['three-test', 3, 3], ['six-test', 6, 6], ['nine-test', 9, 5], ['live-controller-test', 4, 4, true]]) {
    const snapshot = fixture();
    snapshot.run = {...snapshot.run, game_id:gameId, run_id:'active-attempt', seed:0, win_levels:winLevels, sealed_trace:false};
    snapshot.levels = [snapshot.levels[0]];
    const config = {token:'test-token', games:[{game_id:gameId, alias:gameId, win_levels:winLevels}]};
    const overview = overviewFixture(config);
    overview.games[0] = {...overview.games[0], status:'running', active_run_id:'active-attempt', recording_run_id:'active-attempt',
      runs:[{...catalogRun('active-attempt','running',false), completed_levels:0, recording:true}]};
    let releasePreview;
    const preview = {schema:'asterion.arc-agi3-p7-console/v1',generated_at:null,
      run:{game_id:gameId,run_id:null,status:'preview',seed:0,win_levels:winLevels,completed_level_count:0,
        target_level:selectedLevel,primitive_action_count:0,replay_verified:false,sealed_trace:false},
      levels:[{level:selectedLevel,status:'preview',frames:[{id:'initial-selected',grid:[[12,12],[12,12]],
        state:'NOT_FINISHED',levels_completed:selectedLevel-1,available_actions:['ACTION1','RESET']}],
        actions:[],decisions:[],cognition:{scope:'unavailable'},receipt:null}],decisions:[],warnings:[]};
    let revision=1;
    const app = launch(snapshot,{liveConfig:config,overview,fetch:async url=>{
      if(controller && url==='/api/state')return response({...view(snapshot),revision:revision++});
      if(url==='/api/replay/active-attempt')return response(snapshot);
      if(url===`/api/preview/${gameId}/${selectedLevel}`)return new Promise(resolve=>{releasePreview=resolve;});
      return response(idleView());
    }});
    try {
      await settle(); app.$(`level-${selectedLevel}`).click(); await settle();
      assert.ok(releasePreview, 'missing recorded level requests its actual initial frame');
      app.tick();await settle();
      assert.equal(app.$(`level-${selectedLevel}`).getAttribute('aria-current'),'true','same-run polls must not starve a pending preview');
      releasePreview(response(preview)); await settle();
      assert.equal(app.$('board-empty').hidden,true);
      assert.match(app.$('frame-caption').textContent,/关卡初始预览/);
      assert.equal(app.dom.window.__ASTERION_STATE__.run.run_id,'active-attempt');
      assert.equal(app.dom.window.__ASTERION_STATE__.levels.length,1);
      app.tick(); await settle();
      assert.equal(app.$(`level-${selectedLevel}`).getAttribute('aria-current'),'true');
      assert.equal(app.$('board-empty').hidden,true);
      assert.ok([...app.$('available-actions').querySelectorAll('button')].every(button=>button.disabled));
      assert.equal(app.requests.some(entry=>['/api/start','/api/manual/open','/api/manual/action'].includes(entry.url)),false);
      assert.deepEqual(app.errors,[]);
    } finally { app.dom.window.close(); }
  }
});

test('a redo preserves saved level counts and uses saved frames only where its own observations are absent', async () => {
  const gameId='saved-levels-test', config={token:'test-token',games:[{game_id:gameId,alias:'saved',win_levels:6,baseline_actions:[10,15,20,25,30,35]}]};
  const active=fixture(); active.run={...active.run,game_id:gameId,run_id:'redo-attempt',seed:0,win_levels:6,completed_level_count:1,sealed_trace:false};
  active.levels=[{...active.levels[0],status:'successful'}, {...active.levels[0],level:2,status:'incomplete',
    frames:[{id:'redo-level2',grid:[[9,9],[9,9]],state:'NOT_FINISHED',levels_completed:1}],actions:active.levels[0].actions}];
  const saved=fixture(); saved.run={...saved.run,game_id:gameId,run_id:'saved-four',seed:0,win_levels:6,completed_level_count:4,replay_verified:true,sealed_trace:true};
  saved.levels=[9,12,7,5].map((count,index)=>({...fixture().levels[0],level:index+1,status:'successful',
    frames:[{id:`saved-f${index}`,grid:[[12,12],[12,12]],state:'NOT_FINISHED',levels_completed:index}],
    actions:Array.from({length:count},(_,i)=>({id:`saved-a${index}-${i}`,name:'ACTION1',before_frame:`saved-f${index}`,after_frame:`saved-f${index}`,data:{}})),
    decisions:[],cognition:{scope:'final',stable_description:`游戏规则：保存关卡 ${index+1} 的认知。`,updates:[]}}));
  const overview=overviewFixture(config);
  overview.games[0]={...overview.games[0],status:'running',active_run_id:'redo-attempt',completed_levels:4,best_run_id:'saved-four',recording_run_id:'redo-attempt',
    runs:[{...catalogRun('saved-four'),completed_levels:4},{...catalogRun('redo-attempt','running',false),recording:true}]};
  const app=launch(active,{liveConfig:config,overview,fetch:async url=>{
    if(url==='/api/replay/redo-attempt')return response(active);
    if(url==='/api/replay/saved-four')return response(saved);
    return response(idleView());
  }});
  try {
    await settle();
    assert.match(app.$('level-2').title,/已保存.*12 动作/, JSON.stringify(app.requests.map(entry=>entry.url)) + String(app.errors));
    assert.match(app.$('level-3').title,/已保存.*7 动作/);
    app.$('level-2').click(); await settle();
    assert.equal(app.paints.at(-1),'#1E93FF');
    assert.match(app.$('level-efficiency').textContent,/已保存.*12 动作/);
    assert.match(app.$('level-efficiency').textContent,/本次.*1 动作/);
    app.$('level-3').click(); await settle();
    assert.equal(app.$('board-empty').hidden,true);
    assert.match(app.$('frame-caption').textContent,/已保存.*saved-four/);
    assert.match(app.$('world-guide').textContent,/保存关卡 3 的认知/);
    app.tick(); await settle();
    assert.equal(app.$('level-3').getAttribute('aria-current'),'true');
    assert.match(app.$('level-3').title,/已保存.*7 动作/);
    assert.equal(app.dom.window.__ASTERION_STATE__.run.run_id,'redo-attempt');
    assert.equal(app.dom.window.__ASTERION_STATE__.run.completed_level_count,1);
    assert.equal(app.dom.window.__ASTERION_STATE__.levels.length,2);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('saved level sources survive improved routes, continuation, game changes and stale polls', async () => {
  const gameId='route-transition-test', otherId='preview-transition-test';
  const config={token:'test-token',games:[{game_id:gameId,alias:'route',win_levels:9,baseline_actions:[20,50,35,26,40,40,40,40,40]},
    {game_id:otherId,alias:'preview',win_levels:6}]};
  const record=(id,counts,{saved=false,firstLevel=1,color=12}={})=>({schema:'asterion.arc-agi3-p7-console/v1',generated_at:null,
    run:{game_id:gameId,run_id:id,seed:0,win_levels:9,status:saved?'incomplete':'running',completed_level_count:saved?counts.length:1,
      primitive_action_count:counts.reduce((a,b)=>a+b,0),replay_verified:saved,sealed_trace:saved},
    levels:counts.map((count,index)=>({level:index+firstLevel,status:saved?'successful':'incomplete',
      frames:[0,1,2].map(frame=>({id:`${id}-l${index+firstLevel}-f${frame}`,grid:[[color,color],[color,color]],state:'NOT_FINISHED',levels_completed:index})),
      actions:Array.from({length:count},(_,i)=>({id:`${id}-l${index+firstLevel}-a${i}`,name:'ACTION1',data:{}})),decisions:[],
      cognition:{scope:'final',stable_description:`游戏规则：${id} 第 ${index+firstLevel} 关认知。`,updates:[]}})),decisions:[],warnings:[]});
  const original=record('original-four',[19,49,34,25],{saved:true});
  const improved=record('improved-four',[19,40,34,25],{saved:true,color:14});
  const redo=record('retry-level2',[18],{firstLevel:2,color:9});
  const next=record('next-level5',[2],{firstLevel:5,color:10});
  let overview=overviewFixture(config), best=original, active=redo, holdPoll=false, releasePoll, releaseImproved;
  const updateOverview=()=>{
    overview.games[0]={...overview.games[0],status:'running',active_run_id:active.run.run_id,completed_levels:4,best_run_id:best.run.run_id,recording_run_id:active.run.run_id,
      runs:[{...catalogRun(best.run.run_id),completed_levels:4,execution_mode:best===improved?'offline-replay':null},
        {...catalogRun(active.run.run_id,'running',false),recording:true}]};
  };
  updateOverview();
  const preview={schema:'asterion.arc-agi3-p7-console/v1',generated_at:null,
    run:{game_id:otherId,run_id:null,status:'preview',seed:0,win_levels:6,completed_level_count:0,primitive_action_count:0,target_level:1,replay_verified:false,sealed_trace:false},
    levels:[{level:1,status:'preview',frames:[{id:'real-initial',grid:[[15]],state:'NOT_FINISHED',levels_completed:0}],actions:[],decisions:[],cognition:{scope:'unavailable'},receipt:null}],decisions:[],warnings:[]};
  const app=launch(redo,{liveConfig:config,overview:()=>overview,fetch:async url=>{
    if(url==='/api/replay/original-four')return response(original);
    if(url==='/api/replay/improved-four')return new Promise(resolve=>{releaseImproved=resolve;});
    if(url==='/api/replay/retry-level2')return holdPoll?new Promise(resolve=>{releasePoll=resolve;}):response(redo);
    if(url==='/api/replay/next-level5')return response(next);
    if(url===`/api/preview/${otherId}`)return response(preview);
    return response(idleView());
  }});
  const refresh=()=>[...app.timers.values()].find(fn=>fn.intervalMs===5000)();
  const assertSaved=counts=>counts.forEach((count,index)=>assert.equal(app.$(`level-${index+1}`).querySelector('.level-step-count').textContent,`${count} 动作`));
  try {
    await settle(); assertSaved([19,49,34,25]);
    app.$('level-2').click();await settle();
    assert.match(app.$('level-efficiency').textContent,/已保存.*49 动作.*本次 18 动作/);
    best=improved;updateOverview();refresh();await settle();assert.ok(releaseImproved);
    assert.match(app.$('level-2').title,/历史已保存.*最佳路线刷新中.*49 动作/);
    assert.equal(app.$('level-2').dataset.savedSourceRunId,'original-four');
    assert.equal(app.$('level-2').dataset.savedCurrentBest,'false');
    assert.match(app.$('level-efficiency').textContent,/历史已保存.*最佳路线刷新中.*49 动作.*本次 18 动作/);
    app.$('level-4').click();await settle();releaseImproved(response(improved));await settle();
    // A late saved response updates authority, but cannot select the level that requested it.
    assert.equal(app.$('level-4').getAttribute('aria-current'),'true');
    app.$('level-3').click();await settle();assertSaved([19,40,34,25]);
    assert.equal(app.$('level-2').dataset.savedSourceRunId,'improved-four');
    assert.equal(app.$('level-2').dataset.savedCurrentBest,'true');
    assert.doesNotMatch(app.$('level-2').title,/49 动作|刷新中/);
    assert.match(app.$('world-guide').textContent,/improved-four 第 3 关认知/);
    assert.match(app.$('frame-caption').textContent,/已保存.*improved-four.*离线 SDK 路线验证/);
    app.$('frame-slider').value='1';app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
    app.$('play-toggle').click();const playback=[...app.timers.values()].find(fn=>fn.intervalMs!==1000&&fn.intervalMs!==2000&&fn.intervalMs!==5000);
    assert.ok(playback);refresh();await settle();
    assert.equal(app.$('frame-slider').value,'1');assert.ok([...app.timers.values()].includes(playback));
    active=next;updateOverview();refresh();await settle();assertSaved([19,40,34,25]);
    assert.equal(app.dom.window.__ASTERION_STATE__.run.run_id,'next-level5');
    assert.equal(app.$('level-3').getAttribute('aria-current'),'true');assert.equal(app.$('frame-slider').value,'1');
    assert.match(app.$('world-guide').textContent,/improved-four 第 3 关认知/);
    // An obsolete poll cannot put the prior attempt back after game selection.
    active=redo;updateOverview();refresh();await settle();holdPoll=true;
    const poll=[...app.timers.values()].find(fn=>fn.intervalMs===2000);poll();await settle();assert.ok(releasePoll);
    changeGame(app,otherId);await settle();assert.match(app.$('frame-caption').textContent,/关卡初始预览/);
    releasePoll(response(redo));await settle();assert.equal(app.dom.window.__ASTERION_STATE__.run.game_id,otherId);
    holdPoll=false;active=next;updateOverview();changeGame(app,gameId);await settle();assertSaved([19,40,34,25]);
    app.$('level-4').click();await settle();assert.match(app.$('world-guide').textContent,/improved-four 第 4 关认知/);
    assert.equal(app.$('single-board').dataset.sourceRunId,'improved-four');
    assert.equal(app.dom.window.__ASTERION_STATE__.run.completed_level_count,1);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('saved route is the default after an attempt ends and latest attempt is an explicit pinned view', async () => {
  const config = {token:'test-token',games:[{game_id:'sp80-test',alias:'SP80',win_levels:3}]};
  const replay = (id, count) => {
    const snapshot = fixture(); snapshot.run.run_id = id; snapshot.run.sealed_trace = true;
    snapshot.levels[0].actions = Array.from({length:count}, (_,i)=>({...snapshot.levels[0].actions[0],id:`a${i}`}));
    return snapshot;
  };
  let overview = overviewFixture(config);
  overview.games[0] = {...overview.games[0],best_run_id:'a-saved-full',completed_levels:3,
    recording_run_id:'z-new-attempt',runs:[{...catalogRun('a-saved-full'),completed_levels:3},
    {...catalogRun('z-new-attempt','running',false),recording:true}]};
  const app = launch(fixture(),{liveConfig:config,overview:()=>overview,fetch:async url=>response(
    url==='/api/replay/a-saved-full'?replay('a-saved-full',3):url==='/api/replay/z-new-attempt'?replay('z-new-attempt',11):idleView())});
  try {
    await settle(); assert.equal(app.$('run-id').textContent,'a-saved-full');
    delete overview.games[0].recording_run_id; overview.games[0].runs[1].recording=false;
    overview.games[0].runs[1].status='cancelled';
    const refresh = [...app.timers.values()].find(fn=>fn.intervalMs===5000);
    refresh(); await settle(); assert.equal(app.$('run-id').textContent,'a-saved-full');
    assert.match(app.$('level-1').title,/3 动作/);
    app.$('overview-game-list').querySelector('[data-overview-attempt]').click(); await settle();
    assert.equal(app.$('run-id').textContent,'z-new-attempt');
    refresh(); await settle(); assert.equal(app.$('run-id').textContent,'z-new-attempt');
    app.$('overview-game-list').querySelector('[data-overview-watch]').click(); await settle();
    assert.equal(app.$('run-id').textContent,'a-saved-full');
    overview.games[0].latest_run_id='a-saved-full';
    refresh(); await settle(); assert.equal(app.$('run-id').textContent,'a-saved-full');
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('verified saved completion stays separate from a fresh attempt and its current level observations', async () => {
  for (const observedSecondLevel of [false, true]) {
    const snapshot = fixture();
    snapshot.run = {...snapshot.run, game_id: 'vc33-test', run_id: 'new-attempt', seed: 0,
                    win_levels: 7, completed_level_count: 1};
    snapshot.levels = Array.from({length: 7}, (_, index) => ({
      ...fixture().levels[index ? 1 : 0], level: index + 1,
      status: index === 0 ? 'successful' : 'not_run',
    }));
    if (observedSecondLevel) Object.assign(snapshot.levels[1], {
      status: 'incomplete', frames: fixture().levels[0].frames, actions: fixture().levels[0].actions,
    });
    const original = JSON.stringify(snapshot);
    const config = {token: 'test-token', games: [{game_id: 'vc33-test', alias: 'vc33', win_levels: 7}]};
    let overview = overviewFixture(config);
    overview.games[0] = {...overview.games[0], completed_levels: 7, status: 'running', score: '100.000000',
      best_run_id: 'old-completed', recording_run_id: 'new-attempt',
      runs: [{...catalogRun('old-completed', 'completed'), completed_levels: 7},
             {...catalogRun('new-attempt', 'running', false), recording: true}]};
    const app = launch(snapshot, {liveConfig: config, overview: () => overview, fetch: async () => response(view(snapshot))});
    try {
      await settle();
      assert.match(app.$('run-progress-summary').textContent, /游戏已保存 7 \/ 7 · 本轮 1 \/ 7/);
      for (let level = 2; level <= 7; level++) {
        assert.match(app.$(`level-${level}`).title, /已有过关记录/);
        assert.equal(app.$(`level-${level}`).querySelector('.level-step-count').textContent, '步数待读取');
        if (level !== 2 || !observedSecondLevel) {
          assert.match(app.$(`level-${level}`).title, /本轮未运行/);
          assert.doesNotMatch(app.$(`level-${level}`).textContent, /0步/);
        }
      }
      app.$('level-2').click();
      assert.equal(app.$('level-status').textContent, observedSecondLevel ? '本轮进行中' : '本轮未运行');
      assert.match(app.$('level-saved-status').textContent, /已有过关记录/);
      assert.equal(app.$('board-empty').hidden, observedSecondLevel);
      assert.equal(JSON.stringify(snapshot), original);
      overview = {};
      [...app.timers.values()].find((fn) => fn.intervalMs === 5000)(); await settle();
      assert.equal(app.$('level-2').querySelector('.level-verified-badge'), null);
      assert.equal(app.$('level-saved-status').hidden, true);
      assert.deepEqual(app.errors, []);
    } finally { app.dom.window.close(); }
  }
  const staticApp = launch(fixture());
  assert.match(staticApp.$('level-2').textContent, /未开始/);
  assert.equal(staticApp.$('level-2').querySelector('.level-verified-badge'), null);
  staticApp.dom.window.close();
});

test('live game aggregate 100 does not replace completed level efficiency 40.50', async () => {
  const snapshot = fixture(), level = snapshot.levels[0];
  level.status = 'successful';
  level.actions = Array.from({length: 11}, (_, index) => ({...level.actions[0], id: `a${index + 1}`}));
  const config = {token: 'test-token', games: [{game_id: 'sp80-test', alias: 'SP80', win_levels: 3,
                                              baseline_actions: [7, 11, 12]}]};
  const overview = overviewFixture(config);
  overview.games[0].score = '100.000000';
  const app = launch(snapshot, {liveConfig: config, overview, fetch: async () => response(view(snapshot))});
  try {
    await settle();
    assert.equal(app.$('overview-game-list').firstElementChild.children[2].textContent, '100.00');
    assert.match(app.$('level-efficiency').textContent, /基准 7 \/ 11 动作 \/ 关卡效率 40.50 分/);
    assert.match(app.$('level-1').title, /关卡效率 40.50 分/);
    app.$('level-2').click();
    await settle();
    assert.match(app.$('level-efficiency').textContent, /基准 11 \/ 0 动作 \/ 关卡效率待完成/);
    assert.equal(app.$('level-efficiency').classList.contains('efficiency-low'), false);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});

test('local overview renders each catalog game once and uses actual catalog totals and two-decimal score displays', async () => {
  const overview = overviewFixture(catalog25);
  overview.totals = {...overview.totals,score:'1.234567',completed_levels:1,saved_route_actions:8,primitive_actions:15,restoration_actions:4,new_solver_actions:8,actions_pending:3};
  overview.games[0] = {...overview.games[0],completed_levels:1,status:'partial',score:'2.500000',route_actions:8,runs:[catalogRun('best-one')],best_run_id:'best-one',resume_run_id:'best-one'};
  const app = launch(fixture(),{liveConfig:catalog25,overview,fetch:async url=>url==='/api/manual/open'?response({},503):response(url==='/api/runs'?{runs:[]}:idleView())});
  try {
    await settle(); app.tick(); await settle();
    const rows=[...app.$('overview-game-list').children];
    assert.equal(rows.length,25); assert.equal(new Set(rows.map(row=>row.dataset.gameId)).size,25);
    assert.equal(app.$('overview-score').textContent,'1.23');
    assert.equal(app.$('overview-games').textContent,'0 / 25');
    assert.equal(app.$('overview-levels').textContent,'1 / 350');
    assert.match(app.$('overview').textContent,/本地总分|保存路线|热启动|官网冷启动/);
    assert.equal(app.$('overview-actions').textContent,'8');
    assert.match(app.$('overview').textContent,/游戏动作总计/);
    assert.match(app.$('overview-action-breakdown').textContent,/全部尝试 15 · 恢复 4 · 新增求解 8 · 待封存分账 3/);
    assert.equal(overviewRow(app).children[2].textContent,'2.50');
    assert.equal(overviewRow(app).querySelector('[data-overview-watch]').textContent,'回放');
    assert.equal(overviewRow(app).querySelector('[data-overview-attempt]').textContent,'尝试');
    assert.equal(overviewRow(app).querySelector('[data-overview-start]').textContent,'继续');
    assert.equal(overviewRow(app).querySelector('[data-overview-fresh]').textContent,'重玩');
    overview.games[0].status='completed'; app.tick(); await settle();
    assert.equal(overviewRow(app).querySelector('[data-overview-start]').hidden,true);
    assert.equal([...app.timers.values()].some(fn=>fn.intervalMs===5000),true);
    assert.equal(app.requests.filter(r=>r.url==='/api/runs').length,0);
    assert.deepEqual(app.errors,[]);
  } finally { app.dom.window.close(); }
});

test('game action total shows 793 saved-route actions while 2994 all-attempt actions stay secondary', async () => {
  const config = {token:'test-token',games:Array.from({length:3},(_,i)=>({game_id:`count${i}-test`,alias:`C${i}`,win_levels:7}))};
  const overview = overviewFixture(config);
  overview.games.forEach((game,i)=>{game.route_actions=[474,143,176][i];});
  overview.totals = {...overview.totals,saved_route_actions:793,primitive_actions:2994,
                     restoration_actions:1811,new_solver_actions:1183};
  const app = launch(fixture(),{liveConfig:config,overview,fetch:async()=>response(idleView())});
  try {
    await settle();
    assert.equal(app.$('overview-actions').textContent,'793');
    assert.match(app.$('overview-action-breakdown').textContent,/全部尝试 2994 · 恢复 1811 · 新增求解 1183/);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('game selection exposes partial failure runs and continue sends the exact saved route and complete game target', async () => {
  const overview=overviewFixture(catalog25);
  overview.games[1]={...overview.games[1],status:'partial',completed_levels:1,best_run_id:'best-two',resume_run_id:'best-two',runs:[catalogRun('failed-two','failed',false),catalogRun('best-two')]};
  overview.games[0]={...overview.games[0],runs:[catalogRun('other-game')]};
  const app=launch(fixture(),{liveConfig:catalog25,overview,fetch:async(url)=>url==='/api/manual/open'?response({},503):response(url==='/api/runs'?{runs:[]}:idleView())});
  try {
    await settle(); overviewRow(app,1).querySelector('[data-overview-select]').click(); await settle();
    assert.equal(app.$('game-select').value,'game1-catalog');
    assert.deepEqual([...app.$('replay-run').options].map(option=>option.value),['failed-two','best-two']);
    assert.equal(app.$('run-start').textContent,'继续 P7');
    overviewRow(app,1).querySelector('[data-overview-start]').click(); await settle();
    const body=JSON.parse(app.requests.find(request=>request.url==='/api/start').options.body);
    assert.equal(body.game_id,'game1-catalog');assert.equal(body.target_level,3);assert.equal(body.resume_run_id,'best-two');
    assert.equal(typeof body.command_id,'string');
    assert.deepEqual(app.errors,[]);
  } finally { app.dom.window.close(); }
});

test('unplayed games start fresh, completed games require explicit restart, and missing overview never falls back fresh', async () => {
  for (const kind of ['unplayed','completed','missing']) {
    const overview=overviewFixture(catalog25); overview.games[0].status=kind==='completed'?'completed':'unplayed';
    const app=launch(fixture(),{liveConfig:catalog25,overview:kind==='missing'?null:overview,fetch:async(url)=>url==='/api/manual/open'?response({},503):response(url==='/api/runs'?{runs:[]}:url==='/api/overview'?{}:idleView())});
    try {
      await settle(); app.$('run-start').click(); await settle();
      if (kind==='completed') { assert.equal(app.$('run-start').disabled,true); assert.equal(app.requests.some(r=>r.url==='/api/start'),false); app.$('run-fresh').click(); await settle(); }
      const starts=app.requests.filter(r=>r.url==='/api/start');
      assert.equal(starts.length,kind==='missing'?0:1);
      if (starts.length) { const body=JSON.parse(starts[0].options.body); assert.equal(body.target_level,2);assert.equal(Object.hasOwn(body,'resume_run_id'),false); }
      assert.deepEqual(app.errors,[]);
    } finally { app.dom.window.close(); }
  }
});

test('external unsealed replay polling preserves chosen history, switches runs without stale updates, and stops after sealing', async () => {
  const overview=overviewFixture(catalog25);
  overview.guest_busy=true;overview.start_ready=false;overview.start_block_reason='session-busy';
  overview.games[0]={...overview.games[0],status:'running',active_run_id:'external-one',runs:[catalogRun('external-one','running',false)]};
  overview.games[1]={...overview.games[1],active_run_id:'external-two',runs:[catalogRun('external-two')]};
  let replay={...researchStory(),run:{...fixture().run,run_id:'external-one',game_id:'game0-catalog',win_levels:2,sealed_trace:false,status:'incomplete'}};
  let delayed=null,hold=false;
  const app=launch(fixture(),{liveConfig:catalog25,overview,fetch:async(url)=>{
    if(url==='/api/runs')return response({runs:[]});
    if(url==='/api/manual/open')return response({},503);
    if(url==='/api/replay/external-one'){if(hold)return new Promise(resolve=>{delayed=resolve;});return response(replay);}
    if(url==='/api/replay/external-two')return response({...replay,run:{...replay.run,run_id:'external-two',game_id:'game1-catalog',sealed_trace:true}});
    return response(idleView());
  }});
  try {
    await settle(); const row=overviewRow(app); assert.equal(row.querySelector('.overview-result-badge').textContent,'尚未通关'); assert.equal(row.querySelector('.overview-activity-badge').textContent,'● 解题中'); assert.match(row.querySelector('.overview-activity-badge').title,/外部只读/); assert.doesNotMatch(row.textContent,/外部只读/);
    assert.equal(row.querySelector('[data-overview-start]').disabled,true);
    row.querySelector('[data-overview-watch]').click();await settle();
    assert.equal(app.$('run-pause').disabled,true);assert.equal(app.$('run-stop').disabled,true);
    assert.equal([...app.timers.values()].some(fn=>fn.intervalMs===2000),true);
    app.$('event-slider').value='1';app.$('event-slider').dispatchEvent(new app.dom.window.Event('input'));
    assert.match(app.$('world-guide').textContent,/门保持开放/);
    replay={...replay,process_events:[...replay.process_events,{...replay.process_events.at(-1),event_sequence:7}]};
    app.tick();await settle();assert.equal(app.$('event-counter').textContent,'事件 2');assert.match(app.$('world-guide').textContent,/门保持开放/);
    app.$('replay-follow').click();assert.equal(app.$('event-counter').textContent,'事件 7');
    hold=true;app.tick();await settle();
    overviewRow(app,1).querySelector('[data-overview-select]').click();await settle();
    assert.equal(app.$('run-id').textContent,'external-two');
    delayed(response(replay));await settle();assert.equal(app.$('run-id').textContent,'external-two');
    assert.equal([...app.timers.values()].some(fn=>fn.intervalMs===2000),false);
    assert.equal(app.requests.some(r=>['/api/start','/api/pause','/api/stop'].includes(r.url)),false);
    assert.deepEqual(app.errors,[]);
  } finally { app.dom.window.close(); }
});

test('overview shows four corroborated attempts with levels, recent phases and update age',async()=>{
  const overview=overviewFixture(catalog25), phases=['modeling','computing','executing','waiting'];
  for(let i=0;i<4;i++) overview.games[i]={...overview.games[i],solving:true,solving_run_id:`active-${i}`,
    runs:[{...catalogRun(`active-${i}`,'unverified',false),recording:true,activity:{level:1,target_level:2,
      phase:phases[i],event_sequence:12,updated_at:new Date(Date.now()-65000).toISOString()}}]};
  overview.games[4]={...overview.games[4],solving:false,solving_run_id:null,
    runs:[{...catalogRun('stale','unverified',false),recording:true,activity:{level:1,target_level:2,
      phase:'executing',event_sequence:99,updated_at:new Date().toISOString()}}]};
  overview.games[5]={...overview.games[5],status:'running',active_run_id:'stopped-local',solving:false,solving_run_id:null,
    runs:[{...catalogRun('stopped-local','running',false),recording:true,activity:{level:1,target_level:2,
      phase:'executing',event_sequence:100,updated_at:new Date().toISOString()}}]};
  const app=launch(fixture(),{liveConfig:catalog25,overview,fetch:async()=>response(idleView())});
  try {
    await settle();
    for(let i=0;i<4;i++) {
      const row=overviewRow(app,i);
      assert.equal(row.querySelector('.overview-activity-badge').textContent,'● 解题中 · L2');
      assert.equal(row.querySelector('.overview-activity-phase').textContent,`最近${['建模','计算','执行','等待'][i]} · 1分钟前`);
      assert.match(row.querySelector('.overview-activity-phase').title,/最近确认阶段.*事件 #12/);
    }
    assert.equal(overviewRow(app,4).querySelector('.overview-activity-phase'),null);
    assert.equal(overviewRow(app,5).querySelector('.overview-activity-phase'),null);
    assert.equal(overviewRow(app,5).querySelector('.overview-activity-badge').textContent,'● 新尝试');
    assert.equal([...app.timers.values()].some(fn=>fn.intervalMs===5000),true);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('overview subtly marks confirmed solving and never treats old recording files as alive',async()=>{
  const overview=overviewFixture(catalog25);
  overview.games[0]={...overview.games[0],status:'unverified',solving:false,solving_run_id:null,
    runs:[{...catalogRun('stale-recording','unverified',false),completed_levels:0,recording:true}]};
  overview.games[1]={...overview.games[1],status:'unverified',solving:true,solving_run_id:'actual-research',
    runs:[{...catalogRun('actual-research','unverified',false),completed_levels:0,recording:true}]};
  const app=launch(fixture(),{liveConfig:catalog25,overview,fetch:async()=>response(idleView())});
  try {
    await settle();assert.equal(overviewRow(app,0).classList.contains('is-solving'),false);
    assert.equal(overviewRow(app,1).classList.contains('is-solving'),true);
    assert.equal(overviewRow(app,0).querySelector('.overview-activity-badge').textContent,'● 新尝试');
    assert.equal(overviewRow(app,1).querySelector('.overview-activity-badge').textContent,'● 解题中');
    assert.equal(overviewRow(app,2).classList.contains('is-solving'),false);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('overview processing warning remains separate from saved progress and solving status',async()=>{
  const overview=overviewFixture(catalog25);
  overview.games[0]={...overview.games[0],status:'partial',completed_levels:1,diagnostics_count:1,
    latest_diagnostic:{diagnostic_id:'fault-1',code:'evidence-write-failed',severity:'error',stage:'validated-not-durable',
      action_sequence:97,outcome_known:true,durable:false,observed:null,limit:null,unit:null,recovery:'stop-without-redispatch'}};
  const app=launch(fixture(),{liveConfig:catalog25,overview,fetch:async()=>response(idleView())});
  try {
    await settle();const row=overviewRow(app,0),warning=row.querySelector('.overview-processing-warning');
    assert.equal(warning.textContent,'⚠ 1');assert.match(warning.title,/证据保存失败.*结果已知/);
    assert.match(row.querySelector('.overview-result-badge').textContent,/部分通关/);
    assert.equal(row.querySelector('progress').value,1);assert.equal(row.classList.contains('is-solving'),false);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('an action not dispatched remains a public warning with known outcome',async()=>{
  const overview=overviewFixture(catalog25);
  overview.games[0]={...overview.games[0],diagnostics_count:1,
    latest_diagnostic:{diagnostic_id:'not-dispatched-1',code:'action-not-dispatched',severity:'error',stage:'not-dispatched',
      action_sequence:152,outcome_known:true,durable:false,observed:null,limit:null,unit:null,recovery:'stop-without-redispatch'}};
  const app=launch(fixture(),{liveConfig:catalog25,overview,fetch:async()=>response(idleView())});
  try {
    await settle();
    assert.match(overviewRow(app).querySelector('.overview-processing-warning').title,/动作未派发.*结果已知.*未持久化.*尚未执行/);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('older unsealed attempts do not mark a newer completed route as a new attempt',async()=>{
  const overview=overviewFixture(catalog25);
  overview.games[0]={...overview.games[0],status:'completed',completed_levels:2,route_actions:467,
    best_run_id:'newest-completed',latest_run_id:'newest-completed',recording_run_id:'older-unsealed',
    runs:[catalogRun('newest-completed'),{...catalogRun('older-unsealed','unverified',false),recording:true}]};
  overview.games[1]={...overview.games[1],status:'completed',completed_levels:3,
    best_run_id:'saved-completed',latest_run_id:'newest-redo',
    runs:[catalogRun('saved-completed'),{...catalogRun('newest-redo','unverified',false),recording:true}]};
  const app=launch(fixture(),{liveConfig:catalog25,overview,fetch:async()=>response(idleView())});
  try {
    await settle();const saved=overviewRow(app,0),redo=overviewRow(app,1);
    assert.equal(saved.querySelector('.overview-result-badge').textContent,'✓ 全部通关');
    assert.equal(saved.children[4].textContent,'467');
    assert.equal(saved.querySelector('.overview-activity-badge'),null);
    assert.equal(redo.querySelector('.overview-activity-badge').textContent,'● 新尝试');
    assert.deepEqual(app.errors,[]);
  }finally{app.dom.window.close();}
});

test('static exports keep the local overview hidden and never fetch',()=>{
  const app=launch(fixture());try{assert.equal(app.$('overview').hidden,true);assert.equal(app.requests.length,0);assert.deepEqual(app.errors,[]);}finally{app.dom.window.close();}
});


test('unresumable saved progress and stale overview disable default start without discarding displayed records', async()=>{
  let overview=overviewFixture(catalog25);
  overview.games[0]={...overview.games[0],status:'partial',completed_levels:1,best_run_id:'no-world-model',runs:[catalogRun('no-world-model')]};
  const app=launch(fixture(),{liveConfig:catalog25,overview:()=>overview,fetch:async url=>url==='/api/manual/open'?response({},503):response(idleView())});
  try {
    await settle();assert.equal(app.$('run-start').disabled,true);assert.equal(app.$('run-start').textContent,'存档不可接续');assert.equal(app.$('run-fresh').disabled,false);
    app.$('run-start').click();assert.equal(app.requests.some(r=>r.url==='/api/start'),false);
    overview={};app.tick();await settle();assert.equal(app.$('overview-game-list').children.length,25);assert.equal(app.$('run-fresh').disabled,true);
    overviewRow(app,1).querySelector('[data-overview-start]').click();assert.equal(app.requests.some(r=>r.url==='/api/start'),false);
    assert.match(app.$('overview-refresh').textContent,/暂不可用/);assert.deepEqual(app.errors,[]);
  }finally{app.dom.window.close();}
});

test('recording overview keeps saved route by default and explicitly watches an unsealed external attempt',async()=>{
  const overview=overviewFixture(catalog25);overview.guest_busy=true;overview.start_ready=false;overview.start_block_reason='session-busy';
  overview.games[0]={...overview.games[0],status:'partial',completed_levels:1,best_run_id:'old-best',resume_run_id:'old-best',latest_run_id:'new-recording',runs:[catalogRun('old-best'),{...catalogRun('new-recording','unverified',false),recording:true,sealed_trace:false}]};
  overview.games[1]={...overview.games[1],status:'completed',completed_levels:3,best_run_id:'full-best',runs:[catalogRun('full-best'),{...catalogRun('full-redo','unverified',false),recording:true}]};
  overview.games[3]={...overview.games[3],status:'unverified',runs:[catalogRun('pending-verification','unverified',false)]};
  let replay={...fixture(),run:{...fixture().run,game_id:'game0-catalog',run_id:'new-recording',win_levels:2,sealed_trace:false}};
  const saved={...fixture(),run:{...fixture().run,game_id:'game0-catalog',run_id:'old-best',win_levels:2,seed:0,completed_level_count:1,replay_verified:true,sealed_trace:true}};
  const app=launch(fixture(),{liveConfig:catalog25,overview,fetch:async url=>url==='/api/manual/open'?response({},503):response(url==='/api/replay/old-best'?saved:url.startsWith('/api/replay/')?replay:idleView())});
  try {
    await settle();assert.equal(app.$('run-id').textContent,'old-best');const row=overviewRow(app);assert.equal(row.querySelector('.overview-result-badge').textContent,'◐ 部分通关');assert.equal(row.querySelector('.overview-result-badge').classList.contains('partial'),true);assert.equal(row.querySelector('.overview-activity-badge').textContent,'● 新尝试');assert.match(row.querySelector('.overview-activity-badge').title,/外部只读/);assert.match(row.querySelector('.overview-activity-badge').getAttribute('aria-label'),/外部只读/);assert.doesNotMatch(row.textContent,/外部只读/);assert.match(row.querySelector('.overview-progress').textContent,/1 \/ 2/);
    const full=overviewRow(app,1);assert.equal(full.querySelector('.overview-result-badge').textContent,'✓ 全部通关');assert.equal(full.querySelector('.overview-result-badge').classList.contains('completed'),true);assert.equal(full.querySelector('.overview-progress').classList.contains('completed'),true);assert.equal(full.querySelector('.overview-activity-badge').textContent,'● 新尝试');
    assert.equal(overviewRow(app,2).querySelector('.overview-result-badge').textContent,'尚未开始');assert.equal(overviewRow(app,2).querySelector('.overview-activity-badge'),null);
    assert.equal(overviewRow(app,3).querySelector('.overview-result-badge').textContent,'未通关');assert.match(overviewRow(app,3).querySelector('.overview-result-badge').title,/没有已保存过关记录/);assert.equal(overviewRow(app,3).querySelector('.overview-result-badge').classList.contains('unverified'),true);
    row.querySelector('[data-overview-attempt]').click();await settle();assert.equal(app.$('replay-run').value,'new-recording');assert.equal(app.$('run-id').textContent,'new-recording');
    app.$('level-1').click();
    app.$('frame-slider').value='1';app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
    replay={...replay,levels:replay.levels.map((level,i)=>i?level:{...level,frames:[...level.frames,{id:'f3',grid:[[14]],state:'NOT_FINISHED'}]})};
    app.tick();await settle();assert.equal(app.$('frame-counter').textContent,'2 / 4');assert.equal(app.$('replay-follow').hidden,false);
    app.$('replay-follow').click();assert.equal(app.$('frame-counter').textContent,'4 / 4');
    overviewRow(app,1).querySelector('[data-overview-select]').click();await settle();
    const before=app.requests.filter(r=>r.url==='/api/replay/new-recording').length;app.tick();await settle();assert.equal(app.requests.filter(r=>r.url==='/api/replay/new-recording').length,before);
    assert.deepEqual(app.errors,[]);
  }finally{app.dom.window.close();}
});

test('unsealed replay polling keeps active playback and its pinned frame cursor', async () => {
  const overview = overviewFixture(catalog25);
  overview.guest_busy = true; overview.start_ready = false; overview.start_block_reason = 'session-busy';
  overview.games[0] = { ...overview.games[0], active_run_id:'playing-recording', runs: [{ ...catalogRun('playing-recording', 'unverified', false), recording: true }] };
  let replay = { ...fixture(), run: { ...fixture().run, game_id: 'game0-catalog', run_id: 'playing-recording', sealed_trace: false } };
  const app = launch(fixture(), { liveConfig: catalog25, overview, fetch: async url =>
    url === '/api/manual/open' ? response({}, 503) : response(url.startsWith('/api/replay/') ? replay : idleView()) });
  try {
    await settle();
    overviewRow(app).querySelector('[data-overview-watch]').click();
    await settle();

    app.$('frame-slider').value = '0';
    app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
    app.$('play-toggle').click();
    assert.equal(app.$('play-toggle').textContent, '暂停');
    const playbackTimer = [...app.timers.entries()].find(([, fn]) => fn.intervalMs < 1000);
    assert.ok(playbackTimer, 'playback timer is active');
    playbackTimer[1]();
    assert.equal(app.$('frame-counter').textContent, '2 / 3');

    [...app.timers.values()].find(fn => fn.intervalMs === 5000)();
    await settle();
    assert.equal(app.$('frame-counter').textContent, '2 / 3');
    assert.equal(app.$('play-toggle').textContent, '暂停');
    assert.equal([...app.timers.values()].includes(playbackTimer[1]), true);

    replay = { ...replay, levels: replay.levels.map((level, index) => index === 0 ? {
      ...level, frames: [...level.frames, { id: 'f4', grid: [[14]], state: 'NOT_FINISHED' }],
    } : level) };
    const replayPoll = [...app.timers.values()].find(fn => fn.intervalMs === 2000);
    assert.ok(replayPoll, 'unsealed replay refresh timer is active');
    replayPoll();
    await settle();

    assert.equal(app.$('frame-counter').textContent, '2 / 4');
    assert.equal(app.$('play-toggle').textContent, '暂停');
    assert.equal(app.$('play-toggle').getAttribute('aria-pressed'), 'true');
    assert.equal([...app.timers.values()].includes(playbackTimer[1]), true);
    assert.equal(app.requests.some(request => ['/api/start', '/api/pause', '/api/stop'].includes(request.url)), false);
    playbackTimer[1]();
    assert.equal(app.$('frame-counter').textContent, '3 / 4');
    assert.equal(app.$('play-toggle').textContent, '暂停');
    playbackTimer[1]();
    assert.equal(app.$('frame-counter').textContent, '4 / 4');
    assert.equal(app.$('play-toggle').textContent, '播放');
    assert.equal([...app.timers.values()].includes(playbackTimer[1]), false);
    assert.deepEqual(app.errors, []);
  } finally { app.dom.window.close(); }
});


test('replay frame and user level cursors pin the existing event when new revisions arrive at the same frame',async()=>{
  const overview=overviewFixture(catalog25);overview.guest_busy=true;overview.start_ready=false;overview.start_block_reason='session-busy';
  overview.games[0]={...overview.games[0],active_run_id:'cursor-recording',runs:[{...catalogRun('cursor-recording','unverified',false),recording:true}]};
  let replay={...researchStory(),run:{...fixture().run,game_id:'game0-catalog',run_id:'cursor-recording',sealed_trace:false}};
  const app=launch(fixture(),{liveConfig:catalog25,overview,fetch:async url=>url==='/api/manual/open'?response({},503):response(url.startsWith('/api/replay/')?replay:idleView())});
  try{
    await settle();overviewRow(app).querySelector('[data-overview-watch]').click();await settle();
    app.$('frame-slider').value='0';app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
    const revision={...replay.process_events[4],event_sequence:7,payload:{...replay.process_events[4].payload,revision:'model-3',description_zh:'新规则：门永久关闭。'}};
    replay={...replay,process_events:[...replay.process_events,revision]};app.tick();await settle();
    assert.equal(app.$('event-counter').textContent,'事件 6');assert.match(app.$('world-guide').textContent,/门仅开放一步/);assert.doesNotMatch(app.$('world-guide').textContent,/永久关闭/);
    app.$('replay-follow').click();assert.equal(app.$('event-counter').textContent,'事件 7');
    app.$('level-1').click();replay={...replay,process_events:[...replay.process_events,{...revision,event_sequence:8}]};app.tick();await settle();
    assert.equal(app.$('event-counter').textContent,'事件 7');assert.deepEqual(app.errors,[]);
  }finally{app.dom.window.close();}
});

test('switching games clears a previous event cursor and follows the new level only after explicit follow',async()=>{
  const overview=overviewFixture(catalog25);overview.games[0]={...overview.games[0],best_run_id:'first-replay',completed_levels:1,runs:[catalogRun('first-replay')]};overview.games[1]={...overview.games[1],best_run_id:'second-replay',completed_levels:1,runs:[catalogRun('second-replay')]};
  const first={...researchStory(),run:{...fixture().run,game_id:'game0-catalog',run_id:'first-replay',sealed_trace:true}};
  const second={...fixture(),run:{...fixture().run,game_id:'game1-catalog',run_id:'second-replay',sealed_trace:true},process_events:[{...first.process_events[4],level:2,event_sequence:99,frame_id:'f2'}]};
  second.levels[1]={...second.levels[0],level:2};
  const app=launch(fixture(),{liveConfig:catalog25,overview,fetch:async url=>url==='/api/manual/open'?response({},503):response(url==='/api/replay/first-replay'?first:url==='/api/replay/second-replay'?second:idleView())});
  try{
    await settle();overviewRow(app).querySelector('[data-overview-watch]').click();await settle();
    app.$('event-slider').value='1';app.$('event-slider').dispatchEvent(new app.dom.window.Event('input'));
    overviewRow(app,1).querySelector('[data-overview-select]').click();await settle();
    assert.equal(app.$('board-kicker').textContent,'LEVEL 02');assert.equal(app.$('frame-counter').textContent,'1 / 3');
    assert.notEqual(app.$('event-counter').textContent,'事件 1');app.$('replay-follow').click();
    assert.equal(app.$('run-id').textContent,'second-replay');assert.equal(app.$('frame-counter').textContent,'3 / 3');assert.equal(app.$('event-counter').textContent,'事件 99');assert.deepEqual(app.errors,[]);
  }finally{app.dom.window.close();}
});

test('stale unsealed recording does not veto a ready guest and backend readiness blocks new starts',async()=>{
  let overview=overviewFixture(catalog25);overview.games[0]={...overview.games[0],runs:[{...catalogRun('stale-recording','unverified',false),recording:true}]};
  const app=launch(fixture(),{liveConfig:catalog25,overview:()=>overview,fetch:async url=>url==='/api/manual/open'?response({},503):response(idleView())});
  try{
    await settle();assert.equal(app.$('run-start').disabled,false);assert.equal(overviewRow(app).querySelector('.overview-activity-badge').textContent,'● 新尝试');assert.match(overviewRow(app).querySelector('.overview-activity-badge').title,/外部只读/);
    overview={...overview,guest_busy:true,start_ready:false,start_block_reason:'session-busy'};app.tick();await settle();assert.equal(app.$('run-start').disabled,true);assert.equal(app.$('run-fresh').disabled,true);
    app.$('run-start').click();assert.equal(app.requests.some(request=>request.url==='/api/start'),false);assert.deepEqual(app.errors,[]);
  }finally{app.dom.window.close();}
});


test('explicit game selection mounts its latest WorldMap P7 recording at level 6 without manual state overwrites',async()=>{
  const config={...catalog25,games:catalog25.games.map((game,i)=>i===5?{...game,game_id:'sp80-test',alias:'SP80',win_levels:7}:game)};
  const overview=overviewFixture(config);overview.guest_busy=true;overview.start_ready=false;overview.start_block_reason='session-busy';
  overview.games[5]={...overview.games[5],completed_levels:5,status:'partial',score:'59.523810',best_run_id:'saved-five',resume_run_id:'saved-five',active_run_id:'current-six',recording_run_id:'current-six',runs:[{...catalogRun('saved-five'),completed_levels:5},{...catalogRun('current-six','unverified',false),recording:true}]};
  const replay={...fixture(),run:{...fixture().run,game_id:'sp80-test',run_id:'current-six',win_levels:7,completed_level_count:5,sealed_trace:false},levels:Array.from({length:6},(_,i)=>({level:i+1,status:i<5?'successful':'incomplete',frames:[{id:`l${i+1}`,grid:[[i]],state:'NOT_FINISHED'}],actions:[],decisions:[],cognition:{scope:'unavailable'}}))};
  const savedManual=manualView('sp80-test',9,0,2);
  const session={...stateWithManual(savedManual),selection:{game_id:'sp80-test',level:2}};
  const app=launch(fixture(),{liveConfig:config,overview,fetch:async url=>response(url==='/api/replay/current-six'?replay:session)});
  try{
    await settle(); changeGame(app, 'sp80-test'); await settle();assert.equal(app.$('game-select').value,'sp80-test');assert.equal(app.$('run-id').textContent,'current-six');assert.equal(app.$('board-kicker').textContent,'LEVEL 06');assert.equal(app.$('level-progress').textContent,'5 / 7');
    assert.equal(app.$('board-empty').hidden,true);assert.equal(app.$('console-mode').value,'replay');assert.equal(app.$('manual-history').hidden,true);
    assert.equal(app.$('replay-run').hidden,true);assert.equal(app.$('replay-load').hidden,true);assert.equal(app.$('replay-run').getAttribute('aria-hidden'),'true');
    assert.match(app.$('overview').textContent,/当前 WorldMap P7/);assert.doesNotMatch(app.$('overview').textContent,/历史存档|不同代码版本/);
    app.tick();await settle();assert.equal(app.$('board-kicker').textContent,'LEVEL 06');assert.equal(app.$('run-id').textContent,'current-six');
    assert.equal(app.requests.some(request=>['/api/manual/open','/api/manual/action','/api/start'].includes(request.url)),false);assert.deepEqual(app.errors,[]);
  }finally{app.dom.window.close();}
});

test('game selection automatically loads the current source and unplayed games open HUMAN only after explicit mode selection',async()=>{
  const overview=overviewFixture(catalog25);
  overview.games[0]={...overview.games[0],best_run_id:'highest-current',resume_run_id:'highest-current',latest_run_id:'highest-current',completed_levels:1,status:'partial',runs:[catalogRun('older-current'),catalogRun('highest-current')]};
  const replay={...fixture(),run:{...fixture().run,game_id:'game0-catalog',run_id:'highest-current',sealed_trace:true}};
  const app=launch(fixture(),{liveConfig:catalog25,overview,fetch:async(url,options)=>{
    if(url==='/api/replay/highest-current')return response(replay);
    if(url==='/api/manual/open'){const body=JSON.parse(options.body);return response(manualView(body.game_id,9,0,body.level));}
    return response(idleView());
  }});
  try{
    await settle();assert.equal(app.$('run-id').textContent,'highest-current');assert.equal(app.requests.filter(request=>request.url==='/api/replay/highest-current').length,1);
    overviewRow(app,1).querySelector('[data-overview-select]').click();await settle();assert.equal(app.$('game-title').textContent,'game1-catalog');assert.equal(app.$('board-empty').hidden,false);assert.equal(app.requests.some(request=>request.url==='/api/manual/open'),false);
    await enterManual(app);assert.equal(app.$('console-mode').value,'manual');assert.equal(app.$('board-empty').hidden,true);assert.equal(app.requests.filter(request=>request.url==='/api/manual/open').length,1);
    assert.equal(app.requests.some(request=>request.url==='/api/start'),false);assert.deepEqual(app.errors,[]);
  }finally{app.dom.window.close();}
});

test('live level completion refreshes both games overview immediately without moving pinned playback', async () => {
  let overview = overviewFixture(catalog25);
  overview.guest_busy = true; overview.start_ready = false; overview.start_block_reason = 'session-busy';
  overview.games[0] = {...overview.games[0], active_run_id:'live-first', runs:[{...catalogRun('live-first','unverified',false),recording:true}]};
  let replay = {...fixture(),run:{...fixture().run,game_id:'game0-catalog',run_id:'live-first',sealed_trace:false}};
  const app=launch(fixture(),{liveConfig:catalog25,overview:()=>overview,fetch:async url =>
    url==='/api/manual/open'?response({},503):response(url.startsWith('/api/replay/')?replay:idleView())});
  try {
    await settle(); overviewRow(app).querySelector('[data-overview-watch]').click(); await settle();
    app.$('frame-slider').value='0'; app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
    app.$('play-toggle').click();
    const timer=[...app.timers.values()].find(fn=>fn.intervalMs<1000); timer();
    const count=app.requests.filter(request=>request.url==='/api/overview').length;
    overview={...overview,totals:{...overview.totals,display_completed_levels:2,display_completed_games:0},games:overview.games.map((game,index)=>
      index<2?{...game,display_completed_levels:1,progress_pending:true,runs:index===0?[{...game.runs[0],observed_completed_levels:1}]:[{...catalogRun('live-second','unverified',false),recording:true,observed_completed_levels:1}]}:
      {...game,display_completed_levels:0,progress_pending:false})};
    replay={...replay,run:{...replay.run,completed_level_count:1},levels:replay.levels.map((level,index)=>index===0?{...level,status:'successful'}:level)};
    [...app.timers.values()].find(fn=>fn.intervalMs===2000)(); await settle();
    assert.equal(app.requests.filter(request=>request.url==='/api/overview').length,count+1);
    assert.equal(app.$('overview-levels').textContent,'2 / 350');
    assert.match(overviewRow(app).querySelector('.overview-progress').textContent,/1 \/ 2/);
    assert.match(overviewRow(app,1).querySelector('.overview-progress').textContent,/1 \/ 3/);
    assert.match(overviewRow(app).textContent,/待封存/);
    assert.equal(app.$('frame-counter').textContent,'2 / 3');
    assert.equal(app.$('play-toggle').textContent,'暂停');
    assert.equal([...app.timers.values()].includes(timer),true);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

function levelReplayFixture(gameId, runId, {sealed=true, color=12}={}) {
  const record={schema:'asterion.arc-agi3-p7-console/v1',generated_at:null,
    run:{game_id:gameId,run_id:runId,seed:0,win_levels:3,status:sealed?'incomplete':'running',
      completed_level_count:2,primitive_action_count:3,replay_verified:sealed,sealed_trace:sealed},
    levels:[1,2,3].map(level=>({level,status:level<3?'successful':'not-run',
      frames:level<3?Array.from({length:3},(_,i)=>({id:`${runId}-l${level}-f${i}`,grid:[[color]],state:'NOT_FINISHED',levels_completed:level-1})):[],
      actions:level<3?Array.from({length:level},(_,i)=>({id:`${runId}-l${level}-a${i}`,name:'ACTION1',data:{},before_frame:`${runId}-l${level}-f0`,after_frame:`${runId}-l${level}-f2`})):[],
      decisions:[],cognition:{scope:level<3?'final':'unavailable',stable_description:`游戏规则：${runId} 第${level}关的真实认知`}})),decisions:[],process_events:[],warnings:[]};
  const revision=(color===12?'a':'b').repeat(64);
  const manifest={schema:'asterion.arc-agi3-p7-replay-manifest/v1',state:'ready',run_id:runId,revision,run:record.run,
    levels:record.levels.map(level=>({level:level.level,status:level.status,frame_count:level.frames.length,action_count:level.actions.length,has_cognition:level.cognition.scope==='final'})),warnings:[]};
  return {record,manifest,detail:level=>({...record,replay_revision:revision,levels:[record.levels[level-1]]})};
}
function pagedReplayFixture() {
  const data=levelReplayFixture('game0-catalog','paged-run'),token='c'.repeat(64),offset=101,total=95;
  const frame=index=>({id:`f${String(offset+index).padStart(6,'0')}`,index,grid:[[index%16]],state:'NOT_FINISHED',levels_completed:0,available_actions:['ACTION1']});
  const level=data.record.levels[0];
  Object.assign(level,{frame_count:total,frame_index_offset:offset,frame_page:{start:0,limit:32,source_token:token},
    frames:Array.from({length:32},(_,index)=>frame(index)),
    actions:[{id:'a1',name:'ACTION1',before_frame:frame(0).id,after_frame:frame(94).id,before_frame_index:0,after_frame_index:94}],
    cognition_timeline:[0,80].map(index=>({scope:'observation',frame_id:frame(index).id,frame_index:index,stable_description:`精确认知 ${index}`}))});
  data.record.schema='asterion.arc-agi3-p7-console/v2';data.manifest.schema='asterion.arc-agi3-p7-replay-manifest/v2';
  data.manifest.levels[0].frame_count=total;
  const page=start=>({schema:'asterion.arc-agi3-p7-replay-frame-page/v1',run_id:'paged-run',level:1,replay_revision:data.manifest.revision,
    source_token:token,frame_count:total,start,frames:Array.from({length:Math.min(32,total-start)},(_,index)=>frame(start+index))});
  return {data,page};
}
test('paged animation seeks and plays across pages with complete counts and exact cognition',async()=>{
  const {data,page}=pagedReplayFixture();
  const app=launch(fixture(),{liveConfig:levelReplayConfig,overview:levelReplayOverview([data]),fetch:async url=>{
    if(url.endsWith('/manifest'))return response(data.manifest);
    if(url.includes('/frames/'))return response(page(Number(url.split('/').at(-2))));
    if(url.includes('/levels/'))return response(data.detail(Number(url.match(/\/levels\/(\d+)/)[1])));
    return response(idleView());
  }});
  try {
    await settleReplay();app.$('level-1').click();await settleReplay();
    assert.equal(app.$('frame-counter').textContent,'1 / 95');assert.match(app.$('level-1').title,/95 帧/);
    app.$('frame-slider').value='80';app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));await settleReplay();
    assert.equal(app.$('frame-counter').textContent,'81 / 95');assert.match(app.$('frame-caption').textContent,/f000181/);
    assert.match(app.$('world-guide').textContent,/精确认知 80/);
    app.$('frame-slider').value='31';app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
    app.$('play-toggle').click();app.tick();await settleReplay();
    assert.equal(app.$('frame-counter').textContent,'33 / 95');assert.equal(app.$('play-toggle').textContent,'暂停');
    app.tick();await settleReplay();assert.equal(app.$('frame-counter').textContent,'34 / 95');
    assert.equal(app.$('board-empty').hidden,true);assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('missing and stale animation pages preserve saved steps, cognition and the selected level',async()=>{
  const {data,page}=pagedReplayFixture();let fail=true,releasePage;
  const app=launch(fixture(),{liveConfig:levelReplayConfig,overview:levelReplayOverview([data]),fetch:async url=>{
    if(url.endsWith('/manifest'))return response(data.manifest);
    if(url.includes('/frames/')) {
      if(fail)return response({error:'replay-frame-unavailable'},503);
      return new Promise(resolve=>{releasePage=()=>resolve(response(page(Number(url.split('/').at(-2)))));});
    }
    if(url.includes('/levels/'))return response(data.detail(Number(url.match(/\/levels\/(\d+)/)[1])));
    return response(idleView());
  }});
  try {
    await settleReplay();app.$('level-1').click();await settleReplay();
    app.$('frame-slider').value='80';app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));await settleReplay();
    assert.match(app.$('board-empty').textContent,/画面读取失败/);assert.match(app.$('world-guide').textContent,/精确认知 80/);
    assert.match(app.$('level-1').title,/1 动作 · 95 帧/);assert.equal(app.$('level-progress').textContent,'2 / 3');
    fail=false;app.$('next-frame').click();await settleReplay();assert.ok(releasePage);
    app.$('level-2').click();await settleReplay();const caption=app.$('frame-caption').textContent;
    releasePage();await settleReplay();
    assert.equal(app.$('level-2').getAttribute('aria-current'),'true');assert.equal(app.$('frame-caption').textContent,caption);
    assert.match(app.$('world-guide').textContent,/第2关的真实认知/);assert.equal(app.$('board-empty').hidden,true);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('offline animation pages seek and play without HTTP and reject missing or foreign pages',async()=>{
  for (const kind of ['valid','missing','foreign']) {
    const {data,page}=pagedReplayFixture();
    Object.assign(data.record,{offline_frames:true,replay_revision:data.manifest.revision});
    const app=launch(data.record);
    try {
      for (const start of [32,64]) {
        if (kind === 'missing' && start === 64) continue;
        const entry=app.dom.window.document.createElement('script');
        entry.id=`console-frame-page-1-${start}`;entry.type='application/json';
        const payload=page(start);
        if (kind === 'foreign' && start === 64) payload.run_id='another-run';
        entry.textContent=JSON.stringify(payload);app.dom.window.document.body.append(entry);
      }
      app.$('frame-slider').value='80';app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));await settleReplay();
      assert.equal(app.$('frame-counter').textContent,'81 / 95');
      assert.match(app.$('world-guide').textContent,/精确认知 80/);
      assert.match(app.$('level-1').title,/1 动作 · 95 帧/);
      if (kind === 'valid') {
        assert.match(app.$('frame-caption').textContent,/f000181/);assert.equal(app.$('board-empty').hidden,true);
        app.$('frame-slider').value='31';app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));
        app.$('play-toggle').click();app.tick();await settleReplay();
        assert.equal(app.$('frame-counter').textContent,'33 / 95');assert.equal(app.$('play-toggle').textContent,'暂停');
      } else assert.match(app.$('board-empty').textContent,/画面读取失败/);
      assert.deepEqual(app.requests,[]);assert.deepEqual(app.errors,[]);
    } finally {app.dom.window.close();}
  }
});

const levelReplayConfig={token:'test-token',replay_loading:'level-manifest/v1',games:[
  {game_id:'game0-catalog',alias:'first',win_levels:3,baseline_actions:[1,2,3]},
  {game_id:'game1-catalog',alias:'second',win_levels:3,baseline_actions:[1,2,3]}]};
function levelReplayOverview(records) {
  const overview=overviewFixture(levelReplayConfig);
  records.forEach((data,index)=>{
    overview.games[index]={...overview.games[index],status:data.record.run.sealed_trace?'partial':'running',completed_levels:2,
      best_run_id:data.record.run.sealed_trace?data.record.run.run_id:null,active_run_id:data.record.run.sealed_trace?null:data.record.run.run_id,runs:[{...catalogRun(data.record.run.run_id,data.record.run.status,data.record.run.sealed_trace),completed_levels:2}]};
  });
  return overview;
}

const settleReplay=async()=>{await settle();await settle();await settle();};

test('initial page opening selects saved progress once even when the embedded game is already selected',async()=>{
  for (const completed of [8,2]) {
    const config={token:'test-token',replay_loading:'level-manifest/v1',games:[{game_id:'ar25-catalog',alias:'AR25',win_levels:8,baseline_actions:Array(8).fill(1)}]};
    const data=levelReplayFixture('ar25-catalog','boot-saved');
    data.record.run.win_levels=8;data.record.run.completed_level_count=completed;
    data.record.levels=Array.from({length:8},(_,index)=>({...data.record.levels[0],level:index+1,status:index<completed?'successful':'not-run',
      frames:index<completed?data.record.levels[0].frames.map(frame=>({...frame,id:`boot-l${index+1}-${frame.id}`})):[],actions:index<completed?data.record.levels[0].actions:[]}));
    data.manifest.levels=data.record.levels.map(level=>({level:level.level,status:level.status,frame_count:level.frames.length,
      action_count:level.actions.length,has_cognition:level.frames.length>0}));
    const overview=overviewFixture(config);overview.games[0]={...overview.games[0],status:completed===8?'completed':'partial',
      completed_levels:completed,best_run_id:'boot-saved',runs:[{...catalogRun('boot-saved'),completed_levels:completed}]};
    let releaseOverview;
    const preview={schema:data.record.schema,run:{...data.record.run,run_id:null,status:'preview',completed_level_count:0,
      primitive_action_count:0,target_level:3,replay_verified:false,sealed_trace:false},
      levels:[{level:3,status:'preview',frames:[{id:'boot-preview',grid:[[9]],state:'NOT_FINISHED',levels_completed:2}],
        actions:[],decisions:[],cognition:{scope:'unavailable'},receipt:null}],decisions:[],warnings:[]};
    const app=launch(data.record,{liveConfig:config,overview:null,fetch:async url=>{
      if(url==='/api/overview')return releaseOverview?response(overview):new Promise(resolve=>{releaseOverview=resolve;});
      if(url.endsWith('/manifest'))return response(data.manifest);
      if(url.includes('/levels/'))return response({...data.record,replay_revision:data.manifest.revision,levels:[data.record.levels[Number(url.match(/\/levels\/(\d+)/)[1])-1]]});
      if(url.startsWith('/api/preview/'))return response(preview);
      return response({...view(data.record,'completed'),cleanup_confirmed:true});
    }});
    try {
      await settleReplay();assert.ok(releaseOverview);releaseOverview(response(overview));await settleReplay();
      assert.equal(app.$('board-kicker').textContent,completed===8?'LEVEL 01':'LEVEL 03');assert.equal(app.$('board-empty').hidden,true);
      app.$('level-2').click();await settleReplay();
      [...app.timers.values()].find(fn=>fn.intervalMs===5000)();await settleReplay();
      assert.equal(app.$('board-kicker').textContent,'LEVEL 02');assert.deepEqual(app.errors,[]);
    } finally {app.dom.window.close();}
  }
});

test('an explicit level chosen before the first overview survives initial page opening',async()=>{
  const data=levelReplayFixture('game0-catalog','boot-user-choice');let releaseOverview;
  const overview=levelReplayOverview([data]);
  const app=launch(data.record,{liveConfig:levelReplayConfig,overview:null,fetch:async url=>{
    if(url==='/api/overview')return releaseOverview?response(overview):new Promise(resolve=>{releaseOverview=resolve;});
    if(url.endsWith('/manifest'))return response(data.manifest);
    if(url.includes('/levels/'))return response(data.detail(Number(url.match(/\/levels\/(\d+)/)[1])));
    return response({...view(data.record,'completed'),cleanup_confirmed:true});
  }});
  try {
    await settleReplay();app.$('level-1').click();releaseOverview(response(overview));await settleReplay();
    assert.equal(app.$('board-kicker').textContent,'LEVEL 01');assert.equal(app.$('board-empty').hidden,true);assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('explicit game switches use saved progress for full, partial and zero routes in both replay loaders',async()=>{
  for (const progressive of [false,true]) for (const completed of [3,2,0]) {
    const config={...levelReplayConfig,...(!progressive?{replay_loading:undefined}:{})};
    const first=levelReplayFixture('game0-catalog','switch-first');
    const target=levelReplayFixture('game1-catalog',`switch-target-${completed}`,{sealed:completed!==0,color:14});
    target.record.run.completed_level_count=completed;
    if (completed===3) target.record.levels[2]={...target.record.levels[1],level:3};
    if (completed===0) target.record.levels.forEach(level=>{level.status=level.frames.length?'incomplete':'not-run';});
    target.manifest.levels=target.record.levels.map(level=>({level:level.level,status:level.status,
      frame_count:level.frames.length,action_count:level.actions.length,has_cognition:level.cognition.scope==='final'}));
    const overview=levelReplayOverview([first,target]);
    overview.games[1]={...overview.games[1],completed_levels:completed,status:completed===3?'completed':completed?'partial':'running',
      display_completed_levels:completed===2?3:completed,progress_pending:completed===2,
      runs:[{...overview.games[1].runs[0],completed_levels:completed}]};
    overview.totals.display_completed_levels=overview.games.reduce((sum,game)=>sum+(game.display_completed_levels??game.completed_levels),0);
    overview.totals.display_completed_games=overview.games.filter(game=>(game.display_completed_levels??game.completed_levels)===game.win_levels).length;
    const preview={schema:target.record.schema,run:{...target.record.run,run_id:null,status:'preview',completed_level_count:0,
      primitive_action_count:0,target_level:3,replay_verified:false,sealed_trace:false},
      levels:[{level:3,status:'preview',frames:[{id:'initial-three',grid:[[9]],state:'NOT_FINISHED',levels_completed:2}],
        actions:[],decisions:[],cognition:{scope:'unavailable'},receipt:null}],decisions:[],warnings:[]};
    let releaseManifest;
    const app=launch(fixture(),{liveConfig:config,overview,fetch:async url=>{
      if(url.startsWith('/api/preview/'))return response(preview);
      const data=url.includes(target.record.run.run_id)?target:first;
      if(url.endsWith('/manifest'))return data===target&&!releaseManifest?new Promise(resolve=>{releaseManifest=resolve;}):response(data.manifest);
      if(url.includes('/levels/'))return response(data.detail(Number(url.match(/\/levels\/(\d+)/)[1])));
      if(url.startsWith('/api/replay/'))return response(data.record);
      return response(idleView());
    }});
    try {
      await settleReplay();
      if(completed===3) overviewRow(app,1).querySelector('[data-overview-select]').click();
      else if(completed===2) overviewRow(app,1).querySelector('[data-overview-watch]').click();
      else changeGame(app,'game1-catalog');
      await settleReplay();
      const expected=completed===2?3:1;
      if(progressive) {
        assert.ok(releaseManifest);assert.equal(app.$('board-kicker').textContent,`LEVEL 0${expected}`);
        releaseManifest(response(target.manifest));await settleReplay();
      }
      assert.equal(app.$('board-kicker').textContent,`LEVEL 0${expected}`,`progressive=${progressive}, completed=${completed}`);
      assert.equal(app.$(`level-${expected}`).getAttribute('aria-current'),'true');
      assert.equal(app.$('board-empty').hidden,true);
      if(completed===2) assert.ok(app.requests.some(request=>request.url==='/api/preview/game1-catalog/3'));
      if(progressive && completed!==2) assert.ok(app.requests.some(request=>request.url.includes(`${target.record.run.run_id}/levels/1/`)));
      assert.deepEqual(app.errors,[]);
    } finally {app.dom.window.close();}
  }
});

test('late game-switch detail and polling retain an explicitly selected historical level and playback',async()=>{
  const first=levelReplayFixture('game0-catalog','switch-origin');
  const target=levelReplayFixture('game1-catalog','switch-live',{sealed:false,color:14});
  const overview=levelReplayOverview([first,target]);overview.games[1].completed_levels=1;
  let releaseDetail;
  const app=launch(fixture(),{liveConfig:levelReplayConfig,overview,fetch:async url=>{
    const data=url.includes('switch-live')?target:first;
    if(url.endsWith('/manifest'))return response(data.manifest);
    if(url.includes('/switch-live/levels/2/'))return new Promise(resolve=>{releaseDetail=resolve;});
    if(url.includes('/levels/'))return response(data.detail(Number(url.match(/\/levels\/(\d+)/)[1])));
    return response(idleView());
  }});
  try {
    await settleReplay();changeGame(app,'game1-catalog');await settleReplay();
    assert.equal(app.$('board-kicker').textContent,'LEVEL 02');assert.ok(releaseDetail);
    app.$('level-1').click();releaseDetail(response(target.detail(2)));await settleReplay();
    assert.equal(app.$('board-kicker').textContent,'LEVEL 01');assert.equal(app.$('board-empty').hidden,true);
    app.$('play-toggle').click();const timer=[...app.timers.values()].find(fn=>fn.intervalMs<1000);assert.ok(timer);
    [...app.timers.values()].find(fn=>fn.intervalMs===5000)();await settleReplay();
    [...app.timers.values()].find(fn=>fn.intervalMs===2000)();await settleReplay();
    assert.equal(app.$('board-kicker').textContent,'LEVEL 01');assert.equal(app.$('play-toggle').textContent,'暂停');
    assert.ok([...app.timers.values()].includes(timer));assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('accepted replay refreshes keep the stage and loader stable while genuine failures retain retry',async()=>{
  const data=levelReplayFixture('game0-catalog','stable-live',{sealed:false});let releaseManifest;
  const app=launch(fixture(),{liveConfig:levelReplayConfig,overview:levelReplayOverview([data]),fetch:async url=>{
    if(url.endsWith('/manifest'))return releaseManifest===null?new Promise(resolve=>{releaseManifest=resolve;}):response(data.manifest);
    if(url.includes('/levels/2/'))return response(data.detail(2));
    return response(idleView());
  }});
  try {
    await settleReplay();app.$('level-2').click();await settleReplay();assert.equal(app.$('board-empty').hidden,true);
    const stageStyle=app.dom.window.getComputedStyle(app.$('board-stage'));
    assert.notEqual(stageStyle.height,'auto');assert.notEqual(stageStyle.height,'');
    assert.equal(app.dom.window.getComputedStyle(app.$('replay-loading-slot')).position,'absolute');
    assert.ok(app.$('replay-loading-slot').closest('.run-status-column'));
    const frame=app.$('frame-counter').textContent, canvas=app.$('board-canvas');
    const mutations=[];const observer=new app.dom.window.MutationObserver(entries=>mutations.push(...entries));
    observer.observe(canvas,{attributes:true});
    releaseManifest=null;[...app.timers.values()].find(fn=>fn.intervalMs===2000)();await settleReplay();
    assert.ok(releaseManifest);assert.equal(app.$('replay-loading').hidden,true);
    [...app.timers.values()].find(fn=>fn.intervalMs===1000)();await settleReplay();
    assert.equal(app.$('replay-loading').hidden,true);assert.equal(app.$('frame-counter').textContent,frame);
    releaseManifest(response(data.manifest));await settleReplay();
    assert.equal(app.$('replay-loading').hidden,true);assert.equal(mutations.length,0);
    for(let tick=0;tick<5;tick++) {
      [...app.timers.values()].find(fn=>fn.intervalMs===2000)();
      assert.equal(app.$('replay-loading').hidden,true);await settleReplay();
      assert.equal(app.$('replay-loading').hidden,true);
    }
    assert.equal(mutations.length,0);
    releaseManifest=null;[...app.timers.values()].find(fn=>fn.intervalMs===2000)();await settleReplay();
    releaseManifest(response({},503));await settleReplay();
    assert.equal(app.$('replay-loading').hidden,false);assert.equal(app.$('replay-retry').hidden,false);
    assert.equal(app.$('board-empty').hidden,true);assert.equal(app.$('frame-counter').textContent,frame);
    observer.disconnect();assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('real evidence warnings remain accessible as compact status details without a full-width row',()=>{
  const record=fixture();record.warnings=['部分关卡已保存，尚无整题回执。','真实回放边界说明。'];
  const app=launch(record);
  try {
    const details=app.$('evidence-details'),summary=app.$('evidence-summary');
    assert.equal(details.hidden,false);assert.equal(details.open,false);
    assert.ok(details.closest('.run-status-column'));assert.equal(summary.textContent,'说明 2');
    assert.match(summary.title,/部分关卡已保存/);assert.match(summary.getAttribute('aria-label'),/真实回放边界说明/);
    details.open=true;assert.match(app.$('evidence-warning').textContent,/尚无整题回执/);
    assert.equal(app.dom.window.getComputedStyle(app.$('evidence-warning')).position,'absolute');
    assert.equal(app.dom.window.getComputedStyle(app.$('board-title').parentElement.parentElement).height,'');
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('processing faults stay visible and expanded through polling and recovery without a layout row',async()=>{
  const record=fixture();record.schema='asterion.arc-agi3-p7-console/v2';
  record.diagnostics=[{diagnostic_id:'fault-1',code:'evidence-write-failed',severity:'error',
    stage:'validated-not-durable',action_sequence:97,outcome_known:true,durable:false,
    observed:null,limit:null,unit:null,recovery:'stop-without-redispatch',
    first_seen:'2026-10-06T06:30:00Z',last_seen:'2026-10-06T06:30:00Z',count:1,status:'active',recovered_at:null}];
  let revision=1,current=record;
  const app=launch(record,{liveConfig,fetch:async url=>{
    assert.equal(url,'/api/state');return response({...view(current),revision});
  }});
  try {
    await settle();
    const details=app.$('evidence-details');
    assert.equal(details.hidden,false);assert.equal(app.$('evidence-summary').textContent,'警告 1');
    assert.match(app.$('evidence-warning').textContent,/保存失败.*动作 97.*结果已知.*未持久化/);
    details.open=true;
    current=structuredClone(record);current.diagnostics[0].count=2;revision++;
    app.tick();await settle();
    assert.equal(details.open,true);assert.match(app.$('evidence-warning').textContent,/累计 2 次/);
    current=structuredClone(current);Object.assign(current.diagnostics[0],{status:'recovered',recovered_at:'2026-10-06T06:31:00Z'});revision++;
    app.tick();await settle();
    assert.equal(details.open,true);assert.equal(details.hidden,false);
    assert.equal(app.$('evidence-summary').textContent,'已恢复 1');
    assert.match(app.$('evidence-warning').textContent,/已恢复/);
    assert.equal(app.dom.window.getComputedStyle(app.$('evidence-warning')).position,'absolute');
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('per-level replay shows loading, manifest counts, and reads only the chosen level with shared saved cache',async()=>{
  const data=levelReplayFixture('game0-catalog','level-first');let ready=false,releaseDetail;
  const app=launch(fixture(),{liveConfig:levelReplayConfig,overview:levelReplayOverview([data]),fetch:async url=>{
    if(url.endsWith('/manifest'))return response(ready?data.manifest:{schema:data.manifest.schema,state:'loading',run_id:data.manifest.run_id,revision:null,run:null,levels:[],warnings:[]},ready?200:202);
    if(url.includes('/levels/2/'))return new Promise(resolve=>{releaseDetail=resolve;});
    if(url.includes('/levels/1/'))return response(data.detail(1));
    return response(idleView());
  }});
  try {
    await settleReplay();assert.equal(app.$('game-title').textContent,'game0-catalog');assert.equal(app.$('replay-loading').hidden,false);
    const stageHeight=app.dom.window.getComputedStyle(app.$('board-stage')).height;
    assert.equal(app.$('palette-legend').hidden,true);
    assert.match(app.$('replay-loading-text').textContent,/正在整理回放/);assert.equal(app.$('board-empty').hidden,false);
    assert.equal(app.$('run-status').textContent,'读取中');
    assert.equal(app.$('level-progress').textContent,'— / 3');assert.equal(app.$('action-total').textContent,'—');
    assert.match(app.$('run-progress-summary').textContent,/游戏已保存 2 \/ 3 · 正在读取回放/);
    app.$('level-2').click();
    ready=true;app.$('replay-load').click();const clock=app.dom.window.Date.now;app.dom.window.Date.now=()=>clock()+2200;app.tick();await settleReplay();
    assert.ok(releaseDetail);assert.match(app.$('level-1').title,/1 动作 · 3 帧/);assert.match(app.$('level-2').title,/2 动作 · 3 帧/);
    assert.equal(app.$('level-1').querySelector('.level-step-count').textContent,'1 动作');
    assert.equal(app.$('level-2').querySelector('.level-step-count').textContent,'2 动作');
    assert.match(app.$('replay-loading-text').textContent,/正在加载第 2 关/);assert.equal(app.$('replay-loading').hidden,false);
    assert.equal(app.requests.some(request=>request.url==='/api/replay/level-first'),false);
    assert.equal(app.requests.some(request=>request.url.includes('/levels/1/')),false);
    releaseDetail(response(data.detail(2)));await settleReplay();
    assert.equal(app.dom.window.getComputedStyle(app.$('board-stage')).height,stageHeight);
    assert.equal(app.$('palette-legend').hidden,false);
    assert.equal(app.$('frame-counter').textContent,'3 / 3');assert.match(app.$('world-guide').textContent,/第2关/);assert.equal(app.$('replay-loading').hidden,true);
    assert.equal(app.requests.filter(request=>request.url.includes('/levels/2/')).length,1);
    app.$('level-1').click();await settleReplay();assert.equal(app.$('frame-counter').textContent,'1 / 3');assert.match(app.$('world-guide').textContent,/第1关/);
    app.$('level-2').click();await settleReplay();assert.equal(app.requests.filter(request=>request.url.includes('/levels/2/')).length,1);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('per-level replay retries failures and rejects obsolete games and stale revision replies',async()=>{
  const first=levelReplayFixture('game0-catalog','first-slow'),second=levelReplayFixture('game1-catalog','second-ready',{color:14});
  second.record.run.completed_level_count=1;second.record.levels[1].status='incomplete';second.manifest.levels[1].status='incomplete';
  const overview=levelReplayOverview([first,second]);overview.games[1].completed_levels=1;overview.games[1].runs[0].completed_levels=1;
  let releaseFirst,failSecond=true,staleSecond=true;
  const app=launch(fixture(),{liveConfig:levelReplayConfig,overview,fetch:async url=>{
    if(url==='/api/replay/first-slow/manifest')return new Promise(resolve=>{releaseFirst=resolve;});
    if(url==='/api/replay/second-ready/manifest')return failSecond?response({},503):response(second.manifest);
    if(url.includes('/second-ready/levels/')){if(staleSecond){staleSecond=false;return response({error:'replay-stale'},409);}return response(second.detail(2));}
    return response(idleView());
  }});
  try {
    await settleReplay();assert.ok(releaseFirst);overviewRow(app,1).querySelector('[data-overview-select]').click();await settleReplay();
    assert.equal(app.$('game-title').textContent,'game1-catalog');assert.equal(app.$('replay-retry').hidden,false);
    assert.match(app.$('replay-loading-text').textContent,/读取失败/);
    failSecond=false;app.$('replay-retry').click();await settleReplay();
    const clock=app.dom.window.Date.now;app.dom.window.Date.now=()=>clock()+2200;app.tick();await settleReplay();
    assert.equal(app.$('frame-counter').textContent,'1 / 3');assert.match(app.$('world-guide').textContent,/second-ready/);
    releaseFirst(response(first.manifest));await settleReplay();assert.equal(app.$('game-title').textContent,'game1-catalog');
    assert.equal(app.requests.some(request=>request.url.includes('/first-slow/levels/')),false);
    assert.ok(app.requests.filter(request=>request.url==='/api/replay/second-ready/manifest').length>=3);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('per-level live revision updates preserve a historical frame and playback and do not load future previews',async()=>{
  const data=levelReplayFixture('game0-catalog','live-level',{sealed:false});let current=data;
  const overview=levelReplayOverview([data]);
  const app=launch(fixture(),{liveConfig:levelReplayConfig,overview,fetch:async url=>{
    if(url.endsWith('/manifest'))return response(current.manifest);
    if(url.includes('/levels/2/'))return response(current.detail(2));
    return response(idleView());
  }});
  try {
    await settleReplay();await settleReplay();app.$('frame-slider').value='0';app.$('frame-slider').dispatchEvent(new app.dom.window.Event('input'));app.$('play-toggle').click();
    const timer=[...app.timers.values()].find(fn=>fn.intervalMs<1000);assert.ok(timer);
    current=levelReplayFixture('game0-catalog','live-level',{sealed:false,color:14});
    [...app.timers.values()].find(fn=>fn.intervalMs===2000)();await settleReplay();
    assert.equal(app.$('frame-counter').textContent,'1 / 3');assert.equal(app.$('play-toggle').textContent,'暂停');assert.ok([...app.timers.values()].includes(timer));
    assert.equal(app.requests.some(request=>request.url.startsWith('/api/preview/')),false);
    assert.equal(app.requests.some(request=>request.url==='/api/replay/live-level'),false);assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('per-level saved fallback uses the exact improved best and retires a loading ticket after selecting loaded history',async()=>{
  const live=levelReplayFixture('game0-catalog','active-retry',{sealed:false});
  live.record.run.completed_level_count=1;live.manifest.run=live.record.run;
  const makeBest=(id,color)=>{
    const data=levelReplayFixture('game0-catalog',id,{color});
    data.record.run.completed_level_count=3;data.record.run.primitive_action_count=6;
    data.record.levels[2]={...data.record.levels[1],level:3,frames:data.record.levels[1].frames.map(frame=>({...frame,id:frame.id.replace('l2','l3')})),
      actions:[...data.record.levels[1].actions,{...data.record.levels[1].actions[0],id:id+'-l3-a2'}],cognition:{scope:'final',stable_description:`游戏规则：${id} 第3关`}};
    data.manifest.run=data.record.run;data.manifest.levels=data.record.levels.map(level=>({level:level.level,status:level.status,frame_count:level.frames.length,action_count:level.actions.length,has_cognition:true}));
    return data;
  };
  const old=makeBest('saved-old',12),improved=makeBest('saved-improved',14);let best=old,releaseOld,releaseImproved;
  const overview=levelReplayOverview([live]);
  const setBest=()=>{overview.games[0]={...overview.games[0],completed_levels:3,best_run_id:best.record.run.run_id,
    runs:[{...catalogRun(best.record.run.run_id),completed_levels:3},{...catalogRun(live.record.run.run_id,'running',false),recording:true}]};};setBest();
  const app=launch(fixture(),{liveConfig:levelReplayConfig,overview:()=>overview,fetch:async url=>{
    if(url.includes('/active-retry/manifest'))return response(live.manifest);
    if(url.includes('/active-retry/levels/'))return response(live.detail(url.includes('/levels/1/')?1:2));
    if(url.includes('/saved-old/manifest'))return response(old.manifest);
    if(url.includes('/saved-improved/manifest'))return response(improved.manifest);
    if(url.includes('/saved-old/levels/3/'))return new Promise(resolve=>{releaseOld=resolve;});
    if(url.includes('/saved-improved/levels/3/'))return new Promise(resolve=>{releaseImproved=resolve;});
    return response(idleView());
  }});
  try {
    await settleReplay();assert.match(app.$('world-guide').textContent,/active-retry/);
    app.$('level-3').click();await settleReplay();assert.ok(releaseOld);assert.equal(app.$('replay-loading').hidden,false);
    assert.match(app.$('level-3').title,/已保存.*3 动作/);assert.equal(app.requests.some(request=>request.url.startsWith('/api/preview/')),false);
    best=improved;setBest();[...app.timers.values()].find(fn=>fn.intervalMs===5000)();await settleReplay();assert.ok(releaseImproved);
    releaseImproved(response(improved.detail(3)));await settleReplay();assert.match(app.$('world-guide').textContent,/saved-improved/);
    releaseOld(response(old.detail(3)));await settleReplay();assert.match(app.$('world-guide').textContent,/saved-improved/);
    assert.equal(app.$('single-board').dataset.sourceRunId,'saved-improved');
    // A new uncached revision for the selected saved level must not own another level's spinner.
    best=old;setBest();[...app.timers.values()].find(fn=>fn.intervalMs===5000)();await settleReplay();
    app.$('level-2').click();await settleReplay();assert.equal(app.$('replay-loading').hidden,true);assert.match(app.$('world-guide').textContent,/active-retry/);
    releaseOld(response(old.detail(3)));await settleReplay();assert.equal(app.$('replay-loading').hidden,true);assert.equal(app.$('level-2').getAttribute('aria-current'),'true');
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('fresh loading manifest invalidates an in-flight detail from the same saved run revision',async()=>{
  const live=levelReplayFixture('game0-catalog','revision-live',{sealed:false});
  const saved=levelReplayFixture('game0-catalog','revision-saved');
  live.record.run.completed_level_count=1;
  // Level one exists only in the saved route, while the active attempt is on level two.
  live.record.levels[0]={...live.record.levels[0],status:'not-run',frames:[],actions:[],cognition:{scope:'unavailable'}};
  live.manifest.levels[0]={...live.manifest.levels[0],status:'not-run',frame_count:0,action_count:0,has_cognition:false};
  const overview=levelReplayOverview([live]);overview.games[0]={...overview.games[0],best_run_id:'revision-saved',
    runs:[{...catalogRun('revision-saved'),completed_levels:2},{...catalogRun('revision-live','running',false),recording:true}]};
  let ready=true,releaseSaved;
  const app=launch(fixture(),{liveConfig:levelReplayConfig,overview,fetch:async url=>{
    if(url.includes('/revision-live/manifest'))return response(live.manifest);
    if(url.includes('/revision-live/levels/'))return response(live.detail(2));
    if(url.includes('/revision-saved/manifest'))return response(ready?saved.manifest:{schema:saved.manifest.schema,state:'loading',run_id:'revision-saved',revision:null,run:null,levels:[],warnings:[]},ready?200:202);
    if(url.includes('/revision-saved/levels/1/'))return new Promise(resolve=>{releaseSaved=resolve;});
    return response(idleView());
  }});
  try {
    await settleReplay();app.$('level-1').click();await settleReplay();assert.ok(releaseSaved);
    assert.equal(app.$('board-empty').hidden,false);ready=false;
    [...app.timers.values()].find(fn=>fn.intervalMs===5000)();await settleReplay();
    releaseSaved(response(saved.detail(1)));await settleReplay();
    assert.equal(app.$('board-empty').hidden,false);assert.doesNotMatch(app.$('world-guide').textContent,/revision-saved/);
    assert.equal(app.$('replay-loading').hidden,false);assert.match(app.$('level-1').title,/已保存.*1 动作/);
    assert.equal(app.requests.some(request=>request.url.startsWith('/api/preview/')&&!request.url.endsWith('/3')),false);assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('verified sealed partial saved prefixes load history without claiming full-run replay success',async()=>{
  for (const lazy of [true,false]) {
    const live=levelReplayFixture('game0-catalog','partial-active',{sealed:false});
    live.record.run.completed_level_count=1;live.record.levels[0]={...live.record.levels[0],frames:[],actions:[],cognition:{scope:'unavailable'}};
    live.record.levels[1].status='incomplete';
    live.manifest.levels=live.record.levels.map(level=>({level:level.level,status:level.status,frame_count:level.frames.length,action_count:level.actions.length,has_cognition:level.cognition.scope==='final'}));
    const saved=levelReplayFixture('game0-catalog','verified-partial');saved.record.run.replay_verified=false;
    const overview=levelReplayOverview([live]);overview.games[0]={...overview.games[0],completed_levels:2,best_run_id:'verified-partial',
      runs:[{...catalogRun('verified-partial','incomplete',true),completed_levels:2},{...catalogRun('partial-active','running',false),recording:true}]};
    const config=lazy?levelReplayConfig:{...levelReplayConfig,replay_loading:undefined};
    const app=launch(fixture(),{liveConfig:config,overview,fetch:async url=>{
      if(url==='/api/replay/partial-active')return response(live.record);
      if(url==='/api/replay/verified-partial')return response(saved.record);
      if(url.includes('/partial-active/manifest'))return response(live.manifest);
      if(url.includes('/partial-active/levels/'))return response(live.detail(2));
      if(url.includes('/verified-partial/manifest'))return response(saved.manifest);
      if(url.includes('/verified-partial/levels/1/'))return response(saved.detail(1));
      return response(idleView());
    }});
    try {
      await settleReplay();app.$('level-1').click();await settleReplay();
      assert.equal(app.$('single-board').dataset.sourceRunId,'verified-partial');assert.equal(app.$('single-board').dataset.sourceScope,'saved');
      assert.equal(app.$('frame-counter').textContent,'1 / 3');assert.match(app.$('world-guide').textContent,/verified-partial 第1关/);
      assert.match(app.$('level-1').title,/已保存.*1 动作/);assert.match(app.$('run-progress-summary').textContent,/已保存 2 \/ 3/);
      assert.equal(app.dom.window.__ASTERION_STATE__.run.run_id,'partial-active');assert.equal(app.dom.window.__ASTERION_STATE__.run.replay_verified,false);
      assert.equal(saved.record.run.replay_verified,false);assert.equal(saved.record.run.status,'incomplete');
      assert.equal(overviewRow(app).querySelector('.overview-result-badge').textContent,'◐ 部分通关');
      assert.equal(app.requests.some(request=>request.url.startsWith('/api/preview/')&&!request.url.endsWith('/3')),false);assert.deepEqual(app.errors,[]);
    } finally {app.dom.window.close();}
  }
});

test('recording-only failed attempts default to their latest recorded cognition without claiming saved progress',async()=>{
  const config={token:'test-token',games:[{game_id:'game0-catalog',alias:'preview',win_levels:3}]};
  const overview=overviewFixture(config);overview.games[0]={...overview.games[0],status:'unverified',recording_run_id:'stopped-recording',latest_run_id:'stopped-recording',
    runs:[{...catalogRun('stopped-recording','unverified',false),completed_levels:0,recording:true}]};
  const initial={schema:'asterion.arc-agi3-p7-console/v1',generated_at:null,
    run:{game_id:'game0-catalog',run_id:null,status:'preview',seed:0,win_levels:3,completed_level_count:0,primitive_action_count:0,target_level:1,replay_verified:false,sealed_trace:false},
    levels:[{level:1,status:'preview',frames:[{id:'real-initial',grid:[[12]],state:'NOT_FINISHED',levels_completed:0}],actions:[],decisions:[],cognition:{scope:'unavailable'},receipt:null}],decisions:[],warnings:[]};
  const attempt={...fixture(),run:{...fixture().run,game_id:'game0-catalog',run_id:'stopped-recording',seed:0,sealed_trace:false}};
  const app=launch(fixture(),{liveConfig:config,overview,fetch:async url=>response(url==='/api/preview/game0-catalog'?initial:url==='/api/replay/stopped-recording'?attempt:idleView())});
  try {
    await settleReplay();assert.equal(app.$('board-empty').hidden,true);assert.equal(app.$('run-id').textContent,'stopped-recording');
    assert.equal(app.dom.window.__ASTERION_STATE__.run.run_id,'stopped-recording');assert.equal(app.$('level-progress').textContent,'0 / 3');
    assert.equal(app.requests.some(request=>request.url==='/api/replay/stopped-recording'),true);
    assert.equal(app.requests.some(request=>request.url==='/api/preview/game0-catalog'),false);
    assert.match(app.$('world-guide').textContent,/ACTION4 使物件向右移动/);
    [...app.timers.values()].find(fn=>fn.intervalMs===5000)();await settleReplay();assert.equal(app.$('run-id').textContent,'stopped-recording');
    overviewRow(app).querySelector('[data-overview-watch]').click();await settleReplay();assert.equal(app.$('run-id').textContent,'stopped-recording');
    assert.equal(app.dom.window.__ASTERION_STATE__.run.run_id,'stopped-recording');assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});

test('zero-saved game selection prefers a corroborated solving run then the latest attempt at level 1',async()=>{
  for (const solving of [false,true]) {
    const data=levelReplayFixture('game1-catalog',solving?'solving-zero':'latest-zero',{sealed:false});
    Object.assign(data.record.run,{completed_level_count:0,status:solving?'running':'failed'});
    data.record.levels.forEach((level,index)=>{
      level.status=index===0?'incomplete':'not-run';
      if (index>0) Object.assign(level,{frames:[],actions:[],cognition:{scope:'unavailable'}});
    });
    const level=data.record.levels[0],frame=level.frames.at(-1);
    level.cognition={scope:'unavailable'};
    level.cognition_timeline=[{scope:'observation',frame_id:frame.id,event_sequence:3,source_action_sequence:1,
      stable_description:'当前记录认知：ACTION1 推动棋子。'}];
    data.record.process_events=[{kind:'compute_task',level:1,frame_id:frame.id,event_sequence:3,
      payload:{status:'completed',summary:'已检查当前棋盘'}}];
    data.manifest.levels=data.record.levels.map(item=>({level:item.level,status:item.status,frame_count:item.frames.length,
      action_count:item.actions.length,has_cognition:item.level===1}));
    const overview=overviewFixture(levelReplayConfig);
    overview.games[1]={...overview.games[1],status:'unverified',latest_run_id:solving?'stale-zero':'latest-zero',
      solving,solving_run_id:solving?'solving-zero':null,runs:[
        {...catalogRun('stale-zero','unverified',false),completed_levels:0,recording:true},
        {...catalogRun(data.record.run.run_id,'unverified',false),completed_levels:0,recording:true}]};
    const app=launch(fixture(),{liveConfig:levelReplayConfig,overview,fetch:async url=>{
      if(url===`/api/replay/${data.record.run.run_id}/manifest`)return response(data.manifest);
      if(url.includes(`/api/replay/${data.record.run.run_id}/levels/1/`))return response(data.detail(1));
      return response(idleView());
    }});
    try {
      await settleReplay();overviewRow(app,1).querySelector('[data-overview-select]').click();await settleReplay();
      assert.equal(app.$('run-id').textContent,data.record.run.run_id);
      assert.equal(app.$('board-kicker').textContent,'LEVEL 01');assert.equal(app.$('frame-counter').textContent,'1 / 3');
      assert.equal(app.$('replay-follow').hidden,false);app.$('replay-follow').click();
      assert.equal(app.$('frame-counter').textContent,'3 / 3');
      assert.equal(app.$('replay-follow').hidden,true);
      assert.match(app.$('world-guide').textContent,/当前记录认知：ACTION1 推动棋子/);
      assert.equal(app.$('event-counter').textContent,'事件 3');
      assert.equal(app.$('level-progress').textContent,'0 / 3');
      assert.equal(app.requests.some(request=>request.url.startsWith('/api/preview/game1-catalog')),false);
      assert.deepEqual(app.errors,[]);
    } finally {app.dom.window.close();}
  }
});

test('external solving metadata keeps verified saved progress as the default replay',async()=>{
  const overview=overviewFixture(catalog25);
  overview.games[0]={...overview.games[0],status:'partial',completed_levels:1,best_run_id:'saved-best',
    latest_run_id:'external-solving',solving:true,solving_run_id:'external-solving',runs:[catalogRun('saved-best'),
      {...catalogRun('external-solving','unverified',false),recording:true}]};
  const saved={...fixture(),run:{...fixture().run,game_id:'game0-catalog',run_id:'saved-best',sealed_trace:true}};
  const app=launch(fixture(),{liveConfig:catalog25,overview,fetch:async url=>response(url==='/api/replay/saved-best'?saved:idleView())});
  try {
    await settleReplay();assert.equal(app.$('run-id').textContent,'saved-best');
    assert.equal(app.requests.some(request=>request.url==='/api/replay/external-solving'),false);
    assert.deepEqual(app.errors,[]);
  } finally {app.dom.window.close();}
});
