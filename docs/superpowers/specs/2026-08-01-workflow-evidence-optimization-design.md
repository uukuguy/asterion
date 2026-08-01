# Asterion 工作流证据、诊断与受控优化设计

**日期：** 2026-08-01  
**状态：** 已批准的设计，待实施计划  
**首个验收产品：** Asterion DCI Bright Biology、Earth Science、Economics、Robotics

## 问题与目标

Asterion 的智能体工作流不应只产生最终答案和散落日志。框架必须能对任意一次
执行（完成、失败或取消）回答：用了哪些输入和工具、产生了哪些中间产物、花费了多少
时间和成本、哪一项评估结果受哪些上游步骤影响、与另一配置的差别是否可比较，以及
下一项最小的验证实验是什么。

目标是提供领域无关的基础能力，而不是将 DCI 细节写进 framework：

1. 观察：把运行、步骤、工具调用、资源用量、artifact、失败和评估记录为完整且可验证的
   数据流证据。
2. 跟踪：由稳定标识和父子边形成不可变工作流图；任一结果可回溯到输入和实际执行步骤。
3. 评估：将质量、成本、时延、可靠性与领域指标挂到对应图节点，并明确其适用范围。
4. 诊断：区分已经证实的事实、可验证假设、不可比较项和缺失证据，绝不把相关性写成因果。
5. 优化：生成排序的受控实验计划；执行优化实验需要独立、有限、显式的 operator authority。

DCI 是第一个领域适配器：它提供论文参照、检索金标覆盖、QA/IR 指标和 benchmark
选择范围，但不能被 framework 层导入。

## 边界和不变量

- 新的通用模块位于 framework 层，不能依赖 `capabilities/dci/`、DCI 数据集或论文配置。
- `asterion.agent-runtime/v1` 保持闭合；既有事件不会因观测功能而放宽验证。新的
  `asterion.workflow-evidence/v1` 是独立闭合协议，并用现有 validated event stream 作为输入。
- 证据图只接受已经验证的运行事件、明确声明的输入快照和 artifact 元数据；缺边、重复
  身份、循环、序列错误或不匹配的 digest 均 fail closed。
- 公开报告仅包含结构化身份、计数、聚合指标、失败类别和内容 digest。prompt、答案、
  corpus、工具原文、凭据和私有路径只可位于操作员明确注入的私有 evidence service。
- 分析器纯读取不可变 evidence，不能修改运行结果、选择 runtime、重试、授权或启动服务。
- 优化建议是声明式的 experiment proposal；runner 不得自行执行。只有产品层将一个提案
  变成精确 scope、source lock、成本上限和 `--execute` 后才会发生外部调用。

## 分层架构

```text
validated runtime events + declared inputs + artifact metadata
                           │
                           ▼
                workflow evidence collector
                           │
                           ▼
             immutable workflow evidence graph
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       generic evaluators  domain adapters  comparative analyzer
              │            │            │
              └────────────┴──────┬─────┘
                                  ▼
                 diagnosis / ranked experiment proposals
                                  │
                                  ▼
                   explicit product authorization only
```

### 1. 证据图

每个 graph 都绑定一个 run identity 和精确输入范围。节点至少包括 `run`、`step`、
`input`、`tool_call`、`tool_result`、`artifact`、`usage`、`evaluation`、`failure` 与
`comparison`；边表达 consumed、produced、called、measured、evaluated 和 derived-from。
所有 ID、数组和边集规范排序且去重。内容使用 digest；只有私有库可按授权解析内容。

collector 将 runtime 的连续 event sequence 转换为步骤和工具节点，保留调用/结果的一一
对应关系；终态失败也产出完整的 failure 节点和当时已知上游证据，而不是只留下字符串错误。

### 2. 评估与可比性

通用 evaluator 输出质量、成功率、失败分类、时延、token、成本和资源指标，并声明每项
指标对应的 graph 节点和选择范围。领域适配器可增加如 nDCG、gold coverage 或 Judge
一致性，但必须提供指标契约、样本范围和来源摘要。

比较器先决定可比性，再计算差值。两个运行只有在任务、指标契约、数据选择、重复处理、
关键输入和配置差异均已陈述时，才可产生“可比较”的差值。否则输出 `not-comparable`，
并列出阻碍比较的边或字段。

### 3. 诊断

诊断输出四类记录：

- `observed`：由 evidence 直接证明，例如工具错误率、金标文档未被检索、评分范围完整。
- `hypothesis`：由多项 observed 支持但仍需对照验证，例如“检索查询策略导致低 nDCG”。
- `not-comparable`：已知配置、数据或指标无法对齐，不能归因。
- `missing-evidence`：需要补采的证据，例如论文运行的未公开提示词或检索配置。

每个 hypothesis 必须指出支持与反驳证据、置信等级、影响的结果节点、以及最小验证实验。

### 4. 受控优化

优化器不直接修改生产工作流。它只生成版本化 proposal：目标指标、基线 graph、唯一可变
因素、精确案例选择、接受/拒绝准则、预计成本、最大操作数和回滚说明。产品 operator
选择 proposal 后创建新的 exact scope 与 source lock，显式授予预算执行权。

一项改动仅在以下条件同时满足时可称为优化：

1. 对照与候选共享同一数据选择、评分契约、预算类别和其余固定配置；
2. 预注册的主指标改善达到阈值，且失败率、成本和时延未越过明确上限；
3. 原始 graph、比较结论和新 graph 都通过协议验证；
4. 结论明确只适用于已验证的 scope，不能外推为论文复现或所有模型的结论。

## Bright 首个闭环

Bright 四项已各自完成 100% 范围的 Asterion 运行，且与仓库登记的论文参照存在明显差距。
第一轮不是猜测 prompt 或模型问题，而是依次完成：

1. 导入四个 Asterion 全量 batch 的 source lock、effective config、事件/工具摘要、
   artifact digest、nDCG 与成本证据，构建四个 immutable graph。
2. 导入论文参照的已知 experiment scope 与未报告字段，生成逐项可比性报告。模型、工具
   或语料处理未对齐时必须标记不可比较。
3. 对每个任务输出归因矩阵：范围/指标、检索金标覆盖、工具可用性与错误、上下文/调用
   行为、成本/时延、已知配置差异。
4. 针对最高价值且可控的假设生成 paired experiment proposal，例如只改变检索查询策略、
   工具读写策略、上下文配置或评分实现；不能同时改变多项因素。
5. 由 operator 单独批准有限预算后运行对照；将结果写回比较图。只有达到预注册条件的
   候选才形成可采用的优化建议。

这套闭环能够发现 Asterion 实现问题、配置差异或模型能力差异分别占据何处；若论文所需
证据不存在，则结果会诚实地报告“无法判定”，而不是伪造根因。

## 验收标准

- 本地 fixture 运行可生成并验证一张无内容泄露的完整 evidence graph，覆盖完成、失败和
  取消三种终态。
- 篡改 event、digest、边、身份或比较范围均被拒绝。
- 同一输入 graph 的诊断输出字节确定；所有数组规范排序。
- DCI Bright 四项能产生一份中文归因报告，明确已证实项、假设、不可比较项与最小实验。
- 至少一个由该报告提出的 paired experiment 可通过正常的 source lock → plan → explicit
  authorization → execution → evidence → comparison 闭环执行；未授权 proposal 无法触发外部调用。
- `make test`、`make lint`、`make docs-check`、`make check` 和相关 promotion check 均通过。
