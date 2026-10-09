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

## Task31：直接表达115/100的剩余动作空间

用户修订：条件得分绕了一层，应直接告诉模型满分115还剩多少步，以及baseline100还剩多少步。替换而不叠加字段；不使用单个带符号数来迫使模型解释负数。

P7数据层删除 `current_level.level_score_at_current_paid`；115与100各提供 `max_paid_actions_for_X`、`additional_paid_actions_preserving_X`、`paid_actions_exceeding_X`。115阈值沿用精确整数计算，100阈值为baseline。remaining=max(0,threshold-paid)，exceeded=max(0,paid-threshold)。恰好门槛时两者均0；超过门槛时remaining0/exceeded正数，说明该分已不可保持。未知baseline全null；累计已确认paid/RESET不退/未完成真实贡献0保留。

P7研究层同步紧凑host投影和prompt直接解释。Prime通用层不改；这些是领域评分事实，非动作硬上限。仍由LLM自主决定探索与推进，不引入策略切换或补充关卡路线。快照2KiB及原反馈容量/错误/前缀/未知边界继续有效。

Task30封存见证仅验证26250c0e，不覆盖本变更。Task31须独立changed-code review、focused tests、TS→Python→promotion及新的有限packagedr11l见证；无新BP35授权。

## Task33：实跑策略与动作选择说明

用户明确要求：开局先报告游戏策略选择，策略改变后再报告一次；每个动作或动作组说明原因，避免啰嗦。不是事后补问。

P7研究层复用现有NOTES：首个付费动作前记录选择、当前依据、预计付费动作代价和主要未知；可先免费观察/计算，未知代价保持未知，不为填数追加探针。实质改变策略时，在下一批动作前更新一次；未变不重复。日常记忆格式与其它更新时间仍自主。

每次plan用既有goal的1–2短句说明做什么和为什么；一个动作组共享理由，无额外NOTES调用或每step解释。采用ASD-STE100的短句、常用词、主动表达、明确对象、每句一个判断原则；中文不硬套英语word计数或声称80%量化认证。模型记录要求不变成host动作准入检查；无新schema/tool/generic游戏策略，数据层客观事实不改。仅源码与focused边界验证，本轮不启动新实测。

## Task35：资源紧迫时明确倾向推进

用户认为泛化的“随资源变化重新权衡”过于模糊，要求模型意识资源紧张时选择积极推进。P7研究提示具体对照115/100剩余空间与已知路线估计；未知直接保持未知，不为估数追加计算。评分空间或有效datedtime变紧且证据支持有价值行动时，优先积极推进，减少不会改变路线选择的付费探针。必要验证仍可做，比较信息能改变的选择及可避免失败/逆转与资源成本；不要求消除全部未知，不固定积极/保守阈值或模式。

goal仍1–2句，评分或时间实质影响选择时简短写余量、为何推进或为何探针仍值得。不重复无关数字，不新NOTES调用/硬门控/攻略。115/100均超额时仍继续可得分及通关目标。Prime通用层与P7数据层不变；本变化是领域研究策略提示。用户授权完整BP35L1–L6冷测，root优先评估L1，若不理想可中止；L1满分门槛不是应用动作cap，不把该评估规则加给actor。
