# NOTES 主导的研究工作上下文

状态：NOTES 核心源码已提交 2930fbd8，独立评审通过；通用 Prime 接入与默认专用压缩迁移由用户暂缓；当前进行 NOTES 核心打包和过关验证。用户授权实现、评审及实测；尚未启动本版本模型。Task38 保持封存。

## 问题与目标

Task38六关215paid/0RESET/1482.657593秒。goal NOTES1039B、final984B，final输入峰235052tokens；context907892B主要为toolresults580547B及assistant281105B。当前 `projectMemoryContext` 保留完整native交互，NOTES替换state snapshot，不形成研究历史归档边界。此前把已有NOTES视为主要工作认知实现不准确。

目标：由LLM把有用研究转化为可决策的NOTES，工作上下文主要包含任务、有效认知、当前现实与尚需直接观察的交互；完整档案供按需取证、复核和重放。笔记可丰富而不堆日志，不以最短或固定结构为目标；不能用窗口删减冒充认知归纳。

## NOTES 的职责

由LLM自由组织目标、当前局面、推进和返回路线的依赖条件、机制/坐标/连续后果及适用范围、可复用程序与证据引用、重要错误和反例、未解决问题与下一步打算。领域研究提示说明用途，不强制逐动作笔记、固定策略分类或全模型。

重要错误与反例必须在仍影响决策时承接：被否定的判断、真实证据引用、修正认识及适用条件、仍未知的部分和对行动的影响。普通错误不机械累计；LLM判断重要性，不由host判断游戏意义。总结不是证实，不允许把未知结果改写为已知。

例如L2/L6撤销链的价值不是记录全部八次撤销，而是理解停靠块与往返通路的依赖、此前遗漏造成的成本及仍需验证条件。不得用该例编入BP35坐标或过关路线。

## 三层责任

| 层 | 责任 |
| --- | --- |
| Prime通用层 | 分支/完整交互游标、只读档案、模型可读引用、可信checkpoint回执、工作上下文投影、前缀观测、未知执行保护与恢复 |
| P7研究层 | 说明NOTES的有效认知职责，由LLM选择归纳范围、保留反例、维护程序/模型引用、规划与自主更新NOTES |
| P7数据层 | 当前真实状态、动作/动画/历史帧和局部读接口；不判定笔记完整性、不注入攻略 |

现有三工具保持：ipython、p7_workspace、p7_execute_plan。复用应用级工具注册/bridge能力；不在通用runtime注册P7工具，不新增第四工具。

## 私有来源合同

Python memory v3保持version/revision/content/commit四键，新版本明确普通notes基线语义；native TS执行边缘生成独立session/notes revision/toolCallId/group cursor绑定receipt，Python不编造Pi游标。notes接纳与退休成功分开，reader/cursor失败保留已接纳notes/原结果/fullhistory，明确retirement不可用。只有真实matchingtoolresult、完整siblings组闭合后应用receipt；执行时pre-resultcursor仅候选。

P7结果附私有context_interaction={version:"asterion.prime-context-interaction/v1",effect:"unknown"|"settled",feedback:"negative"|"ordinary"}，TS剥离模型正文并存可信details；P7 adapter只从unknown/blocked/uncertain以及真实reject/differences/mismatch结构化结果生成。generic不判游戏含义；普通tool的settled不能解除别的unknown receipt，后者持续保留直至明确host权威证据结算对应effect。自动currentmemory只投必要facts/notes/预算/refs/kernel状态，完整r.current/workspace read证据接口不裁。

## 精确归档与回读先行

`r.history/transition/frame`覆盖动作，`r.cell_history/cell_read`覆盖程序和输出，`notes_history`覆盖笔记，不能恢复任意旧assistant消息、完整tool拒绝或用户修正。Pi `sessionManager`的当前branch/entry目录需通过窄只读适配提供actor可用的分页ref读取；原档存在但不可读不能算可恢复。

目录只暴露本次选定session/branch的opaque refs、类型、顺序及摘要元信息，正文按ref/page读取。仅返回原本对actor可见的记录；不得暴露凭据、host路径、providerheaders、其它session或engine源码。完整工具组包含其assistant调用与全部toolresult，不能以单条记录为可退休边界。无可读原文的必要group暂不退休，明确报告投影不可用而非静默遗漏。

## 正常 NOTES 直接建立工作认知基线

用户明确：正常NOTES都承担主要决策依据，缺信息再专项取明细。不增加可选模型checkpoint或额外认知交接流程。模型仍使用op notes提交有效认知；接受后host自动建立新的工作epoch与可信回执，绑定源/分支/笔记版本、摘要与精确工具组游标。现有memory v2 commit/anchor只是保存，不能静默重定义；新的版本化包络明确新投影语义。覆盖截在发出notes的assistant组之前最后一个完整组，notes同组的其它tool调用与随后结果不能退休。游戏observation sequence只作关联，不能作游标：同一动作序号间可能有大量计算、拒绝和认识修订。

host只验证本次分支、完整组顺序、原档可读、exact refs/版本、已结算状态、没有跨越未确认效果；不认证笔记语义完整、反例已解决或路线安全。未知执行receipt与实际暂停状态持续钉住，任何模型说明/notes/checkpoint不能退休它、改为known或重派动作。初版默认保留notes组之前最近两个完整工具组，以及本分支最近一组真实tool-error/预测失配/前置拒绝反馈（按结构化真实事件选择，去重，不靠文本关键词或游戏含义）。它们是即时纠偏缓冲；older重要反例由LLM写入NOTES并用ref取证，host不推断重要性或语义解决。unknown保护不受两组范围限制。原始组可按ref专项读取，不能仅依赖错误摘要。

投影由可信任务说明、checkpoint认知基线、带as-of引用的状态基线、checkpoint后的完整交互组及受保护记录构成。模型仍看到当前最新真实状态；checkpoint是认识承接而非预算刷新、执行授权或成功证明。当前NOTES更新被接纳后也必须可见，不能为了cache继续投影旧版本为最新。用户有效任务约束必须保留，不能把用户原文授权交给笔记重写。内核generation及程序可用性仍是实际状态，引用回读不自动执行源码，恢复只用已有显式源码/JSONcheckpoint。

正常NOTES建立基线时允许一次真实前缀重建；epoch内完整追加工具组，已有反馈保持历史含义，避免每动作改写长前缀。现有board结果缩写和snapshot迁移同属变更范围，不能只加cut就称动作缓存稳定。Pi原生compaction/reload/branch切换须依据entry lineage/firstKept边界重建，不能解析summary文字猜覆盖范围或重新引入已退休历史；无法证明范围则保留原summary并明确目标未达，不能声称NOTES主认知已完成。必要近期证据范围与上下文增长会计应可观测；不按96/48KiB或任意token窗口盲裁。模型自行选择有新认识时更新NOTES，不增加每步强制总结或额外交接开关。

## 代码接入与实施顺序

1. 通用TS reader/controller绑定Pi只读session entries；Python/TS统一新的checkpoint envelope校验，不静默扩展现有v2含义。新v3内部包络及fixture明确来源与游标；公开四大框架协议不借本改动扩展。
2. 在现有P7应用workspace注册/bridge增加可查询目录、按ref回读、正常notes接纳时自动生成基线的可信内部回执；元数据、allowlist、TS源码、打包mjs、Python dispatch和测试同步。原档不可读时拒绝退休，保留完整工作历史。
3. 修改通用 `MemoryContextController/projectMemoryContext` 及相关tool-state投影：只使用可信receipt选择工作epoch，保持完整toolpairs/未知保护、最新NOTES与真实状态。P7 runtime提供notes/data绑定，不能把游戏策略写进genericcontroller。
4. 修改P7主提示：NOTES承担有效认知与重要反例，历史按需读取，普通NOTES建立基线及回读方式说明清楚，不以更多提示替代投影。

## Prime 专用代码压缩不可省略

用户明确持久IPython的代码语义压缩是必需，区别于普通文本摘要。normalNOTES需要承接仍有用的变量/函数名字、用途/调用约定、状态/已知模型适用范围、source/data refs与kernel generation；不要因为旧cells退休重新定义仍存活对象。保留名字不表示对象真实存活，实际generation及回读/显式checkpoint恢复仍是依据。

调查已证：Pi 自动压缩默认 enabled=true、reserve16384、keepRecent20000。Task38 模型 contextWindow272000，阈值255616，完整usage峰235122，未观察到自动压缩触发。compact_events=True 只是 RPC 事件投影。

旧 Prime fork 确实改写了原生 buildSummarizationPrompt，追加持久内核说明，未替换整个 Pi 压缩流程。历史依赖 loader 曾引入该实现；fd962a66 删除该通道。当前源码、loader、构建脚本及 Task38 实际 rpc-entry/bundle 审计均未找到仍生效的专用摘要改写。现有自有材料进入报价/见证，不等于实际摘要请求；P1 手动 customInstructions 是独立已实现路径。D-2026-09-16-01 的扩展接管仍未完成。

用户明确 P7 的全部底层 Pi 依赖应转为基于 Prime，不能只修压缩。通用 Prime 拥有启动命令、模型配置落实、profile/entry 与扩展加载、RPC 会话和原生事件处理、默认专用摘要与用量/取消边界。P7 注入游戏接口、工具、完成判定、研究续跑内容和领域证据转换，不操作 Pi 内部对象。operator-owned 环境仍由获授权的应用集成读取，通用框架不直接读 .env。

以下完整迁移设计暂缓实施，不混入当前 NOTES 实测版本。后续沿合法 session_before_compact 接管摘要生成，保留 Pi 触发阈值、preparation 切分和持久化；实际摘要使用 Prime 自有代码语义材料和选定 provider/model/auth。每次实际摘要调用须遵守现有 callback/deadline 及已设置的 token/cost 预算并记录真实 usage；失败/取消不得偷偷回落再调用一遍原生摘要。无新 runner/provider，未设置的预算不虚构为必须新增价格系统。P1 旧手动见证保持显式兼容边界，不能双 hook。

NOTES 的日常主认知与高阈值专用压缩同时成立。可信摘要范围只能覆盖真实可压缩历史；未知效果、用户约束及必要近期错误原文继续保护。压缩后不能恢复全部已覆盖 raw 历史使压缩失效，不能凭 summary 文本猜游标。实际 provider-free hook、entry 持久化及重载需验证；真实运行未触发压缩则不声称模型摘要质量验证。

## 历史方案区别

曾经的NOTES即时cut已校验可信receipt/完整siblings，不能将其描述为未经配对检查的盲切。之后96/48KiB滚动删减也已撤回。本次实质补足可用的全文检索、程序连续性、近期反例保护、unknown持续钉住、用户约束及compaction/branch合同，使普通NOTES更新真正在这些保障下承接认知。原档不删，工作视图可逆回读；不是恢复旧字节窗口。

## 验证与结论边界

重点评审实现而非极端测试：错误/跨分支游标、半工具组、不可读证据、unknown effect均不得退休；notes接受不认证语义；用户修正保留；程序/失败/反例经引用回读一致。合成研究跨度验证checkpoint前后输入及恢复、epoch内追加性、原生compaction/reload不复活退休历史、旧frame/程序/拒绝全文可查，不能用测试只匹配文案。

按TS→相关Python→promotion顺序验证，新的真实打包小关见证确认同wheel/resources/tools，记录是否实际发生checkpoint与回读；局部源码或fixture不算NOTE主认知能力完成。正式BP35对照需用户授权，跟踪各关动作/得分/RESET/时间、当时认知承接、peak/cumulative/raw/cachetokens。如果实跑普通NOTES接受后历史仍未收拢，不能宣称主认知目标实现；稳定效率改进也需实测。

NOTES 核心设计与源码独立 APPROVE，TS88 PASS/6外部跳过、相关Python48 PASS、实际安装Pi无provider探针通过。通用接入补齐仍需设计/源码评审及打包闭环，未进行本版本 BP35；不能宣称解题能力或效率改善。
