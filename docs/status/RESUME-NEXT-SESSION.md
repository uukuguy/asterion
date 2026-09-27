# Next-Session Handoff

> Updated: 2026-09-27 10:58 CST. Active checkpoint after P7 Codex migration.

## TL;DR

1. **Final card `8cd88c5b-ec12-49e3-9ff6-1d4af2e1e8c5` scored 11.55** (vs prev 9.98, +1.57 / +15.7%); no new official submission was made.
2. **3 L4 passes this session**: FT09 (+19.05 game score), AR25 (+11.11), TU93 (+8.89). Total +39.05 game score, +1.56 overall contribution.
3. **L3+L4 queue exhausted** — 11 attempts: 3 pass / 8 fail / 1 killed (process). Remaining L2-only games can't be tightened without prefix deletion (destructive).
4. **Optimization strategy revised**: passing more levels (cap increases) >> tightening under-115 actions (only helps when game score < cap; most passed levels already at 115).
5. **P7 native model migration is committed** (`d50897f7`, journal `f886af66`): fixed `openai-codex/gpt-6-sol`, high reasoning, global operator Pi profile, isolated resource discovery, and historical DeepSeek prefix compatibility.
6. **First Codex retry control** on FT09 L5 (`p7-live-20260927024817-d3f5b26a514cd1958c142df1`) loaded the 59-action verified prefix, reported GPT-6-Sol usage, then hit the 300-second no-action stall; only `stall-receipt.json` exists, so it is not a verified result.

## Where things stand

- **Latest official card**: `8cd88c5b` (closed-confirmed), overall_score **11.546**, 25 games attempted. `scorecard_url` in `.asterion-private/prime-p7-official/p7-live-20260926235934-8d921e7c607621adb5e35542/official-receipt.json`.
- **Top-3 L4-passed games** (this session): FT09 (47.62), AR25 (27.78), TU93 (22.22).
- **Game score totals**:
  - 3 games at 4+ levels: FT09 (47.62), AR25 (27.78), TU93 (22.22)
  - 4 games at 3 levels: M0R0 (28.57), VC33 (21.43), SU15 (13.33) — caps hit
  - 7 games at 2 levels (DC22/CN04/SC25/RE86/LS20/KA59/WA30/TR87): 6.67–14.29
  - 11 games at L1 only: 1.46–4.76
- 25/25 games attempted; no game at 100% (would require all levels at 115).
- **Working tree**: clean after commits `d50897f7` and `f886af66`; no P7 or Pi processes remain.

## What this session delivered

- **3 L4 passes via same-game retry**: AR25 L4 (33 actions, 89% efficiency, 115 cap, commit `71d8de86`), TU93 L4 (42 actions, 100% baseline, score 100, commit `81fb0911`), FT09 L4 (24 actions, 86% efficiency, 115 cap, commit `40dca263`). All three were un-tried L4 retries (M0R0/VC33 L4 both retried, both failed).
- **4 framework improvements**:
  - `c93264a9`: exposed `p7_tried_actions(level)` and `p7_last_outcome_summary(level)` top-level Python functions in `client_module_source` + matching TypeScript method tools (`p7_tried_actions`, `p7_last_outcome_summary`) in `ipython-extension.ts`.
  - `633d030d`: prompt.py secondary-objective paragraph rewritten with concrete score formula `((baseline/actions)^2)*100` capped at 115, plus thresholds "1.5x → ≥44%, 2x → 25%, 5x → <4%".
  - `1083708e`: 4 no-effect-loop guards: (1) broker already had REPLAN_REQUIRED at threshold=3; (2) `observe()` in `operator.py` now auto-injects `tried_summary` (attempts/no_effect/top_repeated); (3) `_summarize_prefix_mechanics(prefix)` auto-builds markdown summary of each prior level's action distribution into the prompt; (4) prompt hard rule: 3 no-effect repeats of any action → MUST RESET/switch.
- **5 commits documenting L3/L4 retry results**: `42bf3b34` (SC25 cluster reduced 4→3, still fail), `4488f5e1` (RE86 wander), `ebdf8818` (M0R0 L4 baseline consumed), `b1bbf113` (VC33 L4 62/61), `0caee0fb` (SU15 L4 116/115), `8661e084` (G50T L3 fail queue exhausted).
- **Score formula understanding**: `partial_game_score` in `score.py` uses `min(weighted/weight_sum, completed_weight/weight_sum * 100)` cap. Per-image scorecard from second-place team confirmed: SP80 all 6 WIN but L5=42.65 → 97.77; SU15 all 9 WIN with L7=79.01 → 100 (capped). Tightening under-115 levels only helps when `weighted_score/weight_sum < cap`, i.e., before completed_weight/weight_sum × 100. Most of our passed games are already at this cap.

## Next steps (immediate, action-level)

1. **Keep the Codex route bounded while diagnosing the stall.** The zero-prompt guest RPC is proven (`get_state` → `openai-codex/gpt-6-sol`, `thinkingLevel=high`, auto compaction enabled). The FT09 run proves model access and usage reporting, but not action progress. Inspect the Pi/runtime settlement path before another paid retry.

2. **If more score gains wanted**: do not submit the stalled FT09 run. First reproduce a tiny bounded Codex action probe or fix the settlement issue; then consider M0R0 L4 (cap 217 = 191 prefix + 26 baseline, already failed twice) only with explicit budget authorization.

3. **If strategy pivot**: delete saved prefix for one game (e.g., TN36 L1 prefix at `.asterion-private/prime-p7-live/p7-live-20260926062602-958fbcdcb0e53f999a388dc1/summary.json` + `prefix-replay-recordings/`) and re-solve from L1 — but no retry tool supports target_level=1. Requires modifying `run_prime_p7_retry.py:_target_level` or running an offline full solve.

## Don't go down these paths again (ruled out)

- **Tightening under-115 actions via same-game retry**: doesn't work — retry uses saved prefix unchanged. Only way: delete prefix file (destructive, no rollback).
- **L4 retry for already-failed games**: M0R0 L4 retried twice (killed at 3 actions, then 26/26 baseline consumed). VC33 L4 62/61 failed. SU15 L4 116/115 failed. Diminishing returns; budget better spent on new mechanisms or different game types.
- **4 framework improvements to fix L3 fails**: SC25 L3 retest with all 4 improvements committed (REPLAN_REQUIRED at 3, observe tried_summary, mechanic summary, hard rule) — cluster mode reduced 4→3 but model still failed. Conclusion: model behavior, not framework gap.
- **Continuing to launch L3 retries for L2-only games with no L2 prefix**: BP35, SB26, SK48, G50T all failed because they had no L2 prefix; retry target was effectively L2 fresh solve (which they failed). Check `load_best_prefix` first.
- **Per-level score tightening as primary strategy**: most passed games already at `completed_weight/weight_sum × 100` cap. Pass more levels (cap increases) >> tighten individual levels.

## Ready-to-paste commands / configs

- **Re-submit after any new L4 pass**:
  ```
  cd /Users/sujiangwen/sandbox/agentic-2026/asterion
  timeout 1800 make asterion-prime-p7-official-submit GAME=all
  ```

- **Find next un-tried L4 candidate**:
  ```
  python3 -c "
  import json, os, glob
  for run in sorted(glob.glob('.asterion-private/prime-p7-live/p7-live-*'), key=os.path.getmtime, reverse=True):
      s_path = f'{run}/summary.json'
      if not os.path.exists(s_path): continue
      s = json.load(open(s_path))
      bs = s.get('diagnostics',{}).get('broker_status',{})
      if bs.get('levels_completed',0) >= 3: print(s.get('experiment',{}).get('game_id','?'), bs.get('levels_completed'))
  "
  ```

- **Per-level score gap analysis** (used to identify under-115 levels):
  ```
  cd /Users/sujiangwen/sandbox/agentic-2026/asterion
  python3 -c "
  import json
  card = json.load(open('.asterion-private/prime-p7-official/p7-live-20260926235934-8d921e7c607621adb5e35542/official-receipt.json'))
  for g in card['games']:
    bl = json.load(open(f'/Users/sujiangwen/sandbox/agentic-2026/external-prime/arc-agi-3/environment_files/{g[\"game_id\"].split(\"-\")[0].lower()}/{os.listdir(f\"/Users/sujiangwen/sandbox/agentic-2026/external-prime/arc-agi-3/environment_files/{g['game_id'].split('-')[0].lower()}\")[0]}/metadata.json'))['baseline_actions']
    ws = len(bl)*(len(bl)+1)//2
    cw = sum(range(1, g['levels_completed']+1))
    print(f'{g[\"game_id\"][:12]} score={g[\"score\"]:.2f} cap={cw/ws*100:.2f}')
  "
  ```

- **Monitor active retry** (avoid stale-data blind polling):
  ```
  nohup /tmp/monitor_p7.sh <game_alias> > /tmp/p7-monitor.log 2>&1 &
  tail -f /tmp/p7-monitor.log
  ```
  Script detects DEAD procs (no new actions in 30s with no run dir created) and reports "DEAD" instead of stale data.

## Current task authorization

Current authorization covers the migration and one bounded FT09 control. Further paid retries require an explicit new finite budget after the stall is understood.
