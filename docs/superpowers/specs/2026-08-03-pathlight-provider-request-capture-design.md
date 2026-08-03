# Pathlight Provider Request 双通道采集设计

**日期：** 2026-08-03  
**状态：** 已批准，待实施计划  
**范围：** Asterion-owned Pi/DCI adapter 的精确 provider request 采集；不修改外部 Pi，不执行模型实验

## 背景与目标

Pathlight 已能从 Pi 的 `message_start/message_end`、工具调用和标准 runtime event 投影一条
可验证的数据流主线。真实 Bright Biology 单例证明了 6 次模型调用与 18 次工具调用能够闭合，
但当前 Pi 不发送旧设计假定的 `provider_request_context` native event。因此 Pathlight 只能从
可见消息历史推断请求帧，并必须保留 `model-request` 和 `context-segment` 缺口。

当前 Pi 已提供正式 `before_provider_request` extension hook。该 hook 位于 provider-specific
payload 构建完成之后、headers 与网络请求之前，能够观察实际发送的 system instructions、消息、
工具定义及 provider-specific 字段；它不包含 API key 或 HTTP headers。

本设计的目标是：

1. 对每次 provider request 记录精确原始 payload、结构摘要、调用次序和捕获状态；
2. 原始 payload 只进入 operator-owned 0600 evidence，绝不进入 Pi session、公共 trace、CLI、API、
   Dashboard、Opik envelope 或错误消息；
3. 公共 Pathlight trace 只在私有记录与独立安全摘要交叉验证成功后关闭 `model-request` 缺口；
4. 观察失败不得改变 Agent、Judge、benchmark 或 runtime 的完成/失败语义；
5. 不修改外部 Pi，不在 Python 与 TypeScript 之间复制 runner/provider 实现。

## 已否决方案

### 把原始 payload 写入 Pi custom entry

custom entry 不进入模型上下文，但 persistent Pi session 当前没有在 Asterion 边界强制 0600；
operator agent/session 目录也可能是 0755。把 prompt、工具 schema 和 provider payload 放入 session
不满足 Pathlight 私有证据边界。

### 向 Pi RPC stdout 注入自定义事件

该方案能获得实时事件，但会把非标准消息混入 Pi JSONL-RPC stdout。它依赖未声明的协议容忍行为，
可能与正常 response/event 交错，因此不采用。

### 修改外部 Pi 或维护补丁分支

上游增加正式 observation RPC event 是长期可选方向，但 Asterion 当前必须能在 pin 住且未修改的 Pi
上工作。外部 Pi 仍是 operator resource，不能成为 framework generic code 的隐式依赖或补丁载体。

## 架构

```text
Pi before_provider_request hook
          │
          ├── raw payload JSON ──▶ inherited private FD ──▶ 0600 native evidence
          │                                                │
          └── safe summary ─────▶ Pi custom entry ─────────┤
                                                           ▼
                                             Python closed cross-validation
                                                           │
                              ┌────────────────────────────┴─────────────────────────┐
                              ▼                                                      ▼
                   operator-private reference                         public Pathlight observation
                   (raw input, explicit audit)                         (digest/shape/segments only)
```

### 独立 observation extension

新增 Asterion-owned、完整性校验的 `dci-pathlight-observation.ts`。它与 context policy extension
分离并始终可由 DCI adapter 加载；因此采集不依赖 level0–level4 profile，也不改变上下文压缩策略。

DCI adapter 按确定顺序加载扩展：operator-approved context extension（若有）在前，observation
extension 最后。现有参数校验继续拒绝用户通过普通 `extra_args` 注入额外 `--extension`，从而保证
observation hook 看到的是所有已批准 hook 变换之后的最终 payload。

extension 只使用 Pi 正式的 `before_provider_request`、`appendEntry` 和 Node `fs.writeSync`。它不注册
provider、model、tool、command 或 UI，不修改 hook payload，并始终返回 `undefined`。

### Asterion-owned 私有描述符

`DciRunRecorder` 在已固定的 native generation 目录内，通过 descriptor-relative、no-follow、
`O_CREAT|O_EXCL` 创建 `provider-requests.jsonl`，权限固定为 0600。文件描述符由 product host 显式
传给 `PiRpcClient` 并加入既有 `pass_fds`；路径不进入 manifest、CLI 参数或扩展配置。

子进程环境只携带一次性的十进制 FD 号和 capture contract version。observation extension 加载后
立即读取并删除这两个环境变量，避免工具子进程从环境发现通道。扩展不发现 evidence 路径，也不能
创建、替换或选择文件。Asterion 关闭描述符并负责最终验证。

任何 FD 创建、写入、解析、交叉验证或发布失败都只禁用 rich provider observation，并产生固定
缺口；不得取消已经进行的 provider 请求，也不得把观察错误传播成 benchmark 失败。

## 私有记录契约

每个 JSONL record 使用闭合 schema `dci.private-provider-request/v1`：

- `request_index`：从 1 开始、严格连续；
- `captured_at`：hook 调用时的 UTC 时间，仅作审计排序，不冒充 monotonic timing；
- `payload_json`：hook 收到的 payload 经一次 `JSON.stringify` 得到的完整字符串；
- `payload_sha256`：`payload_json` UTF-8 bytes 的 SHA-256；
- `payload_bytes`：同一 UTF-8 bytes 长度；
- `shape_sha256`：安全结构投影的规范摘要；
- `summary_sha256`：对应 public-safe summary 的规范摘要。

原始文件是 operator-private artifact，不进入 workflow bundle。公共 trace 只保留其内容 digest、记录
序号和不含路径的 private-evidence reference。provider headers、OAuth/API keys 和环境值从未进入 hook，
也不得由扩展读取。

extension 必须拒绝无法 JSON 序列化、循环、`BigInt` 或非有限 number 的 payload；该请求仍可继续，
但 observation 形成 `provider-request-private` 缺口。写入使用完整 write loop，处理 partial write。

为避免观察通道耗尽磁盘，每条私有 record 最大 64 MiB、单次 native generation 最大 512 MiB。
超限不截断、不写半真 payload；它明确降级为 missing evidence。这个上限远高于正常模型 context，
不是 Agent token/cost 配额，也不会阻止任务继续执行。

## 公共安全摘要

同一个 hook 向 Pi 内存 session append 一条 `dci-provider-request-observation` custom entry。entry 只含：

- schema/version、连续 request index、capture status；
- payload/shape/summary SHA-256 和 byte/field/leaf/text counts；
- 有序 segment summaries：role、content type、digest、length、可选 source tool-call digest；
- 明确 missing labels；
- 不含 provider/model/config 名称、JSON key/value 原文、prompt、tool schema、路径或 payload。

安全结构投影递归遍历数组与对象，保持数组顺序并按规范 key 顺序处理对象。它记录节点类型与数量，
而不公开 key/value。segment 角色只在 payload 自身有明确 role/instructions/tool-result 语义时映射为
`system/user/assistant/tool-result`；无法证明时使用 `unknown`，不得猜测。

Python 从 RPC `get_entries` 读取这些 safe entries，同时从私有 FD 文件读取 raw records，重新计算
payload bytes/digest、结构摘要和 segment summaries。只有 request index、所有摘要、计数及顺序完全
一致时，该 request 才可成为 verified native observation。任一不一致使整次 rich request batch
fail closed，原始 Agent 结果保持不变。

## Pathlight 对齐

`PiObservationBuilder` 增加一个闭合的 request reconciliation 输入，而不是接受 DCI custom entry。
DCI adapter 把已交叉验证的数据转成通用 `ProviderRequestObservation`；framework runtime observation
模块不导入 DCI。

每项 verified observation 按 `request_index` 替换对应的 inferred request draft：

- exact payload digest 成为 `model-call.request_sha256`；
- verified segment summaries 成为 ContextFrame 的有序 segments；
- 关闭 `model-request`；
- 所有内容字段均被结构投影覆盖时关闭 `context-segment`，否则保留；
- 因 hook 没有 Asterion monotonic timestamp，保留 `model-request-boundary` timing 缺口；
- `message_end`、usage 和工具 start/end 继续决定 response、token、工具及终态，不由 request entry 推断。

request 数量与已完成/失败模型调用数量不一致、重试 rollback 跨越 observation、tool source identity
不闭合或 raw/safe batch 不一致时，不发布部分 rich request 证据。fallback trace 仍可发布并明确缺口。

## 生命周期与失败语义

1. recorder 固定 native output root，独占创建私有 capture 文件；
2. host 将 FD 与 observation extension 显式注入 Pi；
3. 每个 hook 先形成 raw bytes 和 safe summary，再写 raw FD、append safe entry；
4. provider 正常执行，现有 response/tool/native events 不变；
5. prompt 结束后、recorder finalize 前，Asterion 读取 safe entries 并验证 private records；
6. 完成态投影使用 verified request batch；失败/取消态保留 private forensic record，但不发布完成 bundle；
7. capture 文件即使 observation 不完整也不可覆盖，状态文件记录固定 failure class/digest；
8. resume 创建新的 native generation 和新的 capture 文件，绝不改写旧 generation。

observation hook 自身不得抛出影响 provider 的异常。它在内部记录固定失败状态；若连 safe entry 也无法
写入，Python 通过 raw/safe 数量不一致检测并降级。

## API、CLI 与 Dashboard

默认 `pathlight trace list/show/tail/flow`、Dashboard 和 Opik export 继续只读取公共 bundle。它们可显示：

- request 已交叉验证、payload/shape digest、结构计数和 ContextFrame segment 主线；
- request boundary timing 是否缺失；
- private evidence 是否存在及其不可解析引用；
- 每个模型/工具节点的完成、失败、取消和因果链接。

本阶段不增加返回原文的公共命令。后续 operator-private viewer 必须使用独立显式授权、审计记录和
descriptor-bound evidence service；不能通过 `--show-raw` 一类便捷开关绕过双层安全模型。

## 测试与验收

### TypeScript extension

- hook 观察最终 payload 但返回 `undefined`，不改变 provider 请求；
- raw FD 与 safe entry 对同一 payload 生成一致摘要；
- partial writes、closed FD、循环值、非有限值、超限和 append failure 均不影响 hook 返回；
- sentinel prompt/tool/payload 不出现在 safe entry；
- observation extension 不注册 provider/model/tool/command/UI；
- packaged resource 与 integrity manifest 完全一致。

### Python adapter 与 framework

- 0600、descriptor-relative、exclusive/no-follow capture 文件；
- 环境变量只注入 Pi 子进程，现有环境不被修改，私有路径不进入 argv；
- raw/safe digest、index、shape、segment、数量或顺序任一不一致均 fail closed；
- verified batch 关闭 `model-request`，保留真实存在的 timing/segment gaps；
- retry、provider error、取消、resume 和 write conflict 不改变原执行语义；
- public bundle、CLI、API、Dashboard、Opik envelope 和错误消息通过 sentinel redaction；
- DCI 依赖 framework observation types，framework 不导入 DCI。

### 真实闭环

实现与 provider-free 门禁通过后，另行申请一条 Bright Biology 授权。前台运行必须证明：

- native bundle 直接含至少一个 verified exact request，不需要离线 companion；
- private capture 为 0600，公共 bundle 不含原文；
- ContextFrame、model-call、tool-call 数量和状态由 CLI 与 Dashboard 一致读取；
- `model-request` 已关闭，仍存在的 gap 逐项说明；
- 不把单例分数推广为 benchmark 或论文比较结论。

## 与 Bright 优化闭环的关系

该能力关闭的是“模型实际看到了什么”这一框架证据缺口，不自动证明 Bright 差距根因，也不授权
查询分解实验。完成后，现有 coverage 证据可以与 request/context retention 逐节点对齐：

- Economics 可区分 gold 未检出与已检出但未进入最终 request；
- Earth Science/Robotics 可区分检索后排序、上下文保留和最终输出阶段；
- SciFact 继续作为同配置健康参照。

只有同范围 baseline/candidate 的 exact request、tool flow、evaluation、成本和时延均闭合后，查询分解
proposal 才能形成 TrialHistory 与 Decision。优化实验仍须单独、有限、显式的 operator authority。
