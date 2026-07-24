# Asterion DCI 完整产品参考

本文描述随 `asterion` wheel 发布的 DCI 产品。快速上手见[能力包使用指南](asterion-capability-usage.md)，分层验收见[完整功能验证指南](../verification/asterion-dci-validation-guide.md)。

Asterion DCI 自己拥有研究、产物、恢复、Judge、benchmark、分析和导出实现。它可以独立安装，不导入、启动或打包父工作区的原始 DCI 基线。权威领域实现位于 [`asterion/dci`](../../src/asterion/dci/)。

## 证据状态说明

| 状态 | 含义 |
|---|---|
| **Implemented** | 权威 Asterion 模块中存在生产实现和公开入口。 |
| **Verified** | 指定命令在明确边界内实际通过。 |
| **External-limited** | 边界已实现，但运行依赖外部 Pi、数据、服务或凭据。 |
| **Not rerun** | 实现存在，但本轮没有重跑完整数据集或复现已发表分数。 |

`provider-backed operations` 是 Asterion 调度的 Agent/Judge 操作数，不等于底层多轮模型 API 请求数。

## 配置与依赖

安装和模型外验证只需 Python 3.10+ 与 `uv`：

```bash
uv sync --frozen
uv run asterion list
uv run asterion describe --provider dci-agent-lite
```

外部 Pi 由 `DCI_PI_DIR` 定位，启动器的数据和 corpus 根由 `ASTERION_DCI_RESOURCE_ROOT` 定位。正常配置面是根目录 `.env`：CLI 显式值 > 已导出环境 > `.env` > runtime/Judge 默认值。

```dotenv
DCI_PI_DIR=./pi
DCI_PI_AGENT_DIR=~/.pi/agent
ASTERION_DCI_RESOURCE_ROOT=.
DCI_RUNTIME=pi
DCI_PROVIDER=openai-codex
DCI_MODEL=gpt-5.6-luna
DCI_TOOLS=read,bash
DCI_EVAL_JUDGE_MODEL=
DCI_EVAL_JUDGE_API_KEY_ENV=
```

Pi、corpora、datasets、凭据和运行输出都不进入 wheel/Git。Agent 与 Judge 是独立角色，各自绑定 provider、model、request shape、凭据和 cache identity。实现见 [`config.py`](../../src/asterion/dci/config.py) 和 [`pi_rpc.py`](../../src/asterion/dci/pi_rpc.py)。

新 checkout 的准备路径是：

```bash
make setup-pi
make setup-resources-basic
cp .env.template .env
make doctor
```

全局安装的 `pi` 只可用于管理其自己的登录，不能替代锁定源码 checkout。
`DCI_PI_AGENT_DIR` 将用户认证与 `DCI_PI_DIR` 的可执行来源分离。benchmark
资源使用 `make setup-resources-benchmark`；无法取得的资源会精确失败，不会替换。

## 单次研究、终端与系统提示词

### `run`

`run` 通过受控 JSONL RPC 调用 Pi，流式校验事件并写入可恢复产物：

```bash
uv run asterion-dci run \
  --cwd "$ASTERION_DCI_RESOURCE_ROOT/corpus/wiki_corpus" \
  --tools read,bash \
  --thinking-level high \
  --max-turns 6 \
  "Answer using only the local corpus."
```

`--question-file`、`--system-prompt-file`、`--append-system-prompt-file`、`--show-tools`、`--keep-session`、`--node-max-old-space-size-mb` 和重复 `--extra-arg` 都是显式 argv，不经 shell 解释。校验和运行逻辑见 [`run.py`](../../src/asterion/dci/run.py)。

### `terminal`

```bash
uv run asterion-dci terminal \
  --cwd "$ASTERION_DCI_RESOURCE_ROOT/corpus/wiki_corpus" \
  "Research interactively."
```

`terminal` 只在 stdin/stdout 均为 TTY 时直接启动 Pi，返回子进程退出码。它不创建 RPC 运行目录，也不伪装 resume/Judge 语义。

### `system-prompt`

```bash
uv run asterion-dci system-prompt \
  --system-prompt-file prompts/system_prompt.txt \
  --append-system-prompt-file prompts/local-rules.txt
```

该命令只生成最终系统提示词，不发送模型请求。

## 原生产物、隐私与恢复

私有运行目录包含 question、events、state、完整/处理后 conversation、provenance 和可选 evaluation。公开 CLI/application 结果只投影状态、计数、digest 和 artifact reference，不返回问题、回答、提示词、凭据或私有路径正文。产物实现见 [`artifacts.py`](../../src/asterion/dci/artifacts.py)。

```bash
uv run asterion-dci resume --output-dir path/to/run-directory
```

Resume 要求 failed/incomplete 状态、完整身份兼容和单写者锁。已成功运行、身份漂移或第二写者均失败关闭。可选 conversation 处理控制：

- `--conversation-clear-tool-results`
- `--conversation-clear-tool-results-keep-last`
- `--conversation-externalize-tool-results`
- `--conversation-strip-thinking`
- `--conversation-strip-usage`

完整 conversation 与处理后副本分开保存，防止隐私策略破坏恢复语义。

## Context Management：两个不同层次

1. **Runtime 输入策略**：`level0`–`level4` 是封闭 `dci.context-profile/v1` identity，通过 `--runtime-context-level` 传入安装的 `runtime_context_control` extension。会话必须保留最近用户轮次，要求 summary 时必须真实记录成功/失败。
2. **已保存产物处理**：上述 conversation 开关只改变持久化副本，不声称改变 Pi 模型输入。

Profile/extension digest 进入 run、batch 和 row fingerprint，策略变化不会误用旧缓存。

## Judge、评测与精确缓存

```bash
uv run asterion-dci evaluate \
  --run-dir path/to/run-directory \
  --reference-answer "expected answer"
```

Judge 请求身份绑定最终回答证据、model、API 类型、endpoint、prompt/schema、thinking/store、token limit、超时与价格字段。影响 request shaping 的任一字段变化都会使缓存失效。实现见 [`evaluation.py`](../../src/asterion/dci/evaluation.py)。

Judge 失败不得把 Agent 结果标记为评测成功；取消和 deadline 会终止并等待正在运行的请求。

论文实验契约可在不调用 provider 的情况下检查：

```bash
uv run asterion-dci paper describe
```

该命令描述实验矩阵、ablation、授权边界与预期产物；它不运行论文实验，也不声称复现完整数据集分数。

## Benchmark DCI-Agent-Lite

[`benchmark.py`](../../src/asterion/dci/benchmark.py) 负责有限数据集切片、并发运行、精确 reuse、Judge 缓存、QA/IR 汇总与中断恢复：

```bash
uv run asterion-dci benchmark \
  --profile qa.hotpotqa \
  --dataset "$ASTERION_DCI_RESOURCE_ROOT/data/dci-bench/data/hotpotqa/test.jsonl" \
  --corpus "$ASTERION_DCI_RESOURCE_ROOT/corpus/wiki_corpus" \
  --limit 1
```

Dataset row identity、运行配置、corpus、runtime/Judge request shape 和 implementation digest 共同决定是否可以 reuse。临时文件不是成功输出，缺失/失败行不会被汇总为通过。

历史迁移曾在父工作区执行 original/Asterion 对照。Historical mixed-repository 的 `538/538` selector 和 `12/12` launcher pair 是 **mixed-repository only** 证据，不是当前 standalone acceptance。

## 数据集、Profile 与 Launcher

安装资源包含 14 个 profile：

- BC+：`bcplus.level3`、`bcplus.openai`
- QA：`qa.2wikimultihopqa`、`qa.bamboogle`、`qa.hotpotqa`、`qa.musique`、`qa.nq`、`qa.triviaqa`
- BRIGHT：`bright.biology`、`bright.earth-science`、`bright.economics`、`bright.robotics`
- BEIR：`beir.arguana`、`beir.scifact`

14 个 standalone launcher 位于：

```text
scripts/bcplus_eval/run_L3.sh
scripts/bcplus_eval/run_bcplus_eval_openai.sh
scripts/qa/run_2wikimultihopqa_dev_sample50.sh
scripts/qa/run_bamboogle_test_sample50.sh
scripts/qa/run_hotpotqa_dev_sample50.sh
scripts/qa/run_musique_dev_sample50.sh
scripts/qa/run_nq_test_sample50.sh
scripts/qa/run_triviaqa_test_sample50.sh
scripts/bright/run_bio.sh
scripts/bright/run_earth_science.sh
scripts/bright/run_economics.sh
scripts/bright/run_robotics.sh
scripts/beir/benchmark_arguana.sh
scripts/beir/benchmark_scifact.sh
```

它们都从自身位置解析项目根，通过 `uv run --project "$PROJECT_ROOT"` 运行。数据/corpus 默认位于项目根，也可显式放在 `ASTERION_DCI_RESOURCE_ROOT`。实际运行前必须使用有限 `--limit`。

## 指标、分析、图表与导出

[`analysis.py`](../../src/asterion/dci/analysis.py) 与 `metrics.py` 生成 QA accuracy、IR NDCG、成功/失败计数、运行时间、token/cache/tool 分布、percentile/slice/group 统计、JSON/Markdown 汇总与图表。

```bash
uv run asterion-dci export bcplus --source-dir SOURCE --output-dir OUTPUT
uv run asterion-dci export bright --source-root SOURCE --output-root OUTPUT
uv run asterion-dci export bcplus-qa --parquet-dir SOURCE --output OUTPUT
uv run asterion-dci export resolution \
  --run-dir RUN --attempt 1 --corpus-dir CORPUS \
  --gold-manifest GOLD.json --segment-characters 20000
```

[`export.py`](../../src/asterion/dci/export.py) 实现 BC+ 文档、BRIGHT corpus subset、BC+ QA 与 authoritative resolution 导出。最后一种重算 body-free projection，不盲信已保存公开 summary。

指标/导出为 **Implemented**，单元和集成行为为 **Verified**；完整数据集图表和已发表数值为 **Not rerun**。

## 安装应用与能力包入口

DCI 产品 CLI：

```bash
uv run asterion-dci run --help
uv run asterion-dci benchmark --help
```

通用 framework application runner：

```bash
uv run asterion run \
  --provider dci-agent-lite \
  --application dci.research-capability@1.0.0 \
  --runtime pi.reference \
  --run-id example-run \
  --input "Research the local corpus."
```

Capability manifests 位于 `src/asterion/capabilities/`，application assemblies/provider 位于 `src/asterion/applications/`。安装应用使用同一 native executor，只投影 body-free artifact references。

## 完整验证矩阵

| 验证层 | 命令 | Provider 操作 | 证明内容 | 状态 |
|---|---|---:|---|---|
| Discovery | `uv run asterion list` / `describe` | 0 | 安装 provider/application 元数据 | **Verified** |
| 安装闭包 | `make asterion-verify-acceptance` | 0 | package-owned providers、assemblies、manifests、profiles、inventory | **Verified** |
| 外部准备 | `make asterion-verify-preflight` | 0 | `.env`、Pi、Node、corpus、Judge | **External-limited** |
| 有界基础案例 | `make asterion-verify-basic` | 命令执行前显示 | 有限 Pi/Judge 路径与私有产物 | **External-limited** |
| 综合有界验证 | `make asterion-verify-complete` | 命令执行前显示 | preflight + basic + acceptance | **External-limited** |
| 仓库门禁 | `make check` | 0 | Python/TS/Rust/docs/build | **Verified** |
| 临时复制提升 | `make promotion-check` | 0 | 无父目录的独立构建/验证 | **Verified when command passes** |
| 完整数据集/论文分数 | 独立授权 | 高 | 不属于 promotion gate | **Not rerun** |

关键边界：安装闭包完整性不代表已调用模型；有界功能证据不代表完整数据集复现；historical mixed-repository 对照也不代表当前 standalone live result。
