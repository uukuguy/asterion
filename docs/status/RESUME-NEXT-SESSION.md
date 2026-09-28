# Recovered Session Checkpoint

> Updated: 2026-09-28 14:05 CST. **The prior session missed final handoff.** This file is a recovery baton synthesized from `JOURNAL.md` and `git log` after the 13:02 checkpoint. Session recovery only — not a reviewed closeout.

## TL;DR

1. Registered Pi `p7_act_checked` guidance reduced invalid checked plans on LS20 L3 (`p7-live-20260928043554-4ad46a32850f165e981a723e`: 3 errors / 9 plans), but L3 remains unverified.
2. Run `p7-live-20260928054122-3404f72d04e738282ef11a06` added 10 L3 actions and stayed at level 2; recording proved every action changed the settled frame, then manual cleanup completed.
3. Run `p7-live-20260928065144-20547ddb73d8dbfda34b6213` with `progress` added 53 L3 actions, 0 invalid-plan errors, and sealed/replay-verified evidence, but still stopped at level 2. Recording shows color 11 decreases by four per action and ACTION4 resets the cycle.
4. `35817e03` adds bounded `color_count_delta` to the application-supplied progress object and registered descriptions.
5. Run `p7-live-20260928071500-eb179a897f51290a0b9fb226` added only 6 L3 actions (6 mismatches, 1 error), so color deltas alone did not stabilize planning.
6. `28da86c9` adds direct `progress_guidance` to observe/act_checked results; next bounded witness must measure whether this reduces early mismatch and reaches level 3.
7. Run `p7-live-20260928072349-177a232e9b1db4d109bf9a78` had zero model rounds/actions after prefix replay; treat as startup variance and do not infer anything about guidance.
8. Runs `p7-live-20260928074135-39346a6b32de1f63cd6a328b`, `p7-live-20260928074743-9073b1b03b2472744e81b76f`, and `p7-live-20260928082138-3fcfc9fd11d1bd596714b3b6` all stopped before a model round; the third reached one `mechanics_prior` call, then failed at `capability.execute`. SC25 L3 `p7-live-20260928090051-26d9c5dc70d9c4440b92075e` reproduced the same zero-action boundary after a 28-step prefix. These are runtime boundary evidence, not L3 strategy results.
9. BP35 L2 then entered a real model loop: run `p7-live-20260928091036-3c259e093dcc7f9a14edca36` executed 23 actions and completed L1 at action 22, but produced 63 invalid plans out of 64 and was manually stopped before L2; it is useful gameplay progress but not a verified prefix.
10. BP35 `p7-next` then replayed the verified 20-action L1 prefix but failed before its first L2 model round (`checked_plans=0`, new actions=0); do not treat it as an L2 strategy result.

## 已验证事实

- Working tree is clean on `main` after the state-doc update; latest code commits are `35c8bfd4`, `33c2571b`, and `415b3bc3`.
- Latest sealed LS20 L3 run with actual model actions remains `p7-live-20260928065144-20547ddb73d8dbfda34b6213`: 53 new actions, still level 2, 0 invalid-plan errors, and objective color-cycle evidence. Later 74135/74743 runs had no model round and must not replace that gameplay evidence.
- Earlier same-day negative evidence stays in force: feedback delivery (`p7-live-20260928032105-ccb913dde66198e3c11a8ee0`) and imperative wording (`p7-live-20260928035815-2ff240d231bcc08ea1d9b4dc`, 20/28 checked-plan errors) did not advance L3. Wording alone is not an accepted fix.
- `src/asterion/services/diagnostics.py` maps known `ProtocolError` messages to bounded codes and falls back to `protocol-error`. Prime-native codes added in `35c8bfd4` sit beside the existing Pi codes (`pi-provider-execution`, `pi-process-ended`, `pi-invalid-jsonl`, `pi-invalid-jsonl-object`, `pi-output-limit`, `pi-turn-limit`, `pi-deadline`). Messages are not retained on the record.
- Focused coverage for the new codes is `tests/test_prime_diagnostics.py::TestFailureCodeDiagnostics.test_prime_protocol_failure_codes_are_bounded` inside commit `35c8bfd4`. That commit was not followed by a live run.

## 当前判断

- The blocking boundary is the native runtime `ProtocolError` at `capability.execute`, after the registered-tool description was shown to reduce invalid plans.
- The new codes are classification only. They do not explain the 04:35 run and do not authorize another paid attempt.
- Cross-level mechanics prior and the registered P7 tool path remain connected. Live L3 improvement is still unverified.
- Project route stays managed. Canonical historical worklist: `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md`. Active theme is the P7 LS20 L3 protocol boundary, not a new numbered phase.

## 历史归档

- Prompt-only tool listing, imperative invalid-plan wording, and pre-computed `failed_attempt_advice` injection are closed paths. The registered tool description is the guidance surface to keep.
- FT09 runs that failed before any bridge call are runtime evidence, separate from the verified registered-tool path.
- Prompt wording changes that left the checked-plan error ratio flat are negative evidence, not a fix.

## 未完成边界

- No claim that LS20 L3, any full game, or hidden rules are solved.
- `35c8bfd4` remains diagnostic-only; it is not the current gameplay focus.
- `make promotion-check` remains external-limited from the earlier isolated-venv `python-dotenv` failure. Do not promote that run to PASS.
- Official score stays the 2026-09-25 closed card `403c8b05-ae64-4dd9-b6f6-1d22910a2e24` at `6.498124098124098`. No newer card.

## 下一动作

1. Run `make asterion-prime-p7-level-witness GAME=ls20 LEVEL=3` once with the `progress` field deployed; track the first L3 actions and whether `levels_completed` reaches 3.
2. If the model still abandons positive `changed_cell_count`, inspect final prompt/output signals and adjust the application guidance/tool contract around hypothesis continuation.

## Ready commands

```bash
cd <asterion-repo>
uv run python -m unittest -q tests.test_prime_diagnostics
git show 35c8bfd4 --stat
```
