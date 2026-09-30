# Live Session Checkpoint

> Updated: 2026-09-30. **Session remains active — not a final handoff.**

## 已验证事实

- VC33 L1 has a sealed/replay-verified 3-action prefix and its 12 L0 visual hypotheses are persisted in the same-game Playbook.
- Explicit VC33 L2 final run `p7-live-20260930032535-f1d60eab0c3283257408d346` passed with model `gpt-6.1-sol`: **7 current L2 actions**, 10 total actions including the 3-action L1 prefix, `levels_completed=2`, sealed/replay verified/cleanup complete.
- The final L2 witness used `action_cap=13` and `level_baseline=10`; offline fresh replay compressed the verified 10-action L2 route to 7 actions, and live route adoption followed 7/7.
- L2 model tracking shows successful calls to `p7_world_model()` and `p7_playbook(level=1)`, with persisted same-game hypotheses available before action planning.
- Generic fixes are committed: `a19162a7` (visual Playbook projection and initial witness cap), `37cb3b4a` (same-game suffix replay after rebuilt prefix), `2e526f0f` (current-prefix-only budget), with state journal commits `3620267a`, `56a845bb`, `f811ab3f`.
- Relevant focused P7 tests: 140 passing; `make lint` passing.

## 当前判断

- Explicit level redo now supports rebuilding a short verified prefix while reusing a later-level route only after fresh ARC replay. This is generic and not tied to VC33.
- World-model and Playbook consumption is observable, but the L2 result does not isolate visual hypotheses as the causal source of the route improvement because the checked route was the decisive replay artifact.
- Post-pass audit: the first six live action expectations used replay state digests in the `frame_sha256` field, producing 6 false `prediction-mismatch` conflicts while the independent route witness still followed 7/7. The run is a valid L2 pass, but prediction diagnostics are not clean.
- Post-pass audit: final confirmed world-model facts are 0/0/0 with 21 hypotheses; the pass does not demonstrate mechanism learning. The summary also labels `failure=null` as `application_failure`, and the debug transcript omits all message bodies/tool-result bodies.

## 历史归档

- The first explicit L2 run stopped at 22 total actions with levels still 1; it is unsuccessful evidence and not a new result.
- A later run with the corrected suffix route passed at 10 current L2 actions but used the stale total cap 21; route evidence is valid, budget diagnostics are superseded.
- One corrected-cap run stopped at 3 current actions after three model WebSocket retries; this is an infrastructure failure, not a game-action failure.
- Automatic `next` selection that targeted L4 was stopped and must not be used for explicit level redo.

## 未完成边界

- L2 is a partial level-witness PASS, not a full-game SDK WIN and not an official external submission.
- The causal contribution of visual priors versus replay-verified route evidence remains unisolated.
- Digest field disambiguation, success-path failure classification, clean retrodiction accounting, and current-prefix fallback provenance remain unresolved implementation work.

## 下一动作

- Before starting another level, repair and test the post-pass defects above. Then choose an explicit target level (`LEVEL=3` or another authorized game) and keep current-level counts separate from replayed prefixes; do not use automatic `next` when redoing a completed level.
