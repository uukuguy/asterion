# Task30 Resource-aware autonomous research design

## Authorization and objective

User authorizes “设计与实现” after clarifying that exploration versus progress is a dynamic choice under remaining time/action resources. Preserve model-owned reasoning and Prime/P7 research/P7 data layers. Implement objective timely resource delivery and concise general tradeoff guidance; do not claim L1 efficiency improvement from code/tests. No new BP35 is authorized; required finite packaged r11lL1 is deployment verification only.

## Evidence and chosen scope

Task29 cold6levels completed211paid/zero deaths/1548.246660s, L1Q70.56/others115. ExtraL1 probes are exploration costs, not inherently erroneous. Existing guidance mentions information value but model may not rebalance as costs accrue. SolverControl remaining is live on reads, but P7 IPython tool returns do not refresh model memory; long model+cell chains can retain old time numbers. Rebuilding whole anchored snapshot on every context request would reintroduce prefix instability. AdditionalFD/request hooks are unnecessary for this bounded repair.

Chosen approach: dated resource facts at existing successful/error tool completion, not a separate model call/tool/runner. No per-request realtime guarantee during an in-flight LLM request: sample is explicitly dated; hard host admission remains authoritative.

## Prime generic layer

Reuse trusted TaskDeadline double-clock absolute limits and sticky expiry. Add snapshot() reading clocks once under its existing lock, returning bounded remaining plus sampled epoch/monotonic and fixed corresponding deadlines. Nonfinite clock cannot produce trusted fabricated sample; retain fail-closed expiry and mark unavailable sample fields. No origin/total allowance guessed from object construction; operator origin injection is outside this minimal design. No deadline renewal, action dispatch, provider config, domain imports or new manifests.

Generic resource-aware guidance: investigation and progress can both yield information; weigh expected decision value against research cost, failure/reversal cost and remaining opportunities as evidence/resources change. Model chooses; no mandatory table/strategy classification/threshold transition or per-step justification. Guidance is reusable outside P7 and integrated into primary P7 research and natural continuation.

## P7 data layer

Existing settled journal remains the only score ledger. Add current_level fields level_score_at_current_paid (conditional upon completion at that cumulative count; null if0/unknown), max_paid_actions_for_115=isqrt((20*b*b)//23), additional_paid_actions_preserving_115=max(0,threshold-a). Explain those as scoring facts, not authorized action balance/route length. Current unfinished contribution stays0; existing completed scores and game cap unchanged. Unknown baselines and unsettled tails preserve null/unavailable. Exact integer threshold handles21→19,48→44,44→41,38→35,33→30,87→81 and equality boundaries; RESET/undo never refund.

## P7 research/host integration

SolverControl exposes legacy remaining plus a dated time-snapshot from generic TaskDeadline; fallback clock path is dated monotonic only and never invents wall origin. P7 Runtime samples current context once at tool completion after existing pause/admission logic. Add a compact host_resource_snapshot to the FIRST JSON metadata object of IPython results (bridge forwards only firsttext); keep execution_status/error/export/stdout/content and callid/status unchanged. stdout with same-lookingJSON is data, never promoted as host facts. Non-JSON stopped results stay readable; optional capture/serialization failure must not change a known outcome or erase original feedback. Validate finite bounds and cap snapshot<=2KiB. The new snapshot is lowest priority: when an existing legal result lacks capacity, omit the new field and preserve original stdout/error/exports/content exactly; do not truncate old evidence or increase existing output limits to fit it. Missing new facts mean no refreshed sample, not infinite resources.

For workspace/action dictionary tool results, append the same current-resource field. Historical plan_id reads retain original observation, budget and feedback; fresh current resources have a distinct field/reference. Do not overwrite historical results or mutate stored plans. Current memory/certainty share one captured context where possible; do not re-anchor/update large state during pure computation. Small host facts become ordinary sequential tool-history metadata, preserving earlier model input prefix. No Tool registration/allowlist changes required.

Compact view includes source marker, observation_ref, known/blocked flags, host action limit/used/remaining, target/completed progress, dated host time, and current conditional scoring facts; no board, raw logs, prior levels, strategy decision or estimate of unknown remaining work. Describe latest host snapshot as dated facts; old snapshot is historical and cannot authorize an action.

## Verification and limits

RED→GREEN focused tests: dual-clock/stickyexpiry/finite values/immutability; fresh sampled time after delayed cells/pause; Python-error/interrupted result fidelity; stdout spoof isolation; bounded near-cap result; same-id historical read unchanged with distinct current facts; unknown accounting null; exact115 threshold equality/reset; source/key/dependency neutrality. Test ordinary outcomes rather than hardcoding prompt prose. Independent Astra design and changed-code review; TS tests→focused Python→lint/docs→fullpromotion→sourcecommit→actual packaged r11lL1 identity/replay/cleanup audit. Do not repeat broad checks after green without a new concern. No unseen-game/stable strategy/cross-domain optimality claim; BP35 effects remain untested.
