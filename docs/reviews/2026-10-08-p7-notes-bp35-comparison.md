# Frozen NOTES P7: BP35 L1–L6 comparison

## 最终结论

**这版 NOTES 没有改善 BP35 自主解题表现。** 已确认通过四关，335条已提交付费动作；L5未通过，L6未进入。另有一个执行中计划对应的迟到、截断 SDK 响应，未完成正式结算，因此335不能作为全部物理动作的上界。末段记录到合盖休眠、计时分歧及清理超时；严格5400秒截止、180秒清理宽限和终局封账均未获验证；本轮不能作为完整限时基准。

| 关卡 | 新 NOTES P7 已提交动作 | 旧 cold P7 动作 | 原版 arc-skill 动作 |
| --- | ---: | ---: | ---: |
| L1 |44|26|19|
| L2 |74|47|48|
| L3 |75|41|34|
| L4 |51|23|23|
| L5 |91，未过；另有未结算尾响应|30|45|
| L6 |未进入|46，未过|102|

新P7前四关的真实观察到过关时间分别为639.972、585.888、994.202、771.431秒；过关边界44/118/193/244均由完整SDK响应与账本交叉核对。L5有6次已提交RESET，全程11次。详细研究对照的各前缀边界见下文；不能把早期75步/5RESET前缀当最终L5统计。

| 已记录指标 | 旧 cold P7 | 新 NOTES P7 |
| --- | ---: | ---: |
| 单次输入峰值 |255820|36572|
| 累计 normalized input |19179445|7205603|
| 累计 output |134227|191495|
| usage记录 |171|661|
| Python计算累计 |1.391秒|2.863秒|

输入峰值减少约85.7%，累计输入减少约62.4%，但输出增加约42.7%，usage记录增至约3.87倍。记录不是完整等量任务的单位成本比较，cache/请求时钟也不齐全；它说明**压低上下文规模并不等于减少研究往返或形成有效整体理解**。新P7有242个归档cells，其中64个失败，计算本身仍只占数秒。217个有终止记录的plans包含66次预测失配、30次prefix复用拦截；29次零派发与真实失败/付费动作分开统计，另一个计划仍未正式结算。

145个NOTES版本为495–1439 UTF-8字节，中位861、最终595；首版无父，144次后续替换均链接有效。654条实际投影日志均为cut。笔记与原始资料持续留存，但即时模型视图主要依赖当前笔记/观察和最近锚点之后的交互。主要已证实问题是研究入口使用困难、状态与因果认识反复退化、局部失败没有稳定转化为整体计划；激进裁剪可能放大错误摘要，尚无单变量证据证明其独立因果作用。

## 时钟、部分结果与清理边界

- 计划07:45:31 CST启动，09:15:31截止。最后完整提交动作335为09:12:26.641042的RESET；337条完整SDK行包含2次初始非付费RESET及335条已提交动作。
- 主SDK文件第338行有49160字节截断尾：09:43:13.027182、ACTION6、GAME_OVER、完成4关的前缀，与console内未结束的执行中计划一致。它不是footer；不能修复后冒充完整观测、加进已提交账本，或声称截止后没有动作结果。
- guard记录09:30:16才发起停止；host最终receipt为09:43:13。墙钟7062.072秒、单调5295.828秒，差1766.244秒。系统电源日志直接记录09:11:54起的Clamshell Sleep及后续maintenance sleep/wake；休眠解释计时差是有支持的推断，不能精确分摊所有时间。
- 原清理调用TimeoutExpired；`summary.json`不存在，应用正常终局、sealed trace与replay均未验证。L5到预定deadline的2407.174秒只是算术区间，不能称真实终局用时；迟到清理阶段的5.450秒也不能称180秒宽限合规。
- 后验独立检查确认本次host三进程、guest unit/cgroup及独有运行路径进程已清理，临时认证移除，原console保留。563项source/tool和8项launch哈希不变，579项安装wheel文件与保留wheel一致，Node身份一致。源码未热修，无第二次试跑。

这些缺口属于需要加强的执行与证据保障，不能拿增加研究步骤门槛来替代。


## Trial boundary

The user continued after the [NOTES implementation and r11l deployment verification](2026-10-08-prime-research-notes.md). The one new cold BP35 run has ended; its measured failure and incomplete finalization are stated above.

- Production:`ebcefec9`; exact previously verified wheel SHA256:`7a599c0139e35c043329179f3d8badea8cee7a95f2767480a6944337cc0250a3`.
- Offline `bp35-0a0ad940`,seed0, empty independent history/profile/research root, gpt-6.1-sol/high, target6of9.
- Same existing autonomy controls:5400 seconds total, at most6 natural rounds,1000 primitive actions,1024 model callbacks and4096 tool callbacks. Absolute start2026-10-08 07:45:31 CST; cutoff09:15:31. Another180 seconds permits cleanup only.
- No operator game hints, old routes/notes, midrun solver changes, additional attempts, L7 actions or official card. Actor-written research and existing generic natural continuation remain autonomous behavior.
- Actual restricted-worker bootstrap/persistence/recovery and forbidden-file probes pass. An independently reviewed launch-only Node wrapper preserves argv/stdin/stdout/exit behavior and captures full private stderr, so later context-cut records survive the normal4096-byte summary cap. No model-visible instrumentation changed.

Installed Pi does not consume the existing debug-transcript setting. Complete provider request start/end and cache/reasoning-time decomposition therefore remain unavailable. Environment timestamps, ordered trace usage, private notes ancestry and actual context projections can still support a precise outcome and mechanism comparison.

## Fixed baselines

| Level | Previous cold P7 actions | Original arc-skill actions | Previous P7 wall seconds | ARC wall seconds |
| --- | ---: | ---: | ---: | ---: |
| L1 |26|19|705.593|184.651|
| L2 |47|48|563.398|261.165|
| L3 |41|34|668.007|195.794|
| L4 |23|23|640.492|224.530|
| L5 |30|45|646.165|1086.491|
| L6 |46, unfinished|102|2174.958 to deadline|1415.222, includes stage gap|

Previous cold P7:213 paid actions/5 completed/5400-second cutoff, with RESET in L2 and L3. ARC:271 paid/6 completed, with RESET in L2,L5,L6. ARC L1–L6 action edges19/67/101/124/169/271 were rechecked directly from its272-event ledger; this fills the earlier report's aggregated L1–L4 count124.

Times above run from initial observation or previous pass to the next pass, except unfinished P7 L6 ends at its deadline. ARC L6 includes its stage transition/cleanup/restart gap; its Stage2 natural model round lasted1127.976seconds. ARC's overall3393.950seconds spans Stage1 start to Stage2 natural completion and includes stage overhead. These distinctions prevent attributing every elapsed second to model inference.

The older mature P7 sample has118 actions through L4,32 for its located L5 success and43 for L6. This193-action combination excludes the lengthy outer diagnosis, code changes and failed attempts; it is not an equal cold-start result.

## Questions for the new run

1. Does it complete L6 within the same finite allowance, and what are the actual per-level actions, RESETs and times?
2. Does model-maintained NOTES remain compact and useful across levels, and do actual model-view cuts continue through L5/L6?
3. Does normalized input growth decrease? Note bytes, provider tokens, usage-event counts, natural rounds and tool transactions must remain separate measures.
4. Does learning change subsequent experiments and plans? Reduced input alone does not establish better game reasoning, faster end-to-end completion or fewer actions.

Previous P7 had171 usage events, normalized input19179445/output134227, peak255820. That peak occurs after L5 passes and before the first L6 action; the next input drops41315 and later grows138388. ARC's tiny L6 NOTES511–915bytes coexist with a Stage2 input peak220388; its note size is not its whole model context. Neither dataset provides a controlled single-variable causal comparison.

## Completed-level process audit

L1 passed at paid sequence44, SDK response2026-10-08 07:56:12.344639 CST,641.305seconds after launcher start. This is an exact pass edge, not a sampled post-pass action count. It then advanced to L2. The final table above uses initial observation/pass clocks;641.305seconds here is explicitly launcher-based.

Independent read-only inspection found a concrete application usability issue. `p7_research` is registered as an importable worker module, while only `prime_workspace` is injected as a global. The prompt lists reader methods without an explicit import example. In the first26 cells, the actor makes19 namespace inspections and2 bare-name calls, with no import attempt, then records the module as unavailable. This supports import/discoverability friction, not a missing-runtime-module claim.

The actor later manually transcribes compressed frame rows and indices into two Python cells of2392/2519characters. The codec itself is lossless; the manually copied arrays differ from recorded observations in4/1 background pixels, with no demonstrated actionable consequence. More materially, accepted sequence2 NOTES says an action had no frame effect despite36 recorded pixel changes. Correct observation references do not establish the truth of free-text conclusions. Later notes autonomously correct substantial geometry/mechanism errors.

The actual ARC L1 log instead shows a row-numbered full grid, short queries using prebound `grid`/`np`, and worded geometry transitions. These affordances reduce the work needed to inspect evidence. They do not establish that encoding or NOTES alone caused the observed performance difference. No finding was fed to the actor; no live repair was made. The L5 section below records the later successful import and evidence reads.

### Completed L2: extra failure, not a longer final route

L2 passed at paid sequence118,2026-10-08 08:05:58.233021 CST,585.888382seconds after L1. Its74 actions divide exactly into6 actions to first death +1 RESET +26 actions to second death +1 RESET +40 successful actions. Previous P7 used6+1+40=47; ARC used6+1+41=48. The extra failed episode and RESET explain all27 additional actions against previous P7; its final successful episode is equally long.

The second death follows a concrete perception error. NOTES at sequence73 treats a central column as clear, while the recorded frame contains hazard-colored pixels at all three relevant tile centers. Sequence77 NOTES explicitly corrects confusion between tile edges and centers; the correction survives RESET78 and the final successful episode. No outside diagnosis was supplied.

L2 has18 note revisions of688–1051bytes. All retain an absent/possibly absent reader belief; its19 cells contain13 namespace inspections and no research-module import. Eight `prefix-action-reuse` stops introduce separate tool friction:6 dispatch no actions and2 stop after a partial prefix, leaving11 proposed steps unexecuted. Those11 are not paid actions; no paid undo or unchanged-board action appears in this level. A short memory can preserve both useful corrections and mistaken capability beliefs.

### Completed L3: knowledge regression and repeated relearning

L3 passed at sequence193,2026-10-08 08:22:32.434557 CST,994.201536seconds after L2. Its75 actions comprise13+6+12 failed gameplay actions,3 RESETs, then41 successful-episode actions. Old P7 used6+1+34=41; ARC completed a clean34. Against old P7,27 extra failed/restart actions and7 extra final-episode actions account for the34-action gap.

The strongest evidence concerns a toggle whose center pixel remains unchanged while its surrounding shape changes. NOTES correctly learns it, later reinterprets the unchanged center as an ineffective click, and then learns the same toggle again. A known hazard briefly becomes “unknown.” One repeated fatal move occurs even though the current note retains the earlier counterexample; the new plan relies on an unsupported blocking-wall assumption. Later the actor correctly uses closed gates as protective ceilings and completes. ARC's actual L3 log applies that protective-ceiling idea early, then reuses it without death/RESET.

L3's36 note snapshots are649–1026bytes. They preserve useful controls, deaths and later strategy, while key shape/palette facts regress. Forty-seven archived cells include18 failures;27 inspect the namespace and none imports the raw reader. Twenty of54 plans stop for prediction mismatch, including both harmful outcomes and harmless pixel-prediction mistakes. These are distinct from actual deaths and zero-dispatch tool rejections.

The current view policy replaces messages preceding the accepted NOTES tool group with instructions/current notes/current board, retaining that group and later messages. It has no independent short buffer of previous frames and action results. Therefore an incorrect summary can remain while its contradictory earlier evidence exits the immediate view. Actual cuts and semantic regressions coexist here, but exact request clocks/revision-tagged cut logs are unavailable, and this run does not prove that cuts caused any specific error. The retained-but-ignored counterexample also prevents blaming all failures on missing history.

ARC's short NOTES does not itself trigger comparable prefix deletion; its outer conversation retains earlier tool evidence, subject to host behavior. A future bounded recent-evidence window and separating note editing from automatic prefix deletion are candidates for controlled comparison. This does not justify restoring all old execution logs or claiming that more context alone solves the task. No such change is made during this run.

## L4 boundary

L4 passed at sequence244,2026-10-08 08:35:23.865701 CST,51 actions and771.431144seconds after L3. Both comparison baselines used23 actions. It then entered the requested L5; the final committed evidence remains at four levels, with no L6 entry.

## L5 实际过程对照：稳定理解如何变成行动

以下过程审计覆盖新 P7 paid245–319；最终计数已在顶部单独补齐。新 P7 seq244、旧 P7 seq137、ARC event124 的64×64可见开局在颜色归一化后4096像素全等。它们面对相同可见布局；这不证明隐藏状态、上下文或预算等同。

两者首次都在翻转重力后死亡。ARC 随后使用自己先前的帧与 camera offsets 重建世界坐标地图，区分中心颜色相同、周边形状不同的门状态。它保存可复用机制、明确尚未证实的 L5 假说，并拟出完整路线。重试中先用门边缘像素验证状态切换，形成保护顶棚，再翻转重力和返程，最终通过。其45步包括13步探索、一次 RESET 和31步成功一轮。

新 P7 在上述前缀没有点击这两道门。它曾正确记录一次横向移动穿过稀疏门导致死亡（seq294/295）；seq304/307/308 的笔记却把这段历史改写成“删门导致死亡”，从而推断保持门不动就是安全的。seq309重复危险横移，再次死亡。原始动作是移动，不是点击；原始帧也显示门一直处于稀疏形态。随后又出现重力方向的重新误判与重试。这里的证据是**错误因果解释覆盖已有正确记录**，并非仅仅没有足够动作额度。

截至319，L5已花75动作、5次RESET，经历五次失败。与 ARC 的差别在于它没有把反例组织成稳定的状态模型与保护计划，而是反复修改局部解释。这个前缀内95个真实归档 Python cells 中67个包含 namespace/dir/source 查询，61个发生在首次研究模块导入前。这些是模型实际提交的代码，不是运行时自动附加模板，也没有把 started/completed 重复计数。

seq311后，模型首次成功 `import p7_research`，开始读取原始帧和历史。这证明接口此前存在，但发现与使用成本很高；也保留了模型晚期自主恢复的事实。不能再把“从未成功读取”用于整个 L5。

ARC 的 L5 包含自然续轮、回放缓存阻塞期间的静态研究和外部恢复，不是完全同等连续墙钟实验。它还拥有不同的变化摘要、预绑定数组、地图/路线保存与宿主上下文行为。上述对照支持具体过程差异，不能把全部结果归因于 NOTES 或裁剪一个变量。P7 精确提交预测的字段并非都保留在可用日志里；这里对其认识的判断来自 NOTES，动作效果来自真实帧和付费账本。

## 稳定认知、当前焦点与近期证据

用户指出 ARC NOTES 更接近此前 P7 的“游戏稳定认知”，能够支持快速复用和总览。这与实际材料相符：ARC 把可复用机制保留为主线，另存地图与路线，并对当前关卡的新适用性进行验证。它也记录局部状态，不是只保留抽象规则；日志不能证明模型内部存在某种 System1/System2。

新 P7 将机制、瞬时坐标、预算、工具可用性猜测和下一动作放在一份频繁全文替换的笔记里。有效知识并未全部消失，但关键机制会无新证据地退化，甚至改变真实失败的原因。把笔记写短并不等于形成稳定理解。

后续设计候选应按信息生命周期分层，保持自由组织文本和模型自主判断：

- **通用层**：相对稳定的任务认识、当前研究焦点、有限近期证据分别维护；笔记更新不必立即删除所有更早交互。完整原始记录继续按引用检索。具体保留策略仍需受控验证。
- **P7 适配层**：映射为游戏机制与策略、当前关卡问题/路线、权威观察与近期变化。提供可直接使用的原始帧/坐标/变化查询，减少手抄编码与重复命名空间探索。
- **动作与记忆解耦候选**：当前观察身份、预算、取消和失配截断仍由工具保证；评估是否每次局部预测失配都必须重写整份知识。保留稳定机制的责任属于模型，不能由通用框架猜游戏规则，也不能恢复每步强制填表的流程。

这些是当前证据支持的改进方向，尚未实施或证明能改善通关。尤其近期证据窗口只能降低错误摘要成为唯一依据的风险，不能保证模型一定正确利用保留下来的反例。

## 用户明确的后续原则

充分发挥 LLM 的自主思考与整体判断，框架提供数据保障、工具与真正的执行硬约束。不得把假定有效的研究方法变成细碎的准入门槛。上述三类记忆是可用能力，不是必填表或固定阶段。NOTES强制修订、每次笔记后的裁剪、坐标复用与无变化启发式拦截、细粒度预测要求，都需要按这一原则重新论证。当前观察真实性、权限隔离、预算取消与未知结果不重复派发继续保障。方向已记录为 D-2026-10-08-02；本次运行保持冻结，后续能力尚未验证。

## Evidence status

Preflight, frozen identity, committed-prefix accounting and eventual owned cleanup are independently verified for `p7-live-20261007234531-87e38f105ea518bdba94623a`. Target6 was not achieved. Strict deadline/grace compliance and application finalization/seal/replay are not verified; the uncommitted partial response remains preserved.

Private configuration, probe, launch, progress, raw evidence, `public-final-metadata.json`, `operator-final-audit.json`, `recording-integrity-metadata.json` and `final-independent-review.md` remain under `.asterion-private/p7-notes-bp35-20261008/` and its referenced isolated operator root. No raw game routes, private notes, credentials or provider payloads are published here.

Baseline sources: [previous cold P7](2026-10-07-p7-cold-autonomy-bp35.md), [original ARC BP35 trial](2026-10-07-arc-skill-bp35-l5-l6-trial.md), [offline interactive explanation](2026-10-07-bp35-autonomy-explainer.html).
