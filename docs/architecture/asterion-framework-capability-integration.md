# Asterion 框架与能力包接入指南

本文解释 Asterion 的框架分层、当前仓库中每类目录的职责，以及一个新能力如何从声明走到可安装、可发现、可执行和可验证。它描述的是当前代码的真实边界，不把仓库中的参考副本误认为独立发行物。

相关源码入口：

- [Runtime](../../src/asterion/runtime/)
- [Package](../../src/asterion/packages/)
- [Assembly](../../src/asterion/assembly/)
- [Runner](../../src/asterion/runner/)
- [Installed provider contract](../../src/asterion/applications/provider.py)

## 当前仓库与权威目录

当前 Python 发行物是根 `pyproject.toml` 定义的 `asterion` wheel。wheel 打包 `src/asterion`，因此下面这些目录才是运行时权威实现：

```text
standalone-repository-root/
├── pyproject.toml
└── src/asterion/
    ├── runtime/                 # 运行时中立协议、host client、factory
    ├── runtimes/                # Pi、Claude Code 等具体 adapter
    ├── packages/                # package manifest、catalog、组合与执行契约
    ├── capabilities/            # 能力实现及其 package manifests
    ├── assembly/                # application 静态装配协议与解析
    ├── applications/            # installed provider 与内置应用装配
    ├── runner/                  # 已解析 application 的执行器
    ├── dci/                     # DCI 产品实现与专用 CLI
    └── cli.py                   # 通用 asterion CLI
```

其中两个最容易混淆的路径是：

- `src/asterion/capabilities/` 是能力实现与 manifest 的权威 Python 路径。
- `src/asterion/applications/` 是 installed provider 和 assembly 的权威 Python 路径。

父工作区已不再保留旧的 `applications/` 或 `capabilities/` 产品目录；Asterion 项目内的 `src/asterion/applications/` 与 `src/asterion/capabilities/` 是唯一权威实现。父工作区的 `src/dci` 仅是原始 DCI 对照基线，不是 standalone Asterion 产品或运行依赖。

## 依赖方向

依赖应保持单向：

```text
CLI / 外部宿主
       │ 精确选择 provider、application、runtime
       ▼
Application Provider ──► Assembly ──► Package Catalog
       │                    │              │
       │ implementation     │ resolved     │ manifests
       ▼                    ▼              ▼
Capability Implementation ───────► Composed Runner
       │                                  │
       │ RunRequest / RunEvent            │ host services
       ▼                                  ▼
AgentRuntimeClient ◄──────────── Runtime Factory / Adapter
```

框架层只认识协议对象、声明和注入的实现。具体产品依赖框架；框架不反向依赖具体产品。尤其是通用 `asterion` 永远不能导入 `src/dci` 来发现 DCI，也不能通过扫描源码目录猜测能力。DCI 通过正常的 application entry point 进入框架；`asterion-dci` 才是面向 DCI 用户的产品 CLI。

## Runtime Protocol、Factory 与 Runtime

Runtime 层回答“哪一个 coding agent 真正执行请求”。公共边界在 `runtime/host.py`：

- `RuntimeManifest` 声明 `runtime_id` 和已支持能力；
- `RunRequest` 携带 `run_id`、文本输入、请求能力和可选 deadline；
- `RunEvent` 是顺序化、可验证的标准事件；
- `AgentRuntimeClient` 是异步协议，提供 `manifest` 和 `run()`；
- `CancellationSignal` 由调用方持有，runtime 只能读取取消状态。

`RuntimeFactoryRegistry` 不做模糊匹配。它以精确 `runtime_id` 选择 `RuntimeFactoryBinding`，再把 `provider_id`、application 身份、assembly 路径与 host options 放进 `RuntimeFactoryContext`。工厂创建的 client manifest 必须与 assembly 的 `runtime_id` 一致。

当前参考 runtime 包括 `pi.reference` 和 `claude-code.reference`。这表示 Asterion 是多 runtime 框架，不表示 DCI 的缺省运行时发生变化：DCI 产品的缺省外部执行依然是 Pi；Claude Code 只是显式选择时可用的另一 adapter。

## Adapter 与标准化边界

Adapter 把外部 agent 的命令、事件和错误转成 Runtime Protocol；它不拥有产品语义。边界规则如下：

1. 外部命令参数只在对应 adapter 内构造。
2. 原始事件必须先校验，再投影为递增 sequence 的 `RunEvent`。
3. runtime 身份、run 身份或事件流不一致时安全失败，不能猜测或补造。
4. 密钥仍由环境或外部工具读取，不进入 manifest、assembly 或 artifact。
5. adapter 不发现 package，也不决定 application 中执行哪些能力。

因此新增一种 coding agent，通常是新增 runtime adapter 与 factory binding；新增一种业务能力，则是新增 package manifest、实现 binding 和 application assembly。两者是正交扩展点。

## Package、Capability 与实现绑定

Package manifest 使用封闭的 `dci.package/v1` 协议。每个 JSON 必须且只能包含：

```json
{
  "protocol": "dci.package/v1",
  "package_id": "example.research",
  "version": "1.0.0",
  "kind": "capability",
  "provides_capabilities": ["research.local"],
  "requires_capabilities": ["agent.run"],
  "requires_policies": ["example.policy"],
  "emits_events": ["research.completed"],
  "consumes_events": [],
  "produces_artifacts": ["application/vnd.example.research+json"],
  "consumes_artifacts": []
}
```

数组必须排序、去重；ID 和版本必须符合约束。`kind=policy` 可以参与组合但不执行；`capability`、`workflow`、`memory`、`observability`、`evaluation` 必须有精确 implementation binding。

Capability 是“声明 + 实现”，不是一个任意 Python 目录。实现遵守 `PackageImplementation.execute(invocation)`，接收冻结后的 `PackageInvocation`，返回 `PackageExecutionResult`。结果只能产生 manifest 已声明的事件和 artifact media type；未声明输出、重复 artifact ID、缺失或多余 binding 都会失败。

组合器根据 provides/requires、policy、event 与 artifact 边构造确定性顺序。能力提供者冲突、依赖缺失或循环不会在运行中临时解决，而是在 assembly resolve 阶段拒绝。

## Application、Assembly 与 Provider

Application 是一组已固定版本 package、一个 runtime 身份以及 host 边界的静态装配。`dci.assembly/v1` 只引用 package 身份，不嵌入 Python 对象。例如：

```json
{
  "protocol": "dci.assembly/v1",
  "application_id": "example.research-app",
  "version": "1.0.0",
  "runtime_id": "pi.reference",
  "packages": [
    {"package_id": "example.observability", "version": "1.0.0"},
    {"package_id": "example.policy", "version": "1.0.0"},
    {"package_id": "example.research", "version": "1.0.0"}
  ],
  "host_capabilities": [],
  "host_policies": [],
  "host_events": [],
  "host_artifacts": []
}
```

`InstalledApplicationProvider` 把只含数据的 assembly/catalog 与 Python implementation binding 连接起来。provider 还声明允许的 runtime IDs，并可附加一个面向 CLI 的 capability product 描述和验证器。

发行物通过 `asterion.applications` entry-point group 注册 provider。`asterion list` 只读取 entry-point 元数据，不导入 provider 代码。执行时必须显式给出 `--provider`；loader 只加载被精确选择的 provider，不会加载相邻 provider。重复 ID、缺失 ID、provider 自报身份不符、资源逃逸 `resource_root`、symlink 或 assembly 身份不一致都会拒绝。

这里的三个身份不要混用：

- provider ID：一个发行物暴露的装配提供者，例如 `dci-agent-lite`；
- application identity：例如 `example.research-app@1.0.0`；
- package identity：例如 `example.research@1.0.0`。

## Host Service 与受控执行

Host service 是 application 明确要求、由宿主在执行时注入的能力，不能由 package 自行从全局变量中发现。assembly 的 `host_capabilities` 会在 preflight 中逐一检查；缺一项就不执行。

现有 controlled-code 应用使用 `executor.controlled`。通用 CLI 只有在提供受控执行配置后才建立 managed executor，并通过：

```python
host_services={"executor.controlled": executor}
```

传入 runner。package 只拿到只读映射。这样策略、进程执行和取消生命周期归宿主持有，能力实现不能绕开安全边界启动未受控流程。

## 通用 CLI 与产品 CLI

安装 wheel 后有两个入口：

```bash
# 框架：发现、描述、验证或运行 installed application
uv run asterion list
uv run asterion list --provider dci-agent-lite
uv run asterion describe --provider dci-agent-lite
uv run asterion verify --provider dci-agent-lite --level acceptance
uv run asterion run --provider dci-agent-lite \
  --application dci.research-capability@1.0.0 \
  --runtime pi.reference \
  --run-id example-001 \
  --input "基于本地语料回答问题"

# DCI 产品：单次研究、恢复、评测、benchmark 与导出
uv run asterion-dci --help
uv run asterion-dci run --help
uv run asterion-dci benchmark --help
```

`asterion run` 适合验证框架装配和通用能力执行。`asterion-dci` 暴露 DCI 完整产品功能；两者不是互相替代的命令。DCI 的命令、配置和验证层级见[完整产品参考](../guides/asterion-dci-complete-reference.md)。

## 完整接入示例：example.research

下面是一个中立示例，说明必须交付哪些组成部分。`example.*` 不是当前 wheel 已内置的产品身份，代码片段是接入模板，不是“已实现”声明。

1. Manifest

   在发行物资源目录中创建 `example.policy`、`example.research` 和 `example.observability` 三个符合 `dci.package/v1` 的 JSON。先用 manifest validator 测试字段封闭、数组排序、边完整。

2. Implementation binding

   为所有可执行 package 实现 `execute()`；`example.policy` 为静态 policy，不绑定实现。研究实现只能返回 `research.completed` 和已声明 media type，observability 实现同理。

   ```python
   implementations = (
       (PackageRef("example.research", "1.0.0"), ResearchImplementation()),
       (
           PackageRef("example.observability", "1.0.0"),
           ObservabilityImplementation(),
       ),
   )
   ```

3. Assembly

   创建前文所示 `example.research-app@1.0.0` assembly，固定 `pi.reference` 和三个 package 的确切版本。若还支持另一 runtime，应增加另一份 assembly，而不是在一份文件中放条件逻辑。

4. Installed provider

   工厂返回不可变 provider，并把资源限制在自己的安装根目录：

   ```python
   return InstalledApplicationProvider(
       protocol=APPLICATION_PROVIDER_PROTOCOL,
       provider_id="example-suite",
       resource_root=root,
       applications=(InstalledApplication(
           application_id="example.research-app",
           version="1.0.0",
           assembly_paths=(root / "assemblies/example-research.json",),
           catalog_roots=(root / "manifests",),
           implementations=implementations,
           runtime_ids=("pi.reference",),
       ),),
   )
   ```

5. Python entry point

   在该发行物的 `pyproject.toml` 注册唯一入口：

   ```toml
   [project.entry-points."asterion.applications"]
   example-suite = "example_suite.provider:create_provider"
   ```

6. `asterion list`

   构建并安装 wheel 后运行 `asterion list`。断言能看到 `example-suite` 的 distribution 名与版本，同时用测试 provider 证明 listing 没有导入 provider 模块。

7. `asterion run`

   显式运行：

   ```bash
   uv run asterion run --provider example-suite \
     --application example.research-app@1.0.0 \
     --runtime pi.reference --run-id smoke-001 --input "test"
   ```

   验证输出 application/runtime/run 身份、事件及 artifacts；另测未知 package、缺失 binding、错误 runtime 和缺失 host service 均安全失败。

8. Isolated-wheel test

   在不含仓库源码路径的新虚拟环境中安装构建产物，重复 `asterion list` 与 provider-free 测试。这个 isolated wheel 门禁能发现忘记打包 JSON、依赖了仓库相对路径、entry point 配错等源码树内测试看不到的问题。

## 安全失败与测试清单

一个接入只有同时通过下列检查才算完整：

- Manifest：协议、封闭字段、语义版本、排序去重、所有 edge 均有声明。
- Composition：缺失依赖、能力歧义、循环、未满足 policy/event/artifact 均拒绝。
- Binding：每个可执行 package 恰好一个实现；policy 不伪装成可执行实现。
- Output：事件和 artifact schema、类型及唯一 ID 与 manifest 一致。
- Provider：元数据 listing 不 import；选择时只 import 精确 ID；资源不能逃逸根目录。
- Application：provider、application、assembly、runtime 四层身份完全一致。
- Runtime：factory 精确选择；manifest 能力满足 assembly；事件流及 run ID 通过校验。
- Host：服务由宿主显式注入；缺失时在任何外部执行前失败。
- CLI：`asterion list`、`describe`、`verify`、`run` 的成功与失败路径都有测试。
- Distribution：sdist/wheel 内容检查和 isolated wheel smoke 均通过。
- Product：若 provider 暴露完整产品，功能目录、配置说明、验证层级及 provider 操作计数可从 `describe/verify` 看到。

建议的本仓库验证命令：

```bash
uv run python -m unittest discover -v
uv run ruff check src tests
uv build .
# 然后在临时虚拟环境安装 dist/*.whl，执行 isolated wheel smoke。
```

这些门禁验证“接入结构完整”；是否复现某个外部模型结果，仍需单独的受限 provider-backed 或 full-dataset 验证，不能由 provider-free 测试代替。
