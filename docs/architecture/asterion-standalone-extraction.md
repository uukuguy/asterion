# Asterion 独立项目拆分指南

本文给出把 Asterion 从当前 DCI-Agent-Lite 工作区独立成新项目的实施蓝图。目标不是立即搬目录，而是先固定可复制的产品边界、依赖边界和发布门禁，使拆分过程始终可验证、可回退。

本文严格区分两种命令上下文：**current mixed-repository root** 是当前
DCI-Agent-Lite 仓库根；**standalone repository root after promotion** 是把当前
`asterion/` 子树内容提升后的新仓库根。拆分时要 **promote the contents of `asterion/`**，
而不是把整个目录再嵌套成 `asterion/asterion/`。

当前结论是：Asterion 的核心框架、两个能力应用、DCI 产品实现、协议 schema、TypeScript runtime 包和 Rust controlled executor 都已有明确源码；但运行 DCI 仍需要外部 Pi、语料、数据集和模型凭据。因此“项目源码自包含”不等于“所有外部运行资源内嵌”。

## 当前自包含清单

以下内容应被视为 Asterion 独立项目的初始产品资产：

- Python 发行物：`asterion`，生成 `asterion` wheel，包含框架、adapter、runtime、能力、应用、DCI 产品和两个 CLI。
- Runtime Protocol schemas：`schemas/agent-runtime/v1`。
- Package、assembly 与 executor schemas：`schemas/packages/v1`、`schemas/assembly/v1`、`schemas/executor/v1`。
- TypeScript 包：`packages/typescript/asterion-runtime`，当前 npm 名为 `@dci/agent-runtime`；拆分前应单独决定是否改名。
- Rust 包：`packages/rust/controlled-executor`，当前 crate 名为 `dci-controlled-executor`；拆分前同样单独决定发布名。
- 跨语言协议 fixtures：`tests/fixtures`。
- Python 单元、集成、distribution 与文档契约测试：`tests/test_asterion_*` 以及它们实际导入的公共 fixtures/helpers。
- Asterion benchmark launchers：`scripts`；它们是 DCI 产品资源的项目入口，不是框架核心。
- Asterion 产品文档：当前 `docs` 下的 architecture、guides、verification 和 operator 子目录。
- 构建和常用入口：根 `Makefile` 中的 `asterion-*` targets，以及 `.env.template` 中 Asterion/DCI 需要的非秘密配置说明。

迁出时不能笼统复制整个 `tests/`、`docs/` 或 `scripts/`。先用 import、链接和命令引用确定闭包，再复制闭包；这样既不会漏 fixture，也不会把原 DCI 的历史状态系统当作产品内容带走。

## 外部依赖与明确排除项

独立仓库默认不复制以下内容：

- 外部 `pi/` checkout：它是独立 Git 仓库，通过 `DCI_PI_DIR` 或缺省 `./pi` 接入。
- corpora 与 benchmark datasets：体积大、来源和许可独立；新项目只保留路径配置、下载说明或极小合法 fixture。
- credentials 与 `.env`：只迁移无秘密的 `.env.template`，绝不复制本地 `.env` 或打印 key。
- 运行输出与评测 artifacts：`outputs/`、接受测试临时目录、Judge cache 和用户研究产物不进入源码发行。
- `.worktrees/`：这是临时工作树，不是文档、源码或发布资产。
- mixed-repository dependency `src/dci`：它是父工作区中的原始 DCI 参考实现；Asterion 的权威实现已经位于 wheel 内的 `asterion/dci`，不能同时复制两套实现。
- Python/Node/Rust 构建缓存：`.venv`、`node_modules`、`target`、`dist`、`__pycache__`。
- mixed-repository status/worklist 与协作 memory：这些描述父工作区的迁移项目，不是新 Asterion 产品的历史；新仓库初始化自己的状态文件。

新项目需要在 README 明确这些外部依赖及失败方式。没有 Pi 或凭据时，框架 discovery、文档、schema、unit、provider-free acceptance 仍应运行；需要模型调用的命令必须 preflight 后清晰停止。

## 目标目录树

第一版独立仓库建议保持当前 monorepo 的语言分区，避免拆分同时重写构建系统：

```text
standalone-repository-root/
├── README.md
├── LICENSE
├── Makefile
├── pyproject.toml                 # uv workspace，仅含独立项目成员
├── .env.template
├── src/asterion/
├── packages/
│   ├── typescript/asterion-runtime/
│   └── rust/controlled-executor/
├── schemas/
│   ├── agent-runtime/v1/
│   ├── assembly/v1/
│   ├── packages/v1/
│   └── executor/v1/
├── tests/
│   ├── fixtures/
│   └── test_asterion_*.py
├── scripts/
└── docs/
    ├── README.md
    ├── architecture/
    ├── guides/
    ├── verification/
    └── operator/
```

最初保留一个 Python wheel 是降低拆分风险的关键。框架和内置应用可以在源码中保持清晰边界，而不必在第一天就引入多个 distribution 的版本、兼容矩阵和发布流水线。

## 迁移映射表

| 当前路径 | 独立仓库路径 | 处理 | 验证重点 |
|---|---|---|---|
| `asterion/` 的内容 | 新仓库根 `./` | 提升内容，不保留外层目录 | build、wheel 内容、isolated wheel |
| `asterion/schemas/*` | `schemas/*` | 原样迁移 | Python、TS、Rust 消费同一版本 |
| `asterion/packages/typescript/asterion-runtime` | `packages/typescript/asterion-runtime` | 排除 `node_modules/dist` | `npm test`、schema copy |
| `asterion/packages/rust/controlled-executor` | `packages/rust/controlled-executor` | 排除 `target` | `cargo test`、协议 fixture |
| `asterion/tests/fixtures` | `tests/fixtures` | 复制实际使用闭包 | 跨语言正反例一致 |
| `asterion/tests/` | `tests/` | 原样提升项目测试 | provider-free 全通过 |
| `asterion/scripts` | `scripts` | 随 DCI 产品迁移 | 14 standalone launcher |
| `asterion/docs` | `docs/` | 原样提升并重写 mixed-root 链接 | 本地链接检查 |
| 根 `Makefile` | 根 `Makefile` | 只保留 Asterion targets | 命令与帮助一致 |
| `.env.template` | `.env.template` | 只保留说明和值为空的配置 | 不含 secret |
| 顶层 `applications/` | 初期不复制 | wheel 已有权威 provider/assembly | 无运行引用后删除歧义 |
| 顶层 `capabilities/` | 初期不复制 | wheel 已有权威 capability | 不制造空产品目录 |
| mixed-repository 原 DCI `src/dci` | 不复制 | 仅保留在父工作区作为迁移基线 | Asterion 禁止 import |

## Phase 1：冻结边界与基线

1. 记录源提交、Python/Node/Rust 版本以及 538 个 selector 的 historical mixed-repository 基线证据。
2. 在源仓库运行 scope、文档契约、Python 全量测试、Ruff、compile 和 `git diff --check`。
3. 构建 wheel 并记录其文件清单；搜索 wheel 源码对 `src/dci`、顶层 `applications/`、顶层 `capabilities/` 和仓库绝对路径的引用。
4. 运行当前 provider-free acceptance，保存仅包含计数和版本、不含凭据的报告。
5. 给源提交打迁移基线 tag 或记录不可变 commit SHA；发现失败时先在源仓库修复，再开始复制。

本阶段不改包名、不移动 DCI、不删兼容目录。冻结的是可比较的行为基线，而不是宣布外部 benchmark 已重跑。

## Phase 2：建立独立仓库骨架

1. 创建空仓库、许可证、README、忽略规则和最小 uv workspace。
2. 建立上面的目标目录，但不创建无构建清单的“独立能力包”目录。
3. 初始化独立 CI：Python 版本矩阵、Node 22.19.0+、Rust stable，缓存仅用于依赖。
4. 建立 secret scanning、wheel/sdist 内容检查和本地 Markdown link check。
5. 写新项目自己的状态与贡献规则，不能携带 mixed-repository status 历史冒充产品文档。

骨架提交应能在没有 Pi、数据集和 API key 的干净环境完成配置检查。

## Phase 3：迁移 Python 发行物

1. 把当前 `asterion/` 的内容提升为新仓库根，保持 import 路径和 entry points 不变；后续本 phase 命令都从该 standalone 根运行。
2. 复制 Python 测试闭包与 fixtures，逐项去除指向原仓库的相对路径假设。
3. 调整根 workspace 和 Make targets，使安装只依赖新仓库文件。
4. 执行：

   ```bash
   uv sync --frozen
   uv run python -m unittest discover -v
   uv run ruff check src tests
   uv build .
   ```

5. 在临时目录创建 venv，只安装生成的 wheel；确保 `asterion list`、`asterion-dci --help` 和 provider-free 验证不依赖 source checkout。

Python 迁移完成的定义是 isolated wheel 可用，而不是源目录内 `uv run` 恰好通过。

## Phase 4：迁移协议与跨语言包

1. 复制所有 `schemas` 和被测试引用的 `tests/fixtures`。
2. 复制 `packages/typescript/asterion-runtime`，删除构建产物并修正 schema copy 的相对路径。
3. 复制 `packages/rust/controlled-executor`，删除 `target` 并修正 schema/fixture 路径。
4. 在各自目录执行：

   ```bash
   npm test
   cargo test
   ```

5. 增加协议漂移门禁：三种语言消费同一 schema 版本；正例都接受，反例都拒绝。

包的公开名称变更不与文件复制混在同一提交。如果需要从 `@dci/agent-runtime` 或 `dci-controlled-executor` 改名，应另开兼容性决策和迁移周期。

## Phase 5：迁移 DCI 产品与应用

初始策略是 **keep DCI bundled initially**：保留 `asterion/dci`、`dci_research` capability、`dci_agent_lite` provider、`asterion-dci` entry point、资源 profile 和 `scripts`。原因是当前完整产品验证、resource packaging 和应用绑定都在同一个 wheel 中有证据；在拆仓同时拆 distribution 会让问题来源不可区分。

迁移步骤：

1. 复制 DCI 代码和内置 resources，确认 wheel 文件清单包含 JSON、prompt 和其它运行资源。
2. 复制 14 个 Asterion launcher，并确认它们调用 `asterion-dci`，不回退到旧 `src/dci`。
3. 迁移 `.env.template` 的 `DCI_PI_DIR`、provider/model、语料、输出和 Judge 配置说明，不复制值。
4. 检查缺省 Pi 路径规则：优先 `./pi`，`./pi-mono` 仅为兼容 fallback。
5. 运行 provider discovery、product describe 和 provider-free acceptance；有凭据时再运行 bounded Pi examples，且在输出前显示 operation count。

完整数据集 benchmark 不属于拆仓的默认门禁。它是昂贵、外部依赖的发布候选验证，必须显式授权并记录数据版本、模型、Judge、缓存身份和成本。

## Phase 6：隔离安装与发布验证

发布候选必须从构建产物验证：

```bash
uv build .
asterion list
asterion verify --provider dci-agent-lite --level acceptance
make check
make promotion-check
make asterion-verify-basic
```

具体门禁：

1. sdist/wheel 不含 secret、缓存、外部 checkout、绝对路径和原 DCI 源码。
2. isolated wheel 环境中两个 entry point、两个内置 provider、assembly JSON 和 capability manifests 可发现。
3. provider-free acceptance 的 provider-backed operation count 为零。
4. `make asterion-verify-basic` 只运行明确显示数量的 bounded Pi examples；没有凭据时以可操作 preflight 失败，不静默跳过。
5. TypeScript `npm test`、Rust `cargo test` 与 Python schema tests 使用同一组协议 fixtures。
6. 文档链接、示例 argv 和 `.env.template` 变量与 CLI help 一致。
7. 在临时目录、不同当前工作目录以及没有原仓库存在的机器上重复 smoke。

只有这些门禁通过后，才能发布版本或把原仓库切换到依赖新 Asterion release。

## Phase 7：切换与清理

1. 先发布预发布版本；原 DCI-Agent-Lite 仓库固定依赖该精确版本或 commit artifact。
2. 在原仓库运行相同 provider-free 和 bounded examples，对比结构化输出与 artifact schema。
3. 至少保留一个发布周期的回退路径，然后删除原仓库中已迁出的 Asterion 副本。
4. 顶层兼容 host 只有在 `rg` 证明没有构建、测试、文档或用户入口依赖后才能删除。
5. 更新两边 README：Asterion 仓库讲框架和能力产品；原仓库讲上游 DCI 基线、历史与对新包的依赖。
6. 最后才调整远程 CI、release token、包索引和版本发布自动化。

切换提交必须是可逆的小步，禁止把复制、改名、删除旧实现和发布配置合成一个不可审查的大提交。

## DCI 打包决策门

DCI 未来是否从核心 wheel 拆成独立 plugin，不由目录美观决定，而由 **separately versioned plugin decision gate** 决定。只有同时回答下面问题后才启动：

- DCI 是否需要与框架不同的发布节奏和兼容窗口？
- DCI 的重型依赖是否显著影响不使用 DCI 的框架用户？
- installed provider protocol 是否已足够稳定，能跨 distribution 保持兼容？
- 独立 plugin 能否自带 manifests、assemblies、resources、`asterion-dci` CLI 和验证器？
- 核心仓库是否有真实的第三方 provider 证明接口不是只为 DCI 定制？
- 是否有 core/plugin 版本兼容矩阵、升级策略和两个 isolated-wheel 测试？

若答案不完整，继续单 wheel、内部清晰分层。通过决策门后，建议形成 `asterion-core`、`asterion-dci` 两个发行物；后者依赖前者并注册 `dci-agent-lite` provider，core 不 import plugin。

## 发布门禁

独立项目首个正式版本至少满足：

- 源提交与迁移映射可追溯，许可和第三方依赖清单完整。
- Python 全量测试、compile、Ruff、build、sdist/wheel 内容检查通过。
- isolated wheel 的 `asterion list/describe/verify/run` provider-free 路径通过。
- DCI 产品 CLI help、单元测试和 14 个 standalone launcher 通过；historical mixed-repository 基线中的 12/12 launcher pair 和 538/538 delegated selector 不是当前 standalone 验收。
- TypeScript build/test 和 Rust build/test 通过，无缓存或本机路径进入包。
- 受控 executor 的策略、取消、deadline 和进程清理测试通过。
- 完整文档可从 `docs/README.md` 找到，所有本地链接有效。
- `.env.template` 不含 secret，preflight 不显示 secret 值。
- 若执行了 bounded/provider/full-dataset 验证，报告明确数据、模型、请求数量和证据级别；未运行的结果标为 Not rerun。

## 回滚方案

每个 phase 都产生一个可验证 checkpoint。任何门禁失败时：

1. 停止切换，不删除源仓库文件，也不发布稳定版本。
2. 用记录的源 SHA 重建基线，判断失败来自复制遗漏、路径假设还是有意变更。
3. 修复只落在当前 phase；若协议或公共 API 必须变化，先写决策记录和兼容方案。
4. 已发布预发布包则撤销推荐渠道或发布修复版本，不覆盖同一版本内容。
5. 原仓库依赖保持在最后一个通过版本；外部 Pi、数据和 credentials 不需要迁回，因为它们从未被搬走。

回滚的成功标准是恢复到基线命令可运行，而不是把 working tree 强制重置并丢弃未知用户改动。

## 风险与非目标

主要风险：资源文件未进入 wheel、源码树相对路径泄漏、三种语言 schema 漂移、provider discovery 意外 import 全部插件、旧 DCI 与新实现双写、拆包后版本不兼容、文档仍指向原仓库、外部验证被误写成完整 benchmark 复现。

本拆分不以以下事项为目标：

- 不在搬仓时重写框架协议或业务行为。
- 不把 Pi vendoring 进 Asterion，也不修改外部 Pi 仓库。
- 不把语料、完整数据集、模型凭据或历史输出纳入 Git。
- 不承诺重新复现论文或上游 benchmark 分数。
- 不因顶层目录名称而立即拆成多个 Python distributions。
- 不把 Claude Code 变成 DCI 缺省运行时；缺省仍是 Pi。
- 不删除原始 DCI，直到新项目发行物在原仓库完成对照切换并保留回退窗口。

按此方案执行后，新 Asterion 仓库会拥有可构建、可安装、可发现、可验证的产品闭包；原 DCI-Agent-Lite 则保留为明确的上游基线和迁移来源，而不是继续承载两套权威实现。
