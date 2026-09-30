# Live Session Checkpoint

> Updated: 2026-09-30. **Session remains active — not a final handoff.**

## 已验证事实

- VC33 L1 has a sealed/replay-verified 3-action prefix and its 12 L0 visual hypotheses are persisted in the same-game Playbook.
- Explicit VC33 L2 final run `p7-live-20260930032535-f1d60eab0c3283257408d346` remains an offline-route-assisted integration witness: **7 current L2 actions**, 10 total including the 3-action prefix, sealed/replay verified/cleanup complete.
- The final L2 witness used `action_cap=13` and `level_baseline=10`; offline fresh replay compressed the verified 10-action L2 route to 7 actions, and live route adoption followed 7/7.
- L2 model tracking shows successful calls to `p7_world_model()` and `p7_playbook(level=1)`, with persisted same-game hypotheses available before action planning.
- Generic fixes are committed: `a19162a7` (visual Playbook projection and initial witness cap), `37cb3b4a` (same-game suffix replay after rebuilt prefix), `2e526f0f` (current-prefix-only budget), and `cd489499` (offline route injection disabled by default).
- Relevant focused P7 tests: 148 passing; `make lint` passing.
- Pure VC33 L1 rerun `p7-live-20260930043047-7fc39f2e5eaf3d3361ea3a15`: current level **7 actions**, `levels_completed=0`, `terminal_reason=human-baseline`, replay/cleanup passed; `offline_optimization_enabled=false`, route adoption unarmed, worldmap loaded 12 visual hypotheses and saved 27, confirmed facts 0.

## 当前判断

- Explicit level redo now supports rebuilding a short verified prefix while reusing a later-level route only after fresh ARC replay. This is generic and not tied to VC33.
- World-model and Playbook consumption is observable. The first clean VC33 L1 capability rerun did not complete within the 7-action human baseline, so the persisted visual hypotheses alone did not produce a verified solve.
- Post-pass audit: the first six live action expectations used replay state digests in the `frame_sha256` field, producing 6 false `prediction-mismatch` conflicts while the independent route witness still followed 7/7. The run is a valid L2 pass, but prediction diagnostics are not clean.
- Post-pass audit: final confirmed world-model facts are 0/0/0 with 21 hypotheses; the pass does not demonstrate mechanism learning. The summary also labels `failure=null` as `application_failure`, and the debug transcript omits all message bodies/tool-result bodies.
- Classification correction: because the 7-action candidate was found offline and injected into P7, the VC33 L2 run is not a pure P7 capability result. Keep it only as an offline replay/integration witness; do not claim GPT-6.1-Sol independently solved L2 in 7 actions.
- Scope correction: this applies to the entire world-model VC33 phase. L1/L2 successes (`7→4`, `4→3`, `14→11`, `10→7`) all carried route hypotheses; even the baseline-only L1 rerun carried the prior exact route. Clean P7 capability passes in this phase: 0.

## 历史归档

- The first explicit L2 run stopped at 22 total actions with levels still 1; it is unsuccessful evidence and not a new result.
- A later run with the corrected suffix route passed at 10 current L2 actions but used the stale total cap 21; route evidence is valid, budget diagnostics are superseded.
- One corrected-cap run stopped at 3 current actions after three model WebSocket retries; this is an infrastructure failure, not a game-action failure.
- Automatic `next` selection that targeted L4 was stopped and must not be used for explicit level redo.

## 未完成边界

- L2 is a partial level-witness PASS, not a full-game SDK WIN and not an official external submission.
- The causal contribution of visual priors versus replay-verified route evidence remains unisolated.
- Digest field disambiguation, success-path failure classification, clean retrodiction accounting, and current-prefix fallback provenance remain unresolved implementation work.
- The pure VC33 L1 rerun now disables offline route hints and route-adoption injection by default. It still ended with 7 retrodiction prediction mismatches, 0 confirmed facts, and no level advance; the mismatch/expectation path needs analysis before claiming worldmap capability.
- Decision now fixed: offline optimization is diagnostic only, triggered by prolonged non-success or near-baseline low-score completion. Its output must become a generic mechanism hypothesis; exact candidate routes cannot enter a capability run.

## 下一动作

- Analyze the clean VC33 L1 transcript and 7 prediction mismatches, then decide whether to repair generic expectation/worldmap use or run a second pure retry. Do not enable `ASTERION_PRIME_P7_OFFLINE_OPTIMIZATION` for capability evidence.
