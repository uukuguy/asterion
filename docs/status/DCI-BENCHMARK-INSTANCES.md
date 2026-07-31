# DCI Benchmark 实例

本文档是 `asterion-dci benchmark instances --json` 所公开的全部不可变 DCI
benchmark 实例的实现清单、验证台账和运行手册。

“已经实现”和“已经完成评估”是两个不同状态：存在代码和执行入口，不代表已经运行完整
外部 benchmark。验证状态只使用 `Not rerun`、`Verified-local`、
`External-limited`、`Verified-bounded` 和 `Verified-full`。

| 实例 | 实现/验证 | 已跑/总量 | 结果 | 核心配置与证据 | 下一道门 |
|---|---|---:|---|---|---|
| `dci.bcplus.level3@1.0.0` | planned / Not rerun | — | — | — | 实现并先运行最多 50 个 |
| `dci.bcplus.main@1.0.0` | planned / Not rerun | — | — | — | 实现并先运行最多 50 个 |
| `dci.beir.arguana@1.0.0` | planned / Not rerun | — | — | — | 实现并先运行最多 50 个 |
| `dci.beir.scifact@1.0.0` | planned / Not rerun | — | — | — | 实现并先运行最多 50 个 |
| `dci.bright.biology@1.0.0` | planned / Not rerun | — | — | — | 实现并先运行最多 50 个 |
| `dci.bright.earth-science@1.0.0` | planned / Not rerun | — | — | — | 实现并先运行最多 50 个 |
| `dci.bright.economics@1.0.0` | planned / Not rerun | — | — | — | 实现并先运行最多 50 个 |
| `dci.bright.robotics@1.0.0` | planned / Not rerun | — | — | — | 实现并先运行最多 50 个 |
| `dci.local-fixture@1.0.0` | implemented / Verified-local | 15×1 | 无评分 | 无模型；安装包测试 | 维护闭环 |
| `dci.qa.2wikimultihopqa@1.0.0` | planned / Not rerun | — | — | — | 实现并先运行最多 50 个 |
| `dci.qa.bamboogle.github-sample50@1.0.0` | implemented / Verified-full | 50/50 | 82%（41/50） | `gpt-5.6-luna` / `deepseek-v4-flash`；约 $2.20；`run-e8ea4…7790` | 维护闭环 |
| `dci.qa.bamboogle.paper-full125@1.0.0` | implemented / Verified-bounded | 50/125 | 复用上一行的同一次 41/50 运行 | 50 条输入逐行一致；不新增模型调用、成本或 evidence | 运行余下 75 题形成 125/125 |
| `dci.qa.hotpotqa@1.0.0` | planned / Not rerun | — | — | — | 实现并先运行最多 50 个 |
| `dci.qa.musique@1.0.0` | planned / Not rerun | — | — | — | 实现并先运行最多 50 个 |
| `dci.qa.nq@1.0.0` | planned / Not rerun | — | — | — | 实现并先运行最多 50 个 |
| `dci.qa.triviaqa@1.0.0` | planned / Not rerun | — | — | — | 实现并先运行最多 50 个 |

## 如何使用本文档

只有标记为 `implemented` 的实例可以执行。每个 implemented 实例必须在下方拥有
同名运行手册。`planned` 行表示实例身份已经登记，但实现和运行契约尚未实现，不能执行。

所有命令都从 Asterion 仓库根目录运行。运行手册在 `"$PWD/outputs/manual"` 下创建
绝对的 lock 和 evidence 路径。每次新运行使用新的 evidence root，并返回新的 run ID。
resume 必须继续使用同一个实例、案例范围、source lock 和 evidence root。

lock 和 plan 仅处理元数据，不执行 Agent 或 Judge。包含 `--execute` 的命令才授予
这一次有限运行的执行权限。真实实例可能访问该手册列明的模型、网络、数据集和 corpus。

## 阶段性结果规则

每个真实实例必须实现完整数据范围；但可以先运行 `min(50, 完整案例数)` 个案例，作为
当前版本的阶段性结果。该结果必须写成“已跑/总量”，例如 `50/125`，并同步记录 Agent、
Judge、分数、成本和 evidence 路径。它不能被称为完整结果、论文复现结果，或与完整数据
分数直接比较。

## 运行手册：`dci.local-fixture@1.0.0`

### 作用和边界

`dci.local-fixture@1.0.0` 是 provider-free 的框架闭环夹具，不产生原 DCI benchmark 评估分数。
它验证安装后的 DCI 能力包、Asterion 通用 benchmark
planner/runner、15 个任务 binding、私有 evidence 和 resume 是否能够完整串联。

它不访问 Agent、Judge、网络、外部数据集或外部 corpus，也不衡量研究模型能力。

- Application：`dci.local-benchmark-application@1.0.0`
- Suite：`dci.all@1.0.0`
- 任务：全部 15 个 DCI task binding
- 范围：每个任务运行 1 个 fixture case
- 成本类别：provider-free
- 预期结果：15 个任务全部 `completed`，provider 操作数为 0

### lock、plan、run 和 resume

时间戳为每次运行创建独立目录。传给 Asterion 的路径都是绝对路径。

```bash
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-local-fixture-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"

uv run asterion-dci benchmark lock \
  --instance dci.local-fixture@1.0.0 \
  --output "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark plan \
  --instance dci.local-fixture@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark run \
  --instance dci.local-fixture@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute | tee "$DCI_RUN_RESULT"

export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"

uv run asterion-dci benchmark resume \
  --instance dci.local-fixture@1.0.0 \
  --run-id "$DCI_RUN_ID" \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute
```

公开结果应为 `status: completed`。私有运行状态位于
`"$DCI_EVIDENCE_ROOT/runs/$DCI_RUN_ID"`，任务输出位于
`"$DCI_EVIDENCE_ROOT/outputs/$DCI_RUN_ID"`。resume 复用已经完成的 evidence，
不会重复执行任务。

### 已验证边界

`Verified-local` 由以下安装包闭环测试建立：

```bash
uv run python -m unittest -v tests.test_asterion_dci_benchmark_installed
```

该测试在隔离环境中构建并安装 wheel，通过安装后的 `asterion-dci` 执行全部 15 个
fixture 任务，然后 resume 同一运行且不重复工作。

## 运行手册：`dci.qa.bamboogle.github-sample50@1.0.0`

### 作用和边界

这是第一个真实 DCI benchmark 实例。它在 Bamboogle GitHub sample 的 50 个案例上
运行研究 Agent，并将每个答案交给独立 Judge。Asterion 只在 preflight 通过且收到
显式执行授权后，才把可移植 DCI 能力包绑定到 operator-owned 资源。

- Application：`dci.complete-application@1.0.0`
- Suite：`dci.qa.bamboogle.github-sample50@1.0.0`
- 任务：`qa.bamboogle.github-sample50`
- 默认范围：1 个案例，仅用于有限能力验证
- 完整范围：50 个案例
- Agent：Pi，使用已配置的研究模型和 DCI prompt 契约
- Judge：独立配置的 Judge 模型
- 外部依赖：Pi checkout、Agent authentication、Judge credential、Bamboogle
  数据集、corpus 和网络
- 单案例成本：最多 1 次 Agent 操作和 1 次 Judge 操作
- 完整评估成本：最多 50 次 Agent 操作和 50 次 Judge 操作

### preflight

先根据 operator template 配置 `.env` 中的外部资源路径和 credentials。
preflight 只检查 readiness，不调用 Agent 或 Judge，也不授予执行权限。

```bash
uv run asterion-dci preflight --env-file "$PWD/.env"
```

所有类别都必须为 `PASS`。进程环境变量优先于 `.env`；如果认证结果异常，应检查
继承的 `DEEPSEEK_API_KEY` 等变量。

### 单案例能力验证

这一流程只验证真实 Agent/Judge 执行路径，不能代表完整 Bamboogle sample50 结果。
lock 和 plan 不访问模型、Judge、数据集正文或 corpus 正文；run 最多执行 1 次 Agent
和 1 次 Judge。

```bash
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-bamboogle-case1-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"

uv run asterion-dci benchmark lock \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --output "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark plan \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark run \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute | tee "$DCI_RUN_RESULT"

export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"

uv run asterion-dci benchmark resume \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --run-id "$DCI_RUN_ID" \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute
```

公开结果应报告 1 个 `completed` 任务和 `case_count: 1`。它只建立
`Verified-bounded`，不建立完整 50 案例评估结果。

### 完整 50 案例评估

下面才是完整执行 `dci.qa.bamboogle.github-sample50@1.0.0` 并获得该实例聚合评估
结果的流程。`--all-cases` 在 plan、run 和 resume 中都解析为确定的 50 案例范围。
`--execute` 明确授权最多 50 次 Agent 和 50 次 Judge 操作，因此会产生模型费用并
访问网络、数据集和 corpus。

```bash
export DCI_FULL_RUN_ROOT="$PWD/outputs/manual/dci-bamboogle-full50-$(date +%Y%m%d-%H%M%S)"
export DCI_FULL_SOURCE_LOCK="$DCI_FULL_RUN_ROOT/source-lock.json"
export DCI_FULL_EVIDENCE_ROOT="$DCI_FULL_RUN_ROOT/evidence"
export DCI_FULL_RUN_RESULT="$DCI_FULL_RUN_ROOT/run-result.json"
mkdir -p "$DCI_FULL_RUN_ROOT"

uv run asterion-dci benchmark lock \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --output "$DCI_FULL_SOURCE_LOCK"

uv run asterion-dci benchmark plan \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --all-cases \
  --capability-source-lock "$DCI_FULL_SOURCE_LOCK"

uv run asterion-dci benchmark run \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --all-cases \
  --capability-source-lock "$DCI_FULL_SOURCE_LOCK" \
  --evidence-root "$DCI_FULL_EVIDENCE_ROOT" \
  --execute | tee "$DCI_FULL_RUN_RESULT"

export DCI_FULL_RUN_ID="$(jq -er '.run_id' "$DCI_FULL_RUN_RESULT")"

uv run asterion-dci benchmark resume \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --run-id "$DCI_FULL_RUN_ID" \
  --all-cases \
  --capability-source-lock "$DCI_FULL_SOURCE_LOCK" \
  --evidence-root "$DCI_FULL_EVIDENCE_ROOT" \
  --execute

export DCI_FULL_SUMMARY="$DCI_FULL_EVIDENCE_ROOT/outputs/$DCI_FULL_RUN_ID/qa.bamboogle.github-sample50/summary.json"
jq '{counts,accuracy}' "$DCI_FULL_SUMMARY"
```

成功的 run 应报告 `case_count: 50`。`summary.json` 中：

- `counts.total` 应为 50；
- `counts.judged` 是成功完成独立 Judge 的案例数；
- `counts.correct` 是 Judge 判定正确的案例数；
- `accuracy.over_total` 是完整 50 案例准确率；
- `accuracy.over_judged` 是已完成 Judge 案例中的准确率。

这会产生 GitHub sample50 实例的原 DCI 评估格式和聚合结果，但仍不是论文完整结果。
完整 125 题实例现已可执行；在其真实运行完成前，当前仍不能声称得到原论文的 125-case
结果或完成 paper-score reproduction。

### 已验证边界

2026-07-30 的 main-workspace 完整运行
`run-e8ea4a0db373482b9a849d8f8ace7790` 完成全部 50 个案例：

- 50/50 个案例完成独立 Judge；
- 41/50 判定正确；
- `accuracy.over_total` 和 `accuracy.over_judged` 均为 82%；
- `failed_runs` 为 0；
- 精确 resume 耗时 0 秒，新增 evidence 0 个，新增 generation 0 个。

因此 GitHub sample50 当前为 `Verified-full`。该状态仅覆盖这个 50-case 实例；
它不能替代尚未运行的 full125 实例或原论文复现结果。

## 运行手册：`dci.qa.bamboogle.paper-full125@1.0.0`

这是同一 Bamboogle 数据的完整 125 题实例。50 题公开样本是这 125 题的严格子集：本地
逐行规范化比对确认 50 条记录全部一致（题目和标准答案均相同）。它们共享本地
`corpus/wiki_corpus`，所以已验证 sample50 的结果可作为本实例的阶段性结果。

- Application：`dci.complete-application@1.0.0`
- Suite：`dci.qa.bamboogle.paper-full125@1.0.0`
- 阶段性覆盖：50/125；它引用上方 sample50 行的同一次 `41/50、82%` 运行，
  不重复记录分数、模型、成本或 evidence
- 完整结果：125/125，尚未运行；不以 50/125 声称论文完整分数

50/125 已有上述可复用的已验证结果，无需重跑。后续完整运行使用：

```bash
export DCI_125_ROOT="$PWD/outputs/manual/dci-bamboogle-125-$(date +%Y%m%d-%H%M%S)"
export DCI_125_LOCK="$DCI_125_ROOT/source-lock.json"
export DCI_125_EVIDENCE="$DCI_125_ROOT/evidence"
export DCI_125_RESULT="$DCI_125_ROOT/run-result.json"
mkdir -p "$DCI_125_ROOT"

uv run asterion-dci benchmark lock \
  --instance dci.qa.bamboogle.paper-full125@1.0.0 \
  --output "$DCI_125_LOCK"

uv run asterion-dci benchmark run \
  --instance dci.qa.bamboogle.paper-full125@1.0.0 \
  --all-cases \
  --capability-source-lock "$DCI_125_LOCK" \
  --evidence-root "$DCI_125_EVIDENCE" \
  --execute | tee "$DCI_125_RESULT"

export DCI_125_RUN_ID="$(jq -er '.run_id' "$DCI_125_RESULT")"
export DCI_125_SUMMARY="$DCI_125_EVIDENCE/outputs/$DCI_125_RUN_ID/qa.bamboogle.paper-full125/summary.json"
jq '{counts,accuracy,totals,reproduction_totals}' "$DCI_125_SUMMARY"
```

resume 时必须保留同一 run ID、范围、lock 和 evidence root。完整运行的结果才可以标为
`Verified-full`；50/125 只能标为 `Verified-bounded`。

## 故障排查

- `benchmark source lock is invalid`：必须传入带引号的绝对路径，例如
  `"$PWD/outputs/manual/.../source-lock.json"`，不能使用裸的相对路径
  `FRESH_LOCK`。
- resume 找不到或无法匹配运行：必须使用同一次 `run` 产生的 run ID 和 evidence
  root。历史 run ID 不能在新的空 evidence root 中恢复。
- provider 认证异常：检查继承的进程环境变量，因为它们会覆盖 `.env` 中的值。
- planned 实例被拒绝：实例身份虽然存在，但实现尚未实现。必须同时完成实现和运行
  手册并将其提升为 implemented 后，才能执行 lock、plan 或 run。
