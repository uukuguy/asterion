# DCI Benchmark 实例

本文档是 `asterion-dci benchmark instances --json` 所公开的全部不可变 DCI
benchmark 实例的实现清单、验证台账和运行手册。

“已经实现”和“已经完成评估”是两个不同状态：存在代码和执行入口，不代表已经运行完整
外部 benchmark。验证状态只使用 `Not rerun`、`Verified-local`、
`External-limited`、`Verified-bounded` 和 `Verified-full`。

| 实例 | 实现/验证 | 已跑/总量 | 结果 | 核心配置与证据 | 历史推进记录 |
|---|---|---:|---|---|---|
| `dci.bcplus.level3@1.0.0` | implemented / Verified-bounded | 50/830 | 34%（17/50） | `gpt-5.6-luna` / `deepseek-v4-flash`；约 $4.29；`run-480faa…65ff`；resume 未新增生成 | 实现并完成 `dci.bcplus.main@1.0.0` 的 50 条版本 |
| `dci.bcplus.main@1.0.0` | implemented / Verified-bounded | 50/830 | 28%（14/50） | `gpt-5.6-luna` / `deepseek-v4-flash`；约 $4.69；`run-9bc4c4…ceb4`；resume 未新增生成 | 实现并完成下一个实例的 50 条版本 |
| `dci.beir.arguana@1.0.0` | implemented / Verified-bounded | 50/1406 | nDCG@10 = 0.5493 | `gpt-5.6-luna`；无 Judge；约 $2.75；`run-009492…1d24`；resume 未新增生成 | 实现并完成 `dci.beir.scifact@1.0.0` 的 50 条版本 |
| `dci.beir.scifact@1.0.0` | implemented / Verified-full | 300/300 | nDCG@10 = 0.7524 | `gpt-5.6-luna`；无 Judge；$14.9801；`run-6639…79dc`；0 失败、无密钥 resume 已验证 | 全量结果与论文参照见下表 |
| `dci.bright.biology@1.0.0` | implemented / Verified-full | 103/103 | nDCG@10 = 0.4456 | `gpt-5.6-luna`；无 Judge；$5.6353；`run-86fde4…6443`；无密钥 resume 已验证 | 全量结果与论文参照见下表 |
| `dci.bright.earth-science@1.0.0` | implemented / Verified-full | 116/116 | nDCG@10 = 0.4382 | `gpt-5.6-luna`；无 Judge；$6.4950；`run-f19b7f…eef0`；无密钥 resume 已验证 | 全量结果与论文参照见下表 |
| `dci.bright.economics@1.0.0` | implemented / Verified-full | 103/103 | nDCG@10 = 0.3097 | `gpt-5.6-luna`；无 Judge；$6.8860；0 失败；无密钥 resume 已验证 | 全量结果与论文参照见下表 |
| `dci.bright.robotics@1.0.0` | implemented / Verified-full | 101/101 | nDCG@10 = 0.3367 | `gpt-5.6-luna`；无 Judge；$7.2845；0 失败；无密钥 resume 已验证 | 全量结果与论文参照见下表 |
| `dci.local-fixture@1.0.0` | implemented / Verified-local | 15×1 | 无评分 | 无模型；安装包测试 | 维护闭环 |
| `dci.qa.2wikimultihopqa@1.0.0` | implemented / Verified-bounded | 50/12,576 | 80%（40/50） | `gpt-5.6-luna` / `deepseek-v4-flash`；约 $1.89；`run-9d46b7…7032`；resume 未新增生成 | 实现并完成 `dci.qa.hotpotqa@1.0.0` 的 50 条版本 |
| `dci.qa.bamboogle@1.0.0` | implemented / Verified-bounded | 50/125 | 82%（41/50） | `gpt-5.6-luna` / `deepseek-v4-flash`；约 $2.20；`run-e8ea4…7790` | 等待所有实例的 50 条版本完成后，再统一决定全量 |
| `dci.qa.hotpotqa@1.0.0` | implemented / Verified-bounded | 50/7,405 | 76%（38/50） | `gpt-5.6-luna` / `deepseek-v4-flash`；约 $2.22；`run-9d3831…59eb`；resume 未新增生成 | 实现并完成 `dci.qa.musique@1.0.0` 的 50 条版本 |
| `dci.qa.musique@1.0.0` | implemented / Verified-bounded | 50/2,417 | 44%（22/50） | `gpt-5.6-luna` / `deepseek-v4-flash`；约 $2.64；`run-4d89eb…ccfa`；resume 未新增生成 | 实现并完成 `dci.qa.nq@1.0.0` 的 50 条版本 |
| `dci.qa.nq@1.0.0` | implemented / Verified-bounded | 50/3,610 | 72%（36/50） | `gpt-5.6-luna` / `deepseek-v4-flash`；约 $1.74；`run-dde54b…c23d`；resume 未新增生成 | 实现并完成 `dci.qa.triviaqa@1.0.0` 的 50 条版本 |
| `dci.qa.triviaqa@1.0.0` | implemented / Verified-bounded | 50/11,313 | 92%（46/50） | `gpt-5.6-luna` / `deepseek-v4-flash`；约 $1.10；`run-8b0d0b…755d`；resume 未新增生成 | 所有真实实例已完成 50 条版本 |

表中最后一列仅保留当时的实施顺序，**不是待办或下一步**。所有真实实例的 50 条阶段已经完成；
推荐核验包的 Bright 四项、SciFact 和 Bamboogle 全量运行均已完成。

六项已完成 evidence 已经由 provider-free Pathlight 命令恢复、交叉验证并诊断；安全的数值观察、证据缺口和未获授权的两项最小实验提案见
[Pathlight DCI 差分诊断](PATHLIGHT-DCI-DIAGNOSIS.md)。该诊断中的论文数值为 reference-only，不能作为完全复现或跨配置可比性的结论。

Pathlight coverage 有限实验已完成五项各 10/10：共 50 次 Agent、0 次 Judge、
0 失败，实际成本 $2.950832。其 observed gold mean coverage 中位数分别为 Biology
0.758772、Earth Science 0.833333、Economics 0.214285、Robotics 1.000000、SciFact
1.000000。Economics 显示明显的检索覆盖不足；Earth Science 与 Robotics 已找到大部分或
全部 gold 却仍低分，说明还需检查排序、证据选择和最终输出。最后一次 LLM 调用上下文尚未形成
可验证帧，因此 retained coverage 仍不可用；这项框架采集缺口必须先于新的模型优化实验修复。
完整分母、成本、摘要和结论边界见上述中文诊断文档。

## 推荐核验包的全量执行台账

推荐核验包共 848 条：Bright Biology 103、Earth Science 116、Economics 103、Robotics 101、
Bamboogle 125、SciFact 300。这里的“全量”严格指该实例的全部案例，而不是扩大后的样本。

| 实例 | 全量覆盖 | 实际分数 | 论文参照 | 差值 | 实际成本 | 状态与解释 |
|---|---:|---:|---:|---:|---:|---|
| Bright Biology | 103/103 | 0.4456 | 0.7710 | −0.3254 | $5.6353 | 已完成；0 失败、无密钥 resume 已验证 |
| Bright Earth Science | 116/116 | 0.4382 | 0.6900 | −0.2518 | $6.4950 | 已完成；0 失败、无密钥 resume 已验证 |
| Bright Economics | 103/103 | 0.3097 | 0.4680 | −0.1583 | $6.8860 | 已完成；0 失败、无密钥 resume 已验证 |
| Bright Robotics | 101/101 | 0.3367 | 0.5680 | −0.2313 | $7.2845 | 已完成；0 失败、无密钥 resume 已验证 |
| Bamboogle | 125/125 | 81.6% | 80.0% | +1.6 个百分点 | $3.3553 | 已完成；0 失败；以清理后的进程配置加载 `.env` 后运行；同一 run resume 已验证 |
| BEIR SciFact | 300/300 | 0.7524 | 0.7570 | −0.0046 | $14.9801 | 已完成；0 失败、无 Judge、无密钥 resume 已验证 |

前四项与论文相差较大，但不能写成“论文复现失败”：论文登记的配置、模型、工具、语料处理
与当前 Asterion `gpt-5.6-luna` 配置不相同。全量覆盖说明聚合与数据范围正确；它不让不同配置的
分数自动具备可比性。

## 与论文记录的分数参照

下表的“论文参照”来自仓库固化的论文主结果登记（`DCI-Agent-CC`，全量数据）；Asterion
结果默认是 `gpt-5.6-luna / deepseek-v4-flash` 的 50 条有界运行；Bright 四项已替换为其
完整运行。覆盖率决定了差值的性质：覆盖率低时它只是发现异常的信号。两边模型、工具和语料
处理不同，因此差值**不能**当作论文复现结论或实现正确性的充分证明。

| 实例 | Asterion 运行 / 覆盖率 | 论文参照（全量） | 表面差值 | 解读强度 |
|---|---:|---:|---:|---|
| BC+ Level 3 | 34.0%，50/830（6.0%） | 80.0% | −46.0 个百分点 | 低覆盖；强烈异常信号，不能量化偏差 |
| BC+ Main | 28.0%，50/830（6.0%） | 80.0% | −52.0 个百分点 | 低覆盖；强烈异常信号，不能量化偏差 |
| BEIR ArguAna | 0.5493，50/1,406（3.6%） | 0.8530 | −0.3037 | 低覆盖；需全量复核 |
| BEIR SciFact | 0.7524，300/300（100%） | 0.7570 | −0.0046 | 全量；相差 0.46 个百分点，配置不同，方向上接近 |
| Bright Biology | 0.4456，103/103（100%） | 0.7710 | −0.3254 | 全量；配置不同，偏低值得后续诊断 |
| Bright Earth Science | 0.4382，116/116（100%） | 0.6900 | −0.2518 | 全量；配置不同，偏低值得后续诊断 |
| Bright Economics | 0.3097，103/103（100%） | 0.4680 | −0.1583 | 全量；配置不同，偏低值得后续诊断 |
| Bright Robotics | 0.3367，101/101（100%） | 0.5680 | −0.2313 | 全量；配置不同，偏低值得后续诊断 |
| 2WikiMultiHopQA | 80.0%，50/12,576（0.4%） | 82.0% | −2.0 个百分点 | 极低覆盖；仅说明流程可用 |
| Bamboogle | 81.6%，125/125（100%） | 80.0% | +1.6 个百分点 | 全量；方向上接近，配置不同，不能作为论文复现结论 |
| HotpotQA | 76.0%，50/7,405（0.7%） | 88.0% | −12.0 个百分点 | 极低覆盖；不能判定偏差大小 |
| MuSiQue | 44.0%，50/2,417（2.1%） | 74.0% | −30.0 个百分点 | 低覆盖；强烈异常信号，需全量复核 |
| Natural Questions | 72.0%，50/3,610（1.4%） | 78.0% | −6.0 个百分点 | 极低覆盖；不能判定偏差大小 |
| TriviaQA | 92.0%，50/11,313（0.4%） | 96.0% | −4.0 个百分点 | 极低覆盖；仅说明流程可用 |

因此目前可确认的是 Bright 四项的全量执行闭环正确。若要诊断与论文的分差，优先核对模型、
工具、语料检索与度量实现差异；BC+ 和 MuSiQue 仍只完成低覆盖阶段运行。

## 全量运行的时间和费用估算

以下是**当前 Asterion 配置**（表中所记的 Agent/Judge、并发和工具限制）的预算估算，不是
论文作者配置的复现预算。费用以每个实例已完成的 50 条实际账单按 `完整案例数 / 50` 线性外推；
时间以对应 evidence 中首末案例事件的墙钟跨度按同一比例外推。它不含数据下载、人工排障、
失败重试和 API 限流等待；因此应把费用预留为约数，并为时间额外预留至少 25%。

| 实例 | 完整案例数 | 预计费用 | 预计单实例墙钟时间 |
|---|---:|---:|---:|
| BC+ Level 3 | 830 | $71 | 6.3 小时 |
| BC+ Main | 830 | $78 | 5.7 小时 |
| BEIR ArguAna | 1,406 | $77 | 4.6 小时 |
| BEIR SciFact | 300 | $15 | 0.8 小时 |
| Bright Biology | 103 | $8 | 0.5 小时 |
| Bright Earth Science | 116 | $8 | 0.7 小时 |
| Bright Economics | 103 | $8 | 0.4 小时 |
| Bright Robotics | 101 | $9 | 0.5 小时 |
| 2WikiMultiHopQA | 12,576 | $475 | 169 小时 |
| Bamboogle | 125 | $6 | 1.9 小时 |
| HotpotQA | 7,405 | $329 | 97 小时 |
| MuSiQue | 2,417 | $128 | 39 小时 |
| Natural Questions | 3,610 | $125 | 38 小时 |
| TriviaQA | 11,313 | $248 | 92 小时 |
| **全部 14 个真实实例，依次执行** | **41,235** | **约 $1,586** | **约 456 小时（19 天连续运行）** |

这里的“单实例墙钟时间”已经包含该实例当前并发策略的效果；若多个实例同时运行，理论日历时间
可缩短，但会受模型配额、网络和主机资源限制，不能把 456 小时直接除以任意并发数。费用不会因
并行而降低。

### 只选择少数实例做全量时的建议

“全量”应指某个实例的全部案例；若只挑部分案例，应明确称为“扩大样本”，不能称为全量。推荐按
下列三个预算包逐级推进，每一包完成、评分和 resume 都验证后再进入下一包：

| 优先包 | 包含的全量实例 | 案例数 | 预计费用 | 预计墙钟时间 | 选择理由 |
|---|---|---:|---:|---:|---|
| **A：最小诊断包（首选）** | Bright Biology、Earth Science、Economics、Robotics | 423 | 约 $34 | 约 2.1 小时 | 50 条已覆盖 43%–50%，且四项都低于论文参照；以极低成本即可得到可解释的完整分数。 |
| **B：推荐核验包** | A + Bamboogle + SciFact | 848 | 约 $54 | 约 4.8 小时 | 加入一个 QA 锚点和一个 IR 锚点；两者的 50 条结果已接近论文参照，可检验完整聚合是否稳定。 |
| **C：差异排查包** | B + BC+ Level 3 + BC+ Main + MuSiQue | 4,925 | 约 $330 | 约 56 小时 | BC+ 与 MuSiQue 的 50 条表面差异很大；这包能区分“抽样偶然性”和系统性配置/能力差异。 |

因此，如果本轮只批准一小部分全量，我建议批准 **B 包**：848 条、约 $54，并预留 6–8 小时。
它既会产出四个最有诊断价值的 Bright 完整结果，也有 Bamboogle/SciFact 两个相对稳定的参照点。
不建议首先全量运行 2Wiki、HotpotQA、Natural Questions 或 TriviaQA：它们目前的覆盖率只有
0.4%–1.4%，但合计约 $1,178 和约 399 小时；除非目标是完成全部论文规模的逐项结果，否则投入产出比最低。

## 如何使用本文档

只有标记为 `implemented` 的实例可以执行。每个 implemented 实例必须在下方拥有
同名运行手册。`planned` 行表示实例身份已经登记，但实现和运行契约尚未实现，不能执行。

所有命令都从 Asterion 仓库根目录运行。运行手册在 `"$PWD/outputs/manual"` 下创建
绝对的 lock 和 evidence 路径。每次新运行使用新的 evidence root，并返回新的 run ID。
resume 必须继续使用同一个实例、案例范围、source lock 和 evidence root。

lock 和 plan 仅处理元数据，不执行 Agent 或 Judge。包含 `--execute` 的命令才授予
这一次有限运行的执行权限。真实实例可能访问该手册列明的模型、网络、数据集和 corpus。

## 阶段性结果规则

每个真实实例必须实现完整数据范围；当前执行策略是先逐一完成每个实例的
`min(50, 完整案例数)` 真实运行、评分与 resume 验证，再考虑启动任一实例的全量数据。
阶段性结果必须写成“已跑/总量”，例如 `50/125`，并同步记录 Agent、Judge、分数、成本和
evidence 路径。它不能被称为完整结果、论文复现结果，或与完整数据分数直接比较。

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

## 运行手册：`dci.qa.bamboogle@1.0.0`

### 作用和边界

这是第一个真实 DCI benchmark 实例。总量为 125 条；它运行研究
Agent，并将每个答案交给独立 Judge。Asterion 只在 preflight 通过且收到显式执行授权后，
才把 DCI 能力包绑定到 operator-owned 资源。

- Application：`dci.complete-application@1.0.0`
- Suite：`dci.qa.bamboogle.paper-full125@1.0.0`
- 任务：`qa.bamboogle.paper-full125`
- 默认范围：1 个案例，仅用于有限能力验证
- 完整范围：125 个案例
- Agent：Pi，使用已配置的研究模型和 DCI prompt 契约
- Judge：独立配置的 Judge 模型
- 外部依赖：Pi checkout、Agent authentication、Judge credential、Bamboogle
  数据集、corpus 和网络
- 单案例成本：最多 1 次 Agent 操作和 1 次 Judge 操作
- 已验证的全量：125/125，0 失败，准确率 81.6%，实际成本 $3.3553

### preflight

先根据 operator template 配置 `.env` 中的外部资源路径和 credentials。
preflight 只检查 readiness，不调用 Agent 或 Judge，也不授予执行权限。
这份完整 125 条数据与其 corpus 位于本工作区，运行前必须固定资源根，避免继承到只含
50 条样本的外部基线目录。

```bash
export ASTERION_DCI_RESOURCE_ROOT="$PWD"
uv run asterion-dci preflight --env-file "$PWD/.env"
```

所有类别都必须为 `PASS`。这里的 Judge `PASS` 仅表示模型选择和非空凭据已经配置，
不会向远端发送题目来验证凭据是否被接受；正式运行的第一条 Judge 请求才会完成该验证。
进程环境变量优先于 `.env`；如果认证结果异常，应检查继承的 `DEEPSEEK_API_KEY` 等变量。

### 已验证的全量 125/125 结果

本轮使用同一个独立 evidence root 完成全部 125 条：0 失败，准确率 `81.6%`，实际成本
`$3.3553`。论文登记的参照为 `80.0%`，表面差值为 `+1.6` 个百分点。这个差值说明当前
完整聚合的方向接近参照；由于 Agent、Judge、提示和外部工具配置并不等同于论文环境，不能
把它写成论文复现结论。

该运行的 `benchmark resume` 已在清理继承模型/Judge 配置、再加载 `.env` 的 shell 中返回
`completed` 和 125 条，未创建新案例。这同时验证了已完成 evidence 可以恢复读取，而无需重复
调用 Agent 或 Judge。

### 当前 50 条阶段性评估

这条命令处理 125 条中的前 50 条，得到当前版本的阶段性结果。lock 和 plan 不访问模型、
Judge、数据集正文或 corpus 正文；run 最多执行 50 次 Agent 和 50 次 Judge。

```bash
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-bamboogle-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"

uv run asterion-dci benchmark lock \
  --instance dci.qa.bamboogle@1.0.0 \
  --output "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark plan \
  --instance dci.qa.bamboogle@1.0.0 \
  --case-limit 50 \
  --capability-source-lock "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark run \
  --instance dci.qa.bamboogle@1.0.0 \
  --case-limit 50 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute | tee "$DCI_RUN_RESULT"

export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"

uv run asterion-dci benchmark resume \
  --instance dci.qa.bamboogle@1.0.0 \
  --run-id "$DCI_RUN_ID" \
  --case-limit 50 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute
```

公开结果应报告一个 `completed` 任务和 `case_count: 50`。它建立
`Verified-bounded`，不代表 125 条完整评估。

### 已验证边界

2026-07-30 的 main-workspace 完整运行
`run-e8ea4a0db373482b9a849d8f8ace7790` 完成全部 50 个案例：

- 50/50 个案例完成独立 Judge；
- 41/50 判定正确；
- `accuracy.over_total` 和 `accuracy.over_judged` 均为 82%；
- `failed_runs` 为 0；
- 精确 resume 耗时 0 秒，新增 evidence 0 个，新增 generation 0 个。

这项 50/125 的阶段性结果为 `Verified-bounded`；它不能替代完整的 125 条结果或论文复现。
只有在所有实例的 50 条版本都完成后，才择机运行完整范围。届时使用：

```bash
export DCI_125_ROOT="$PWD/outputs/manual/dci-bamboogle-125-$(date +%Y%m%d-%H%M%S)"
export DCI_125_LOCK="$DCI_125_ROOT/source-lock.json"
export DCI_125_EVIDENCE="$DCI_125_ROOT/evidence"
export DCI_125_RESULT="$DCI_125_ROOT/run-result.json"
mkdir -p "$DCI_125_ROOT"

uv run asterion-dci benchmark lock \
  --instance dci.qa.bamboogle@1.0.0 \
  --output "$DCI_125_LOCK"

uv run asterion-dci benchmark run \
  --instance dci.qa.bamboogle@1.0.0 \
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

## 运行手册：`dci.bcplus.level3@1.0.0`

### 作用和边界

这是 BrowseComp-Plus Level 3 的真实 DCI 实例，总量 830 条。当前版本只运行前 50 条；
每条由研究 Agent 作答，再由独立 Judge 聚合评分。它使用 operator 配置的数据集、corpus、
Pi、模型认证和网络；模型调用会产生费用。

- Application：`dci.complete-application@1.0.0`
- Suite：`dci.bcplus.level3@1.0.0`
- 任务：`bcplus.level3`
- 当前范围：50/830
- 完整范围：830 条（当前不执行）
- 每条最多 300 个 Agent 回合，最多 10 路并发（沿用该实例既定执行档案）

### 当前 50 条阶段性评估

先执行 preflight。它只检查外部资源是否就绪，不调用 Agent 或 Judge。

```bash
uv run asterion-dci preflight --env-file "$PWD/.env"

export DCI_RUN_ROOT="$PWD/outputs/manual/dci-bcplus-level3-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"

uv run asterion-dci benchmark lock \
  --instance dci.bcplus.level3@1.0.0 \
  --output "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark plan \
  --instance dci.bcplus.level3@1.0.0 \
  --case-limit 50 \
  --capability-source-lock "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark run \
  --instance dci.bcplus.level3@1.0.0 \
  --case-limit 50 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute | tee "$DCI_RUN_RESULT"

export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"
export DCI_SUMMARY="$DCI_EVIDENCE_ROOT/outputs/$DCI_RUN_ID/bcplus.level3/summary.json"
jq '{counts,accuracy}' "$DCI_SUMMARY"
```

resume 必须复用同一个 run ID、范围、source lock 和 evidence root。运行成功后，将
`summary.json` 的聚合计数、准确率、模型、Judge、成本和 evidence 路径填写到上方表格。
在 50 条完成前，本实例不标为 `Verified-bounded`。

### 已验证的 50/830 结果

本次真实执行使用 `gpt-5.6-luna` 作为 Agent、`deepseek-v4-flash` 作为 Judge，完成
50 个案例的 Agent 运行与独立判分：17 个正确、33 个不正确或未判为正确、0 个失败，
准确率为 34%。总 Agent 成本约为 $4.29；Judge 成本为 $0。

运行 ID 为 `run-480faaa833b84c84a766284b8e7865ff`。随后以完全相同的实例、50 条
范围、source lock 与 evidence root 执行 `benchmark resume`，结果仍为 completed，且
native-generation 目录数量保持 50，证明 resume 没有重新调用 Agent 或 Judge。该结果为
`Verified-bounded`，不是 830 条完整结果，也不是原论文分数。

## 运行手册：`dci.beir.arguana@1.0.0`

这是 BEIR ArguAna 的真实 IR 实例，总量 1406 条；当前先执行 50 条。它由 Agent 生成
检索结果，并以 binary deduplicated nDCG@10 聚合评分，不使用 QA 答案正确率。每条最多
300 个 Agent 回合，最多 10 路并发。若原生 Agent 留下可验证的 failed/incomplete/running
证据，DCI 只恢复一次：有可恢复会话时复用同一 native generation；否则保留失败证据并新建
一代。50 条运行最多产生 100 次 Agent 尝试；第二次仍失败则 fail closed。完整 1406 条在
所有实例的 50 条版本完成前不执行。

```bash
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci preflight --env-file "$PWD/.env"

export DCI_RUN_ROOT="$PWD/outputs/manual/dci-beir-arguana-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"

ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark lock --instance dci.beir.arguana@1.0.0 --output "$DCI_SOURCE_LOCK"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark plan --instance dci.beir.arguana@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark run --instance dci.beir.arguana@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute | tee "$DCI_RUN_RESULT"

export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark resume --instance dci.beir.arguana@1.0.0 --run-id "$DCI_RUN_ID" --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute
```

只有 run 和 resume 都成功，且 resume 不新增 generation，才能标为 `Verified-bounded`；台账
必须记录 `50/1406`、nDCG@10、成本和 run ID。

### 已验证的 50/1406 结果

本次真实运行使用 `gpt-5.6-luna` 生成检索结果，不使用 Judge，完成 50/1406 条，全部
完成、0 失败。binary deduplicated nDCG@10 为 `0.5493`（约 54.93%）；Agent 成本约
为 $2.75。期间有 2 条出现原生瞬态问题，保留首代证据后在第二代完成，因此有 52 个
native generation、但仍只有 50 个评测案例和 50 次计入评测的 Agent 操作。

运行 ID 为 `run-0094923a1dd747cb960ee7a64af21d24`。随后以相同实例、范围、source
lock 和 evidence root 执行 `benchmark resume`，结果仍为 completed，native generation
数量保持 52，证明 resume 没有新调用 Agent。该结果为 `Verified-bounded`，不是 1406 条
完整结果，也不是原论文分数。

## 运行手册：`dci.beir.scifact@1.0.0`

这是 BEIR SciFact 的真实 IR 实例，总量 300 条；当前执行论文选定的 50 条。它由 Agent
生成检索结果，并按 binary deduplicated nDCG@10 聚合评分，不使用 Judge。每条最多 300
个 Agent 回合、最多 10 路并发；失败时至多再尝试两次，第三次仍失败即 fail closed。

```bash
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci preflight --env-file "$PWD/.env"
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-beir-scifact-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark lock --instance dci.beir.scifact@1.0.0 --output "$DCI_SOURCE_LOCK"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark plan --instance dci.beir.scifact@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark run --instance dci.beir.scifact@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute | tee "$DCI_RUN_RESULT"
export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark resume --instance dci.beir.scifact@1.0.0 --run-id "$DCI_RUN_ID" --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute
```

只有 run 和 resume 都成功，且 resume 不新增 generation，才能标为 `Verified-bounded`；台账
必须记录 `50/300`、nDCG@10、成本和 run ID。

### 已验证的 50/300 结果

本次真实运行使用 `gpt-5.6-luna` 生成检索结果，不使用 Judge，完成 50/300 条，全部
完成、0 失败。binary deduplicated nDCG@10 为 `0.7579`（约 75.79%）；Agent 成本约
为 $2.46。期间有 6 条出现原生瞬态问题，在后续 generation 完成，因此共有 56 个 native
generation、但仍只有 50 个评测案例和 50 次计入评测的 Agent 操作。

运行 ID 为 `run-ec81e1d47d6f4188b1d0e1691f51687e`。随后以相同实例、范围、source
lock 和 evidence root 执行 `benchmark resume`，结果仍为 completed，native generation
数量保持 56，证明 resume 没有新调用 Agent。该结果为 `Verified-bounded`，不是 300 条
完整结果，也不是原论文分数。

### 已验证的全量 300/300 结果

全量运行 ID 为 `run-6639f380eb0c4e8ab7632c6bf05979dc`。它在官方 BEIR SciFact test
qrels 的全部 300 条案例上完成，0 失败；binary deduplicated nDCG@10 为 `0.7524`，Agent
实际成本为 `$14.9801`。仓库登记的论文参照为 `0.7570`，表面差值为 `−0.0046`（0.46 个
百分点）。这证明当前实例的数据选择、聚合和完整运行链路可用；模型、提示和检索细节并未
与论文逐项对齐，因此该差值不是论文复现结论。

随后使用同一实例、全量范围、source lock 和 evidence root 执行 `benchmark resume`，返回
`completed` 和 `case_count: 300`，没有重新调用 Agent。最终 evidence 中有 300 份案例结果，
没有 batch error 文件，故状态为 `Verified-full`。

## 运行手册：`dci.bright.biology@1.0.0`

这是 Bright Biology 的真实 IR 实例，总量 103 条；当前先运行 50 条。它由 Agent 生成
检索结果，并按 binary deduplicated nDCG@10 聚合评分，不使用 Judge。每条最多 300 个
Agent 回合、最多 10 路并发；失败时至多再尝试两次，第三次仍失败即 fail closed。

```bash
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci preflight --env-file "$PWD/.env"
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-bright-biology-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark lock --instance dci.bright.biology@1.0.0 --output "$DCI_SOURCE_LOCK"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark plan --instance dci.bright.biology@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark run --instance dci.bright.biology@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute | tee "$DCI_RUN_RESULT"
export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark resume --instance dci.bright.biology@1.0.0 --run-id "$DCI_RUN_ID" --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute
```

只有 run 和 resume 都成功，且 resume 不新增 generation，才能标为 `Verified-bounded`；台账
必须记录 `50/103`、nDCG@10、成本和 run ID。

### 已验证的 50/103 结果

本次真实运行使用 `gpt-5.6-luna` 生成检索结果，不使用 Judge，完成 50/103 条，全部
完成、0 失败。binary deduplicated nDCG@10 为 `0.6339`（精确值
`0.6338939527446429`）；Agent 成本约为 $3.92。共创建 50 个 native generation，恰好
对应 50 个评测案例与 50 次计入评测的 Agent 操作。

运行 ID 为 `run-9ae14d96f2c5457d883d0f32b4cb0b0c`。随后以相同实例、范围、source
lock 和 evidence root 执行 `benchmark resume`，结果仍为 completed，native generation
数量保持 50，证明 resume 没有新调用 Agent。该结果为 `Verified-bounded`，不是 103 条
完整结果，也不是原论文分数。

## 运行手册：`dci.bright.economics@1.0.0`

这是 Bright Economics 的真实 IR 实例，总量 103 条；当前先运行 50 条。它由 Agent
生成检索结果，并按 binary deduplicated nDCG@10 聚合评分，不使用 Judge。每条最多 300 个
Agent 回合、最多 10 路并发；失败时至多再尝试两次，第三次仍失败即 fail closed。

```bash
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci preflight --env-file "$PWD/.env"
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-bright-economics-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark lock --instance dci.bright.economics@1.0.0 --output "$DCI_SOURCE_LOCK"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark plan --instance dci.bright.economics@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark run --instance dci.bright.economics@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute | tee "$DCI_RUN_RESULT"
export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark resume --instance dci.bright.economics@1.0.0 --run-id "$DCI_RUN_ID" --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute
```

只有 run 和 resume 都成功，且 resume 不新增 generation，才能标为 `Verified-bounded`；台账
必须记录 `50/103`、nDCG@10、成本和 run ID。

### 已验证的 50/103 结果

本次真实运行的 run ID 为 `run-63742304e39c4d4a852d1bc4b27174f9`：50 条全部完成、
无失败，nDCG@10 为 `0.37165142180029237`（台账显示为 0.3717）。共执行 50 次 Agent
操作、0 次 Judge 操作，成本为 `$4.1091958`（台账显示约 $4.11）。首次运行后共有 50 条
native generation；resume 后仍为 50，未发起新生成。此为 50/103 的有界结果，不是完整
103 条结果，也不能与原论文完整分数直接等同。

## 运行手册：`dci.bright.robotics@1.0.0`

这是 Bright Robotics 的真实 IR 实例，总量 101 条；当前先运行 50 条。它由 Agent
生成检索结果，并按 binary deduplicated nDCG@10 聚合评分，不使用 Judge。每条最多 300 个
Agent 回合、最多 10 路并发；失败时至多再尝试两次，第三次仍失败即 fail closed。

```bash
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci preflight --env-file "$PWD/.env"
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-bright-robotics-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark lock --instance dci.bright.robotics@1.0.0 --output "$DCI_SOURCE_LOCK"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark plan --instance dci.bright.robotics@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark run --instance dci.bright.robotics@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute | tee "$DCI_RUN_RESULT"
export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark resume --instance dci.bright.robotics@1.0.0 --run-id "$DCI_RUN_ID" --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute
```

只有 run 和 resume 都成功，且 resume 不新增 generation，才能标为 `Verified-bounded`；台账
必须记录 `50/101`、nDCG@10、成本和 run ID。

### 已验证的 50/101 结果

本次真实运行的 run ID 为 `run-e9575e75038647269134b72c4da70502`：50 条全部完成、
无失败，nDCG@10 为 `0.4178025843311341`（台账显示为 0.4178）。共执行 50 次 Agent
操作、0 次 Judge 操作，成本为 `$4.4601244`（台账显示约 $4.46）。首次运行后共有 50 条
native generation；resume 后仍为 50，未发起新生成。此为 50/101 的有界结果，不是完整
101 条结果，也不能与原论文完整分数直接等同。

## 运行手册：`dci.qa.2wikimultihopqa@1.0.0`

这是 2WikiMultiHopQA 的真实 QA 实例，总量 12,576 条；当前先运行 50 条。它由 Agent
给出答案，并由 Judge 按 answer correctness 聚合评分。每条最多 100 个 Agent 回合、单路
执行；单条原生执行失败即 fail closed。

```bash
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci preflight --env-file "$PWD/.env"
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-qa-2wikimultihopqa-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark lock --instance dci.qa.2wikimultihopqa@1.0.0 --output "$DCI_SOURCE_LOCK"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark plan --instance dci.qa.2wikimultihopqa@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark run --instance dci.qa.2wikimultihopqa@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute | tee "$DCI_RUN_RESULT"
export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark resume --instance dci.qa.2wikimultihopqa@1.0.0 --run-id "$DCI_RUN_ID" --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute
```

只有 run 和 resume 都成功，且 resume 不新增 generation，才能标为 `Verified-bounded`；台账
必须记录 `50/12,576`、正确率、成本和 run ID。

### 已验证的 50/12,576 结果

本次真实运行的 run ID 为 `run-9d46b77d0fd84f408a20bc329b7f7032`：50 条全部完成、
无失败，Judge 判定正确 40 条，正确率为 `80%`。共执行 50 次 Agent 操作、50 次 Judge
操作，成本为 `$1.88782`（台账显示约 $1.89）。首次运行后共有 50 条 native generation；
resume 后仍为 50，未发起新生成。此为 50/12,576 的有界结果，不是完整 12,576 条结果，
也不能与原论文完整分数直接等同。

## 运行手册：`dci.qa.triviaqa@1.0.0`

这是 TriviaQA 的真实 QA 实例，总量 11,313 条；当前先运行 50 条。它由 Agent 给出答案，
并由 Judge 按 answer correctness 聚合评分。每条最多 100 个 Agent 回合、单路执行。

```bash
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci preflight --env-file "$PWD/.env"
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-qa-triviaqa-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark lock --instance dci.qa.triviaqa@1.0.0 --output "$DCI_SOURCE_LOCK"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark plan --instance dci.qa.triviaqa@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark run --instance dci.qa.triviaqa@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute | tee "$DCI_RUN_RESULT"
export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark resume --instance dci.qa.triviaqa@1.0.0 --run-id "$DCI_RUN_ID" --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute
```

### 已验证的 50/11,313 结果

本次真实运行的 run ID 为 `run-8b0d0b9ca0654f0c9b0863906a54755d`：50 条全部完成、无失败，
Judge 判定正确 46 条，正确率为 `92%`。共执行 50 次 Agent 操作、50 次 Judge 操作，成本为
`$1.0974634`（台账显示约 $1.10）。首次运行后共有 50 条 native generation；resume 后仍为
50，未发起新生成。此为 50/11,313 的有界结果，不是完整 11,313 条结果，也不能与原论文完整
分数直接等同。

## 运行手册：`dci.qa.hotpotqa@1.0.0`

这是 HotpotQA 的真实 QA 实例，总量 7,405 条；当前先运行 50 条。它由 Agent 给出答案，
并由 Judge 按 answer correctness 聚合评分。每条最多 100 个 Agent 回合、单路执行；单条
原生执行失败即 fail closed。

```bash
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci preflight --env-file "$PWD/.env"
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-qa-hotpotqa-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark lock --instance dci.qa.hotpotqa@1.0.0 --output "$DCI_SOURCE_LOCK"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark plan --instance dci.qa.hotpotqa@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark run --instance dci.qa.hotpotqa@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute | tee "$DCI_RUN_RESULT"
export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark resume --instance dci.qa.hotpotqa@1.0.0 --run-id "$DCI_RUN_ID" --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute
```

只有 run 和 resume 都成功，且 resume 不新增 generation，才能标为 `Verified-bounded`；台账
必须记录 `50/7,405`、正确率、成本和 run ID。

### 已验证的 50/7,405 结果

本次真实运行的 run ID 为 `run-9d38318832304246bd46f3c19fe459eb`：50 条全部完成、
无失败，Judge 判定正确 38 条，正确率为 `76%`。共执行 50 次 Agent 操作、50 次 Judge
操作，成本为 `$2.2247338`（台账显示约 $2.22）。首次运行后共有 50 条 native generation；
resume 后仍为 50，未发起新生成。此为 50/7,405 的有界结果，不是完整 7,405 条结果，
也不能与原论文完整分数直接等同。

## 运行手册：`dci.qa.musique@1.0.0`

这是 Musique 的真实 QA 实例，总量 2,417 条；当前先运行 50 条。它由 Agent 给出答案，并由
Judge 按 answer correctness 聚合评分。每条最多 100 个 Agent 回合、单路执行；单条原生执行
失败即 fail closed。

```bash
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci preflight --env-file "$PWD/.env"
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-qa-musique-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark lock --instance dci.qa.musique@1.0.0 --output "$DCI_SOURCE_LOCK"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark plan --instance dci.qa.musique@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark run --instance dci.qa.musique@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute | tee "$DCI_RUN_RESULT"
export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark resume --instance dci.qa.musique@1.0.0 --run-id "$DCI_RUN_ID" --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute
```

只有 run 和 resume 都成功，且 resume 不新增 generation，才能标为 `Verified-bounded`；台账
必须记录 `50/2,417`、正确率、成本和 run ID。

### 已验证的 50/2,417 结果

本次真实运行的 run ID 为 `run-4d89eb351de14ba4a7ed7a988331ccfa`：50 条全部完成、
无失败，Judge 判定正确 22 条，正确率为 `44%`。共执行 50 次 Agent 操作、50 次 Judge
操作，成本为 `$2.6381642`（台账显示约 $2.64）。首次运行后共有 50 条 native generation；
resume 后仍为 50，未发起新生成。此为 50/2,417 的有界结果，不是完整 2,417 条结果，
也不能与原论文完整分数直接等同。

## 运行手册：`dci.qa.nq@1.0.0`

这是 Natural Questions 的真实 QA 实例，总量 3,610 条；当前先运行 50 条。它由 Agent 给出答案，
并由 Judge 按 answer correctness 聚合评分。每条最多 100 个 Agent 回合、单路执行。

```bash
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci preflight --env-file "$PWD/.env"
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-qa-nq-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark lock --instance dci.qa.nq@1.0.0 --output "$DCI_SOURCE_LOCK"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark plan --instance dci.qa.nq@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark run --instance dci.qa.nq@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute | tee "$DCI_RUN_RESULT"
export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark resume --instance dci.qa.nq@1.0.0 --run-id "$DCI_RUN_ID" --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute
```

只有 run 和 resume 都成功，且 resume 不新增 generation，才能标为 `Verified-bounded`；台账
必须记录 `50/3,610`、正确率、成本和 run ID。

### 已验证的 50/3,610 结果

本次真实运行的 run ID 为 `run-dde54b4fef884efc84bece74a327c23d`：50 条全部完成、
无失败，Judge 判定正确 36 条，正确率为 `72%`。共执行 50 次 Agent 操作、50 次 Judge
操作，成本为 `$1.7370096`（台账显示约 $1.74）。首次运行后共有 50 条 native generation；
resume 后仍为 50，未发起新生成。此为 50/3,610 的有界结果，不是完整 3,610 条结果，
也不能与原论文完整分数直接等同。

## 运行手册：`dci.bright.earth-science@1.0.0`

这是 Bright Earth Science 的真实 IR 实例，总量 116 条；当前先运行 50 条。它由 Agent
生成检索结果，并按 binary deduplicated nDCG@10 聚合评分，不使用 Judge。每条最多 300 个
Agent 回合、最多 10 路并发；失败时至多再尝试两次，第三次仍失败即 fail closed。

```bash
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci preflight --env-file "$PWD/.env"
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-bright-earth-science-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark lock --instance dci.bright.earth-science@1.0.0 --output "$DCI_SOURCE_LOCK"
ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark plan --instance dci.bright.earth-science@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark run --instance dci.bright.earth-science@1.0.0 --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute | tee "$DCI_RUN_RESULT"
export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"
env -u DEEPSEEK_API_KEY ASTERION_DCI_RESOURCE_ROOT="$PWD" uv run asterion-dci benchmark resume --instance dci.bright.earth-science@1.0.0 --run-id "$DCI_RUN_ID" --case-limit 50 --capability-source-lock "$DCI_SOURCE_LOCK" --evidence-root "$DCI_EVIDENCE_ROOT" --execute
```

只有 run 和 resume 都成功，且 resume 不新增 generation，才能标为 `Verified-bounded`；台账
必须记录 `50/116`、nDCG@10、成本和 run ID。

### 已验证的 50/116 结果

本次真实运行使用 `gpt-5.6-luna` 生成检索结果，不使用 Judge，完成 50/116 条，全部
完成、0 失败。binary deduplicated nDCG@10 为 `0.4014`（精确值
`0.401425292325608`）；Agent 成本约为 $3.46。共创建 50 个 native generation，恰好
对应 50 个评测案例与 50 次计入评测的 Agent 操作。

运行 ID 为 `run-d607f65db6934875bc9b15da930c9814`。随后以相同实例、范围、source
lock 和 evidence root 执行 `benchmark resume`，结果仍为 completed，native generation
数量保持 50，证明 resume 没有新调用 Agent。该结果为 `Verified-bounded`，不是 116 条
完整结果，也不是原论文分数。

## 运行手册：`dci.bcplus.main@1.0.0`

### 作用和边界

这是 BrowseComp-Plus Main 的真实 DCI 实例，总量 830 条。当前阶段处理前 50 条；每条
由研究 Agent 作答，再由独立 Judge 判分。它使用 operator 配置的数据集、corpus、Pi、模型
认证和网络，模型调用会产生费用。

- Application：`dci.complete-application@1.0.0`
- Suite：`dci.bcplus.main@1.0.0`
- 任务：`bcplus.main`
- 当前范围：50/830
- 完整范围：830 条（在所有实例的 50 条版本完成前不执行）
- 每条最多 100 个 Agent 回合，最多 10 路并发（该任务既定执行档案）

### 当前 50 条阶段性评估

先执行 preflight。它只检查外部资源是否就绪，不调用 Agent 或 Judge。

```bash
env -u DEEPSEEK_API_KEY uv run asterion-dci preflight --env-file "$PWD/.env"

export DCI_RUN_ROOT="$PWD/outputs/manual/dci-bcplus-main-stage50-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"

uv run asterion-dci benchmark lock \
  --instance dci.bcplus.main@1.0.0 \
  --output "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark plan \
  --instance dci.bcplus.main@1.0.0 \
  --case-limit 50 \
  --capability-source-lock "$DCI_SOURCE_LOCK"

env -u DEEPSEEK_API_KEY uv run asterion-dci benchmark run \
  --instance dci.bcplus.main@1.0.0 \
  --case-limit 50 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute | tee "$DCI_RUN_RESULT"

export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"
export DCI_SUMMARY="$DCI_EVIDENCE_ROOT/outputs/$DCI_RUN_ID/bcplus.main/summary.json"
jq '{counts,accuracy,totals}' "$DCI_SUMMARY"

env -u DEEPSEEK_API_KEY uv run asterion-dci benchmark resume \
  --instance dci.bcplus.main@1.0.0 \
  --run-id "$DCI_RUN_ID" \
  --case-limit 50 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute
```

`run` 成功后必须显示一个 completed 的 `bcplus.main` 任务，且 `case_count` 为 50。
resume 必须复用同一实例、范围、source lock 和 evidence root，且不得新增 generation。
只有这两步均成功，才把本实例提升为 `Verified-bounded` 并把分数、成本和 run ID 填入表格。

### 已验证的 50/830 结果

本次真实执行使用 `gpt-5.6-luna` 作为 Agent、`deepseek-v4-flash` 作为 Judge。50 个
案例都完成 Agent 运行和独立判分：14 个正确、36 个不正确或未判为正确、0 个失败，准确率
为 28%。Agent 总成本约为 $4.69；Judge 成本为 $0。

运行 ID 为 `run-9bc4c4ec92f44ee8bab0fda79c01ceb4`。随后以相同实例、范围、source lock
和 evidence root 执行 `benchmark resume`，仍返回 completed，且 native-generation 目录
数量保持 50。因此 resume 没有重新调用 Agent 或 Judge。该结果是 `Verified-bounded`，不
是 830 条完整结果，也不是原论文分数。

## 故障排查

- `benchmark source lock is invalid`：必须传入带引号的绝对路径，例如
  `"$PWD/outputs/manual/.../source-lock.json"`，不能使用裸的相对路径
  `FRESH_LOCK`。
- resume 找不到或无法匹配运行：必须使用同一次 `run` 产生的 run ID 和 evidence
  root。历史 run ID 不能在新的空 evidence root 中恢复。
- Judge 返回 401：继承的进程环境变量会覆盖 `.env`。确认项目 `.env` 中的 key
  有效后，以 `env -u DEEPSEEK_API_KEY uv run asterion-dci …` 清除陈旧继承值再运行；
  不要把 key 写入命令行或日志。
- planned 实例被拒绝：实例身份虽然存在，但实现尚未实现。必须同时完成实现和运行
  手册并将其提升为 implemented 后，才能执行 lock、plan 或 run。
