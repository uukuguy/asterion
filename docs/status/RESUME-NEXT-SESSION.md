# Live Session Checkpoint

> Updated: 2026-10-13 12:23. Session remains active — baseline published to origin; no new live trial.

## 已验证事实

- README.md, README.zh-CN.md and AGENTS.md now describe the standard Prime library owner, independent applications, NOTES and P7 model-relative rollout boundaries. Independent consolidation/documentation review found no blockers. Fresh post-merge Python76 PASS; runtime TypeScript31 PASS; Prime extension112 PASS/6 skipped; lint/docs PASS (327 markdown/283 local links). No full regression, promotion or new model/game trial performed for this consolidation. Baseline is marked by `asterion-prime-p7-baseline-2026-10-13`.

- Main fast-forward includes all 237 commits from the research branch. Original branch tips are retained under annotated `baseline-archive/2026-10-13/` tags. Fully merged branches retired; patch-equivalent experiment branches renamed under `archive/2026-10-13/`. P1–P3 legacy branches/worktrees and P2/P3 uncommitted journal receipts are preserved; old code was already integrated before deliberate legacy removal, so no old implementation was cherry-picked. Remote main and all 11 baseline/archive tags were pushed and verified on 2026-10-13; baseline tag resolves to `4107aefb`.

- Recovery checked closeout commit `0b79acb9` and recovery commit `fd30ab81` and final JOURNAL entries: Task52 process cleanup and evidence sealing were recorded; real cache/cost acceptance remains open. Working tree was clean before this recovery-only edit.

- Branch `main`; stable Prime/P7 baseline fast-forwarded from `feat/prime-research-notes` on 2026-10-13. Latest implementation: `d1c96cf1` (cache/cost statistics); preceding `cb0ba4ec` (scope support and actor-only history), `07d00c1f` (retained fatal witnesses/input pressure). Stop receipt committed `33d0214d`. Baseline consolidation is now pushed to origin.
- Task52 fresh BP35 seed0/target9/historyOFF/noresume was explicitly stopped by the user because it was too slow. It ran frozen `cb0ba4ecd712d79ba46045f06e20cfe62d05c0be`, wheel `4ad6518a19f77e1dd0e1a37fb95e663b0aaeec0765ea86bfbcc4881985baabe9`, not the later cache fix.
- Run `p7-live-20261011205910-0feb1490aea0c7f7684f3644`: 5/9,225 actual actions,3887.154227 seconds,one death,two RESET. Final model callbacks369, settled usage368,input13248210/output133425,peak input61077. Total input includes cache reads/writes; cache fractions and costs are unknown and cannot be backfilled.

| Level | Actual actions | Seconds | Input/output tokens | Result |
|---|---:|---:|---|---|
| 1 | 17 | 234.214 | 933041 / 7149 | completed |
| 2 | 44 | 249.855 | 915835 / 8150 | completed |
| 3 | 36 | 402.182 | 1281935 / 13650 | completed |
| 4 | 25 | 393.681 | 1523615 / 13483 | completed |
| 5 | 31 | 596.027 | 2066079 / 21414 | completed |
| 6 | 72 | 2011.195 | 6527705 / 69579 | unfinished |

- L6: death154,deathRESET155,first retry55 actions,voluntaryRESET211,final retry14 actions. RESET211 followed NOT_FINISHED; actor estimated reset+11 replay versus15 undo. It was not a death or automatic host reset.
- Final CPU187.894586s,peak memory553164800B (527.539MiB),swap0. Closed/sealed/replay_verified/cleanup_complete=true,unresolved=false,deadline=false. Guest unit `asterion-p7-35b2e1a655ec4c6ea01b02409abf44d8.service` inactive/dead,MainPID0,empty cgroup,guest PID404633 absent. Main PTY47116 ended Make2/Error130; monitor47142 ended0; read-only monitor stopped. Unrelated console52024 was preserved.
- Evidence root `.asterion-private/task52-bp35-scope-builtins-live/`: `final-resource-receipt.json` SHA256 e452a50c610319539ca6bdd3201eaccb5b321ff06aae8ab3fb5d4ed777c6f098; `final-summary.json`; `level-usage.json`; `readonly-monitor/final-readonly-audit-receipt.json` SHA256 a8d76293aba79066dae6105478666184ef92a7a89b2e75a679eeb1699750263b. Raw frames, source, NOTES and usage remain private.

## 关键分析与责任边界

- Task51 stopped4/9,150actions,2292.953s after ordinary scope initializers stalled: missing genuine hasattr/round support and incorrectly rejected Python3.14 local STORE/DELETE_DEREF. `cb0ba4ec` supports these while retaining dependency identity and rejecting external closure mutations. P7 model-facing cell_history/cell_read now exposes actor provenance only, preserving kernel ordinal and complete private history. Focused25 auto+40 research/bridge tests,ruff/docs and independent source APPROVE. Full promotion was interrupted at user direction; never label it PASS.
- Task52 exercised actor-only history:50 returned IDs across3pages were actor cells; no host scaffold IDs. L5 old extractor reg24 remained available under reg25 and correctly found a different initial state; this verifies cross-registration nonmatching applicability, not same-danger downgrade blocking.
- L5 actor68 and L6 actor109 identified conditional/predicted lethal candidates and chose alternatives. Host before214 reg34 blocked a fresh predicted death after3 safe prefix actions. Total auto226=225 real+1fresh veto; actor helpers138; scope unavailable0,old-registration fatal veto0. Do not claim live same-danger cross-model retention was verified.
- L6 first action154 click(39,33) killed the player in25 frames. Actor86 and hostreg26 both predicted settled1/covered1/no identified fatal. Initial direction+1 plus inherited click8 flip to-1 predicted an upper-wall stop, while pixels showed downward fatal motion. This proves the combined initial-direction/click-effect model was wrong. Animation alone cannot uniquely prove click8 does not flip. Later actor used initial up+click flip down. Postdeath replay predicted death3ticks; it was not predeath prevention.
- Click8 flip first appeared in L4 cell205 after action102; actual101 upward/102 downward and111 upward/116 downward supported that level-specific inference. L5 reread/reused L4 source; L6 changed initial direction while inheriting the rule. Audits `death154-audit.json`, `click8-assumption-lineage-and-animation-audit.json`, `l5-actor68-scope-and-alternative-audit.json`, `l6-active-reset211-and-fatalstop214-audit.json` preserve the causal evidence and qualifications.
- Fixed research instructions already occupy the stable initial prefix. They are also duplicated in dynamic memory snapshots:22551UTF8B (~22616 JSON bytes),74.1% of one30511B snapshot; actual NOTES3605B. Do not claim the prefix was absent or cache hits were assured. Hook bytes are not provider tokens. Peak hook view210850B;128KiB capacity is a reminder, not a hard limit. Static duplication is not repaired; raw pixels remain intact.

## 当前判断

The main remaining cost is lengthy research/model revision and repeated input content. L6 mechanics generalization was overconfident; current rollout evaluates an actor model, not true engine mechanics. Scope preservation fixes do not fix an inaccurate original model. These explanations are supported locally, but their correction has not been shown to improve end-to-end solving.

## 未完成边界

- Generic migration versus P7 adaptation must remain separate. Overall migration losslessness is not certified by a game score or focused tests.
- Cache interface `d1c96cf1` is implemented and independently approved: optional uncached/cache-read/cache-write tokens,coverage-aware sums/cache ratio and labelled USD `pi_sdk_estimate`; absent/partial data remains unknown,SDK estimate is not invoice. Python normalizer/protocol15 + P7/stat/story41 + TS2 focused testsPASS,ruff/docs/diffPASS. It was not deployed into Task52 and has no real backend cache/cost acceptance yet. Existing budget authority is unchanged.
- Runtime protocol/schema/TS types and P7 trace/status/story were updated. The strict older recovery script `tools/recover_prime_p7_trace_race.py` needs compatibility review before using it on new extended usage traces; do not assume all consumers changed.
- No static-instruction duplication repair,rule-confidence/scope mechanism,or new L6 improvement implemented. No new paid trial authorized after the stop.

## 历史归档与不要重走的路径

- Task44 full9/9 used same-game/same-seed historical success actions; it is not an independent fresh capability baseline. Default history must stay OFF unless the user explicitly asks to evaluate experience.
- Task49/50/51/52 are stopped trials, not full passes. Task51 scope-unavailable stops and Task52 false-safe model predictions have different causes.
- Unvalidated behavioral prompts belong only to the experiment entry. Promote to the common P7 prompt only after useful behavior is verified. Do not crop raw game frames or mistake a single input action for bounded automatic consequences.
- User explicitly rejected excessive production regressions. Use changed-code review and relevant boundary tests; no broad regression merely to close a supervised experiment.

## 下一动作

The user authorized stable-baseline consolidation into main and README/AGENTS alignment. Local merge is complete; no new live trial is authorized. Await the next research instruction. If asked to continue optimization, first inspect recorded L6 research and repeated context without new model/game calls, identify a concrete limited repair or discriminating experiment, and review new usage consumers. Do not automatically repeat the64-minute trial. If a new trial is authorized, freeze its source/wheel identity and verify actual cache fields are retained; report per-level actions,time and resource use.

## 恢复命令

```bash
git status --short
git log --oneline -5
cat .asterion-private/task52-bp35-scope-builtins-live/final-summary.json
cat .asterion-private/task52-bp35-scope-builtins-live/final-resource-receipt.json
```

Read `CURRENT-STATE.md`,recent `JOURNAL.md`, `INDEX.md`, `DECISIONS.md` D-2026-10-12-03/04 and `MEMORY.md`. No active trial to attach or resume.
