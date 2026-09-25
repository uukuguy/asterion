# Asterion Prime P7 Evidence

> Original slice: 2026-09-10, first native `asterion.prime` AgentRuntime
> and `prime.arc-agi-3-solving@1.0.0`. Official result appended 2026-09-25.

## Claim

**Verified:** Asterion Prime, using Asterion's Pi integration and the
`deepseek-v4-flash` model, completed Level 1 of ARC-AGI-3 game
`ls20-9607627b`. The selected application and runtime contain no Prime Agent
source or SDK dependency, no seeded answer, and no preset action sequence.

This proves the native P7 application slice. It does not prove complete
Asterion Prime parity, all seven game levels, the ARC-AGI-3 suite, or product
promotion.

## Live run

| Field | Recorded value |
|---|---|
| Run | `p7-live-20260909065351` |
| Application / runtime | `prime.arc-agi-3-solving@1.0.0` / `asterion.prime` |
| Game / seed | `ls20-9607627b` / `0` |
| Model | `deepseek-v4-flash` |
| Result | Level 1 completed; terminal reason `level-completed` |
| Actions | 23 primitive environment actions; 23 action trace entries |
| Agent tools | 43 persistent IPython cells |
| Frames | 30 recorded visual frames |
| Partial game score | `3.267621` |
| Trace | 25 entries; sealed |
| Replay / cleanup | verified / complete |
| Receipt SHA-256 | `72dbca77f43b88579911883daa96250d38113e7103171c2fb125a01e152d21d9` |
| Replay SHA-256 | `sha256:ce19ada57c6bbf6c71a3091a4ea8ba4b56550b91ee948884b7ce6e51680bc6a4` |
| Final trace SHA-256 | `sha256:61d983c2eb0ab41acb6d016fafa209b0f85636ccf6edccadd226665ac39c2225` |
| Story bundle SHA-256 | `sha256:b35614f8764e6b27409f8e4777f7efab732b58161379446dea4a09da4fdc681e` |

The run predates common Pi usage normalization. Elapsed time, token usage,
and an exact model-callback count were not persisted and are therefore
reported as **not recorded**, not estimated. No comparison report was produced
for this run.

## Reproducible artifacts

- Canonical catalog: `artifacts/arc-agi-3/catalog.json`
- Normalized run data: `artifacts/arc-agi-3/games/ls20-9607627b/runs/p7-live-20260909065351/`
- Accepted analysis: `analysis-eaebabce55daf73d3eda`
- Current web render: `web-2936ab8ccd2c7b525b2d`
- Offline single-file export:
  `artifacts/arc-agi-3/exports/arc-agi-3-ls20-9607627b-p7-live-20260909065351-web-2936ab8ccd2c7b525b2d.html`
- Offline export SHA-256:
  `c8ca0a727b1b36c803f3a9b1b2e2e111424f3fbbc4964ec40f6767730a62e561`

The normalized bundle is digest-bound to the private source evidence. Public
documentation does not reproduce private prompts, provider payloads, or raw
reasoning content.

## Verification ledger

| Status | Command / evidence | Boundary |
|---|---|---|
| PASS | Original native P7 live runner | authoritative level transition, sealed trace, replay and cleanup |
| PASS | Focused native runtime/P7/Pi suite: 95 tests | native runtime and P7 implementation |
| PASS | Focused legacy preparation/lock suite: 23 tests | retained P1-P7 development preparation |
| PASS | Wrapper-removal regression: 112 Python tests | native registration, source detachment, packaging inventory and retained broker behavior |
| PASS | `npm run build --prefix packages/typescript/prime-gateway` | remaining TypeScript gateway compiles after P7 wrapper removal |
| PASS | `uv build --wheel` | wheel builds and contains no removed P7 SDK wrapper files |
| PASS | `git diff --check` | changed files have no whitespace errors |
| Not rerun | full `make test`, `make check`, `make promotion-check` | intentionally not promoted from focused research checks |
| External-limited | remaining six ARC levels and multi-game benchmark | require separately authorized model/environment execution |

## Architecture boundary and next work

`asterion.prime` and `asterion.native` are peer agent runtimes built on the
shared Asterion framework. P1-P7 are applications. P7 is the first application
implemented on the native Asterion Prime kernel; the former Prime SDK solving
provider, gateway, host, preparation route, TypeScript bridge, seeded command,
and package artifacts were removed in commit `e8ac49ec`.

Complete Asterion Prime capability parity still requires separately planned
work for its control-plane client, durable sessions and recovery, context
accounting and compaction, child-agent coordination, bounded autonomy,
continual improvement, and native P1-P6 application routes. Historical
Prime-Agent-backed development evidence remains historical evidence only.

## 2026-09-25 official Competition partial result

One operator-authorized `GAME=ls20` saved-action submission created and normally
closed official card [`14868b83-3f40-4afd-84b0-4d25176f97d0`](https://arcprize.org/scorecards/14868b83-3f40-4afd-84b0-4d25176f97d0). The original command returned `recovery-required` because its result validator rejected the official zero-action placeholders for unselected games. After correcting that rule, a GET-only public result recovery bound the card ID, complete 25-game catalog, and selected LS20 run ID to the private normal-close record. The private `official-receipt.json` is `closed-confirmed`, with closure digest `07d24be4adebe5667631aaa94bab491f056532cb39602a1d35b6c76a0e4ab9b3`.

The service reports LS20 score `3.571428571428571`, one completed level, 20 actions, and state `NOT_FINISHED`. The overall Competition score is `0.14285714285714285`; the other 24 games are zero-action, zero-score placeholders. This verifies a partial official score and the saved-action submission path. It does not establish a full LS20 win, all-game solving, or a live model Competition run. The recovery used no new card, game action, or model call. See the [operator guide](../guides/prime-p7-games-and-official-results.md) and [live checkpoint](RESUME-NEXT-SESSION.md) for commands and the current verification boundary.

## 2026-09-25 official Competition 17-game submission

With operator authorization, `make asterion-prime-p7-official-submit GAME=all` revalidated the 17 locally verified Level-1 action prefixes and played them under one new Competition card. The command exited 0 after normal closure. Local authoritative receipt: `.asterion-private/prime-p7-official/p7-live-20260925031809-dabd0f7fd2131740a0cbfacc/official-receipt.json`, schema `asterion.prime.p7-official-receipt/v1`, status `closed-confirmed`, closure digest `5a85d3ffc778bb4622ca19d215b11ee502e9b5b1dca5e7ff10964783bdf6e60b`.

Official card [`fb3e52a2-2bfe-473e-9e5c-30bcf7f2355d`](https://arcprize.org/scorecards/fb3e52a2-2bfe-473e-9e5c-30bcf7f2355d) reports overall score **`2.5044733044733043`** across the 25-game catalog. Seventeen selected games each completed Level 1 and remain `NOT_FINISHED`; eight unselected games have zero-action placeholders. No whole game was won (`games_completed=0`). Per-game scores below are the official SDK close result, not local estimates.

| Game | Official actions | Levels completed | Official score |
|---|---:|---:|---:|
| AR25 | 22 | 1 | 2.777778 |
| CN04 | 18 | 1 | 4.761905 |
| DC22 | 43 | 1 | 4.761905 |
| FT09 | 10 | 1 | 4.761905 |
| LF52 | 28 | 1 | 1.818182 |
| LP85 | 9 | 1 | 2.777778 |
| LS20 | 20 | 1 | 3.571429 |
| M0R0 | 17 | 1 | 4.761905 |
| R11L | 10 | 1 | 4.761905 |
| RE86 | 21 | 1 | 2.777778 |
| SB26 | 13 | 1 | 2.777778 |
| SC25 | 22 | 1 | 4.761905 |
| SP80 | 6 | 1 | 4.761905 |
| SU15 | 13 | 1 | 2.222222 |
| TR87 | 40 | 1 | 4.761905 |
| VC33 | 7 | 1 | 3.571429 |
| WA30 | 37 | 1 | 2.222222 |

The same 17 selected local Level-1 runs now have accepted, evidence-cited Chinese analyses and standalone offline HTML reports under `artifacts/arc-agi-3/exports/`. The local `artifacts/arc-agi-3/catalog.json` indexes all 17 current reports plus the earlier 23-action LS20 historical report. `make asterion-prime-p7-stories` opens the read-only local catalog. Each current report's run ID and action count were checked against this official receipt; its normalized data and accepted analysis remain bound to the sealed local evidence. The report's rounded local partial score is not the official score above.

## 2026-09-25 local Level-2 breadth-first results

The operator-authorized 17-game second-round campaign is complete. The local ledger is `.asterion-private/prime-p7-live/second-round-campaign.json`. Four games have a sealed, replay-verified, guest-cleaned Level-2 run:

| Game | Level-2 new actions | Local run | Provenance |
|---|---:|---|---|
| DC22 | 61 | `p7-live-20260925053157-78dacce1eddc1c81872f31ed` | passed before verified-history change |
| M0R0 | 90 | `p7-live-20260925065812-a0611a8c8f24f7ef189509d2` | passed before verified-history change |
| VC33 | 14 | `p7-live-20260925110850-b61955289cb652fe638ac65d` | newly passed after verified-history change |
| WA30 | 58 | `p7-live-20260925111620-c1c66d732b4e873ecfc2da32` | newly passed after verified-history change |

The campaign attempted each of the other 13 games once at Level 2: eleven remain unsolved at the human action cap, LP85 is `execution-failed`, and TR87 is `execution-stalled`. Neither failure category means a solved level. The final resumed command attempted only VC33 and WA30, exited 0, and recorded `newly_verified_level_two` for those two games. It used 8,119,694 input tokens (including cached input) and 153,256 output tokens for those two attempts. No new official scorecard was submitted.

An earlier paid DC22 repeat reached Level 2 in **99 new actions**, versus the previously verified **61**. It is a slower duplicate and provides no evidence of a performance gain. The intended legacy-versus-verified comparison was invalid because the guest launcher initially omitted the history-variant environment value; the comparison tool rejected it before a second arm. After the forwarding fix, a further DC22 repeat was interrupted at the user's direction and was not sealed or counted as a verified result. Further paid attempts are directed to unsolved next levels rather than repeating an already solved level.

The local single-file Chinese Level-2 reports for VC33 and WA30 are indexed in `artifacts/arc-agi-3/catalog.json` and stored under `artifacts/arc-agi-3/exports/`. They bind the source run and normalized bundle by digest. WA30's analysis passed evidence citation validation; VC33's model analysis was rejected for invalid citation format, so its page uses a fact-checked Chinese fallback summary. Neither page changes the underlying game result. `e128f3b1` updated the story evidence reader to accept the exact validated modern summary fields; 26 focused tests, Ruff and an independent code review passed.

VC33 then passed Level 3 in a separate OFFLINE run `p7-live-20260925112555-4e235588d483805a4edbfb88`: 21 verified prefix actions plus 31 new Level-3 actions, below the human baseline of 44. The run has sealed trace, replay verification and completed guest cleanup; its next-level manifest records `status=verified`. This is an additional solved level for VC33, not a replay of its Level 2. No official card was created.
An accepted Chinese analysis and standalone HTML report for this Level-3 run are also indexed in the local catalog; the export SHA-256 is `b4176df54ad83a1b3b5647bd07f7598a1a01bf06b20e10e3e6a571480c44cb19`.

WA30's first Level-3 attempt `p7-live-20260925113438-dad7330565bbe94dfbc507e0` used all 183 new actions allowed by that level's human baseline without passing it. Its trace is sealed, replay verified and guest cleaned; the broker terminal reason is `human-baseline` and the next-level manifest remains `unverified`. The prior WA30 Level-2 success remains intact. The operator moved to DC22 Level 3 rather than paying to repeat WA30 Level 3.

DC22's first Level-3 attempt `p7-live-20260925115050-aa51a29c969b32fa07662b18` replayed its 104-action verified Level-2 prefix but produced no new Level-3 action for five minutes. The supervisor stopped it and wrote a private stall receipt recording 300 seconds and `cleanup_complete=true`. Its original next-level manifest is still `unverified` with `execution-stalled-evidence-invalid`, because the validator at the time was limited to Level 2. `cbdf0a86` added strict L3+ prefix, action, usage, deadline and cleanup validation; 48 focused tests and Ruff passed, and independent review approved the actual `next-level` path. A read-only validation in an isolated installed environment with the ARC wheels now returns `True` for this original run. No raw record or manifest was rewritten. It remains an execution stall, not a Level-3 solution, and the operator did not repeat the paid attempt.

M0R0 passed Level 3 in a separate OFFLINE run `p7-live-20260925115949-e2170cc432ebeab1d5b84875`: 107 verified prefix actions plus 84 new Level-3 actions, below that level's human baseline of 203. The trace is sealed, replay verified and guest cleaned, and the next-level manifest records `status=verified`. This is a new solved level; the saved Level-2 solution was replayed rather than solved again. No official card was created.
Its standalone Chinese HTML report is indexed in the local catalog with export SHA-256 `1171cd400d24092cceb04e7e7d1b63c4a7cd77e68bba19dbc8cf59b39415db69`. The generated analysis failed citation validation, so the page uses a fact-checked fallback summary; the game success evidence is independent of that narrative.

The subsequent VC33 Level-4 attempt `p7-live-20260925121649-7604f40b2427eb2a2b401679` was operator-interrupted when the user redirected work to a breadth-first retry of unresolved Levels 1 and 2. Its trace contains only the 52 replayed, previously verified Level-3 prefix actions and no new Level-4 action. The original unsealed run and its `unverified/not-started` next-level manifest remain unmodified; guest P7 units were confirmed absent after interruption. It is neither a Level-4 success nor a completed failure attempt.

## 2026-09-25 breadth resweep pause and BP35 diagnosis

The new local breadth ledger `.asterion-private/prime-p7-live/breadth-resweep-campaign.json` began with eight unresolved Level-1 candidates and thirteen already eligible unresolved Level-2 candidates. BP35 Level 1 run `p7-live-20260925131956-015b9ec7016434350579a0c0` is a sealed, replay-verified, guest-cleaned **unsolved** attempt: 21/21 human-baseline actions, 0/9 levels, 3,166,683 input tokens including cache hits, and 86,477 output tokens. It is recorded once in the new ledger and must not be retried by this campaign.

The trace and settled recordings show seven successive green-block clicks at actions 2–8 reduced the green-cell count from 147 to zero without advancing the level. Action 12, movement to the right, changed 792 interior cells and introduced a new layout with 189 green cells; the level still remained at zero. At actions 9, 13 and 19, only one cell changed, always on the bottom edge at `(8,63)`, `(12,63)` and `(18,63)` respectively; no interior cell changed. Treating each different full-frame hash as useful game progress would overstate those three actions. The helper `diff()` currently includes these edge changes, while the prompt does not explicitly separate a moving HUD strip from gameplay. This is an observed analysis gap, not proof that a different policy would solve BP35 within 21 actions.

Verified-history/prediction wiring was active: 1 history query returned 16 records, 33 settled-frame queries, 2 checked plans covered 8 matched expectations, and there were no prediction mismatches. Thus prediction checks confirmed the local effect of selected clicks and movement but did not validate the conjectured objective “clear all green blocks.” The other 13 actions were ordinary `act` calls. Three recoverable worker-cell errors did not terminate the application; the terminal reason was the human action cap. Current judgment: premature commitment to a locally predictable click effect consumed a tight budget before the major scene transition was explored. The game's actual objective remains unknown from this evidence.

The operator paused the campaign during CD82 Level 1. Its run `p7-live-20260925132710-d537667d2929a4cbf70ac7b0` has four actions and no sealed summary; the ledger retains `running`. No guest P7 unit remained after interruption. CD82 is neither a verified success nor an admissible terminal failure, and the controller intentionally refuses automatic retry while that entry requires manual audit. No further paid run or official submission was started.

## 2026-09-25 BP35 same-game retry

The user authorized one BP35 Level-1 retry after adding generic checked failed-run facts and border/interior action feedback. The installed-wheel zero-model preflight selected exactly the two sealed BP35 failures above and `p7-live-20260925003806-41571b31a9fcc45305e4bbca` (42 action facts), seed 0 and a 21-action human baseline. The first launch, `p7-live-20260925145408-4833804854176b997bc7deaa`, failed before a game action because the solver capability still enforced an exact prompt digest and rejected appended facts. It produced no sealed solve evidence. The prompt-boundary fix passed an installed-wheel zero-model preflight before the retry was restarted; this zero-action launch must not be counted as a game attempt.

The resulting OFFLINE run `p7-live-20260925150342-922a463cdccb12142fc3bdba` **completed BP35 Level 1 in 20/21 actions**, with 1/9 levels completed. Its private summary reports `sealed_trace=true`, `replay_verified=true`, `cleanup_complete=true`, terminal `level-completed`, replay digest `sha256:bd2d6ae787be60f505eab0609bcd97ca873ec9a3bd4590572d7a4efb41d1bcbe`, and receipt digest `018e0d17ecd4fad3533efb4600aa5dc8c6c9412c635fec31311124188eefa363`. Reported usage was 2,279,608 input tokens including cache traffic and 92,448 output tokens; this is not a monetary cost estimate. The one-shot private manifest is `.asterion-private/prime-p7-live/retry-manifests/20260925T151042Z-bp35-0a0ad940-level-1.json`. The paused breadth ledger was not used or changed, and no official scorecard was submitted.

| BP35 Level-1 run | Result | Actions | Border-only actions | Distinct interior states | Input / output tokens |
| --- | --- | ---: | ---: | ---: | ---: |
| First sealed failure `p7-live-20260925003806-41571b31a9fcc45305e4bbca` | 0 levels | 21 | 6 | 14 | 2,449,935 / 75,096 |
| Breadth failure `p7-live-20260925131956-015b9ec7016434350579a0c0` | 0 levels | 21 | 3 | 18 | 3,166,683 / 86,477 |
| Checked-fact retry `p7-live-20260925150342-922a463cdccb12142fc3bdba` | **1 level** | **20** | **0** | **19** | 2,279,608 / 92,448 |

The successful run began with seven movement actions, first clicked on action 8, and advanced on action 20. Action 4 changed 1,122 interior cells; action 9 changed 1,357. It did not repeat the breadth failure's opening seven-click sequence. This is a real one-run improvement in outcome and a changed exploration pattern. A single successful retry does not establish general BP35 reliability or isolate which guidance element caused it. The local run-story bundle was compiled and its offline Chinese HTML indexed in `artifacts/arc-agi-3/catalog.json`; the generated analysis failed format validation, so the page uses fact-checked fallback copy. The successful level is a reusable local prefix for Level 2, not a complete nine-level game win.

## 2026-09-26 breadth resweep continuation

The operator authorized continuation. The CD82 Level-1 `running` entry was reconciled by a zero-model trace-chain, recording-identity, action-count and usage audit into an explicit `interrupted` entry, retaining the original four-action unsealed run. No level outcome was inferred from it. The breadth controller now permits exactly one replacement formal attempt while preserving that audit row; focused tests passed. Installed-wheel preflight listed seven unresolved Level-1 games and fourteen eligible Level-2 games, including BP35 Level 2 and excluding its completed Level 1. The breadth process started with CD82 Level 1.

CD82 Level 1 then passed in a new OFFLINE run `p7-live-20260925155253-959e7fab2ce06d7828d4652a` in **28/55 actions**. Its summary reports `sealed_trace=true`, `replay_verified=true`, `cleanup_complete=true`, terminal `level-completed`, and replay digest `sha256:50e735e76c00147fc032760619bf968ad093f04f7d04579746ed69d485a5a3c2`. The breadth ledger records `verified` in a separate row after the retained `interrupted` row. A Chinese offline HTML page is indexed in `artifacts/arc-agi-3/catalog.json`; the model narrative failed citation-format validation, so the page uses factual fallback. The active breadth process moved to G50T Level 1; later outcomes must be read from the live ledger and verified individually.

S5I5 Level 1 then passed in OFFLINE run `p7-live-20260925162722-148b5d47a5b0f27e9f0cc895` in **19 actions**, with 1/8 levels completed. Its private summary reports `sealed_trace=true`, `replay_verified=true`, `cleanup_complete=true`, terminal `level-completed`, replay digest `sha256:7653c3abf4a32655d4e51113ccb7338a40191b04f0e3f9ec5aa8751c20703980`, and receipt digest `c49746d97163dac74e85be67ec74233d65ff93f7aa0d558a024f28bed7c776da`. The run-story bundle was compiled and its standalone Chinese HTML is indexed in `artifacts/arc-agi-3/catalog.json` under export SHA-256 `sha256:02e0c907639dab6b5f4a88280f262134354e3972d16b3ae0132e25642411fc3b`; the analysis used deterministic factual fallback (`status=unavailable`) and did not invoke a narration model. This verified prefix is eligible for Level 2 in the continuing breadth sweep.

TU93 Level 1 then passed in OFFLINE run `p7-live-20260925164956-a2ddcdca8d104314b5dbed63` in **19/19 actions**, with 1/9 levels completed. Its private summary reports `sealed_trace=true`, `replay_verified=true`, `cleanup_complete=true`, terminal `level-completed`, replay digest `sha256:c63c7547461c7eeb54f60466ad898a3166fbd196f5af8115262d8089b5c80701`, and receipt digest `a0188334dd2839f89b74a8d9e166a844ce3fd713cc3b44387e98b4420a2acef2`. The run used 295,056 input and 11,439 output tokens. The run-story bundle was compiled and exported as `artifacts/arc-agi-3/exports/arc-agi-3-tu93-0768757b-p7-live-20260925164956-a2ddcdca8d104314b5dbed63-web-14c538e19938c6bed3dc.html` under export SHA-256 `sha256:cce564e8e8f8789af2016aea0c331ab5d93cbe61059d677c5605b89ce1b22ac8`; the analysis used deterministic factual fallback (`status=unavailable`) and did not invoke a narration model. This verified prefix is eligible for Level 2 in the continuing breadth sweep.
