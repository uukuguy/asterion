# Prime Standard Application Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 遵循 AGENTS.md 的模型分工与独立复审要求。

**Goal:** 把已有真实模型路径接入 Prime 标准入口，由 Prime 持有 Pi/RPC、扩展与适用计算资源，保持领域行为及控制边界。

**Architecture:** 独立应用用 Python 描述与 operator 数据直接构造 Prime owner；不要求登记 provider、assembly、inventory。runtime、模型操作和 durable attachment 是同一 owner 的窄视图，复用现有 kernel/session/backend 与抽出的 `LiveModelSession`。应用提供领域工具 artifact、数据与判断；现存集成仅作兼容，不另造 runner。

**Tech Stack:** Python 3、unittest、现有 Pi RPC/Node、TypeScript 打包扩展、现有 wheel 与 Make 部署检查。

**Status:** 书面设计已获用户批准；本计划已完成根代理覆盖、接口及迁移顺序自审，实施进行中（Task 1–4/6 完成，Task 5/7 进行中）。已完成计划文档检查；各代码测试与模型验证按任务实际结果记录。

**Design:** [approved design](../specs/2026-10-10-prime-standard-application-entry-design.md)；[canonical worklist](2026-10-08-prime-autonomous-research-interface.md) Task 40；[DECISIONS](../../status/DECISIONS.md) D-2026-10-10-03。

## Global Constraints

- 框架保持同一根 wheel；独立应用可自带领域包/artifact。不拆框架 SDK、不改四个 closed protocols、manifest 或 runtime identity。
- P1–P7 为独立应用，标准入口不要求注册；CLI 定位待定，本轮不设计统一 CLI，现有 CLI/provider/assembly 只在兼容范围内保留。
- P1–P6 精确使用 `deepseek/deepseek-flash`，P7 全部模型路径含 narrator 精确使用 `openai-codex/gpt-6.1-sol`；禁止猜测 `deepseek-v4-flash` 等价或静默 fallback。P2 只记目标，不新增调用。
- operator 解析 `.env`；core 只消费注入数据，不发现凭据、邻接源码或应用实现。
- 应用不创建 Pi/RPC、扩展 lease/fd 或 Pi argv；不接受能暗中创建它们的 startup callback。
- 保留 generic runner、session/backend/kernel、工具注册机制；不建立第二套执行器。
- text-only 不借用 IPython runtime manifest 伪装能力；它服务现有领域 host 回调。
- 持久执行保留 deadline、callback、动作预算、pause、未知 effect、源/JSON 恢复和 generation 边界。
- 首次构造不产生模型效果；同 owner 的视图不续期、不重复授予额度，只有既有显式 child authority 可以分配独立额度。
- 默认专用压缩提示重接与低阈值实测不在本计划；仅保留 P1 手工/witness 与 P7 当前接线。
- P2 仅记录目标边界；确定性 witness 不改成假 live，也不强制挂模型。
- 不启动 BP35 或官方提交。末尾 r11l 打包 witness 是部署验收项，执行时核实具体授权与有限 preset。
- 测试以实际边界和代码评审为主；RED/GREEN 使用替身，无付费模型；全量检查不逐任务重复。

## 文件职责与依赖

| 文件 | 新职责 |
| --- | --- |
| `src/asterion/agents/prime/application.py`（新） | 进程内描述、标准入口、owner 的窄视图与关闭合同 |
| `src/asterion/agents/prime/_launch.py`（新） | 私有 argv、RPC、扩展资源/lease、配置目录和诊断接线 |
| `src/asterion/agents/prime/_text_model.py`（新） | 从现有 live_model 搬入模型会话、计量与取消实现 |
| `src/asterion/agents/prime/_tool_bridge.py`（新） | 现有 wire envelope、socket/thread/loop、读写和关闭；不含 P7 方法名 |
| `src/asterion/agents/prime/_workspace_owner.py`（新） | 通用 worker 构造/生命周期及既有 source/JSON 恢复 |
| `src/asterion/applications/prime/p7/tool_dispatch.py`（新） | 从 operator 提取 P7 方法 dispatch/领域输出/日志 |
| `packages/typescript/asterion-prime-extension/src/tool-bridge.ts`（新） | 现有通用 bridge/tool 类型 |
| `packages/typescript/asterion-prime-extension/src/p7-tools.ts`（新） | 现有 P7 schema、method tool、memory hook |
| `packages/typescript/asterion-prime-extension/src/ipython-extension.ts` | 通用 registerPrime 函数与 core-only 默认入口，无应用 switch |
| `packages/typescript/asterion-prime-extension/src/p7-research-extension.ts`、`p7-legacy-extension.ts`（新） | 应用拥有的显式打包入口，各自固定 module |
| 原 operator/runtime binding/live 文件 | 配置解析、领域回调、入口使用；移除私有后端构造 |

依赖：Task 1 → Task 2；Task 1 → Task 3；Task 2+3 → Task 4；Task 2+4 → Task 5；Task 2 → Task 6；Task 6 → Task 7；全部 → Task 8。
Wave A：Task 1；Wave B：Task 2/3 可按文件所有权并行；Wave C：Task 4；Wave D：Task 5/6 可并行；Wave E：Task 7；Wave F：Task 8。
Task 4 先完成 P7 再扩展 P1/P3–P6。共享 `application.py` 的必要修改交同一 owner 合并，禁止两个 worker 同时改它。
每个任务提交保持现有消费者可运行：Task 2 保留旧 launch/factory 兼容面到 Task 6/7 迁完；Task 3 的新 artifact 与旧 producer 同提交切换；Task 8 才删除过渡适配。

## 固定 API 与所有权

下列为应实现的进程内接口，不是新的序列化合同。字段沿用现有类型；可选能力必须在模型效果前拒绝不匹配。

```python
@dataclass(frozen=True, repr=False)
class PrimeOperatorContext:
    executable: Path                 # 已预检的 node 或 pi 可执行文件
    entry: Path | None                # node 模式下的已预检 Pi entry
    cwd: Path
    provider: str
    model: str
    effort: str
    environment: Mapping[str, str]   # 复制并脱敏；无启动 flags
    task_deadline: TaskDeadline | None # 既有授权的绝对总期限；不由视图重新创建
    diagnostics: DiagnosticSink | None = None
    private_failure_sink: PrivateFailureSink | None = None

@dataclass(frozen=True, repr=False)
class PrimeApplicationSpec:
    application_id: str
    application_version: str
    profile: Literal['text-only', 'persistent-code-tools']
    system_prompt: str | None = None
    tools: PrimeToolModuleArtifact | None = None

@dataclass(frozen=True, repr=False)
class PrimeToolModuleArtifact:
    path: Path                       # 显式应用构建产物，owner负责preflight/pin
    registry: PrimeApplicationToolRegistry

def prepare_prime_application(spec: PrimeApplicationSpec,
                              operator: PrimeOperatorContext, *,
                              authorization: PrimeTextLimits | AsterionPrimeLimits | PrimeBackendSpec
                              ) -> PrimeApplication: ...
```

`PrimeApplication` 是资源 owner，不是新的 runner。构造时复制/校验数据；首次执行才开模型进程。
application_id/version 是本地身份而非注册证明；metadata 中 provider 指模型服务商，与应用 provider/catalog 无关。
入口不 import inventory/provider dispatcher，不要求 RuntimeFactoryContext；已有 provider adapter 可调用同一入口。

```python
class PrimeModelView(Protocol):
    async def prompt(self, text: str, *, signal: CancellationSignal) -> LiveModelReply: ...

class PrimeApplication:
    def text_model(self, *, key: str, limits: PrimeTextLimits) -> PrimeModelView: ...
    async def text_once(self, *, key: str, text: str, limits: PrimeTextLimits,
                        signal: CancellationSignal) -> LiveModelReply: ...
    def runtime(self, *, services: PrimeApplicationServices,
                limits: AsterionPrimeLimits, hooks: PrimeRunHooks) -> AgentRuntimeClient: ...
    async def open_backend(self, *, spec: PrimeBackendSpec,
                           services: PrimeApplicationServices) -> PrimeAttachment: ...
    async def close(self) -> PrimeApplicationCleanup: ...
```

`text_model` 视图仅可 prompt；`text_once` 在返回前完成模型关闭，适合 P3/P4/narrator；同 key 关闭后不能隐式重开或换限额。owner 构造即接收 operator 批准的 authorization 与绝对 task_deadline；后续方法的 limits 只能等于或收紧原授权，不能新授预算。text key 仅隔离对话，所有 key 的消耗进入同一 owner 账本；已有显式 child grant 由既有 child authority 分配并从 parent 扣减，不能仅凭换 key 创建 grant。
`PrimeTextLimits` 为 frozen dataclass：`deadline_seconds: float`，`max_prompts/max_input_bytes/max_output_bytes/max_input_tokens/max_output_tokens/max_cost_micros/provider_output_tokens: int | None`，`price: ModelPrice | None`。`ModelPrice` 复用 `agents.prime.compaction_budget` 的 input_per_million/output_per_million；非 None 上限必须正数，声明 cost cap 时必须有匹配 exact provider/model 的已核实价格。
保留 narrator 的 300 秒 deadline，模型改为 P7 的 gpt-6.1-sol；不强加 live-verification 的 512 output cap。原未声明维度保持 None，不生成新额度；模型配置与 get_state 一致性仍核对 exact provider/model。
运行总期限来自既有任务 authority；`text_once` 与后续 workflow 使用其剩余量，不能重新从 now 加满时限。
`PrimeRunHooks` 为 frozen dataclass：`completion_predicate: Callable[[], bool] | None`、`continuation_prompt: Callable[[int], str] | None`、`round_admission: Callable[[int, CancellationSignal], Awaitable[bool]] | None`、`round_diagnostic: Callable[[PrimeRoundDiagnostic], None] | None`、`failure_diagnostic: Callable[[FailureDiagnostic | None], None] | None`、`prompt_recovery: PrimePromptRecovery | None`、`reusable_session: bool = False`；回调字段默认 None，原 session 语义不变，不接受启动函数。
`PrimeBackendSpec` 字段为 session_id、generation、private_root、continuation_policy_id、limits、aggregate_tokens、cost_micros、model_price、authority_id、compaction_instructions；类型沿用现有 backend/state。应用身份来自 owner，worker 身份来自 executor，command/extension/private-root/ceilings 哈希由 owner 按现有公式派生；不接收应用伪造的 Pi 指纹。
其具体类型依次为 `str/int/Path/str/AsterionPrimeLimits/int/int/ModelPrice | None/str | None/Mapping[str, str] | None`，另有 `compat_provider_id: str | None = None`。既有 adapter 明确设置该字段为原 provider_id；直接路径的既有 backend identity 使用内部 `prime.direct` 来源标识，不创建/查询 provider 注册，状态格式不变。
`PrimeApplicationCleanup` 返回 effects/model/extension/bridge/workspace 的关闭状态与 `complete`，对外只允许投影布尔/状态码。
`PrimeApplicationServices` 是领域 executor 协议：`async execute(request_id: str, code: str, signal: CancellationSignal) -> PrimeToolResult`、`async call(request_id: str, method: str, params: Mapping[str, object], signal: CancellationSignal) -> Mapping[str, object]`、`request_stop() -> None`、`async close() -> None`、`identity_sha256: str`、`validate_lifecycle() -> object`；call 返回沿用当前 wire 方法结果，由 core 校验 envelope，领域 dispatch 不持 socket。
服务可以有领域 bootstrap/source/data，但不能给出 argv/fd 或 Pi/worker startup callback。
通用 workspace owner 使用现有 `KernelBootstrap`、`KernelLimits`、`SubprocessPythonWorker`；公开 `create_workspace(bootstrap, limits)` 和 `restore_workspace(checkpoint)` 操作，owner 跟踪并关闭历代 worker。
P1 oracle executor、旧 P7 领域 worker 可按现有窄 executor 协议转交关闭责任；core 不导入其类，不重写其领域协议。
`open_backend` 持有 backend owner，只返回 attachment。attachment close 只撤销视图；应用最终 close 才关闭真实资源。
上述类型只从 `agents.prime.application` 公布；旧 session/backend 保留内部与机制测试用途，应用不再直接构造。
只有已有特殊授权允许 task_deadline=None；新 direct 示例与普通 presets 必须有限。既有 backend/host authority 与 owner 共享消耗，同 key/新视图不重新建立起始时间或预算。
共享计量沿用已有实现：将 LiveModelSession 的 `_prompts/_input_bytes/_output_bytes/_input_tokens/_output_tokens` 及成本计算提取为 owner 唯一私有 usage state，各 key session 引用它；不新增授权协议。持久 backend 继续通过现有 `sync_authority_snapshot(RemainingBudget, authority_revision=...)` 与 `BudgetUsage` 接轨，P3 child 使用已有 admit/record_child_cost，P6 effect_sender 投影同一 usage，禁止再建立第二账本。operator 原总限额在 prepare 固定，owner 不自行刷新 authority。

## Task 1：标准入口的数据与无效果边界

完成：`d5668e8c`、`ae185b25`；8 项 focused tests 与 Ruff 通过，独立 Astra 复审通过，根代理核对输入校验兼容修复。此阶段正向工厂仍显式拒绝，模型能力不计为完成。

**Files:** Create `src/asterion/agents/prime/application.py`；Modify `src/asterion/agents/prime/__init__.py`；Create `tests/test_prime_application_entry.py`。
**Interfaces:** 定义上节所有数据类型与协议；实现 `PrimeOperatorContext`、`PrimeApplicationSpec` 和 `prepare_prime_application` 无效果构造。Task 2/3 在 owner 固定私有方法内接入资源，禁止将未定义类型推给后续 task。

- [x] 添加 `TestPrimeApplicationEntry.test_prepare_is_effect_free_and_profile_checked`，使用临时已预检可执行文件、sentinel 环境与 RPC/worker 构造 patch；断言 prepare 零调用，text-only 请求 runtime 在启动前失败。

```python
with patch('asterion.runtimes.pi_rpc.PiRpcSession') as rpc:
    app = prepare_prime_application(text_spec, operator, authorization=bounded_limits)
    with self.assertRaises(ProtocolError):
        app.runtime(services=services, limits=limits, hooks=hooks)
    rpc.assert_not_called()
self.assertNotIn('private-sentinel', repr(app))
```

- [x] RED：`uv run python -m unittest -v tests.test_prime_application_entry`；预期入口导入失败，确认失败原因后再实现。
- [x] 实现 frozen/slotted 数据、复制环境、本地身份检查、profile/tool 组合检查；构造不查询 provider/inventory、不读 `.env`、不写临时配置、不开线程或进程。加入未登记 `example.independent` 的 prepare 测试。
- [x] 固定 owner 状态：prepared → active → closing → closed；同 key 限额不同拒绝，closed 不再接纳效果，close 幂等。暂未装配的 profile 正向工厂由 Task 2/3 完成，禁止放任意 factory 参数。
- [x] 添加 `test_context_is_immutable_and_redacted`：原字典修改不影响 context；任何异常不带 provider env、prompt、cwd。
- [x] GREEN：同一命令；预期新增无效果/不可变/脱敏测试通过，不调用 provider。
- [x] 提交：`git add src/asterion/agents/prime/application.py src/asterion/agents/prime/__init__.py tests/test_prime_application_entry.py`；`git commit -m "feat(prime): define standard application owner boundary"`。

## Task 2：提取真实 text-only 会话并收回模型启动

完成：`6fe51d20`、`5cc50b56`；67 项 focused/旧调用方测试与 Ruff 通过，Astra 复审通过。修复 core 读取 profile 和共享用量耗尽后多发一次请求的问题。

**Files:** Create `src/asterion/agents/prime/_launch.py`、`_text_model.py`；Modify `application.py`、`src/asterion/applications/prime/live_model.py`、`src/asterion/applications/prime/operator_config.py`、`tests/test_prime_live_model.py`、`tests/test_prime_application_entry.py`。
**Interfaces:** `PrimeTextLimits`、`PrimeModelView`、`text_model/text_once/close`；新增 resolver 返回 `PrimeOperatorContext`；旧 resolver 返回形状在消费者迁完前保持兼容。

- [x] 添加 `test_text_view_has_no_launch_handles` 与 `test_text_once_reaps_before_return`；改既有 fake RPC fixture 到新的私有 `_launch` seam，应用 fixture 只提供数据。

```python
view = app.text_model(key='candidate', limits=bounded_limits)
self.assertFalse(any(hasattr(view, name) for name in ('open', 'close', 'process', 'config')))
reply = await app.text_once(key='checkpoint', text='private input',
                            limits=bounded_limits, signal=signal)
self.assertEqual(reply.text, 'private output')
self.assertTrue(fake_rpc.closed)
```

- [x] RED：`uv run python -m unittest -v tests.test_prime_application_entry tests.test_prime_live_model`；预期缺失 view 行为/owner 关闭断言失败。
- [x] 按符号搬移 `LiveModelUsage/Reply`、`LiveModelSession.__init__/_verify_model_cap/open/prompt/close` 至 `_text_model.py`；保留 usage normalizer、cache token 计量、取消异常和配置目录清理。
- [x] bounded-live 数量上限保持 120 秒、4 prompts、8192/32768 bytes、16000/8000 tokens、3000 cost_micros、provider maxTokens 512；exact model 改为 deepseek-flash，配置/get_state 两端一致。本地 Pi exact model metadata 的 input/output 为每百万 0.3/1.2 USD，对应 300000/1200000 micros；旧 140000/280000 不适用。operator 注入匹配价格，缓存继续按全价输入保守计量；未知价格在 effect 前拒绝，不能用 v4-flash 名称或价格猜映射。
- [x] `_launch.py` 以 executable/entry/provider/model/effort、profile 和固定 flags 组装 Pi 命令；保留 text-only `--no-tools --no-session --no-extensions` 及其余 isolation flags，禁止把任意 flags 作为应用入参。
- [x] 新增 `resolve_live_model_context`，保留 operator 配置/安装/路径预检。旧 `resolve_live_model_launch`、`LiveModelLaunch.command` 和旧 session 构造形状暂保留给 Task 6/7 未迁移调用方；兼容层委托 Prime 私有命令构造与 session engine，不复制实现。此阶段不得把旧返回值直接换成没有 `.command` 的 context；Task 8 才移除过渡面。
- [x] owner 延迟 open、跟踪每 key 的真实 session 与已消耗额度，重取视图不续期；`text_once` 使用 try/finally 关闭且关闭失败不返回成功；总体 close 汇总并重试既有 reap 兜底。
- [x] 复用 `tests.test_prime_live_model` 全部 cap/usage/cache/cancel 测试，不复制第二套；新增两个 key 的独立对话与同 authority 不因视图重置的断言。
- [x] 增加 `test_unlisted_application_runs_without_provider_lookup`：对本地 `example.independent` spec 调 `prepare_prime_application(text_spec, operator, authorization=bounded_limits)` 与 text_once，provider/inventory 入口 patch 为抛错仍成功；检查新 key 消耗累计、关闭 key 拒绝重开、deadline 不从第二调用重新计时。
- [x] GREEN：同 RED 命令，另跑 `uv run python -m unittest -v tests.test_prime_p3_live tests.test_prime_p4_live tests.test_prime_p5_live tests.test_prime_p6_live` 证明未迁移消费者仍工作；缺配置 public-safe、框架不读 `.env`。
- [x] 提交上述精确文件：`git commit -m "refactor(prime): own bounded text model sessions"`。

## Task 3：核心扩展与应用模块分离

**Files:** Create `packages/typescript/asterion-prime-extension/src/tool-bridge.ts`、`p7-tools.ts`、`p7-research-extension.ts`、`p7-legacy-extension.ts`；Modify 该包 `src/ipython-extension.ts`、`package.json`、`scripts/sync-runtime-resource.mjs`、`test/ipython-extension.test.mjs`，`src/asterion/agents/prime/tool_registry.py`，P1 `operator.py`，P7 `operator.py`、`live.py`、`official_operator.py`，`tests/test_prime_extension_tool_contract.py`。生成同 wheel 资源 `applications/prime/resources/ipython-extension.mjs`、`p7-research-extension.mjs`、`p7-legacy-extension.mjs`，必要时同步根 `pyproject.toml` 的资源包含规则。
实施补充范围：`hatch_build.py`、`pyproject.toml` 和 `tests/test_prime_extension_build.py` 同步三资源构建/安装证明；`src/asterion/runtime/pinned_extension.py` 窄支持合法 ESM default export-list，保持 node-only imports/digest/pin 边界。外部应用使用普通构建产物，无需专用导出重写。
**Interfaces:** 应用传 `PrimeToolModuleArtifact(path, registry)`；artifact 自包含并导出 `default register(pi, dependencies)`。核心导出 `registerPrime(pi, dependencies, module)`，没有 app selector switch、目录查询或 P7 import。

- [x] 在现有 TS 测试增加 core-only 不注册 P7 hook/tool、P7 两个显式入口工具集不变、外部自定义 module 无需编辑核心即可注册；模块身份/完整工具名与 injected registry 不符在任何注册前拒绝。

```typescript
// module只描述领域工具和context hook；不能接管RPC或进程生命周期。
export interface PrimeToolModule {
  readonly registry: { module_id: string; capability_id: string; tool_names: readonly string[] };
  createTools(bridge: IpythonBridge): readonly ReturnType<typeof createIpythonTool>[];
  registerContextHooks?(pi: ExtensionApi, dependencies: unknown): void;
}
// P7应用自己的research artifact入口；legacy入口绑定另一个显式module。
export default function register(pi: ExtensionApi, dependencies: unknown) {
  return registerPrime(pi, dependencies, p7ResearchModule);
}
```

- [x] RED：`npm --prefix packages/typescript/asterion-prime-extension test`；预期新 core 分离断言失败，因为当前 register 总安装 P7 memory。
- [x] 将当前 bridge/type 168–422、`createIpythonTool` 的通用依赖搬入 `tool-bridge.ts`；P7 specs 513–784、`makeMethodTool`、research/legacy 工具创建与 P7 memory hook 搬入 `p7-tools.ts`。
- [x] `ipython-extension.ts` 只保留核心 registerPrime、context witness/telemetry 与 core-only module；`context-memory/archive/projection` 通用模块不搬进 P7。p7-tools 导出 research/legacy 模块，由两个应用 entry 静态选择，核心不接受 P7 枚举。
- [x] 模块 artifact 在构建时 bundle 核心注册函数+应用 module；沿用现有固定源码仅允许 node import 的限制，禁止运行时 import 外部路径/npm 包。外部应用可在构建时使用 wheel 中已导出的通用 registerPrime bundle，不需要编辑框架源码或登记应用。
- [x] 本 Task 生成的 core-only `ipython-extension.mjs` 保留 named export `registerPrime`，同时有供 P1 使用的 default register；构建脚本改为按 entry 的真实导出生成资源，不能重复追加 default footer。外部 fixture 只从隔离安装 wheel 的 importlib.resources 获取该 bundle 作构建输入，再 esbuild 合入应用 module，禁止引用仓库邻接 TS 源码或假设存在尚未发布的 npm SDK。
- [x] Prime 私有绑定注入期望 registry（module/capability/完整 names），registerPrime 读取后清除环境值，逐项核对 artifact 内的 registry；P7 research/legacy 的 module/capability 相同，完整 names 仍必须精确。
- [x] 本提交同步旧 P1/P7 producer：P1 选择 core-only artifact；P7 research/legacy 在应用层选择对应 artifact，official 随 P7 producer；三者均注入期望 registry。不要等 Task 4 才改 producer，也不能依赖缺配置默认 P7。过渡期旧 producer 仍拥有 lease，Task 4/5 再原子移入 Prime owner。
- [x] 为现有测试保留必要 re-export；这些导出不触发默认 P7 注册。不得修改 P7 描述、schema、NOTES retirement、frame/state 可见逻辑。
- [x] GREEN：先 `npm --prefix packages/typescript/asterion-prime-extension test`，再 `uv run python -m unittest -v tests.test_prime_extension_tool_contract tests.test_prime_p7_tool_registry tests.test_prime_p7_native_provider tests.test_asterion_prime_p1_operator`；验证此时尚未迁 owner 的 producer 也能加载新 artifact。
- [x] 用 package 既有命令同步并检查：`npm --prefix packages/typescript/asterion-prime-extension run sync-resource`；`npm --prefix packages/typescript/asterion-prime-extension run check-resource`。
- [x] 提交 TS、registry、测试和生成 `.mjs`：`git commit -m "refactor(prime): select application tools through existing extension"`。

Task 3 完成：`fc225adb`；Astra 独立复审无发现。TS 93 PASS/6 External-limited；Python 工具/安装/三资源构建检查通过。最终 promotion 与真实部署见证仍待 Task 8。

## Task 4：Prime 持有 persistent runtime、bridge 与 workspace

**Files:** Create `src/asterion/agents/prime/_tool_bridge.py`、`_workspace_owner.py`、`src/asterion/applications/prime/p7/tool_dispatch.py`；Modify `application.py`、`_launch.py`、`src/asterion/applications/prime/p7/operator.py`、`runtime_binding.py`、`research_runtime.py`、`live.py`、`official_operator.py`、`model_selection.py`；Test `tests/test_prime_application_entry.py`、`tests/test_prime_p7_bridge_dispatch.py`、`tests/test_prime_p7_native_provider.py`、`tests/test_prime_p7_live_command.py`、`tests/test_prime_p7_official_operator.py`。
实施补充范围：`runtime/pi_rpc.py` 可选成对 expected provider/model，首次 prompt 前核对实际 state，未配置时保留原合同；同步 transport 与 research-runtime 测试。services 保留既有领域 params/缺省区别；workspace 使用现有 sources/data/signal 恢复合同。
**Interfaces:** `runtime(services, limits, hooks)` 返回现有 runtime client；`PrimeApplicationServices` 提供领域执行方法；workspace owner 返回现有 `PersistentIpythonHost` 窄执行视图。

- [x] 先扩展 provider 的 no-start、lease-failure、exact registry、bounds 测试：应用输入只有数据/services，Prime private launch 被调用一次；错误 profile/identity/allowlist 在 Pi 前拒绝。

```python
runtime = app.runtime(services=domain_services, limits=limits, hooks=hooks)
self.assertEqual(private_launch.call_count, 0)
events = [event async for event in runtime.run(request, signal=signal)]
self.assertEqual(events[0].type, 'run.started')
self.assertEqual(private_launch.call_count, 1)
```

- [x] RED：`uv run python -m unittest -v tests.test_prime_application_entry tests.test_prime_p7_native_provider tests.test_prime_p7_bridge_dispatch`；失败必须指向 owner/注册/关闭边界。
- [x] 从 `_IpythonBridgeServer` 提取 socket/thread/loop/envelope/read-write/close 到 `_tool_bridge.py`；method 名、缺 params 的领域兼容、P7 日志和 `_dispatch_method_call` 留 `tool_dispatch.py`，core 只调用 services。
- [x] Prime `_launch` 接管 `socketpair`、metrics FD、ExtensionBinding/preflight、精确 command args、build_rpc_session、资源失败回收；只使用 spec.tools.path 显式 artifact，不在 core 按应用 ID 找资源。内置应用由各自包装从同 wheel 取资源，外部应用可提供已授权的自有打包产物。
- [x] 将 `live.pi_base_command` 的固定 flags/effort 拼装搬入 `_launch`；P7/official preflight 只返回 executable/entry/model/effort 等数据。移除 `PrimeLaunch` 应用构造与 binding 内 RPC/Session 创建。
- [x] P7 model_selection 的旧 gpt-6-sol 默认改为本轮 exact `openai-codex/gpt-6.1-sol`；solving/gameplay/official operator 使用同一选择，配置冲突或运行 state 不一致执行前拒绝，不转 fallback。
- [x] 分离 P7 直接业务入口与旧 provider 包装：operator 用应用本地 identity、tool artifact、services 和 hooks 构造 owner；运行调用不经过中央 inventory/runtime factory lookup。旧 provider/runtime binding 委托同一业务函数并附加原 exact identity 校验，不复制求解循环。给 P7 直接入口加禁用中央 lookup 的替身测试。
- [x] 保持现有 host service key/manifest；`prime.launch` 可内部承载 `PrimeApplication` handle，禁止泄露旧 lease/command 字段。runtime factory 校验 app/version/runtime/options 与 handle 身份一致，再请求 `runtime()`。
- [x] 内部使用 `AsterionPrimeSession` 与同一 `PrimeExecutionKernel`；原 `_p7_terminal/_p7_gameplay_terminal`、continuation、round admission、event projector 和 diagnostics 保持在 P7。
- [x] `_workspace_owner` 构造现有通用 `SubprocessPythonWorker`；P7ResearchRuntime 提供 `KernelBootstrap` 和 limits，移除其 worker_factory/default constructor。operator 当前先建旧 worker 再按 isinstance 替换的 4956/4032/4033 接线一并移除；core 只接收 Python executable 和 typed bootstrap，不能 import p7.live。
- [x] 正常续跑复用 current generation；丢失后的 `restore_workspace` 使用既有 source/JSON checkpoint 与 provenance，禁止对象复活/动作 cell 重放；旧 P7 领域 executor 保持窄服务注入，由 owner 接管 close。
- [x] P7OperatorResources 只持领域 trace/broker 与 Prime handle，metrics/accounting 通过窄只读访问；close 调用 owner，再收领域 trace；保留独立进程 reap，不能被活动 command lock 阻塞。
- [x] 加 `test_pause_does_not_reset_owner_budget`、`test_unknown_action_blocks_prompt_recovery`、`test_explicit_workspace_restore_advances_generation`，复用现有 control/action-journal/恢复 fixture，不建新模拟协议。
- [x] 加独立未注册 persistent 应用测试：临时 artifact bundle `registerPrime+example_lookup`，提供其 registry、services 和有限授权，直接 `app.runtime(...).run(...)`；禁用 provider/catalog lookup，fake backend 下通过真实 pin/preflight 与 registerTool 校验。断言工具仅 ipython+example_lookup、无 P7 hook；digest 或 registry 不匹配在模型效果前失败，不改 core app 列表。
- [x] GREEN：先重复 RED 命令，再 `uv run python -m unittest -v tests.test_prime_p7_live_command tests.test_prime_p7_official_operator`；只运行一次 broad P7 文件集。
- [x] 提交列出的实现与测试：`git commit -m "refactor(prime): own persistent P7 runtime resources"`。

Task 4 完成：`865eea25` + `61856505`，Astra 复审通过；公开 worker 注入与活动 cell 阻塞关闭均已修复，60 项定向测试通过。首次 P7 广跑未整体重跑，失败对应子集已通过；最终部署验收仍待 Task 8。

## Task 5：P1 durable owner 与 P7 narrator 接入

**Files:** Modify `src/asterion/agents/prime/application.py`、`_launch.py`、`src/asterion/applications/prime/p1/operator.py`、`runtime_binding.py`、`src/asterion/applications/prime/p7/run_story/operator_narrator.py`；Test `tests/test_asterion_prime_backend.py`、`tests/test_asterion_prime_p1_operator.py`、`tests/test_asterion_prime_p1_runtime.py`、`tests/test_prime_arc_agi_3_run_story.py`。
**Interfaces:** `PrimeBackendSpec/open_backend` 创建 backend/store/witness 并保留其 owner；P1 得到现有 attachment 操作，narrator 使用 `text_once`。
实施补充范围：控制兼容工厂可接受 exact PrimeApplication 并调用 attach_backend，保留身份/授权校验；通用 bridge 保留 P1 原事件循环。共享 owner 提供私有不可变启动指纹与既有用量账本投影，区分 unknown effect 与仅清理失败；Task 5 独占共享核心文件，Task 6 只消费这些接口。

- [ ] RED 测试扩展 P1 清理：close attachment 后同 owner 可 attach、kernel generation 未变；Pi close 故障时 independent reap 仍执行，构造阶段不启动模型。

```python
attachment = await app.open_backend(spec=backend_spec, services=executor)
identity = attachment.snapshot().identity
before = identity.generation
await attachment.close()
attached_again = app.attach_backend(identity)
self.assertEqual(attached_again.snapshot().identity.generation, before)
self.assertFalse(executor.closed)
```

- [ ] 将 `attach_backend(identity: PrimeBackendIdentity) -> PrimeAttachment` 作为 owner 的只读身份核验入口，只调用已创建 backend.attach，不另建 owner 或执行效果。
- [ ] RED：`uv run python -m unittest -v tests.test_asterion_prime_backend tests.test_asterion_prime_p1_operator tests.test_prime_arc_agi_3_run_story`。
- [ ] 从 P1 `_build_resources` 搬移 RPC/binding/lease/store/witness/identity 私有启动派生到 Prime；identity 的应用字段和授权数据由 spec 提供，command/binding 指纹由 owner 计算，不能接受应用伪造启动哈希。
- [ ] P1 独立 operator 使用本地 spec 与 backend owner；原 provider 包装只负责兼容身份映射。中央 application lookup 被 patch 为拒绝时，直接 setup/verify 生命周期仍能通过替身执行。
- [ ] P1Oracle、coordination、domain stage 和 `_construct_host/reconstruct/compact/resume` 留 P1；worker 是领域 executor，可转交 owner 管理关闭，core 不导入 P1WorkerProcess。
- [ ] P1 operator 固定为 exact deepseek/deepseek-flash；同步价格、get_state/trace identity 与相关 fixture，旧 v4-flash 值不能作为 alias 继续通过。已有 token/cost/时间额度保持不扩张，未核实 exact model 价格即 preflight 拒绝。
- [ ] 保留 P1 `cleanup` 的独立 worker/Pi 强制回收；不把所有 close 串在同一 backend lock 后面。已启动但结果未知继续 fence；账本丢失不得重试。
- [ ] narrator resolver 改为 P7 同一 exact openai-codex/gpt-6.1-sol 选择，移除 EXPERIMENT_MODEL/deepseek-only 选择旁路；保留 300 秒与领域输入输出行为，使用该 provider 的注入授权环境。`invoke` 内 asyncio.run 仅包 owner.text_once+finally close，不再构造 RPC/argv，不套用 flash 的512 output上限。
- [ ] narrator 继续同步 `RunStoryNarrator.generate` API 与 JSON/引用/脱敏验证；模型失败不改变 deterministic renderer/evidence 数据。
- [ ] GREEN：同 RED 命令，另 `uv run python -m unittest -v tests.test_asterion_prime_p1_runtime`；重点保留 `test_aggregate_usage_includes_both_stages_and_compact_charge`。
- [ ] 提交：`git commit -m "refactor(prime): bind durable P1 and narrator to owned sessions"`。

## Task 6：P3/P4/P5 live 消费窄模型视图

**Files:** Modify `src/asterion/applications/prime/p3/live.py`、`operator.py`、`live_entry.py`；`src/asterion/applications/prime/p4/live.py`、`operator.py`、`live_entry.py`；`src/asterion/applications/prime/p5/live.py`、`operator.py`；Test `tests/test_prime_p3_live.py`、`tests/test_prime_p4_live.py`、`tests/test_prime_p5_live.py`、`tests/test_prime_p3_composed_runtime.py`、`tests/test_prime_p5_p6_composed_execution.py`。
**Interfaces:** 去掉 session_factory 参数，改为 PrimeApplication owner/PrimeModelView；回调只能请求领域模型操作，不能自建/open/close 模型。

- [x] 将现有 fake session factory fixture 改为 private owner seam；保留原领域断言，并加 view 接口没有 process/open/close 的断言。

```python
# P3LiveHost._prompt: child admission 已通过，再使用各自独立 key。
reply = await prime.text_once(key=role, text=prompt,
                              limits=live_limits, signal=signal)
# P5 多轮仍共享一个会话与计量，只有 Prime owner 知道其生命周期。
work = _CandidateWork(prime.text_model(key='candidate', limits=live_limits), run_id)
```

- [x] RED：`uv run python -m unittest -v tests.test_prime_p3_live tests.test_prime_p4_live tests.test_prime_p5_live`；验证 factory 泄漏/生命周期新断言确实失败。
- [x] P3/P4/P5 的直接 live 入口从本地应用描述构造 owner，不调用中央应用目录；需要 composed 执行时继续用本地精确 assembly/已解析 plan 和原 runner，不能为了绕过注册复制执行器。旧 provider 包装委托相同领域函数。直接入口测试禁用中央 inventory/provider lookup，保留原领域断言。
- [x] P3 `run_live_verification`、`P3LiveHost._prompt` 使用 child/root 独立 model key；首次效果必须在 child admission 后；root 仅消费已验证 child JSON，保留成本记录与 child cap。
- [x] P3/P4/P5 resolver、usage/get_state 和 fake fixture 都使用 exact deepseek-flash；消费者在本提交切到新 context/view，旧兼容入口继续给尚未迁移的 P6 使用。
- [x] P3 原 command/binding 哈希用途逐项保留，改取 owner 的私有身份摘要；应用不能自行拼 argv 算哈希，公开 surfaces 不输出私有配置。
- [x] P4 `run_live_round/P4LiveHost.commit_checkpoint` 用 `text_once`，仅在 prompt 与 close 都成功后 seal；保留 prior generation lock、disk JSON 恢复和 retry 合同，不换成 backend.attach。旧检查点的启动/绑定指纹若与新实现不符必须拒绝，不改写旧身份或放宽相等校验。
- [x] P5 `_CandidateWork._ask/propose/verify/repair` 只用 model view；`_open_bounded_autonomy_loop` 与 `_run_composed_loop` 保留领域编排，operator finally 关闭 Prime owner。
- [x] 消除应用 finalize=session.close 的模型生命周期回调；已有领域 finalize 行为保留，但模型 reap 由 Prime owner 的 execution scope 保证。P5 原 wait_finalization 必须在成功终态前检查 owner cleanup.complete；P3 清理故障不丢失已知成本，未知效果保留原 admission fence。
- [x] GREEN：同 RED 命令，再 `uv run python -m unittest -v tests.test_prime_p3_composed_runtime tests.test_prime_p5_p6_composed_execution`。
- [x] 重点检查 P3 admission refusal 零模型、child budget 阻断 root，P4 close failure 不 seal，P5 malformed artifact/cancel 均 reap；不要把名为 real_candidate 的 fake-model 测试写成 live 验证。
- [x] 提交：`git commit -m "refactor(prime): route P3 P4 P5 live model operations through owner"`。

Task 6 完成：`3d23decc`；51 项定向测试通过，Sol 独立复审无发现。P4 旧检查点不匹配启动/绑定指纹时，在模型效果前拒绝，不隐式转换。

## Task 7：把 P6 候选效果移入既有 composed 执行阶段

**Files:** Modify `src/asterion/applications/prime/p6/live.py`、`operator.py`、`runtime_binding.py`；Test `tests/test_prime_p6_live.py`、`tests/test_prime_p5_p6_composed_execution.py`、`tests/test_prime_p6_live_task.py`。
**Interfaces:** 使用 `_ComposedCandidateHost(..., workflow=...)` 与 `run_candidate(root_run_id, signal)` 的现有执行点；模型仅由 Prime view 提供。

- [ ] 在既有 composed tests 添加事件顺序与 pre-cancel 断言；fake model 记录调用时已见 `run.started`，预取消时零 model/候选文件/admission。

```python
async def generate(text, *, signal):
    self.assertIn('run.started', observed_events)
    self.assertFalse(signal.cancelled)
    return candidate_reply
self.assertEqual(model_calls_after_precancel, 0)
```

- [ ] RED：`uv run python -m unittest -v tests.test_prime_p6_live tests.test_prime_p5_p6_composed_execution`；当前前置模型效果使新增顺序断言失败。
- [ ] P6 直接入口以本地精确 assembly 和原 composed runner 组织 workflow，不查询中央应用清单；给同一替身执行添加 lookup 禁用断言。P2 保留既有本地入口，不因统一接口强制注册或挂接模型。
- [ ] 将 `run_live_candidate` 中 session_factory/open/prompt/close、parse、candidate 写入、Task A 证据构造搬进现有 workflow 执行体；构造 loop/coordinator 本身保持无模型效果。
- [ ] P6 同步切到 exact deepseek-flash 的新 context/view；Task 2 旧 .command/factory 兼容此时才失去最后消费者，先以 rg 核对，删除统一放 Task 8。
- [ ] workflow 先 `await model.prompt(_TASK_A_PROMPT, signal=signal)`，再原 `parse_candidate/task_a_evidence/_run_workflow`；异常进入已有 host 的 baseline/rollback/recovery-required 路径，不绕过 domain admission。
- [ ] 建立单个已有总 deadline：runtime 的执行期限覆盖生成与后续 workflow，text 模型仍受原 120s/3000micros 等更窄限制，不能改用 P6 较宽 300000micro cap。
- [ ] 已有 `effect_sender` 从本次 owner usage 读取候选消耗，保留证据与账本关系；标明 ledger owner，禁止 generation 和 workflow 两次为同 usage 增加总额。
- [ ] 加生成失败不 admit/promote、预取消零调用、生成消耗可见且不双计、跨阶段 deadline 不续期四项正常边界；用 fake clock，不增加长 sleep 或极端矩阵。
- [ ] GREEN：同 RED 命令，另 `uv run python -m unittest -v tests.test_prime_p6_live_task`；保留 unsafe JSON、holdout、回滚和 unknown-effect 原测试。
- [ ] 提交：`git commit -m "fix(prime): contain P6 candidate model effects within composed execution"`。

## Task 8：移除旁路、打包验收与状态收口

**Files:** Modify `src/asterion/applications/prime/runtime_binding.py`、`live_model.py`（仅删除遗留兼容启动）、`docs/architecture/agent-framework.md`、`docs/status/PRIME-P1-P7-ACCEPTANCE.md`、`docs/status/CURRENT-STATE.md`、`docs/status/DECISIONS.md`、`docs/status/INDEX.md`、`docs/status/RESUME-NEXT-SESSION.md`；更新 canonical Task 40 与现有协作 MEMORY/JOURNAL 的真实位置；Test `tests/test_prime_application_entry.py` 和下列 installed suites。
**Interfaces:** 独立应用直接依赖 standard entry；现有 provider 的 exact dispatch 和 metadata-only list 仅兼容保留，不能成为入口前置条件。CLI 定位待定，本任务不新增 Prime CLI。

- [ ] 写一个静态依赖边界测试扫描指定迁移文件的 AST import/call：禁止 PiRpcSession/PiRpcConfig/build_rpc_session/ExtensionBinding/Lease、AsterionPrimeSession/PrimeSessionBackend 构造。机制 fixture 与底层私有实现不纳入禁区。
- [ ] RED：先在遗留兼容 wrapper 尚在时运行 `uv run python -m unittest -v tests.test_prime_application_entry`，预期点名旁路位置；若前面已全部清除，加入临时内存源码 fixture 验证检测器能识别禁止调用，勿人为破坏生产代码。
- [ ] 删除应用树已无调用者的 argv/启动 wrapper；provider dispatcher 保持惰性 exact key，不能导入未选应用。`live_model.py` 只留 operator resolver 与明确兼容数据 re-export，或迁完所有导入后移除。
- [ ] 将 Task 2 过渡 `.command`/old factory 与 Task 3 过渡旧 lease producer 纳入明确删除清单；现有 provider adapter 只调用直接入口，framework core 不 import P7/tools inventory。未注册 direct-app 测试和内置兼容测试同时通过才能关闭迁移。
- [ ] 静态核对：

```bash
rg -n 'PiRpcSession|PiRpcConfig|build_rpc_session|ExtensionBinding|ExtensionLease|AsterionPrimeSession\(|PrimeSessionBackend\(|pi_base_command' src/asterion/applications/prime
rg -n 'asterion\.applications|dotenv|load_operator_environment' src/asterion/agents/prime src/asterion/runtimes/asterion_prime.py
```

- [ ] 每条命中分类：禁止的真实模型构造消除；保留的 operator 配置解析/领域 executor 必须说明；不以改名 alias 或启动 callback 绕过检查。
- [ ] 最终 focused 顺序：

```bash
npm --prefix packages/typescript/asterion-prime-extension test
uv run python -m unittest -v tests.test_prime_application_entry tests.test_asterion_prime_session tests.test_asterion_prime_backend tests.test_prime_live_model tests.test_prime_extension_tool_contract tests.test_prime_p7_native_installed tests.test_prime_p7_official_installed
make promotion-check
make lint
make docs-check
git diff --check
```

- [ ] 上述是最终整合复核；Task 4–7 已通过且未再次修改的领域测试不再重复。只因新变更/失败扩大检查；所有结果按实际范围记录。
- [ ] 独立 Sol 复审整体所有权与领域语义，关键预算/attachment/unknown effect 合同交 Astra；复审发现先修再重跑相关检查。
- [ ] 按执行时已有授权核实有限 r11l preset：`make asterion-prime-p7-level-witness GAME=r11l LEVEL=1`。若实际 game catalogue 要完整 ID，用该预设已解析的 r11l 精确 ID；不改预算或启动新 BP35。
- [ ] 在执行前读取 Make recipe 确认既有 900 秒 witness、动作限额和 fresh run/evidence root；不借用旧结果，不从 model prompt 传 knobs。若缺授权/外部条件，记录精确未完成项，不伪造 PASS。
- [ ] 检查本次证据的 wheel/resource fingerprint、registered tool set/allowlist、runtime身份、总 deadline、终止与进程清理；不以解题失败自动认定接线失败，也不把接线成功当跨领域能力完成。
- [ ] 状态文档分别记录 implemented、provider-free verified、packaged/live evidence；P2 和确定性 witness 原分类保留，专用压缩仍写未完成；不覆盖既有历史证据。
- [ ] 提交代码/测试与状态文档的最终小批次，记录每步真实命令：`git commit -m "docs(prime): record standard entry migration and packaged evidence"`；最后 `git status --short` 无本任务遗漏。

## 复审与执行交接

根代理已按 writing-plans 自审：独立入口与外部应用验收对应 Task 1/2/4–8；模型策略对应 Task 2/4/5；工具资源对应 Task 3/4；恢复/授权对应 Task 4/5/7；打包与证据对应 Task 8。已修复过渡期接口破坏、核心 P7 分派及缺失授权参数；CLI 待定是明确的范围排除，不是实施占位项。
Task 1–3 核心类型、Task 4 persistent owner 和 Task 5 attachment 是合并前合同检查点。
不能把 temporary wrapper 合并后直接标记整个 Task 40 完成；最终以 Task 8 的旁路清单和证据为准。
本计划不重跑模型，不开始生产实现；执行以批准设计、AGENTS.md 和执行时持续有效的授权为准。
