# Pathlight Provider Call 对齐与 Compaction 建模设计

**日期：** 2026-08-04  
**状态：** 已批准  
**范围：** 修正 provider request 与 assistant response 的一对一假设；不修改外部 Pi，不修改既有 evidence，不执行新的模型调用

## 现场证据与根因

Task 8 的首轮前台执行清除了代理变量，而项目 `.env` 不包含代理配置。该运行的所有 provider
请求均返回 `fetch failed`，0 token、0 Judge、账单为 0。保留继承代理并重新加载同一 `.env` 后，
同一授权范围完成 1/1 Bright Biology：墙钟 31.43 秒、Agent 成本 $0.0480122、47,901 tokens、
7 次工具调用、0 次工具错误、0 Judge，单例 nDCG@10 为 0.339160。单例结果不是 benchmark 分数。

成功运行同时证明现有对账模型错误。私有通道完整捕获 4 个连续 provider request；Pi 可见事件只形成
3 个 assistant response。安全 context telemetry 给出了下列顺序：

1. request 1 → assistant tool-use response；
2. request 2 → assistant tool-use response；
3. request 3 → `compaction_requested`、`session_compact`、`compaction_complete`，没有 assistant
   `message_end`；
4. request 4 → assistant final response。

现有 `reconcile_provider_requests()` 要求 `provider_requests` 和 `model_calls` 数量相等并按相同 index
直接配对，因此整个 rich batch 正确地 fail closed。结果 bundle 保留 3 个 `model-request` 缺口，
没有泄漏 raw payload，但也没有完成 Task 8 所需的精确请求主线。

根因不是 provider、凭据、数据集或 capture 损坏，而是框架把“真实 provider 调用”等同于
“产生 assistant message 的调用”。Compaction、摘要、重试和其他 runtime-internal LLM 调用都可能
没有 assistant message；这些调用仍必须成为 Pathlight 主线节点。

## 目标与非目标

本设计必须：

1. 保留每个经过 raw/safe 交叉验证的 provider request，不丢弃 compaction 或失败尝试；
2. 按原生事件顺序把 assistant response 与其之前最近的未消费 request 对齐；
3. 为没有 assistant response 的 request 生成诚实的 request-only model call；
4. 只关闭已有精确证据支持的 gap，不推断 compaction response、token 或 model identity；
5. 继续保持 raw payload 只存在于封存的 operator-private evidence；
6. 观察失败仍不得改变 Agent、Judge、benchmark、重试或评分语义；
7. 保持 framework domain-neutral，DCI 只负责把产品事件翻译成通用 marker。

本阶段不修改外部 Pi，不关闭或改变 compaction，不补造 response，不把单例结果推广成 benchmark
结论，也不授权新的真实运行或优化实验。

## 已否决方案

### 丢弃没有 assistant response 的 request

这会使 compaction、provider retry 或摘要调用从 trace 消失，与“观察每次 LLM 调用”的核心目标冲突。
它还会使成本、延迟和上下文变化无法解释，因此不采用。

### 禁用 compaction 后重新运行

这会改变 Agent 的任务语义和上下文策略，只能绕开缺陷，不能修复通用观察模型。其他 runtime-internal
调用仍会再次暴露同一问题，因此不采用。

### 继续使用数量相等并靠 payload 形状猜测

Provider-specific payload 形状不是调用身份，模型重试也可能产生相似 payload。按内容猜测无法证明
事件因果关系，因此不采用。

## 数据模型

公共 `ProviderRequestObservation` 和 `RuntimeObservationBatch` 的 JSON 字段保持不变；内部 runtime
observation schema 继续使用 v2。对账完成后仍满足一个 provider request 对应一个
`ModelCallObservation`，区别是 builder 可以为 request-only 调用合成一个缺失 response 的 call。

### 已配对调用

对 request 1、2、4：

- `request_index` 使用真实 provider request index；
- `request_sha256`、ContextFrame segments 和安全结构计数来自 verified request；
- response digest、长度、usage、status 和 model digest来自对应 assistant response；
- `model-request` 被关闭；
- 因 hook 没有 Asterion monotonic timestamp，继续保留 `model-request-boundary`。

### Request-only 调用

对 request 3：

- 创建同一 `request_index` 的 `ModelCallObservation`；
- ContextFrame 完全来自 verified request segments；
- `request_sha256` 和安全结构字段完整；
- `response_sha256`、response length、input/output tokens 和 model identity 为 `None`；
- status 为 `missing`，不得把相邻 telemetry 冒充成 provider response；
- 明确保留 `model-response`、`token-usage`、`model-identity` 和
  `model-request-boundary`；
- 不包含 `model-request`，因为实际 request 已被精确捕获。

Batch 级 `missing_evidence` 仍是所有节点缺口的规范并集。公共投影必须按具体 call/frame 计算
`missing_evidence_labels`，不能把 request-only 节点的 `model-response` 错误地复制到已配对调用。

## 事件标记与单调对齐

### 产品边界

DCI recorder 已能看到 Pi 的 `entry_appended` 事件。它只识别闭合 custom type
`dci-provider-request-observation`，读取连续 `request_index`，并把下面的通用 marker 交给
`PiObservationBuilder`：

- request index；
- recorder 已分配的原生事件 sequence；
- 不含 entry data、payload、路径、provider/model/config 或自由文本。

Marker 在 raw/safe validation 完成前只是未受信候选，不得改变 batch。Framework 的 Pi adapter
只消费通用 marker API，不导入 DCI 模块或 DCI schema。

### 对齐算法

Builder 同时保存每个 assistant response 的原生事件 sequence。Reconciliation 仅在下面条件全部成立
时原子执行：

1. verified request index 严格连续；
2. marker index、数量和顺序与 verified requests 完全一致；
3. marker sequence 严格递增，且每个 response sequence 位于至少一个尚未消费的 marker 之后；
4. response sequence 严格递增；
5. rollback 没有跨越参与对齐的 marker 或 response；
6. 重建后的 frames、model calls、tools 和 missing-evidence closure 通过既有闭合验证。

对每个 response，选择它之前、上一个已配对 response 之后的**最后一个**未消费 marker。这样连续多个
request 只产生一个可见 response 时，最后一个 request 与 response 配对，之前的 request 成为
request-only call。本例得到 `1→1`、`2→2`、`4→3`，request 3 未配对。

任何 marker 漂移、response 无前置 marker、重复 index、非单调 sequence 或验证失败都保留原 inferred
batch 和原 gap，不发布部分 rich evidence。

## 主线投影

Reconciliation 按 provider request 顺序重建 frames 和 model calls，因此 trace 顺序为：

```text
request 1 / response 1
request 2 / response 2
request 3 / response missing   ← compaction request-only call
request 4 / response 3
```

工具调用继续根据原 response/tool events 和 `source_call_sha256` 链接，不把 compaction telemetry 当作
工具或 response。`trace show/tail/flow`、Dashboard 和 Opik 显示 4 个 model-call 节点；request-only
节点显示 request digest、shape/count/private-reference 和精确缺口，不显示 raw input。

`trace list` 继续是聚合摘要，不展开逐请求结构。所有公共 surfaces 继续通过闭合字段白名单，任意
`*_sha256`、`*_version` 或自由属性不能绕过协议验证。

## 私有 evidence 与离线验证

成功运行的 private capture 已在子进程静默后执行 inode/size/mtime 绑定验证，随后以 0400 封存；
公共 bundle 为 0600。既有 generation 不修改、不覆盖、不“升级”为新的 native bundle。

为复用不可变证据，`ProviderRequestCapture` 增加 operator-private、descriptor-relative 的只读 sealed
reader：

- 只接受 regular、owner-owned、0400、no-follow 的既有 `provider-requests.jsonl`；
- 通过 held read-only FD 做 bounded read 和 raw/safe 交叉验证；
- 不返回 raw payload，不公开路径，不提供公共 CLI；
- 只产生 immutable `ProviderRequestObservation`。

它用于 provider-free 重投影和回归证据。生成的 companion 必须明确标为 offline companion，不能取代
原 native bundle。新的 native 直接闭环仍需另一次独立授权。

## 失败与安全语义

- Marker 采集、sealed read、对齐、重建或投影任一失败都只保留 inferred evidence；
- request-only call 是证据缺失状态，不是 Agent 失败，也不触发 benchmark retry；
- compaction telemetry 可以作为旁证展示，但本阶段不关闭 response/usage/identity gap；
- raw payload、tool schema、prompt、answer、provider/model/config、FD 和私有路径不进入公共 bundle、
  CLI、Dashboard、Opik 或错误；
- sealed reader 和对账错误使用固定无链错误；
- DCI result、score、cost 和 authorization receipt 不因离线重投影改变。

## 测试与验收

### Provider-free TDD

- 真实顺序 fixture：4 markers、3 responses、7 tools，request 3 位于 compaction telemetry 周围；
- RED 证明当前数量相等假设拒绝该 fixture；
- GREEN 证明输出 4 frames / 4 model calls / 4 provider requests / 7 tools；
- 配对为 1→1、2→2、4→3，request 3 是 response-missing；
- 三个已配对节点不含 `model-request` 或 `model-response`；
- request-only 节点不含 `model-request`，但含 `model-response`、`token-usage`、
  `model-identity` 和 `model-request-boundary`；
- duplicate/non-contiguous marker、marker-after-response、response-without-marker、rollback crossing 和
  partial validated batch 全部原子 fallback；
- retry markers 在一个 response 前使用 latest-wins，早期 attempts 保留为 request-only；
- sealed reader 拒绝 0600、symlink、替换 inode、oversize、变更内容和 raw/safe drift；
- CLI/flow/Dashboard/Opik sentinel redaction 不变。

### 现有 evidence 的 provider-free验收

- private sealed capture 仍为 0400、4 records；
- 原 bundle 摘要不变；
- 新 offline companion 显示 4 model calls、3 observed responses、7 tools；
- `model-request` 关闭，request 3 的 response/usage/identity gap 保留；
- 不执行模型、Judge、网络或优化实验。

### 新 native 验收

完成 provider-free 门禁和独立审查后，必须再次申请一条明确、有限的 Bright Biology 单例授权。
新的前台运行必须直接生成 verified native bundle；不得用本次 offline companion 冒充。公开报告记录
实际时间、成本、tokens、工具数、request/response 数和剩余 gap，但不推广单例分数。

## 完成标准

本修复只有在以下条件全部满足时才完成：

1. provider-free tests、`make check`、`make promotion-check` 全部通过且 provider operations 为 0；
2. 本次不可变 evidence 的 offline companion 证明 4/3/7 主线和逐节点缺口；
3. 文档修正“request 数量必须等于 assistant response 数量”的旧假设；
4. 后续另行授权的 native one-case 直接产生 verified requests；
5. Dashboard 前台读取并停止，公共 surfaces 无 raw/private sentinel；
6. 单例分数继续与正式 benchmark/论文结果严格区分。
