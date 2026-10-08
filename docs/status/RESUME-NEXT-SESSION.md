# Live Session Checkpoint

Updated: 2026-10-08 after Task21 settlement. Session remains active; this is not a final handoff.

## Current intent and next action

User wants LLM autonomous reasoning with complete objective facts and reliable generic harness. Latest request: after this trial, analyze death-triggered RESET causes and improvements. Analysis is complete in [the canonical comparison](../reviews/2026-10-08-p7-continuity-bp35-comparison.md). No new code repair or game trial is authorized. Discuss concrete generic/P7 improvements when requested; avoid mandatory cognitive forms, every-step prediction gates or game-specific known-route hints.

## Current source and configuration

- Branch feat/prime-research-notes; production1a22dc33. Task21 adds only factual scoring paragraph and budget.scoring, preserving the original actor goal/behavior from9b62d2c2. score.py unchanged;49 focused tests passed. Generic schema/RPC/config repairs remain.
- Operator.env openai-codex/gpt-6.1-sol/medium, ASTERION_PRIME_EFFORT takes precedence. Preserve credentials; do not print whole.env.
- No active trial. Task21 owned host/guest processes and temporary auth/environment removed, exact unit7a6e9c2a4fd947d2800595330a3dc376 stopped. User console52024/56659 preserved.
- State/report commit84df08e3; JOURNAL append-only. Canonical worklist [research interface plan](../superpowers/plans/2026-10-08-prime-autonomous-research-interface.md).

## Task21 verified facts

Run p7-live-20261008150326-fee42292ed274268646133a2, cold BP35 L1–L6, no inherited NOTES/routes or outer hints/edits. Started15:03:26.614283Z; sixth pass15:25:03.433270Z.221paid/3deathRESET/1296.819519seconds. Perlevel19/43/41/38/31/49; RESET0/1/1/1/0/0; times105.879669/128.983589/170.686295/242.417207/188.725361/460.127398seconds.

q115/115/115/100/113.319459/115. Formula q=min(115,100*(baseline/paid)^2), baselines21/48/44/38/33/87/86/131/163, N9/W45. Six completed levels cap fullgame score at46.666667; receipt reaches that cap, not fullgame100. All failed/noop/undo/RESET costs included; two initialization RESET rows uncharged.

Full221trace/221knowncommitted journal and223SDK/replay rows independently exact, including allframes. Seal/source566/install584/extension/cleanup PASS. Cleanup1337.083092wall/1337.078490mono.35cells allok;99usage reported input11087866/output28764/peak207778. NOTES662→754→969→1058B, last postgoal. One naturalround index0 completed; no continuation receipt. Native128tail showed no retry, not whole-run guarantee; no failure-sink file.

Private evidence .asterion-private/p7-objective-only-sol-medium-bp35-20261008/trial/,1906file manifest SHA132ba40891733435f1a9aa5f36e7bfc25362a879d36c9f863c72fea3286f33dd.

## Death analysis: facts and proposed improvements

All3 deaths concern automatic vertical movement after an action, not Python errors or demonstrated engine randomness.

- L2: seq20/21 same-plan two-hit probe removed ceiling then floated into hazard; hazard visible but lethal semantics not yet established.2failed+RESET+40success.
- L3: after seq67, cell10 marked hazard15 as!, then independent seq68 moved left into an unsealed upward path. NOTES still called12 unknown; view collapsed purple open/closed states intoX.6failed+RESET+34success; retry first closed three upper slots.
- L4: seq108 showed hazard above x21; lower camera at114 showed path to viewport edge. cell15 read current stand/phase, independent115 flipped gravity at x21 and died.12failed+RESET+25success; retry first stood atx33, then same switch safely.
- ARC also died in L2. Actual events e73–75 explicitly build safe roof in L3; e115 explicitly flip from protected position in L4. Evidence .asterion-private/arc-skill-bp35-l5-trial-20261007T111904Z/evidence/stage2-target6/arc-state/events.jsonl.
- L6 extra7steps vsold42:4left+3right before remotely clicking a visible gravity ball. new178=old185, new186=old186; subsequent frames187–221 match. No late-room convergence failure or RESET.

Current judgment: improve joint representation and application of action→automatic motion→final stop, preserving cross-view paths/unknown bounds and purple-state distinction. Generic layer owns real evidence/readback/versions/effect safety; P7 actor owns game mechanisms, representation, probes and optional computation. No hard safety-semantic gate or forced BFS. These are proposals, not implemented/verified ability improvements.

## Comparison anchors and limits

- Best coldSolmedium/source9b62:221paid/2RESET/1023.279883seconds,21/71/34/23/30/42. FullreplayPASS. Task21 samepaid but26.73percent slower; death costs23vs31, successful198vs190. Medium remains best elapsed-time sample.
- Full score behavioral guidance Task19/source766d71e0:234paid/3RESET/2103.806813seconds,24/51/47/25/44/43, stagegame43.286656. FullreplayPASS. Task21 is38.36percent faster and has better quality, but one sample cannot isolate score-guidance causality or provider latency.
- Task20 no-score/sourcecfc46c63: user-stopped after4levels151completed+10unfinishedL5=161total;21/72/34/24, first4elapsed622.235seconds. Full161replay/cleanupPASS. Actual actor had neitherbaseline nor scoring; legacyfacade visibility claim corrected. No L5/L6 performance conclusion.
- ARC originalSolhigh:6levels271paid/3RESET,19/48/34/23/45/102, naturalcontinuation/hostrecovery; around56minutes including stages. No outer solve hints or skill edits. NOTES small does not mean total context small; actual context peak220388.
- Mature old P7 full100 winner:19/40/34/25/32/43/53/46/70,362total/frontsix193. Resumed292prefix+70L9, not coldresearch cost or an official scorecard claim.
- Low231/1968.197seconds; secondhigh262/4409.249seconds. DeepSeek Flash/Pro BP35 user-stopped inL1; no later-level ability conclusion. PackagedFlash r11lL1 witness10paid/0RESET/fullreplayPASS.

## Previously verified framework repairs

Generic object-root tool schema normalization, bounded private RPC diagnostics, once-per-run exact same-session recovery under original budget; P7 only injects effect facts/storage/deadline. TS50/Python165/promotion25PASS. Recovery code is not a claim all errors prevented or live transient recovery proven. Effort.env shared launcher/guest configuration156related tests(one skip), Make fix49(one skip), promotion25PASS. Current trial required no registry change or repeated r11l.
