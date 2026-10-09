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
