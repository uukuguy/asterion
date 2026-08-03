# DCI 差分诊断

本报告由六项已完成 historical evidence 的 provider-free Pathlight 恢复与诊断生成。它只包含数值、摘要关系和预先固定的中文说明；不包含 operator 路径、案例标识、提示、答案、payload 或 provider/model/config 值。

## 前瞻采集闭环（单例核验）

获批的一条 Bright Biology 前瞻核验已经在前台完成：1/1 成功、0 次 Judge、墙钟
59.68 秒、Agent 成本 $0.084855，使用 62,521 个输入 token 和 1,973 个输出 token；
18 次工具调用全部成功，其中 grep 13 次、read 5 次。本例 nDCG@10 为
0.339160，但单例结果既不是该实例总分，也不能用于和论文全量结果比较。

这次运行同时暴露并修复了五个执行/观察问题：worktree 中相对 Pi 路径锚定错误、已过期
OAuth 的正常刷新链路、Node 原生 fetch 未使用已配置代理、`willRetry: null` 被误判为重试，
以及当前 Pi 版本不发送 `provider_request_context`。前三项曾分别产生 0 case、0 token 或
`fetch failed`，没有额外模型费用；后两项使成功运行当时写出的原生 bundle 只能诚实降级。
相关修复为 `ecb0395`、`780921e` 和 `f80bcf5`。

成功运行的原生不可变 bundle 摘要为
`69b9d21af9c2960aeb5e5809af46199e3b1f8784a76138e51f404e693a24f5c7`，trace 摘要为
`6d25ce045feb192b8fa47be0737c47a4a08cf14a85e18b238978711f1a031b8e`。它保持原样，
没有因修复而覆盖。修复后从同一次运行的 486 条原始事件和 298 条标准事件离线重投影了一个
独立 companion；bundle 摘要为
`57cddb940e866b5633df438dcf017eb874bece14b9d4d9b9ce83a0ba4355e910`，trace 摘要为
`61749c6888e623af0a0ac4fd533076ec835c3a7cbe8363ebc41b49c8948057be`。它验证出一条
30 节点主线：6 个 ContextFrame、6 次完成的模型调用、18 次完成的工具调用。companion 的
时间戳只是严格递增的离线序号，不是执行耗时证据；真实耗时仍来自原生运行账本。

这条旧运行发生在精确 provider request 观察器实现之前，因此它的 6 个 ContextFrame 与
6 次模型调用仍明确保留 `context-segment` / `model-request` 缺口。Pathlight 能跟踪可见消息
和工具结果的纵向关系，但不会把它冒充包含 system/hidden 内容的完整最终调用输入。后续实现
不会追写或覆盖这条历史事实。

同一 companion 已通过 `pathlight trace list/flow` 和前台 Dashboard 核验。Dashboard 快照摘要为
`431ed5f79a4231d693f2971b01f779907eeb7dba7f566c10286d9a3709c83e8d`，显示 1 条完成
trace、6/6/18 节点和 1 类显式证据缺口；服务停止时网络操作计数为 0。

## 精确请求采集实现边界（provider-free）

当前实现已经在 Pi 的 `before_provider_request` 支持边界通过双通道采集每次精确请求：原始
JSON 只写入 host 创建、权限 0600 的私有 descriptor；公共 observation 只携带请求摘要、结构
摘要、字节/字段/叶子/文本字符计数、分段摘要和私有记录引用摘要。Python 会独立重算并交叉
验证两条通道，只有完整一致的连续请求序列才进入通用 Pathlight 主线；失败时保持原有结果并
显式降级，不改变重试、评分或执行授权。

本轮没有运行 Agent、Judge、模型、provider 或网络。provider-free 测试夹具把原始 payload、
key/value、provider/model/config 身份、实际 FD 和私有路径只保留在测试 setup 中；CLI
`trace show/tail/flow`、Dashboard snapshot/API/本地 assets 和 Opik 离线 envelope 只显示已验证的
请求摘要、结构摘要、计数与私有引用摘要。`trace list` 继续是聚合目录，只报告可定位的 trace
摘要和缺口计数，不展开逐请求结构。所有公共序列化字节都验证不含上述私有 sentinel 或原文。

精确 request body 已验证后，公共主线不再标记 `model-request` 缺口；但 Pi hook 目前没有提供
可与 Asterion 单调时钟交叉验证的精确调用边界时间，所以仍诚实保留闭合枚举值
`model-request-boundary`。这不是自由文本错误原因，也不能被解释为已观测到完整单调边界。

这些结果只证明实现与 provider-free 公共边界。上面的旧单例原生 bundle 仍不可变，离线
companion 没有被提升为 native evidence，旧单例 nDCG@10 仍为 0.339160，任何正式实例分数也
没有变化。本轮没有产生新的真实运行。下一条 Bright Biology 单例若要验证原生精确请求采集，
必须使用新的 source lock 与 evidence root，并获得一次单独、明确的执行授权；现有计划、配置、
缓存和历史批准都不授予这次调用权限。

## Coverage 实验状态（已完成）

获批的 v8 有限实验已以前台串行方式完成：五个数据集各 10/10，共 50 次 Agent、
0 次 Judge、0 次失败，实际成本 2,950,832 微美元（$2.950832）。执行绑定摘要为
`0ca6151fbef02c009729fffba4a588de298a596a342788a54644a34cfe84c3fd`，计划摘要为
`143350e02c518f073c26e32074ce73636c21d859522cd4818b21a904f06faf98`；50 条轨迹生成的
coverage experiment 摘要为
`8deb7710947e56672e7e13eeb0268b7bf0eaeea222617012f4b46fcea85f23de`。

| 数据集 | v8 nDCG@10（10 条） | 实际成本 | gold coverage any/mean/all 中位数 | 浮现 gold / 工具观测 |
|---|---:|---:|---:|---:|
| Bright Biology | 0.581166 | $0.540605 | 1.000000 / 0.758772 / 0.000000 | 39 / 136 |
| Bright Earth Science | 0.258671 | $0.538526 | 1.000000 / 0.833333 / 0.500000 | 14 / 133 |
| Bright Economics | 0.140249 | $0.632802 | 1.000000 / 0.214285 / 0.000000 | 12 / 129 |
| Bright Robotics | 0.473500 | $0.727880 | 1.000000 / 1.000000 / 1.000000 | 23 / 219 |
| BEIR SciFact | 0.787501 | $0.511019 | 1.000000 / 1.000000 / 1.000000 | 13 / 145 |

这些 10 条结果用于定位工作流环节，不替代 103/116/103/101/300 条全量分数，也不能与
论文全量分数直接作统计结论。它们足以排除“Bright 四项都因为完全没有找到 gold 文档”这一
单一解释：Economics 的 mean coverage 只有 0.214285，检索覆盖不足是强候选原因；
Earth Science 和 Robotics 已有较高或完整覆盖却仍低分，差距还发生在检索之后的排序、证据
选择或最终输出阶段；SciFact 的完整覆盖与接近论文的分数构成同配置参照。Biology 处于两者
之间。上述只是机制定位，不是因果证明。

真实 Pi 轨迹最初被错误记为零覆盖，原因是工具结果采用结构化 `content/details` 形态，长行还会
携带明确的截断标志；旧解析器只接受裸字符串和逐字完整行。提交 `972bc13` 已以严格形态校验、
错误结果排除、空白规范化和显式长前缀绑定修复，并对 50/50 真实轨迹重新验证。coverage 摘要随后
被规范成 5 个真实 Pathlight EvaluationRecord，避免把 evidence 摘要冒充评价身份；最终诊断
产物摘要为 `8241222ea6411422e27efd0f6e6d469c8bc1301c77bf017f1fa6a28f9fd7d8c8`。

当前 50 条的 retained coverage 均不可用：现有 evidence 能证明工具输出中出现过 gold，
但没有保存可验证的最后一次 LLM 调用上下文帧，因此还不能证明这些证据最终进入模型上下文。
这是 Pathlight 基础采集层的明确缺口，也是下一步先补调用边界与上下文帧、再做查询分解实验的
原因。coverage 闭包现已把检索查询分解门槛从 `blocked-by-coverage` 打开为
`ready-for-authorization`；它没有自动授权后续模型实验。

## Opik 离线互操作状态

最新诊断、六个 experiment、六项历史 evaluation bundle 和新增的五条 coverage evaluation 已
通过 Pathlight–Opik 1.0.0 白名单映射，生成 1721 个幂等 envelope；批次摘要为
`3ba1d6d212b083375f5764c246c8cae6189910f64a3fb2cca6379d3be98a32ce`，文件权限 0600，
`network_operation_count=0`。批次包含 dataset、experiment、case trial、evaluation 和 proposal
关系，不包含 prompt、答案、语料、工具/模型 payload、provider 配置、凭据、私有路径或 Opik UUID。

该批次只是 operator-owned adapter 的离线输入，不代表已经发送到 Opik。Opik 的 401、限流、
网络或服务错误只能写成 `ExportReceipt`，不得改变任何 benchmark、trace 或 evaluation 结果；
Opik 导回的优化建议只能形成未授权的 `ProposalCandidate`。

## 已证实事实

### SciFact

- 分数：nDCG@10 752431 微单位；样本 300/300；失败 0；语料文件 5183。
- 论文参照：757000 微单位；差值 -4569 微单位；状态：仅参考、不可作完全可比结论。
- 零分率：190000 微单位；覆盖可用 0/300；解析状态：不可用。
- 中位数：tokens 86990；工具调用 15；墙钟 36979869500 ns；工具 2882887500 ns；read 调用 1；grep 调用 12；read 113409500 ns；grep 2516172000 ns；问题词 12。
- 工具错误：26；时间占比：工具/墙钟 83480 微单位、read/工具 79919 微单位、grep/工具 920080 微单位。

### Bright 生物学

- 分数：nDCG@10 445584 微单位；样本 103/103；失败 0；语料文件 57146。
- 论文参照：771000 微单位；差值 -325416 微单位；状态：仅参考、不可作完全可比结论。
- 零分率：271844 微单位；覆盖可用 0/103；解析状态：不可用。
- 中位数：tokens 74313；工具调用 9；墙钟 43422733000 ns；工具 18227092000 ns；read 调用 0；grep 调用 8；read 0 ns；grep 17999240000 ns；问题词 76。
- 工具错误：44；时间占比：工具/墙钟 425636 微单位、read/工具 24052 微单位、grep/工具 975947 微单位。

### Bright 地球科学

- 分数：nDCG@10 438227 微单位；样本 116/116；失败 0；语料文件 121250。
- 论文参照：690000 微单位；差值 -251773 微单位；状态：仅参考、不可作完全可比结论。
- 零分率：318965 微单位；覆盖可用 0/116；解析状态：不可用。
- 中位数：tokens 77545；工具调用 10；墙钟 56049190000 ns；工具 45909349500 ns；read 调用 0；grep 调用 8；read 0 ns；grep 45909349500 ns；问题词 68。
- 工具错误：30；时间占比：工具/墙钟 911002 微单位、read/工具 8325 微单位、grep/工具 991674 微单位。

### Bright 经济学

- 分数：nDCG@10 309687 微单位；样本 103/103；失败 0；语料文件 50221。
- 论文参照：468000 微单位；差值 -158313 微单位；状态：仅参考、不可作完全可比结论。
- 零分率：466019 微单位；覆盖可用 0/103；解析状态：不可用。
- 中位数：tokens 85194；工具调用 14；墙钟 50926483000 ns；工具 16167417000 ns；read 调用 4；grep 调用 8；read 303792000 ns；grep 15352295000 ns；问题词 111。
- 工具错误：61；时间占比：工具/墙钟 344945 微单位、read/工具 64567 微单位、grep/工具 935432 微单位。

### Bright 机器人学

- 分数：nDCG@10 336664 微单位；样本 101/101；失败 0；语料文件 61956。
- 论文参照：568000 微单位；差值 -231336 微单位；状态：仅参考、不可作完全可比结论。
- 零分率：465346 微单位；覆盖可用 0/101；解析状态：不可用。
- 中位数：tokens 134189；工具调用 18；墙钟 65471602000 ns；工具 32506458000 ns；read 调用 6；grep 调用 11；read 624686000 ns；grep 31272710000 ns；问题词 121。
- 工具错误：54；时间占比：工具/墙钟 576546 微单位、read/工具 37736 微单位、grep/工具 962263 微单位。

### Bamboogle

- 分数：准确率 816000 微单位；样本 125/125；失败 0；语料文件 1。
- 论文参照：800000 微单位；差值 16000 微单位；状态：仅参考、不可作完全可比结论。
- 零分率：184000 微单位；覆盖可用 0/125；解析状态：不可用。
- 中位数：tokens 36162；工具调用 6；墙钟 31501144000 ns；工具 15096800000 ns；read 调用 1；grep 调用 5；read 7047000 ns；grep 15089737000 ns；问题词 11。
- 工具错误：122；时间占比：工具/墙钟 619885 微单位、read/工具 562 微单位、grep/工具 999437 微单位。

## 组件摘要关系

- SciFact 的运行时组件摘要关系：相对 Bright 生物学相同。
- SciFact 的模型组件摘要关系：相对 Bright 生物学相同。
- SciFact 的工具集组件摘要关系：相对 Bright 生物学相同。
- SciFact 的提示契约组件摘要关系：相对 Bright 生物学相同。
- SciFact 的上下文契约组件摘要关系：相对 Bright 生物学相同。
- SciFact 的度量契约组件摘要关系：相对 Bright 生物学相同。
- Bright 生物学的运行时组件摘要关系：相对 Bright 生物学相同。
- Bright 生物学的模型组件摘要关系：相对 Bright 生物学相同。
- Bright 生物学的工具集组件摘要关系：相对 Bright 生物学相同。
- Bright 生物学的提示契约组件摘要关系：相对 Bright 生物学相同。
- Bright 生物学的上下文契约组件摘要关系：相对 Bright 生物学相同。
- Bright 生物学的度量契约组件摘要关系：相对 Bright 生物学相同。
- Bright 地球科学的运行时组件摘要关系：相对 Bright 生物学相同。
- Bright 地球科学的模型组件摘要关系：相对 Bright 生物学相同。
- Bright 地球科学的工具集组件摘要关系：相对 Bright 生物学相同。
- Bright 地球科学的提示契约组件摘要关系：相对 Bright 生物学相同。
- Bright 地球科学的上下文契约组件摘要关系：相对 Bright 生物学相同。
- Bright 地球科学的度量契约组件摘要关系：相对 Bright 生物学相同。
- Bright 经济学的运行时组件摘要关系：相对 Bright 生物学相同。
- Bright 经济学的模型组件摘要关系：相对 Bright 生物学相同。
- Bright 经济学的工具集组件摘要关系：相对 Bright 生物学相同。
- Bright 经济学的提示契约组件摘要关系：相对 Bright 生物学相同。
- Bright 经济学的上下文契约组件摘要关系：相对 Bright 生物学相同。
- Bright 经济学的度量契约组件摘要关系：相对 Bright 生物学相同。
- Bright 机器人学的运行时组件摘要关系：相对 Bright 生物学相同。
- Bright 机器人学的模型组件摘要关系：相对 Bright 生物学相同。
- Bright 机器人学的工具集组件摘要关系：相对 Bright 生物学相同。
- Bright 机器人学的提示契约组件摘要关系：相对 Bright 生物学相同。
- Bright 机器人学的上下文契约组件摘要关系：相对 Bright 生物学相同。
- Bright 机器人学的度量契约组件摘要关系：相对 Bright 生物学相同。

上述关系只说明已恢复的摘要关系，不证明论文环境与当前运行完全可比。

## 待验证假设

- 大语料检索尺度噪声。
- 查询分解不足。
- 上下文保留不可见。
- 论文方法差异。

## 反证与不可比较项

- 论文数值仅作参考，当前变体不可视为完全可比；因此没有跨数据集汇总分数或分数导出指标。
- 缺少封存配置、封存分析、装配/包谱系、最终调用上下文与完整轨迹图谱，不能把差值归因于单一组件。

## 证据缺口

- 装配谱系
- 包谱系
- 封存分析摘要
- 封存配置摘要
- 轨迹图谱

## Pathlight Dashboard 核验

现有六项 DCI experiment、最新五条 coverage evaluation 和诊断闭包已通过同一个只读
`DashboardSnapshot` 验证并以前台服务启动；没有执行 Agent、Judge 或外部网络请求。快照摘要为
`eb21c3b98b8a2e1ed511ad26a447ba47ff746c65bbf156beef8dfe46c7157435`，包含：

- 6 个 experiment、848 个 case trial；
- 859 个唯一 evaluation；
- 21 个 finding、2 个未获执行权的 proposal；
- 0 条历史 trace/ContextFrame 主线、854 个显式证据缺口。

最后一行不是 Dashboard 失败：早期 848 条 DCI evidence 只恢复了结果、指标和实验谱系，没有
Pathlight trace graph；界面因此拒绝伪造 ContextFrame。后续新运行只要产生已验证的
`workflow-evidence.json`，同一 Dashboard 就会显示 ContextFrame、模型调用、工具调用、节点
成功/失败和结构化摘要。启动命令和 API 边界见
[Pathlight 设计](../superpowers/specs/2026-08-02-asterion-pathlight-design.md)。

## 最小受控实验

- 覆盖率观测：状态 completed；五项各 10/10，50 次 Agent、0 次 Judge、0 失败，实际成本 2950832 微美元。
- 最终调用上下文采集：provider-free 框架工作，先补齐每次 LLM/tool 调用前后的结构化边界、上下文帧与失败原因，不重跑模型。
- 检索查询分解：状态 proposed；coverage 前提已满足，但仍须在上下文采集闭环后单独授权；最多 80 次 Agent 操作，成本上限 8000000 微美元；最小平均 nDCG 增益 50000 微单位，成本或时间增长上限 250000 微单位；覆盖 4 个数据集、每项 10 例。
