# Task30 Resource-aware Research Implementation Plan

> **For agentic workers:** Use subagent-driven development, RED→GREEN and independent review. Root commits; workers are not alone and must preserve each other's edits.

**Goal:** Give the autonomous model dated resource and scoring facts for dynamic research/action tradeoffs.
**Architecture:** Generic deadline facts/guidance; P7 settled scoring data; P7 trusted tool-completion resource delivery without moving context anchors.
**Tech Stack:** Python unittest, packaged TypeScript Pi extension and existing controlled execution.

## Global constraints

Spec: [Task30 design](../specs/2026-10-09-prime-resource-aware-research-design.md). No new runtime/tool/FD/provider call or strategy gate; no renewal/refund/oracle. User authorized implementation and required packaged deployment, not another BP35. Currentsource9557ad63/docs6d87e2b9; existingJOURNALtail preserved. No guessed origin/total time. Unknown outcomes remain unknown.

## Task1 — Generic and host resource facts (context_impl)

Ownership: agents/prime/deadline.py and continuation.py; P7 solver_control.py/research_runtime.py; tests/test_prime_deadline.py, test_prime_p7_solver_control.py, test_prime_p7_witness_deadline.py, test_prime_p7_research_runtime.py; new tests/test_prime_p7_resource_snapshot.py.

- [x] Write RED for TaskDeadline.snapshot and dated sample after clock advancement/sticky expiry, boolean/nonfinite rejection and copied results.
- [x] Add one sampled generic snapshot; share clock sampling with remaining_seconds, no new authority or allowance origins. Add resource-aware guidance constant/export; integrate natural continuation through existing guidance.
- [x] Write RED for purecell metadata resource refresh (firstJSONtext), error/stdout spoof preservation, near-cap payload, failed optional capture, historical plan read and stable prior input prefix.
- [x] Integrate SolverControl dated budget and P7 host_resource_snapshot at post-admission tool completion. IPython FIRSTmetadata must remain valid JSON; preserve execution_status, exports and original outcome. Compact snapshot<=2KiB; if a legal original result is near its existing cap, omit newfacts and preserve original content exactly (no old evidence truncation or cap increase). Reuse captured currentcontext without mutating raw results/history. No fullmemory refresh on purecell.
- [x] Run focused unittest and send diff+RED/GREEN evidence to root/review.

## Task2 — P7 scoring facts and primary guidance (deployment)

Ownership: P7 score.py/prompt.py; tests/test_prime_p7_score_planning.py and new tests/test_prime_p7_resource_scoring.py. Do not edit runtime/control owned byTask1.

- [x] RED exactthreshold and conditional current score, a0/null/unsettled/reset consistency. Example b21/a0→threshold19/conditionalnull, b48/a42→threshold44/additional2/conditional115; b21/a25→conditional70.560000/additional0. Actual game contribution unchanged.
- [x] Minimal derived facts from settled existing ledger, isqrt((20*b*b)//23); no new scoring ledger, cap or forced strategy. Preserve unknowns.
- [x] Primary prompt consumes generic resource-aware guidance; explain dated latest host snapshot, conditional scores and distinction of scoring room/real action/time limit. No requirement for every-step model explanation or BP35 route.
- [x] Focused unittest, independent reviewer changed-code handoff.

## Task3 — Integration and packaged closure (root + deployment + review)

- [x] Root independent design challenge followed by final changed-code review; fix important findings with focused tests.
- [x] Run npm --prefix packages/typescript/asterion-prime-extension test, relevant Python unittest, lint/docs and RUST_TEST_THREADS=1 make promotion-check. No TS registration change planned; resource identity stays exact.
- [x] Commit reviewed source, journal and checkpoint. Deployment creates one fresh finite actual make asterion-prime-p7-level-witness GAME=r11l LEVEL=1 (current.env), original900+180.
- [x] Verify actualinstalled source/wheel/resource/allowlist, real resource facts/error/prefix boundary as applicable; fullSDKreplay/trace/manifest/cleanup and independentREADY. Preserve userconsole.
- [x] Close standalone review, canonical worklist/state/index; journal allcommits. Distinguish implementation/deployment from untested BP35 policy effect. No further run.

Implementation final191PASS/TS79PASS+6externalskip/lint/docs/diff/independentAPPROVE. Sourcefreeze26250c0e/fullpromotion25PASS/packagedr11l4paid0RESET67.896532s/independentREADY complete. ActualPi fact receipt/adoption unknown. No BP35. Subsequent direct115/100room adjustment is Task31, outside this sealed deployment.

## Task31 — Direct scoring action room (follow-up)

User requests direct115/100remaining steps instead of conditional score. Same spec Task31 amendment. Deployment owns score/prompt/scoringtests; context_impl owns runtimeprojection/resourcetests; root integrates docs/commit; Astra reviews. Preserve shared edits and sealedTask30evidence.

- [x] RED→GREEN exact115/100remaining/exceeded facts; unknown/reset/threshold edges; remove conditional score.
- [x] Synchronize smallhost projection and factual prompt; retain allresource/cap/prefix/error boundaries.
- [x] Independent changed-code review, focusedintegration/TS/lint/docs/diff.
- [x] Freeze reviewed source, fullpromotion and fresh r11lL1 original900+180; source/install/tool identities, replay/seal/cleanup and independentREADY.
- [x] Update state with exact verification boundary; noBP35.

Task31 sourceba51c62e/48PythonPASS/79TS+6skip/APPROVE/fullpromotion25PASS/newr11l6paid0paidRESET94.471582s. Finalmanifest115entries independentREADY, state closed; actualPi fact receipt/adoption unknown, noBP35.

## Task33 — Contemporaneous strategy and action reasons

User explicitly requests live initial/changed strategy reporting, plus concise reasons per action/group. P7prompt/associated focusedtest ownedcontext_impl; Astra review; root docs/commit. No source changes in Prime/data/tool registration. Preserve sealedTask32 evidence.

- [x] Reuse NOTES for initial/changed strategy, allow unknown costs, no fixedstrategy taxonomy/hostgate.
- [x] Reuse goal for1–2shortsentences perplan; no perstepprose/extraNOTEScall, concise STE-style Chinese.
- [x] Focused source contract tests + existing noNOTES-admission regression, independentchangedcode review, lint/docs/diff.
- [x] Commit and close source state; new live adherence and strategy-effect untested, no further trial.

Task33 source reviewAPPROVE/root35PythonPASS1.678s/lint/docs/diff; prompt935B additional, no new tool/runtime/data changes. Implemented guidance only; live adherence/deployment/effect not rerun.
