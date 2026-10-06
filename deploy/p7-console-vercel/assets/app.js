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
  const ACTION_NAMES = ['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4', 'ACTION5', 'ACTION6', 'ACTION7', 'RESET'];
  const validActionLabels = (value) => (value.action_labels === undefined || (Array.isArray(value.action_labels) && value.action_labels.length <= 8 &&
      value.action_labels.every((entry, index, entries) => isRecord(entry) &&
        Object.keys(entry).sort().join(',') === 'action,confidence,evidence_sequences,label,purpose' &&
        ACTION_NAMES.includes(entry.action) && (index === 0 || entry.action > entries[index - 1].action) &&
        ['certain', 'hypothesis', 'unknown', 'conflict'].includes(entry.confidence) &&
        (entry.label === null || (typeof entry.label === 'string' && entry.label.trim().length > 0 && [...entry.label].length <= 24)) &&
        typeof entry.purpose === 'string' && [...entry.purpose].length <= 600 &&
        (['unknown', 'conflict'].includes(entry.confidence) ? entry.label === null : entry.label !== null && Boolean(entry.purpose.trim()) && Boolean(entry.evidence_sequences?.length)) &&
        Array.isArray(entry.evidence_sequences) && entry.evidence_sequences.length <= 32 &&
        entry.evidence_sequences.every((sequence, i, sequences) => Number.isInteger(sequence) && sequence >= 0 && sequence <= 1000000000 &&
          (i === 0 || sequence > sequences[i - 1]) && (value.provenance !== undefined || !Number.isInteger(value.source_action_sequence) || sequence <= value.source_action_sequence)))));
  const validProvenance = (value) => value === undefined || (isRecord(value) && Object.keys(value).sort().join(',') === 'event_sequence,run_id' &&
    typeof value.run_id === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}$/.test(value.run_id) && Number.isInteger(value.event_sequence) && value.event_sequence > 0);
  const validCognition = (cognition) => cognition === undefined || (isRecord(cognition) &&
    stringFields(cognition, ['scope', 'stable_description']) && validProvenance(cognition.provenance) && validActionLabels(cognition) &&
    optionalRecords(cognition.updates, (update) => isRecord(update) && optionalString(update.type) && optionalNumber(update.sequence) && optionalRecords(update.changes, validClaim)) &&
    (cognition.action_meanings === undefined || (isRecord(cognition.action_meanings) && Object.values(cognition.action_meanings).every((entries) => optionalRecords(entries, validClaim)))));
  const validTimelineEntry = (entry) => isRecord(entry) &&
    stringFields(entry, ['scope', 'frame_id', 'action_id', 'stable_description', 'cognition_narrative_zh']) &&
    numberFields(entry, ['cognition_revision', 'source_action_sequence', 'event_sequence']) && validProvenance(entry.provenance) && validActionLabels(entry);
  const DIAGNOSTIC_LABELS = {
    'evidence-write-failed':'证据保存失败', 'evidence-read-failed':'证据读取失败', 'evidence-hash-failed':'证据校验失败',
    'observation-validation-failed':'观察校验失败', 'derived-projection-failed':'展示数据整理失败',
    'console-publication-failed':'控制台发布失败', 'research-read-failed':'研究记录读取失败',
    'research-response-budget-exceeded':'研究响应容量超限', 'engine-no-reply':'环境未返回结果', 'engine-response-invalid':'环境返回结果无效', 'action-not-dispatched':'动作未派发',
    'evidence-cancelled':'证据处理已取消', 'evidence-deadline-exceeded':'证据处理达到本轮时限',
  };
  const DIAGNOSTIC_STAGES = {
    'not-dispatched':'尚未执行', 'dispatched-no-reply':'已执行，未收到结果', 'reply-received-unvalidated':'收到结果，完整校验未完成', 'reply-received-invalid':'收到结果，校验失败',
    'validated-not-durable':'结果有效，保存未完成', 'durably-committed':'结果已保存', 'derived-failed':'展示或研究数据处理失败',
  };
  const DIAGNOSTIC_RECOVERY = {
    'pause-and-rebuild':'暂停并重建', 'read-only-rebuild':'从已保存证据重建', 'stop-without-redispatch':'停止，避免重复执行',
    'fix-request':'修正请求', 'retry-read':'重试读取', 'operator-recovery':'等待恢复处理', 'none':'无需恢复操作',
  };
  const validDiagnostic = value => isRecord(value) && Object.hasOwn(DIAGNOSTIC_LABELS,value.code) &&
    Object.keys(value).every(key=>['diagnostic_id','code','severity','stage','action_sequence','outcome_known','durable','observed','limit','unit','recovery','first_seen','last_seen','count','status','recovered_at'].includes(key)) &&
    ['info','warning','error'].includes(value.severity) && Object.hasOwn(DIAGNOSTIC_STAGES,value.stage) &&
    Object.hasOwn(DIAGNOSTIC_RECOVERY,value.recovery) && Number.isInteger(value.action_sequence) && value.action_sequence >= 0 &&
    typeof value.outcome_known === 'boolean' && typeof value.durable === 'boolean' && (!value.durable || value.outcome_known) &&
    [value.observed,value.limit].every(metric => metric === null || (Number.isInteger(metric) && metric >= 0)) &&
    (value.unit === null || ['bytes','cells','frames','rows','events'].includes(value.unit)) &&
    (value.status === undefined || ['active','recovered'].includes(value.status)) &&
    (value.count === undefined || (Number.isInteger(value.count) && value.count > 0));
  function validSnapshot(value) {
    if (!isRecord(value) || !['asterion.arc-agi3-p7-console/v1','asterion.arc-agi3-p7-console/v2'].includes(value.schema) || !isRecord(value.run) || !Array.isArray(value.levels)) return false;
    if (!optionalRecords(value.diagnostics,validDiagnostic)) return false;
    if (!optionalRecords(value.decisions, validDecision) || !stringFields(value.run, ['status', 'game_id', 'run_id']) || !optionalString(value.generated_at)) return false;
    if (value.process_events !== undefined && (!Array.isArray(value.process_events) || value.process_events.length > 16384 ||
      value.process_events.some((event, index, events) => !isRecord(event) || !Number.isInteger(event.event_sequence) || event.event_sequence < 1 ||
        (index > 0 && event.event_sequence <= events[index - 1].event_sequence) || !['observation', 'action', 'decision', 'cognition', 'compute_task', 'model_revision', 'plan', 'feedback', 'run_control', 'diagnostic'].includes(event.kind) ||
        typeof event.frame_id !== 'string' || !Number.isInteger(event.level) || !isRecord(event.payload) || !validProvenance(event.provenance) ||
        (event.kind === 'diagnostic' && !validDiagnostic(event.payload)) ||
        !validActionLabels({ ...event.payload, source_action_sequence: event.source_action_sequence, provenance: event.provenance })))) return false;
    const run = value.run;
    if (run.win_levels != null && (!Number.isInteger(run.win_levels) || run.win_levels < 0 || run.win_levels > 1000)) return false;
    const ids = new Set();
    return value.levels.every((level) => {
      if (!isRecord(level) || !Number.isInteger(level.level) || level.level < 1 || level.level > 1000 || ids.has(level.level)) return false;
      ids.add(level.level);
      if (!Array.isArray(level.frames) || !Array.isArray(level.actions) || !Array.isArray(level.decisions) || !optionalString(level.status) || !validCognition(level.cognition)) return false;
      if (level.frame_page !== undefined && (!isRecord(level.frame_page) || !Number.isInteger(level.frame_count) || level.frame_count < 1 ||
        !Number.isInteger(level.frame_index_offset) || level.frame_index_offset < 0 || !/^[a-f0-9]{64}$/.test(level.frame_page.source_token || '') ||
        !Number.isInteger(level.frame_page.start) || level.frame_page.start < 0 || level.frame_page.start >= level.frame_count ||
        !Number.isInteger(level.frame_page.limit) || level.frame_page.limit < 1 || level.frame_page.limit > 32 ||
        level.frames.length > 32 || level.frames.some((frame,index)=>frame.index !== level.frame_page.start+index || frame.id !== `f${String(level.frame_index_offset+frame.index).padStart(6,'0')}`))) return false;
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
    renderEvidenceWarnings(['控制台快照无法读取，或数据版本不受支持。']);
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
  let consoleConfig = null;
  try { consoleConfig = JSON.parse($('console-config').textContent); } catch (_) { /* An invalid config never enables requests. */ }
  const liveConfig = isRecord(consoleConfig) && consoleConfig.readOnly === true ? consoleConfig : null;
  const CLOUD_REFRESH_INTERVAL = 300000;
  function enforceCloudReadOnly() {
    document.querySelectorAll('#run-start,#run-fresh,#run-pause,#run-resume,#run-stop,#manual-close,#manual-restart,#retry-command,[data-overview-start],[data-overview-fresh]').forEach(button => {button.disabled = true; button.hidden = true; button.title = '云端只读；请在本地控制求解';});
    $('game-select').disabled = false;
    $('manual-note').textContent = '云端只读观察与回放；游戏动作和求解控制在本地执行。';
  }
  $('console-mode').querySelector('option[value=manual]')?.remove();
  const levelReplayEnabled = liveConfig?.replay_loading === 'level-manifest/v1';
  $('replay-loading-slot').hidden = !levelReplayEnabled;
  const validatedReplayViews = new WeakSet();
  const state = { selectionReady: false, gameSelectionTouched: false, overview: null, overviewFresh: false, overviewBusy: false, overviewPending: false, overviewTimer: null, replayPollTimer: null, replayPollBusy: false, replayFailures: 0, replayRetryAt: 0, replayFollow: true, mode: liveConfig ? 'live' : 'replay', replayRun: null, replayGeneration: 0, manualGeneration: 0, manualPollGeneration: 0, manualBusy: false, manualError: false, manualView: null, manualChoice: null, manualPending: null, manualSaveRetry: null, manualFeedback: null, manualHistory: null, pointerAction: null, liveView: null, pendingCommand: null, commandBusy: false, pollBusy: false, pollTimer: null, levelIndex: Math.max(0, levels.findIndex((level) => array(level.frames).length)), frameIndex: 0, eventSequence: null, actionId: null, timer: null, tab: 'decisions' };
  const emptyLevel = { level: null, status: 'not-run', frames: [], actions: [], decisions: [], cognition: { scope: 'unavailable' }, receipt: null };
  const retiredManualSessions = new Set();
  let attemptReplayRun = null;
  let initialGameLevelPending = Boolean(liveConfig);
  const gamePreviews = new Map();
  // Auxiliary views retain their own run authority. Never merge them into the
  // currently observed attempt or attach its events to another run's frames.
  const savedViews = new Map(), savedRequests = new Map(), previewViews = new Map(), boardSavedViews = new Map();
  const replayManifests = new Map(), manifestRequests = new Map(), replayLevelRequests = new Map(), replayLevelViews = new Map(), replayViewSizes = new WeakMap();
  const framePages=new Map(),framePageRequests=new Map(),framePageErrors=new Set(),frameIndexMaps=new WeakMap();
  let replayLoad = null, replayLoadTimer = null;
  const primaryLevel = () => levels[state.levelIndex] || emptyLevel;
  const levelFrameCount = level => level.replay_unloaded || level.frame_page ? number(level.frame_count) : array(level.frames).length;
  const levelActionCount = level => level.replay_unloaded ? number(level.action_count) : array(level.actions).length;
  function cachedSavedView() {
    if (state.mode === 'manual') return null;
    const view = savedViews.get(run.game_id), game = verifiedSavedGame();
    return view && view.run.seed === run.seed && view.run.win_levels === run.win_levels &&
      (!state.overviewFresh || Boolean(game)) ? view : null;
  }
  function savedView() {
    const view = cachedSavedView();
    return view && (!state.overviewFresh || verifiedSavedGame()?.best_run_id === view.run.run_id) ? view : null;
  }
  const savedLevel = (level) => array(savedView()?.levels).find(entry => entry.level === level && entry.status === 'successful') || null;
  const retainedSavedLevel = (level) => savedView() ? null : array(cachedSavedView()?.levels).find(entry => entry.level === level && entry.status === 'successful') || null;
  function levelSource(level = primaryLevel()) {
    if (state.mode === 'manual' || levelFrameCount(level) > 0) return {scope: string(run.status, '').startsWith('preview') ? 'preview' : 'current', snapshot, level, key:`${run.game_id}/${run.run_id || 'preview'}/${snapshot.replay_revision || ''}/${level.level}/${level.replay_unloaded ? 'unloaded' : 'loaded'}`};
    const view = boardSavedViews.get(`${run.game_id}/${level.level}`);
    const saved = state.mode !== 'manual' && view && view.run.seed === run.seed && view.run.win_levels === run.win_levels ?
      array(view.levels).find(entry => entry.level === level.level && entry.status === 'successful') : null;
    if (saved && levelFrameCount(saved) > 0) return {scope:'saved',snapshot:view,level:saved,key:`${run.game_id}/${view.run.run_id}/${view.replay_revision || ''}/${level.level}/${saved.replay_unloaded ? 'unloaded' : 'loaded'}`};
    const preview = previewViews.get(`${run.game_id}/${level.level}`);
    return preview ? {scope:'preview',snapshot:preview,level:preview.levels[0],key:`${run.game_id}/preview/${level.level}`} : {scope:'current',snapshot,level,key:`${run.game_id}/${run.run_id}/${snapshot.replay_revision || ''}/${level.level}/${level.replay_unloaded ? 'unloaded' : 'loaded'}`};
  }
  const currentLevel = () => levelSource().level;
  const frames = () => array(currentLevel().frames);
  const actions = () => array(currentLevel().actions);
  function frameIndexForId(id) {
    if (currentLevel().frame_page) return /^f\d+$/.test(id || '') ? Number(id.slice(1))-currentLevel().frame_index_offset : -1;
    const list=frames();
    let index=frameIndexMaps.get(list);
    if (!index || index.size !== list.length) {index=new Map(list.map((frame,index)=>[frame.id,index]));frameIndexMaps.set(list,index);}
    return index.get(id) ?? -1;
  }
  const framePageKey = (source,start) => `${source.key}/${source.level.frame_page.source_token}/${start}`;
  function frameAt(index) {
    const source=levelSource(),level=source.level;
    if (!level.frame_page) return array(level.frames)[index];
    const local=array(level.frames).find(frame=>frame.index===index);
    if (local) return local;
    const key=framePageKey(source,Math.floor(index/32)*32),page=framePages.get(key);
    if (page) {framePages.delete(key);framePages.set(key,page);return page.find(frame=>frame.index===index);}
    return undefined;
  }
  const currentFrame = () => frameAt(state.frameIndex);
  const frameById = id => state.mode === 'manual' && run.status === 'manual' ? levels.flatMap(level=>array(level.frames)).find(frame=>frame.id===id) : frameAt(frameIndexForId(id));
  const processEvents = () => {
    if (state.mode === 'manual') return [];
    const source = levelSource(), frameIds = new Set(array(source.level.frames).map(frame => frame.id));
    return array(source.snapshot.process_events).filter(event => event.level === source.level.level && (source.level.frame_page ? frameIndexForId(event.frame_id)>=0 && frameIndexForId(event.frame_id)<levelFrameCount(source.level) : frameIds.has(event.frame_id)));
  };
  const cursorSequence = (events) => {
    if (state.eventSequence !== null) return state.eventSequence;
    const frameIndexes = new Map(frames().map((frame, index) => [frame.id, index]));
    let cursor = null;
    (events || processEvents()).forEach(event => {
      if ((currentLevel().frame_page ? frameIndexForId(event.frame_id) : frameIndexes.get(event.frame_id)) <= state.frameIndex) cursor = event.event_sequence;
    });
    return cursor;
  };
  const researchEvents = () => {
    const events = processEvents(), cursor = cursorSequence(events);
    return events.filter(event => event.event_sequence <= cursor && ['compute_task', 'model_revision', 'plan', 'feedback', 'run_control'].includes(event.kind));
  };
  const selectedAction = () => actions().find((action) => action.id === state.actionId) || null;
  const manualPlayable = () => state.mode === 'manual' && run.status === 'manual' && state.manualView?.state === 'ready' &&
    state.manualView.game_id === run.game_id && manualLevel(state.manualView) === currentLevel().level && !state.manualBusy && !state.manualPending && !state.manualError &&
    !state.commandBusy && !state.pendingCommand && !activeSession() && !manualUnsaved() && Boolean(currentFrame()) && manualAtCurrent();
  const manualRestartable = () => state.mode === 'manual' && run.status === 'manual' && ['ready', 'uncertain'].includes(state.manualView?.state) &&
    state.manualView.game_id === run.game_id && manualLevel(state.manualView) === currentLevel().level && liveConfig && state.liveView &&
    !activeSession() && !state.manualBusy && !state.manualPending && !state.commandBusy && !state.pendingCommand && Boolean(currentFrame()) && manualAtCurrent();
  const manualHistoryActive = () => state.mode === 'manual' && run.status === 'manual' && Boolean(state.manualHistory && state.manualView && state.manualHistory.session_id === state.manualView.session_id);
  const manualAtCurrent = () => !manualHistoryActive() || state.manualHistory.index === state.manualHistory.entries.length - 1;
  const timelineCount = () => manualHistoryActive() ? state.manualHistory.entries.length : levelFrameCount(currentLevel());
  const timelinePosition = () => manualHistoryActive() ? state.manualHistory.index : state.frameIndex;

  function setManualFrame(index, actionId) {
    const history = state.manualHistory;
    if (!manualHistoryActive() || !history.entries.length) return;
    history.index = Math.max(0, Math.min(history.entries.length - 1, index));
    const entry = history.entries[history.index];
    const levelIndex = levels.findIndex((level) => level.level === entry.level);
    if (state.levelIndex !== levelIndex) selectLevel(levelIndex, { pausePlayback: false });
    state.frameIndex = frames().findIndex((frame) => frame.id === entry.frame.id);
    state.actionId = actionId === undefined ? entry.action?.id || actions().find((action) => action.after_frame === entry.frame.id)?.id || null : actionId;
    if (!manualAtCurrent()) state.pointerAction = null;
    renderFrame(); renderSessionControls();
  }

  function sameManualFrame(left, right) {
    return ['id', 'state', 'levels_completed', 'timestamp'].every((key) => left[key] === right[key]) &&
      JSON.stringify(left.grid) === JSON.stringify(right.grid) && JSON.stringify(left.available_actions) === JSON.stringify(right.available_actions);
  }

  function sameManualAction(left, right) {
    return left == null || right == null ? left == null && right == null : left.action === right.action &&
      left.observation_version === right.observation_version && Object.keys(left.data).length === Object.keys(right.data).length &&
      Object.keys(left.data).every((key) => left.data[key] === right.data[key]);
  }

  function appendManualObservation(view) {
    const record = array(view.snapshot?.levels).find((level) => level.level === manualLevel(view));
    const frame = array(record?.frames).at(-1);
    if (!frame) return false;
    const existing = state.manualHistory;
    const same = existing?.session_id === view.session_id && existing.game_id === view.game_id;
    const source = view.history?.length ? view.history : [{ observation_version: view.observation_version,
      episode_id: view.episode_id, action_count: view.action_count, level: record.level, frame, last_action: view.last_action }];
    const observations = new Map(same ? existing.entries.map((entry) => [entry.version, entry]) : []);
    source.forEach((item) => {
      const previous = observations.get(item.observation_version);
      if (previous) {
        if (previous.level !== item.level || previous.count !== item.action_count || previous.episode_id !== item.episode_id ||
            !sameManualFrame(previous.frame, item.frame) || !sameManualAction(previous.last_action, item.last_action)) throw new Error('invalid-response');
        return;
      }
      const historical = item.observation_version !== view.observation_version;
      const itemRecord = historical ? { level: item.level, status: 'manual', frames: [item.frame], actions: [], decisions: [], cognition: { scope: 'unavailable' } } : record;
      observations.set(item.observation_version, { version: item.observation_version, episode_id: item.episode_id,
        count: item.action_count, level: item.level, record: itemRecord, frame: item.frame, last_action: item.last_action, action: null });
    });
    const entries = [...observations.values()].sort((a, b) => a.version - b.version).slice(-1001);
    if (same && entries.length === existing.entries.length && entries.every((entry, index) => entry === existing.entries[index])) return false;
    const derived = entries.map((item, index) => {
      const previous = entries[index - 1], last = item.last_action;
      const entry = { ...item, gap: previous ? item.version - previous.version - 1 : item.version, action: null };
      if (previous && entry.version === previous.version + 1 && last?.observation_version === entry.version &&
          entry.count === previous.count + 1 && array(previous.frame.available_actions).includes(last.action)) {
        const before = previous.frame.grid, after = entry.frame.grid;
        let changed = 0;
        for (let y = 0; y < Math.max(before.length, after.length); y += 1) {
          for (let x = 0; x < Math.max(array(before[y]).length, array(after[y]).length); x += 1) {
            if (before[y]?.[x] !== after[y]?.[x]) changed += 1;
          }
        }
        entry.action = { id: `manual-action-${entry.version}`, name: last.action, data: last.data,
          before_frame: previous.frame.id, after_frame: entry.frame.id, changed_cells: changed };
      }
      return entry;
    });
    const selectedVersion = same ? existing.entries[existing.index]?.version : null;
    const follow = !same || existing.index === existing.entries.length - 1;
    const selectedIndex = derived.findIndex((entry) => entry.version === selectedVersion);
    state.manualHistory = { session_id: view.session_id, game_id: view.game_id, entries: derived,
      index: follow ? derived.length - 1 : Math.max(0, selectedIndex) };
    return true;
  }

  function manualHistorySnapshot(view) {
    if (!state.manualHistory || state.manualHistory.session_id !== view.session_id || !view.snapshot) return view.snapshot;
    const records = new Map();
    state.manualHistory.entries.forEach((entry) => {
      const previous = records.get(entry.level);
      const record = { ...entry.record, frames: previous ? [...previous.frames] : [], actions: previous ? [...previous.actions] : [] };
      array(entry.record.frames).forEach((frame) => { if (!record.frames.some((item) => item.id === frame.id)) record.frames.push(frame); });
      [...array(entry.record.actions), ...(entry.action ? [entry.action] : [])].forEach((action) => { if (!record.actions.some((item) => item.id === action.id)) record.actions.push(action); });
      records.set(entry.level, record);
    });
    return { ...view.snapshot, levels: [...records.values()].sort((a, b) => a.level - b.level) };
  }

  function renderManualHistory() {
    const active = manualHistoryActive();
    const list = $('manual-action-history');
    $('manual-history').hidden = !active;
    $('manual-return-current').hidden = !active || manualAtCurrent();
    if (!active) return;
    const history = state.manualHistory;
    const entries = history.entries.filter((entry) => entry.action);
    const existing = new Map([...list.children].map((button) => [button.dataset.historyVersion, button]));
    [...list.children].forEach((button) => { if (!entries.some((entry) => String(entry.version) === button.dataset.historyVersion)) button.remove(); });
    entries.forEach((entry, index) => {
      let button = existing.get(String(entry.version));
      if (!button) {
        button = node('button', `#${entry.count} ${entry.action.name}`, 'manual-history-action');
        button.type = 'button'; button.dataset.historyVersion = String(entry.version);
        button.addEventListener('click', () => { pause(); const position = state.manualHistory.entries.findIndex((item) => item.version === Number(button.dataset.historyVersion)); if (position >= 0) setManualFrame(position); });
      }
      const selected = entry.action.id === state.actionId;
      button.classList.toggle('is-selected', selected);
      if (selected) button.setAttribute('aria-current', 'true'); else button.removeAttribute('aria-current');
      if (list.children[index] !== button) list.insertBefore(button, list.children[index] || null);
    });
    const missing = history.entries.some((entry) => entry.gap > 0);
    write('manual-history-note', missing ? '试玩记录 · 中间或更早的观察记录缺失，不补写动作' : '试玩记录 · 播放与定位只查看画面');
  }

  const statuses = {
    completed: ['已过关', 'success'], successful: ['已成功', 'success'], success: ['已成功', 'success'], won: ['已过关', 'success'],
    running: ['运行中', 'active'], active: ['可继续', 'active'], in_progress: ['进行中', 'active'], loading: ['读取中', 'active'],
    incomplete: ['未完成', 'warning'], interrupted: ['已中断', 'warning'], waiting: ['等待', 'warning'], unknown: ['信息不足', 'warning'],
    unsuccessful: ['未成功', 'failed'], failed: ['失败', 'failed'], game_over: ['游戏结束', 'failed'],
    manual: ['人工试玩', 'neutral'], 'not-run': ['未运行', 'neutral'], not_run: ['未运行', 'neutral'], unobserved: ['未运行', 'neutral'], unavailable: ['无证据', 'neutral'],
    preview: ['尚未开始', 'neutral'], 'preview-unavailable': ['初始画面不可用', 'warning'],
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
    write('run-id', ['manual', 'preview', 'preview-unavailable'].includes(run.status) ? '尚未启动 P7' : string(run.run_id));
    write('level-progress', `${run.status === 'loading' ? '—' : number(run.completed_level_count)} / ${number(run.win_levels) || '未知'}`);
    write('action-total', run.status === 'loading' ? '—' : number(run.primitive_action_count));
    write('level-total', levelCount ? `${levelCount} 个关卡` : '总数未知');
    renderProgressContext();
    setStatus($('run-status'), run.status);
    write('snapshot-date', `快照时间 ${string(snapshot.generated_at)}`);
    write('verification-note', run.status === 'manual' ? '独立人工试玩；启动 P7 会重置游戏并开始新的运行。' : string(run.status, '').startsWith('preview') ? '只读初始画面；尚未启动 P7，没有求解或试玩动作记录。' : `${run.replay_verified === true ? '回放已验证。' : '回放验证未确认。'}${run.sealed_trace === true ? '具有封存轨迹。' : '无封存成功证明。'}`);
    renderEvidenceWarnings(array(snapshot.warnings).filter((warning) => typeof warning === 'string'),array(snapshot.diagnostics),`${run.game_id}/${run.run_id}`);
  }

  function diagnosticText(diagnostic) {
    const unit={bytes:'字节',cells:'格',frames:'帧',rows:'行',events:'事件'}[diagnostic.unit] || '';
    const size=diagnostic.observed === null ? '' : ` · ${diagnostic.observed}${unit}${diagnostic.limit === null ? '' : ` / 上限 ${diagnostic.limit}${unit}`}`;
    return `${diagnostic.status === 'recovered' ? '已恢复 · ' : ''}${DIAGNOSTIC_LABELS[diagnostic.code]} · 动作 ${diagnostic.action_sequence} · ${diagnostic.outcome_known ? '结果已知' : '结果未知'} · ${diagnostic.durable ? '已持久化' : '未持久化'} · ${DIAGNOSTIC_STAGES[diagnostic.stage]}${size} · ${DIAGNOSTIC_RECOVERY[diagnostic.recovery]}${diagnostic.count > 1 ? ` · 累计 ${diagnostic.count} 次` : ''}`;
  }

  function renderEvidenceWarnings(warnings,diagnostics=[],source='invalid-snapshot') {
    const details = $('evidence-details'), records=diagnostics.filter(validDiagnostic);
    const active=records.filter(record=>record.status !== 'recovered' && record.severity !== 'info');
    const text=[...records.map(diagnosticText),...warnings].join('；');
    if (details.dataset.source !== source) details.open = false;
    details.dataset.source=source;
    details.classList.toggle('has-processing-warning',active.length > 0);
    details.hidden = !text;
    write('evidence-warning', text);
    const label=active.length ? `警告 ${active.length}` : records.length && records.every(record=>record.status === 'recovered') ? `已恢复 ${records.length}` : `说明 ${warnings.length + records.length}`;
    write('evidence-summary',label);
    $('evidence-summary').title = text;
    $('evidence-summary').setAttribute('aria-label', `${label}：${text}`);
  }

  function levelEfficiency(level) {
    const game = array(consoleConfig?.games).find((entry) => entry.game_id === run.game_id && entry.win_levels === run.win_levels);
    const baseline = array(game?.baseline_actions)[level.level - 1];
    const actual = levelActionCount(level);
    const known = Number.isInteger(baseline) && baseline > 0;
    const completed = level.status === 'successful';
    const score = completed && known && actual > 0 ? Math.min(115, 100 * (baseline / actual) ** 2) : null;
    return {text: `基准 ${known ? baseline : '未知'} / ${actual} 动作 / 关卡效率${completed ? score === null ? '未知' : ` ${score.toFixed(2)} 分` : '待完成'}`,
      railText: `基准 ${known ? baseline : '未知'} · ${completed ? score === null ? '分数未知' : `${score.toFixed(2)} 分` : '待完成'}`,
      low: score !== null && score < 100};
  }

  function verifiedSavedGame() {
    if (state.mode === 'manual' || !state.overviewFresh || run.seed !== state.overview?.scope.seed) return null;
    const game = array(state.overview?.games).find((entry) => entry.game_id === run.game_id && entry.win_levels === run.win_levels);
    const best = array(game?.runs).find((entry) => entry.run_id === game.best_run_id);
    return best?.verified === true && best.completed_levels === game.completed_levels && game.completed_levels > 0 ? game : null;
  }

  function matchesVerifiedSavedRun(meta, game, seed) {
    // Validate immutable request evidence here. Current selection/authority is
    // rechecked by the caller before applying a shared asynchronous response.
    const best = array(game.runs).find(entry => entry.run_id === game.best_run_id);
    return best?.verified === true && best.completed_levels === game.completed_levels && game.best_run_id === meta.run_id &&
      game.completed_levels === meta.completed_level_count && meta.game_id === game.game_id &&
      meta.seed === seed && meta.win_levels === game.win_levels && meta.sealed_trace === true;
  }

  function currentRunLevelLabel(level) {
    if (state.mode === 'manual') return statusInfo(level.status)[0];
    if (level.replay_unloaded && levelFrameCount(level) > 0) return level.status === 'successful' ? '已过关 · 画面按需读取' : '已有记录 · 画面按需读取';
    if (level.status === 'loading') return '正在读取记录';
    if (level.status === 'preview') return '关卡初始预览 · 尚未开始';
    if (level.status === 'preview-unavailable') return '初始画面暂不可用 · 尚未开始';
    if (level.status === 'successful') return '本轮已过关';
    if (['not_run', 'not-run', 'unobserved'].includes(level.status)) return liveConfig ? '本轮未运行' : '本轮未记录';
    if (level.status === 'incomplete' && activeSession() && state.liveView?.run_id === run.run_id) return '本轮进行中';
    return `本轮${statusInfo(level.status)[0]}`;
  }

  function renderProgressContext() {
    const manual = state.mode === 'manual', game = verifiedSavedGame();
    const current = run.status === 'loading' ? '正在读取回放' : `本轮 ${number(run.completed_level_count)} / ${number(run.win_levels) || '未知'}`;
    $('run-progress-summary').hidden = manual;
    write('run-progress-summary', string(run.status, '').startsWith('preview') ? '关卡初始预览 · 尚未开始' : game ? `游戏已保存 ${game.completed_levels} / ${game.win_levels} · ${current}` : current);
    setStatus($('level-status'), currentLevel().status === 'successful' ? 'completed' : currentLevel().status);
    if (!manual) write('level-status', levelSource().scope === 'saved' ? '已保存 · 已过关' : currentRunLevelLabel(currentLevel()));
    const saved = game && currentLevel().status !== 'successful' && currentLevel().level <= game.completed_levels;
    $('level-saved-status').hidden = !saved;
    write('level-saved-status', saved ? '已有过关记录' : '');
  }

  function renderRail() {
    const list = $('level-list');
    const savedGame = verifiedSavedGame();
    list.replaceChildren();
    if (!levels.length) list.append(node('p', '没有可验证的关卡记录。', 'guide-empty'));
    levels.forEach((level, index) => {
      const authority = savedLevel(level.level), retained = retainedSavedLevel(level.level), displayed = authority || retained || levelSource(level).level;
      const button = node('button', undefined, 'level-button');
      button.id = `level-${level.level}`;
      button.type = 'button';
      button.setAttribute('aria-current', String(index === state.levelIndex));
      const manual = state.mode === 'manual';
      const [statusLabel, tone] = manual && !array(level.frames).length ? ['可直接试玩', 'neutral'] : statusInfo(displayed.status === 'successful' ? 'completed' : displayed.status);
      const label = manual ? statusLabel : authority ? '已保存 · 已过关' : retained ? '历史已保存 · 最佳路线刷新中' : currentRunLevelLabel(displayed);
      if (authority || retained) {
        button.dataset.savedSourceRunId = (authority ? savedView() : cachedSavedView()).run.run_id;
        button.dataset.savedCurrentBest = String(Boolean(authority));
      }
      button.disabled = manual && manualSelectionLocked();
      const saved = manual && state.manualView?.game_id === run.game_id && array(state.manualView.saved_levels).includes(level.level);
      const verified = savedGame && level.status !== 'successful' && level.level <= savedGame.completed_levels;
      const count = levelActionCount(displayed), passed = displayed.status === 'successful';
      const savedStepsPending = verified && !authority && !retained && !passed;
      const conciseStatus = manual ? statusLabel : retained ? '已过关 · 更新中' : passed || verified ? '已过关'
        : displayed.status === 'loading' ? '读取中' : displayed.status === 'preview-unavailable' ? '预览不可用'
          : ['preview', 'not_run', 'not-run', 'unobserved'].includes(displayed.status) ? '未开始'
            : currentRunLevelLabel(displayed) === '本轮进行中' ? '进行中' : '未过关';
      const stepText = savedStepsPending ? '步数待读取' : passed || count ? `${count} 动作` : '无动作记录';
      const details = `${label}${verified ? ' · 已有过关记录' : ''} · ${count} 动作 · ${levelFrameCount(displayed)} 帧${displayed.replay_unloaded ? ' · 按需读取' : ''}${displayed.receipt ? ' · 回执' : ''}${manual ? '' : ` · ${levelEfficiency(displayed).text}`}`;
      button.title = details;
      button.setAttribute('aria-label', `关卡 ${level.level}，${conciseStatus}，${savedStepsPending ? '已保存过关步数待读取' : passed ? `过关 ${count} 步` : count ? `本次${manual ? '试玩' : '尝试'} ${count} 步` : '尚无动作记录'}，${details}`);
      button.append(node('span', String(level.level).padStart(2, '0'), 'level-number'));
      const content = node('div', undefined, 'level-item-content');
      const heading = node('div', undefined, 'level-item-heading');
      const dot = node('span', undefined, `level-status-dot status-${tone}`);
      dot.setAttribute('aria-hidden', 'true');
      heading.append(node('strong', `关卡 ${level.level}`), dot);
      if (saved) heading.append(node('span', '已保存', 'level-saved-badge'));
      const meta = node('p', undefined, 'level-item-detail');
      if (!savedStepsPending && !passed && count) meta.append(document.createTextNode(`${manual ? '试玩' : '尝试'} `));
      meta.append(node(!savedStepsPending && (passed || count) ? 'strong' : 'span', stepText, 'level-step-count'));
      if (count && levelFrameCount(displayed)) meta.append(document.createTextNode(` · ${levelFrameCount(displayed)} 帧`));
      content.append(heading, node('p', conciseStatus, 'level-item-status'));
      if (savedStepsPending || passed || count || !['未开始', '读取中', '预览不可用'].includes(conciseStatus)) content.append(meta);
      if (!manual) {
        const efficiency = levelEfficiency(displayed);
        content.append(node('p', efficiency.railText, `level-item-detail level-item-efficiency${efficiency.low ? ' efficiency-low' : ''}`));
      }
      button.append(content);
      button.addEventListener('click', () => {
        if (state.mode !== 'manual') {
          selectLevel(index); seekFrame(0);
          if (levelReplayEnabled && state.mode === 'replay' && run.run_id && primaryLevel().replay_unloaded) loadReplay({ preserveSelection:true });
          else ensureSelectedSource();
          return;
        }
        if (manualSelectionLocked()) return;
        if (state.manualView?.state === 'ready' && !state.manualError && state.manualView.game_id === run.game_id && manualLevel(state.manualView) === level.level && array(level.frames).length) { if (manualHistoryActive()) { pause(); setManualFrame(state.manualHistory.entries.length - 1); } else selectLevel(index); }
        else openManual(level.level);
      });
      list.append(button);
    });
  }

  function selectLevel(index, { pausePlayback = true, bindSavedSource = true, retireLoad = true } = {}) {
    if (pausePlayback) pause();
    if (retireLoad && replayLoad && replayLoad.level !== levels[index]?.level) clearReplayLoad();
    state.levelIndex = index;
    state.eventSequence = null;
    state.frameIndex = 0;
    state.actionId = null;
    const saved = savedView() || cachedSavedView();
    if (levelReplayEnabled) [...boardSavedViews.keys()].forEach(key => {if (key !== `${run.game_id}/${primaryLevel().level}`) boardSavedViews.delete(key);});
    if (saved && bindSavedSource) boardSavedViews.set(`${run.game_id}/${primaryLevel().level}`, saved);
    if (run.status === 'preview') run.target_level = currentLevel().level;
    renderRail();
    write('board-kicker', currentLevel().level === null ? 'LEVEL —' : `LEVEL ${String(currentLevel().level).padStart(2, '0')}`);
    write('board-title', run.status === 'manual' ? `关卡 ${currentLevel().level} · 人工试玩` : currentLevel().level === null ? '游戏画面 · 未记录关卡' : `关卡 ${currentLevel().level} · 游戏画面`);
    renderProgressContext();
    renderLevelEfficiency();
    renderWorld();
    renderProcess();
    renderReceipt();
    renderFrame();
    write('playback-announcement', currentLevel().level === null ? '没有可验证的关卡记录。' : `已选择关卡 ${currentLevel().level}，${timelineCount()} 帧。`);
    renderSessionControls();
  }

  function renderLevelEfficiency() {
    const authority = savedLevel(primaryLevel().level), retained = retainedSavedLevel(primaryLevel().level), saved = authority || retained;
    const efficiency = levelEfficiency(saved || currentLevel());
    const current = saved && levelSource().scope === 'current' && run.run_id !== (savedView() || cachedSavedView()).run.run_id;
    write('level-efficiency', state.mode === 'manual' ? '人工试玩不计 P7 分数' : `${authority ? '已保存 · ' : retained ? '历史已保存 · 最佳路线刷新中 · ' : ''}${efficiency.text}${current ? ` · 本次 ${array(primaryLevel().actions).length} 动作 · ${currentRunLevelLabel(primaryLevel())}` : ''}`);
    $('level-efficiency').classList.toggle('efficiency-low', state.mode !== 'manual' && efficiency.low);
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
    canvas.setAttribute('aria-label', `${columns} × ${rows} 网格，${frameLabel(frame)}${$('diff-toggle').checked && previous.length ? '，黄色方框为变化格回放标记，不属于游戏画面' : ''}`);
  }

  function renderClickMarker(canvas, frame, action, status = 'recorded') {
    let marker = $(canvas.id + '-click-marker');
    if (!marker) {
      marker = node('span', undefined, 'click-marker');
      marker.id = canvas.id + '-click-marker'; marker.setAttribute('aria-hidden', 'true');
      marker.append(node('span', undefined, 'click-marker-label'));
      canvas.parentElement.append(marker);
    }
    const grid = array(frame?.grid), point = object(action?.data);
    const visible = action?.name === 'ACTION6' && (status !== 'recorded' || $('highlight-toggle').checked) &&
      Number.isInteger(point.x) && Number.isInteger(point.y) && point.x >= 0 && point.y >= 0 &&
      point.y < grid.length && point.x < array(grid[0]).length;
    marker.hidden = !visible;
    if (!visible) { marker.dataset.markerKey = ''; return ''; }
    const bounds = canvas.getBoundingClientRect(), parent = canvas.parentElement.getBoundingClientRect();
    marker.style.left = `${bounds.left - parent.left + (point.x + 0.5) * bounds.width / grid[0].length}px`;
    marker.style.top = `${bounds.top - parent.top + (point.y + 0.5) * bounds.height / grid.length}px`;
    marker.dataset.action = action.name; marker.dataset.status = status;
    marker.classList.toggle('is-pending', status !== 'recorded');
    marker.classList.toggle('is-right', point.x >= grid[0].length / 2);
    marker.classList.toggle('is-bottom', point.y >= grid.length / 2);
    const label = `${status === 'recorded' ? '已记录点击' : status === 'pending' ? '点击等待确认' : '点击结果未确认'} (${point.x}, ${point.y})`;
    marker.firstElementChild.textContent = label;
    const key = `${run.run_id}:${action.id}:${point.x}:${point.y}:${status}`;
    if (marker.dataset.markerKey !== key) {
      marker.dataset.markerKey = key;
      marker.classList.remove('click-marker-pulse'); void marker.offsetWidth;
      marker.classList.add('click-marker-pulse');
    }
    canvas.setAttribute('aria-label', `${canvas.getAttribute('aria-label')}，${label}，点击位置标记不属于游戏画面`);
    return label;
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
  // Preserve historical prose as evidence in the cognition panel, without
  // interpreting it as a control label.
  const meaningEntries = entries => array(entries).filter(entry => entry && ['certain', 'undetermined', 'falsified'].includes(entry.status) && typeof entry.claim === 'string' && entry.claim);
  function recordedActionMeaning(name, cognition = selectedCognition()) {
    const label = ['final', 'observation', 'planning'].includes(cognition.scope) && validActionLabels(cognition)
      ? array(cognition.action_labels).find(entry => entry.action === name) : null;
    if (label) return { ...label, background: cognition.scope !== 'observation', provenance: cognition.provenance };
    if (name === 'RESET') return { label: '重置', purpose: '原生输入接口的重置动作；不代表当前关卡的具体机制。', confidence: 'certain', native: true };
    if (name === 'ACTION6') return { label: '点击', purpose: '原生输入接口的坐标点击动作；不代表当前关卡的具体机制。', confidence: 'certain', native: true };
    return { label: null, purpose: '', confidence: null };
  }

  function renderAvailableActions(frame, action) {
    const hasAvailability = Boolean(frame && Array.isArray(frame.available_actions));
    const available = [...new Set(array(frame && frame.available_actions).filter((name) => typeof name === 'string' && name))];
    const beforeIndex = action ? frameIndexForId(action.before_frame) : -1;
    const afterIndex = action ? frameIndexForId(action.after_frame) : -1;
    const linked = action && frame && (frame.id === action.after_frame || (beforeIndex >= 0 && afterIndex >= beforeIndex && state.frameIndex > beforeIndex && state.frameIndex <= afterIndex));
    const manual = state.mode === 'manual' && run.status === 'manual';
    const cognition = selectedCognition();
    const activeName = manual ? frame ? manualAtCurrent() ? state.manualView?.last_action?.action : action?.name : null : linked ? action.name : null;
    const recordedActions = (name) => actions().filter((entry) => entry.name === name).map((entry) => ({
      action: entry, index: frameIndexForId(entry.after_frame) >= 0 ? frameIndexForId(entry.after_frame) : frameIndexForId(entry.before_frame),
    })).filter((entry) => entry.index >= 0);
    const card = (name, availability, wrapper) => {
      const active = name === activeName;
      const armed = manual && name === state.pointerAction;
      const pending = manual && manualAtCurrent() && state.manualBusy && state.manualPending?.path === '/api/manual/action' && state.manualPending.body.action === name;
      if (!wrapper) {
        wrapper = node('div');
        wrapper.setAttribute('role', 'listitem');
        const item = node('button');
        item.type = 'button'; item.dataset.availableAction = name;
        item.append(node('strong', name, 'action-key-label'), node('span', '', 'action-key-meaning'), node('span', '', 'action-key-status'));
        item.addEventListener('click', () => {
          if (item.disabled) return;
          if (state.mode === 'manual' && run.status === 'manual') {
            if (!manualPlayable()) return;
            if (name === 'ACTION6') { state.pointerAction = 'ACTION6'; $('compare-toggle').checked = false; renderFrame(); renderSessionControls(); return; }
            sendManualAction(name); return;
          }
          if (state.mode !== 'replay') return;
          const recorded = recordedActions(name);
          const target = recorded.find((entry) => entry.index > state.frameIndex) || recorded[0];
          if (target) locateAction(target.action);
        });
        wrapper.append(item);
      }
      const item = wrapper.firstElementChild;
      item.className = `available-action${active ? ' is-current' : ''}${armed ? ' is-armed' : ''}${pending ? ' is-pending' : ''}`;
      item.disabled = manual ? !manualPlayable() || Boolean(availability) : state.mode === 'live' || Boolean(availability) || recordedActions(name).length === 0;
      item.title = manual ? name === 'ACTION6' ? '选择后点击游戏画面上的目标格' : '执行一次人工试玩动作' : state.mode === 'live' ? 'P7 运行中的动作观察；不发送游戏动作' : availability || (recordedActions(name).length ? '定位该动作的下一条回放记录' : '没有可定位的已录动作');
      if (active) item.setAttribute('aria-current', 'true'); else item.removeAttribute('aria-current');
      if (manual && name === 'ACTION6') item.setAttribute('aria-pressed', String(armed)); else item.removeAttribute('aria-pressed');
      if (pending) item.setAttribute('aria-busy', 'true'); else item.removeAttribute('aria-busy');
      const short = recordedActionMeaning(name, cognition);
      // Manual snapshots can omit actions while retaining a played journal.
      // Their empty action array is not evidence that a key was unused.
      const actionCount = manual ? null : actions().filter(entry => entry.name === name).length;
      const identified = short.confidence === 'certain' && Boolean(short.label || short.purpose);
      const meaning = short.label || (short.confidence === null ? '未记录' : '未识别');
      const status = short.native ? '固定含义' : identified ? '已识别' : short.confidence === 'hypothesis' ? '推测'
        : short.confidence === 'conflict' ? '有冲突' : !manual && !actionCount ? '本关未使用' : '';
      const explanation = short.purpose || (short.confidence === null ? '未记录动作含义' : '未识别');
      item.querySelector('.action-key-label').textContent = name;
      item.querySelector('.action-key-meaning').textContent = meaning;
      const statusNode = item.querySelector('.action-key-status');
      statusNode.textContent = status;
      statusNode.className = `action-key-status${short.native ? '' : ({ certain: ' status-active', hypothesis: ' status-warning', conflict: ' status-failed' })[short.confidence] || ''}`;
      if (actionCount !== null) item.title += `；本关已记录 ${actionCount} 次`;
      item.title += `；${short.confidence === 'hypothesis' ? '推测：' : ''}${explanation}`;
      if (short.confidence === null || short.confidence === 'unknown' || short.confidence === 'conflict') {
        const responses=[...new Set(actions().filter(entry=>entry.name===name).flatMap(entry=>array(entry.visual_observations)).filter(text=>typeof text==='string'))].slice(0,3);
        if (actionCount) item.title += responses.length ? `；动作响应：${responses.join('；')}` : '；响应见动作记录';
      }
      if (short.native) item.title += `；固定含义：${meaning}`;
      else if (short.label || short.purpose) item.title += `；P7 的动作理解（不等于机制已验证） · 来源 ${short.provenance?.run_id || levelSource().snapshot.run.run_id || '当前观察'} · 第 ${currentLevel().level} 关${short.background ? ' · 仅作规划背景，不表示当前帧当时已知' : ''}`;
      item.setAttribute('aria-label', `${name}，${meaning}${status ? '，'+status : ''}${actionCount !== null ? `，本关已记录 ${actionCount} 次` : ''}，${explanation}${short.background ? '，本关已保存记录，仅作规划背景' : ''}，${manual ? '人工试玩动作' : '定位已录动作'}${active ? `，${availability || '当前动作'}` : ''}${armed ? '，等待点击目标格' : ''}${pending ? '，等待响应' : ''}`);
      return wrapper;
    };
    const reconcile = (list, names, availability) => {
      const existing = new Map([...list.children].filter((child) => child.firstElementChild?.dataset.availableAction)
        .map((child) => [child.firstElementChild.dataset.availableAction, child]));
      [...list.children].forEach((child) => { if (!names.includes(child.firstElementChild?.dataset.availableAction)) child.remove(); });
      names.forEach((name, index) => {
        const wrapper = card(name, availability, existing.get(name));
        if (list.children[index] !== wrapper) list.insertBefore(wrapper, list.children[index] || null);
      });
    };
    const list = $('available-actions');
    if (available.length) reconcile(list, available);
    else if (!list.querySelector('.available-actions-empty')) list.replaceChildren(node('span', hasAvailability ? '当前帧没有可用动作。' : '未记录可用动作。', 'available-actions-empty'));
    else list.firstElementChild.textContent = hasAvailability ? '当前帧没有可用动作。' : '未记录可用动作。';
    const unavailable = $('unavailable-current-action');
    unavailable.hidden = !activeName || available.includes(activeName);
    reconcile(unavailable, unavailable.hidden ? [] : [activeName], hasAvailability ? '已执行／当前不可用' : '已执行／可用性未记录');
  }

  function renderFrame() {
    const count = timelineCount();
    const position = timelinePosition();
    const frame = currentFrame();
    const action = selectedAction();
    renderWorld();
    renderResearch();
    renderAvailableActions(frame, action);
    const before = action && frameById(action.before_frame);
    const after = action && frameById(action.after_frame);
    const comparisonRequested = $('compare-toggle').checked;
    const canCompare = Boolean(before && after);
    $('board-empty').hidden = Boolean(frame);
    $('board-empty').querySelector('h3').textContent = currentLevel().replay_unloaded || run.status === 'loading' ? '正在读取所选关卡记录' : currentLevel().status === 'preview-unavailable' ? '初始画面暂不可用' : run.status === 'preview' ? '正在读取关卡初始画面' : run.status === 'manual' && state.manualBusy ? '正在打开人工试玩' : run.status === 'manual' && state.manualError ? '人工试玩暂不可用' : '当前关卡没有可回放画面';
    $('board-empty').querySelector('p').textContent = currentLevel().replay_unloaded || run.status === 'loading' ? '读取当前关卡的画面与认知；其他关卡将在选择后加载。' : string(run.status, '').startsWith('preview') ? '尚未启动 P7；可启动求解，或明确切换人工试玩。' : run.status === 'manual' ? (state.manualBusy ? '正在读取所选游戏的初始观察，尚未启动 P7。' : state.manualError ? '试玩操作未确认；可重新选择游戏开启新的试玩。' : '该关卡尚无真实观察记录；人工试玩仅展示当前关卡的真实画面。') : '没有记录帧，无法恢复该关卡的画面。';
    if (currentLevel().frame_page && !frame) {
      const failed=framePageErrors.has(framePageKey(levelSource(),Math.floor(position/32)*32));
      $('board-empty').querySelector('h3').textContent=failed ? '画面读取失败' : `正在读取第 ${position+1} 帧`;
      $('board-empty').querySelector('p').textContent=failed ? '过关记录和认知已保留；点击下一帧或时间轴重试读取。' : '只读取当前画面页，过关记录和认知保持显示。';
    }
    $('single-board').hidden = !frame || (comparisonRequested && canCompare);
    $('comparison-board').hidden = !frame || !comparisonRequested || !canCompare;
    $('frame-slider').max = String(Math.max(0, count - 1));
    $('frame-slider').setAttribute('aria-label', state.mode === 'manual' ? '选择试玩记录帧' : '选择回放帧');
    $('frame-slider').value = String(position);
    $('frame-slider').disabled = count < 2;
    write('frame-counter', `${count ? position + 1 : 0} / ${count}`);
    write('frame-state', frame ? frameState(frame.state) : '无帧记录');
    const manualEntry = manualHistoryActive() ? state.manualHistory.entries[position] : null;
    const source = levelSource();
    const sourceRun = array(overviewGame(run.game_id)?.runs).find(entry => entry.run_id === source.snapshot.run.run_id);
    const offline = ['offline', 'offline-replay'].includes(source.snapshot.run.execution_mode || sourceRun?.execution_mode);
    $('single-board').dataset.sourceScope = source.scope;
    $('single-board').dataset.sourceRunId = source.snapshot.run.run_id || '';
    write('frame-caption', source.scope === 'preview' && frame ? '关卡初始预览 · 尚未开始 · 只读' : run.status === 'manual' && frame ? `${manualAtCurrent() ? '人工试玩当前观察' : '人工试玩历史观察'}${manualEntry ? ` · 观察 ${manualEntry.version} · 回合 ${manualEntry.episode_id}` : ''} · 尚未启动 P7` : frame ? `${source.scope === 'saved' ? `已保存 · ${source.snapshot.run.run_id} · ` : offline ? '' : replayUnsealed(source.snapshot) ? '本次记录 · LIVE · ' : '本次记录 · '}${offline ? '离线 SDK 路线验证 · ' : ''}${string(frame.id)}${frame.timestamp ? ` · ${frame.timestamp}` : ''}` : '当前关卡无帧记录');
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
    write('comparison-note', comparisonRequested ? (canCompare ? '对照显示所选动作的起始帧与结算帧' : action ? currentLevel().frame_page ? '正在读取动作前后画面页；读取失败时可重新定位动作重试。' : '前后帧缺链，无法对照' : '选择一个有前后帧的动作以对照') : '');
    const overlayNotes = [];
    if ($('diff-toggle').checked) overlayNotes.push('黄色方框为回放标记，不属于游戏画面');
    renderPalette(comparisonRequested && canCompare ? [before, after] : [frame]);
    if (frame) draw($('board-canvas'), frame, before, action);
    const pending = state.mode === 'manual' && manualAtCurrent() &&
      state.manualPending?.path === '/api/manual/action' && state.manualPending.body.session_id === state.manualView?.session_id
      ? state.manualPending : null;
    const markerAction = pending ? {id: pending.body.command_id, name: pending.body.action, data: pending.body.data} : action;
    const clickLabel = renderClickMarker($('board-canvas'), frame, markerAction, pending ? state.manualBusy ? 'pending' : 'unconfirmed' : 'recorded');
    if (clickLabel) overlayNotes.push(`${clickLabel} · 圆圈与十字为点击位置标记，不属于游戏画面`);
    write('overlay-note', overlayNotes.join('；'));
    $('overlay-note').hidden = overlayNotes.length === 0;
    if (comparisonRequested && canCompare) {
      draw($('before-canvas'), before, null, action);
      draw($('after-canvas'), after, before, action);
      renderClickMarker($('before-canvas'), before, action);
      renderClickMarker($('after-canvas'), after, action);
      write('before-label', `动作前 · ${string(before.id)}`);
      write('after-label', `动作后 · ${string(after.id)}`);
    }
    $('previous-frame').disabled = !count || position <= 0;
    $('next-frame').disabled = !count || position >= count - 1;
    $('play-toggle').disabled = !['replay', 'manual'].includes(state.mode) || count < 2;
    $('play-speed').disabled = count < 2;
    $('previous-action').disabled = actionTarget(-1) === null;
    $('next-action').disabled = actionTarget(1) === null;
    renderManualHistory();
    document.querySelectorAll('[data-action-id]').forEach((card) => card.classList.toggle('is-selected', card.dataset.actionId === state.actionId));
    document.querySelectorAll('[data-decision-id]').forEach((card) => card.classList.toggle('is-selected', Boolean(decision) && card.dataset.decisionId === decision));
  }

  async function ensureFramePage(index,{retry=false}={}) {
    const source=levelSource(),level=source.level;
    if (!level.frame_page || index < 0 || index >= level.frame_count || frameAt(index)) return;
    const start=Math.floor(index/32)*32,key=framePageKey(source,start);
    if (framePageErrors.has(key) && !retry) return;
    if (retry) framePageErrors.delete(key);
    while (!framePageRequests.has(key) && framePageRequests.size >= 2) {
      await Promise.race([...framePageRequests.values()]);
      if (levelSource().key !== source.key || currentLevel().frame_page?.source_token !== level.frame_page.source_token) return;
    }
    if (!framePageRequests.has(key)) {
      const token=level.frame_page.source_token,runId=source.snapshot.run.run_id,revision=source.snapshot.replay_revision;
      const readPage = source.snapshot.offline_frames === true
        ? Promise.resolve().then(() => {
          const entry=$(`console-frame-page-${level.level}-${start}`);
          if (!entry || entry.type !== 'application/json') throw new Error('invalid-response');
          return JSON.parse(entry.textContent);
        })
        : request(`/api/replay/${encodeURIComponent(runId)}/levels/${level.level}/${revision}/frames/${token}/${start}/32`);
      const pending=readPage.then(page=>{
        if (!isRecord(page) || page.schema !== 'asterion.arc-agi3-p7-replay-frame-page/v1' || page.run_id !== runId || page.level !== level.level ||
            page.replay_revision !== revision || page.source_token !== token || page.frame_count !== level.frame_count || page.start !== start ||
            !Array.isArray(page.frames) || page.frames.length !== Math.min(32,level.frame_count-start) ||
            !validSnapshot({schema:'asterion.arc-agi3-p7-console/v2',run:source.snapshot.run,levels:[{...level,frame_page:{...level.frame_page,start},frames:page.frames}]})) throw new Error('invalid-response');
        framePages.set(key,page.frames);
        while(framePages.size>4)framePages.delete(framePages.keys().next().value);
      }).catch(()=>{framePageErrors.add(key);while(framePageErrors.size>16)framePageErrors.delete(framePageErrors.values().next().value);}).finally(()=>framePageRequests.delete(key));
      framePageRequests.set(key,pending);
    }
    await framePageRequests.get(key);
    if (levelSource().key === source.key && currentLevel().frame_page?.source_token === level.frame_page.source_token &&
        (state.frameIndex === index || ($('compare-toggle').checked && [selectedAction()?.before_frame,selectedAction()?.after_frame].some(id=>frameIndexForId(id)===index)))) {
      renderFrame();renderSessionControls();
    }
  }

  function setFrame(index, actionId) {
    if (manualHistoryActive()) { setManualFrame(index, actionId); return; }
    if (!timelineCount()) return;
    state.frameIndex = Math.max(0, Math.min(timelineCount() - 1, index));
    state.eventSequence = null;
    if (actionId !== undefined) state.actionId = actionId;
    else {
      const linked = actions().filter((action) => {
        const before = frameIndexForId(action.before_frame);
        const after = frameIndexForId(action.after_frame);
        return after === state.frameIndex || (before >= 0 && after >= before && state.frameIndex > before && state.frameIndex <= after);
      });
      state.actionId = linked.length ? linked[linked.length - 1].id : null;
    }
    renderFrame();
    renderSessionControls();
    if (!currentFrame()) ensureFramePage(state.frameIndex,{retry:true});
    if ($('compare-toggle').checked) [selectedAction()?.before_frame,selectedAction()?.after_frame].forEach(id=>{const position=frameIndexForId(id);if(position>=0 && !frameAt(position))ensureFramePage(position);});
  }

  function seekFrame(index, actionId) {
    if (['live', 'replay'].includes(state.mode)) state.replayFollow = false;
    setFrame(index, actionId);
    if (['live', 'replay'].includes(state.mode) && processEvents().length) { state.eventSequence = cursorSequence() ?? 0; renderFrame(); renderSessionControls(); }
  }

  function locateAction(action) {
    pause();
    if (manualHistoryActive()) { const index = state.manualHistory.entries.findIndex((entry) => entry.frame.id === action.after_frame); if (index >= 0) setManualFrame(index, action.id); return; }
    const target = frameIndexForId(action.after_frame);
    const fallback = frameIndexForId(action.before_frame);
    if (target >= 0 || fallback >= 0) seekFrame(target >= 0 ? target : fallback, action.id);
    else { state.actionId = action.id; renderFrame(); }
  }

  function actionTarget(direction) {
    if (manualHistoryActive()) {
      const linked = state.manualHistory.entries.map((entry, index) => ({ action: entry.action, index })).filter((item) => item.action);
      const selected = linked.findIndex((item) => item.action.id === state.actionId);
      if (selected >= 0) return linked[selected + direction] || null;
      return direction > 0 ? linked.find((item) => item.index > timelinePosition()) || null : linked.filter((item) => item.index < timelinePosition()).at(-1) || null;
    }
    const linked = actions().map((action) => ({ action, index: frameIndexForId(action.after_frame) })).filter((item) => item.index >= 0);
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
    if (!['replay', 'manual'].includes(state.mode) || timelineCount() < 2) return;
    if (timelinePosition() >= timelineCount() - 1) setFrame(0);
    pause();
    write('play-toggle', '暂停');
    $('play-toggle').setAttribute('aria-pressed', 'true');
    // Canvas frames switch immediately, including under prefers-reduced-motion.
    state.timer = window.setInterval(() => {
      if (!currentFrame()) {ensureFramePage(state.frameIndex);return;}
      if (timelinePosition() >= timelineCount() - 1) { pause(); return; }
      setFrame(timelinePosition() + 1);
      if (timelinePosition() >= timelineCount() - 1) pause();
    }, 650 / Number($('play-speed').value));
  }

  function observationCognition() {
    const timeline = array(currentLevel().cognition_timeline);
    const frameIndexes = new Map(frames().map((frame, index) => [frame.id, index]));
    return timeline.filter((entry) => entry.scope === 'observation').map((entry) => ({ entry, index: currentLevel().frame_page ? frameIndexForId(entry.frame_id) : frameIndexes.get(entry.frame_id) ?? -1 }))
      .filter(({ entry, index }) => index >= 0 && index <= state.frameIndex && (state.eventSequence === null || !Number.isInteger(entry.event_sequence) || entry.event_sequence <= state.eventSequence))
      .sort((a, b) => a.index - b.index || number(a.entry.event_sequence) - number(b.entry.event_sequence)).pop()?.entry || null;
  }

  function selectedCognition() {
    const timeline = array(currentLevel().cognition_timeline);
    const revision = timeline.length ? null : researchEvents().filter((event) => event.kind === 'model_revision').at(-1);
    const aligned = timeline.length ? observationCognition() : revision ? { scope: 'observation', frame_id: revision.frame_id,
      source_action_sequence: revision.source_action_sequence, cognition_revision: revision.event_sequence, event_sequence: revision.event_sequence,
      stable_description: revision.payload.description_zh, cognition_narrative_zh: revision.payload.correction_summary, origin: 'actor', provenance: revision.provenance,
      action_labels: revision.payload.action_labels } : null;
    const saved = object(currentLevel().cognition);
    return aligned || (timeline.length && saved.scope === 'observation' ? { ...saved, scope: 'planning' }
      : state.eventSequence !== null ? {} : saved);
  }

  function renderWorld() {
    const cognition = selectedCognition();
    const guide = $('world-guide');
    const facts = $('world-facts');
    guide.replaceChildren(); facts.replaceChildren();
    if (!['final', 'observation', 'planning'].includes(cognition.scope)) {
      write('cognition-scope', run.status === 'manual' ? '人工试玩不生成 P7 认知。' : '当前关卡没有身份匹配的稳定认知。');
      guide.append(node('p', run.status === 'manual' ? '人工试玩不生成 P7 认知与决策。启动 P7 后会开始新的观察与探索。' : '尚未确定。没有认知记录可供展示。', 'guide-empty'));
      return;
    }
    const provenance = cognition.provenance ? ` · 来源运行 ${cognition.provenance.run_id} · 原事件 ${cognition.provenance.event_sequence}` : '';
    const scopeText = cognition.scope === 'observation'
      ? `观察来源 ${string(cognition.frame_id)} · 动作序号 ${number(cognition.source_action_sequence)} · 认知版本 ${number(cognition.cognition_revision)}${provenance}。当前帧仅使用已关联观察的认知。`
      : cognition.scope === 'planning' ? `本关保存的认知，形成于第 ${number(cognition.source_action_sequence)} 步${provenance}。仅作规划背景，不表示此帧当时已知。`
        : '运行结束时的最终认知快照。未与历史帧或动作建立时间对齐，不能视为该帧当时已有的知识。';
    write('cognition-scope', scopeText + (cognition.origin === 'actor' ? ' 这是模型记录的玩法理解与假说，不认证规则或授权动作。' : ''));
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
    update.append(node('h3', '最近一次稳定更新'), node('p', ['observation', 'planning'].includes(cognition.scope) ? string(cognition.cognition_narrative_zh, '该观察未记录更新说明。') : '最终快照；具体更新时间未与回放帧对齐。'));
    guide.append(update);
  }

  function setEvent(index) {
    const event = processEvents()[index];
    if (!event) return;
    pause();
    if (state.mode === 'replay') state.replayFollow = false;
    const frameIndex = frameIndexForId(event.frame_id);
    setFrame(frameIndex);
    state.eventSequence = event.event_sequence;
    renderFrame(); renderSessionControls();
  }

  function renderResearch() {
    const events = processEvents(), cursor = cursorSequence();
    $('event-timeline').hidden = !events.length;
    $('event-slider').max = String(Math.max(0, events.length - 1));
    $('event-slider').value = String(Math.max(0, events.findIndex((event) => event.event_sequence === cursor)));
    $('event-slider').disabled = events.length < 2;
    write('event-counter', cursor === null || cursor === 0 ? '' : `事件 ${cursor}`);
    const visible = researchEvents();
    $('research-workspace').hidden = !visible.length;
    const task = visible.filter((event) => event.kind === 'compute_task').at(-1);
    const revision = visible.filter((event) => event.kind === 'model_revision').at(-1);
    write('research-revision', revision ? `模型 ${revision.payload.revision}` : '模型版本未关联');
    const current = $('research-task'); current.replaceChildren();
    if (task) {
      current.append(node('p', `目标：${task.payload.goal || '尚未声明'}`));
      if (array(task.payload.obstacles).length) current.append(node('p', `障碍：${task.payload.obstacles.join('；')}`));
      if (task.payload.question) current.append(node('p', `关键未知：${task.payload.question}`));
    }
    const panel = $('research-events'); panel.replaceChildren();
    const kinds = { compute_task: '研究任务', model_revision: '模型修订', plan: '候选计划', feedback: '真实反馈', run_control: '运行控制' };
    const statuses = { declared: '已声明', started: '已开始', completed: '已完成', failed: '失败', interrupted: '已中断', proposed: '待执行', executing: '执行中', stopped: '已停止', pause_requested: '暂停请求待确认', paused: '已暂停', running: '运行中', stop_requested: '结束请求待确认', stopping: '清理中', cleanup_failed: '清理未确认' };
    const origins = { actor: '模型声明', calculation: '计算结果', environment: '真实观察', operator: '运行记录' };
    visible.forEach((event) => {
      const payload = event.payload, item = node('details', undefined, 'research-event');
      item.dataset.eventSequence = String(event.event_sequence);
      item.append(node('summary', `事件 ${event.event_sequence} · ${kinds[event.kind]} · ${statuses[payload.status || payload.state] || ''} · ${origins[payload.origin] || ''}`));
      const add = (label, value) => { if (typeof value === 'string' && value) item.append(node('p', `${label}：${value}`)); };
      if (event.kind === 'compute_task') {
        add('计算目的', payload.operation); add('结果', payload.summary);
        if (Number.isFinite(payload.elapsed_ms)) item.append(node('p', `实际用时 ${payload.elapsed_ms} ms`));
        if (Number.isFinite(payload.completed_units)) item.append(node('p', `已完成工作量 ${payload.completed_units}`));
        if (payload.status === 'started' && !visible.some((other) => other.event_sequence > event.event_sequence && other.kind === 'compute_task' && other.payload.task_id === payload.task_id && ['completed', 'failed', 'interrupted'].includes(other.payload.status))) item.append(node('p', '尚无结束记录；计算完成不代表关卡完成。'));
      } else if (event.kind === 'model_revision') {
        add('当前状态', payload.state_summary); add('覆盖', payload.coverage_summary); add('检验', payload.validation_summary); add('修订', payload.correction_summary);
        array(payload.unknowns).forEach((unknown) => add('未知', unknown));
      } else if (event.kind === 'plan') {
        add('计划', payload.plan_id); add('目标', payload.goal);
        array(payload.assumptions).forEach((assumption) => add('假设', assumption));
        item.append(node('p', `候选动作：${array(payload.actions).map((action) => action.name + (action.name === 'ACTION6' ? `(${action.data.x},${action.data.y})` : '')).join(' → ')}`));
        item.append(node('p', `已执行 ${payload.applied_count} / ${array(payload.actions).length}；未执行 ${Math.max(0, array(payload.actions).length - payload.applied_count)}`));
        add('停止原因', payload.stop_reason);
      } else if (event.kind === 'feedback') {
        add('模型预期', payload.expected_summary); add('实际结果', payload.actual_summary); add('差异类别', payload.mismatch_kind);
        item.append(node('p', `未执行后缀 ${payload.unexecuted_count}`));
        if (payload.counterexample_sequence !== null) item.append(node('p', `反例观察 ${payload.counterexample_sequence}`));
      } else add('原因', payload.reason);
      add('模型版本', payload.workspace_revision);
      const link = node('button', '定位此事件', 'event-link'); link.type = 'button';
      link.addEventListener('click', () => setEvent(events.findIndex((candidate) => candidate.event_sequence === event.event_sequence)));
      item.append(link); panel.append(item);
    });
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
    array(levelSource().snapshot.decisions).forEach((decision) => { if (!decisionMap.has(decision.id)) decisionMap.set(decision.id, decision); });
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
      if (run.status !== 'manual') addMetadata(card, [action.trace_sequence != null ? `轨迹序号 ${action.trace_sequence}` : '轨迹关联缺失', action.decision_id ? `P7 关联 ${action.decision_id}` : 'P7 轮次关联缺失']);
      if (!before || !after) card.append(node('p', '动作前后帧不完整，无法建立完整的结果对照。', 'event-note'));
      const evidence = node('div', undefined, 'action-evidence');
      renderActionEvidence(evidence, action); card.append(evidence);
      actionsPanel.append(card);
    });
    timeline.forEach((entry) => {
      const card = node('article', undefined, 'event-card timeline-cognition');
      card.append(node('h3', `${entry.origin === 'actor' ? '模型认知' : '观察认知'} · 版本 ${number(entry.cognition_revision)}`));
      addMetadata(card, [`来源帧 ${string(entry.frame_id)}`, `动作序号 ${number(entry.source_action_sequence)}`, entry.action_id ? `关联动作 ${entry.action_id}` : '初始观察',
        entry.provenance ? `来源运行 ${entry.provenance.run_id} · 原事件 ${entry.provenance.event_sequence}` : null]);
      if (entry.origin === 'actor') card.append(node('p', '模型记录的玩法理解与假说，仅作规划背景，不认证规则或授权动作。', 'process-note'));
      const button = node('button', '定位观察', 'event-link'); button.type = 'button';
      const index = frameIndexForId(entry.frame_id); button.disabled = index < 0;
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
    const labels = { completed_level_count: '已完成关卡', primitive_action_count: '原子动作', partial_game_score: '游戏综合分（局部）', scope: '回执范围', promotion: '证明边界' };
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
  $('frame-slider').addEventListener('input', () => { pause(); seekFrame(Number($('frame-slider').value)); });
  $('previous-frame').addEventListener('click', () => { pause(); seekFrame(timelinePosition() - 1); });
  $('next-frame').addEventListener('click', () => { pause(); seekFrame(timelinePosition() + 1); });
  $('manual-return-current').addEventListener('click', () => { pause(); if (manualHistoryActive()) setManualFrame(state.manualHistory.entries.length - 1); });
  $('play-toggle').addEventListener('click', () => state.timer === null ? play() : pause());
  $('play-speed').addEventListener('change', () => { if (state.timer !== null) play(); });
  ['diff-toggle', 'highlight-toggle', 'compare-toggle'].forEach((id) => $(id).addEventListener('change', () => {
    if (id === 'compare-toggle' && $('compare-toggle').checked && state.pointerAction) {
      state.pointerAction = null;
      renderSessionControls();
    }
    renderFrame();
    if (id === 'compare-toggle' && $('compare-toggle').checked) [selectedAction()?.before_frame,selectedAction()?.after_frame].forEach(frameId=>{const position=frameIndexForId(frameId);if(position>=0 && !frameAt(position))ensureFramePage(position,{retry:true});});
  }));
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
      event.preventDefault(); pause(); seekFrame(state.frameIndex + (event.key === 'ArrowRight' ? 1 : -1));
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
  window.addEventListener('resize', renderFrame);
  function replaceSnapshot(next, { follow = state.mode === 'live' && state.replayFollow, manualPosition = null } = {}) {
    if (!validatedReplayViews.has(next) && !validSnapshot(next)) throw new Error('invalid-response');
    follow = follow && state.eventSequence === null;
    const previousEvent = state.eventSequence;
    const previousEventRecord = processEvents().find(event=>event.event_sequence===previousEvent);
    const previous = { snapshot, run, recordedLevels, levelCount, levels,
      levelIndex: state.levelIndex, frameIndex: state.frameIndex, actionId: state.actionId };
    const previousSource = levelSource();
    const previousGame = run.game_id, previousLevel = currentLevel().level, previousFrame = currentFrame()?.id, previousAction = state.actionId;
    // Derive the complete next view before changing the currently accepted state.
    const nextRun = object(next.run), nextRecordedLevels = array(next.levels);
    const nextCount = Math.max(0, number(nextRun.win_levels), ...nextRecordedLevels.map((level) => number(level.level)));
    const nextLevels = Array.from({ length: nextCount }, (_, index) => nextRecordedLevels.find((level) => level.level === index + 1) || {
      level: index + 1, status: 'not_run', frames: [], actions: [], decisions: [], cognition: { scope: 'unavailable' }, receipt: null,
    });
    let index = nextLevels.findIndex((level) => level.level === previousLevel);
    if (follow) index = nextLevels.map((level, i) => levelFrameCount(level) > 0 ? i : -1).filter((i) => i >= 0).pop() ?? 0;
    else if (previousGame !== nextRun.game_id || index < 0) index = Math.max(0, nextLevels.findIndex((level) => levelFrameCount(level) > 0));
    try {
      snapshot = next; run = nextRun; recordedLevels = nextRecordedLevels; levelCount = nextCount; levels = nextLevels;
      const nextSource = levelSource(nextLevels[index] || emptyLevel);
      const sameSource = nextSource.scope === previousSource.scope && nextSource.snapshot.run.game_id === previousSource.snapshot.run.game_id &&
        nextSource.snapshot.run.run_id === previousSource.snapshot.run.run_id && nextSource.level.level === previousSource.level.level;
      const preserve = !follow && sameSource;
      const preservePlayback = state.timer !== null && state.mode === 'replay' && sameSource && index === state.levelIndex;
      renderRunHeader(); selectLevel(index, { pausePlayback: !preservePlayback, bindSavedSource:false, retireLoad:false });
      const historical = preserve ? previousFrame ? frameIndexForId(previousFrame) : currentLevel().frame_page && previous.frameIndex < timelineCount() ? previous.frameIndex : -1 : -1;
      if (manualPosition !== null) setManualFrame(manualPosition);
      else setFrame(follow ? timelineCount() - 1 : historical >= 0 ? historical : 0,
        preserve && actions().some((action) => action.id === previousAction) ? previousAction : undefined);
      if (preserve && (previousEvent === 0 || processEvents().some((event) => event.event_sequence === previousEvent &&
        (!levelReplayEnabled || event.kind===previousEventRecord?.kind && event.frame_id===previousEventRecord?.frame_id &&
          JSON.stringify(event.provenance)===JSON.stringify(previousEventRecord?.provenance) && JSON.stringify(event.payload)===JSON.stringify(previousEventRecord?.payload))))) { state.eventSequence = previousEvent; renderFrame(); }
    } catch (_) {
      snapshot = previous.snapshot; run = previous.run; recordedLevels = previous.recordedLevels;
      levelCount = previous.levelCount; levels = previous.levels;
      state.levelIndex = previous.levelIndex; state.frameIndex = previous.frameIndex; state.actionId = previous.actionId; state.eventSequence = previousEvent;
      // Restore the old rendered frame if the failing canvas/DOM operation was transient.
      try {
        renderRunHeader(); selectLevel(previous.levelIndex); setFrame(previous.frameIndex, previous.actionId);
      } catch (_) { /* Persistent rendering failure must not commit data or revision. */ }
      state.levelIndex = previous.levelIndex; state.frameIndex = previous.frameIndex; state.actionId = previous.actionId; state.eventSequence = previousEvent;
      throw new Error('invalid-response');
    }
    window.__ASTERION_STATE__ = snapshot;
  }

  const sessionLabels = { idle: '就绪 · 尚未启动', starting: '启动中', running: 'P7 运行中', pause_requested: '暂停已请求 · 等待真实边界', paused: '已暂停 · 期限继续计时', resume_requested: '继续已请求 · 等待确认', stopping: '结束中 · 等待清理确认', completed: '运行完成 · 有完成证据', incomplete: '运行未完成', cancelled: '运行已结束', 'timed-out': '运行超时', failed: '运行失败', 'cleanup-unconfirmed': '清理未确认 · 无法启动新运行' };
  const liveAtCurrent = () => state.mode === 'live' && state.eventSequence === null && run.run_id === state.liveView?.run_id &&
    state.levelIndex === levels.map((level, index) => array(level.frames).length ? index : -1).filter((index) => index >= 0).at(-1) && state.frameIndex === timelineCount() - 1;
  const activeSession = () => ['starting', 'running', 'pause_requested', 'paused', 'resume_requested', 'stopping', 'cleanup-unconfirmed'].includes(state.liveView?.state);
  const manualUnsaved = () => state.manualView?.state === 'ready' && state.manualView.save_status === 'failed';
  const manualSelectionLocked = () => manualUnsaved() || !liveConfig || !state.liveView || activeSession() || state.manualBusy || Boolean(state.manualPending) || state.commandBusy || Boolean(state.pendingCommand);
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
    $('console-mode').disabled = !liveConfig || Boolean(state.manualPending && ['/api/manual/action', '/api/manual/restart'].includes(state.manualPending.path));
    $('live-controls').hidden = !liveConfig;
    $('replay-controls').hidden = !liveConfig || state.mode !== 'replay';
    $('replay-transport').hidden = state.mode !== 'replay' && !manual;
    $('header-mode').textContent = liveConfig ? (manual ? '人工试玩' : live ? 'P7 实时运行' : '回放记录') : '离线回放';
    write('actions-mode', manual ? '人工试玩动作' : live ? '运行观察' : '只读回放');
    write('actions-note', manual ? !manualAtCurrent() ? '历史画面只读；返回当前画面后可操作' : state.pointerAction === 'ACTION6' ? '点击画面目标格执行 ACTION6' : '执行可用动作；含义见按键标注' : live ? '动作由 P7 执行，此处只观察' : '点击定位已录动作');
    renderManualFeedback();
    const saveStatus = state.manualView?.save_status;
    $('manual-save-status').hidden = !manual || !saveStatus || saveStatus === 'disabled';
    write('manual-save-status', saveStatus === 'failed' ? '保存失败 · 当前进度尚未保存' : saveStatus === 'saved' ? `自动保存${state.manualView.restored ? ' · 已恢复' : ''}` : saveStatus === 'pending' ? '已保留该关原存档；继续操作后更新' : '');
    write('manual-note', liveConfig ? manual ? '点击左侧关卡可直接试玩任意关卡；直接选择不代表已过关。P7 默认继续最高进度保存路线；从头开始需明确选择。画面获得焦点时可按 1–7 选择 ACTION 按键。' : '人工试玩独立于 P7；P7 运行时动作面板仅展示观察。' : '离线回放不执行游戏动作。');
    document.querySelectorAll('.level-button').forEach((button) => {
      button.disabled = manual && manualSelectionLocked();
      const saved = manual && state.manualView?.game_id === run.game_id && array(state.manualView.saved_levels).includes(Number(button.id.slice(6)));
      const badge = button.querySelector('.level-saved-badge');
      if (saved && !badge) button.querySelector('.level-item-heading').append(node('span', '已保存', 'level-saved-badge'));
      else if (!saved && badge) badge.remove();
      const label = button.getAttribute('aria-label').replace('，已保存，可继续', '');
      button.setAttribute('aria-label', saved ? `${label}，已保存，可继续` : label);
    });
    const selectedGame = overviewGame($('game-select').value);
    $('run-start').textContent = selectedGame?.status === 'completed' ? '已全部通关' : selectedGame?.resume_run_id ? '继续 P7' : selectedGame?.completed_levels > 0 ? '存档不可接续' : '启动 P7';
    $('run-start').disabled = startLocked() || !selectedGame || selectedGame.status === 'completed' || selectedGame.status === 'running' || (selectedGame.completed_levels > 0 && !selectedGame.resume_run_id);
    $('run-fresh').disabled = startLocked() || !selectedGame || selectedGame.status === 'running';
    $('replay-follow').hidden = state.mode !== 'replay' || !state.replayRun || state.replayFollow;
    renderOverviewControls();
    $('game-select').disabled = manualUnsaved() || !state.liveView || activeSession() || state.manualBusy || Boolean(state.manualPending) || state.commandBusy || Boolean(state.pendingCommand);
    $('run-stop').disabled = !state.liveView?.session_id || !['starting', 'running', 'pause_requested', 'paused', 'resume_requested'].includes(state.liveView?.state) || state.commandBusy || Boolean(state.pendingCommand);
    $('run-pause').disabled = !liveAtCurrent() || state.liveView?.state !== 'running' || state.commandBusy || Boolean(state.pendingCommand);
    $('event-return-current').hidden = state.mode !== 'live' || liveAtCurrent();
    $('run-resume').disabled = !liveAtCurrent() || state.liveView?.state !== 'paused' || state.commandBusy || Boolean(state.pendingCommand);
    $('manual-close').hidden = !manual;
    $('manual-close').textContent = state.manualView?.state === 'ready' && !state.manualError ? '结束试玩' : '重新打开试玩';
    $('manual-close').disabled = !liveConfig || !state.liveView || activeSession() || state.manualBusy || Boolean(state.manualPending) || state.commandBusy || Boolean(state.pendingCommand) || !$('game-select').value;
    $('manual-restart').hidden = !manual;
    $('manual-restart').disabled = !manualRestartable();
    $('retry-command').hidden = (!state.pendingCommand && !(manual && (state.manualPending || state.manualSaveRetry))) || state.commandBusy || state.manualBusy;
    $('retry-command').textContent = !state.pendingCommand && !state.manualPending && state.manualSaveRetry ? '重试保存' : '重试原请求';
    $('replay-load').disabled = !$('replay-run').value;
    write('session-id', state.liveView?.session_id ? `会话 ${state.liveView.session_id}` : '');
    enforceCloudReadOnly();
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
      if (state.mode !== 'replay' && array(liveConfig?.games).some((game) => game.game_id === view.game_id)) { $('game-select').value = view.game_id; renderRunChoices(); }
    }
    if (!preserveManual && !view.snapshot && state.mode === 'live' && (run.run_id !== view.run_id || run.game_id !== view.game_id || (previous && previous.session_id !== view.session_id))) replaceSnapshot(snapshotForView(view));
    if (view.snapshot && (state.mode === 'live' || (!state.replayRun && run.run_id === view.run_id)) &&
        !preserveManual && (!previous || previous.revision !== view.revision || previous.run_id !== view.run_id || displayingManual)) replaceSnapshot(view.snapshot);
    // Publish the accepted session/revision only after snapshot replacement rendered successfully.
    state.liveView = view;
    if (view.snapshot && (!previous || previous.run_id !== view.run_id ||
        number(view.snapshot.run.completed_level_count) > number(previous.snapshot?.run.completed_level_count))) loadOverview();
    if (manualProjection && !active && view.manual && state.mode === 'manual' && !state.manualBusy && !state.manualPending && view.manual.game_id === $('game-select').value) acceptManual(view.manual);
    if (state.mode !== 'replay' || !state.replayRun) write('service-status', `${sessionLabels[view.state]}${view.cleanup_confirmed ? ' · 清理已确认' : ''}`);
    if (state.mode === 'manual') renderManualStatus();
    renderSessionControls();
  }

  async function request(path, command = null) {
    if (command) throw new Error('request-rejected');
    // Fixed relative routes and the injected same-origin token are the only request authority.
    let result;
    try {
      result = await window.fetch(path, {
        method: command ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
        ...(!command && window.AbortSignal?.timeout ? { signal: window.AbortSignal.timeout(10000) } : {}),
        headers: {},
        ...(command ? { body: JSON.stringify(command) } : {}),
      });
    } catch (_) { throw new Error('disconnected'); }
    if (!result.ok) {
      const error = new Error('request-rejected');
      if (path === '/api/manual/restart') {
        try {
          const value = await result.json();
          // Only public, permanent rejection codes release the exact retry request.
          error.refreshManual = isRecord(value) && ['session-mismatch', 'observation-stale', 'session-busy', 'manual-expired',
            'command-invalid', 'command-conflict', 'command-limit', 'game-unavailable', 'level-unavailable'].includes(value.error);
        } catch (_) { /* An unknown rejection leaves the original request retryable. */ }
      }
      error.status = result.status;
      throw error;
    }
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
    state.manualFeedback = null;
    state.pointerAction = null;
  }

  async function openManual(level = 1) {
    if (state.mode === 'replay' || manualSelectionLocked()) return;
    const gameId = $('game-select').value;
    const game = array(liveConfig.games).find((entry) => entry.game_id === gameId);
    if (!game || !validChoice({ game_id: gameId, level })) return;
    state.manualChoice = { game_id: gameId, level };
    invalidateManual(); state.manualView = null; state.manualHistory = null; state.manualSaveRetry = null; state.mode = 'manual';
    replaceSnapshot({ schema: 'asterion.arc-agi3-p7-console/v1', generated_at: null,
      run: { run_id: null, game_id: gameId, status: 'manual', win_levels: game.win_levels ?? null, completed_level_count: 0, primitive_action_count: 0 },
      levels: [], decisions: [], warnings: [] });
    selectLevel(level - 1);
    await sendManualCommand({ path: '/api/manual/open', body: { game_id: gameId, level, command_id: window.crypto.randomUUID() } });
  }

  const manualLabels = { idle: '尚未打开人工试玩', ready: '人工试玩 · 可操作', closed: '人工试玩已结束', expired: '人工试玩已过期', uncertain: '人工试玩结果未确认 · 已停止操作' };
  function validManualHistory(view) {
    if (view.history === undefined) return true;
    if (!Array.isArray(view.history) || view.history.length > 1001) return false;
    if (!view.history.length) return view.snapshot === null && view.state !== 'ready';
    if (!view.snapshot) return false;
    const ids = new Set();
    let previous = null;
    for (const entry of view.history) {
      if (!isRecord(entry) || !['observation_version', 'episode_id', 'action_count'].every((key) => Number.isInteger(entry[key]) && entry[key] >= 0) ||
          !validChoice({ game_id: view.game_id, level: entry.level }) || entry.observation_version !== entry.action_count || entry.episode_id < 1) return false;
      if (previous && (entry.observation_version <= previous.observation_version || entry.episode_id < previous.episode_id)) return false;
      const record = { level: entry.level, frames: [entry.frame], actions: [], decisions: [] };
      if (!validSnapshot({ ...view.snapshot, levels: [record] }) || ids.has(entry.frame.id) ||
          !Array.isArray(entry.frame.available_actions) || !entry.frame.available_actions.every((action) => ['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4', 'ACTION5', 'ACTION6', 'ACTION7', 'RESET'].includes(action)) ||
          !Number.isInteger(entry.frame.levels_completed) || entry.frame.levels_completed < 0) return false;
      ids.add(entry.frame.id);
      const last = entry.last_action;
      if (last == null) { if (entry.observation_version !== 0) return false; }
      else {
        if (!isRecord(last) || !['ACTION1', 'ACTION2', 'ACTION3', 'ACTION4', 'ACTION5', 'ACTION6', 'ACTION7', 'RESET'].includes(last.action) ||
            !isRecord(last.data) || last.observation_version !== entry.observation_version) return false;
        const keys = Object.keys(last.data);
        if (last.action === 'ACTION6' ? keys.length !== 2 || !keys.includes('x') || !keys.includes('y') ||
            !['x', 'y'].every((key) => Number.isInteger(last.data[key]) && last.data[key] >= 0 && last.data[key] < 64) : keys.length !== 0) return false;
        if (previous && entry.observation_version === previous.observation_version + 1 &&
            (entry.episode_id !== previous.episode_id + Number(last.action === 'RESET') || !previous.frame.available_actions.includes(last.action))) return false;
      }
      previous = entry;
    }
    const record = view.snapshot.levels.find((level) => level.level === manualLevel(view));
    const frame = array(record?.frames).at(-1);
    return Boolean(frame && previous.observation_version === view.observation_version && previous.action_count === view.action_count &&
      previous.episode_id === view.episode_id && previous.level === manualLevel(view) && sameManualFrame(previous.frame, frame) && sameManualAction(previous.last_action, view.last_action));
  }

  function validManual(view) {
    if (!isRecord(view) || !Object.hasOwn(manualLabels, view.state) || !['session_id', 'game_id'].every((key) => view[key] === null || typeof view[key] === 'string')) return false;
    if (!['observation_version', 'episode_id', 'action_count'].every((key) => Number.isInteger(view[key]) && view[key] >= 0)) return false;
    if (view.snapshot !== null && (!validSnapshot(view.snapshot) || view.snapshot.run.run_id !== null || view.snapshot.run.game_id !== view.game_id || view.snapshot.run.status !== 'manual')) return false;
    if (view.state === 'ready' && (!view.session_id || !view.game_id || !view.snapshot)) return false;
    if (view.level != null && !validChoice({ game_id: view.game_id, level: view.level })) return false;
    if (view.state === 'ready' && (!validChoice({ game_id: view.game_id, level: manualLevel(view) }) || !array(view.snapshot.levels).some((level) => level.level === manualLevel(view) && array(level.frames).length))) return false;
    if (view.last_action != null && (!isRecord(view.last_action) || typeof view.last_action.action !== 'string' || !isRecord(view.last_action.data))) return false;
    if (view.saved_levels !== undefined && (!Array.isArray(view.saved_levels) || !view.saved_levels.every((level, index) => validChoice({ game_id: view.game_id, level }) && (index === 0 || level > view.saved_levels[index - 1])))) return false;
    if (view.save_status !== undefined && !['disabled', 'saved', 'failed', 'pending'].includes(view.save_status)) return false;
    if (view.restored !== undefined && typeof view.restored !== 'boolean') return false;
    return validManualHistory(view);
  }

  function renderManualFeedback() {
    const panel = $('manual-action-status');
    const feedback = state.manualFeedback?.session_id === state.manualView?.session_id ? state.manualFeedback : null;
    const actionPending = state.manualPending?.path === '/api/manual/action';
    panel.hidden = state.mode !== 'manual' || (!feedback && !actionPending);
    let text = '';
    if (actionPending) text = state.manualBusy ? '正在发送 · 等待响应' : '结果未确认 · 请重试原请求';
    else if (feedback?.status === 'confirmed') text = `已执行 ${feedback.count} 次 · ${feedback.changed === null ? '画面对比不可用' : feedback.changed ? '画面已变化' : '画面未变化'}`;
    else if (feedback?.status === 'rejected') text = '请求已拒绝 · 请重新打开试玩';
    else if (feedback?.status === 'ended') text = '试玩已结束 · 动作结果未确认';
    else if (feedback) text = '动作结果未确认 · 已停止操作';
    panel.textContent = text;
  }

  function validManualRestart(view, command) {
    const record = array(view.snapshot?.levels).find((level) => level.level === command.choice.level);
    const frame = array(record?.frames)[0];
    return view.state === 'ready' && view.session_id !== command.body.session_id && !retiredManualSessions.has(view.session_id) &&
      view.game_id === command.choice.game_id && manualLevel(view) === command.choice.level && view.observation_version === 0 &&
      view.action_count === 0 && view.episode_id === 1 && view.last_action === null && view.restored === false &&
      ['saved', 'disabled'].includes(view.save_status) && view.history?.length === 1 && view.history[0].observation_version === 0 &&
      view.snapshot.run.primitive_action_count === 0 && view.snapshot.run.completed_level_count === 0 && array(record?.frames).length === 1 &&
      frame.state === 'NOT_FINISHED' && frame.levels_completed === 0 &&
      !array(view.snapshot.levels).some((level) => array(level.actions).length);
  }

  function renderManualStatus() {
    write('service-status', state.manualBusy ? '正在处理人工试玩操作' : state.manualPending ? '试玩请求结果未确认 · 请重试原请求' : state.manualError ? '人工试玩操作未确认 · 请重新打开试玩' : `${manualLabels[state.manualView?.state] || '正在打开人工试玩'}${manualLevel(state.manualView) ? ` · 关卡 ${manualLevel(state.manualView)}` : ''}`);
  }

  function acceptManual(view) {
    if (!validManual(view)) throw new Error('invalid-response');
    if (retiredManualSessions.has(view.session_id)) return;
    if (state.manualView?.session_id === view.session_id && state.manualView.observation_version > view.observation_version) return;
    const previous = state.manualView;
    const previousHistory = state.manualHistory;
    state.manualView = view;
    try {
      const appended = appendManualObservation(view);
      if (view.snapshot && (run.status !== 'manual' || previous?.session_id !== view.session_id || previous?.observation_version !== view.observation_version || previous?.state !== view.state || manualLevel(previous) !== manualLevel(view) || appended)) replaceSnapshot(manualHistorySnapshot(view), { follow: false, manualPosition: state.manualHistory?.index ?? null });
      else renderFrame();
    } catch (error) {
      state.manualView = previous; state.manualHistory = previousHistory;
      try { if (manualHistoryActive()) setManualFrame(previousHistory.index); } catch (_) { /* Keep the accepted data on persistent rendering failure. */ }
      throw error;
    }
    if (view.save_status !== 'failed' || previous?.session_id !== view.session_id) state.manualSaveRetry = null;
    const choice = { game_id: view.game_id, level: manualLevel(view) };
    if (validChoice(choice)) state.manualChoice = choice;
    renderManualStatus(); renderSessionControls();
  }

  async function sendManualCommand(command) {
    if (!liveConfig || state.mode !== 'manual' || state.manualBusy || state.commandBusy || state.pendingCommand || activeSession()) return;
    const generation = state.manualGeneration;
    const restart = command.path === '/api/manual/restart';
    const originSession = state.manualView?.session_id;
    let refreshManual = false;
    if (restart && originSession !== command.body.session_id) return;
    state.manualPollGeneration += 1;
    const isCurrent = () => generation === state.manualGeneration && state.mode === 'manual' && !activeSession() &&
      (!restart || state.manualView?.session_id === originSession);
    if (command.path === '/api/manual/action' && state.manualFeedback?.command_id !== command.body.command_id) {
      state.manualFeedback = { command_id: command.body.command_id, session_id: command.body.session_id,
        beforeGrid: currentFrame()?.grid, status: 'unconfirmed' };
    }
    state.manualBusy = true; state.manualPending = command; state.manualError = false;
    renderFrame(); renderSessionControls(); renderManualStatus();
    try {
      const view = await request(command.path, command.body);
      if (!isCurrent()) return;
      if (!validManual(view) || (restart ? !validManualRestart(view, command) :
        command.path === '/api/manual/open' ? view.game_id !== command.body.game_id || manualLevel(view) !== command.body.level : view.session_id !== command.body.session_id)) throw new Error('invalid-response');
      if (command.path === '/api/manual/action') {
        const acknowledged = view.observation_version === command.body.observation_version + 1 && view.last_action?.observation_version === view.observation_version &&
          view.last_action.action === command.body.action && Object.keys(view.last_action.data).length === Object.keys(command.body.data).length &&
          Object.keys(command.body.data).every((key) => view.last_action.data[key] === command.body.data[key]);
        // A ready response without action evidence leaves the exact request available for retry.
        if (view.state === 'ready' && !acknowledged) throw new Error('invalid-response');
        const afterGrid = array(array(view.snapshot?.levels).find((level) => level.level === manualLevel(view))?.frames).at(-1)?.grid;
        state.manualFeedback.status = view.state === 'ready' && acknowledged ? 'confirmed' : view.state === 'closed' ? 'ended' : 'unconfirmed';
        state.manualFeedback.count = view.action_count;
        state.manualFeedback.changed = state.manualFeedback.beforeGrid && afterGrid ? JSON.stringify(state.manualFeedback.beforeGrid) !== JSON.stringify(afterGrid) : null;
      }
      acceptManual(view); state.manualPending = null; state.pointerAction = null;
      if (restart) { retiredManualSessions.add(originSession); state.manualFeedback = null; }
      state.manualSaveRetry = view.state === 'ready' && view.save_status === 'failed' ? command : null;
      state.manualPollGeneration += 1;
    } catch (error) {
      if (!isCurrent()) return;
      if (error.message === 'request-rejected' && (!restart || error.refreshManual)) {
        state.manualPending = null; state.manualError = true;
        if (state.manualFeedback) state.manualFeedback.status = 'rejected';
        refreshManual = restart;
      }
      showRequestError(error);
    } finally {
      if (generation === state.manualGeneration && state.mode === 'manual' && !activeSession()) {
        state.manualBusy = false; renderFrame(); renderSessionControls(); renderManualStatus();
        if (refreshManual) await pollState();
      }
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

  const overviewLabels = { unplayed: '尚未开始', partial: '部分通关', completed: '全部通关', running: '正在运行', unverified: '记录未验证' };
  const activityPhases = { modeling: '建模', computing: '计算', executing: '执行', waiting: '等待' };
  function validActivity(activity, winLevels) {
    return activity === null || (isRecord(activity) && Number.isInteger(activity.level) && activity.level >= 1 && activity.level <= winLevels &&
      Number.isInteger(activity.target_level) && activity.target_level >= activity.level && activity.target_level <= winLevels &&
      Object.hasOwn(activityPhases, activity.phase) && Number.isInteger(activity.event_sequence) && activity.event_sequence > 0 &&
      typeof activity.updated_at === 'string' && Number.isFinite(Date.parse(activity.updated_at)));
  }
  function activityAge(updatedAt) {
    const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(updatedAt)) / 1000));
    return seconds < 60 ? `${seconds}秒前` : seconds < 3600 ? `${Math.floor(seconds / 60)}分钟前` : `${Math.floor(seconds / 3600)}小时前`;
  }
  const overviewGame = (id) => array(state.overview?.games).find((game) => game.game_id === id);
  const startLocked = () => manualUnsaved() || !liveConfig || !state.liveView || activeSession() ||
    state.manualBusy || Boolean(state.manualPending) || state.commandBusy || Boolean(state.pendingCommand) ||
    !state.overviewFresh || state.overview?.start_ready !== true;

  function validOverview(value) {
    const count = (entry) => Number.isInteger(entry) && entry >= 0;
    const score = (entry) => typeof entry === 'string' && /^\d+\.\d{6}$/.test(entry);
    const id = (entry) => entry === null || (typeof entry === 'string' && /^[A-Za-z0-9_-]+$/.test(entry));
    if (!isRecord(value) || !isRecord(value.scope) || !isRecord(value.totals) || !Array.isArray(value.games) ||
      typeof value.start_ready !== 'boolean' || (value.guest_busy !== null && typeof value.guest_busy !== 'boolean') ||
      ![null, 'guest-unavailable', 'session-busy', 'model-unavailable', 'model-mismatch'].includes(value.start_block_reason) ||
      !stringFields(value.scope, ['model_id', 'score_kind', 'catalog_id']) || value.scope.score_kind !== 'saved-route-rhae' || !count(value.scope.seed)) return false;
    const totals = value.totals, seen = new Set();
    if ((totals.actions_pending !== undefined && !count(totals.actions_pending)) ||
      (totals.saved_route_actions !== undefined && !count(totals.saved_route_actions)) || !score(totals.score) || !['completed_games', 'total_games', 'completed_levels', 'total_levels', 'primitive_actions', 'restoration_actions', 'new_solver_actions'].every((key) => count(totals[key]))) return false;
    if ((totals.display_completed_levels !== undefined && (!count(totals.display_completed_levels) || totals.display_completed_levels < totals.completed_levels || totals.display_completed_levels > totals.total_levels)) ||
      (totals.display_completed_games !== undefined && (!count(totals.display_completed_games) || totals.display_completed_games < totals.completed_games || totals.display_completed_games > totals.total_games))) return false;
    if (totals.total_games !== value.games.length || totals.completed_games > totals.total_games || totals.completed_levels > totals.total_levels) return false;
    if (!value.games.every((game) => {
      const catalog = array(liveConfig?.games).find((entry) => entry.game_id === game?.game_id);
      if (!isRecord(game) || !catalog || seen.has(game.game_id) || game.win_levels !== catalog.win_levels ||
        !count(game.win_levels) || !count(game.completed_levels) || game.completed_levels > game.win_levels || !score(game.score) ||
        !Object.hasOwn(overviewLabels, game.status) || !count(game.route_actions) || !id(game.best_run_id) || !id(game.resume_run_id) || !Array.isArray(game.runs)) return false;
      if (game.display_completed_levels !== undefined && (!count(game.display_completed_levels) || game.display_completed_levels < game.completed_levels || game.display_completed_levels > game.win_levels ||
          typeof game.progress_pending !== 'boolean' || game.progress_pending !== (game.display_completed_levels > game.completed_levels))) return false;
      seen.add(game.game_id);
      const runs = new Set();
      if (!game.runs.every((run) => isRecord(run) && id(run.run_id) && run.run_id !== null && !runs.has(run.run_id) && runs.add(run.run_id) &&
        typeof run.status === 'string' && typeof run.verified === 'boolean' &&
        ['completed_levels', 'primitive_actions', 'restoration_actions', 'new_solver_actions'].every((key) => count(run[key])) &&
        (run.activity === undefined || validActivity(run.activity, game.win_levels)) &&
        (run.observed_completed_levels === undefined || count(run.observed_completed_levels) && run.observed_completed_levels <= game.win_levels))) return false;
      if (game.solving !== undefined || game.solving_run_id !== undefined) {
        if (typeof game.solving !== 'boolean' || !id(game.solving_run_id) ||
            (game.solving ? game.solving_run_id === null || !runs.has(game.solving_run_id) : game.solving_run_id !== null)) return false;
      }
      return [game.best_run_id, game.resume_run_id, game.latest_run_id ?? null].every((runId) => runId === null || (id(runId) && runs.has(runId)));
    })) return false;
    return value.games.length === array(liveConfig?.games).length && totals.total_levels === value.games.reduce((sum, game) => sum + game.win_levels, 0) &&
      (totals.display_completed_levels === undefined || totals.display_completed_levels === value.games.reduce((sum, game) => sum + (game.display_completed_levels ?? game.completed_levels), 0)) &&
      (totals.display_completed_games === undefined || totals.display_completed_games === value.games.filter(game => (game.display_completed_levels ?? game.completed_levels) === game.win_levels).length) &&
      (totals.saved_route_actions === undefined || totals.saved_route_actions === value.games.reduce((sum, game) => sum + game.route_actions, 0));
  }

  function renderRunChoices() {
    const select = $('replay-run'), previous = select.value;
    const game = overviewGame($('game-select').value);
    const choices = new Map();
    array(game?.runs).forEach((run) => choices.set(run.run_id, { ...run, game_id: game.game_id }));
    select.replaceChildren();
    choices.forEach((run) => {
      const option = node('option', `${run.run_id}${run.status ? ' · ' + (sessionLabels[run.status] || run.status) : ''}`);
      option.value = run.run_id; select.append(option);
    });
    if (choices.has(previous)) select.value = previous;
    if (state.replayRun && select.value !== state.replayRun) stopReplayPolling();
    $('replay-load').disabled = !select.value;
  }

  function renderOverviewControls() {
    if (!state.overview) return;
    const locked = startLocked();
    [...$('overview-game-list').children].forEach((row) => {
      const game = overviewGame(row.dataset.gameId);
      row.classList.toggle('is-selected', row.dataset.gameId === $('game-select').value);
      row.classList.toggle('is-solving', gameSolving(game));
      row.querySelector('[data-overview-start]').disabled = locked || game.status === 'completed' || game.status === 'running' || (game.completed_levels > 0 && !game.resume_run_id);
      row.querySelector('[data-overview-start]').hidden = game.status === 'completed';
      row.querySelector('[data-overview-fresh]').disabled = locked || game.status === 'running';
      row.querySelector('[data-overview-watch]').disabled = !game.runs.length;
      const attempt = row.querySelector('[data-overview-attempt]');
      attempt.hidden = !latestReplayId(game) || preferredReplayId(game) === latestReplayId(game);
      attempt.disabled = manualUnsaved() || Boolean(state.manualPending) || state.commandBusy;
      row.querySelector('[data-overview-select]').disabled = manualUnsaved() || Boolean(state.manualPending) || state.commandBusy;
    });
    enforceCloudReadOnly();
  }

  function gameSolving(game) {
    if (typeof game.solving === 'boolean') return game.solving;
    return game.solving === true || (state.liveView?.state === 'running' && activeSession() &&
      state.liveView.game_id === game.game_id && game.runs.some(entry=>entry.run_id===state.liveView.run_id));
  }

  function renderOverview() {
    const { scope, totals, games } = state.overview;
    write('overview-scope', `当前 WorldMap P7 · ${scope.model_id} · seed ${scope.seed} · 本地目录 ${totals.total_games} 个游戏`);
    write('overview-score', Number(totals.score).toFixed(2));
    write('overview-games', `${totals.display_completed_games ?? totals.completed_games} / ${totals.total_games}`);
    write('overview-levels', `${totals.display_completed_levels ?? totals.completed_levels} / ${totals.total_levels}`);
    const pendingLevels = (totals.display_completed_levels ?? totals.completed_levels) - totals.completed_levels;
    write('overview-progress-breakdown', pendingLevels ? `实时已过（已保存 ${totals.completed_levels}，待封存 ${pendingLevels}）` : `已保存 ${totals.completed_levels} 关`);
    write('overview-actions', totals.saved_route_actions ?? games.reduce((sum, game) => sum + game.route_actions, 0));
    write('overview-action-breakdown', `全部尝试 ${totals.primitive_actions} · 恢复 ${totals.restoration_actions} · 新增求解 ${totals.new_solver_actions}${totals.actions_pending ? ' · 待封存分账 ' + totals.actions_pending : ''}`);
    const list = $('overview-game-list');
    const existing = new Map([...list.children].map((row) => [row.dataset.gameId, row]));
    [...list.children].forEach((row) => { if (!games.some((game) => game.game_id === row.dataset.gameId)) row.remove(); });
    games.forEach((game, index) => {
      let row = existing.get(game.game_id);
      if (!row) {
        row = node('tr'); row.dataset.gameId = game.game_id;
        const identity = node('td'), choice = node('button', undefined, 'game-choice');
        choice.type = 'button'; choice.dataset.overviewSelect = game.game_id;
        choice.addEventListener('click', () => chooseOverviewGame(game.game_id)); identity.append(choice);
        const progressCell = node('td'), progress = node('div', undefined, 'overview-progress');
        progress.append(node('progress'), node('span')); progressCell.append(progress);
        const operations = node('td'), buttons = node('div', undefined, 'overview-game-actions');
        [['watch', '回放', '回放或观察游戏', () => watchGame(game.game_id)], ['attempt', '尝试', '查看最新尝试', () => chooseOverviewGame(game.game_id, {replay:true,attempt:true})], ['start', '启动', '启动或继续求解', () => startGame(game.game_id)], ['fresh', '重玩', '从头开始游戏', () => startGame(game.game_id, true)]].forEach(([kind, label, description, action]) => {
          const button = node('button', label, 'text-button' + (kind === 'start' ? ' overview-primary' : ''));
          button.title = description; button.setAttribute('aria-label', description);
          button.type = 'button'; button.dataset['overview' + kind[0].toUpperCase() + kind.slice(1)] = game.game_id;
          button.addEventListener('click', action); buttons.append(button);
        });
        operations.append(buttons); row.append(identity, progressCell, node('td'), node('td'), node('td'), operations);
      }
      const choice = row.querySelector('[data-overview-select]');
      choice.replaceChildren(node('span', string(game.alias, game.game_id)), node('span', game.game_id, 'game-code'));
      choice.setAttribute('aria-label', `选择游戏 ${string(game.alias, game.game_id)}`);
      const displayed = game.display_completed_levels ?? game.completed_levels;
      const progress = row.querySelector('progress'); progress.max = game.win_levels; progress.value = displayed;
      row.querySelector('.overview-progress').classList.toggle('completed', game.win_levels > 0 && game.completed_levels === game.win_levels);
      row.querySelector('.overview-progress').classList.toggle('partial', game.completed_levels > 0 && game.completed_levels < game.win_levels);
      progress.setAttribute('aria-label', `${displayed} / ${game.win_levels} 关卡`);
      row.querySelector('.overview-progress span').textContent = `${displayed} / ${game.win_levels}${game.progress_pending ? ' · 待封存' : ''}`;
      row.children[2].textContent = Number(game.score).toFixed(2);
      const latestRunId = latestReplayId(game);
      const recording = game.runs.some((run) => run.run_id === latestRunId && run.recording === true);
      const solving = gameSolving(game);
      const active = solving || (game.solving === undefined && game.status === 'running') || recording;
      const external = active && !game.runs.some((run) => run.run_id === state.liveView?.run_id && activeSession());
      const completed = game.win_levels > 0 && game.completed_levels === game.win_levels;
      const resultKind = completed ? 'completed' : game.completed_levels > 0 ? 'partial' : !active && game.status === 'unverified' ? 'unverified' : 'unplayed';
      const resultLabel = completed ? '✓ 全部通关' : game.completed_levels > 0 ? '◐ 部分通关' : resultKind === 'unverified' ? '未通关' : active ? '尚未通关' : '尚未开始';
      const result = node('span', resultLabel, 'overview-result-badge ' + resultKind);
      result.title = resultKind === 'unverified' ? '没有已保存过关记录；尝试记录未形成可用过关路线' : `已保存 ${game.completed_levels} / ${game.win_levels} 关`;
      result.setAttribute('aria-label', `${resultLabel} · ${result.title}`);
      const status = row.children[3]; status.className = 'overview-state'; status.replaceChildren(result);
      if (Number.isInteger(game.diagnostics_count) && game.diagnostics_count > 0 && validDiagnostic(game.latest_diagnostic)) {
        const warning=node('span',`⚠ ${game.diagnostics_count}`,'overview-processing-warning');
        warning.title=diagnosticText(game.latest_diagnostic);
        warning.setAttribute('aria-label',`处理警告 ${game.diagnostics_count} 项：${warning.title}`);
        status.append(warning);
      }
      if (active) {
        const running = solving || (game.solving === undefined && game.status === 'running');
        const solvingRunId = game.solving_run_id || game.active_run_id || (solving ? state.liveView?.run_id : null);
        const recent = running ? game.runs.find(run => run.run_id === solvingRunId)?.activity : null;
        const activity = node('span', running ? `● 解题中${recent ? ' · L' + recent.target_level : ''}` : '● 新尝试', 'overview-activity-badge');
        activity.title = (running ? '解题中' : '最新尝试记录尚未封存') + (external ? ' · 外部只读' : ' · 当前会话');
        activity.setAttribute('aria-label', activity.title); status.append(activity);
        if (recent) {
          const phase = node('span', `最近${activityPhases[recent.phase]} · ${activityAge(recent.updated_at)}`, 'overview-activity-phase');
          phase.title = `最近确认阶段：${activityPhases[recent.phase]} · 事件 #${recent.event_sequence} · ${recent.updated_at}`;
          phase.setAttribute('aria-label', phase.title); status.append(phase);
        }
      }
      row.children[4].textContent = String(game.route_actions);
      const start = row.querySelector('[data-overview-start]');
      start.textContent = game.resume_run_id ? '继续' : game.completed_levels > 0 ? '待恢复' : '启动';
      start.title = game.resume_run_id ? '继续求解下一关' : game.completed_levels > 0 ? '存档不可接续' : '启动游戏求解';
      start.setAttribute('aria-label', start.title);
      if (list.children[index] !== row) list.insertBefore(row, list.children[index] || null);
    });
    renderOverviewControls(); renderRunChoices();
  }

  async function loadOverview() {
    if (!liveConfig) return;
    if (state.overviewBusy) { state.overviewPending = true; return; }
    state.overviewBusy = true;
    try {
      const overview = await request('/api/overview');
      if (!validOverview(overview)) throw new Error('invalid-response');
      state.overview = overview; state.overviewFresh = true; renderOverview(); renderRail(); renderProgressContext(); renderSessionControls();
      renderLevelEfficiency();
      observeSelectedGame();
      ensureSelectedSource();
      if (state.replayPollTimer !== null && !replayUnsealed(snapshot)) loadReplay();
      write('overview-refresh', '云端只读 · 每 5 分钟检查更新');
    } catch (_) {
      state.overviewFresh = false; renderRail(); renderProgressContext(); renderSessionControls();
      write('overview-refresh', '总览暂不可用 · 保留已显示记录');
    } finally {
      state.overviewBusy = false;
      if (state.overviewPending) { state.overviewPending = false; loadOverview(); }
    }
  }

  function stopReplayPolling() {
    clearReplayLoad();
    state.replayGeneration += 1; state.replayRun = null; state.replayPollBusy = false; state.replayFailures = 0; state.replayRetryAt = 0;
    if (state.replayPollTimer !== null) window.clearInterval(state.replayPollTimer);
    state.replayPollTimer = null;
  }

  function chooseOverviewGame(gameId, { replay = false, attempt = false } = {}) {
    if (manualUnsaved() || state.manualPending || state.commandBusy || !overviewGame(gameId)) return false;
    state.gameSelectionTouched = true;
    pause(); stopReplayPolling(); $('game-select').value = gameId; renderRunChoices();
    attemptReplayRun = attempt ? latestReplayId(overviewGame(gameId)) : null;
    if (!replay && state.mode === 'manual' && !activeSession()) openManual(1);
    else { invalidateManual(); state.manualPending = null; state.mode = 'replay'; selectSwitchedGameLevel(overviewGame(gameId)); observeSelectedGame(); }
    renderSessionControls(); return true;
  }

  function startGame(gameId, fresh = false) {
    const game = overviewGame(gameId);
    if (!game || startLocked() || game.status === 'running' || (!fresh && (game.status === 'completed' || (game.completed_levels > 0 && !game.resume_run_id)))) return;
    state.gameSelectionTouched = true;
    pause(); stopReplayPolling(); $('game-select').value = gameId; renderRunChoices();
    attemptReplayRun = null;
    state.mode = 'live'; state.replayFollow = true; state.manualView = null; state.eventSequence = null;
    const body = { game_id: gameId, command_id: window.crypto.randomUUID(), target_level: game.win_levels };
    if (!fresh && game.resume_run_id) body.resume_run_id = game.resume_run_id;
    sendCommand({ path: '/api/start', body });
  }

  const replayUnsealed = (replay) => replay.run.sealed_trace === false &&
    !['successful', 'unsuccessful', 'completed', 'cancelled', 'timed-out', 'failed'].includes(replay.run.status) &&
    array(overviewGame(replay.run.game_id)?.runs).some((run) => run.run_id === replay.run.run_id &&
      (run.recording === true || ['starting', 'running', 'pause_requested', 'paused', 'resume_requested', 'stopping'].includes(run.status)));

  function clearReplayLoad(ticket = null) {
    if (ticket && replayLoad !== ticket) return;
    replayLoad = null;
    if (replayLoadTimer !== null) window.clearInterval(replayLoadTimer);
    replayLoadTimer = null;
    $('replay-loading').hidden = true; $('replay-retry').hidden = true;
    $('replay-loading').setAttribute('aria-busy', 'false');
  }

  function beginReplayLoad(game, runId, level, phase, retry) {
    const key = `${state.replayGeneration}/${game.game_id}/${runId}/${level}`;
    if (replayLoad?.key !== key) {
      clearReplayLoad();
      replayLoad = {key, started:Date.now(), gameId:game.game_id, runId, level, visible:false};
    }
    const ticket = replayLoad;
    Object.assign(ticket, {phase, retry, failed:false, waiting:false});
    // Keep accepted, identity-matched frames visible during background refresh.
    // A cold selection still reports its real wait immediately.
    ticket.visible ||= !frames().length;
    const update = () => {
      if (replayLoad !== ticket) return;
      $('replay-loading').hidden = !ticket.visible;
      $('replay-loading').classList.toggle('load-failed', ticket.failed);
      $('replay-loading').setAttribute('aria-busy', String(!ticket.failed));
      const elapsed = Math.floor((Date.now() - ticket.started) / 1000);
      write('replay-loading-text', `${string(game.alias, game.game_id)} · ${ticket.phase} · 已等待 ${elapsed} 秒`);
      $('replay-retry').hidden = !ticket.failed;
      if (ticket.waiting && Date.now() >= ticket.retryAt) {
        ticket.waiting = false; ticket.retry();
      }
    };
    ticket.render = update;
    update();
    if (replayLoadTimer === null) replayLoadTimer = window.setInterval(update, 1000);
    return ticket;
  }

  function waitReplayLoad(ticket) {
    if (replayLoad !== ticket) return;
    ticket.waiting = true; ticket.retryAt = Date.now() + 2000;
  }

  function failReplayLoad(ticket) {
    if (replayLoad !== ticket) return;
    ticket.phase = '读取失败，请重新加载'; ticket.failed = true; ticket.waiting = false; ticket.visible = true;
    ticket.render();
  }

  function validReplayManifest(value, game, runId) {
    if (!isRecord(value) || !['asterion.arc-agi3-p7-replay-manifest/v1','asterion.arc-agi3-p7-replay-manifest/v2'].includes(value.schema) || value.run_id !== runId ||
        !Array.isArray(value.levels) || !Array.isArray(value.warnings) || !value.warnings.every(warning => typeof warning === 'string')) return false;
    if (!optionalRecords(value.diagnostics,validDiagnostic)) return false;
    if (value.state === 'loading') return value.revision === null && value.run === null && value.levels.length === 0;
    const meta = value.run, ids = new Set();
    return value.state === 'ready' && typeof value.revision === 'string' && /^[a-f0-9]{64}$/.test(value.revision) &&
      isRecord(meta) && meta.run_id === runId && meta.game_id === game.game_id && meta.seed === 0 && meta.win_levels === game.win_levels &&
      Number.isInteger(meta.completed_level_count) && meta.completed_level_count >= 0 && meta.completed_level_count <= game.win_levels &&
      Number.isInteger(meta.primitive_action_count) && meta.primitive_action_count >= 0 && typeof meta.status === 'string' &&
      value.levels.length === game.win_levels && value.levels.every(level => isRecord(level) &&
        Number.isInteger(level.level) && level.level > 0 && level.level <= game.win_levels && !ids.has(level.level) && ids.add(level.level) &&
        typeof level.status === 'string' && Number.isInteger(level.frame_count) && level.frame_count >= 0 &&
        Number.isInteger(level.action_count) && level.action_count >= 0 && typeof level.has_cognition === 'boolean');
  }

  async function readReplayManifest(game, runId) {
    if (!manifestRequests.has(runId)) {
      const pending = request(`/api/replay/${encodeURIComponent(runId)}/manifest`).then(value => {
        if (!validReplayManifest(value, game, runId)) throw new Error('invalid-response');
        if (value.state === 'loading') {
          replayManifests.delete(runId);
          [...replayLevelViews.keys()].forEach(key=>{if (key.startsWith(runId+'/')) replayLevelViews.delete(key);});
        }
        if (value.state === 'ready') {
          replayManifests.delete(runId);replayManifests.set(runId,value);
          while(replayManifests.size > 4) replayManifests.delete(replayManifests.keys().next().value);
          [...replayLevelViews.keys()].forEach(key => {if (key.startsWith(runId+'/') && !key.startsWith(`${runId}/${value.revision}/`)) replayLevelViews.delete(key);});
        }
        return value;
      }).finally(() => manifestRequests.delete(runId));
      manifestRequests.set(runId, pending);
    }
    return manifestRequests.get(runId);
  }

  async function readReplayLevel(manifest, level) {
    const generation=state.replayGeneration;
    const runId = manifest.run_id, key = `${runId}/${manifest.revision}/${level}`;
    if (replayLevelViews.has(key)) {const cached=replayLevelViews.get(key);replayLevelViews.delete(key);replayLevelViews.set(key,cached);return cached;}
    while (!replayLevelRequests.has(key) && replayLevelRequests.size >= 2) {
      await Promise.race([...replayLevelRequests.values()].map(pending=>pending.catch(()=>null)));
      if (generation!==state.replayGeneration) throw new Error('obsolete-request');
      assertReplayRevision(manifest);
    }
    if (!replayLevelRequests.has(key)) {
      const pending = request(`/api/replay/${encodeURIComponent(runId)}/levels/${level}/${manifest.revision}`).then(value => {
        const meta = manifest.levels.find(entry => entry.level === level), record = value?.levels?.[0];
        if (!validSnapshot(value) || value.replay_revision !== manifest.revision || value.run.run_id !== runId ||
            JSON.stringify(value.run) !== JSON.stringify(manifest.run) || value.run.game_id !== manifest.run.game_id || value.run.seed !== manifest.run.seed || value.run.win_levels !== manifest.run.win_levels ||
            value.run.completed_level_count !== manifest.run.completed_level_count || value.run.primitive_action_count !== manifest.run.primitive_action_count ||
            value.run.replay_verified !== manifest.run.replay_verified || value.run.sealed_trace !== manifest.run.sealed_trace ||
            value.levels.length !== 1 || record.level !== level || record.status !== meta?.status ||
            levelFrameCount(record) !== meta.frame_count || record.actions.length !== meta.action_count ||
            (record.frame_page && (record.frame_page.start !== 0 || record.frames.length !== Math.min(32,record.frame_count)))) throw new Error('invalid-response');
        assertReplayRevision(manifest);
        const bytes=estimateReplayBytes(value);
        if (bytes <= 32*1024*1024) {
          replayLevelViews.set(key,value);
          while (replayLevelViews.size > 4 || [...replayLevelViews.values()].reduce((sum,view)=>sum+estimateReplayBytes(view),0) > 32*1024*1024) replayLevelViews.delete(replayLevelViews.keys().next().value);
        }
        return value;
      }).catch(error=>{error.replayRevision=manifest.revision;throw error;}).finally(() => replayLevelRequests.delete(key));
      replayLevelRequests.set(key,pending);
    }
    return replayLevelRequests.get(key);
  }

  function estimateReplayBytes(value) {
    if (!replayViewSizes.has(value)) {
      const grids=value.levels.reduce((sum,level)=>sum+level.frames.reduce((total,frame)=>total+frame.grid.reduce((n,row)=>n+row.length*8+32,256),0),0);
      // A conservative cache estimate, not a browser heap guarantee. Include
      // every public field, plus numeric-grid storage, once per immutable view.
      replayViewSizes.set(value,JSON.stringify(value).length*2+grids);
    }
    return replayViewSizes.get(value);
  }

  function assertReplayRevision(manifest) {
    if (replayManifests.get(manifest.run_id)?.revision !== manifest.revision) {const error=new Error('replay-stale');error.status=409;error.obsolete=true;throw error;}
  }

  function replayManifestView(manifest, selectedDetail = null) {
    const details = manifest.levels.map(level => replayLevelViews.get(`${manifest.run_id}/${manifest.revision}/${level.level}`)).filter(Boolean);
    if (selectedDetail && !details.includes(selectedDetail)) details.push(selectedDetail);
    const byLevel=new Map(details.map(detail=>[detail.levels[0].level,detail.levels[0]]));
    const decisions = new Map(), events = new Map();
    details.forEach(detail => {
      array(detail.decisions).forEach(decision => decisions.set(decision.id,decision));
      array(detail.process_events).forEach(event => events.set(event.event_sequence,event));
    });
    const view = {schema:'asterion.arc-agi3-p7-console/v1', generated_at:details[0]?.generated_at ?? null,
      run:manifest.run, replay_revision:manifest.revision, warnings:manifest.warnings,diagnostics:manifest.diagnostics,
      levels:manifest.levels.map(meta => byLevel.get(meta.level) || {
        ...meta,replay_unloaded:true,frames:[],actions:[],decisions:[],cognition:{scope:'unavailable'},receipt:null}),
      decisions:[...decisions.values()],process_events:[...events.values()].sort((a,b) => a.event_sequence-b.event_sequence)};
    validatedReplayViews.add(view); return view;
  }

  async function loadLevelReplay({initial = false, preserveSelection = false} = {}) {
    const runId = $('replay-run').value, game = overviewGame($('game-select').value);
    if (!game || !runId || state.mode !== 'replay' || (state.replayPollBusy && !initial)) return;
    if (initial) { stopReplayPolling(); state.replayRun = runId; if (!preserveSelection) {state.replayFollow = true;state.eventSequence = null;} }
    const generation = state.replayGeneration;
    const isCurrent = () => state.mode === 'replay' && state.replayGeneration === generation &&
      $('replay-run').value === runId && $('game-select').value === game.game_id;
    if (run.game_id !== game.game_id || run.run_id !== runId) {
      const placeholder = emptyGamePreview(game,'loading'); placeholder.run.run_id = runId;
      [...savedViews.keys()].forEach(id=>{if (id!==game.game_id) savedViews.delete(id);});
      replaceSnapshot(placeholder,{follow:false});
    }
    const selectedLevel = primaryLevel().level || 1;
    const retry = () => loadReplay({preserveSelection:true});
    const ticket = beginReplayLoad(game,runId,selectedLevel,'正在整理回放',retry);
    state.replayPollBusy = true;
    try {
      const manifest = await readReplayManifest(game,runId);
      if (!isCurrent()) return;
      if (manifest.state === 'loading') {waitReplayLoad(ticket);return;}
      const currentSelected = primaryLevel().level;
      const target = state.replayFollow ? manifest.levels.filter(level => level.frame_count > 0).at(-1)?.level || 1 : currentSelected;
      if (currentSelected !== selectedLevel) return;
      ticket.level=target;
      if (snapshot.replay_revision !== manifest.revision && !frames().length) {
        replaceSnapshot(replayManifestView(manifest),{follow:false});
        selectLevel(target-1,{bindSavedSource:false,retireLoad:false});
      } else if (state.replayFollow && target !== currentSelected) selectLevel(target-1,{bindSavedSource:false,retireLoad:false});
      assertReplayRevision(manifest);
      const level = manifest.levels.find(entry => entry.level === target);
      let detail=null;
      if (level.frame_count > 0) {
        ticket.phase = `正在加载第 ${target} 关`; ticket.level = target;
        ticket.visible ||= !frames().length; ticket.render();
        detail=await readReplayLevel(manifest,target);
        if (!isCurrent() || primaryLevel().level !== target) return;
      }
      assertReplayRevision(manifest);
      const previousCompleted = number(run.completed_level_count);
      // The revision covers the whole immutable public snapshot. Repainting an
      // unchanged selected detail resets canvas attributes and rebuilds cards.
      if (initial || target !== currentSelected || snapshot.replay_revision !== manifest.revision || primaryLevel().replay_unloaded)
        replaceSnapshot(replayManifestView(manifest,detail),{follow:state.replayFollow});
      state.replayRun = runId;state.replayFailures = 0;state.replayRetryAt = 0;
      clearReplayLoad(ticket);ensureSelectedSource();
      write('service-status',replayUnsealed(snapshot) ? '只读观察 · 记录未封口 · 每 2 秒更新' : '回放记录 · 按关卡读取 · 只读');
      if (replayUnsealed(snapshot) && state.replayPollTimer === null) state.replayPollTimer = window.setInterval(() => loadReplay(), CLOUD_REFRESH_INTERVAL);
      else if (!replayUnsealed(snapshot) && state.replayPollTimer !== null) {window.clearInterval(state.replayPollTimer);state.replayPollTimer = null;}
      renderSessionControls();
      if (number(run.completed_level_count)>previousCompleted) loadOverview();
    } catch(error) {
      if (!isCurrent() || primaryLevel().level !== ticket.level) return;
      if (error.status === 409) {
        if (!error.obsolete && (!error.replayRevision || replayManifests.get(runId)?.revision===error.replayRevision)) replayManifests.delete(runId);
        waitReplayLoad(ticket);
      }
      else failReplayLoad(ticket);
    } finally {
      if (isCurrent()) {
        state.replayPollBusy = false;
        if (primaryLevel().replay_unloaded && primaryLevel().level !== selectedLevel) loadReplay({preserveSelection:true});
      }
    }
  }

  async function loadSavedLevelView(game) {
    const bestId = game.best_run_id, generation = state.replayGeneration, currentRun = run.run_id;
    const selectedLevel = primaryLevel().level, seed = run.seed;
    if (run.status === 'loading' && state.replayRun === currentRun) return;
    const isCurrent = () => state.mode !== 'manual' && state.replayGeneration === generation && run.game_id === game.game_id &&
      run.run_id === currentRun && $('game-select').value === game.game_id && verifiedSavedGame()?.best_run_id === bestId && verifiedSavedGame()?.completed_levels === game.completed_levels && run.seed === seed;
    const selected = () => isCurrent() && primaryLevel().level === selectedLevel;
    const retry = () => ensureSelectedSource();
    let ticket = null;
    try {
      const manifest = await readReplayManifest(game,bestId);
      if (!isCurrent()) return;
      if (manifest.state === 'loading') {
        if (selected() && !frames().length) {ticket=beginReplayLoad(game,bestId,selectedLevel,'正在整理已保存回放',retry);waitReplayLoad(ticket);}
        return;
      }
      if (manifest.run.seed !== seed || !matchesVerifiedSavedRun(manifest.run,game,seed)) throw new Error('invalid-response');
      assertReplayRevision(manifest);
      savedViews.set(game.game_id,replayManifestView(manifest));
      renderRail();renderLevelEfficiency();
      const meta = manifest.levels.find(level => level.level===selectedLevel);
      let detail=null;
      // A selected level already present in the current attempt needs no saved grids.
      if (levelFrameCount(primaryLevel()) > 0 && (currentRun !== bestId || !primaryLevel().replay_unloaded)) return;
      if (meta?.frame_count > 0 && (!array(primaryLevel().frames).length || currentRun === bestId)) {
        if (selected()) ticket=beginReplayLoad(game,bestId,selectedLevel,`正在加载已保存第 ${selectedLevel} 关`,retry);
        detail=await readReplayLevel(manifest,selectedLevel);
      }
      if (!isCurrent()) return;
      assertReplayRevision(manifest);
      const saved=replayManifestView(manifest,detail);savedViews.set(game.game_id,saved);
      if (selected()) {
        const previousSource=levelSource().key;
        boardSavedViews.set(`${run.game_id}/${selectedLevel}`,saved);
        refreshLevelSource(previousSource);if (ticket) clearReplayLoad(ticket);
      } else {renderRail();renderProgressContext();renderLevelEfficiency();}
    } catch(error) {
      if (!selected()) return;
      if (error.obsolete && replayManifests.has(bestId)) return;
      if (error.status===409) {if (!error.replayRevision || replayManifests.get(bestId)?.revision===error.replayRevision) replayManifests.delete(bestId);ticket=ticket||beginReplayLoad(game,bestId,selectedLevel,'正在刷新已保存回放',retry);waitReplayLoad(ticket);}
      else if (!frames().length) {ticket=ticket||beginReplayLoad(game,bestId,selectedLevel,'读取已保存关卡',retry);failReplayLoad(ticket);}
    }
  }

  async function loadReplay({ initial = false, preserveSelection = false } = {}) {
    if (levelReplayEnabled) return loadLevelReplay({initial,preserveSelection});
    const runId = $('replay-run').value;
    if (!runId || state.mode !== 'replay' || (state.replayPollBusy && !initial)) return;
    if (initial) { stopReplayPolling(); state.replayRun = runId; if (!preserveSelection) { state.replayFollow = true; state.eventSequence = null; } }
    if (!initial && Date.now() < state.replayRetryAt) return;
    const generation = state.replayGeneration;
    const isCurrent = () => state.mode === 'replay' && state.replayGeneration === generation && $('replay-run').value === runId;
    state.replayPollBusy = true;
    try {
      const replay = await request(`/api/replay/${encodeURIComponent(runId)}`);
      if (!isCurrent()) return;
      if (!validSnapshot(replay) || replay.run.run_id !== runId || replay.run.game_id !== $('game-select').value) throw new Error('invalid-response');
      const completedBefore = run.run_id === replay.run.run_id ? number(run.completed_level_count) : 0;
      replaceSnapshot(replay, { follow: state.replayFollow }); state.replayRun = runId; state.replayFailures = 0; state.replayRetryAt = 0;
      ensureSelectedSource();
      write('service-status', replayUnsealed(replay) ? '只读观察 · 记录未封口 · 每 2 秒更新' : '回放记录 · 只读');
      if (replayUnsealed(replay) && state.replayPollTimer === null) state.replayPollTimer = window.setInterval(() => loadReplay(), CLOUD_REFRESH_INTERVAL);
      else if (!replayUnsealed(replay) && state.replayPollTimer !== null) { window.clearInterval(state.replayPollTimer); state.replayPollTimer = null; }
      renderSessionControls();
      if (number(replay.run.completed_level_count) > completedBefore) loadOverview();
    } catch (error) {
      if (isCurrent()) {
        state.replayFailures += 1; state.replayRetryAt = Date.now() + Math.min(30000, 2000 * (2 ** Math.min(state.replayFailures, 4)));
        showRequestError(error);
      }
    } finally { if (isCurrent()) state.replayPollBusy = false; }
  }

  function activeReplayId(game) {
    if (!game?.runs.length) return null;
    const ids = new Set(game.runs.map((entry) => entry.run_id));
    if (activeSession() && state.liveView?.game_id === game.game_id && ids.has(state.liveView.run_id)) return state.liveView.run_id;
    return ids.has(game.active_run_id) ? game.active_run_id : null;
  }

  function latestReplayId(game) {
    if (!game?.runs.length) return null;
    const explicit = game.runs.some(entry => entry.run_id === game.latest_run_id) ? game.latest_run_id : null;
    const recording = game.runs.some(entry => entry.run_id === game.recording_run_id) ? game.recording_run_id : null;
    return explicit || recording || activeReplayId(game) || [...game.runs].sort((a, b) => b.run_id.localeCompare(a.run_id))[0].run_id;
  }

  function preferredReplayId(game) {
    const best = array(game?.runs).find(entry => entry.run_id === game.best_run_id && entry.verified === true &&
      entry.completed_levels === game.completed_levels && entry.completed_levels > 0);
    return best?.run_id || null;
  }

  function emptyGamePreview(game, status = 'preview') {
    return {schema:'asterion.arc-agi3-p7-console/v1',generated_at:null,
      run:{run_id:null,game_id:game.game_id,status,seed:0,win_levels:game.win_levels,
           completed_level_count:0,primitive_action_count:0,replay_verified:false,sealed_trace:false},
      levels:Array.from({length:game.win_levels}, (_,index) => ({level:index+1,status,
        frames:[],actions:[],decisions:[],cognition:{scope:'unavailable'},receipt:null})),decisions:[],warnings:[]};
  }

  function selectSwitchedGameLevel(game, {force = false} = {}) {
    if (!game || (!force && run.game_id === game.game_id)) return;
    // Saved contiguous progress owns the switch default, even when a newer
    // attempt has fewer passed levels or unsealed progress appears in the UI.
    const target = game.win_levels > 0 && game.completed_levels === game.win_levels ? 1 : game.completed_levels + 1;
    state.replayFollow = false; state.eventSequence = null;
    replaceSnapshot(emptyGamePreview(game), {follow:false});
    selectLevel(target - 1, {bindSavedSource:false});
  }

  function validGamePreview(value, game, selectedLevel) {
    if (!validSnapshot(value)) return false;
    const record = value.run, level = value.levels[0];
    return record.game_id === game.game_id && record.win_levels === game.win_levels && record.run_id === null &&
      record.status === 'preview' && record.seed === 0 && record.completed_level_count === 0 && record.primitive_action_count === 0 &&
      record.target_level === selectedLevel && record.replay_verified === false && record.sealed_trace === false && value.levels.length === 1 &&
      level.level === selectedLevel && level.status === 'preview' && level.frames.length === 1 && level.frames[0].grid.length > 0 &&
      level.frames[0].state === 'NOT_FINISHED' && level.frames[0].levels_completed === selectedLevel - 1 &&
      level.actions.length === 0 && level.decisions.length === 0 && array(value.decisions).length === 0 &&
      level.cognition?.scope === 'unavailable' && level.receipt == null;
  }

  function refreshLevelSource(previousSource) {
    renderRail(); renderProgressContext(); renderLevelEfficiency();
    if (levelSource().key !== previousSource) selectLevel(state.levelIndex);
  }

  async function loadSavedView(game) {
    if (!game || !verifiedSavedGame() || game.game_id !== run.game_id) return;
    if (levelReplayEnabled) return loadSavedLevelView(game);
    const bestId = game.best_run_id;
    if (savedViews.get(game.game_id)?.run.run_id === bestId) {
      const previousSource = levelSource().key;
      const key = `${run.game_id}/${primaryLevel().level}`;
      if (!boardSavedViews.has(key)) boardSavedViews.set(key, savedViews.get(game.game_id));
      refreshLevelSource(previousSource);
      return;
    }
    const generation = state.replayGeneration, currentRun = run.run_id, selectedLevel = primaryLevel().level, seed = run.seed;
    const isCurrent = () => state.mode !== 'manual' && state.replayGeneration === generation &&
      run.game_id === game.game_id && run.run_id === currentRun && $('game-select').value === game.game_id &&
      verifiedSavedGame()?.best_run_id === bestId && verifiedSavedGame()?.completed_levels === game.completed_levels && run.seed === seed;
    if (!savedRequests.has(bestId)) savedRequests.set(bestId, request(`/api/replay/${encodeURIComponent(bestId)}`).then(value => {
      if (!validSnapshot(value) || value.run.run_id !== bestId || value.run.game_id !== game.game_id ||
        value.run.seed !== seed || !matchesVerifiedSavedRun(value.run,game,seed)) throw new Error('invalid-response');
      return value;
    }).catch(error => { savedRequests.delete(bestId); throw error; }));
    try {
      const saved = await savedRequests.get(bestId);
      if (!isCurrent()) return;
      const previousSource = levelSource().key;
      savedViews.set(game.game_id, saved);
      // Authority can update the rail. Only the still-selected level accepts
      // a new board source; late replies cannot reset another level's cursor.
      if (primaryLevel().level === selectedLevel) {
        boardSavedViews.set(`${run.game_id}/${selectedLevel}`, saved);
        refreshLevelSource(previousSource);
      } else { renderRail(); renderProgressContext(); renderLevelEfficiency(); }
    } catch (_) { /* The current observation remains usable if saved evidence is unavailable. */ }
  }

  async function ensureSelectedSource() {
    if (state.mode === 'manual') return;
    const game = overviewGame(run.game_id), generation = state.replayGeneration, currentRun = run.run_id, selectedLevel = primaryLevel().level;
    if (!game || $('game-select').value !== game.game_id) return;
    await loadSavedView(game);
    if (state.mode === 'manual' || state.replayGeneration !== generation || run.run_id !== currentRun ||
      run.game_id !== game.game_id || primaryLevel().level !== selectedLevel) return;
    if (levelReplayEnabled && (levelFrameCount(primaryLevel()) > 0 || levelFrameCount(savedLevel(selectedLevel) || emptyLevel) > 0 ||
      (verifiedSavedGame()?.completed_levels >= selectedLevel && !frames().length))) return;
    if (!array(levelSource().level.frames).length) loadGamePreview(game, selectedLevel);
  }

  async function loadGamePreview(game, selectedLevel = currentLevel().level || 1) {
    if (!game || (run.game_id === game.game_id &&
        (currentLevel().status === 'preview-unavailable' || (run.status === 'preview' && currentLevel().frames.length)))) return;
    const generation = state.replayGeneration, mode = state.mode;
    const isCurrent = () => state.mode === mode && mode !== 'manual' && state.replayGeneration === generation &&
      $('game-select').value === game.game_id && primaryLevel().level === selectedLevel && run.run_id === currentRun;
    const currentRun = run.run_id;
    const key = `${game.game_id}/${selectedLevel}`;
    if (!gamePreviews.has(key)) {
      gamePreviews.set(key, request('/api/preview/' + game.game_id + (selectedLevel === 1 ? '' : '/' + selectedLevel)).then(value => {
        if (!validGamePreview(value, game, selectedLevel)) throw new Error('invalid-response');
        return value;
      }));
    }
    try {
      const preview = await gamePreviews.get(key);
      if (!isCurrent()) return;
      if (currentRun === null && !latestReplayId(overviewGame(game.game_id))) {
        replaceSnapshot({...preview, levels:levels.map(level => level.level === selectedLevel ? preview.levels[0] : level)}, {follow:false});
        write('service-status','关卡初始预览 · 尚未开始 · 可启动 P7 或选择人工试玩');
      } else {
        const previousSource = levelSource().key;
        previewViews.set(key, preview);
        refreshLevelSource(previousSource);
      }
    } catch (_) {
      gamePreviews.delete(key);
      if (!isCurrent()) return;
      if (currentRun === null) {
        replaceSnapshot({...snapshot,levels:levels.map(level => level.level === selectedLevel ? {...level,status:'preview-unavailable'} : level)}, {follow:false});
        write('service-status','初始画面暂不可用 · 尚未启动 P7');
      }
    }
  }

  function observeSelectedGame() {
    if (!state.selectionReady || state.mode === 'manual' || state.commandBusy || state.pendingCommand || !state.overview) return;
    // An operator-owned run retains its own live controls; other records are read-only.
    if (state.mode === 'live' && activeSession()) return;
    state.mode = 'replay';
    const game = overviewGame($('game-select').value);
    if (game && initialGameLevelPending) {
      initialGameLevelPending = false;
      // Apply authoritative startup progress once. Explicit cursor choices
      // already disable following and must survive a delayed first overview.
      if (state.replayFollow) selectSwitchedGameLevel(game, {force:true});
    }
    const runId = array(game?.runs).some(entry => entry.run_id === attemptReplayRun) ? attemptReplayRun : preferredReplayId(game);
    renderRunChoices();
    if (runId) {
      $('replay-run').value = runId;
      if (state.replayRun !== runId || (run.run_id !== runId && !state.replayPollBusy && Date.now() >= state.replayRetryAt)) loadReplay({ initial: true, preserveSelection:run.game_id === game.game_id && !state.replayFollow });
    } else if (game) {
      if (run.game_id !== game.game_id || run.run_id !== null) {
        stopReplayPolling(); state.eventSequence = null;
        replaceSnapshot(emptyGamePreview(game), {follow:false});
        write('service-status','尚未开始 · 正在读取初始画面');
      }
      loadGamePreview(game);
    }
    renderSessionControls();
  }

  function watchGame(gameId) {
    chooseOverviewGame(gameId, { replay: true });
  }

  async function initializeSelection() {
    await pollState();
    if (!state.liveView) return;
    if (activeSession()) { state.selectionReady = true; return; }
    if (validChoice(state.liveView.selection)) {
      state.manualChoice = {...state.liveView.selection}; $('game-select').value = state.manualChoice.game_id;
    } else {
      const manual = state.liveView.manual;
      const choice = {game_id:manual?.game_id,level:manualLevel(manual)};
      if (validChoice(choice)) { state.manualChoice = choice; $('game-select').value = choice.game_id; }
    }
    if (!state.gameSelectionTouched) $('game-select').value = array(liveConfig.games)[0]?.game_id || '';
    state.selectionReady = true;
    observeSelectedGame();
  }

  function initializeLive() {
    $('console-mode').disabled = !liveConfig;
    renderRunHeader(); selectLevel(state.levelIndex); renderSessionControls();
    $('console-mode').addEventListener('change', () => {
      if (['/api/manual/action', '/api/manual/restart'].includes(state.manualPending?.path)) { renderSessionControls(); return; }
      pause(); stopReplayPolling(); invalidateManual(); state.manualPending = null; state.mode = $('console-mode').value;
      attemptReplayRun = null;
      if (state.mode === 'manual' && activeSession()) { state.mode = 'live'; write('service-status', 'P7 运行期间无法打开人工试玩'); }
      if (state.mode === 'live' && state.liveView) { state.replayFollow = true; state.eventSequence = null; replaceSnapshot(snapshotForView(state.liveView), { follow: true }); }
      else if (state.mode === 'manual' && ['ready', 'uncertain'].includes(state.manualView?.state) && state.manualView.snapshot) { $('game-select').value = state.manualView.game_id; replaceSnapshot(manualHistorySnapshot(state.manualView), { follow: false, manualPosition: state.manualHistory?.index ?? null }); renderManualStatus(); }
      else if (state.mode === 'manual') {
        const saved = state.liveView?.manual;
        if (['ready', 'uncertain'].includes(saved?.state) && saved.snapshot &&
            (!state.gameSelectionTouched || saved.game_id === $('game-select').value)) {
          $('game-select').value = saved.game_id; acceptManual(saved);
        } else if (!state.gameSelectionTouched && validChoice(state.manualChoice)) {
          $('game-select').value = state.manualChoice.game_id; openManual(state.manualChoice.level);
        } else openManual(rememberedManualLevel());
      } else observeSelectedGame();
      renderSessionControls();
    });
    if (!liveConfig) return;
    const games = array(liveConfig.games);
    games.filter((game) => isRecord(game) && typeof game.game_id === 'string').forEach((game) => {
      const option = node('option', `${string(game.alias, game.game_id)} · ${game.game_id}`); option.value = game.game_id; $('game-select').append(option);
    });
    $('game-select').addEventListener('change', () => { state.gameSelectionTouched = true; attemptReplayRun = null; stopReplayPolling(); renderRunChoices(); if (state.mode === 'manual') openManual(1); else { selectSwitchedGameLevel(overviewGame($('game-select').value)); observeSelectedGame(); } renderSessionControls(); });
    $('run-start').addEventListener('click', () => startGame($('game-select').value));
    $('run-fresh').addEventListener('click', () => startGame($('game-select').value, true));
    ['pause', 'resume'].forEach((operation) => $('run-' + operation).addEventListener('click', () => sendCommand({ path: '/api/' + operation, body: { session_id: state.liveView.session_id, command_id: window.crypto.randomUUID() } })));
    $('run-stop').addEventListener('click', () => sendCommand({ path: '/api/stop', body: { session_id: state.liveView.session_id, command_id: window.crypto.randomUUID() } }));
    $('retry-command').addEventListener('click', () => { if (state.pendingCommand) sendCommand(state.pendingCommand); else if (state.mode === 'manual' && state.manualPending) sendManualCommand(state.manualPending); else if (state.mode === 'manual' && state.manualSaveRetry) sendManualCommand(state.manualSaveRetry); });
    $('manual-restart').addEventListener('click', () => {
      if (!manualRestartable()) return;
      pause(); state.pointerAction = null;
      sendManualCommand({ path: '/api/manual/restart', choice: { game_id: state.manualView.game_id, level: manualLevel(state.manualView) },
        body: { session_id: state.manualView.session_id, command_id: window.crypto.randomUUID(), observation_version: state.manualView.observation_version } });
    });
    $('manual-close').addEventListener('click', () => {
      if ($('manual-close').disabled) return;
      if (state.manualView?.state === 'ready' && !state.manualError) sendManualCommand({ path: '/api/manual/close', body: { session_id: state.manualView.session_id, command_id: window.crypto.randomUUID() } });
      else openManual(rememberedManualLevel());
    });
    $('replay-run').addEventListener('change', () => { stopReplayPolling(); renderSessionControls(); });
    $('replay-retry').addEventListener('click', () => replayLoad?.retry?.());
    $('replay-load').addEventListener('click', () => loadReplay({ initial: true }));
    $('replay-follow').addEventListener('click', () => { state.replayFollow = true; state.eventSequence = null; replaceSnapshot(snapshot, { follow: true }); renderSessionControls(); });
    write('service-status', '正在读取云端同步记录');
    $('overview').hidden = false; loadOverview(); initializeSelection().catch(showRequestError);
    state.pollTimer = window.setInterval(pollState, CLOUD_REFRESH_INTERVAL);
    state.overviewTimer = window.setInterval(loadOverview, CLOUD_REFRESH_INTERVAL);
    window.addEventListener('pagehide', () => { stopReplayPolling(); if (state.pollTimer !== null) window.clearInterval(state.pollTimer); if (state.overviewTimer !== null) window.clearInterval(state.overviewTimer); });
  }

  $('event-return-current').addEventListener('click', () => { if (state.liveView) { state.replayFollow = true; state.eventSequence = null; replaceSnapshot(snapshotForView(state.liveView), { follow: true }); renderSessionControls(); } });
  $('event-slider').addEventListener('input', () => setEvent(Number($('event-slider').value)));
  initializeLive();
})();
