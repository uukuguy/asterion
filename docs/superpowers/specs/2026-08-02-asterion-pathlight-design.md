# Asterion Pathlight 设计

**日期：** 2026-08-02  
**状态：** Core、查询、评估、诊断、受控优化、Opik 离线互操作与 operator-local Dashboard 已实现；Bright 4×10 真实 A/B 为 ready-for-authorization / Not rerun
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

## Opik 互操作与设计吸收

Opik 是 Pathlight 的重要外部工具和可选工作台，但不是 Asterion 的执行权威、私有证据库或
运行时依赖。Pathlight 先在本地形成可验证的安全记录；安装并显式配置 Opik exporter 后，才以
异步、失败不影响任务的方式导出可分享摘要。默认优先 operator-local/self-hosted 部署；云端
导出必须另有操作员配置与审计。

从 Opik 吸收以下框架设计，同时保持 Asterion 的边界：

- **Trace / Span / Thread。** 保留 Pathlight 的端到端 Trace 与 Span，增加跨轮次的安全
  `thread` 关联摘要；它仅链接 digest 身份，不携带会话文本。
- **评估可回溯。** 每项 Evaluation、人工/规则反馈和指标反馈都指向产生它的 Trace、Span 与
  版本化 metric contract；因此分数能够回到具体工作流阶段，而不是孤立报表。
- **不可变数据集与实验。** 用 dataset snapshot、case scope、experiment 和 variant 明确记录
  比较对象，拒绝覆盖范围、版本或指标契约不一致的比较。Opik 的 experiment 可成为 Pathlight
  的外部镜像，不能取代本地记录。
- **从失败到回归。** 经确认的 Finding 可以产生最小 regression case/test-suite 候选；候选须
  保留事实、假设、成功标准和基线，而不能把模型推测自动固化为真相。
- **离线优先导出。** 导出进入 operator-owned 队列；网络、认证或 Opik 服务故障只形成安全的
  exporter 状态，不得改变 runner、runtime、评估或证据落盘结果。恢复后可幂等补发。
- **标准互操作。** 优先通过安全的 OpenTelemetry trace/span 摘要或一个窄 Pathlight exporter
  adapter 对接 Opik；不在 framework core 引入 Opik SDK、自动装饰器或不稳定 REST 依赖。
- **受控优化。** Opik 的 prompt/模型优化、评估和实验分析只能产生 Pathlight Proposal 的建议。
  仍由 Asterion 的操作员审批、预算、停止条件、授权和取消链路决定是否执行。

### 从 Opik 源码吸收的规范对象

Opik 的关键价值不是单独的 trace 页面，而是把 dataset item、experiment item、trace、feedback
score 和 optimization history 连成一个可回溯闭环。Pathlight 将该思想收敛为以下领域中立、内容
寻址的对象；它们属于 Asterion 契约，不依赖 Opik ID 或 Opik SDK：

- `SubjectRef`：以 `trace`、`span`、`thread`、`experiment` 或 `case-trial` 类型和内容摘要标识一个
  可评价对象。它使指标既能评价最终任务，也能评价一次检索、工具调用或跨轮会话。
- `DatasetSnapshot`：绑定 dataset schema、数据来源契约、内容摘要、总样本数和可选父快照。名称或
  “latest” 标签不能作为比较依据；恢复旧版本产生新快照，不改写历史快照。
- `EvaluatorContract`：绑定 Metric contract、评价器类别、实现摘要、版本、输入/输出结构和失败
  语义。LLM Judge 的模型/策略只保存安全版本摘要，凭据和原始 prompt 仍在操作员私有层。
- `ExperimentPlan`：绑定一个 DatasetSnapshot、确定的 case scope、一个基线 variant、若干候选
  variant、case 分派策略、EvaluatorContract 集合、预算/停止条件摘要和授权引用。它描述获准的
  实验，不自行授予执行权限。
- `Variant`：记录 assembly、能力包、实现、runtime、模型、工具、prompt contract 和策略的精确
  摘要，以及相对基线的最小变更摘要。真实 prompt 或 provider 配置不得进入该对象。
- `CaseTrial`：将一个 dataset item digest、一个 Variant、一次 Trace 和逐项 Evaluation 一一
  关联。聚合分数必须能下钻到 CaseTrial，不能只保留一个总分。
- `TrialHistory`：不可变记录 baseline、round、candidate、随机种子、安全用量、成本、最佳值、
  停止原因和失败分布。并行只影响调度，不得改变 case identity、排序或聚合结果。
- `Decision`：以 `accepted`、`rejected` 或 `inconclusive` 记录候选相对基线的最终结论、阈值、
  Finding/TrialHistory 摘要和操作员审批引用。分数持平、证据不足或不可比较时默认保留基线。

因此完整主线为：

```text
DatasetSnapshot → ExperimentPlan → Variant → CaseTrial → Trace / Span
                                              │              │
                                              └── Evaluation ┘
                                                       │
                                              Finding → Proposal
                                                       │
                                      TrialHistory → Decision
```

### 反馈、在线评估和回归

借鉴 Opik 将 feedback score 绑定 trace/span/experiment item 的方式，Pathlight Evaluation 增加
`SubjectRef`、EvaluatorContract、来源类别（规则、人工、Judge、回收）和评价者安全摘要。同名
分数只有在 metric、evaluator、dataset snapshot、scope 和 coverage 全部一致时才能聚合或比较。

在线采样规则建模为版本化 `EvaluationPolicy`，记录选择条件、采样率、评价器、预算和停止条件。
规则本身不授权模型调用；需要 Judge 时仍经过 Asterion 的显式 authority、成本上限、取消和审计
链路。确认的失败可以生成 regression case 候选，但必须由操作员决定是否纳入新的 DatasetSnapshot。

人工反馈保留 reviewer identity digest、来源、时间、冲突状态和被评价 SubjectRef。人工与自动
Judge 的结果不能无来源地覆盖彼此；冲突形成 Finding，而不是静默选择最后写入值。

### 查询与分析模型

Pathlight 吸收 Opik 查询语言的可组合过滤思想，但不在核心中执行任意查询字符串。查询 API 使用
版本化、字段白名单、类型安全的 filter AST，并只作用于默认安全层。第一阶段的精确 CLI filter
保持不变；后续 AST 是其兼容扩展，可表达组件、状态、时间、metric、dataset、experiment、
variant 和 failure category 的交并条件。未知字段、私有字段和不受支持的操作符 fail closed。

### Opik 映射与双向信任边界

映射是版本化 adapter，而不是两个系统共享数据库：

| Pathlight 权威对象 | Opik 外部镜像 | 边界 |
|---|---|---|
| Trace / Span / Thread | trace / span / thread | 只导出安全摘要和稳定关联 |
| DatasetSnapshot | dataset version | Opik 名称/标签不能替代本地内容摘要 |
| ExperimentPlan / Variant | experiment metadata | Opik 可视化实验，不获得执行权限 |
| CaseTrial | experiment item | 只链接 dataset item digest、trace 和安全结果 |
| Evaluation | feedback score | 必须携带 metric/evaluator 映射版本与来源 |
| TrialHistory | optimization run/trial | 作为外部分析镜像，不是本地决策记录 |
| Proposal / Decision | optimization suggestion/result | 导入后先成为非权威候选 |

导出单位为不可变 `ExportEnvelope`：包含本地对象摘要、schema/mapping 版本、事件类型、幂等键、
安全 payload 摘要和队列序号。operator-owned exporter 在 runner 外消费持久队列，记录
`ExportReceipt`、重试类别和最终状态；网络、401、限流、服务升级或部分写入都不得改变任务和
本地 Evaluation 结果。相同幂等键重发不得产生第二份逻辑对象。

反向导入仅接受 feedback、实验分析和优化建议，先验证 connector identity、mapping 版本、对象
摘要、metric/evaluator 可解析性和重复事件，再保存为 `ExternalObservation` 或
`ProposalCandidate`。它们在本地复核、显式批准和受控试验前没有执行或评价权威；Opik 删除、
修改或重新标记对象也不能改写 Pathlight 已存在的不可变事实。

### 明确不吸收的 Opik 机制

- 不在 framework core 引入 Opik SDK、全局客户端、自动装饰器或隐式网络发送。
- 不把原始 prompt/response、dataset item、工具参数/输出或其可逆编码放入默认 trace。
- 不让 Opik prompt registry 成为 Asterion manifest 权威；Pathlight 只记录 prompt contract 和
  私有内容摘要，真实内容仍由 operator-owned evidence 管理。
- 不把 Opik 项目名、对象 UUID、可变标签或“latest”当作 Asterion 的规范身份。
- 不允许外部 optimizer 直接修改能力包、assembly、runtime、模型、工具、prompt 或预算。
- 不让 Opik Dashboard、在线规则或 Guardrails 服务绕过 Asterion host authority；Pathlight 只
  观察并关联其结果。

导出时只允许 Pathlight 默认安全层：opaque/digest identity、状态、时延、token/可信成本、失败
分类、版本摘要、metric 和已授权的安全 evidence reference。prompt、answer、语料、工具/模型
原始 payload、凭据、私有路径及其可逆编码一律禁止。Dashboard 阶段将把 Opik UI 作为可选的
外部视图，与 Asterion operator-local UI 的取舍基于稳定 API 决定。

### API

- 创建/读取 trace，实时订阅安全事件；
- 按任务、能力包、实现绑定、assembly、runtime、host service、状态或 metric 查询；
- 读取 evaluation 与比较范围；
- 请求 comparison、diagnosis 和 proposal，拒绝范围或指标不兼容；
- 私有 evidence 只返回授权引用，永不返回原文。

Dashboard API 已实现为一次性验证并固定的 `DashboardSnapshot`。它只读取操作员显式指定的
`workflow-evidence.json`、`pathlight-evaluations.json`、`pathlight-experiment.json` 和
`pathlight-diagnosis.json`；诊断引用的 experiment/evaluation 必须在同一快照内解析，否则在
开端口前拒绝。API 只允许回环地址上的 `GET`/`HEAD`，提供 `summary`、`traces`、逐 trace
`flow`、`evaluations`、`experiments`、`diagnoses` 和完整 `snapshot` 投影。没有写入、执行、授权、
上传、provider 或外部网络接口。

### CLI

提供 `trace list/show/tail/flow`、`metrics query`、`evaluate compare`、`diagnose`、
`proposal create/review/execute`、`export opik/inspect` 和 `import opik-observation`。所有
human-readable 输出与 JSON 输出都遵守安全层；执行 proposal 复用显式 authorization、成本上限
和 cancellation，绝不以已有 trace 或外部建议授权。

已实现的本机界面命令为：

```bash
uv run asterion pathlight dashboard \
  --evidence-file /absolute/path/workflow-evidence.json \
  --evaluation-file /absolute/path/pathlight-evaluations.json \
  --experiment-file /absolute/path/pathlight-experiment.json \
  --diagnosis-file /absolute/path/pathlight-diagnosis.json \
  --host 127.0.0.1 \
  --port 8765
```

四类输入均可重复指定且至少需要一种；若包含 diagnosis，则必须同时提供它引用的 experiment
和 evaluation 闭包。命令在前台运行，只有显式 `--open` 才打开浏览器，`Ctrl-C` 后输出停止状态。

### Bright 受控优化命令

DCI 产品层已经实现查询分解 A/B 协调器；通用 Pathlight 只提供领域中立的 Experiment、
Evaluation、TrialHistory、Decision、查询、Dashboard 和 Opik 安全映射。DCI 协调器不会反向
进入 framework 模块。它固定比较四个 Bright 数据集各 10 例的基线/候选，最多 80 次 Agent、
0 次 Judge、8,000,000 微美元，每个原生案例最多一次尝试；收据链累计两次基础设施失败即停止。

当前真实 A/B 未运行，状态为 `ready-for-authorization` / `Not rerun`。provider-free 的准备、
查询和执行后收口入口如下；变量只指向操作员私有文件，公共产物不得展开其值：

```bash
uv run asterion-dci pathlight optimization prepare \
  --diagnosis-file "$PATHLIGHT_DIAGNOSIS_ROOT/pathlight-diagnosis.json" \
  --diagnosis-report-file "$PATHLIGHT_DIAGNOSIS_ROOT/pathlight-dci-diagnosis-report.json" \
  --gate-report-file "$PATHLIGHT_DIAGNOSIS_ROOT/pathlight-dci-authorization-gate.json" \
  --proposal-sha256 "$QUERY_DECOMPOSITION_PROPOSAL" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"

uv run asterion-dci pathlight optimization status \
  --plan-file "$FRESH_OPTIMIZATION_ROOT/pathlight-bright-optimization.json" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"

uv run asterion-dci pathlight optimization finalize \
  --plan-file "$FRESH_OPTIMIZATION_ROOT/pathlight-bright-optimization.json" \
  --authorization-file "$FRESH_AUTHORIZATION_FILE" \
  --diagnosis-file "$PATHLIGHT_DIAGNOSIS_ROOT/pathlight-diagnosis.json" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"
```

`prepare` 生成的不可变计划保持 `execution_authorized=false`。单独的 0600 授权文档使用
`asterion.dci.pathlight.bright-optimization-authorization/v1`，必须逐项绑定计划、诊断、授权门、
finding/proposal/scope、source lock、所选案例范围、基线/候选查询规划、variant、执行配置、输出
根设备/inode，以及 80/0/$8/两次基础设施失败/一次原生尝试边界；另含操作员审批摘要、
`execution_authorized=true` 和对规范授权体的摘要。执行命令只在这一精确授权下以前台方式运行，
`resume` 只能处理同一计划中从未开始的剩余任务；`finalize` 重新读取原生证据，证据不足时只能
产生 `inconclusive`。详尽中文运行手册见
[DCI 差分诊断](../../status/PATHLIGHT-DCI-DIAGNOSIS.md#bright-查询分解-ab-状态尚未执行)。

### Opik 离线操作模式

第一阶段实现不安装或调用 Opik SDK。`export opik` 读取已经验证的 Pathlight evidence、experiment、
evaluation 与 diagnosis 文件，把白名单字段映射成 `ExportEnvelope`，再写入操作员拥有的 0700
目录中的 0600 幂等批次。`export inspect` 只校验并显示这个安全批次；真正的网络发送、认证、重试
与 Opik 对象 UUID 由 runner 外的 operator-owned adapter 负责，并用 `ExportReceipt` 回写结果。

```bash
install -d -m 700 "$PATHLIGHT_OPIK_QUEUE"
uv run asterion pathlight export opik \
  --experiment-file /absolute/path/pathlight-experiment.json \
  --evaluation-file /absolute/path/pathlight-evaluations.json \
  --diagnosis-file /absolute/path/pathlight-diagnosis.json \
  --queue-root "$PATHLIGHT_OPIK_QUEUE"

uv run asterion pathlight export inspect \
  --batch-file "$PATHLIGHT_OPIK_QUEUE/batch-<sha256>.json"
```

反向输入必须是 0600 的 `pathlight-external-observation.json`。优化建议只能转成
`ProposalCandidate`，其 `requires_operator_authorization=true` 且
`execution_authorized=false`；导入命令不执行建议，也不加载 provider：

```bash
install -d -m 700 "$PATHLIGHT_OPIK_IMPORT"
uv run asterion pathlight import opik-observation \
  --observation-file /absolute/path/pathlight-external-observation.json \
  --output-root "$PATHLIGHT_OPIK_IMPORT"
```

### Dashboard（最后实现）

Dashboard 只通过 API 工作，不直接读取 evidence store。主视图是 ContextFrame 数据流主线与
Span 时序；辅助视图为评估、实验历史、诊断和证据缺口。它默认只展示安全层。当前实现为随 wheel
发布的无外部依赖 HTML/CSS/JavaScript，使用同源只读 API，不使用 CDN、远程字体、分析脚本或
浏览器持久化。没有 ContextFrame 的历史运行显示为 `missing`，不根据结果反推节点。

2026-08-03 使用六项现有 DCI 安全实验、最新五条 coverage evaluation 和诊断闭包完成前台核验：
快照摘要为 `eb21c3b98b8a2e1ed511ad26a447ba47ff746c65bbf156beef8dfe46c7157435`，包含 6 个
experiment、848 个 trial、859 个 evaluation、21 个 finding 和 2 个 proposal。由于这些 848 条
历史运行没有 Pathlight trace graph，Dashboard 如实显示 0 条 trace 主线和 854 个证据缺口；这
证明现有结果/评估/诊断可观察，不表示历史最终 LLM ContextFrame 已被恢复。

## 分期交付

1. **核心契约与采集。** schema、Trace/Span/ContextFrame、framework 边界事件、不可变存储、
   完整性/红线验证和现有 `workflow_evidence` 兼容迁移。
2. **查询与评估。** 本地查询 API、CLI、trace 回放、安全 evidence 回收和版本化 evaluation
   关联。
3. **诊断与受控优化。** 可比性规则、事实/假设/缺口报告、proposal 生命周期及最小实验授权。
4. **DCI 验收。** 对 Bright/SciFact/Bamboogle 生成回收报告；对证据缺口执行批准的小样本验证。
5. **Opik 互操作。** 在本地查询、评估和 proposal 契约稳定后，实现离线安全 exporter、实验
   映射与回归反馈闭环。
6. **Dashboard（已验证）。** 基于稳定 API 实现 operator-local UI，并保留 Opik 作为可选外部
   工作台；两者都不得绕过安全层或操作员授权。

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
