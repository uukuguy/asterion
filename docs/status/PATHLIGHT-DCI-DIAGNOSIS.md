# DCI 差分诊断

## 最新 Bright 查询分解 A/B（真实完成）

已完成四个 Bright 域各 10 条的配对 A/B：共 80 次 Agent、0 次 Judge、0 次基础设施失败。
候选查询分解结论为 **rejected（quality-threshold-missed）**：Biology 0.398525→0.556891、Economics
0.190583→0.241777 有提升；Earth Science 0.564065→0.525888、Robotics 0.477792→0.448306 下降。
这是受控 4×10 诊断，不能当作 423 条 Bright 全量论文复现。基线与候选成本同为 $8，候选时间增加约 9.93%。

本次 A/B 之前，修复后的五项各 10 条 coverage 已完成原生闭合并由 provider-free `reconcile`
复核；它用于选择本次固定配对范围。本文后面保留的“尚未执行”“等待重新核验”“$8 上限”文字是
执行前的历史记录，均由本节的实际完成状态取代；当前实际预算为 $16（每个四域任务 $2），实际消耗
$16，80 次 Agent 已全部完成。

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

精确请求采集实现后，另一条已获批的 Bright Biology 历史单例完成 1/1、0 次 Judge：墙钟
31.43 秒、Agent 成本 $0.0480122、47,901 tokens，7 次工具调用全部成功；单例 nDCG@10 为
0.339160。它的封存 capture 含 4 个连续 provider request，而 Pi 只产生 3 个 assistant response。
provider-free 重投影证明对齐关系为 request 1→response 1、request 2→response 2、request 4→
response 3；request 3 位于 compaction telemetry 周围，是一次没有 assistant `message_end` 的
compaction request-only 调用。

因此 request 3 缺少 response、token usage 和 model identity 是诚实的缺失证据，不是 Agent
失败，也不应触发 benchmark retry 或改变评分。该节点仍保留 `model-request-boundary`；由于精确
request 已经交叉验证，它不再含 `model-request` 缺口。offline companion 共显示 4 个
ContextFrame、4 个 model-call、3 个已观测 response 和 7 个成功工具调用，并已通过 reader、
`trace show/flow`、Dashboard 与 Pathlight–Opik 离线白名单验证。

这些结果只修正基础设施的调用对齐与可观测性。它们既不解释、也不改善 Bright 相对论文参照的
分数差距；上面的旧单例和本次历史单例原生 bundle 都保持不可变，offline companion 没有被提升为
native evidence，任何正式实例分数也没有变化。下一条 Bright Biology 单例若要验证新的 native
闭环，必须使用新的 source lock 与 evidence root，并获得一次单独、明确的执行授权；现有计划、
配置、缓存和历史批准都不授予这次调用权限。

## Coverage 实验状态（历史 v8 无效；修复后闭合已完成）

旧 v8 receipt 曾记录五项各 10/10、共 50 次 Agent、0 次 Judge、0 次失败和 $2.950832，
但后续原生闭包复核已证伪这次 coverage：原生配置中的 dataset identity 是本地夹具
`dataset.local`，不是计划要求的四项 Bright 与 BEIR SciFact。receipt 的“完成”不能替代原生
身份闭合，因此旧 v8 **不是有效的 Bright/BEIR coverage，不得用作 authorization gate**。

下表只保留先前公开数值以解释历史，不再支持任何机制结论；整表状态均为
`historical-invalid` / `non-authoritative`：

| 数据集标签 | 旧 v8 nDCG@10（10 条） | 旧记录成本 | 旧 gold coverage any/mean/all 中位数 | 旧浮现 gold / 工具观测 |
|---|---:|---:|---:|---:|
| Bright Biology | 0.581166 | $0.540605 | 1.000000 / 0.758772 / 0.000000 | 39 / 136 |
| Bright Earth Science | 0.258671 | $0.538526 | 1.000000 / 0.833333 / 0.500000 | 14 / 133 |
| Bright Economics | 0.140249 | $0.632802 | 1.000000 / 0.214285 / 0.000000 | 12 / 129 |
| Bright Robotics | 0.473500 | $0.727880 | 1.000000 / 1.000000 / 1.000000 | 23 / 219 |
| BEIR SciFact | 0.787501 | $0.511019 | 1.000000 / 1.000000 / 1.000000 | 13 / 145 |

解析器、结构化过程证据和 provider-free coverage reader 已经实现并通过本地验证，但这些实现
不能修复或升级旧 v8 的错误原生身份。旧 v8 的 coverage、retained coverage、评价记录、诊断和
门报告均不可作为真实 Bright/BEIR 证据。后续已用封存的原生证据重新验证五项各 10 条，并以
provider-free `reconcile` 写入五条身份重验记录；它们已经支撑本报告顶部所述的真实 4×10 A/B，
不再处于 `blocked-by-coverage-reverification`。

该 5×10 范围是用于选择诊断 cohort 的证据重验，不是新的 benchmark 总分或对六项全量结果的
替代。开发模式默认直接执行；设置 `ASTERION_DCI_REQUIRE_EXECUTION_AUTHORIZATION=1` 才恢复
严格生产授权文件校验。

### Fresh 5×10 coverage 与重新诊断命令

以下命令中的变量只代表操作员拥有的私有文件位置；不得把其实际值、案例 ID 或 payload 写入
公开文档。`prepare`、`status` 和执行后的 `diagnose` 读取均为 provider-free；只有 `execute`
会在单独授权后调用 Agent。

```bash
install -d -m 700 "$FRESH_COVERAGE_ROOT"
uv run asterion-dci pathlight experiment prepare \
  --diagnosis-file "$PATHLIGHT_DIAGNOSIS_ROOT/pathlight-diagnosis.json" \
  --proposal-sha256 "$COVERAGE_PROPOSAL" \
  --output-root "$FRESH_COVERAGE_ROOT"

# 获得与新计划及 output root 精确绑定的 0600 authorization 后，前台执行
uv run asterion-dci pathlight experiment execute \
  --plan-file "$FRESH_COVERAGE_ROOT/pathlight-coverage-experiment.json" \
  --authorization-file "$FRESH_COVERAGE_AUTHORIZATION_FILE" \
  --output-root "$FRESH_COVERAGE_ROOT"

uv run asterion-dci pathlight experiment status \
  --plan-file "$FRESH_COVERAGE_ROOT/pathlight-coverage-experiment.json" \
  --authorization-file "$FRESH_COVERAGE_AUTHORIZATION_FILE" \
  --output-root "$FRESH_COVERAGE_ROOT"

install -d -m 700 "$FRESH_DIAGNOSIS_ROOT"
uv run asterion-dci pathlight diagnose \
  --recovery-root "$BIOLOGY_RECOVERY_ROOT" \
  --recovery-root "$EARTH_SCIENCE_RECOVERY_ROOT" \
  --recovery-root "$ECONOMICS_RECOVERY_ROOT" \
  --recovery-root "$ROBOTICS_RECOVERY_ROOT" \
  --recovery-root "$SCIFACT_RECOVERY_ROOT" \
  --recovery-root "$BAMBOOGLE_RECOVERY_ROOT" \
  --coverage-plan-file "$FRESH_COVERAGE_ROOT/pathlight-coverage-experiment.json" \
  --coverage-authorization-file "$FRESH_COVERAGE_AUTHORIZATION_FILE" \
  --coverage-output-root "$FRESH_COVERAGE_ROOT" \
  --output-root "$FRESH_DIAGNOSIS_ROOT"
```

`diagnose` 的三个 coverage 参数必须同时出现；它会重新读取精确 authorization、receipt chain、
原生 benchmark、trajectory 与 workflow evidence，拒绝不完整、被替换或身份不一致的闭包。

## Bright 查询分解 A/B 状态（真实执行并已收口）

Pathlight 已实现 Bright 查询分解 A/B 的完整控制链：从既有诊断闭包准备不可变计划，读取精确
授权，按固定顺序执行或续跑，查看收据进度，再从原生 benchmark 与 workflow evidence 生成
Experiment、Evaluation、TrialHistory、Decision、更新后的 Diagnosis 和中文报告。真实 4×10 A/B
已经完成：40 条基线与同一 40 条候选、共 80 次 Agent、0 次 Judge、0 次基础设施失败；最终
`rejected (quality-threshold-missed)`。测试夹具仅额外验证实现边界，不是这项真实结果的依据。

### 固定范围和停止边界

- 数据范围：Bright Biology、Earth Science、Economics、Robotics 各固定 10 例；基线与候选各跑
  一次，共最多 80 次 Agent 操作。
- Judge：0 次；本实验沿用各实例自身的 nDCG@10 评估，不增加 LLM Judge。
- 计划预算：16,000,000 微美元（$16），每个四域任务 $2；本次实际消耗 $16，每个原生案例最多 1 次尝试。
- 累计 2 次基础设施类失败后停止；类别限于授权、网络、限流、超时和 host service。
- 最终结论可能是 `accepted`、`rejected` 或 `inconclusive`。缺少或不可信的收据、成本、原生
  trace、逐例配对或评价证据不能被提升为成功结论。

### 可执行的准备、查询和收口命令

下面命令是可复用的执行形状；本次已通过完成的 coverage 重验和诊断闭合执行。开发模式不要求
授权文件；仅严格生产模式需要它，且两阶段授权不能复用。

以下变量只代表操作员本机的私有位置，不应把它们的实际值复制进公开报告。`prepare` 是
provider-free 的，但它需要从当前进程环境解析四个数据源；因此在干净 shell 中清除旧值并加载
仓库 `.env`。输出根必须是当前用户拥有、权限 0700 的空目录。

```bash
# 先进入仅保留命令搜索、用户身份和代理变量的干净前台 shell
env -i HOME="$HOME" PATH="$PATH" USER="$USER" SHELL="$SHELL" TERM="${TERM:-}" \
  HTTP_PROXY="${HTTP_PROXY:-}" HTTPS_PROXY="${HTTPS_PROXY:-}" NO_PROXY="${NO_PROXY:-}" \
  zsh -f

# 以下命令在这个新 shell 中执行；.env 成为 DCI 配置的唯一来源
set -a
source .env
set +a

export PATHLIGHT_DIAGNOSIS_ROOT="/absolute/operator-owned/diagnosis-root"
export FRESH_OPTIMIZATION_ROOT="/absolute/operator-owned/empty-optimization-root"
export QUERY_DECOMPOSITION_PROPOSAL="<64-hex-proposal-sha256>"

install -d -m 700 "$FRESH_OPTIMIZATION_ROOT"
uv run asterion-dci pathlight optimization prepare \
  --diagnosis-file "$PATHLIGHT_DIAGNOSIS_ROOT/pathlight-diagnosis.json" \
  --diagnosis-report-file "$PATHLIGHT_DIAGNOSIS_ROOT/pathlight-dci-diagnosis-report.json" \
  --gate-report-file "$PATHLIGHT_DIAGNOSIS_ROOT/pathlight-dci-authorization-gate.json" \
  --proposal-sha256 "$QUERY_DECOMPOSITION_PROPOSAL" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"

uv run asterion-dci pathlight optimization status \
  --plan-file "$FRESH_OPTIMIZATION_ROOT/pathlight-bright-optimization.json" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"
```

准备后的 `status` 显示 `prepared`；本次完成后的 `status` 为 `completed`，已完成 Agent/Judge
为 80/0，实际消耗 $16。计划、`.env` 和历史输出不会自动覆盖严格生产模式的授权边界。

开发模式可在前台直接运行；中断后显式调用 `resume`。严格生产模式则传入针对计划和输出根的
单独授权文件：

```bash
uv run asterion-dci pathlight optimization execute \
  --plan-file "$FRESH_OPTIMIZATION_ROOT/pathlight-bright-optimization.json" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"

uv run asterion-dci pathlight optimization status \
  --plan-file "$FRESH_OPTIMIZATION_ROOT/pathlight-bright-optimization.json" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"

# 仅在同一授权尚有效且确需续跑时人工调用
uv run asterion-dci pathlight optimization resume \
  --plan-file "$FRESH_OPTIMIZATION_ROOT/pathlight-bright-optimization.json" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"

# 执行终止后离线读取原生证据并发布决策；本命令不调用模型
uv run asterion-dci pathlight optimization finalize \
  --plan-file "$FRESH_OPTIMIZATION_ROOT/pathlight-bright-optimization.json" \
  --diagnosis-file "$PATHLIGHT_DIAGNOSIS_ROOT/pathlight-diagnosis.json" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"
```

### 精确授权文档

授权文件必须为权限 0600 的
`asterion.dci.pathlight.bright-optimization-authorization/v1` JSON。它不是把
`execution_authorized` 从计划中原地改成 `true`，而是一个单独文件：以下边界字段必须与刚刚
读取的计划逐项完全相等。

| 绑定类别 | 必须从计划原样复制的字段 |
|---|---|
| 诊断与提案 | `plan_sha256`、`diagnosis_bundle_sha256`、`authorization_gate_report_sha256`、`proposal_sha256`、`finding_sha256`、`scope_sha256` |
| 数据与实现 | `source_lock_sha256`、`selected_case_scope_sha256`、`baseline_query_plan_sha256`、`candidate_query_plan_sha256`、`baseline_variant_sha256`、`candidate_variant_sha256`、`baseline_execution_config_sha256`、`candidate_execution_config_sha256` |
| 输出根 | `output_root_device`、`output_root_inode` |
| 有限预算 | `max_agent_operations=80`、`max_judge_operations=0`、`max_cost_microusd=8000000`、`max_infrastructure_failures=2`、`max_native_attempts=1` |

授权体还必须包含 `execution_authorized=true` 和操作员审批记录的
`operator_approval_sha256`；最后对不含 `authorization_sha256` 的整个对象按 UTF-8、键排序、
紧凑分隔符并以换行结尾做 SHA-256，写回 `authorization_sha256`。任何字段漂移、摘要错误、
文件权限错误、输出根 inode 改变或额外字段都会在加载 provider 前失败。授权应只在操作员明确
批准上述有限范围后生成；本文档本身不构成授权。

## Opik 离线互操作状态

旧诊断、六个 experiment、六项历史 evaluation bundle 和五条现已失效的 coverage evaluation 曾
通过 Pathlight–Opik 1.0.0 白名单映射，生成 1721 个幂等 envelope；批次摘要为
`3ba1d6d212b083375f5764c246c8cae6189910f64a3fb2cca6379d3be98a32ce`，文件权限 0600，
`network_operation_count=0`。批次包含 dataset、experiment、case trial、evaluation 和 proposal
关系，不包含 prompt、答案、语料、工具/模型 payload、provider 配置、凭据、私有路径或 Opik UUID。

该批次中的 coverage 与由其导出的 gate 现统一标为 `historical-invalid` / `non-authoritative`；
Opik 镜像不能恢复原生 dataset identity，也不得据此授权 A/B。

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

现有六项 DCI experiment 与历史诊断曾通过同一个只读
`DashboardSnapshot` 验证并以前台服务启动；没有执行 Agent、Judge 或外部网络请求。快照摘要为
`eb21c3b98b8a2e1ed511ad26a447ba47ff746c65bbf156beef8dfe46c7157435`，包含：

- 6 个 experiment、848 个 case trial；
- 859 个唯一 evaluation；
- 21 个 finding、2 个未获执行权的 proposal；
- 0 条历史 trace/ContextFrame 主线、854 个显式证据缺口。

其中五条 coverage evaluation 已随旧 v8 原生身份复核而失效；Dashboard 展示不构成证据 seal，
也不能把这些记录提升为 authorization gate。

最后一行不是 Dashboard 失败：早期 848 条 DCI evidence 只恢复了结果、指标和实验谱系，没有
Pathlight trace graph；界面因此拒绝伪造 ContextFrame。后续新运行只要产生已验证的
`workflow-evidence.json`，同一 Dashboard 就会显示 ContextFrame、模型调用、工具调用、节点
成功/失败和结构化摘要。启动命令和 API 边界见
[Pathlight 设计](../superpowers/specs/2026-08-02-asterion-pathlight-design.md)。

## 已完成的最小受控实验

- 覆盖率观测：旧 v8 为 `historical-invalid` / `non-authoritative`；修复后的 5×10 cohort 已完成
  provider-free 原生闭合重验，并用于 A/B 固定选样。
- 最终调用上下文采集：provider-free 框架工作，先补齐每次 LLM/tool 调用前后的结构化边界、上下文帧与失败原因，不重跑模型。
- 检索查询分解：真实 4×10 A/B 已执行并收口；80 次 Agent、0 次 Judge、$16、0 基础设施失败。候选
  未达质量门槛，Decision 为 `rejected (quality-threshold-missed)`；不自动重跑或把诊断结论伪装成
  全量 benchmark 结果。
