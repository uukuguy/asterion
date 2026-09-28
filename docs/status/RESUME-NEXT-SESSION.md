# Live Session Checkpoint

> Updated: 2026-09-28 07:54 CST. Session remains active; this is not a final handoff.

## TL;DR

P7 now has a bounded structured cross-level mechanics prior and a real Pi registered tool path. The Python broker, facade, Unix bridge, TypeScript registration, packaged extension, verified solve guidance, and bounded `p7_observe.frame_summary` are connected. The latest sealed LS20 L3 run avoided the former read-only loop but made 200 new actions without advancing beyond level 2 and ended `GAME_OVER`; a follow-up with dynamic tried-action context made 34 new actions, used two RESETs, then was manually stopped while idle. Cross-level live improvement remains unverified.

## 已验证事实

- Design and plan for structured cross-level prior were approved and committed as `bcb9cbe1` and `5910b645`.
- `build_mechanics_prior()` is deterministic, bounded, redacted, immutable-input safe, and accepts only ACTION1–ACTION7 with level bounds. Implementation: `ec69aa51`, boundary fix: `08f25fa2`.
- `_P7BrokerClient.mechanics_prior()` pages bounded detached history and returns a capped safe mapping.
- Pi registers `p7_mechanics_prior` alongside the existing P7 tools. The Python `_IpythonBridgeServer` injects the live prediction client, allowlists methods, decodes exact parameter shapes, and returns the five-field method-result envelope.
- The TypeScript method-call writer now appends the newline required by the Python newline-delimited socket server; packaged resource was rebuilt. Bridge repair commits: `c4b390b5`, compatibility fix `7f463b65`, framing fix `57342951`.
- Verified solve guidance calls `p7_client.mechanics_prior()` on later levels, treats results as evidence rather than routes, and requests a falsifiable distinguishing probe. Legacy prompt remains unchanged. Commit: `df70f09d`.
- Verification passed:
  - `uv run python -m unittest -q tests.test_prime_p7_mechanics_prior tests.test_prime_p7_live_command tests.test_prime_p7_native_broker tests.test_prime_p7_native_provider` — 115 passed.
  - `uv run python -m unittest -v tests.test_prime_extension_build` — 8 passed.
  - TypeScript typecheck, focused registration test, Ruff, and diff-check passed.
- Full TypeScript test suite still has its pre-existing context-witness fixture path failures when invoked from the repository root; this is separate from P7 bridge registration.
- The current TypeScript source and packaged extension resource both expose the same nine tools, including `p7_mechanics_prior`; `npm run build` and the extension build-closure suite passed, with the generated bundle digest matching the packaged resource.
- `make promotion-check` was attempted but is external-limited: its isolated temporary environment omitted `python-dotenv` (`ModuleNotFoundError` in `p7.official_operator`) and the aggregate run reported 5 failures and 2 errors. This is not promoted to PASS.
- The optional `python-dotenv` import is now lazy with a bounded standard-library `.env` fallback (`f7ba5f1c`); the focused 116-test P7/operator-config suite passes. The installed official smoke then reaches P7 host preflight and fails on its intentionally minimal fixture environment, so promotion remains unresolved rather than being claimed green.
- A temporary fixture-only profile experiment advanced that smoke into composed application execution, where it still failed with the generic capability error; the fixture change was discarded, so no production or test-fixture behavior was retained from that experiment.
- Required settled state is now appended by the application before the Pi session and on each continuation; only scenario-useful registered query/action tools remain exposed. Model-round private diagnostics retain hashes/signals only, and the sealed LS20 L3 run reports one action-producing round rather than the former read-only loop.
- Continuations now also receive bounded `tried_summary` and an application-generated `action_guard`; unsealed recorder snapshots are merged with action diagnostics before the private summary is written. This is guidance and observability, not an engine-specific route or hard action stop.
- The follow-up summary had 42 checked plans with 31 mismatches, so verified guidance now stops batching after two same-level mismatches and requires a one-item probe or RESET (`5db4a62b`).
- Completed run `p7-live-20260928000722-c0ad73a972c21edd9c357bc0` replayed the 94-step L1/L2 prefix and added 44 L3 actions, but stayed at `levels_completed=2`; prefix replay, seal, replay verification, and cleanup passed before a native `ProtocolError` at `capability.execute` ended the application. Five model rounds carried the application state; 103 checked plans produced 41 mismatches, 59 errors, 3 matches, and 355 unexecuted items. The next run must verify the new in-band `checked_plan_guidance` from `ad71d5d5`.
- Retries `p7-live-20260928005634-caddcfa10b894019e77e9449` and `p7-live-20260928010922-24be5e8179381f438191716b` each replayed the prefix, made one L3 action, then failed at `capability.execute` with `ProtocolError`; both had zero model-round diagnostics, so they cannot evaluate prompt/output behavior. Private diagnostics now classify known protocol failure messages without retaining text (`b2dff557`).
- Run `p7-live-20260928032105-ccb913dde66198e3c11a8ee0` exercised the new invalid checked-plan result. It replayed the 94-action prefix, made 24 L3 actions, stayed at level 2, and was manually stopped after about 31 minutes with cleanup complete. Private summary: 3 model rounds, 110 bridge calls, 68 checked plans, 44 checked-plan errors, 24 mismatches, `repeated_action_streak=7`, recommendation `reinforce-hypothesis-to-action-link`. This confirms P7-generated validation feedback reaches the model; it remains unsealed negative evidence.

## 当前判断

- The implementation boundary is code-verified, but FT09 live verification is paused until the native runtime `ProtocolError` is independently diagnosed or the Pi provider/session is changed.
- The prior is intentionally evidence-only: it summarizes repeated effects, no-effect counts, click ranges, advances, and confidence; it does not synthesize a route or authorize actions.
- A legacy client without `mechanics_prior` receives an empty safe prior for compatibility; the live prediction client implements the real method.

## 历史归档

- Prompt-only tool listing was insufficient; prior GPT-6-Sol runs stalled at the replay prefix with no new actions.
- Earlier bridge tests covered the old worker socket but not the actual Pi Unix bridge. That gap caused the parameter, result-envelope, injected-client, and newline-framing fixes above.
- Existing successful FT09 and SU15 runs remain historical evidence; they do not prove the new structured prior improves live solving.

## 未完成边界

- FT09 post-change run `p7-live-20260927081939-5c7820a6bfe22dbc0be38357` ended `execution-stalled` at prefix 59 / target L5 with cleanup true and no new verified level. The recording has no model tool-call events, so it cannot establish whether `p7_mechanics_prior` was called.
- FT09 second run `p7-live-20260927083252-0bd5aa566c21a90c48c60cf7` ended `child-evidence-invalid`; private accounting shows zero bridge calls, worker cell count 0, two usage events, and successful prefix replay/seal/cleanup. The native runtime error is intentionally redacted to a generic application failure; operator now retains private failure stage/type when a composed capability diagnostic is available.
- FT09 fourth run `p7-live-20260927170356-0499ca87ddaeba7c4a2d6ce8` recorded `application_failure={stage: capability.execute, exception_type: ProtocolError}`, zero bridge calls, worker cell count 0, and successful prefix replay/seal/cleanup. This places the failure before P7 tool dispatch.
- LS20 L3 run `p7-live-20260927192648-44682d9ca51c56d759e37bf2` recorded 4 `mechanics_prior`, 6 `act_checked`, and 98 total actions including the 94-action verified prefix; it stalled after four new actions with no level advance. This confirms the registered tool path is live and moves the remaining issue to model planning/action selection.
- LS20 L3 run `p7-live-20260927201952-f8fa61c11bdff7da4b441230` recorded 3 `mechanics_prior`, 12 `act_checked`, 7 `observe`, and 101 total actions including the 94-action verified prefix. The new sequence was `ACTION2, ACTION1, ACTION3, ACTION4, ACTION2, RESET, ACTION1`; it remained at level 2 and produced a private stall receipt with `action_count=101`, `stall_seconds=300`, and `cleanup_complete=true`. The manifest is `execution-stalled-evidence-invalid` because the interrupted run was not sealed; this is execution-stall evidence, not a verified solve.
- LS20 L3 run `p7-live-20260927215428-0bd2d477fe937f5a9fa6592c` ran with the bounded `p7_observe.frame_summary`. It recorded 1 `mechanics_prior`, 9 `act_checked`, 6 `observe`, 2 `history`, and 99 total actions including the 94-action verified prefix. The new sequence was `ACTION2, ACTION1, RESET, ACTION3, ACTION4`; it remained at level 2 and produced a private stall receipt with `action_count=99`, `stall_seconds=300`, and `cleanup_complete=true`. The manifest is `execution-stalled-evidence-invalid` because the interrupted run was not sealed; this is execution-stall evidence, not a verified solve.
- LS20 L3 run `p7-live-20260927221112-13a287271776e58251e98863` ran after the registered `p7_observe` wiring fix. It recorded 2 `mechanics_prior` before action and 4 total, 1 `act_checked`, 9 `observe`, 8 `status`, 2 `history`, and 95 total actions including the 94-action verified prefix. The new sequence was only `ACTION1`; it remained at level 2 and produced a private stall receipt with `action_count=95`, `stall_seconds=300`, and `cleanup_complete=true`. The manifest is `execution-stalled-evidence-invalid` because the interrupted run was not sealed; this is execution-stall evidence, not a verified solve.
- LS20 L3 run `p7-live-20260927231351-9091397216b90957b1db2915` used the continuation state contract and completed 200 new actions after the 94-action prefix. It remained at level 2, ended `GAME_OVER`/`reset-required` at sequence 294, and passed seal, replay, and cleanup. Private model/action diagnosis is `round_count=1`, `planned_action_rounds=1`, `repeated_action_streak=30`, `actions_since_progress=200`, recommendation `force-replan-after-no-progress`; this is valid negative evidence, not a solved level.
- Follow-up LS20 L3 run `p7-live-20260927233815-f11534a8432f44972983050a` made 34 new actions after the prefix and remained at level 2. It included two RESETs and then no new action for roughly two minutes, so it was manually stopped; cleanup completed, but no seal/replay or solve evidence exists. Summary accounting recorded 42 checked plans, 31 mismatches, and 50 registered bridge calls. The unsealed snapshot is retained as bounded negative evidence.
- No claim is made that all games or hidden rules are solved, or that the current model will generalize from one prior.
- The full npm test suite remains broader than the focused registration test and retains unrelated fixture-harness failures.

## 下一动作

1. Treat `p7-live-20260928032105-ccb913dde66198e3c11a8ee0` as the current negative baseline: broker feedback was delivered, but 44 invalid checked plans remained and level 3 did not advance. Next change should target hypothesis-to-action linking or model session guidance, not tool registration.
2. Keep the FT09 pre-tool failures and LS20 L3 failures as bounded negative evidence; do not attribute them to the now-verified registered P7 tool path.
3. Run another bounded attempt only after an evidence-based prompt or model-session change, and track it at startup, first actions, and termination.

## Ready commands

```bash
cd <asterion-repo>
uv run python -m unittest -q \
  tests.test_prime_p7_mechanics_prior \
  tests.test_prime_p7_live_command \
  tests.test_prime_p7_native_broker \
  tests.test_prime_p7_native_provider
npm run typecheck --prefix packages/typescript/asterion-prime-extension
```

The previously retained `.superpowers/sdd/task-1-report.md` scratch changes were reviewed and committed in `697da942`; the working tree is clean.
