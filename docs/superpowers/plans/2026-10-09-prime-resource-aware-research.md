# Task30 Resource-aware Research Implementation Plan

> **For agentic workers:** Use subagent-driven development, RED→GREEN and independent review. Root commits; workers are not alone and must preserve each other's edits.

**Goal:** Give the autonomous model dated resource and scoring facts for dynamic research/action tradeoffs.
**Architecture:** Generic deadline facts/guidance; P7 settled scoring data; P7 trusted tool-completion resource delivery without moving context anchors.
**Tech Stack:** Python unittest, packaged TypeScript Pi extension and existing controlled execution.

## Global constraints

Spec: [Task30 design](../specs/2026-10-09-prime-resource-aware-research-design.md). No new runtime/tool/FD/provider call or strategy gate; no renewal/refund/oracle. User authorized implementation and required packaged deployment, not another BP35. Currentsource9557ad63/docs6d87e2b9; existingJOURNALtail preserved. No guessed origin/total time. Unknown outcomes remain unknown.

## Task1 — Generic and host resource facts (context_impl)

Ownership: agents/prime/deadline.py and continuation.py; P7 solver_control.py/research_runtime.py; tests/test_prime_deadline.py, test_prime_p7_solver_control.py, test_prime_p7_witness_deadline.py, test_prime_p7_research_runtime.py; new tests/test_prime_p7_resource_snapshot.py.

- [ ] Write RED for TaskDeadline.snapshot and dated sample after clock advancement/sticky expiry, boolean/nonfinite rejection and copied results.
- [ ] Add one sampled generic snapshot; share clock sampling with remaining_seconds, no new authority or allowance origins. Add resource-aware guidance constant/export; integrate natural continuation through existing guidance.
- [ ] Write RED for purecell metadata resource refresh (firstJSONtext), error/stdout spoof preservation, near-cap payload, failed optional capture, historical plan read and stable prior input prefix.
- [ ] Integrate SolverControl dated budget and P7 host_resource_snapshot at post-admission tool completion. IPython FIRSTmetadata must remain valid JSON; preserve execution_status, exports and original outcome. Compact snapshot<=2KiB. Reuse captured currentcontext without mutating raw results/history. No fullmemory refresh on purecell.
- [ ] Run focused unittest and send diff+RED/GREEN evidence to root/review.

## Task2 — P7 scoring facts and primary guidance (deployment)

Ownership: P7 score.py/prompt.py; tests/test_prime_p7_score_planning.py and new tests/test_prime_p7_resource_scoring.py. Do not edit runtime/control owned byTask1.

- [ ] RED exactthreshold and conditional current score, a0/null/unsettled/reset consistency. Example b21/a0→threshold19/conditionalnull, b48/a42→threshold44/additional2/conditional115; b21/a25→conditional70.560000/additional0. Actual game contribution unchanged.
- [ ] Minimal derived facts from settled existing ledger, isqrt((20*b*b)//23); no new scoring ledger, cap or forced strategy. Preserve unknowns.
- [ ] Primary prompt consumes generic resource-aware guidance; explain dated latest host snapshot, conditional scores and distinction of scoring room/real action/time limit. No requirement for every-step model explanation or BP35 route.
- [ ] Focused unittest, independent reviewer changed-code handoff.

## Task3 — Integration and packaged closure (root + deployment + review)

- [ ] Root independent design challenge followed by final changed-code review; fix important findings with focused tests.
- [ ] Run npm --prefix packages/typescript/asterion-prime-extension test, relevant Python unittest, lint/docs and RUST_TEST_THREADS=1 make promotion-check. No TS registration change planned; resource identity stays exact.
- [ ] Commit reviewed source, journal and checkpoint. Deployment creates one fresh finite actual make asterion-prime-p7-level-witness GAME=r11l LEVEL=1 (current.env), original900+180.
- [ ] Verify actualinstalled source/wheel/resource/allowlist, real resource facts/error/prefix boundary as applicable; fullSDKreplay/trace/manifest/cleanup and independentREADY. Preserve userconsole.
- [ ] Close standalone review, canonical worklist/state/index; journal allcommits. Distinguish implementation/deployment from untested BP35 policy effect. No further run.
