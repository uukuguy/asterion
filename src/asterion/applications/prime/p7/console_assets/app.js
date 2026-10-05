(() => {
  'use strict';

  // Official ARC-AGI-3 colors, verified against arc_agi/rendering.py.
  const PALETTE = ['#FFFFFF', '#CCCCCC', '#999999', '#666666', '#333333', '#000000', '#E53AA3', '#FF7BCC', '#F93C31', '#1E93FF', '#88D8F1', '#FFDC00', '#FF851B', '#921231', '#4FCC30', '#A356D6'];
  const COLOR_NAMES = ['白色', '浅灰色', '灰色', '深灰色', '炭灰色', '黑色', '品红色', '粉色', '红色', '蓝色', '浅蓝色', '黄色', '橙色', '暗红色', '绿色', '紫色'];
  const $ = (id) => document.getElementById(id);
  const array = (value) => Array.isArray(value) ? value : [];
  const object = (value) => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const string = (value, fallback = '未记录') => typeof value === 'string' && value ? value : fallback;
  const number = (value, fallback = 0) => Number.isFinite(value) ? value : fallback;
  const write = (id, value) => { $(id).textContent = String(value); };
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  };
  const isRecord = (value) => Boolean(value && typeof value === 'object' && !Array.isArray(value));
  const optionalRecords = (value, check = isRecord) => value === undefined || (Array.isArray(value) && value.every(check));
  const optionalString = (value) => value == null || typeof value === 'string';
  const optionalNumber = (value) => value == null || (typeof value === 'number' && Number.isFinite(value));
  const stringFields = (value, fields) => fields.every((key) => optionalString(value[key]));
  const numberFields = (value, fields) => fields.every((key) => optionalNumber(value[key]));
  const validDecision = (decision) => isRecord(decision) && typeof decision.id === 'string' && decision.id.length > 0 &&
    (decision.action_ids === undefined || (Array.isArray(decision.action_ids) && decision.action_ids.every((id) => typeof id === 'string'))) &&
    stringFields(decision, ['source', 'goal', 'basis', 'expected']) && numberFields(decision, ['trace_sequence', 'round_index']);
  const validClaim = (claim) => isRecord(claim) && stringFields(claim, ['id', 'kind', 'status', 'claim']);
  const validCognition = (cognition) => cognition === undefined || (isRecord(cognition) &&
    stringFields(cognition, ['scope', 'stable_description']) &&
    optionalRecords(cognition.updates, (update) => isRecord(update) && optionalString(update.type) && optionalNumber(update.sequence) && optionalRecords(update.changes, validClaim)) &&
    (cognition.action_meanings === undefined || (isRecord(cognition.action_meanings) && Object.values(cognition.action_meanings).every((entries) => optionalRecords(entries, validClaim)))));
  const validTimelineEntry = (entry) => isRecord(entry) &&
    stringFields(entry, ['scope', 'frame_id', 'action_id', 'stable_description', 'cognition_narrative_zh']) &&
    numberFields(entry, ['cognition_revision', 'source_action_sequence', 'event_sequence']);
  function validSnapshot(value) {
    if (!isRecord(value) || value.schema !== 'asterion.arc-agi3-p7-console/v1' || !isRecord(value.run) || !Array.isArray(value.levels)) return false;
    if (!optionalRecords(value.decisions, validDecision) || !stringFields(value.run, ['status', 'game_id', 'run_id']) || !optionalString(value.generated_at)) return false;
    const run = value.run;
    if (run.win_levels != null && (!Number.isInteger(run.win_levels) || run.win_levels < 0 || run.win_levels > 1000)) return false;
    const ids = new Set();
    return value.levels.every((level) => {
      if (!isRecord(level) || !Number.isInteger(level.level) || level.level < 1 || level.level > 1000 || ids.has(level.level)) return false;
      ids.add(level.level);
      if (!Array.isArray(level.frames) || !Array.isArray(level.actions) || !Array.isArray(level.decisions) || !optionalString(level.status) || !validCognition(level.cognition)) return false;
      const frameIds = new Set(), actionIds = new Set();
      return level.frames.every((frame) => {
        if (!isRecord(frame) || typeof frame.id !== 'string' || !frame.id || frameIds.has(frame.id) || !Array.isArray(frame.grid)) return false;
        if (!stringFields(frame, ['state', 'timestamp'])) return false;
        frameIds.add(frame.id);
        const width = frame.grid.length ? array(frame.grid[0]).length : 0;
        return frame.grid.length <= 256 && width <= 256 && frame.grid.every((row) => Array.isArray(row) && row.length === width && row.every((color) => Number.isInteger(color) && color >= 0 && color < PALETTE.length));
      }) && level.actions.every((action) => {
        if (!isRecord(action) || typeof action.id !== 'string' || !action.id || actionIds.has(action.id) || typeof action.name !== 'string') return false;
        if (!stringFields(action, ['before_frame', 'after_frame', 'decision_id']) || !numberFields(action, ['trace_sequence'])) return false;
        actionIds.add(action.id); return true;
      }) && level.decisions.every(validDecision) && (level.cognition_timeline === undefined || (Array.isArray(level.cognition_timeline) && level.cognition_timeline.every(validTimelineEntry)));
    });
  }
  let snapshot;
  try {
    snapshot = JSON.parse($('console-data').textContent);
    if (!validSnapshot(snapshot)) throw new Error('schema');
  } catch (_) {
    write('evidence-warning', '控制台快照无法读取，或数据版本不受支持。');
    $('evidence-warning').hidden = false;
    document.querySelectorAll('button, input, select').forEach((element) => { element.disabled = true; });
    return;
  }
  window.__ASTERION_STATE__ = snapshot;
  let run = object(snapshot.run);
  let recordedLevels = array(snapshot.levels);
  let levelCount = Math.max(0, number(run.win_levels), ...recordedLevels.map((level) => number(level.level)));
  let levels = Array.from({ length: levelCount }, (_, index) => recordedLevels.find((level) => level.level === index + 1) || {
    level: index + 1, status: 'not_run', frames: [], actions: [], decisions: [], cognition: { scope: 'unavailable' }, receipt: null,
  });
  let liveConfig = null;
  try { liveConfig = JSON.parse($('console-config').textContent); } catch (_) { /* An invalid config never enables requests. */ }
  if (!isRecord(liveConfig) || typeof liveConfig.token !== 'string' || !liveConfig.token) liveConfig = null;
  const state = { mode: liveConfig ? 'live' : 'replay', replayRun: null, replayGeneration: 0, manualGeneration: 0, manualPollGeneration: 0, manualBusy: false, manualError: false, manualView: null, manualChoice: null, manualPending: null, pointerAction: null, liveView: null, pendingCommand: null, commandBusy: false, pollBusy: false, pollTimer: null, levelIndex: Math.max(0, levels.findIndex((level) => array(level.frames).length)), frameIndex: 0, actionId: null, timer: null, tab: 'decisions' };
  const emptyLevel = { level: null, status: 'not-run', frames: [], actions: [], decisions: [], cognition: { scope: 'unavailable' }, receipt: null };
  const currentLevel = () => levels[state.levelIndex] || emptyLevel;
  const frames = () => array(currentLevel().frames);
  const actions = () => array(currentLevel().actions);
  const currentFrame = () => frames()[state.frameIndex];
  const frameById = (id) => frames().find((frame) => frame.id === id);
  const selectedAction = () => actions().find((action) => action.id === state.actionId) || null;
  const manualPlayable = () => state.mode === 'manual' && run.status === 'manual' && state.manualView?.state === 'ready' &&
    state.manualView.game_id === run.game_id && manualLevel(state.manualView) === currentLevel().level && !state.manualBusy && !state.manualPending && !state.manualError &&
    !state.commandBusy && !state.pendingCommand && !activeSession() && Boolean(currentFrame());
  const statuses = {
    completed: ['已过关', 'success'], successful: ['已成功', 'success'], success: ['已成功', 'success'], won: ['已过关', 'success'],
    running: ['运行中', 'active'], active: ['可继续', 'active'], in_progress: ['进行中', 'active'],
    incomplete: ['未完成', 'warning'], interrupted: ['已中断', 'warning'], waiting: ['等待', 'warning'], unknown: ['信息不足', 'warning'],
    unsuccessful: ['未成功', 'failed'], failed: ['失败', 'failed'], game_over: ['游戏结束', 'failed'],
    manual: ['人工试玩', 'neutral'], 'not-run': ['未运行', 'neutral'], not_run: ['未运行', 'neutral'], unobserved: ['未运行', 'neutral'], unavailable: ['无证据', 'neutral'],
  };
  const statusInfo = (value) => Object.hasOwn(statuses, value) ? statuses[value] : ['信息不足', 'warning'];
  const setStatus = (element, value) => {
    const [label, tone] = statusInfo(value);
    element.textContent = label;
    element.className = `status-tag status-${tone}`;
  };
  const frameState = (value) => ({ NOT_PLAYED: '尚未开始', NOT_FINISHED: '未结束', WIN: 'WIN · 已胜利', GAME_OVER: 'GAME OVER · 已结束' }[value] || string(value, '状态未记录'));
  const frameLabel = (frame) => frame ? `${string(frame.id)} · ${frameState(frame.state)}` : '帧记录缺失';
  const actionLabel = (action) => {
    const data = object(action.data);
    const point = Number.isFinite(data.x) && Number.isFinite(data.y) ? ` (${data.x}, ${data.y})` : '';
    return `${string(action.name, '未知动作')}${point}`;
  };
  const signalNames = { 'tool-guidance': '工具使用指引', 'mechanics-prior': '机制先验', 'state-guidance': '状态指引', 'application-state': '应用状态', 'completion-guidance': '完成条件指引', plan: '规划信号', observation: '观察信号', prior: '先验信号', action: '动作信号', progress: '进展信号' };
  const scalarText = (value) => {
    if (typeof value === 'boolean') return value ? '是' : '否';
    if (typeof value === 'number' || typeof value === 'string') return String(value);
    return '未记录';
  };

  function renderRunHeader() {
    write('game-title', string(run.game_id, '未识别游戏'));
    write('run-id', run.status === 'manual' ? '尚未启动 P7' : string(run.run_id));
    write('level-progress', `${number(run.completed_level_count)} / ${number(run.win_levels) || '未知'}`);
    write('action-total', number(run.primitive_action_count));
    write('level-total', levelCount ? `${levelCount} 个关卡` : '总数未知');
    setStatus($('run-status'), run.status);
    write('snapshot-date', `快照时间 ${string(snapshot.generated_at)}`);
    write('verification-note', run.status === 'manual' ? '独立人工试玩；启动 P7 会重置游戏并开始新的运行。' : `${run.replay_verified === true ? '回放已验证。' : '回放验证未确认。'}${run.sealed_trace === true ? '具有封存轨迹。' : '无封存成功证明。'}`);
    const warnings = array(snapshot.warnings).filter((warning) => typeof warning === 'string');
    $('evidence-warning').hidden = !warnings.length;
    write('evidence-warning', warnings.length ? `证据提示 · ${warnings.join('；')}` : '');
  }

  function renderRail() {
    const list = $('level-list');
    list.replaceChildren();
    if (!levels.length) list.append(node('p', '没有可验证的关卡记录。', 'guide-empty'));
    levels.forEach((level, index) => {
      const button = node('button', undefined, 'level-button');
      button.id = `level-${level.level}`;
      button.type = 'button';
      button.setAttribute('aria-current', String(index === state.levelIndex));
      const manual = state.mode === 'manual';
      const [label, tone] = manual && !array(level.frames).length ? ['可直接试玩', 'neutral'] : statusInfo(level.status === 'successful' ? 'completed' : level.status);
      button.disabled = manual && manualSelectionLocked();
      button.setAttribute('aria-label', `关卡 ${level.level}，${label}，${array(level.actions).length} 个动作`);
      button.append(node('span', String(level.level).padStart(2, '0'), 'level-number'));
      const content = node('div', undefined, 'level-item-content');
      const heading = node('div', undefined, 'level-item-heading');
      const dot = node('span', undefined, `level-status-dot status-${tone}`);
      dot.setAttribute('aria-hidden', 'true');
      heading.append(node('strong', `关卡 ${level.level}`), dot);
      content.append(heading, node('p', label, 'level-item-status'));
      content.append(node('p', `${array(level.actions).length} 动作 · ${array(level.frames).length ? `${array(level.frames).length} 帧` : '无画面'}${level.receipt ? ' · 回执' : ''}`, 'level-item-detail'));
      button.append(content);
      button.addEventListener('click', () => {
        if (state.mode !== 'manual') { selectLevel(index); return; }
        if (manualSelectionLocked()) return;
        if (state.manualView?.state === 'ready' && !state.manualError && state.manualView.game_id === run.game_id && manualLevel(state.manualView) === level.level && array(level.frames).length) selectLevel(index);
        else openManual(level.level);
      });
      list.append(button);
    });
  }

  function selectLevel(index) {
    pause();
    state.levelIndex = index;
    state.frameIndex = 0;
    state.actionId = null;
    renderRail();
    write('board-kicker', currentLevel().level === null ? 'LEVEL —' : `LEVEL ${String(currentLevel().level).padStart(2, '0')}`);
    write('board-title', run.status === 'manual' ? `关卡 ${currentLevel().level} · 人工试玩` : currentLevel().level === null ? '游戏画面 · 未记录关卡' : `关卡 ${currentLevel().level} · 游戏画面`);
    setStatus($('level-status'), currentLevel().status === 'successful' ? 'completed' : currentLevel().status);
    renderWorld();
    renderProcess();
    renderReceipt();
    renderFrame();
    write('playback-announcement', currentLevel().level === null ? '没有可验证的关卡记录。' : `已选择关卡 ${currentLevel().level}，${frames().length} 帧。`);
  }

  function draw(canvas, frame, before, action) {
    const grid = array(frame && frame.grid);
    const rows = grid.length;
    const columns = rows ? array(grid[0]).length : 0;
    if (!rows || !columns) { canvas.width = 1; canvas.height = 1; return; }
    const cell = Math.max(6, Math.floor(512 / Math.max(rows, columns)));
    canvas.width = columns * cell;
    canvas.height = rows * cell;
    const context = canvas.getContext('2d');
    context.imageSmoothingEnabled = false;
    grid.forEach((row, y) => array(row).forEach((color, x) => {
      context.fillStyle = PALETTE[color] || '#FFFFFF';
      context.fillRect(x * cell, y * cell, cell, cell);
    }));
    const previous = array(before && before.grid);
    if ($('diff-toggle').checked && previous.length) {
      context.strokeStyle = '#FFD84D';
      context.lineWidth = Math.max(1, cell * 0.18);
      grid.forEach((row, y) => array(row).forEach((color, x) => {
        if (array(previous[y])[x] !== color) context.strokeRect(x * cell + 1, y * cell + 1, cell - 2, cell - 2);
      }));
    }
    const point = object(action && action.data);
    if ($('highlight-toggle').checked && Number.isFinite(point.x) && Number.isFinite(point.y) && point.x >= 0 && point.y >= 0 && point.x < columns && point.y < rows) {
      const x = (point.x + 0.5) * cell;
      const y = (point.y + 0.5) * cell;
      context.strokeStyle = '#FFFFFF';
      context.lineWidth = 3;
      context.beginPath(); context.arc(x, y, Math.max(cell * 0.8, 5), 0, Math.PI * 2); context.stroke();
      context.strokeStyle = '#3159A7'; context.lineWidth = 1.5; context.stroke();
    }
    canvas.setAttribute('aria-label', `${columns} × ${rows} 网格，${frameLabel(frame)}${$('diff-toggle').checked && previous.length ? '，黄色方框为变化格回放标记，不属于游戏画面' : ''}`);
  }

  function renderPalette(visibleFrames) {
    const used = new Set();
    visibleFrames.forEach((frame) => array(frame && frame.grid).forEach((row) => array(row).forEach((color) => {
      if (Number.isInteger(color) && color >= 0 && color < PALETTE.length) used.add(color);
    })));
    const colors = $('palette-colors');
    colors.replaceChildren();
    [...used].sort((a, b) => a - b).forEach((color) => {
      const item = node('span', undefined, 'palette-color');
      item.setAttribute('role', 'listitem');
      item.dataset.color = String(color);
      const swatch = node('span', undefined, 'palette-swatch');
      swatch.style.backgroundColor = PALETTE[color];
      swatch.setAttribute('aria-hidden', 'true');
      item.append(swatch, node('span', `${COLOR_NAMES[color]}（${color}）`));
      colors.append(item);
    });
    $('palette-legend').hidden = used.size === 0;
  }

  const actionMeanings = () => !array(currentLevel().cognition_timeline).length && object(currentLevel().cognition).scope === 'final' ? object(object(currentLevel().cognition).action_meanings) : {};
  const meaningEntries = (entries) => array(entries).filter((entry) => entry && ['certain', 'undetermined', 'falsified'].includes(entry.status) && typeof entry.claim === 'string' && entry.claim);

  function shortActionMeaning(name, entries) {
    const directions = { 上: '上移', 下: '下移', 左: '左移', 右: '右移' };
    const candidates = [];
    entries.forEach((entry) => {
      entry.claim.split(/[。；;\n]/).forEach((clause) => {
        const names = [...new Set(clause.match(/(?<![A-Za-z0-9_])ACTION[1-7](?![A-Za-z0-9_])/g) || [])];
        if (names.length !== 1 || names[0] !== name) return;
        const denied = [...new Set([...clause.matchAll(/(?:不会|不能|无法|并非|没有|未曾|不曾|不|未)\s*(?:向([上下左右])(?:移动|平移)|([上下左右])移)/g)].map((match) => match[1] || match[2]))];
        denied.forEach((direction) => candidates.push({ status: entry.status, direction, affirmative: false }));
        if (/不|未|无|否|并非/.test(clause)) return;
        const found = [...new Set([...clause.matchAll(/(?:向([上下左右])(?:移动|平移)|([上下左右])移)/g)].map((match) => match[1] || match[2]))];
        if (found.length === 1) candidates.push({ status: entry.status, direction: found[0], affirmative: true });
      });
    });
    const supported = candidates.filter((entry) => entry.affirmative && entry.status !== 'falsified');
    const found = [...new Set(supported.map((entry) => entry.direction))];
    const contradicted = candidates.some((entry) => entry.direction === found[0] && (entry.affirmative ? entry.status === 'falsified' : entry.status !== 'falsified'));
    if (found.length !== 1 || contradicted) return { meaning: '未识别', status: '?' };
    return { meaning: directions[found[0]], status: supported.some((entry) => entry.status === 'certain') ? '已识别' : '推测' };
  }

  function renderAvailableActions(frame, action) {
    const hasAvailability = Boolean(frame && Array.isArray(frame.available_actions));
    const available = [...new Set(array(frame && frame.available_actions).filter((name) => typeof name === 'string' && name))];
    const beforeIndex = action ? frames().findIndex((item) => item.id === action.before_frame) : -1;
    const afterIndex = action ? frames().findIndex((item) => item.id === action.after_frame) : -1;
    const linked = action && frame && (frame.id === action.after_frame || (beforeIndex >= 0 && afterIndex >= beforeIndex && state.frameIndex > beforeIndex && state.frameIndex <= afterIndex));
    const manual = state.mode === 'manual' && run.status === 'manual';
    const activeName = manual ? frame ? state.manualView?.last_action?.action : null : linked ? action.name : null;
    const meanings = actionMeanings();
    const card = (name, availability) => {
      const active = name === activeName;
      const armed = manual && name === state.pointerAction;
      const wrapper = node('div');
      wrapper.setAttribute('role', 'listitem');
      const item = node('button', undefined, `available-action${active ? ' is-current' : ''}${armed ? ' is-armed' : ''}`);
      item.type = 'button';
      const recorded = actions().filter((entry) => entry.name === name).map((entry) => ({
        action: entry, index: frames().findIndex((frame) => frame.id === entry.after_frame || (!frameById(entry.after_frame) && frame.id === entry.before_frame)),
      })).filter((entry) => entry.index >= 0);
      item.disabled = manual ? !manualPlayable() || Boolean(availability) : state.mode === 'live' || Boolean(availability) || recorded.length === 0;
      item.title = manual ? name === 'ACTION6' ? '选择后点击游戏画面上的目标格' : '执行一次人工试玩动作' : state.mode === 'live' ? 'P7 运行中的动作观察；不发送游戏动作' : availability || (recorded.length ? '定位该动作的下一条回放记录' : '没有可定位的已录动作');
      item.addEventListener('click', () => {
        if (manual) {
          if (item.disabled) return;
          if (name === 'ACTION6') { state.pointerAction = 'ACTION6'; renderFrame(); renderSessionControls(); return; }
          sendManualAction(name); return;
        }
        const target = recorded.find((entry) => entry.index > state.frameIndex) || recorded[0];
        if (!item.disabled && target) locateAction(target.action);
      });
      item.dataset.availableAction = name;
      if (active) item.setAttribute('aria-current', 'true');
      if (manual && name === 'ACTION6') item.setAttribute('aria-pressed', String(armed));
      const short = shortActionMeaning(name, meaningEntries(meanings[name]));
      item.append(node('strong', name, 'action-key-label'), node('span', short.meaning, 'action-key-meaning'), node('span', short.status, 'action-key-status'));
      item.setAttribute('aria-label', `${name}，${short.meaning}，${short.status === '?' ? '含义未知' : short.status}，${manual ? '人工试玩动作' : '定位已录动作'}${active ? `，${availability || '当前动作'}` : ''}${armed ? '，等待点击目标格' : ''}`);
      wrapper.append(item);
      return wrapper;
    };
    const list = $('available-actions');
    list.replaceChildren();
    if (!available.length) list.append(node('span', hasAvailability ? '当前帧没有可用动作。' : '未记录可用动作。', 'available-actions-empty'));
    available.forEach((name) => list.append(card(name)));
    const unavailable = $('unavailable-current-action');
    unavailable.replaceChildren();
    unavailable.hidden = !activeName || available.includes(activeName);
    if (!unavailable.hidden) unavailable.append(card(activeName, hasAvailability ? '已执行／当前不可用' : '已执行／可用性未记录'));
  }

  function renderFrame() {
    const count = frames().length;
    const frame = currentFrame();
    const action = selectedAction();
    renderWorld();
    renderAvailableActions(frame, action);
    const before = action && frameById(action.before_frame);
    const after = action && frameById(action.after_frame);
    const comparisonRequested = $('compare-toggle').checked;
    const canCompare = Boolean(before && after);
    $('board-empty').hidden = count > 0;
    $('board-empty').querySelector('h3').textContent = run.status === 'manual' && state.manualBusy ? '正在打开人工试玩' : run.status === 'manual' && state.manualError ? '人工试玩暂不可用' : '当前关卡没有可回放画面';
    $('board-empty').querySelector('p').textContent = run.status === 'manual' ? (state.manualBusy ? '正在读取所选游戏的初始观察，尚未启动 P7。' : state.manualError ? '试玩操作未确认；可重新选择游戏开启新的试玩。' : '该关卡尚无真实观察记录；人工试玩仅展示当前关卡的真实画面。') : '没有记录帧，无法恢复该关卡的画面。';
    $('single-board').hidden = count === 0 || (comparisonRequested && canCompare);
    $('comparison-board').hidden = count === 0 || !comparisonRequested || !canCompare;
    $('frame-slider').max = String(Math.max(0, count - 1));
    $('frame-slider').value = String(state.frameIndex);
    $('frame-slider').disabled = count < 2;
    write('frame-counter', `${count ? state.frameIndex + 1 : 0} / ${count}`);
    write('frame-state', frame ? frameState(frame.state) : '无帧记录');
    write('frame-caption', run.status === 'manual' && frame ? '人工试玩当前观察 · 尚未启动 P7' : frame ? `${string(frame.id)}${frame.timestamp ? ` · ${frame.timestamp}` : ''}` : '当前关卡无帧记录');
    $('board-canvas').style.cursor = state.mode === 'manual' && state.pointerAction === 'ACTION6' ? 'crosshair' : '';
    const decision = action && action.decision_id;
    const showDecisionLink = Boolean(action && run.status !== 'manual');
    write('current-action-link', showDecisionLink ? (decision ? `决策关联 ${decision}` : '未建立可靠的 P7 轮次关联') : '');
    $('current-action-link').hidden = !showDecisionLink;
    const evidence = $('current-action-evidence');
    evidence.replaceChildren();
    if (action) renderActionEvidence(evidence, action);
    evidence.hidden = !evidence.childElementCount;
    $('current-action-strip').hidden = !showDecisionLink && evidence.hidden;
    const changed = action && action.changed_cells;
    write('change-caption', action ? `结算变化 ${Number.isFinite(changed) ? changed : array(changed).length} 格${changed === 0 ? ' · 画面未变化' : ''}` : '游戏原始画面');
    write('comparison-note', comparisonRequested ? (canCompare ? '对照显示所选动作的起始帧与结算帧' : action ? '前后帧缺链，无法对照' : '选择一个有前后帧的动作以对照') : '');
    const overlayNotes = [];
    if ($('diff-toggle').checked) overlayNotes.push('黄色方框为回放标记，不属于游戏画面');
    if ($('highlight-toggle').checked) overlayNotes.push('圆圈为点击位置回放标记，不属于游戏画面');
    write('overlay-note', overlayNotes.join('；'));
    $('overlay-note').hidden = overlayNotes.length === 0;
    renderPalette(comparisonRequested && canCompare ? [before, after] : [frame]);
    if (frame) draw($('board-canvas'), frame, before, action);
    if (comparisonRequested && canCompare) {
      draw($('before-canvas'), before, null, action);
      draw($('after-canvas'), after, before, action);
      write('before-label', `动作前 · ${string(before.id)}`);
      write('after-label', `动作后 · ${string(after.id)}`);
    }
    $('previous-frame').disabled = !count || state.frameIndex <= 0;
    $('next-frame').disabled = !count || state.frameIndex >= count - 1;
    $('play-toggle').disabled = state.mode !== 'replay' || count < 2;
    $('play-speed').disabled = count < 2;
    $('previous-action').disabled = actionTarget(-1) === null;
    $('next-action').disabled = actionTarget(1) === null;
    document.querySelectorAll('[data-action-id]').forEach((card) => card.classList.toggle('is-selected', card.dataset.actionId === state.actionId));
    document.querySelectorAll('[data-decision-id]').forEach((card) => card.classList.toggle('is-selected', Boolean(decision) && card.dataset.decisionId === decision));
  }

  function setFrame(index, actionId) {
    if (!frames().length) return;
    state.frameIndex = Math.max(0, Math.min(frames().length - 1, index));
    if (actionId !== undefined) state.actionId = actionId;
    else {
      const linked = actions().filter((action) => {
        const before = frames().findIndex((frame) => frame.id === action.before_frame);
        const after = frames().findIndex((frame) => frame.id === action.after_frame);
        return after === state.frameIndex || (before >= 0 && after >= before && state.frameIndex > before && state.frameIndex <= after);
      });
      state.actionId = linked.length ? linked[linked.length - 1].id : null;
    }
    renderFrame();
  }

  function locateAction(action) {
    pause();
    const target = frames().findIndex((frame) => frame.id === action.after_frame);
    const fallback = frames().findIndex((frame) => frame.id === action.before_frame);
    if (target >= 0 || fallback >= 0) setFrame(target >= 0 ? target : fallback, action.id);
    else { state.actionId = action.id; renderFrame(); }
  }

  function actionTarget(direction) {
    const linked = actions().map((action) => ({ action, index: frames().findIndex((frame) => frame.id === action.after_frame) })).filter((item) => item.index >= 0);
    const position = linked.findIndex((item) => item.action.id === state.actionId);
    if (position >= 0) return linked[position + direction] || null;
    if (direction > 0) return linked.find((item) => item.index > state.frameIndex) || null;
    return linked.filter((item) => item.index < state.frameIndex).pop() || null;
  }

  function pause() {
    if (state.timer !== null) window.clearInterval(state.timer);
    state.timer = null;
    write('play-toggle', '播放');
    $('play-toggle').setAttribute('aria-pressed', 'false');
  }

  function play() {
    if (state.mode !== 'replay' || frames().length < 2) return;
    if (state.frameIndex >= frames().length - 1) setFrame(0);
    pause();
    write('play-toggle', '暂停');
    $('play-toggle').setAttribute('aria-pressed', 'true');
    // Canvas frames switch immediately, including under prefers-reduced-motion.
    state.timer = window.setInterval(() => {
      if (state.frameIndex >= frames().length - 1) { pause(); return; }
      setFrame(state.frameIndex + 1);
      if (state.frameIndex >= frames().length - 1) pause();
    }, 650 / Number($('play-speed').value));
  }

  function observationCognition() {
    const timeline = array(currentLevel().cognition_timeline);
    return timeline.filter((entry) => entry.scope === 'observation').map((entry) => ({ entry, index: frames().findIndex((frame) => frame.id === entry.frame_id) }))
      .filter(({ index }) => index >= 0 && index <= state.frameIndex)
      .sort((a, b) => a.index - b.index || number(a.entry.event_sequence) - number(b.entry.event_sequence)).pop()?.entry || null;
  }

  function renderWorld() {
    const timeline = array(currentLevel().cognition_timeline);
    const cognition = timeline.length ? observationCognition() || {} : object(currentLevel().cognition);
    const guide = $('world-guide');
    const facts = $('world-facts');
    guide.replaceChildren(); facts.replaceChildren();
    if (!['final', 'observation'].includes(cognition.scope)) {
      write('cognition-scope', run.status === 'manual' ? '人工试玩不生成 P7 认知。' : '当前关卡没有身份匹配的稳定认知。');
      guide.append(node('p', run.status === 'manual' ? '人工试玩不生成 P7 认知与决策。启动 P7 后会开始新的观察与探索。' : '尚未确定。没有认知记录可供展示。', 'guide-empty'));
      return;
    }
    write('cognition-scope', cognition.scope === 'observation' ? `观察来源 ${string(cognition.frame_id)} · 动作序号 ${number(cognition.source_action_sequence)} · 认知版本 ${number(cognition.cognition_revision)}。当前帧仅使用已关联观察的认知。` : '运行结束时的最终认知快照。未与历史帧或动作建立时间对齐，不能视为该帧当时已有的知识。');
    const world = object(cognition.world_map_facts);
    const confirmed = object(world.confirmed);
    const factLabels = { entities: '对象', mechanics: '机制', relations: '关系' };
    Object.entries(factLabels).forEach(([key, label]) => {
      if (Number.isFinite(confirmed[key])) facts.append(node('span', `${label} ${confirmed[key]}`));
    });
    if (Number.isFinite(world.hypotheses)) facts.append(node('span', `假说 ${world.hypotheses}`));
    if (Number.isFinite(world.conflicts)) facts.append(node('span', `冲突 ${world.conflicts}`));
    const description = string(cognition.stable_description, '');
    const groups = new Map();
    const headings = ['游戏类型', '画面物件', '动作操作', '游戏规则', '过关条件', '当前玩法', '规划推断'];
    let active = null;
    description.split('\n').forEach((line) => {
      const match = line.match(/^([^：:]+)[：:](.*)$/);
      if (match && headings.includes(match[1])) {
        active = match[1]; groups.set(active, match[2].trim());
      } else if (active && line.trim()) groups.set(active, `${groups.get(active)}\n${line.trim()}`);
    });
    if (groups.size) {
      headings.forEach((heading) => {
        if (heading === '规划推断' && !groups.has(heading)) return;
        const section = node('section', undefined, 'guide-section');
        section.append(node('h3', heading), node('p', groups.get(heading) || '尚未确定。'));
        guide.append(section);
      });
    } else guide.append(node('p', description || '没有可用的稳定游戏认知。', 'guide-empty'));
    const update = node('section', undefined, 'guide-section');
    update.append(node('h3', '最近一次稳定更新'), node('p', cognition.scope === 'observation' ? string(cognition.cognition_narrative_zh, '该观察未记录更新说明。') : '最终快照；具体更新时间未与回放帧对齐。'));
    guide.append(update);
  }

  function emptyPanel(panel, title, detail) {
    const empty = node('div', undefined, 'empty-process');
    empty.append(node('h3', title), node('p', detail)); panel.append(empty);
  }

  function addMetadata(card, entries) {
    const meta = node('div', undefined, 'event-meta');
    entries.filter((entry) => entry).forEach((entry) => meta.append(node('span', entry)));
    card.append(meta);
  }

  function renderActionEvidence(target, action) {
    const before = frameById(action.before_frame), after = frameById(action.after_frame);
    const observations = array(action.visual_observations).filter((entry) => typeof entry === 'string' && entry);
    if (before && after && observations.length) {
      target.append(node('p', '画面对比（自动测量）', 'signal-heading'));
      target.append(node('p', `${before.id} → ${after.id} · 起始帧到结算帧`, 'measurement-source'));
      observations.forEach((observation) => target.append(node('p', observation, 'signal-line')));
    }
    if (run.status === 'manual') return;
    const updates = array(currentLevel().cognition_timeline).filter((entry) => entry.scope === 'observation' && entry.action_id === action.id && entry.frame_id === action.after_frame);
    if (updates.length) updates.forEach((entry) => target.append(node('p', `P7 认知更新（${string(entry.frame_id)}）：${string(entry.cognition_narrative_zh, '未记录更新说明。')}`, 'cognition-narrative')));
    else target.append(node('p', 'P7 认知结论：该动作未保存可关联的分析记录。', 'cognition-missing'));
  }

  function signalLines(signals, target) {
    if (Array.isArray(signals)) {
      signals.forEach((signal) => { if (typeof signal === 'string') target.append(node('p', signalNames[signal] || signal, 'signal-line')); });
    } else Object.entries(object(signals)).forEach(([key, value]) => {
      if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') target.append(node('p', `${signalNames[key] || key}：${scalarText(value)}`, 'signal-line'));
    });
    if (!target.childElementCount) target.append(node('p', '没有记录该侧信号。', 'signal-line'));
  }

  function renderProcess() {
    const level = currentLevel();
    const decisionsPanel = $('panel-decisions');
    const actionsPanel = $('panel-actions');
    const cognitionPanel = $('panel-cognition');
    [decisionsPanel, actionsPanel, cognitionPanel].forEach((panel) => panel.replaceChildren());
    const ownDecisions = array(level.decisions);
    const decisionMap = new Map(ownDecisions.map((decision) => [decision.id, decision]));
    array(snapshot.decisions).forEach((decision) => { if (!decisionMap.has(decision.id)) decisionMap.set(decision.id, decision); });
    const decisions = [...decisionMap.values()];
    const updates = array(object(level.cognition).updates);
    const timeline = array(level.cognition_timeline).filter((entry) => entry.scope === 'observation');
    const meaningRecords = Object.entries(actionMeanings()).map(([name, entries]) => [name, meaningEntries(entries)]).filter(([, entries]) => entries.length);
    write('decision-count', decisions.length);
    write('actions-count', actions().length);
    write('cognition-count', updates.length + meaningRecords.length + timeline.length);
    decisionsPanel.append(node('p', '应用保存的 P7 决策显示目标、依据、预期和关联实际结果。旧轮次仅显示原始信号；未记录的解释不补写。', 'process-note'));
    if (!decisions.length) emptyPanel(decisionsPanel, '没有可审计的 P7 决策信号', '动作记录本身不能证明某一轮次的规划内容。');
    decisions.forEach((decision, index) => {
      const card = node('article', undefined, 'event-card');
      card.dataset.decisionId = string(decision.id, '');
      const header = node('div', undefined, 'event-header');
      const heading = node('div', undefined, 'event-heading');
      heading.append(node('span', String(index + 1).padStart(2, '0'), 'event-index'), node('h3', decision.source === 'p7_decision' ? `P7 决策 ${index + 1}` : `P7 第 ${number(decision.round_index, index + 1)} 轮`), node('span', decision.source === 'p7_decision' ? '应用决策' : '决策信号', 'neutral-tag'));
      header.append(heading);
      const linked = actions().filter((action) => array(decision.action_ids).includes(action.id));
      if (linked.length) {
        const button = node('button', '定位动作', 'event-link'); button.type = 'button';
        button.addEventListener('click', () => locateAction(linked[0])); header.append(button);
      }
      card.append(header);
      addMetadata(card, [decision.trace_sequence != null ? `轨迹序号 ${decision.trace_sequence}` : '轨迹序号缺失', `关联动作 ${linked.length}`]);
      if (!linked.length) card.append(node('p', '全运行信号：未建立可靠的关卡、帧或动作关联。该轮次不代表当前画面的决策。', 'event-note'));
      if (decision.source === 'p7_decision') {
        const summary = node('div', undefined, 'decision-summary');
        [['目标', decision.goal], ['依据', decision.basis], ['预期', decision.expected]].forEach(([label, value]) => summary.append(node('p', `${label}：${string(value, '未记录')}`)));
        linked.forEach((action) => {
          const before = frameById(action.before_frame), after = frameById(action.after_frame);
          summary.append(node('p', `实际结果：${actionLabel(action)} · ${before ? before.id : '前帧缺失'} → ${after ? after.id : '后帧缺失'} · ${after ? frameState(after.state) : '状态未记录'}`));
          array(action.visual_observations).filter((entry) => typeof entry === 'string').forEach((entry) => summary.append(node('p', entry)));
        });
        if (!linked.length) summary.append(node('p', '实际结果：没有可关联的动作结果。'));
        card.append(summary); decisionsPanel.append(card); return;
      }
      const signals = node('div', undefined, 'signals');
      [['输入信号', decision.prompt_signals], ['输出信号', decision.output_signals]].forEach(([label, source]) => {
        const column = node('div'); column.append(node('p', label, 'signal-heading'));
        const body = node('div'); signalLines(source, body); column.append(body); signals.append(column);
      });
      card.append(signals); decisionsPanel.append(card);
    });
    if (!actions().length) emptyPanel(actionsPanel, '当前关卡没有动作记录', '这里仅展示录制动作，不执行新的游戏动作。');
    else actionsPanel.append(node('p', '点击“定位画面”查看动作结算帧。变化格来自画面比较；画面未变化不能单独证明受阻或动作无效。', 'process-note'));
    actions().forEach((action, index) => {
      const card = node('article', undefined, 'event-card');
      card.dataset.actionId = string(action.id, '');
      const header = node('div', undefined, 'event-header');
      const heading = node('div', undefined, 'event-heading');
      heading.append(node('span', String(index + 1).padStart(2, '0'), 'event-index'), node('h3', actionLabel(action)));
      header.append(heading);
      const button = node('button', '定位画面', 'event-link'); button.type = 'button';
      button.disabled = !frameById(action.before_frame) && !frameById(action.after_frame);
      button.addEventListener('click', () => locateAction(action)); header.append(button); card.append(header);
      const before = frameById(action.before_frame), after = frameById(action.after_frame);
      const changed = Number.isFinite(action.changed_cells) ? action.changed_cells : array(action.changed_cells).length;
      addMetadata(card, [`动作前 ${before ? before.id : '记录缺失'}`, `动作后 ${after ? after.id : '记录缺失'}`, `变化 ${changed} 格${changed === 0 ? ' · 画面未变化' : ''}`, before && after ? `已完成关卡 ${number(before.levels_completed)} → ${number(after.levels_completed)}` : '关卡变化无法核对', after && after.state === 'WIN' ? '结算状态 WIN' : null]);
      addMetadata(card, [action.trace_sequence != null ? `轨迹序号 ${action.trace_sequence}` : '轨迹关联缺失', action.decision_id ? `P7 关联 ${action.decision_id}` : 'P7 轮次关联缺失']);
      if (!before || !after) card.append(node('p', '动作前后帧不完整，无法建立完整的结果对照。', 'event-note'));
      const evidence = node('div', undefined, 'action-evidence');
      renderActionEvidence(evidence, action); card.append(evidence);
      actionsPanel.append(card);
    });
    timeline.forEach((entry) => {
      const card = node('article', undefined, 'event-card timeline-cognition');
      card.append(node('h3', `观察认知 · 版本 ${number(entry.cognition_revision)}`));
      addMetadata(card, [`来源帧 ${string(entry.frame_id)}`, `动作序号 ${number(entry.source_action_sequence)}`, entry.action_id ? `关联动作 ${entry.action_id}` : '初始观察']);
      const button = node('button', '定位观察', 'event-link'); button.type = 'button';
      const index = frames().findIndex((frame) => frame.id === entry.frame_id); button.disabled = index < 0;
      button.addEventListener('click', () => { pause(); setFrame(index, entry.action_id); });
      card.append(button, node('p', string(entry.cognition_narrative_zh, '没有更新说明。'), 'cognition-narrative'));
      const details = node('details'); details.append(node('summary', '查看该观察的稳定认知'), node('p', string(entry.stable_description, '没有稳定描述。'), 'cognition-narrative'));
      card.append(details); cognitionPanel.append(card);
    });
    cognitionPanel.append(node('p', '以下旧认知事件是最终会话的记录，未与回放帧、动作或模型轮次建立时间关联。展开后可查看保留的认知条目。', 'process-note'));
    if (meaningRecords.length) cognitionPanel.append(node('p', '动作含义来自最终认知，未与历史帧对齐。按键上的简短含义只采用明确的方向记录；完整原始记录保留如下。', 'process-note'));
    const meaningStatuses = { certain: '已识别', undetermined: '推测', falsified: '已否定' };
    meaningRecords.forEach(([name, entries]) => {
      const card = node('article', undefined, 'event-card');
      card.dataset.meaningAction = name;
      const heading = node('div', undefined, 'event-heading');
      heading.append(node('h3', name), node('span', '最终动作认知', 'neutral-tag'));
      card.append(heading);
      const details = node('details');
      details.append(node('summary', `认知依据（${entries.length}）`));
      const list = node('ul', undefined, 'claim-list');
      entries.forEach((entry) => {
        const row = node('li');
        row.append(node('span', meaningStatuses[entry.status], 'claim-label'), node('p', entry.claim));
        list.append(row);
      });
      details.append(list); card.append(details); cognitionPanel.append(card);
    });
    if (!timeline.length && !updates.length && !meaningRecords.length) emptyPanel(cognitionPanel, '没有可展示的认知更新事件', '没有事件证据时，不从最终快照倒推历史认知。');
    const types = { 'cognition.hypothesis.confirmed': '确认事实', 'cognition.hypothesis.falsified': '否定事实', 'cognition.hypothesis.remains_undetermined': '保留未决假说' };
    const claimStatuses = { certain: '已确认', falsified: '已否定', undetermined: '未决假说', superseded: '已替代' };
    const claimKinds = { game_type: '游戏类型', object_role: '物件角色', control: '动作操作', rule: '游戏规则', success_condition: '过关条件', strategy: '规划策略' };
    updates.forEach((update) => {
      const card = node('article', undefined, 'event-card');
      const header = node('div', undefined, 'event-heading');
      header.append(node('span', `#${number(update.sequence)}`, 'event-index'), node('h3', types[update.type] || '认知更新'));
      card.append(header);
      const changes = array(update.changes);
      addMetadata(card, [`${changes.length} 个认知条目`, '历史时间对齐：未建立']);
      const details = node('details'); details.append(node('summary', '查看完整认知条目'));
      const list = node('ul', undefined, 'claim-list');
      changes.forEach((change) => {
        const item = node('li');
        item.append(node('span', `${claimStatuses[change.status] || '状态未记录'} · ${claimKinds[change.kind] || '认知条目'} · ${string(change.id)}`, 'claim-label'), node('p', string(change.claim, '条目内容缺失')));
        list.append(item);
      });
      if (!changes.length) list.append(node('li', '该事件没有可核对的条目内容。'));
      details.append(list); card.append(details); cognitionPanel.append(card);
    });
  }

  function renderReceipt() {
    const target = $('receipt-content'); target.replaceChildren();
    const receipt = currentLevel().receipt;
    if (!receipt) { target.append(node('span', '未发现该关卡的完整权威回执。录制画面不替代最终成功证明。')); return; }
    const labels = { completed_level_count: '已完成关卡', primitive_action_count: '原子动作', partial_game_score: '局部分数', scope: '回执范围', promotion: '证明边界' };
    Object.entries(labels).forEach(([key, label]) => {
      if (receipt[key] != null) target.append(node('span', `${label}：${scalarText(receipt[key])}`));
    });
    if (!target.childElementCount) target.append(node('span', '回执缺少可展示的字段。'));
  }

  function selectTab(name, focus = false) {
    state.tab = name;
    ['decisions', 'actions', 'cognition'].forEach((tab) => {
      const active = tab === name;
      $(`tab-${tab}`).setAttribute('aria-selected', String(active));
      $(`tab-${tab}`).tabIndex = active ? 0 : -1;
      $(`panel-${tab}`).hidden = !active;
    });
    if (focus) $(`tab-${name}`).focus();
  }
  ['decisions', 'actions', 'cognition'].forEach((name, index, names) => {
    $(`tab-${name}`).addEventListener('click', () => selectTab(name));
    $(`tab-${name}`).addEventListener('keydown', (event) => {
      let target = null;
      if (event.key === 'ArrowRight') target = names[(index + 1) % names.length];
      if (event.key === 'ArrowLeft') target = names[(index + names.length - 1) % names.length];
      if (event.key === 'Home') target = names[0];
      if (event.key === 'End') target = names[names.length - 1];
      if (target) { event.preventDefault(); event.stopPropagation(); selectTab(target, true); }
    });
  });
  $('frame-slider').addEventListener('input', () => { pause(); setFrame(Number($('frame-slider').value)); });
  $('previous-frame').addEventListener('click', () => { pause(); setFrame(state.frameIndex - 1); });
  $('next-frame').addEventListener('click', () => { pause(); setFrame(state.frameIndex + 1); });
  $('play-toggle').addEventListener('click', () => state.timer === null ? play() : pause());
  $('play-speed').addEventListener('change', () => { if (state.timer !== null) play(); });
  ['diff-toggle', 'highlight-toggle', 'compare-toggle'].forEach((id) => $(id).addEventListener('change', renderFrame));
  [-1, 1].forEach((direction) => $(direction < 0 ? 'previous-action' : 'next-action').addEventListener('click', () => {
    const target = actionTarget(direction); if (target) locateAction(target.action);
  }));
  document.addEventListener('keydown', (event) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.target.closest('input, select, textarea, button, a, summary, [contenteditable]')) return;
    if (state.mode === 'manual') {
      if (!event.repeat && event.target.closest('#board-section') && /^[1-7]$/.test(event.key)) {
        const button = $('available-actions').querySelector(`[data-available-action="ACTION${event.key}"]`);
        if (button && !button.disabled) { event.preventDefault(); button.click(); }
      }
      return;
    }
    if (state.mode !== 'replay') return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault(); pause(); setFrame(state.frameIndex + (event.key === 'ArrowRight' ? 1 : -1));
    } else if (event.code === 'Space' && !event.repeat) { event.preventDefault(); state.timer === null ? play() : pause(); }
  });
  $('board-canvas').addEventListener('click', (event) => {
    if (state.mode === 'manual') $('board-section').focus();
    if (!manualPlayable() || state.pointerAction !== 'ACTION6' || !array(currentFrame().available_actions).includes('ACTION6')) return;
    const bounds = $('board-canvas').getBoundingClientRect(), grid = currentFrame().grid;
    if (!bounds.width || !bounds.height || !grid.length || !grid[0].length) return;
    const x = Math.floor((event.clientX - bounds.left) * grid[0].length / bounds.width);
    const y = Math.floor((event.clientY - bounds.top) * grid.length / bounds.height);
    if (x < 0 || y < 0 || x >= grid[0].length || y >= grid.length) return;
    sendManualAction('ACTION6', { x, y });
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); });
  window.addEventListener('pagehide', pause);
  function replaceSnapshot(next, { follow = state.mode === 'live' } = {}) {
    if (!validSnapshot(next)) throw new Error('invalid-response');
    const previous = { snapshot, run, recordedLevels, levelCount, levels,
      levelIndex: state.levelIndex, frameIndex: state.frameIndex, actionId: state.actionId };
    const previousRun = run.run_id, previousLevel = currentLevel().level, previousFrame = currentFrame()?.id, previousAction = state.actionId;
    // Derive the complete next view before changing the currently accepted state.
    const nextRun = object(next.run), nextRecordedLevels = array(next.levels);
    const nextCount = Math.max(0, number(nextRun.win_levels), ...nextRecordedLevels.map((level) => number(level.level)));
    const nextLevels = Array.from({ length: nextCount }, (_, index) => nextRecordedLevels.find((level) => level.level === index + 1) || {
      level: index + 1, status: 'not_run', frames: [], actions: [], decisions: [], cognition: { scope: 'unavailable' }, receipt: null,
    });
    let index = nextLevels.findIndex((level) => level.level === previousLevel);
    if (follow) index = nextLevels.map((level, i) => array(level.frames).length ? i : -1).filter((i) => i >= 0).pop() ?? 0;
    else if (previousRun !== nextRun.run_id || index < 0) index = Math.max(0, nextLevels.findIndex((level) => array(level.frames).length));
    const preserve = !follow && previousRun === nextRun.run_id;
    try {
      snapshot = next; run = nextRun; recordedLevels = nextRecordedLevels; levelCount = nextCount; levels = nextLevels;
      renderRunHeader(); selectLevel(index);
      const historical = preserve ? frames().findIndex((frame) => frame.id === previousFrame) : -1;
      setFrame(follow ? frames().length - 1 : historical >= 0 ? historical : 0,
        preserve && actions().some((action) => action.id === previousAction) ? previousAction : undefined);
    } catch (_) {
      snapshot = previous.snapshot; run = previous.run; recordedLevels = previous.recordedLevels;
      levelCount = previous.levelCount; levels = previous.levels;
      state.levelIndex = previous.levelIndex; state.frameIndex = previous.frameIndex; state.actionId = previous.actionId;
      // Restore the old rendered frame if the failing canvas/DOM operation was transient.
      try {
        renderRunHeader(); selectLevel(previous.levelIndex); setFrame(previous.frameIndex, previous.actionId);
      } catch (_) { /* Persistent rendering failure must not commit data or revision. */ }
      state.levelIndex = previous.levelIndex; state.frameIndex = previous.frameIndex; state.actionId = previous.actionId;
      throw new Error('invalid-response');
    }
    window.__ASTERION_STATE__ = snapshot;
  }

  const sessionLabels = { idle: '就绪 · 尚未启动', starting: '启动中', running: 'P7 运行中', stopping: '结束中 · 等待清理确认', completed: '运行完成 · 有完成证据', incomplete: '运行未完成', cancelled: '运行已结束', 'timed-out': '运行超时', failed: '运行失败', 'cleanup-unconfirmed': '清理未确认 · 无法启动新运行' };
  const activeSession = () => ['starting', 'running', 'stopping', 'cleanup-unconfirmed'].includes(state.liveView?.state);
  const manualSelectionLocked = () => !liveConfig || !state.liveView || activeSession() || state.manualBusy || Boolean(state.manualPending) || state.commandBusy || Boolean(state.pendingCommand);
  function validChoice(choice) {
    if (!isRecord(choice) || typeof choice.game_id !== 'string' || !Number.isInteger(choice.level)) return false;
    const game = array(liveConfig?.games).find((entry) => entry.game_id === choice.game_id);
    return Boolean(game && choice.level >= 1 && choice.level <= game.win_levels);
  }
  function manualLevel(view) {
    return view?.level ?? array(view?.snapshot?.levels).find((level) => array(level.frames).length)?.level ?? null;
  }
  function rememberedManualLevel() {
    return validChoice(state.manualChoice) && state.manualChoice.game_id === $('game-select').value ? state.manualChoice.level : 1;
  }
  function renderSessionControls() {
    const live = state.mode === 'live', manual = state.mode === 'manual';
    $('console-mode').value = state.mode;
    $('console-mode').disabled = !liveConfig || Boolean(state.manualPending && state.manualPending.path === '/api/manual/action');
    $('live-controls').hidden = !liveConfig || (!live && !manual);
    $('replay-controls').hidden = !liveConfig || state.mode !== 'replay';
    $('replay-transport').hidden = state.mode !== 'replay';
    $('header-mode').textContent = liveConfig ? (manual ? '人工试玩' : live ? 'P7 实时运行' : '回放记录') : '离线回放';
    write('actions-mode', manual ? '人工试玩动作' : live ? '运行观察' : '只读回放');
    write('actions-note', manual ? state.pointerAction === 'ACTION6' ? '点击画面目标格执行 ACTION6' : '执行可用动作；按键含义尚未识别' : live ? '动作由 P7 执行，此处只观察' : '点击定位已录动作');
    write('manual-note', liveConfig ? manual ? '点击左侧关卡可直接试玩任意关卡；直接选择不代表已过关。启动 P7 会从第 1 关开始全新运行。画面获得焦点时可按 1–7 选择 ACTION 按键。' : '人工试玩独立于 P7；P7 运行时动作面板仅展示观察。' : '离线回放不执行游戏动作。');
    document.querySelectorAll('.level-button').forEach((button) => { button.disabled = manual && manualSelectionLocked(); });
    $('run-start').disabled = !liveConfig || !state.liveView || activeSession() || state.manualBusy || Boolean(state.manualPending) || state.commandBusy || Boolean(state.pendingCommand) || !$('game-select').value;
    $('game-select').disabled = !state.liveView || activeSession() || state.manualBusy || Boolean(state.manualPending) || state.commandBusy || Boolean(state.pendingCommand);
    $('run-stop').disabled = !state.liveView?.session_id || !['starting', 'running'].includes(state.liveView?.state) || state.commandBusy || Boolean(state.pendingCommand);
    $('manual-close').hidden = !manual;
    $('manual-close').textContent = state.manualView?.state === 'ready' && !state.manualError ? '结束试玩' : '重新打开试玩';
    $('manual-close').disabled = !liveConfig || !state.liveView || activeSession() || state.manualBusy || Boolean(state.manualPending) || state.commandBusy || Boolean(state.pendingCommand) || !$('game-select').value;
    $('retry-command').hidden = (!state.pendingCommand && !state.manualPending) || state.commandBusy || state.manualBusy;
    $('replay-load').disabled = !$('replay-run').value;
    write('session-id', manual && state.manualView?.session_id ? `试玩 ${state.manualView.session_id}` : state.liveView?.session_id ? `会话 ${state.liveView.session_id}` : '');
  }

  function validView(view) {
    if (!isRecord(view) || !Object.hasOwn(sessionLabels, view.state) || !Number.isInteger(view.revision) || view.revision < 0 || typeof view.cleanup_confirmed !== 'boolean') return false;
    if (!['session_id', 'game_id', 'run_id'].every((key) => view[key] === null || (typeof view[key] === 'string' && view[key].length > 0))) return false;
    if (view.snapshot !== null && !validSnapshot(view.snapshot)) return false;
    if (view.snapshot !== null && (view.snapshot.run.run_id !== view.run_id || view.snapshot.run.game_id !== view.game_id)) return false;
    if (view.manual != null && !validManual(view.manual)) return false;
    return true;
  }

  function snapshotForView(view) {
    if (view.snapshot) return view.snapshot;
    const game = array(liveConfig?.games).find((entry) => entry.game_id === view.game_id);
    return { schema: 'asterion.arc-agi3-p7-console/v1', generated_at: null,
      run: { run_id: view.run_id, game_id: view.game_id, status: view.state, win_levels: game?.win_levels ?? null,
        completed_level_count: 0, primitive_action_count: 0, replay_verified: false, sealed_trace: false },
      levels: [], decisions: [], warnings: [] };
  }

  function acceptView(view, { manualProjection = true } = {}) {
    if (!validView(view)) throw new Error('invalid-response');
    const previous = state.liveView;
    if (previous && view.revision < previous.revision) return;
    const active = ['starting', 'running', 'stopping', 'cleanup-unconfirmed'].includes(view.state);
    const displayingManual = run.status === 'manual';
    const preserveManual = displayingManual && !active && ((view.state === 'idle' && view.run_id === null && !view.snapshot) || (previous && previous.revision === view.revision && previous.session_id === view.session_id));
    if (active) {
      invalidateManual(); state.manualView = null; state.manualPending = null;
      if (state.mode === 'manual') state.mode = 'live';
      if (array(liveConfig?.games).some((game) => game.game_id === view.game_id)) $('game-select').value = view.game_id;
    }
    if (!preserveManual && !view.snapshot && state.mode === 'live' && (run.run_id !== view.run_id || run.game_id !== view.game_id || (previous && previous.session_id !== view.session_id))) replaceSnapshot(snapshotForView(view));
    if (view.snapshot && (state.mode === 'live' || (!state.replayRun && run.run_id === view.run_id)) &&
        !preserveManual && (!previous || previous.revision !== view.revision || previous.run_id !== view.run_id || displayingManual)) replaceSnapshot(view.snapshot);
    // Publish the accepted session/revision only after snapshot replacement rendered successfully.
    state.liveView = view;
    if (manualProjection && !active && view.manual && state.mode === 'manual' && !state.manualBusy && !state.manualPending && view.manual.game_id === $('game-select').value) acceptManual(view.manual);
    write('service-status', `${sessionLabels[view.state]}${view.cleanup_confirmed ? ' · 清理已确认' : ''}`);
    if (state.mode === 'manual') renderManualStatus();
    renderSessionControls();
  }

  async function request(path, command = null) {
    // Fixed relative routes and the injected same-origin token are the only request authority.
    let result;
    try {
      result = await window.fetch(path, {
        method: command ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
        headers: { 'X-P7-Console-Token': liveConfig.token, ...(command ? { 'Content-Type': 'application/json' } : {}) },
        ...(command ? { body: JSON.stringify(command) } : {}),
      });
    } catch (_) { throw new Error('disconnected'); }
    if (!result.ok) throw new Error('request-rejected');
    try { return await result.json(); } catch (_) { throw new Error('invalid-response'); }
  }

  function showRequestError(error) {
    const labels = { disconnected: '连接中断 · 保留最近画面', 'invalid-response': '服务响应无效 · 保留最近画面', 'request-rejected': '服务拒绝请求 · 保留最近画面' };
    write('service-status', labels[error.message] || labels['invalid-response']);
    renderSessionControls();
  }

  function invalidateManual() {
    state.manualGeneration += 1;
    state.manualPollGeneration += 1;
    state.manualBusy = false;
    state.manualError = false;
    state.pointerAction = null;
  }

  async function openManual(level = 1) {
    if (state.mode === 'replay' || manualSelectionLocked()) return;
    const gameId = $('game-select').value;
    const game = array(liveConfig.games).find((entry) => entry.game_id === gameId);
    if (!game || !validChoice({ game_id: gameId, level })) return;
    state.manualChoice = { game_id: gameId, level };
    invalidateManual(); state.manualView = null; state.mode = 'manual';
    replaceSnapshot({ schema: 'asterion.arc-agi3-p7-console/v1', generated_at: null,
      run: { run_id: null, game_id: gameId, status: 'manual', win_levels: game.win_levels ?? null, completed_level_count: 0, primitive_action_count: 0 },
      levels: [], decisions: [], warnings: [] });
    selectLevel(level - 1);
    await sendManualCommand({ path: '/api/manual/open', body: { game_id: gameId, level, command_id: window.crypto.randomUUID() } });
  }

  const manualLabels = { idle: '尚未打开人工试玩', ready: '人工试玩 · 可操作', closed: '人工试玩已结束', expired: '人工试玩已过期', uncertain: '人工试玩结果未确认 · 已停止操作' };
  function validManual(view) {
    if (!isRecord(view) || !Object.hasOwn(manualLabels, view.state) || !['session_id', 'game_id'].every((key) => view[key] === null || typeof view[key] === 'string')) return false;
    if (!['observation_version', 'episode_id', 'action_count'].every((key) => Number.isInteger(view[key]) && view[key] >= 0)) return false;
    if (view.snapshot !== null && (!validSnapshot(view.snapshot) || view.snapshot.run.run_id !== null || view.snapshot.run.game_id !== view.game_id || view.snapshot.run.status !== 'manual')) return false;
    if (view.state === 'ready' && (!view.session_id || !view.game_id || !view.snapshot)) return false;
    if (view.level != null && !validChoice({ game_id: view.game_id, level: view.level })) return false;
    if (view.state === 'ready' && (!validChoice({ game_id: view.game_id, level: manualLevel(view) }) || !array(view.snapshot.levels).some((level) => level.level === manualLevel(view) && array(level.frames).length))) return false;
    if (view.last_action != null && (!isRecord(view.last_action) || typeof view.last_action.action !== 'string' || !isRecord(view.last_action.data))) return false;
    return true;
  }

  function renderManualStatus() {
    write('service-status', state.manualBusy ? '正在处理人工试玩操作' : state.manualPending ? '试玩请求结果未确认 · 请重试原请求' : state.manualError ? '人工试玩操作未确认 · 请重新打开试玩' : `${manualLabels[state.manualView?.state] || '正在打开人工试玩'}${manualLevel(state.manualView) ? ` · 关卡 ${manualLevel(state.manualView)}` : ''}`);
  }

  function acceptManual(view) {
    if (!validManual(view)) throw new Error('invalid-response');
    if (state.manualView?.session_id === view.session_id && state.manualView.observation_version > view.observation_version) return;
    const previous = state.manualView;
    state.manualView = view;
    try {
      if (view.snapshot && (run.status !== 'manual' || previous?.session_id !== view.session_id || previous?.observation_version !== view.observation_version || previous?.state !== view.state || manualLevel(previous) !== manualLevel(view))) replaceSnapshot(view.snapshot, { follow: true });
      else renderFrame();
    } catch (error) { state.manualView = previous; throw error; }
    const choice = { game_id: view.game_id, level: manualLevel(view) };
    if (validChoice(choice)) state.manualChoice = choice;
    renderManualStatus(); renderSessionControls();
  }

  async function sendManualCommand(command) {
    if (!liveConfig || state.manualBusy || state.commandBusy || state.pendingCommand || activeSession()) return;
    const generation = state.manualGeneration;
    state.manualPollGeneration += 1;
    const isCurrent = () => generation === state.manualGeneration && state.mode === 'manual' && !activeSession();
    state.manualBusy = true; state.manualPending = command; state.manualError = false;
    renderFrame(); renderSessionControls(); renderManualStatus();
    try {
      const view = await request(command.path, command.body);
      if (!isCurrent()) return;
      if (!validManual(view) || (command.path === '/api/manual/open' ? view.game_id !== command.body.game_id || manualLevel(view) !== command.body.level : view.session_id !== command.body.session_id)) throw new Error('invalid-response');
      acceptManual(view); state.manualPending = null; state.pointerAction = null;
      state.manualPollGeneration += 1;
    } catch (error) {
      if (!isCurrent()) return;
      if (error.message === 'request-rejected') { state.manualPending = null; state.manualError = true; }
      showRequestError(error);
    } finally {
      if (isCurrent()) { state.manualBusy = false; renderFrame(); renderSessionControls(); renderManualStatus(); }
    }
  }

  function sendManualAction(action, data = {}) {
    if (!manualPlayable() || !array(currentFrame().available_actions).includes(action)) return;
    sendManualCommand({ path: '/api/manual/action', body: { session_id: state.manualView.session_id,
      command_id: window.crypto.randomUUID(), observation_version: state.manualView.observation_version, action, data } });
  }

  async function pollState() {
    if (!liveConfig || state.pollBusy || state.commandBusy) return;
    state.pollBusy = true;
    const manualGeneration = state.manualPollGeneration;
    try { acceptView(await request('/api/state'), { manualProjection: manualGeneration === state.manualPollGeneration }); } catch (error) { showRequestError(error); }
    finally { state.pollBusy = false; }
  }

  async function sendCommand(command) {
    if (!liveConfig || state.commandBusy) return;
    invalidateManual();
    state.commandBusy = true; state.pendingCommand = command; renderSessionControls();
    try {
      acceptView(await request(command.path, command.body));
      state.pendingCommand = null;
    } catch (error) {
      // An unknown transport outcome can be retried only with the original command identity.
      if (error.message === 'request-rejected') state.pendingCommand = null;
      showRequestError(error);
    } finally { state.commandBusy = false; renderSessionControls(); }
  }

  async function loadRuns() {
    try {
      const result = await request('/api/runs');
      if (!isRecord(result) || !Array.isArray(result.runs) || !result.runs.every((run) => isRecord(run) && typeof run.run_id === 'string' && /^[A-Za-z0-9_-]+$/.test(run.run_id) && typeof run.game_id === 'string')) throw new Error('invalid-response');
      const select = $('replay-run'); select.replaceChildren();
      result.runs.forEach((run) => { const option = node('option', `${run.game_id} · ${run.run_id}`); option.value = run.run_id; select.append(option); });
      renderSessionControls();
    } catch (error) { showRequestError(error); }
  }

  async function initializeSelection() {
    const generation = state.manualGeneration;
    await pollState();
    if (!state.liveView || activeSession() || state.mode !== 'live' || generation !== state.manualGeneration) return;
    const manual = state.liveView.manual;
    if (manual?.state === 'ready' && array(liveConfig.games).some((game) => game.game_id === manual.game_id)) {
      $('game-select').value = manual.game_id;
      state.mode = 'manual'; acceptManual(manual);
    } else {
      if (validChoice(state.liveView.selection)) {
        state.manualChoice = { game_id: state.liveView.selection.game_id, level: state.liveView.selection.level };
        $('game-select').value = state.manualChoice.game_id;
      }
      openManual(rememberedManualLevel());
    }
  }

  function initializeLive() {
    $('console-mode').disabled = !liveConfig;
    renderRunHeader(); selectLevel(state.levelIndex); renderSessionControls();
    $('console-mode').addEventListener('change', () => {
      if (state.manualPending?.path === '/api/manual/action') { renderSessionControls(); return; }
      pause(); invalidateManual(); state.manualPending = null; state.mode = $('console-mode').value; state.replayRun = null; state.replayGeneration += 1;
      if (state.mode === 'manual' && activeSession()) { state.mode = 'live'; write('service-status', 'P7 运行期间无法打开人工试玩'); }
      if (state.mode === 'live' && state.liveView) replaceSnapshot(snapshotForView(state.liveView), { follow: true });
      else if (state.mode === 'manual' && state.manualView?.state === 'ready') { $('game-select').value = state.manualView.game_id; replaceSnapshot(state.manualView.snapshot, { follow: true }); renderManualStatus(); }
      else if (state.mode === 'manual') openManual(rememberedManualLevel());
      else renderFrame();
      renderSessionControls();
    });
    if (!liveConfig) return;
    const games = array(liveConfig.games);
    games.filter((game) => isRecord(game) && typeof game.game_id === 'string').forEach((game) => {
      const option = node('option', `${string(game.alias, game.game_id)} · ${game.game_id}`); option.value = game.game_id; $('game-select').append(option);
    });
    $('game-select').addEventListener('change', () => openManual(1));
    $('run-start').addEventListener('click', () => {
      state.mode = 'live'; state.manualView = null;
      sendCommand({ path: '/api/start', body: { game_id: $('game-select').value, command_id: window.crypto.randomUUID() } });
    });
    $('run-stop').addEventListener('click', () => sendCommand({ path: '/api/stop', body: { session_id: state.liveView.session_id, command_id: window.crypto.randomUUID() } }));
    $('retry-command').addEventListener('click', () => { if (state.pendingCommand) sendCommand(state.pendingCommand); else if (state.manualPending) sendManualCommand(state.manualPending); });
    $('manual-close').addEventListener('click', () => {
      if ($('manual-close').disabled) return;
      if (state.manualView?.state === 'ready' && !state.manualError) sendManualCommand({ path: '/api/manual/close', body: { session_id: state.manualView.session_id, command_id: window.crypto.randomUUID() } });
      else openManual(rememberedManualLevel());
    });
    $('replay-run').addEventListener('change', () => { state.replayGeneration += 1; });
    $('replay-load').addEventListener('click', async () => {
      const runId = $('replay-run').value;
      if (!runId || state.mode !== 'replay') return;
      const generation = ++state.replayGeneration;
      const isCurrent = () => state.mode === 'replay' && state.replayGeneration === generation && $('replay-run').value === runId;
      try {
        const replay = await request(`/api/replay/${encodeURIComponent(runId)}`);
        if (!isCurrent()) return;
        if (!validSnapshot(replay) || replay.run.run_id !== runId) throw new Error('invalid-response');
        replaceSnapshot(replay, { follow: false }); state.replayRun = runId;
      } catch (error) { if (isCurrent()) showRequestError(error); }
    });
    write('service-status', '正在连接本地服务');
    initializeSelection().catch(showRequestError); loadRuns();
    state.pollTimer = window.setInterval(pollState, 1000);
    window.addEventListener('pagehide', () => { if (state.pollTimer !== null) window.clearInterval(state.pollTimer); });
  }

  initializeLive();
})();
