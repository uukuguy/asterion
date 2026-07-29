# Asterion DCI 完整产品参考

DCI 是 Asterion 通用 capability package 与 benchmark subsystem 的参考产品，不是
framework 的依赖。权威领域实现位于
[`asterion.capabilities.dci`](../../src/asterion/capabilities/dci/)，应用和 operator
适配位于
[`asterion.applications.dci_agent_lite`](../../src/asterion/applications/dci_agent_lite/)。
快速上手见[能力包使用指南](asterion-capability-usage.md)，验收步骤见
[功能验证指南](../verification/asterion-dci-validation-guide.md)。

## 证据状态

| 状态 | 含义 |
|---|---|
| **Implemented** | 生产代码和入口存在。 |
| **Verified** | 指定命令在声明边界内通过。 |
| **External-limited** | 接口完整，但执行依赖外部数据、服务、凭据或授权。 |
| **Not rerun** | 本轮没有运行完整数据集或复现已发表分数。 |

安装、list、describe、acceptance、benchmark plan 和仓库 gate 都是 provider-free。
`basic`、`complete` 和显式 benchmark execution 可能调用 Agent/Judge。

## 安装与外部依赖

```bash
uv sync --frozen
make setup-pi
make setup-resources-basic
cp .env.template .env
make doctor
```

锁定的 Pi checkout 由 `DCI_PI_DIR` 定位，认证目录由 `DCI_PI_AGENT_DIR` 定位。
`ASTERION_DCI_RESOURCE_ROOT` 只是 operator-owned 数据与 corpus 的根。Pi、数据、
凭据、运行输出和 private evidence 都不进入 wheel 或 Git。

`make doctor`/`preflight` 只检查 readiness，不授予执行权限。路径、命令、环境值、
prompt、凭据、provider 配置和 mutable state 都不能进入 capability 或 suite manifest。

## 应用适配器

`asterion-dci` 是薄应用适配器，支持：

```bash
uv run asterion-dci list
uv run asterion-dci describe
uv run asterion-dci preflight
uv run asterion-dci basic
uv run asterion-dci complete
uv run asterion-dci run --help
uv run asterion-dci benchmark --help
```

适配器固定 `dci.complete-application@1.0.0`，只负责 DCI 参数别名、operator
配置翻译、host-service preflight 和通用 host delegation。它不组合 package、
解析 suite、运行 task loop、发现 source、持久化证据或启动进程。

## Capability package

DCI 的 portable package identity 是 `dci@1.0.0`。package 自己拥有 capability
manifest、suite、资源、实现 binding 和 conformance assets；通用 framework 不导入
DCI 模块。

三个精确 suite 是：

- `dci.github@1.0.0`：12 个 GitHub-reference task。
- `dci.paper-main@1.0.0`：13 个 paper-main task。
- `dci.all@1.0.0`：两者的 15-task 规范并集。

GitHub Bamboogle 50-case sample 与 paper-main Bamboogle 125-case contract 是不同
task identity。每个 task 都由 package-owned Python binding 解析私有 operator 输入；
仓库不保留逐任务 shell 入口。

## Benchmark plan

默认 DCI plan 是 provider-free、不可变且 body-free：

```bash
uv run asterion-dci benchmark plan --case-limit 1
```

通用入口等价地显式命名应用和 suite：

```bash
uv run asterion benchmark plan \
  --application dci.complete-application@1.0.0 \
  --suite dci.all@1.0.0 \
  --case-limit 1
```

plan 不创建 evidence、不加载 capability implementation provider、不调用
Agent/Judge，也不读取完整数据集。`--case-limit 1` 对 suite 中每个 task 生效。

## Benchmark execution 与恢复

只有 embedding operator host 可以提供显式 authority、精确 source lock、实现、
executor、取消信号、output directory factory 和 private evidence service。通用
benchmark run 命令形状是：

```bash
uv run asterion-dci benchmark run \
  --case-limit 1 \
  --capability-source-lock "$OPERATOR_SELECTED_SOURCE_LOCK" \
  --evidence-root "$OPERATOR_SELECTED_PRIVATE_EVIDENCE_ROOT" \
  --execute
```

普通安装 CLI 故意不提供 execution authority。`--execute`、source lock 和 evidence
root 缺一即在 implementation load 前失败。凭据、配置、cache、已有输出、旧 plan 或旧
evidence 都不能隐式授权新执行。

恢复使用相同 application、suite、case limit 和 source identity，并额外要求兼容 run ID：

```bash
uv run asterion-dci benchmark resume \
  --run-id "$COMPATIBLE_RUN_ID" \
  --case-limit 1 \
  --capability-source-lock "$OPERATOR_SELECTED_SOURCE_LOCK" \
  --evidence-root "$OPERATOR_SELECTED_PRIVATE_EVIDENCE_ROOT" \
  --execute
```

task 按 suite 顺序串行运行，首次失败或取消后停止。证据是 immutable、mode-restricted
且私有的；公开结果只包含安全 identity、状态、计数、digest 和 opaque artifact
reference，不包含 prompt、answer、corpus text、provider payload、raw output、凭据或
私有路径。

## 成本与论文边界

完整数据集、paper score reproduction 和 publication 需要独立治理与有限预算，不由普通
benchmark plan/run 隐式授权。金额只是可选 operator metadata；`amount=None` 合法，
既不提示用户输入也不阻塞 plan 或执行。

有界 execution interface 的状态是 **External-limited**。它不能把有限 case 结果提升为
完整论文复现或已发表分数验证。provider-free 验证使用：

```bash
make test
make lint
make docs-check
make check
make promotion-check
```

`promotion-check` 在临时 standalone copy 中验证 wheel、entry points、schemas 和资源闭包；
它不运行 provider 或完整数据集。
