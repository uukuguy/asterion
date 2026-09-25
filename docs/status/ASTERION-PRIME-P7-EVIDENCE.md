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
