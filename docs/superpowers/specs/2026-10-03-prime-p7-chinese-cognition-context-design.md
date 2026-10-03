# P7 中文认知上下文设计

## 目标

让 P7 LLM 在每次决策前先看到一段短、稳定、中文的当前游戏认知，再使用结构化证据进行校验和行动。认知摘要必须随观察、动作反馈和认知更新自动刷新，不能依赖模型主动查询工具。

## 现状问题

- 初始上下文和工具返回以结构化 JSON 为主，模型需要从大量字段中自行寻找认知。
- `natural_language_context` 目前主要由英文假设拼接，不能满足中文协作和调试需求。
- `planning_background` 会在动作后刷新，但缺少一个独立、置前、短小的当前认知段落。

## 方案

增加一个应用层确定性渲染器，将当前语义报告和 cognition session 转换为有上限的中文摘要。摘要包含：

1. 当前游戏/关卡和认知状态；
2. 已确认的关键事实；
3. 尚未确认的问题；
4. 最近一次动作或分析带来的变化；
5. 下一步建议验证的事项。

摘要放入初始 prompt 和每个可决策响应的最前面，字段名固定为 `cognition_narrative_zh`；随后保留有限的结构化 JSON、当前棋盘和权威状态。JSON 仍是程序校验和持久化依据，中文摘要是 LLM 的首要阅读面。

提示词改为中文优先，并要求模型以中文提交假设、实验问题、分析解释和认知更新。已有英文历史假设继续保留，渲染器会用中文状态标签包裹；新产生的认知逐步采用中文。

## 数据流

```text
broker semantic report/session
        ↓
render_cognition_narrative_zh (bounded, deterministic)
        ↓
initial prompt / observe / act_checked / cognition / cognition_update
        ↓
LLM reads Chinese narrative first, then structured evidence
```

摘要不可授予执行权。实际动作仍只能经 `p7_act_checked`，当前观察和 broker 状态仍是权威来源。

## 边界与失败处理

- 摘要固定字节上限；超限时优先保留状态、确认事实和下一步，裁剪长文本和低优先级开放假设。
- 认知不可用时返回明确中文提示“当前认知刷新不可用，请先读取 p7_cognition”，不伪造已知事实。
- 摘要渲染失败不得阻断原有结构化工具响应；记录受限错误并保留 `execution_authority=none`。
- 不把凭据、原始模型 payload、完整私有路径或未经确认的路线写进摘要。

## 验证

- 单测验证初始 prompt、observe、act_checked、cognition 和 cognition_update 都包含中文摘要。
- 验证动作后摘要的认知序号、状态和确认/开放数量随最新报告变化。
- 验证摘要超限裁剪、认知不可用和结构化响应保持不变。
- 运行 P7 定向测试、lint、打包启动验证；真实运行只在有收据证据时报告过关。
