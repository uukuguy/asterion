# P7 实时主流程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** `make p7-console` 打开控制台，点击启动后实际运行有限自主 P7，持续显示真实帧、决策摘要、动作和认识更新，并可可靠结束。

**Architecture:** Mac 应用服务复用现有 Make/wheel/Orb operator；guest 用已有 systemd containment 管理后代。应用事件在 source 写入，Mac 只读取绑定 run 的安全快照。离线导出仍自包含。首包不实现人工模式或可恢复暂停。

**Tech Stack:** Python stdlib HTTP/thread/subprocess、现有 ARC operator、内嵌 Tailwind、原生 JS、Pi TypeScript 应用工具。

## Global Constraints

- P7 自主解题为主；人工验证独立，不进入 P7 工作流。本包不实现人工执行。
- 浏览器启动固定有限 level-witness 预设（首版 LEVEL=1），只选本地确切题目，不提供 provider/model/成本/deadline 控件。
- 页面打开不调用模型；浏览器断线不终止有限自主任务。停止必须确认 guest unit 与后代清理，再允许重开。
- 所有控制服务留在 Prime/P7 应用层，不增加通用 runner 或修改闭合协议。
- source 决策摘要是 P7 显式简短输出；不读取 provider 原文、私有思维或 stderr 给浏览器。不补造未记录解释。
- 事件、帧和认识必须绑定相同 run/游戏/观察或动作序号；旧记录范围保持诚实。
- 离线 `connect-src 'none'` 不变；实时同源，Host/Origin/token 校验，私有路径和配置不出 API。
- 本次使用分支 `feat/p7-live-console`；已有批准设计在 `docs/superpowers/specs/2026-10-05-prime-p7-console-modes-design.md`。

## Task 1: Source 过程事件和 P7 决策摘要

**Files:** Create `src/asterion/applications/prime/p7/console_events.py`, `tests/test_prime_p7_console_events.py`; modify `operator.py`, `ipython_host.py`, `live.py`, `prompt.py`, `tool_registry.py`, `console_snapshot.py`; TypeScript `src/ipython-extension.ts`, matching extension tests and packaged `resources/ipython-extension.mjs`.

**Interfaces:**

```python
# source writer; writes only bounded public game-process records
class ConsoleEventWriter:
    def __init__(self, run_root: Path, run_id: str, game_id: str): ...
    def append(self, kind: str, payload: Mapping[str, object]) -> None: ...
# P7 intentionally supplies a concise public summary before a plan.
def decision(self, payload: Mapping[str, object]) -> Mapping[str, object]: ...
# registered p7_decision inputs: {goal, basis, expected}; each nonempty <=600 chars.
```

- [x] Add failing writer/reader tests: exact identity, contiguous event sequence, bounded prose/redaction, incomplete tail, wrong run rejected; a recorded decision links only subsequent matching actual actions; cognition revision binds to an actual observation.
- [x] Writer emits `{schema, run_id, game_id, sequence, kind, payload}` to `console-events.jsonl`, flushing complete newline rows. Source observation/action positions are `len(broker.journal)` and transition before/after digests. Include decision ID and actual action sequences; no authority effect.
- [x] Register real `p7_decision` in Pi, allowlist, facade and both dispatch paths. Chinese prompt requests public goal/basis/expected before significant action plans, keeping decisions optional for backward compatibility. Missing summary remains missing.
- [x] Capture initial and refreshed bounded `cognition_narrative_zh`, stable description, session state and source action sequence without raw prompt/ledger/provider payload. Capture the initial observation and each settled transition through the application broker observation listener; `_record_transitions` retains trace handling without duplicate source events. Associate the pending summary only with a plan whose starting position matches. Invalidate on changed position/new plan.
- [x] Extend snapshot projection to read safe event prefix without final summary, add source decisions and action `decision_id`, plus `cognition_timeline` keyed by actual action/frame. Preserve final-scope fallbacks for older runs. No action match is inferred from timing alone.
- [x] Run `uv run python -m unittest -q tests.test_prime_p7_console_events tests.test_prime_p7_console tests.test_prime_p7_console_export` and affected facade/bridge suites. Run `npm --prefix packages/typescript/asterion-prime-extension test` and sync-resource. Expected: passing targeted checks; record any source-detachment baseline failures separately.

## Task 2: Bounded run supervisor and loopback application

**Files:** Create `console_session.py`, `console_server.py`, `tests/test_prime_p7_console_session.py`, `tests/test_prime_p7_console_server.py`; modify `game.py` public metadata accessor, `operator.py` optional console run-ID selection, `tools/p7_guest_environment.txt`, `tools/run_prime_p7_guest.py`, contained witness branch in Makefile.

**Interfaces:**

```python
class ConsoleSession:
    def start(self, game_id: str, command_id: str) -> dict[str, object]: ...
    def stop(self, session_id: str, command_id: str) -> dict[str, object]: ...
    def view(self) -> dict[str, object]: ...
    def close(self) -> None: ...
# view {session_id, state, game_id, run_id, cleanup_confirmed, snapshot, revision}
# HTTP GET /api/state, /api/games, /api/runs
# POST /api/start {game_id,command_id}; /api/stop {session_id,command_id}
# GET /api/replay/<validated known run_id> returns safe snapshot, never file bytes
```

- [x] Test with injected fake process/cleanup: concurrent start accepted once, idempotent request, stop during startup, completed receipt vs exit0, failed cleanup prevents restart, browser read/disconnect does not cancel. No tests invoke model.
- [x] Allocate known `live.safe_run_id()` before launch. Pass only optional exact validated `ASTERION_PRIME_P7_CONSOLE_RUN_ID` through fixed guest environment; ordinary operator runs retain generated IDs. Bind snapshot to that directory and selected game; never read latest for active session.
- [x] Reject reused run directory; optional run ID must match `p7-live-[0-9]{14}-[0-9a-f]{24}` exactly and come from process environment before dotenv merging. Before launch clear inherited unbounded, run/attempt identity and OPERATION_MODE flags, plus MAKEFLAGS/MFLAGS/MAKEOVERRIDES/GNUMAKEFLAGS/MAKEFILES. Add one contaminated-environment test.
- [x] Start fixed argv `make asterion-prime-p7-level-witness GAME=<catalog id> LEVEL=1 ASTERION_PRIME_P7_ATTEMPT_UNIT=<owned unit> ASTERION_PRIME_P7_ATTEMPT_SECONDS=900` with fixed root, known run-ID env and a new process group. No browser-controlled executable or path. Drain/discard stdout/stderr; use only structured artifacts for browser data.
- [x] Extend existing containment conditional to witness with server-owned unit. Stop Mac process group before guest cleanup, wait/reap, kill as needed. Reuse exact owned unit via Orb cleanup. Guest stop timeout >=30s, host cleanup >=40s; verify inactive/not-found + cgroup unpopulated. Watchdog owns fixed deadline and shutdown cleanup.
- [x] Console witness requires all three controlled values together: strict console run ID, `asterion-p7-[0-9a-f]{32}.service`, and positive 900 seconds. Reject missing/invalid values, never use the sweep zero/unbounded sentinel. Preserve existing sweep behavior.
- [x] Scan local known metadata and safe recorded runs. Runtime snapshot tolerates absent summary and complete JSONL prefixes; compare content excluding generated_at to increment revision only on actual changes. Finite polling client may use GET state every second as event transport for first package; chronological source events remain in snapshot.
- [x] Server binds 127.0.0.1 only, fixed routes, exact Host, Origin/token required for writes, bounded JSON, no arbitrary files/CORS. Service-level writes serialized; do not hold response lock during slow cleanup. Unknown session/actions/provider parameters rejected. Opening HTML is provider-free.
- [x] Run `uv run python -m unittest -q tests.test_prime_p7_console_session tests.test_prime_p7_console_server`; test actual local HTTP with no model and fake process. Shutdown test confirms owned cleanup path.

## Task 3: Shared realtime P7 UI and offline compatibility

**Files:** modify `console_export.py`, `console_assets/index.html`, `app.js`, `styles.css`, `tests/prime_p7_console_dom.cjs`, exporter tests.

**Interfaces:**

```python
def render_console(snapshot: dict[str, object], *, live_config: dict[str, object] | None = None) -> str: ...
# same HTML; live_config holds same-origin token + catalog only, never host paths.
```

- [x] Default live work area: catalog selector, 启动 P7 / 结束运行, service/session status and latest frame. No manual dispatch and no fake pause control. Manual validation labelled not yet available. Replay remains selectable and has its own transport controls.
- [x] `app.js` accepts validated snapshot replacement, preserves selected historical frame in replay, follows newest observation in live mode. Separate play/pause (replay animation) from actual run start/stop. Poll only when live_config exists; offline export makes zero network requests.
- [x] Render explicit P7 goal/basis/expected summaries and linked actual results. WorldMap uses source-associated cognition timeline; old final cognition remains final. Show per-action/cognition changes without inventing explanations. Compact action keys remain observational in P7 live mode.
- [x] DOM tests use mocked fetch and actual assets: idle initialization makes no start POST, user start chooses exact game, same command retry ID, polling refreshes true frame and process, stop includes session identity, replay does not stop solver, disconnected UI retains frame and reports status, offline no requests, malformed responses fail safely.
- [x] Regenerate real HTML and run focused DOM with `P7_CONSOLE_HTML` plus exporter tests. Build and isolate installed-wheel render to verify assets and CSP.

## Task 4: Entry point, source review and real witness

**Files:** first-party CLI route, Make `p7-console` service launcher, `docs/guides/prime-p7-games-and-official-results.md`, existing status files. Keep `asterion-prime-p7-console` export-only and optional recorded RUN override.

- [x] `make p7-console` launches `asterion arc-console serve` with operator-owned roots/guest config and opens existing default browser. No required long path. `make asterion-prime-p7-console` unchanged. Server can `--no-browser` for verification.
- [x] Independent source/contract review and resolve material findings. Run focused Python/DOM, TypeScript extension test, lint, docs-check, promotion-check once final code is stable. Preserve full logs and do not attribute unknown failures without evidence.
- [x] Build wheel, use isolated export/server smoke test, then one real packaged SP80 LEVEL=1 bounded run through live service start. Observe initial frame, model summary if emitted, real action feedback and source cognition. Normal incomplete result is reported as incomplete, never capability PASS. Explicit stop + guest cleanup verify no residual owned processes.
- [x] Update approved design status, implementation checkboxes, JOURNAL/CURRENT/RESUME/INDEX. Commit focused delivered packages; distinguish implemented, provider-free verified, live witness, external-limited visual acceptance and no proven game completion.

## Scope self-review

This plan implements the first approved package and its deployment proof. Resumable P7 pause and independent manual verification remain subsequent packages. No shared human/P7 state, human-derived experience or manual-first flow is introduced. Finite snapshot polling is the first live event transport; source event associations remain durable for offline replay. The UI does not claim unavailable controls are present.

## Delivery evidence — 2026-10-05

- Implementation `ed6fa64b`; repeated-frame fix `004442f2`; guest-only proxy preservation `9e98b49e`. Independent final source reviews PASS.
- Final installed wheel ran `p7-live-20261005063214-b9a30b6cbfd609490469887f` through the live HTTP start route. SP80 L1, `openai-codex/gpt-6.1-sol`: 2 public P7 decisions, 5 settled actions, 33 real frames and 5 source cognition versions. All actions retain source sequence and decision links. Explicit stop returned stopping, then cancelled with cleanup confirmed. Exact guest unit/cgroup and host parent were independently absent. Zero completed levels; this is process verification, not solving proficiency.
- Final real-run self-contained HTML: `/tmp/p7-live-console-final-run.html`; 28 actual-asset DOM checks PASS. Final guest/CLI/session checks: 29 OK, one existing opt-in Orb skip. Broader source checks: 297 OK, one skip; service/CLI checks 21 OK. Root lint/docs/diff checks PASS.
- Full promotion non-PASS: 3861 tests, 13 failures, 5 errors, 4 skips. Complete log `/tmp/p7-live-console-promotion-full.log`. Known failures remain in source-detachment test literals, legacy preset/fixture/API, cognition ANSI logging, replay digests and sweep boundaries. Full npm also remains non-PASS (29 pass, 2 descriptor timeouts, 6 skips); targeted real tool/resource checks passed. No full-gate PASS or merge claim.
- Initial two deployment runs stopped before actions because systemd dropped Orb-resolved proxy environment. No-auth probes isolated that boundary; the guest-only fix restored actual model/decision/action operation. No model, credentials, CA or shared ORBENV change. Temporary diagnostic entry removed; all owned services stopped.
- Browser visual acceptance remains external-limited by unavailable cached browser runtime. No alternate profile was created. Resumable pause and independent manual execution remain future packages.


## Follow-up: open a playable independent game — 2026-10-05

User requests selection to show the real initial frame and immediately permit human play. This activates the independent manual package without changing P7 autonomy.

- [x] Isolated SDK-only manual worker. Temporary recordings, no broker/model/cognition/experience access. Finite actions, command deadlines, idle expiration and verified shutdown.
- [x] Same-origin protected open/action/close API. Exact catalog, session and observation identity; command deduplication; no queued stale clicks. P7 start closes manual first and opens a fresh solver run.
- [x] Selection opens a clearly marked manual game. Compact action buttons and explicit coordinate input update real frames. P7 live remains read-only; replay remains independent.
- [x] Focused Python/actual-asset DOM checks, source review, installed-wheel real manual actions, lifecycle cleanup, lint/docs/promotion checks. Report boundaries and commit code/state.

Evidence: 79 focused Python PASS; actual SDK HTTP SP80 3 independent actions and cleanup PASS; independent review fixes verified; 39 DOM and wheel checks passed. Full promotion remains non-PASS (3879 tests, 13 failures, 5 errors, 4 skips). No new P7 completion or manual trajectory export.


## Follow-up: direct human levels and remembered selection — 2026-10-05

User approved restoring both game and level across restart, and direct level selection for independent human play. P7 remains a separate fresh L1 run.

- [x] Current action uses button highlight only; ACTION6 arming remains distinct.
- [x] HUMAN-only pinned SDK selection/reset adapter; actual current level is separate from real completed score.
- [x] Validated metadata preference; page restores active sessions first, otherwise saved choice. Busy selection is blocked; delayed retries keep latest choice.
- [x] Focused Python/DOM tests, independent source review and installed-wheel real SP80 L1/L2/L6 actions, reset, restart and cleanup.

Actual smoke performed six human actions, zero P7 actions and zero artificial completions. Detailed counts and full-gate status are recorded in `docs/status/ASTERION-PRIME-P7-EVIDENCE.md`.


## Follow-up: reliable human clicks and browser history — 2026-10-05

Files: `console_assets/app.js`, `index.html`, `styles.css`; DOM regressions in `tests/prime_p7_console_dom.cjs`. Host/controller APIs remain unchanged. Design follows the same independent HUMAN boundary.

- [x] Reproduce unchanged-poll button replacement and focus loss; test sending, no-change acknowledged execution and uncertain retry before implementing stable keyed controls.
- [x] Add bounded browser-only same-session observation/action history; exact links, no duplicate polls/retries, explicit gaps and RESET episode distinction.
- [x] Reuse slider/playback, add compact clickable action queue and return-to-current. Historical views reject actual commands; unchanged polls preserve seek position.
- [x] Run focused DOM/Python, isolated wheel plus real SDK HTTP/action-history integration, source review and lint/docs/promotion. Record exact boundaries and commit.

Verification command: `NODE_PATH=/tmp/asterion-console-tailwind/node_modules node --test tests/prime_p7_console_dom.cjs`; then the named installed-wheel/manual HTTP smoke and related Python console suite. Actual manual route tests establish interface behavior only, not P7 proficiency.

Final follow-up: 112 Python, 54 installed-export DOM and installed real SDK/served-HTML integration pass. Eight human actions, nine actual frames; cross-level playback and cleanup verified, zero P7 requests. Independent final review passes. Full promotion remains non-PASS; browser visual acceptance remains external-limited. See the existing evidence file.
