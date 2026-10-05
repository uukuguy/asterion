# Live Session Checkpoint

Updated 2026-10-06 00:34 CST. Active work; not a handoff.

## 已验证事实

- Branch `feat/p7-live-console`. Current console worklist is `docs/superpowers/plans/2026-10-05-p7-worldmap-solver-redesign.md`; the broader design contract is in the matching spec.
- New overview covers the fixed local catalog of 25 games / 183 levels. Only exact WorldMap P7 records with model `gpt-6.1-sol` and seed 0 count. Old `dc22`/`vc33` progress and actions are excluded. A game selects its run by most completed progress, then highest RHAE, then fewer actions. Per-game score uses the full-game denominator; unplayed games score 0 in the local 25-game average.
- Console exposes public `/api/start` with an explicit target and exact resume source. The UI automatically opens the latest replay for the selected game; there is no multi-run chooser. History cursor is pinned; externally launched runs are read-only. Fixed aliases are `replays/sp80.html` and `p7-console.html`; `make p7-replay GAME=sp80` and `make p7-controller` are entry points.
- User’s canonical controller URL is `http://127.0.0.1:57515/` and remains fixed across restart. Legacy port 56659 is idle and within task scope; do not recommend it as the main URL. Metadata files `launches/p7-controller-server.json` and `launches/p7-controller-server-56659.json` and their processes remain active. Do not stop them during this active session.
- SP80 full WIN run `p7-live-20261006001222-3a7662493aa44f01b109e5f9`, guest unit `asterion-p7-132187b58696406ba1864d7a3d8d2804.service` now inactive. Result 6/6, 143 actions = 95 restored + 48 new, RESET=2 (an older summary incorrectly said 0; earlier runs had 0). Seal/replay/cleanup true; receipt 100. Local standing is 1/25 games, 6/183 levels, 4%. Eight cells; actual DOM 92 research cursors PASS, no JS errors or network requests. Private acceptance file: `launches/p7-live-20261006001222-3a7662493aa44f01b109e5f9/console-acceptance/final-summary.json`.
- Earlier warm-five source `p7-live-20261005235518-0401f6db49354f27bca12e60`: 143 actions = 67 restored + 76 new, successful prefix 95, failed tail 48, 900 seconds. It is historical evidence, not an active process.
- DC22 fresh run `p7-live-20261006002338-7fc5ecf2b7ca4c5e8a827607`, guest unit `asterion-p7-43e92fd0c88642658a4f73a00494c584.service`, stopped on `_CallbackRejected` / `prime-event-type` in `pi.prompt`: 14 actions, 0 completed levels, 5 cells; cleanup true, unsealed/unreplayed. This is a runtime interruption, not a solving failure. Root is fixing the run path; do not relaunch/duplicate DC22 until that fix is ready. Private `launches/attempt-progress.json` tracks roster and attempts.
- User explicitly authorized all 25 games sequentially: DC22 → VC33 → remaining catalog, skipping completed SP80; one finite guest at a time. After two failed attempts on the same blocked level, switch games; a success resets that level’s failure counter. This supersedes older “25 unauthorized” wording. The user additionally authorized exactly one complete 25-task official submission, only after finite DC22 and VC33 attempts finish (regardless of completion): pause remaining local games, let root perform the official submission and record official score/channel, then resume remaining local games. This does not authorize repeated or open-ended livebench runs.
- Exact resume currently restores the successful action prefix only. Latest WorldMap may include failed semantic knowledge as advisory; failed action tail, cells, kernel state, zero-level failure experience, and program/source state are not restored. Root is to design and implement the full failure-experience reuse contract next. Do not claim a retry has high success probability.
- Related checks: overview Python 59, export 14, CLI 3 PASS; final actual static/export DOM is 86/86 PASS, 0 skips. Command: `NODE_PATH=/tmp/asterion-console-tailwind/node_modules P7_CONSOLE_HTML=<persistent replays/sp80.html> node --test tests/prime_p7_console_dom.cjs`; log `launches/console-overview-acceptance/final-dom.txt`. Lint/docs passed earlier. Mandatory promotion latest: 3990 tests, 14 failures / 4 errors / 4 skips, non-PASS; one additional failure remains unclassified. Log is private `launches/p7-overview-promotion.log`. Do not call all failures historical or repeat full suite.
- Four console worklist items are implemented and targeted-verified; final actual static/export DOM passed 86/86 with 0 skips. Root HTTP/DOM review and commit coordination remain pending.

## 当前判断 / 下一动作

1. Root next owns the full failure-experience reuse contract and implementation. Zero-level failed attempts, failed action tails, and program/source restoration are not implemented; do not infer them from advisory WorldMap text or successful-prefix restore.
2. Console static/export DOM is complete at 86/86 PASS. Root should finish HTTP/commit integration without losing those verified facts.
3. Repair the DC22 runtime callback path before any retry. Then finish finite DC22 and VC33 attempts; preserve the two-failure switching rule and skip SP80 as completed.
4. After those attempts, pause remaining games for the single authorized official 25-task submission; record score/channel, then continue the local sequence.

## 历史归档

- Previous SP80 two-level and warm four-level runs remain bounded historical witnesses, superseded as current progress by the sealed 6/6 WIN above.
- The earlier statement that 25-game work was unauthorized is superseded by the current explicit local-sweep authorization. Formal benchmark/submission remains outside it.

## 未完成边界

- Local standing 1/25 is not the authorized sweep’s completion. The one explicitly authorized official 25-task submission is pending finite DC22/VC33 attempts and root’s fix for the DC22 runtime callback interruption.
- Console final root acceptance/commit remain pending.
- Exact resume does not recover failed-tail actions, computation cells or live kernel. A separate failure-experience reuse contract is being prepared; zero-level failed-run reuse is not yet connected.
- Full promotion is non-PASS; its one additional failure has not been classified.
- Public endpoints must remain free of prompt, answer, credential, provider payload, corpus text, raw output and private paths.
