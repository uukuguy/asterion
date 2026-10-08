# Frozen NOTES P7: BP35 L1–L6 comparison

## Trial boundary

The user continued after the [NOTES implementation and r11l deployment verification](2026-10-08-prime-research-notes.md). One new cold BP35 run is active; no outcome is assumed before its measured end.

- Production:`ebcefec9`; exact previously verified wheel SHA256:`7a599c0139e35c043329179f3d8badea8cee7a95f2767480a6944337cc0250a3`.
- Offline `bp35-0a0ad940`,seed0, empty independent history/profile/research root, gpt-6.1-sol/high, target6of9.
- Same existing autonomy controls:5400 seconds total, at most6 natural rounds,1000 primitive actions,1024 model callbacks and4096 tool callbacks. Absolute start2026-10-08 07:45:31 CST; cutoff09:15:31. Another180 seconds permits cleanup only.
- No operator game hints, old routes/notes, midrun solver changes, additional attempts, L7 actions or official card. Actor-written research and existing generic natural continuation remain autonomous behavior.
- Actual restricted-worker bootstrap/persistence/recovery and forbidden-file probes pass. An independently reviewed launch-only Node wrapper preserves argv/stdin/stdout/exit behavior and captures full private stderr, so later context-cut records survive the normal4096-byte summary cap. No model-visible instrumentation changed.

Installed Pi does not consume the existing debug-transcript setting. Complete provider request start/end and cache/reasoning-time decomposition therefore remain unavailable. Environment timestamps, ordered trace usage, private notes ancestry and actual context projections can still support a precise outcome and mechanism comparison.

## Fixed baselines

| Level | Previous cold P7 actions | Original arc-skill actions | Previous P7 wall seconds | ARC wall seconds |
| --- | ---: | ---: | ---: | ---: |
| L1 |26|19|705.593|184.651|
| L2 |47|48|563.398|261.165|
| L3 |41|34|668.007|195.794|
| L4 |23|23|640.492|224.530|
| L5 |30|45|646.165|1086.491|
| L6 |46, unfinished|102|2174.958 to deadline|1415.222, includes stage gap|

Previous cold P7:213 paid actions/5 completed/5400-second cutoff, with RESET in L2 and L3. ARC:271 paid/6 completed, with RESET in L2,L5,L6. ARC L1–L6 action edges19/67/101/124/169/271 were rechecked directly from its272-event ledger; this fills the earlier report's aggregated L1–L4 count124.

Times above run from initial observation or previous pass to the next pass, except unfinished P7 L6 ends at its deadline. ARC L6 includes its stage transition/cleanup/restart gap; its Stage2 natural model round lasted1127.976seconds. ARC's overall3393.950seconds spans Stage1 start to Stage2 natural completion and includes stage overhead. These distinctions prevent attributing every elapsed second to model inference.

The older mature P7 sample has118 actions through L4,32 for its located L5 success and43 for L6. This193-action combination excludes the lengthy outer diagnosis, code changes and failed attempts; it is not an equal cold-start result.

## Questions for the new run

1. Does it complete L6 within the same finite allowance, and what are the actual per-level actions, RESETs and times?
2. Does model-maintained NOTES remain compact and useful across levels, and do actual model-view cuts continue through L5/L6?
3. Does normalized input growth decrease? Note bytes, provider tokens, usage-event counts, natural rounds and tool transactions must remain separate measures.
4. Does learning change subsequent experiments and plans? Reduced input alone does not establish better game reasoning, faster end-to-end completion or fewer actions.

Previous P7 had171 usage events, normalized input19179445/output134227, peak255820. That peak occurs after L5 passes and before the first L6 action; the next input drops41315 and later grows138388. ARC's tiny L6 NOTES511–915bytes coexist with a Stage2 input peak220388; its note size is not its whole model context. Neither dataset provides a controlled single-variable causal comparison.

## Interim observations — not the final result

L1 passed at paid sequence44, SDK response2026-10-08 07:56:12.344639 CST,641.305seconds after launcher start. This is an exact pass edge, not a sampled post-pass action count. The run continues into L2; final per-level timings will use initial observation/pass clocks consistently.

Independent read-only inspection found a concrete application usability issue. `p7_research` is registered as an importable worker module, while only `prime_workspace` is injected as a global. The prompt lists reader methods without an explicit import example. In the first26 cells, the actor makes19 namespace inspections and2 bare-name calls, with no import attempt, then records the module as unavailable. This supports import/discoverability friction, not a missing-runtime-module claim.

The actor later manually transcribes compressed frame rows and indices into two Python cells of2392/2519characters. The codec itself is lossless; the manually copied arrays differ from recorded observations in4/1 background pixels, with no demonstrated actionable consequence. More materially, accepted sequence2 NOTES says an action had no frame effect despite36 recorded pixel changes. Correct observation references do not establish the truth of free-text conclusions. Later notes autonomously correct substantial geometry/mechanism errors.

The actual ARC L1 log instead shows a row-numbered full grid, short queries using prebound `grid`/`np`, and worded geometry transitions. These affordances reduce the work needed to inspect evidence. They do not establish that encoding or NOTES alone caused the observed performance difference. No finding was fed to the actor; no live repair was made. Final analysis must also inspect later successful reads, corrections and outcomes.

### Completed L2: extra failure, not a longer final route

L2 passed at paid sequence118,2026-10-08 08:05:58.233021 CST,585.888382seconds after L1. Its74 actions divide exactly into6 actions to first death +1 RESET +26 actions to second death +1 RESET +40 successful actions. Previous P7 used6+1+40=47; ARC used6+1+41=48. The extra failed episode and RESET explain all27 additional actions against previous P7; its final successful episode is equally long.

The second death follows a concrete perception error. NOTES at sequence73 treats a central column as clear, while the recorded frame contains hazard-colored pixels at all three relevant tile centers. Sequence77 NOTES explicitly corrects confusion between tile edges and centers; the correction survives RESET78 and the final successful episode. No outside diagnosis was supplied.

L2 has18 note revisions of688–1051bytes. All retain an absent/possibly absent reader belief; its19 cells contain13 namespace inspections and no research-module import. Eight `prefix-action-reuse` stops introduce separate tool friction:6 dispatch no actions and2 stop after a partial prefix, leaving11 proposed steps unexecuted. Those11 are not paid actions; no paid undo or unchanged-board action appears in this level. A short memory can preserve both useful corrections and mistaken capability beliefs.

### Completed L3: knowledge regression and repeated relearning

L3 passed at sequence193,2026-10-08 08:22:32.434557 CST,994.201536seconds after L2. Its75 actions comprise13+6+12 failed gameplay actions,3 RESETs, then41 successful-episode actions. Old P7 used6+1+34=41; ARC completed a clean34. Against old P7,27 extra failed/restart actions and7 extra final-episode actions account for the34-action gap.

The strongest evidence concerns a toggle whose center pixel remains unchanged while its surrounding shape changes. NOTES correctly learns it, later reinterprets the unchanged center as an ineffective click, and then learns the same toggle again. A known hazard briefly becomes “unknown.” One repeated fatal move occurs even though the current note retains the earlier counterexample; the new plan relies on an unsupported blocking-wall assumption. Later the actor correctly uses closed gates as protective ceilings and completes. ARC's actual L3 log applies that protective-ceiling idea early, then reuses it without death/RESET.

L3's36 note snapshots are649–1026bytes. They preserve useful controls, deaths and later strategy, while key shape/palette facts regress. Forty-seven archived cells include18 failures;27 inspect the namespace and none imports the raw reader. Twenty of54 plans stop for prediction mismatch, including both harmful outcomes and harmless pixel-prediction mistakes. These are distinct from actual deaths and zero-dispatch tool rejections.

The current view policy replaces messages preceding the accepted NOTES tool group with instructions/current notes/current board, retaining that group and later messages. It has no independent short buffer of previous frames and action results. Therefore an incorrect summary can remain while its contradictory earlier evidence exits the immediate view. Actual cuts and semantic regressions coexist here, but exact request clocks/revision-tagged cut logs are unavailable, and this run does not prove that cuts caused any specific error. The retained-but-ignored counterexample also prevents blaming all failures on missing history.

ARC's short NOTES does not itself trigger comparable prefix deletion; its outer conversation retains earlier tool evidence, subject to host behavior. A future bounded recent-evidence window and separating note editing from automatic prefix deletion are candidates for controlled comparison. This does not justify restoring all old execution logs or claiming that more context alone solves the task. No such change is made during this run.

## L4 boundary

L4 passed at sequence244,2026-10-08 08:35:23.865701 CST,51 actions and771.431144seconds after L3. Both comparison baselines used23 actions. The frozen run now enters the requested L5; its result and L6 remain pending.

## Evidence status

Preflight and exact packaged identity are verified. The active run is `p7-live-20261007234531-87e38f105ea518bdba94623a`. Result, post-run audit and cleanup remain pending.

Private configuration, probe, launch, progress, raw evidence and independent review remain under `.asterion-private/p7-notes-bp35-20261008/` and its referenced isolated operator root. No raw game routes, private notes, credentials or provider payloads are published here.

Baseline sources: [previous cold P7](2026-10-07-p7-cold-autonomy-bp35.md), [original ARC BP35 trial](2026-10-07-arc-skill-bp35-l5-l6-trial.md), [offline interactive explanation](2026-10-07-bp35-autonomy-explainer.html).
