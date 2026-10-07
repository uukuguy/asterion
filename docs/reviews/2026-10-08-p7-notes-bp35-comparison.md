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

## Evidence status

Preflight and exact packaged identity are verified. The active run is `p7-live-20261007234531-87e38f105ea518bdba94623a`. Result, post-run audit and cleanup remain pending.

Private configuration, probe, launch, progress, raw evidence and independent review remain under `.asterion-private/p7-notes-bp35-20261008/` and its referenced isolated operator root. No raw game routes, private notes, credentials or provider payloads are published here.

Baseline sources: [previous cold P7](2026-10-07-p7-cold-autonomy-bp35.md), [original ARC BP35 trial](2026-10-07-arc-skill-bp35-l5-l6-trial.md), [offline interactive explanation](2026-10-07-bp35-autonomy-explainer.html).
