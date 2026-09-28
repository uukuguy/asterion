# Next-Session Handoff

> Updated: 2026-09-29 01:36 CST. End of session.

## TL;DR

1. **Target clarified:** raise BP35's official scorecard **LEVEL** row to the `115.00` cap by completing L1 in **≤19 actions**. It currently shows `110.25` (20 actions, baseline 21). The game score `2.22` cannot move for a 1-of-9-level result.
2. **The L1 attempt made no progress:** run `p7-live-20260928171314-be7c1fd04b02dadc007ac487` produced **0 game actions** in ~20 minutes. The Pi model host (`pi-rpc`) was restarted every ~15-25 s. Stopped at closeout; cause **not diagnosed**.
3. `e392577` (operator-selected P7 provider/model) is confirmed working in a live run: that run's trace carries `model_id: gpt-6-sol`, produced by the default `openai-codex / gpt-6-sol` selection.

## Verified facts

- Official scoring (matches `p7/score.py` and the live card exactly): `level_score = (baseline/actions)² × 100`, per-level cap **115**; game score = weighted average with weight = level index, capped by completed weight. For BP35 at 1/9 levels the game cap is `1/45 = 2.222222`.
- BP35 baselines are `(21, 48, 44, 38, 33, 87, 86, 131, 163)` over 9 levels (`environment_files/bp35/0a0ad940/metadata.json`). L1 baseline is **21**, not 22.
- BP35 L1 action → level score: `18→115.00`, `19→115.00`, `20→110.25`, `21→100.00`. The official card reports exactly `110.25 / 20 actions / baseline 21` and `2.2222222222222223` for the game.
- The recorded BP35 success is run `p7-live-20260925150342-922a463cdccb12142fc3bdba`: 20 actions, 1 level, `replay_verified`/`sealed_trace`/`cleanup_complete` all true, trace identity `deepseek-v4-flash`.
- A single-level witness gets `action_cap = 500` and the standard 1-hour deadline / 128 callbacks.
- The failed attempt's trace: 60 `arc.usage.reported` entries (45,641 input / 3,259 output tokens), **0 `arc.action`**, no `worker/` directory, no `worker-cells.jsonl`, no `summary.json` (never sealed). Each model call was only ~500-750 input tokens, far below a P7 solve prompt, so every cycle died early.
- Guest `pi-rpc` PIDs changed within 90 s: `97903 → 97941 → 97972 → 98008` (each 8-25 s old), parented by the operator process.

## Current judgment (not proven)

- The restart loop is most plausibly the model host failing during startup/handshake and something respawning it, but **which layer restarts it, and why, is unproven**. The operator's stdout/stderr was invisible this session (the background job reported no incremental output), which is why the failure could not be diagnosed live.
- Guest memory looked healthy (64 GB total, 18 GB used). `dmesg` shows an old `VM_FAULT_OOM leaked out to the #PF handler` burst whose kernel timestamp (~15.3 days) does not match the current boot (2 d 18 h), so it is **not** attributed to this run.
- `gpt-6-sol` remains unexercised on BP35 in a way that produces actions.

## Historical archive (do not reopen)

- The previous checkpoint's claim that a BP35 L1 rerun cannot change any reported score is **wrong for the LEVEL column** — it holds only for the game score. The user's target is the LEVEL column cap.
- `load_best_prefix` returning `None` from the host venv is expected: `arcengine` is not importable there. Prefix loading must run where the ARC wheels are installed (the guest / isolated wheel env). This is not a regression from the prefix changes.
- `/tmp/asterion-p7-pi-rpc.err` (2026-09-27) records a `MODULE_NOT_FOUND` for `rpc-entry.js` under node v24 — a resolved migration-era issue, unrelated to this failure.
- `make asterion-prime-p7-breadth-preflight` spends minutes in `uv --isolated` resolution and proves less than a direct model probe.

## Unfinished boundaries

- The BP35 L1 ≤19-action goal is **not** attempted successfully; no new prefix, no new scorecard.
- The model host's restart loop is unexplained; the current P7 witness path must be treated as **not runnable** until a logged rerun explains it.
- Official re-submission (which is what makes the website show `115.00`) is a separate authorized action and was not performed.

## Next steps (immediate, action-level)

1. Re-run with the console captured, so the failure is visible:
   `make asterion-prime-p7-level-witness GAME=bp35-0a0ad940 LEVEL=1 > /tmp/bp35-l1.log 2>&1` (background), then `tail -f /tmp/bp35-l1.log` while watching `.asterion-private/prime-p7-live/<new-run>/trace/prime-trace.jsonl` for the first `arc.action`.
2. If the host keeps restarting, capture `pi-rpc` stderr directly and identify the respawning layer (operator session vs. wrapper) before spending more.
3. On a successful L1 with ≤19 actions, verify the sealed run and then decide separately whether to authorize an official re-submission for BP35.

## Don't go down these paths again (ruled out)

- Do not chase the BP35 game score with an L1 rerun: `2.222222` is the 1/9-level ceiling.
- Do not read `.asterion-private` runs from 2026-09-28 17:13 or earlier post-baseline timestamps as current evidence.
- Do not assume the operator's console output is visible through a backgrounded `make` job; redirect it to a file.

## Ready-to-paste commands / configs

```bash
git log --oneline -4
make asterion-prime-p7-games                 # provider-free progress ledger
uv run python -m unittest tests.test_prime_p7_model_selection
uv run python -c "from decimal import Decimal; print([(n, min(Decimal(115),(Decimal(21)/n)**2*100)) for n in (18,19,20,21)])"
```

Run state: clean tree at `c0827a6d`; no P7 process running (a stale `/tmp/monitor_p7.sh g50t` poller from a 2026-09-27 session was stopped). The BP35 L1 selection uses the default `openai-codex / gpt-6-sol`; `ASTERION_PRIME_PROVIDER` / `ASTERION_PRIME_MODEL` in the operator environment override it (`p7/model_selection.py` is the only reader).
