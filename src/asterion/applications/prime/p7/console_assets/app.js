(() => {
  'use strict';

  // Official ARC-AGI-3 colors, verified against arc_agi/rendering.py.
  const PALETTE = ['#FFFFFF', '#CCCCCC', '#999999', '#666666', '#333333', '#000000', '#E53AA3', '#FF7BCC', '#F93C31', '#1E93FF', '#88D8F1', '#FFDC00', '#FF851B', '#921231', '#4FCC30', '#A356D6'];
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
  let snapshot;
  try {
    snapshot = JSON.parse($('console-data').textContent);
    if (snapshot.schema !== 'asterion.arc-agi3-p7-console/v1') throw new Error('schema');
  } catch (_) {
    write('evidence-warning', '控制台快照无法读取，或数据版本不受支持。');
    $('evidence-warning').hidden = false;
    document.querySelectorAll('button, input, select').forEach((element) => { element.disabled = true; });
    return;
  }
  window.__ASTERION_STATE__ = snapshot;
  const run = object(snapshot.run);
  const recordedLevels = array(snapshot.levels);
  const levelCount = Math.max(0, number(run.win_levels), ...recordedLevels.map((level) => number(level.level)));
  const levels = Array.from({ length: levelCount }, (_, index) => recordedLevels.find((level) => level.level === index + 1) || {
    level: index + 1, status: 'not_run', frames: [], actions: [], decisions: [], cognition: { scope: 'unavailable' }, receipt: null,
  });
  const state = { levelIndex: Math.max(0, levels.findIndex((level) => array(level.frames).length)), frameIndex: 0, actionId: null, timer: null, tab: 'decisions' };
  const emptyLevel = { level: null, status: 'not-run', frames: [], actions: [], decisions: [], cognition: { scope: 'unavailable' }, receipt: null };
  const currentLevel = () => levels[state.levelIndex] || emptyLevel;
  const frames = () => array(currentLevel().frames);
  const actions = () => array(currentLevel().actions);
  const currentFrame = () => frames()[state.frameIndex];
  const frameById = (id) => frames().find((frame) => frame.id === id);
  const selectedAction = () => actions().find((action) => action.id === state.actionId) || null;
  const statuses = {
    completed: ['已过关', 'success'], successful: ['已成功', 'success'], success: ['已成功', 'success'], won: ['已过关', 'success'],
    running: ['运行中', 'active'], active: ['可继续', 'active'], in_progress: ['进行中', 'active'],
    incomplete: ['未完成', 'warning'], interrupted: ['已中断', 'warning'], waiting: ['等待', 'warning'], unknown: ['信息不足', 'warning'],
    unsuccessful: ['未成功', 'failed'], failed: ['失败', 'failed'], game_over: ['游戏结束', 'failed'],
    'not-run': ['未运行', 'neutral'], not_run: ['未运行', 'neutral'], unobserved: ['未运行', 'neutral'], unavailable: ['无证据', 'neutral'],
  };
  const statusInfo = (value) => statuses[value] || ['信息不足', 'warning'];
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

  write('game-title', string(run.game_id, '未识别游戏'));
  write('run-id', string(run.run_id));
  write('level-progress', `${number(run.completed_level_count)} / ${number(run.win_levels) || '未知'}`);
  write('action-total', number(run.primitive_action_count));
  write('level-total', levelCount ? `${levelCount} 个关卡` : '总数未知');
  setStatus($('run-status'), run.status);
  write('snapshot-date', `快照时间 ${string(snapshot.generated_at)}`);
  write('verification-note', `${run.replay_verified === true ? '回放已验证。' : '回放验证未确认。'}${run.sealed_trace === true ? '具有封存轨迹。' : '无封存成功证明。'}`);
  const warnings = array(snapshot.warnings).filter((warning) => typeof warning === 'string');
  if (warnings.length) {
    write('evidence-warning', `证据提示 · ${warnings.join('；')}`);
    $('evidence-warning').hidden = false;
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
      const [label, tone] = statusInfo(level.status === 'successful' ? 'completed' : level.status);
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
      button.addEventListener('click', () => selectLevel(index));
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
    write('board-title', currentLevel().level === null ? '游戏画面 · 未记录关卡' : `关卡 ${currentLevel().level} · 游戏画面`);
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
    canvas.setAttribute('aria-label', `${columns} × ${rows} 网格，${frameLabel(frame)}${$('diff-toggle').checked && previous.length ? '，黄色边框标记变化格' : ''}`);
  }

  function renderFrame() {
    const count = frames().length;
    const frame = currentFrame();
    const action = selectedAction();
    const before = action && frameById(action.before_frame);
    const after = action && frameById(action.after_frame);
    const comparisonRequested = $('compare-toggle').checked;
    const canCompare = Boolean(before && after);
    $('board-empty').hidden = count > 0;
    $('single-board').hidden = count === 0 || (comparisonRequested && canCompare);
    $('comparison-board').hidden = count === 0 || !comparisonRequested || !canCompare;
    $('frame-slider').max = String(Math.max(0, count - 1));
    $('frame-slider').value = String(state.frameIndex);
    $('frame-slider').disabled = count < 2;
    write('frame-counter', `${count ? state.frameIndex + 1 : 0} / ${count}`);
    write('frame-state', frame ? frameState(frame.state) : '无帧记录');
    write('frame-caption', frame ? `${string(frame.id)}${frame.timestamp ? ` · ${frame.timestamp}` : ''}` : '当前关卡无帧记录');
    write('current-action', action ? actionLabel(action) : count ? '初始观察 / 未关联动作' : '没有记录动作');
    const decision = action && action.decision_id;
    write('current-action-link', action ? (decision ? `决策关联 ${decision}` : '未建立可靠的 P7 轮次关联') : '');
    const changed = action && action.changed_cells;
    write('change-caption', action ? `结算变化 ${Number.isFinite(changed) ? changed : array(changed).length} 格${changed === 0 ? ' · 画面未变化' : ''}` : '黄色边框：变化格');
    write('comparison-note', comparisonRequested ? (canCompare ? '对照显示所选动作的起始帧与结算帧' : action ? '前后帧缺链，无法对照' : '选择一个有前后帧的动作以对照') : '');
    if (frame) draw($('board-canvas'), frame, before, action);
    if (comparisonRequested && canCompare) {
      draw($('before-canvas'), before, null, action);
      draw($('after-canvas'), after, before, action);
      write('before-label', `动作前 · ${string(before.id)}`);
      write('after-label', `动作后 · ${string(after.id)}`);
    }
    $('previous-frame').disabled = !count || state.frameIndex <= 0;
    $('next-frame').disabled = !count || state.frameIndex >= count - 1;
    $('play-toggle').disabled = count < 2;
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
    if (frames().length < 2) return;
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

  function renderWorld() {
    const cognition = object(currentLevel().cognition);
    const guide = $('world-guide');
    const facts = $('world-facts');
    guide.replaceChildren(); facts.replaceChildren();
    if (cognition.scope !== 'final') {
      write('cognition-scope', '当前关卡没有身份匹配的稳定认知。');
      guide.append(node('p', '尚未确定。没有认知记录可供展示。', 'guide-empty'));
      return;
    }
    write('cognition-scope', '运行结束时的最终认知快照。未与历史帧或动作建立时间对齐，不能视为该帧当时已有的知识。');
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
    update.append(node('h3', '最近一次稳定更新'), node('p', '最终快照；具体更新时间未与回放帧对齐。'));
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
    write('decision-count', decisions.length);
    write('actions-count', actions().length);
    write('cognition-count', updates.length);
    decisionsPanel.append(node('p', '这里只展示模型轮次与输入 / 输出信号。信号不是详细决策解释；缺失的规划目标、依据和下一步判断不会被补写。', 'process-note'));
    if (!decisions.length) emptyPanel(decisionsPanel, '没有可审计的 P7 决策信号', '动作记录本身不能证明某一轮次的规划内容。');
    decisions.forEach((decision, index) => {
      const card = node('article', undefined, 'event-card');
      card.dataset.decisionId = string(decision.id, '');
      const header = node('div', undefined, 'event-header');
      const heading = node('div', undefined, 'event-heading');
      heading.append(node('span', String(index + 1).padStart(2, '0'), 'event-index'), node('h3', `P7 第 ${number(decision.round_index, index + 1)} 轮`), node('span', '决策信号', 'neutral-tag'));
      header.append(heading);
      const linked = actions().filter((action) => array(decision.action_ids).includes(action.id));
      if (linked.length) {
        const button = node('button', '定位动作', 'event-link'); button.type = 'button';
        button.addEventListener('click', () => locateAction(linked[0])); header.append(button);
      }
      card.append(header);
      addMetadata(card, [decision.trace_sequence != null ? `轨迹序号 ${decision.trace_sequence}` : '轨迹序号缺失', `关联动作 ${linked.length}`]);
      if (!linked.length) card.append(node('p', '全运行信号：未建立可靠的关卡、帧或动作关联。该轮次不代表当前画面的决策。', 'event-note'));
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
      actionsPanel.append(card);
    });
    cognitionPanel.append(node('p', '认知事件是最终会话的记录，未与回放帧、动作或模型轮次建立时间关联。展开后可查看保留的认知条目。', 'process-note'));
    if (!updates.length) emptyPanel(cognitionPanel, '没有可展示的认知更新事件', '没有事件证据时，不从最终快照倒推历史认知。');
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
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault(); pause(); setFrame(state.frameIndex + (event.key === 'ArrowRight' ? 1 : -1));
    } else if (event.code === 'Space' && !event.repeat) { event.preventDefault(); state.timer === null ? play() : pause(); }
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); });
  window.addEventListener('pagehide', pause);
  selectLevel(state.levelIndex);
})();
