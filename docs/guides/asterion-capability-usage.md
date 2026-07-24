# Asterion 能力包使用指南（以 DCI 为例）

这份指南回答三个问题：DCI 能做什么、零费用怎样验证安装完整性、何时需要外部 Pi/数据/凭据。详细产品语义见 [Asterion DCI 完整产品参考](asterion-dci-complete-reference.md)，逐项验收见[完整功能验证指南](../verification/asterion-dci-validation-guide.md)。

## 五分钟开始

以下命令都从 standalone 仓库根执行：

```bash
uv sync --frozen
uv run asterion list
uv run asterion describe --provider dci-agent-lite
uv run asterion verify --provider dci-agent-lite --level acceptance
```

这四条命令不调用 Agent/Judge，不运行数据集。`acceptance` 检查 wheel/source 中实际安装的 provider、application、assembly、capability manifests、context profiles、benchmark identities 和 paper scopes。

开发者还可以运行：

```bash
make test
make lint
make docs-check
make check
```

## 最少需要哪些配置

模型外 discovery/acceptance 不需要 `.env`。需要 Pi、Judge 或 benchmark 时，先复制无秘密模板：

```bash
make setup-pi
make setup-resources-basic
cp .env.template .env
make doctor
```

主要边界：

- `DCI_PI_DIR`：由 `pi-revision.txt` 锁定的外部 Pi checkout，默认 `./pi`；全局 `pi` 命令不替代该源码运行时。
- `DCI_PI_AGENT_DIR`：用户自己管理的 Pi agent/auth 目录，默认 `~/.pi/agent`；setup 不复制凭据。
- `ASTERION_DCI_RESOURCE_ROOT`：启动器使用的外部 datasets/corpora 根。
- `DCI_RUNTIME`、`DCI_PROVIDER`、`DCI_MODEL`：缺省为 `pi`、`openai-codex`、`gpt-5.6-luna`。
- `DCI_EVAL_JUDGE_*`：独立 Judge 角色的 endpoint、API、model、密钥变量名和 request shape。
- `.env` 和已导出环境只提供配置，不会自动授权模型请求或完整数据集。

凭据只保存在 `.env`、已导出环境或 Pi 自己的受管认证中。Asterion 不在描述、错误、公开证据或 body-free application 结果中输出密钥值。

`make setup-resources-basic` 只准备 `wiki_corpus` 和 `bc_plus_docs`。
`make setup-resources-benchmark` 另行检查/准备 launcher 清单；无法自动取得的
BEIR 或 gated 资源会报告精确路径与来源，不会换成其他数据。所有 setup/check
命令都是 0 Agent、0 Judge，且不执行数据集。

## 查看能力：`list` 与 `describe`

```bash
uv run asterion list
uv run asterion describe --provider dci-agent-lite
uv run asterion describe --provider dci-agent-lite --json
```

`list` 是纯元数据发现，不加载 provider。`describe` 只加载被精确选择的 provider，列出 application、assembly、命令、配置、验证级别与费用边界。

## 四种验证级别

### `preflight`：只检查外部准备

```bash
uv run asterion verify \
  --provider dci-agent-lite \
  --level preflight \
  --env-file .env \
  --corpus-root "$ASTERION_DCI_RESOURCE_ROOT/corpus"
```

检查 `.env`、Pi/Node、corpus 和 Judge 配置；Agent/Judge 操作均为 0。成功只表示 ready，不表示已执行。

### `acceptance`：已安装产品闭包

```bash
uv run asterion verify \
  --provider dci-agent-lite \
  --level acceptance
```

该级别为 package-owned，在源码和 isolated wheel 中都可运行。它忽略邻接源码树，不依赖父工作区 verifier，provider-backed operations 固定为 0。

### `basic`：有界 Agent/Judge 案例

```bash
uv run asterion verify \
  --provider dci-agent-lite \
  --level basic \
  --env-file .env \
  --corpus-root "$ASTERION_DCI_RESOURCE_ROOT/corpus" \
  --output-root "$PWD/outputs/asterion-verification"
```

运行前确认 `describe` 报告的有界操作数。每个 Agent 案例有有限轮数，一次 Agent 操作可能包含多次底层 API 请求。它不运行完整数据集。

### `complete`：有界路径加安装闭包

```bash
uv run asterion verify \
  --provider dci-agent-lite \
  --level complete \
  --env-file .env \
  --corpus-root "$ASTERION_DCI_RESOURCE_ROOT/corpus" \
  --output-root "$PWD/outputs/asterion-verification"
```

顺序为 `preflight → basic → acceptance`，前一步失败就停止。它仍必须报告 `Full dataset ran: no`。

对应 Make 入口：

```bash
make asterion-verify-preflight
make asterion-verify-basic
make asterion-verify-acceptance
make asterion-verify-complete
```

## DCI 产品命令

```bash
uv run asterion-dci system-prompt --help
uv run asterion-dci run --help
uv run asterion-dci terminal --help
uv run asterion-dci resume --help
uv run asterion-dci evaluate --help
uv run asterion-dci benchmark --help
uv run asterion-dci export --help
uv run asterion-dci ablation --help
uv run asterion-dci paper --help
```

| 功能 | 主入口 | 验证重点 |
|---|---|---|
| 本地语料研究 | `asterion-dci run` | 有限 turns、受控 cwd、可恢复产物 |
| 交互终端 | `asterion-dci terminal` | TTY-only、退出码传递、不伪造 RPC 产物 |
| 中断恢复 | `asterion-dci resume` | failed/incomplete、identity 兼容、单写者 |
| Judge 评测 | `asterion-dci evaluate` | 精确 request/cache identity、body-free 结果 |
| QA/IR/BC+/BRIGHT/BEIR | `asterion-dci benchmark --profile ... --limit 1` | 有限 rows、并发、reuse、汇总 |
| 导出与分析 | `asterion-dci export ...` | 临时文件安全、authoritative reanalysis |
| 通用安装应用 | `asterion run --provider dci-agent-lite ...` | 精确 application/runtime 选择与 body-free projection |

## 费用与完整数据集边界

| 级别/命令 | Agent | Judge | 完整数据集 |
|---|---:|---:|---|
| `list` / `describe` / `acceptance` | 0 | 0 | 否 |
| `preflight` | 0 | 0 | 否 |
| `basic` | 有界，执行前显示 | 有界，执行前显示 | 否 |
| `complete` | 有界，执行前显示 | 有界，执行前显示 | 否 |
| benchmark full/paper score | 需独立授权 | 需独立授权 | 可能，默认禁止 |

零费用验证只用 `acceptance`、`make check` 或 `make promotion-check`。`.env`、缓存或历史报告不能隐式授权新请求。

## 产物与隐私

`basic`、`complete`和直接产品运行在操作者选择的私有输出根下创建产物。其中可包含 `state.json`、`events.jsonl`、完整/处理后 conversation、final 文本和 protocol 记录。

公开输出的 `artifact_refs` 只是安全角色引用，不包含回答正文、对话、provider 响应、密钥或本机绝对路径。

## 常见问题

- `environment` 失败：执行 `cp .env.template .env`；不要在日志中打印密钥。
- `pi-checkout/built-pi-cli` 失败：执行 `make setup-pi`；不要 vendoring 外部 checkout。
- `agent-authentication` 失败：完成 Pi 登录并设置 `DCI_PI_AGENT_DIR`。
- `resources-basic` 失败：执行 `make setup-resources-basic`；不要把资源放进 wheel。
- Judge 重跑：任何 request-shaping 配置变化都应使精确缓存失效。
- `acceptance` 失败：它是安装包闭包错误，不要指向父工作区或改为 `NOT RUN`。
- 需要 original/Asterion selector 对照时，该证据属于 historical **mixed-repository only** 集成，不是 standalone live acceptance。
