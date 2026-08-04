# Pathlight Bright 差分诊断与优化闭环设计

**日期：** 2026-08-04  
**状态：** 已批准；实现已通过 provider-free 验证；真实 A/B 为 `blocked-by-coverage-reverification` / `Not rerun`
**范围：** Pathlight 通用优化生命周期，以及 DCI Bright 查询分解首个产品适配器

## 目标

**当前证据更正：** 旧 v8 receipt 对应的原生 dataset identity 是 `dataset.local` 夹具，而不是
Bright/BEIR，因此旧 coverage、诊断和 gate 均为 `historical-invalid` /
`non-authoritative`。新的 5×10 coverage 计划已 provider-free 生成（计划摘要
`5c1a18927edb7f5519c738caa1e64ae1f2c927b1f1c9fa30678d89544cdb363e`，50 次 Agent、
0 次 Judge、$5、累计 2 次基础设施失败停止），但尚未授权。
必须先完成该 coverage 的真实 seal，再生成新的 diagnosis/gate，之后才可准备本设计的 4×10
A/B。此更正不改变下文已批准的 A/B 目标、80/0/$8 预算和停止规则。

Pathlight 已能把一次真实 DCI 运行投影为可验证的 ContextFrame、模型调用和工具调用主线，
也已恢复 Bright、SciFact 与 Bamboogle 的历史结果并形成安全诊断。然而，当前实现尚未把一个
待验证 Proposal 连成可追溯的基线/候选实验历史和最终 Decision，因此不能声称 Bright 的
差分诊断已经形成优化闭环。

本设计补齐以下主线：

```text
Finding → Proposal → operator authorization → ExperimentPlan
        → baseline/candidate CaseTrial → Evaluation
        → TrialHistory → Decision → Diagnosis / CLI / Dashboard / Opik mirror
```

首个真实适配器在 Bright Biology、Earth Science、Economics 和 Robotics 各取固定的前 10 条，
使用同题 baseline/candidate 配对实验验证“结构化检索查询分解”假设。一次闭环的成功是形成
证据完整的 `accepted`、`rejected` 或 `inconclusive` Decision，不要求人为保证候选提分。

## 非目标

- 不建设自动搜索 prompt、模型、工具或超参数的多轮 optimizer。
- 不允许 Pathlight、Dashboard、Opik、旧 trace、缓存或 Proposal 自行授予执行权。
- 不把一次 4×10 实验宣称为 Bright 全量分数、论文复现或跨配置因果证明。
- 不自动把 `accepted` 候选提升为正式 DCI 默认能力；正式替换是独立产品变更。
- 不把 prompt、问题、答案、语料、工具/模型 payload、凭据、provider 配置或私有路径放入
  Pathlight 默认安全层。

## 架构与依赖方向

通用实现位于 `src/asterion/pathlight/`，只消费已验证的 Pathlight experiment、evaluation 和
trace identity。它不知道 Bright、DCI、nDCG、prompt 或 corpus。DCI 产品适配器位于
`src/asterion/applications/dci_agent_lite/` 与
`src/asterion/capabilities/dci/implementation/pathlight/`，可以依赖通用 Pathlight，但反向依赖
被禁止。

```text
asterion-dci host
  → exact DCI proposal and source selection
  → existing benchmark host and authorization boundary
  → native workflow evidence + DCI evaluation
  → Pathlight OptimizationBundle
  → provider-free Pathlight CLI / Dashboard / Opik adapter
```

Python 继续拥有计划、授权协调、顺序执行和闭包构建。TypeScript 仅负责 Pi 观察扩展已有的请求
采集，不新增第二个优化器或执行器。Rust executor 的责任不变。

## 通用领域模型

### OptimizationTrial

`OptimizationTrial` 是一个已经发生的、公开安全的试验引用，字段包括：

- `experiment_plan_sha256`、`case_trial_sha256`、`dataset_item_sha256`；
- `variant_role`，严格为 `baseline` 或 `candidate`；
- `variant_sha256`、`trace_sha256`、`evaluation_sha256`；
- `status`，严格为 `completed`、`failed` 或 `cancelled`；
- 可信的 `agent_cost_microusd`、`input_tokens`、`output_tokens`、`elapsed_ns`；
- 固定枚举的失败类别或 `null`；
- 内容寻址的 `optimization_trial_sha256`。

trial 不保存输入或输出正文。`completed` 必须解析一个 trace 和一个同 scope、同 metric contract 的
evaluation；`failed`/`cancelled` 不得伪造得分。相同 dataset item 与 variant 在同一 plan 内只能
出现一次。

### TrialHistory

`TrialHistory` 绑定一个精确 ExperimentPlan，并包含：

- baseline/candidate variant identity；
- 数据集快照、case scope、metric contract 和 evaluator contract identity；
- 确定性配对规则摘要；
- baseline 与 candidate trial 的排序闭包；
- 每组完成/失败/取消数、成本、token 和耗时；
- 每个数据集及全 scope 的安全聚合值；
- 预先固定的成功、停止和预算摘要；
- `complete` 或 `incomplete` 证据状态；
- 内容寻址的 `trial_history_sha256`。

构建器必须逐 case 验证 baseline/candidate 配对，拒绝重复、范围漂移、variant 互换、metric 或
evaluator 不一致、未知 trace/evaluation、非规范排序和不可信成本。任何缺例使 history 保持
`incomplete`，不能通过缩小分母获得接受结论。已封闭 trace 中与 Decision 无关的局部缺口可以
保留，例如 compaction request-only 节点缺少 response/usage；只要该次 case 的终态、evaluation、
总成本和总耗时仍由权威账本闭合，它不会被误判成整个 trial 缺失。

### Decision

`Decision` 的结果严格为：

- `accepted`：完整配对证据满足质量、成本与时间全部门槛；
- `rejected`：完整配对证据存在，但至少一个预先固定门槛未满足；
- `inconclusive`：证据不完整、基础设施停止、观测闭包不足或比较不可用。

Decision 绑定 Proposal、Finding、ExperimentPlan、TrialHistory、阈值摘要、操作员审批摘要、
决定原因枚举和 `decision_sha256`。原因是固定枚举而不是自由文本。构建器从已验证 history 和
criteria 确定结果；调用者不能直接指定一个与证据矛盾的结果。

### OptimizationBundle

`asterion.pathlight-optimization/v1` bundle 包含规范排序的 trials、histories 和 decisions，并
引用其所需的 experiment/evaluation/diagnosis/trace bundle digest。所有引用必须在构建或读取时
闭合，整个 document 使用 canonical JSON 和 bundle SHA-256。文件名固定为
`pathlight-optimization.json`，operator-owned 输出为 0600，不允许 symlink、FIFO、路径替换或
部分发布。

通用 reader、writer 和 catalog 必须像现有 Pathlight bundle 一样对 hostile mapping、深层结构、
额外字段、bool-as-int、非有限数、TOCTOU 和冲突重写 fail closed。

## Bright 查询分解候选

现有 Bright IR prompt 已要求多关键词和分轮补查；候选不能只改写近义句。DCI 产品层新增一个
精确版本化的 query-plan prompt contract，其可观察行为要求模型在检索前形成以下结构：

1. 从问题识别实体、概念、关系和限定条件；
2. 为这些组成部分形成互补子查询；
3. 对每个子查询执行独立检索轮次；
4. 合并候选后去重、验证直接相关性并重新排序；
5. 继续使用现有最多 20 个相关文档输出协议。

真实 prompt body 仍属于 DCI 实现与 operator 私有执行输入。公共 Variant、plan、trace 和报告只
保存 prompt contract、query-plan contract 与 change 的摘要。

### 单变量约束

baseline 使用当前 `asterion-safe/pi` Bright IR 路径；candidate 只替换 query-plan/prompt contract。
下列身份在计划生成时必须相同并在执行前重新验证：

- dataset snapshot、40 个 selected case identity 与 corpus identity；
- assembly、capability package set、implementation 和 runtime；
- provider/model、authentication mode、toolset 和 context policy；
- nDCG@10 metric、解析、去重和聚合契约；
- 每 case turn、成本、deadline 和 native-attempt 上限。

若候选需要改变以上任一项，当前实验必须失败并产生新的 Proposal，而不是把漂移吸收到既有计划。

## 实验范围、门槛与决策规则

固定范围为四个 Bright 数据集各前 10 条，共 40 个 dataset item。每条运行一次 baseline 和一次
candidate，总计最多 80 次 Agent、0 次 Judge。每个数据集内部先执行完整 baseline batch，再执行
同 scope candidate batch；数据集顺序固定为 Biology、Earth Science、Economics、Robotics。

成功门槛沿用已发布 Proposal：

- 全 scope candidate 平均 nDCG@10 相对 baseline 至少增加 `50_000` 微单位；
- candidate 总成本相对 baseline 增幅不超过 `250_000` 微单位（25%）；
- candidate 总墙钟时间相对 baseline 增幅不超过 `250_000` 微单位（25%）。

三个门槛全部满足才是 `accepted`。80 个 trial 全部形成可信 trace/evaluation，但任一门槛未满足时
为 `rejected`。以下任一情况为 `inconclusive`：缺少 trial、执行被取消、达到基础设施停止阈值、
metric/scope 不可比较、原生 trace 缺失、可信成本或耗时缺失，或 trial/trace/evaluation 引用闭包
无效。`model-request-boundary` 等固定局部 evidence gap 必须展示，但本身不否定由 benchmark
账本闭合的 case score、总成本和总耗时。

数据集级结果始终单独报告，不允许用全 scope 平均掩盖某个数据集退化。全 scope Decision 是
Proposal 的预注册规则结果，不构成“查询分解对所有 Bright 子领域有效”的因果结论。

## 计划、授权、执行与恢复

### Prepare

`asterion-dci pathlight optimization prepare` 完全 provider-free。它读取已验证 diagnosis 与
`retrieval-query-decomposition` Proposal，生成：

- 精确数据和 corpus source lock；
- 40 条 selected case identity 与四个 dataset scope digest；
- baseline/candidate Variant 与 ExperimentPlan；
- execution-config digest、预算、停止规则和 output-root identity；
- `execution_authorized=false` 的 0600 plan。

prepare 必须证明 fresh coverage prerequisite 已通过原生 seal 且新 Proposal gate 为
`ready-for-authorization`。旧 v8 gate 必须 fail closed，不能进入 prepare。
旧 trace、`.env`、缓存、计划文件或先前授权均不能改变该字段。

### Authorization

执行要求单独的 0600 authorization document，精确绑定 plan、proposal、scope、source lock、
execution config、output root device/inode、operator approval digest，并固定：

- `execution_authorized=true`；
- `max_agent_operations=80`；
- `max_judge_operations=0`；
- `max_cost_microusd=8_000_000`；
- `max_infrastructure_failures=2`；
- 每 case 最多 1 个 native attempt，禁止协调器自动模型重试。

授权只对一个新建的 0700 output root 有效，不能跨 root、跨 plan、跨配置或跨恢复链复用。

### Execute and Resume

`execute` 在首次 provider 加载前预检全部四项数据、corpus、source lock、selected IDs、Variant、
运行时、provider readiness、预算和输出身份。预检失败不产生 Agent 操作。

执行在前台顺序进行，每个 dataset/variant batch 完成后写一个不可变 receipt。receipt 包含完成
trial 数、可信实际成本、失败类别、原生 workflow bundle/evaluation digest 和前一 receipt digest。
状态发布使用私有 staging 与原子 rename；冲突或不完整发布 fail closed。

`resume` 只读取同一 plan、authorization 和 receipt chain。已完成 trial 不重放；失败的模型业务
trial 作为终态保留；只有尚未开始的 trial 可以继续。网络、认证、限流、超时或 host 不可用计入
基础设施失败，累计达到 2 次后停止。无论停止原因如何，都可 provider-free finalize 为
`inconclusive`，但不能伪造缺失 trial。

### Finalize

`finalize` 不加载 provider。它重验 receipt、native workflow evidence、experiment、evaluation 和
diagnosis 闭包，生成 OptimizationBundle、更新后的 DiagnosisBundle 与中文报告。若已存在字节
相同输出则幂等返回；字节不同则拒绝覆盖。

## CLI、Dashboard 与 Opik

通用 `asterion pathlight` 增加只读命令：

```text
optimization history --optimization-file ... --history <sha256>
optimization decision --optimization-file ... --decision <sha256>
optimization trials --optimization-file ... --history <sha256> [--variant-role ...]
```

现有 `proposal` 命令继续只显示非执行 Proposal。通用 CLI 不提供 DCI provider 构造或隐式执行；
执行入口只存在于产品命令并复用既有授权边界。

DashboardSnapshot 接受可重复的 `--optimization-file`，闭合引用后显示：

- baseline/candidate 数据集级和全 scope 指标；
- 80 个 paired trial 的状态、成本、token、耗时与 trace flow 链接；
- 成功/停止阈值、证据缺口和最终 Decision；
- `accepted`、`rejected` 或 `inconclusive` 的固定原因。

Dashboard 仍只允许 loopback GET/HEAD，不增加授权、执行、写入、上传或外部网络接口。前端只消费
Dashboard API，不直接读取 evidence store。

Opik 离线映射为 OptimizationTrial、TrialHistory 和 Decision 增加白名单 envelope。它们只携带
opaque identity、状态、聚合指标、可信用量、阈值和关联摘要；Opik 仍是非权威外部镜像，导入的
建议不能改写本地 Decision 或执行候选。

## 错误与隐私语义

- benchmark 业务失败、Pathlight 观察失败和基础设施失败是三种不同状态，不互相覆盖。
- Pathlight 观察失败不能改变 benchmark 结果、评分、重试或成本账本，但会阻止 `accepted`。
- 未知原因保持 `unknown`；报告不能从低分、工具次数或 coverage 相关性推断单一根因。
- 公共异常、CLI、API 和文档不包含 provider 错误正文、prompt、答案、case ID、私有路径或配置值。
- sentinel 必须覆盖原始问题、prompt、模型请求/响应、工具参数/结果、corpus 文本、凭据、provider
  与 model identity、descriptor 和私有 root；这些值不能出现在公共 bundle、repr、CLI、API、
  Dashboard assets、Opik envelope 或中文报告。

## 验收与验证

### 通用 Pathlight

- OptimizationTrial、TrialHistory、Decision 和 OptimizationBundle 的构建、round-trip、摘要、
  引用闭包、不可变性和确定性测试。
- 拒绝重复/缺失 trial、scope/metric/evaluator/variant 漂移、伪造 Decision、未知 trace/evaluation、
  bool-as-int、非有限值、额外字段、非规范排序、symlink、FIFO、TOCTOU 和冲突发布。
- 三种 Decision 均有正向测试；不完整证据永远不能成为 `accepted` 或 `rejected`。
- CLI、Dashboard 和 Opik 的 provider-free、只读、下钻、引用闭包与 sentinel redaction 测试。

### DCI 产品适配器

- query-plan contract 与 baseline 的唯一差异是预注册 query-planning change；身份漂移在 provider
  加载前失败。
- prepare、authorization、execute、resume、status 和 finalize 覆盖成功、业务失败、两次基础设施
  失败、取消、部分 receipt、预算耗尽、root 替换和重复恢复。
- 80/0 操作边界、8,000,000 微美元总上限和一次 native attempt 由测试直接断言。
- 每个 completed trial 必须解析原生 Pathlight trace 与 nDCG evaluation；offline companion 不能
  冒充本次 native evidence。

### 仓库与真实验收

provider-free 实现完成后必须通过 focused `unittest`、Pyright、Ruff、`make check` 和
`make promotion-check`。真实实验必须另获上述精确授权，在前台运行，随后用 CLI 与前台 Dashboard
核验并停止服务。中文差分报告必须同时列出 baseline、candidate、样本总量、四项数据集结果、
成本/时间、证据缺口、Decision、论文参照的不可比较边界和下一步建议。

## 完成定义

以下条件全部成立时，才可声称本目标完成：

1. 通用 Pathlight 优化生命周期、CLI、Dashboard 和 Opik 安全映射已实现并通过全仓验证；
2. DCI 查询分解产品适配器与有限授权链已实现并通过 provider-free 验证；
3. 获批的 Bright 4×10 baseline/candidate 实验已完成或按预注册停止规则终止；
4. 原生 trace、Evaluation、TrialHistory、Decision 和更新后的 Diagnosis 引用闭合；
5. 中文报告诚实给出 `accepted`、`rejected` 或 `inconclusive`，并通过 CLI/Dashboard 核验；
6. 没有后台服务、未结算授权、未封存私有输出或未记录的 provider 操作遗留。
