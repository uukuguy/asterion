# Asterion Pathlight 设计

**日期：** 2026-08-02  
**状态：** 已与用户逐节确认，待实现计划  
**名称：** Asterion Pathlight — 路径可观测、评估与受控优化

## 目标

Pathlight 是 Asterion 执行架构的伴生能力，而不是一个旁路日志工具。它让一次任务的
`assembly → runner → runtime → host service → evaluation` 数据流可追踪、可比较、可诊断，
并只在操作员明确授权后执行有限的优化实验。

它必须支持两种问题：

1. **纵向问题：** 一次任务从输入到最终评估经历了哪些 ContextFrame、LLM/API 调用和工具
   调用；每个节点是否成功，失败类别和安全证据是什么。
2. **横向问题：** 同一可比较范围的两组运行在哪些可观察指标不同；哪些事实已证实，哪些仅是
   待验证假设，下一步最小实验是什么。

首个实际消费者是 DCI 的 Bright、SciFact 和 Bamboogle 完整运行。通用框架不得导入 DCI
字段、论文语义或私有执行内容。

## 非目标

- 不把 prompt、答案、语料、工具参数/输出、凭据、私有路径或原始模型响应导出到通用 API、CLI
  或 Dashboard。
- 不从最终分数推断因果关系，不将不同任务类型或不同指标伪造成可比较的结果。
- 不自动改 prompt、模型、工具、能力包或预算；任何实验必须由操作员批准并受现有授权边界约束。
- Dashboard 不是首期交付；它只能消费已稳定的 Pathlight API。

## 架构定位

```text
CLI / Host → selected provider → assembly → resolved plan → runner → runtime → host services
                     │                 │            │         │          │
                     └──────────── Pathlight safety events ───────────────┘
                                             │
                                      immutable trace store
                                             │
                              API / CLI / comparison / diagnosis / proposal
                                             │
                                      Dashboard（最后实现）
```

Pathlight 在既有边界采集事件，不改变 runner 的顺序执行、授权、重试、持久化或 runtime 选择
责任。每个 trace 使用稳定 `trace_id`，并链接已有 `run_id`、任务、能力包、实现绑定、assembly、
runtime、host service、artifact 和 evaluation identity。

## 安全双层记录

### 默认安全层

不可变、可导出、可比较的结构化记录，包括：生命周期、嵌套节点关系、摘要和长度、标准化失败
分类、成本/token/时延、版本与策略摘要、指标、artifact digest 和私有证据引用。它是 API、CLI
和 Dashboard 唯一的默认数据源。

### 操作员私有层

原始 prompt、模型输入输出、工具输入输出、答案和语料仅留在 operator-owned evidence store。
Pathlight 默认仅保存不可逆摘要、长度、结构类型和授权引用；读取私有内容必须通过显式操作员
授权和审计。通用 framework 永不返回该内容。

## 规范数据模型

### Trace

一次端到端任务运行的不可变头记录：身份、开始/结束、终态、范围 digest、关联组件、完整性
digest 和根 Span。

### Span

有父子关系的一个已发生步骤。类型为 `plan`、`assembly`、`task`、`runtime`、`context-frame`、
`model-call`、`tool-call`、`host-service`、`evaluation` 或 `artifact`。每个 Span 记录：

- 计划状态、实际状态、开始/结束时间和尝试次数；
- 输入/输出结构摘要、长度、内容 digest 和私有证据引用；
- 成功、失败、取消或跳过状态；
- 标准化失败类别、责任边界和安全证据 digest；
- token、成本、时延、模型/API/工具版本和策略摘要。

失败类别至少覆盖：配置/参数、授权、网络、超时、速率限制、模型拒绝、工具协议、解析、评估、
取消和未知。未知必须保持未知；不能以推测替换事实。

### ContextFrame 数据流主线

每次 LLM 调用消费一个 ContextFrame 并产生后继 frame。frame 不是内容堆砌：它以有序 segment
引用建模系统指令、用户输入、工具结果和模型输出的来源、结构类型、摘要、长度、私有引用和
增量关系。通过 `consumed-by`、`produced-by`、`derived-from` 和 `caused-next` 链接，可以回答：

- 某次模型调用看到的上下文由哪些类别组成；
- 哪个工具结果进入了后续 ContextFrame；
- 某节点失败后，哪个后继节点接收了失败结果；
- 结果变化发生在哪一段可验证的数据流之后。

### Metric、Evaluation、Finding、Proposal

- `Metric` 记录单位、值、来源 Span、范围和版本化指标契约。
- `Evaluation` 绑定逐例/聚合得分、覆盖范围、指标契约和可选基线；范围或契约不一致时拒绝比较。
- `Finding` 只陈述可观察事实及缺失数据；不得陈述未证明的因果根因。
- `Proposal` 绑定 Finding digest、假设、最小变更摘要、成功/停止标准、预算和审批状态；默认不可
  执行，获批准后形成新的 trace。

## 对现有六项 DCI 全量运行的分析方法

现有 Bright 四项、SciFact 和 Bamboogle 的全量证据是结果基线，但早期运行未采集完整
ContextFrame。Pathlight 分两阶段处理，避免以大规模重跑掩盖缺口：

1. **证据回收。** 从安全元数据重建 trace identity、任务/能力包/运行时关联、结果、成本、错误、
   工具和评估摘要。可恢复记录明确标为 observed；无法恢复的上下文细节标为 missing。
2. **最小验证。** Bright 与 SciFact 都使用 IR 指标，作为主要的同指标对照；检查覆盖、候选/
   工具成功率、调用次数、时延、上下文增长、解析和度量拒绝。Bamboogle 的 accuracy 不与 nDCG
   直接比较，只作为 Agent/Judge/API 工作流健康度的对照。

诊断输出严格分为已证实事实、待验证假设和证据缺口。初始候选实验可以涉及语料/检索工具适配、
上下文保真或压缩、结果解析和去重、领域检索策略、超时/重试策略；它们不是预设根因。每项只先
在小样本上做受预算约束的 A/B 验证，并有预先声明的目标指标与停止条件。

## API、CLI 和 Dashboard

### API

- 创建/读取 trace，实时订阅安全事件；
- 按任务、能力包、实现绑定、assembly、runtime、host service、状态或 metric 查询；
- 读取 evaluation 与比较范围；
- 请求 comparison、diagnosis 和 proposal，拒绝范围或指标不兼容；
- 私有 evidence 只返回授权引用，永不返回原文。

### CLI

提供 `trace list/show/tail`、`metrics query`、`evaluate compare`、`diagnose` 和
`proposal create/review/execute`。所有 human-readable 输出与 JSON 输出都遵守安全层；执行
proposal 复用显式 authorization、成本上限和 cancellation，绝不以已有 trace 授权。

### Dashboard（最后实现）

Dashboard 只通过 API 工作，不直接读取 evidence store。主视图是 ContextFrame 数据流主线与
Span 时序；辅助视图为跨运行对比、评估差异、证据缺口和实验历史。它默认只展示安全层。

## 分期交付

1. **核心契约与采集。** schema、Trace/Span/ContextFrame、framework 边界事件、不可变存储、
   完整性/红线验证和现有 `workflow_evidence` 兼容迁移。
2. **查询与评估。** 本地查询 API、CLI、trace 回放、安全 evidence 回收和版本化 evaluation
   关联。
3. **诊断与受控优化。** 可比性规则、事实/假设/缺口报告、proposal 生命周期及最小实验授权。
4. **DCI 验收。** 对 Bright/SciFact/Bamboogle 生成回收报告；对证据缺口执行批准的小样本验证。
5. **Dashboard。** 基于稳定 API 实现 operator-local UI，随后才考虑受控 OpenTelemetry 摘要导出。

## 验收与测试

- 框架模块不导入 DCI；DCI adapter 可提供指标和领域映射。
- Trace 的父子关系、frame 链、序列、终态、metric 来源、digest 和引用完整性均 fail closed。
- 成功、失败、取消、重试、网络/API 错误和缺失私有 evidence 都有测试。
- sentinel secret、prompt、answer、tool payload 和私有路径绝不出现在默认 trace、CLI、API 或
  Dashboard payload。
- 运行时事件与 Pathlight trace 可一一关联，且 Pathlight 不改变原 Runner/runtime 结果。
- 不同 metric contract 或 coverage scope 的比较必须拒绝并说明缺失条件。
- proposal 未获授权时不触发调用；获授权的实验保留预算、停止条件、trace 与前后比较。
- DCI 验收报告必须把 Bright 低分与 SciFact/Bamboogle 较好结果分为可证实事实、假设和缺口，
  不得把分数差异写成因果结论。
