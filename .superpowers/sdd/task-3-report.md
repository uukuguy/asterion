# Task 3 report: shared live/offline P7 console UI

## Implemented

Owned changes: `console_export.render_console` only; `console_assets/index.html`, `app.js`, `styles.css`; `tests/prime_p7_console_dom.cjs`; `tests/test_prime_p7_console_export.py`. CLI/main edits belong to root Task 4. No commit made, as requested.

- `render_console(snapshot, *, live_config=None)` embeds separate script-safe JSON configuration, permits only token and public catalog fields, hashes exact inline JS/CSS/data/config bytes. Offline CSP remains `connect-src 'none'`; live permits same-origin requests only.
- Live configuration selects the P7 work area by default: exact catalog selector, actual start/stop, source session status, latest observed frame. Actions remain observational; replay transport is hidden in live mode. Manual validation is explicitly not implemented. Opening the page performs state/runs reads only.
- Fixed GET state/runs/replay and POST start/stop routes use `X-P7-Console-Token`. Start selects the exact game; stop includes the current session ID. A retry preserves its command ID and body. Fixed public messages cover disconnection, rejected requests and malformed responses; exception details never render.
- Snapshot replacement validates basic nested structure and run identity before changing the screen. Live follows the newest source frame; replay preserves the selected historical frame ID and separately loaded replay runs stay isolated from live polling. Older revisions cannot revert a newer command result. A new session/game with no snapshot clears previous frame/cognition; disconnects within the session retain the last frame.
- Explicit `p7_decision` rows show recorded goal/basis/expected and linked observed action results. WorldMap follows the source-associated cognition timeline at or before the selected source frame. Intermediate frames cannot see later cognition. Legacy final cognition retains its explicit final/unaligned boundary. Timeline updates and per-action associated cognition are displayed without synthesizing explanations.
- Offline exports perform zero requests; replay play/pause controls animation only and never send solver stop.

## Verified facts

TDD: new live/timeline/config tests failed before implementation; later race and new-session clearing tests also failed before their fixes.

- `uv run python -m unittest -v tests.test_prime_p7_console_export` — 12 PASS.
- `uv run ruff check src/asterion/applications/prime/p7/console_export.py tests/test_prime_p7_console_export.py` — PASS.
- `git diff --check` — PASS.
- `uv run asterion arc-console --output /tmp/asterion-task3-console.html` — actual historical run `p7-live-20261004140407-76efe9d22e179d6db7810496` exported successfully, no model execution.
- `uv build --wheel --out-dir /tmp/asterion-task3-wheel` plus isolated `/tmp/asterion-task3-installed` install — PASS. Python `-I` from `/tmp` confirmed imports from site-packages, rendered live/offline HTML, and verified every exact inline resource/data/config CSP digest.
- `P7_CONSOLE_HTML=/tmp/asterion-task3-installed-console.html NODE_PATH=/tmp/asterion-console-tailwind/node_modules node --test tests/prime_p7_console_dom.cjs` — 18 PASS, zero skipped. Includes actual historical installed-wheel HTML, offline zero network, live request controls, retries, source cognition, isolation, disconnection/malformed responses, stale revision race and session change clearing.
- `PYTHONPATH=. uv run python /tmp/asterion-task3-http-check.py` — PASS: real `create_console_server` HTTP + shipped rendered HTML/assets + jsdom, `ConsoleSession` with injected fake process/cleanup. Idle no POST; exact-game start; sourced frame/cognition refresh; matching session stop and cleanup confirmed. Exactly one injected launcher and one cleanup observed. Harness exits and joins server/builder threads; no real make, guest or model execution.

## Integration boundaries

The UI freezes to server revision as a nonnegative monotonic integer and nullable snapshot/identities; served server implementation agrees. GET replay returns a snapshot directly. Games are embedded in live configuration; polling reads state and initial runs, not model endpoints.

An earlier expanded Python run of exporter/snapshot/source suites reported 48 PASS and 2 source projection failures: explicit reset action dropped, recording-gap expected frame ID mismatch. Reported to root/source owner, not modified by Task 3. Those source tests require a fresh integrated rerun after source owner's fixes.

No real browser visual/pixel layout verification, authenticated browser operation, actual guest P7 solve, or promotion deployment is claimed here. Root's final integration, promotion checks and any authorized real witness remain separate required boundaries. The HTTP harness is temporary `/tmp` evidence; stable regression coverage is the checked-in DOM suite.

## Task 3 important review fixes

Both Important findings in `task-3-review.md` are fixed. This follow-up modifies only `console_assets/app.js`, the checked-in DOM suite, and this report; exporter/main and other workers' sources were not changed.

1. Replay loads now capture a request generation. Changing mode, changing the selected run, or starting another load invalidates earlier requests. After await, the handler confirms current replay mode, generation and exact selected run before validation or replacement. Superseded responses and their errors are discarded. `replayRun` commits only after replacement succeeds.
2. Snapshot validation now checks both global and per-level decision records, cognition timeline/updates/change records, action meaning records, and renderer-used identity/string/numeric metadata before any display mutation. The full next derived level view is built before assignment. Replacement publishes `window.__ASTERION_STATE__` only after rendering completes; rendering failure restores the prior internal snapshot/selection and attempts to restore its frame. `acceptView` advances `state.liveView`/revision only after successful replacement. A rejected or failed response therefore leaves the same revision available for a subsequent valid recovery.

Regression evidence (actual commands were run):

- Initial `NODE_PATH=/tmp/asterion-console-tailwind/node_modules node --test tests/prime_p7_console_dom.cjs` after adding regressions: **19 PASS, 6 FAIL, 1 SKIP**. The failures reproduced delayed replay after mode switch, superseded replay requests, global `[null]` decisions, `[null]` cognition updates/changes, and publishing after render failure. Existing level decision/timeline invalid-record guards passed.
- Added action metadata and cognition type cases plus a no-paint assertion to prove precommit rejection rather than post-render rollback: **25 PASS, 2 FAIL, 1 SKIP** before their field validation. These failures detected rendering/repainting before rejection of malformed scalar metadata. After validation both pass without repainting.
- Final real historical document command: `uv run asterion arc-console --output /tmp/asterion-task3-console.html` — exit 0; selected the historical `p7-live-20261004140407-76efe9d22e179d6db7810496` run.
- `P7_CONSOLE_HTML=/tmp/asterion-task3-console.html NODE_PATH=/tmp/asterion-console-tailwind/node_modules node --test tests/prime_p7_console_dom.cjs` — **28 PASS, 0 FAIL, 0 SKIP**.
- `uv run python -m unittest -v tests.test_prime_p7_console_export` — **Ran 12 tests; OK**.
- `uv run ruff check src/asterion/applications/prime/p7/console_export.py tests/test_prime_p7_console_export.py` — **All checks passed!**
- `git diff --check` — exit 0, no output.
- `PYTHONPATH=. uv run python /tmp/asterion-task3-http-check.py` — exit 0: **Served real assets: idle no start; exact-game start; sourced frame/cognition refresh; session stop and cleanup confirmed.** FakeProcess injection remains provider-free.
- Rebuilt with `uv build --wheel --out-dir /tmp/asterion-task3-wheel`, reinstalled the wheel into `/tmp/asterion-task3-installed`, then isolated Python `-I` from `/tmp` confirmed site-packages imports and hashes for all rendered live/offline JS/CSS/data/config bodies: **Installed wheel live/offline resources and CSP verified.**
- `P7_CONSOLE_HTML=/tmp/asterion-task3-installed-console.html NODE_PATH=/tmp/asterion-console-tailwind/node_modules node --test tests/prime_p7_console_dom.cjs` — **28 PASS, 0 FAIL, 0 SKIP** against the newly installed wheel's historical HTML.

No commit made. These checks remain UI/renderer/provider-free integration evidence; no new real guest solve, browser pixel acceptance, or deployment claim is introduced.

Cross-task renderer format check: source cognition `stable_description` must preserve its safe newlines so WorldMap can parse `游戏类型`, `画面物件`, and `动作操作` as separate sections. The existing source-timeline DOM case now uses a multiline description and asserts separate rendered values; the unchanged UI consumer supports that shape. Re-running the installed-wheel real HTML DOM command after this fixture strengthening reports **28 PASS, 0 FAIL, 0 SKIP**. Root assigned source writer newline preservation to the source owner; this consumer check does not itself prove that writer change or promote it to source end-to-end verification. Decisions remain single-line under the source contract.
