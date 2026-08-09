# Pathlight 操作者手册

Pathlight 用于观察、追踪、评估和优化 Asterion 智能体工作流。它只读取已封存的安全证据；不会因为
查看 trace、指标或 Dashboard 而调用模型、执行工具或访问外部网络。DCI Bright 的实验协调器是
Pathlight 的参考产品适配器，不是通用框架接口。

## 1. 先理解它的作用：不替你完成任务，而是让任务可解释、可改进

Pathlight 默认**不改变任务的答案、工具选择、重试策略或成功/失败判定**。它不是“运行一条
Pathlight 指令就自动提高任务质量”的系统。

它在一次任务中的作用链是：

```text
正常执行任务 → 记录安全的工作流证据 → 查看过程与结果 → 比较两次运行 → 诊断差异 →
人工确认改动 → 用受控实验验证改动是否真的更好
```

因此，Pathlight 的直接价值是回答：任务在哪个节点成功或失败、模型/工具上下文怎样流动、差异发生在
哪里、某个改动是否真正提升指标。它会让下一次任务的改进有证据依据，但不会在没有批准的情况下自行
修改或重跑任务。

### 最小起步：先让一次正常任务产生证据

平时怎样运行任务，就仍然怎样运行；只额外指定一个**尚不存在**的 evidence 文件。父目录必须是你
拥有的私有目录：

```bash
install -d -m 700 "$PATHLIGHT_EVIDENCE_ROOT"

uv run asterion run \
  --provider "<provider-id>" \
  --application "<application-id>@<version>" \
  --input "<your task input>" \
  --workflow-evidence-file "$PATHLIGHT_EVIDENCE_ROOT/workflow-evidence.json"
```

这条命令仍以原有应用、runtime 和 host service 完成任务；Pathlight 同时记录安全摘要和 trace。
任务完成后，终端会给出原本的公开结果，而 `workflow-evidence.json` 成为下面所有观察命令的起点。
不带 `--workflow-evidence-file` 的正常任务也可以完成，但不会有可供 Pathlight 回放的完整过程数据。

## 2. 可直接执行的案例

### 案例 A：读取已经完成的 Bright A/B（不调用模型）

如果你有一个已经完成的 Bright 优化输出根，下面四步只读取封存产物，不调用模型、Judge、工具或网络。
把第一行替换为该输出根即可：

```bash
export PATHLIGHT_AB_ROOT="/absolute/path/to/pathlight-bright-optimization"

# 1. 先确认这批实验确实完成；预期显示 status=completed。
uv run asterion-dci pathlight optimization status \
  --plan-file "$PATHLIGHT_AB_ROOT/pathlight-bright-optimization.json" \
  --output-root "$PATHLIGHT_AB_ROOT"

# 2. 读取逐例指标；输出为 canonical JSON，不会重跑案例。
uv run asterion pathlight metrics query \
  --evaluation-file "$PATHLIGHT_AB_ROOT/pathlight-evaluations.json"

# 3. 读取诊断和待审 proposal；它们不是执行命令。
uv run asterion pathlight diagnosis show \
  --diagnosis-file "$PATHLIGHT_AB_ROOT/pathlight-diagnosis.json"

uv run asterion pathlight proposal list \
  --diagnosis-file "$PATHLIGHT_AB_ROOT/pathlight-diagnosis.json"

# 4. 在本机只读 Dashboard 中查看实验、指标、诊断与最终 Decision。
uv run asterion pathlight dashboard \
  --evaluation-file "$PATHLIGHT_AB_ROOT/pathlight-evaluations.json" \
  --experiment-file "$PATHLIGHT_AB_ROOT/pathlight-experiment.json" \
  --diagnosis-file "$PATHLIGHT_AB_ROOT/pathlight-diagnosis.json" \
  --optimization-file "$PATHLIGHT_AB_ROOT/pathlight-optimization.json" \
  --host 127.0.0.1 --port 8765 --open
```

本仓库已完成的参考 A/B 运行在这套命令下会显示：80/80 Agent 操作、0 次基础设施失败、$16；最终
Decision 为 `rejected (quality-threshold-missed)`。这说明 Pathlight 的实际作用：它让你看到候选在
Biology/Economics 提升、在 Earth Science/Robotics 回退，并据此拒绝“整体优化成功”的错误结论。

### 案例 B：让下一条正常任务变得可追踪（会运行该任务本身）

这不是模拟命令。它会按你指定的 provider/application 真正完成一次任务；`--workflow-evidence-file`
只额外写出可观察证据。先在 `.env` 或你的运行环境中准备该应用所需的配置，然后执行：

```bash
install -d -m 700 "$PATHLIGHT_EVIDENCE_ROOT"

uv run asterion run \
  --provider "<provider-id>" \
  --application "<application-id>@<version>" \
  --input "<your task input>" \
  --workflow-evidence-file "$PATHLIGHT_EVIDENCE_ROOT/workflow-evidence.json"

uv run asterion pathlight trace list \
  --evidence-file "$PATHLIGHT_EVIDENCE_ROOT/workflow-evidence.json"
```

最后一条输出一个或多个 `trace_id`。复制其中一个 ID，继续执行本手册下一节的 `trace flow`。你会看到
本次任务实际经过的 ContextFrame、模型调用、工具调用以及节点成功/失败原因；这就是 Pathlight 对
“任务是否完成、为什么这样完成”的直接贡献。

## 3. 开始前：准备哪些文件

Pathlight 的输入是运行后生成的不可变文件。常用文件如下：

| 文件 | 用途 |
|---|---|
| `workflow-evidence.json` | 结构化工作流、ContextFrame、模型/工具调用与成功失败主线 |
| `pathlight-evaluations.json` | 指标、评估和可比较性范围 |
| `pathlight-experiment.json` | 实验、变体和 trial 历史 |
| `pathlight-diagnosis.json` | 诊断、finding 与 proposal |
| `pathlight-optimization.json` | 优化历史、逐例配对与最终 Decision |

所有路径必须是绝对路径。公共输出只包含经验证的结构和摘要；不要把 prompt、问题、答案、case ID、
provider payload、凭据或私有运行目录复制到终端记录、文档或工单中。

## 4. 观察与追踪：Trace 和 Flow

先列出可用 trace，再选择一个 `trace_id` 查看数据流。以下命令均为只读、无模型调用：

```bash
uv run asterion pathlight trace list \
  --evidence-file /absolute/path/workflow-evidence.json

uv run asterion pathlight trace show \
  --evidence-file /absolute/path/workflow-evidence.json \
  --trace-id "<trace-id>"

uv run asterion pathlight trace flow \
  --evidence-file /absolute/path/workflow-evidence.json \
  --trace-id "<trace-id>"
```

`flow` 是主检查入口：按顺序显示 ContextFrame、模型调用和工具调用，并明确每个节点的状态、可见
结构摘要与证据缺口。需要增量查看时使用 `trace tail --after-sequence <n>`；不要把 trace 缺口解释为
模型或工具一定失败。

## 5. 评估、实验和诊断

```bash
# 查询指标；可额外加 --metric-name、--status 或 --scope-sha256 筛选
uv run asterion pathlight metrics query \
  --evaluation-file /absolute/path/pathlight-evaluations.json

# 比较两个同一可比较范围内的评估 ID
uv run asterion pathlight evaluate compare \
  --evaluation-file /absolute/path/pathlight-evaluations.json \
  --baseline "<evaluation-id>" \
  --candidate "<evaluation-id>"

uv run asterion pathlight diagnosis show \
  --diagnosis-file /absolute/path/pathlight-diagnosis.json

uv run asterion pathlight proposal list \
  --diagnosis-file /absolute/path/pathlight-diagnosis.json
```

比较只接受范围和指标契约兼容的评估；不兼容时拒绝输出，而不是伪造结论。proposal 是待审建议，
不包含执行权，不能用已有 trace、缓存或外部建议直接启动模型调用。

## 6. 本地 Dashboard

Dashboard 在回环地址提供只读页面和 API。它读取你显式传入的文件，默认不打开浏览器；添加 `--open`
才会打开本机浏览器。运行时保持在前台，`Ctrl-C` 安全停止。

```bash
uv run asterion pathlight dashboard \
  --evidence-file /absolute/path/workflow-evidence.json \
  --evaluation-file /absolute/path/pathlight-evaluations.json \
  --experiment-file /absolute/path/pathlight-experiment.json \
  --diagnosis-file /absolute/path/pathlight-diagnosis.json \
  --optimization-file /absolute/path/pathlight-optimization.json \
  --host 127.0.0.1 \
  --port 8765
```

至少提供一种输入。若提供 diagnosis，它所引用的 experiment 与 evaluation 也必须同时提供，否则
Dashboard 会在开端口前拒绝。页面显示工作流主线、评估、实验、诊断和证据缺口；不提供写入、执行、
授权、上传或外部网络接口。

## 7. DCI Bright 受控优化

以下是 DCI 产品层命令。它从已闭合的 DCI 诊断准备固定 cohort 的查询分解实验，再从原生证据生成
Decision；通用 `asterion pathlight` 不运行这些命令。

```bash
# provider-free：生成不可变计划
uv run asterion-dci pathlight optimization prepare \
  --diagnosis-file "$PATHLIGHT_DIAGNOSIS_ROOT/pathlight-diagnosis.json" \
  --diagnosis-report-file "$PATHLIGHT_DIAGNOSIS_ROOT/pathlight-dci-diagnosis-report.json" \
  --gate-report-file "$PATHLIGHT_DIAGNOSIS_ROOT/pathlight-dci-authorization-gate.json" \
  --proposal-sha256 "$QUERY_DECOMPOSITION_PROPOSAL" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"

# 前台执行；开发模式默认不要求外层授权文件
uv run asterion-dci pathlight optimization execute \
  --env-file /absolute/path/.env \
  --plan-file "$FRESH_OPTIMIZATION_ROOT/pathlight-bright-optimization.json" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"

# 只读进度和 provider-free 收口
uv run asterion-dci pathlight optimization status \
  --plan-file "$FRESH_OPTIMIZATION_ROOT/pathlight-bright-optimization.json" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"

uv run asterion-dci pathlight optimization finalize \
  --plan-file "$FRESH_OPTIMIZATION_ROOT/pathlight-bright-optimization.json" \
  --diagnosis-file "$PATHLIGHT_DIAGNOSIS_ROOT/pathlight-diagnosis.json" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"
```

中断后使用同一计划的 `resume`，不创建新的基线或候选。开发模式默认可执行；严格生产模式设置
`ASTERION_DCI_REQUIRE_EXECUTION_AUTHORIZATION=1`，并传入与计划和输出根精确绑定的授权文件。

已经完成的 Bright 参考实验固定比较四个域各 10 条：80 次 Agent、0 次 Judge、$16、0 次基础设施
失败。候选在 Biology 和 Economics 提升、在 Earth Science 和 Robotics 回退，因此 Decision 为
`rejected (quality-threshold-missed)`。这是诊断结果，不是 423 条 Bright 全量 benchmark 的替代分数。

## 8. Opik 离线交换

Pathlight 不直接调用 Opik SDK 或网络。导出生成安全 envelope 批次，检查也只读；网络发送、认证和
重试由 Pathlight 之外的 operator-owned adapter 负责。

```bash
install -d -m 700 "$PATHLIGHT_OPIK_QUEUE"
uv run asterion pathlight export opik \
  --experiment-file /absolute/path/pathlight-experiment.json \
  --evaluation-file /absolute/path/pathlight-evaluations.json \
  --diagnosis-file /absolute/path/pathlight-diagnosis.json \
  --optimization-file /absolute/path/pathlight-optimization.json \
  --queue-root "$PATHLIGHT_OPIK_QUEUE"

uv run asterion pathlight export inspect \
  --batch-file "$PATHLIGHT_OPIK_QUEUE/batch-<sha256>.json"
```

外部观察只能用 `import opik-observation` 导入为未授权 `ProposalCandidate`；导入不会执行建议或加载
provider。

## 9. 故障排查与安全检查

- `asterion pathlight: request is invalid`：检查命令层级、必填 `--*-file` 参数和绝对路径；通用 CLI
  没有 `diagnose`，正确命令是 `diagnosis show`。
- Dashboard 启动前失败：诊断所引用的 experiment/evaluation 没有一并传入，或输入不是封存的
  Pathlight 文件。
- 比较被拒绝：两条 evaluation 的 scope 或 metric contract 不兼容；不要以人工换算替代受拒绝比较。
- DCI `execute` 前失败：先确认 `.env` 只从预期文件加载、source lock/evidence root 是新的且私有；
  出现认证、网络、限流、配额或真实模型调用障碍时，应立即报告，不把它伪装成 benchmark 分数。
- production 模式授权失败：确认开关、授权文件权限、计划摘要和输出根绑定一致。开发模式不要为了绕过
  配置问题而手工伪造授权文件。

更多架构背景见 [Pathlight 设计](../superpowers/specs/2026-08-02-asterion-pathlight-design.md)；DCI 的
全量结果与论文参照见 [DCI Benchmark 实例](../status/DCI-BENCHMARK-INSTANCES.md)。
