# Task30：动态资源权衡的设计、实现与验证

Task30封存版本26250c0e落实用户提出的方向：策略随证据、剩余时间和动作成本变化；积极推进与保守探索由LLM自主选择。没有固定策略模式、强制推理步骤或baseline硬截止。

## 三层实现

- **Prime通用层**：TaskDeadline新增带采样时刻的双时钟事实快照，固定期限和过期不可恢复约束保留。提供简短通用指导：推进与调查都可产出信息，按资源与证据变化比较决策收益、研究/失败/逆转及机会成本；未知工作成本保持未知。
- **P7数据层**：沿用唯一真实已确认动作账本，新增当前条件分、精确115分整数步数门槛与剩余评分空间。零动作/未知baseline/未确认结果不伪造分数；未过关实际贡献仍0。RESET与撤销不退还计费，评分门槛不产生执行授权或强制停止。
- **P7研究层和宿主适配**：在既有工具完成边界附加小型host_resource_snapshot，包含当前引用、确定性、动作资源、进度、带日期的时间与当前评分事实。纯计算写入已有首段JSON元数据，不新增工具/FD/runner，不移动完整上下文锚点。模型根据这些事实自主重估探索和推进。

## 修复的实际信息缺口

此前时间余额每次读取时准确，但IPython返回不更新模型所见的状态快照；长模型请求和连续计算后，模型可能继续使用旧余额。新增完成边界读数使其区分历史预算与较新的资源事实，**不承诺正在进行的模型请求中实时刷新**。没有从对象创建时刻推算原始时间额度或漏算启动/恢复成本。

历史plan_id回读保留原动作、观察和预算；当前资源另附引用。采样或容量失败时新字段可缺失，不表示无限资源。近原64KiB计算或60KiB计划反馈上限时优先保留原合法结果，不截stdout/错误/exports来容纳新字段，不增加容量。JSON形式和execution_status保持桥兼容；程序stdout中的同名JSON不能伪造宿主读数。快照至多2KiB，不带画面、完整NOTES、前关历史或评分公式副本。

## 独立复审发现与处理

1. 控制器允许独立时钟；展示余额不能只使用TaskDeadline的时钟。复现90秒与已停止控制器矛盾，修为采样两来源后取更严余额，并标记采样来源，RED→GREEN。
2. 联合测试发现当前状态读取失败会丢独立有效memory。恢复失败分支原合同，保留已接受结果和有效记忆，确定性仍保守处理，新读数省略。原测试未弱化。
3. 完整但非法类型的确定性读数可能与顶层保护矛盾。对两布尔标记严格验证，非法读数使新快照省略；新增完整异常context回归矩阵通过。

最终changed-code独立APPROVE，无阻塞问题。此结论覆盖实现和边界，不等于自主策略效果已验证。

## 验证

- 评分lane：17tests，预期RED→GREEN，独立PASS。
- 时间/工具lane：54focusedPASS，兼容和确定性修复针对性PASS。
- 最终联合19modules：191PASS，26.935秒，日志/tmp/asterion-task30-python-final-green.log；早期191项中1error记录保留在/tmp/asterion-task30-python-final.log，已修复，不能将早期结果标PASS。
- TypeScript扩展测试：79PASS/6externalcompatibilityskips，注册与bundled资源未修改。
- make lint、docs-check、diffcheck通过；完整promotion PASS：25commands/provider_operations=0/full_dataset=no。

## 冻结版本部署验证

生产提交26250c0e；canonical wheel fc6d064b9ff7f779095048de83b26c14bae88ba13524c7877ff16a890262c616；扩展a799561245c1d8ba7b6a1156f7d1954d44cc6072e05feaa831404b73c641d140。source570/install588/archive1685逐项一致。

一次fresh packaged r11l L1（Solmedium，900+180未续期）：4计费动作、0计费RESET、Q115；baseline22，目标67.896532秒，收口含清理86.545788秒。2初始化RESET另外记录，不计费。6个SDK反馈完整回放、4事务、17trace/seal均一致。目标阶段7usage input173093/output1404/peak32507；最终9usage input245003/output1855/peak36710。9context峰值108320字节，9prefix峰值105285字节；既有计算前缀保持的请求对已核对。8研究记录=3compute/4experiment/1acceptedNOTES，0omitted/unknown。

真实installed Runtime.execute+worker的首JSON新增资源日期/评分字段、错误保留、stdout隔离与纯计算锚点不刷新均provider-free验证。实际Pi工具正文没有持久保存，故实际字段收取及模型采用未直接观测；不得由小关成功推断策略收益。进程/auth/env已清理，用户console52024:56659保留。

独立审计READY：101manifest项bytes/SHA及coverage一致，manifest SHA aefaf300d353d77860b6647401049d92dc438fa78b45a4bebf3c72f78b557ccc。私有证据 `.asterion-private/p7-task30-witness-20261009/trial/`。Task30部署闭环已完成；封存版本仍有条件分字段，后续用户要求改为直接115/100剩余动作空间（Task31），不能把本次见证标为后续源码验证。

## 尚未验证

是否改善BP35 L1探索成本、策略转换、总耗时或得分，需要另一次用户授权的实测。本轮没有启动新BP35；不会由单元测试、提示内容或r11l小验证推断这些能力。通用快照与指导可以被其它领域适配，跨领域效果仍未评估。

[设计](../superpowers/specs/2026-10-09-prime-resource-aware-research-design.md)、[计划](../superpowers/plans/2026-10-09-prime-resource-aware-research.md)、[上一轮BP35结果](2026-10-09-p7-bp35-task29-evaluation.md)。

## Task31：直接评分动作空间修订

用户要求去掉条件分，直接给出115满分与baseline100的剩余步数。数据层删除条件分，新增100阈值/剩余/超额及115超额；研究层同步host小投影和prompt，Prime通用层未改。阈值相等时remaining/exceeded均0，超出时exceeded正数，未知null。实际未完成贡献、累计计费和执行硬边界保持。

独立changed-code APPROVE；评分17与runtime31各RED→GREEN；root联合48tests PASS15.933秒，TS79PASS/6external skips，lint/docs/diff通过。Astra另跑最大20step/60KiB合法反馈回归PASS，新增字段不裁旧证据。新源码冻结ba51c62e，完整promotion25PASS/provider0。独立fresh packaged见证结果见下，未继承Task30部署证据。

### Task31 新版本打包见证

新wheel 2d4126285354026be93d17f554f0d7c6f9bbc776ad697eb1cf2988640d016ba3；生产570/安装588/归档1685与ba51c62e一致，扩展a79956和三工具不变。真实installed Runtime/worker首JSON六直接评分字段验证（paid0、恰好、超额、未知null），旧条件分不存在，错误/spoof/时间同capture测试通过；provider-free。

新r11l L1（同Solmedium，独立900+180）：6计费动作、0计费RESET、Q115；2setupRESET另计，目标94.471582秒，收口含清理129.638564825秒。8个SDK反馈完整回放，6事务、22trace/seal一致。目标阶段9usage input250278/output1852/peak36803；最终12usage input372244/output2517/peak41943；12context峰值135169/累计1058923字节；12prefix峰值129754字节，0identityflags；11研究记录=4compute/6experiment/1acceptedNOTES，0omitted/unknown。

与Task30小关4动作/67.896532秒相比，多2动作/+26.575050秒；此为部署检查，不构成同种子独立重复策略实验，不能归因字段变化或推断BP35退步/改进。实际Pi资源正文仍未持久留存，收取/模型采用unknown；真实worker返回证据与策略效果分列。本次进程/auth/env清理，用户console保留。私有 `.asterion-private/p7-task31-witness-20261009/trial/`；独立最终部署审计READY：115manifest项bytes/SHA/fullcoverage通过，SHA6c6dbf7e6aa0c78d81767d2157178d6d9de4e3a8179719f7a07e6080ff8c4b0a。

## Task33：实时策略与行动理由

用户明确要求开局先报告策略，策略实质改变后再报告一次；每次动作或动作组说明原因。P7主prompt复用已有NOTES与plan.goal：首paid前可先免费观察/计算；总代价未知则明确未知，无需为了估数追加研究。改变后下一批行动前更新，未变不机械重报；goal用1–2短句说明行动意图与当前观察依据/预期效果。简明中文采用STE式短句、常用词、主动表达、明确对象和单一判断原则，未声称80%量化认证。

仅prompt与两个focused接口测试变更，增加935UTF8字节；无新tool/schema/hostgate，Prime通用层与P7数据层未改。已有NOTES与提出/执行计划事件、submitted_plan研究链保存外显选择理由，不要求内部思考展开。协议goal仍可省略，研究提示要求填写；直接行动无NOTES的宿主边界测试仍通过。

独立changed-code APPROVE/接口5PASS；root35相关Python PASS1.678秒，lint/docs/diff通过。**已实现提示合同，未新实跑或新版本打包见证；模型遵从、理由质量和效率改善尚未验证。** Task32封存中无这些新要求，不能把后加说明当成当时依据。

## Task35/36：从后期资源取舍到开局选择

Task35生产b2d1a453已部署冷测，模型在start10/start15公开引用准确评分余量选择推进/保100，但L120paidQ110.25未达115，授权早停；source与304manifest独立READY，详情在Task32–35中止分析。没有证明总体策略改善。

Task36只修改P7主prompt初报段和已有focused接口测试。开局依据初始画面、目标和115/100余量先选择推进路线/探索投入，不默认先probe；probe事先说明动作价值及哪些结果改变路线。已有信息足则推进，未知不能替代判断，必要免费分析可做。无新工具/数据/Primegeneric逻辑/hostgate，报告仍简短NOTES与goal。+433UTF8B，主prompt13484B。独立changed-code APPROVE/23相关PythonPASS0.970秒/Ruff/lint/docs/diff。源合同已实现，实际开局遵从及分数待新冷测；不能回填为Task35依据。

Task36 frozen94dabe66独立打包/安装身份检查通过并完成一轮freshBP35：开局判断报告实际存在，但L124paid/Q76.5625、247.167053秒，授权早停，L2未行动。26SDK完整回放/24tx/47trace/ownedcleanup/final280manifest独立READY。初始选择有条件依据，不等于合理路线；批量清块未证目标关联。一次print整组animation导致65536B截断并显著增下一输入，研究输出组织需另行设计。实际评估详见Task32–36中止分析；不宣称新策略优于baseline。

## Task38 changed-code review

Independent review APPROVE: only `build_autonomous_prompt()` and focused prompt-delivery test. Adds482UTF8bytes (13484→13966), fullrevisableACTION1–7 interfacepriors; ACTION7 normalundo vsRESETrestart, GAME_OVERonlyRESET, feedback/currentavailability and existing paidcost boundaries retained. NoPrimegeneric/data/tool/schema/route/gate changes. Worker observed15missingcontent RED before implementation; root29focusedPythonPASS1.561s (`tests.test_prime_p7_autonomous_interface`, `tests.test_prime_p7_autonomous_solver`, `tests.test_prime_p7_score_planning`). Sourcecontract approved, packagedactualdelivery and BP35quality pending.

Task38 packageddeliveryverified: TS79PASS/6externalskips→focusedPython29PASS→fullpromotion25PASS/provider0 in requiredorder. Source8e2e8a29/wheel3856d706/source570/install588/actualprompt13966B/resourcea799/exact3tools/archive1686/launch21 independentlypreflightREADY; coldBP35target6 naturalcompletion1482.657593s/215paid/0RESET, with217fullSDKreplay andcleanup. Actualinterfaceadoptionobserved, stablecausalqualitybenefitunproven. Final1908manifest3cebc44d independentlyREADY; thispromptfixdoesnotimplementNOTES-primarycontextprojection.

## Task39：正常 NOTES 主认知源码评审

Prime 通用层以真实会话完整工具组建立 NOTES epoch，保留当前约束、近期反馈、重要错误及未知执行结果；旧明细按引用读取。P7 研究层提供正常 NOTES 与必要当前事实，数据层保留完整反馈。无需另加模型 checkpoint。独立设计、Python 与 TypeScript changed-code review 均 APPROVE。

源码验证：`npm --prefix packages/typescript/asterion-prime-extension test` 88 PASS / 6 external skips；installed Pi provider-free probe 验证正常 NOTES、archive、完整工具组、压缩与重载；相关 Python 48 PASS。`sync-resource` 构建通过，打包扩展 SHA256 `13bfee2e2990b7556950ea9a440f610263ab3f03f82a0ffe1f7f1ea54329272b`。未做本版本 promotion、付费打包见证或 BP35，不能据此宣称解题改善。

专用代码压缩另有底层接入缺口：历史 Prime fork 有 kernel 专用默认提示；Task38 实际 operator-owned Pi bundle 自动路径仍用原生提示，没有接入自有摘要材料。D-2026-09-16-01 接管实现仍 pending。默认开启、较高触发阈值与专用语义是独立要求；NOTES 主认知不能替代专用代码压缩。本轮 Task38 未观察到压缩触发，不能评估其效果。后续在 Prime 通用层修复，应用层不负责配置。

### Task39 NOTES-only 打包见证

用户暂缓全部 Pi 接入迁移，先完成 P7 NOTES 与过关。专用摘要初稿隔离，生产精确2930fbd8，轮包 a6ad55934e4104a67ad978fd8694197c2bb9e7b0c9094208ef4963966706e863，扩展13bfee2e2990b7556950ea9a440f610263ab3f03f82a0ffe1f7f1ea54329272b。TS88 PASS/6外部skip、相关Python48 PASS、完整promotion25 PASS/provider0按序完成；570源码、588安装文件及真实Pi离线探针独立核验。

实际 r11l L1：7paid/Q115，mint→SDKgoal128.140348秒，最终清理132.482697秒；0actor RESET/0undo，另2初始化RESET。goal12usage input395627/output3571/peak68422，final13usage input425412/output3599。4次正常NOTES更新均进入primary，退休完整组0→2→4→7；本轮3049B诊断未截断，11次覆盖request3–13。第三次NOTES后输入61073→21105tokens。实际动画整份print产生39247B，是此前峰值的大项；约23KB初始任务与snapshot重复也是尚存开销。NOTES562–714B。不能把日志字节叫tokens，不能从诊断计数重建未持久化的Pi原始会话全文。

Task30四步与本轮前三次付费点击相同。Task30第四次点击(39,25)完成；本轮第四次点已占端点(39,21)，只切换选择，再用三步调整两端完成，净增三步。Task31曾六步/94.471582秒，Task30四步/67.896532秒。本轮动作及时间回退真实存在，但没有证据归因于NOTES失效；也未证明整体解题收益。

9份完整SDK回放（仅guid排除）、7known事务、24trace/seal、12研究链及13metrics通过，owned进程/auth/env清理，console52024:56659保留。138项最终manifest SHA0f4e44188e4977da6edfdb29e67bcb23a53e7b654f1bc7daf6624f6530f8d201，独立READY。actualMake未启scalarobserver，rawcache未知；未自然调用archive专项回读，未触发nativecompaction，不验证专用压缩。本轮证明正常NOTES实际退休；随后授权BP35比较尚未启动。
