# Repository Guidelines

本项目是长时间自主研究型 AI 编程

## Asterion Prime 总体指导思想

Asterion Prime 面向智能体自主解决人类需要花费大量时间与精力的问题，旨在自主开展长程、开放式、可证伪的计算研究，形成一条人类可理解、机器可复核、证据可追溯、结论可重放的推理链记录。

架构分为 Prime 通用层、领域研究层、领域数据层：通用层提供计算、记忆、工具、证据与执行保障；领域层提供目标、客观规则和真实系统接口；LLM 自主组织假说、建模、实验、推理与行动。研究记录保留程序、实际反馈、反例、认识修订和结论依据，不能用执行日志堆积代替有效认知，也不以细碎的强制认知流程代替模型推理。

当前先在 P7 上实验研究并定型，再推广至其它领域。总体指导思想与已验证能力分别记录；跨领域适用性和研究结论的复核、重放范围需要具体验证。现有协议、依赖方向、授权、预算和未知执行结果等硬性边界继续有效。核心定位见 `docs/architecture/agent-framework.md` 与 `docs/status/DECISIONS.md` 的 D-2026-10-09-01。

- 任务编排
For GPT:
积极使用 subagent完成具体任务，合理选择astra, sol,terra,luna 模型完成各项具体工作。根模型做集成调度，机械检查简单处理等重复性工作交给 Luna；日常独立脚本代码编写修复等工作交给 terra 完成；主力编程等工作交给gpt-6.1-sol high，一直出错则该任务切换成 astra 编写；最复杂的契约设计、恢复合同、训练架构、复杂故
障和最终关键复审等由 astra 处理，必要时安排 Sol 独立复审
For Claude:
积极使用 subagent完成具体任务，合理选择Fable, Opus, Sonnet, Haiku 模型完成各项具体工作。根 Opus 做集成调度，机械检查简单处理等重复性工作交给 Haiku；日常独立脚本代码编写修复等工作交给 Sonnet 完成；主力编程等工作交给 Opus，一直出错则该任务切换成 Fable 编写；最复杂的契约设计、恢复合同、训练架
构、复杂故障和最终关键复审等由 Fable 处理，必要时安排 Opus 独立复审

- 解题研究而非发布产品，测试不需要过于严苛极端，保证边界控制断言即可。不要在测试环节花费的过多时间
- 研发阶段复审和测试的重点应该是变更后代码实现的评审
- 及时完整提交，不要积累大量未跟踪、未提交的文件

**DeepSeek 后端规则**（`ANTHROPIC_BASE_URL` 指向 DeepSeek 时）：

- **一律不传 `model` 给 subagent**，只用会话的 `ANTHROPIC_MODEL`。
- 本后端统一 `deepseek-flash`，不做难度分档；上面的 Fable/Opus/Sonnet/Haiku 分工仅适用于原生 Anthropic 端点。
- `ANTHROPIC_SMALL_FAST_MODEL` 必须设置（`~/openai-coding-deepseek.sh` 已有），否则后台任务也走最贵档。

原因：该兼容层把**任何 `claude-*` 模型名映射到最贵的 `deepseek-v4-pro`**（实测 `claude-opus-4-7` → `deepseek-v4-pro`；裸别名 `opus` 直接报错）。`Agent` 的 `model` 参数只收 `sonnet/opus/haiku/fable` 别名，传不出 `deepseek-flash`，所以传任何别名都等于选最贵档——与"派 Haiku 省钱"的意图正好相反。

## Handoff 跨会话收口合同

用户说 `handoff` 时，直接完成最终会话收口，不再把草稿交回用户确认：停止本会话遗留进程，处理并提交本会话改动，保证 `git status --short` 为空；把核心分析、已验证事实、当前判断、过时归档、未完成边界和下一动作写入 `RESUME-NEXT-SESSION.md`。同步修正 `CURRENT-STATE.md`、`DECISIONS.md`、`docs/status/INDEX.md` 与协作 `MEMORY.md` 的错误或缺失索引，使新会话执行 `project-state resume` 后无需聊天记忆即可继续。

收口必须控制在必要范围：优先更新既有核心文件，不为一次交接扩张新的状态体系；验证以状态一致性、关键路径可检索、无遗留进程和 Git 干净为准。事实分类固定为：

- **已验证事实**：由提交、测试、评估、进程或文件证据直接支持。
- **当前判断**：基于现有证据选择的方向，尚未被端到端评估证明。
- **历史归档**：已否决或被替代但值得避免重走的路径。
- **未完成边界**：不得从局部代码或单元测试推断为任务能力完成。

## Scope and Authority

Asterion is a composable, multi-runtime agent application framework. The wheel defined by root `pyproject.toml` and implemented in `src/asterion/` is authoritative. DCI is the reference product, not a dependency generic framework code may assume. Pi, data, credentials, generated evidence, and the parent DCI baseline remain external.

Python owns orchestration, composition, assembly, and execution; TypeScript validates shared contracts and Node integration; Rust owns controlled execution. Do not duplicate composers or runners across languages without approval.

## Architecture and Dependency Direction

For provider/assembly integration, preserve this direction:

```text
CLI/host → selected provider → assembly → catalog/composer
         → exact implementations → runner → runtime/host services
```

Independent Prime applications consume the standard library directly: application/operator → Prime resource owner → private backend/runtime services. Central registration, provider discovery and CLI dispatch are not prerequisites; an optional provider integration must still follow the direction above.

Framework modules (`runtime/`, `packages/`, `assembly/`, `runner/`, `services/`) and generic Prime infrastructure must remain domain-neutral. Products may depend on them; they must not import DCI implementations, tests, or adjacent source trees. Runtime adapters only translate native commands/events into the public protocol.

## Protocol and Composition Invariants

`asterion.agent-runtime/v1`, `asterion.capability/v1`, `asterion.capability-package/v1`, and `asterion.application-assembly/v1` are closed contracts. Schemas under `schemas/`, Python validators, and TypeScript validation must agree. IDs are canonical, versions exact, and arrays sorted and unique.

Manifests describe compatibility, not authority. Never place prompts, credentials, commands, executable paths, environment values, provider configuration, or mutable state in them. Catalogs use explicit local roots, direct JSON children, and exact `package_id@version`; do not add source scanning, ranges, registries, hidden precedence, or symlink traversal.

Composition must be deterministic and fail closed on ambiguity, missing edges, or cycles. Executable kinds require exactly one implementation binding; policies remain declarative. Inputs/results stay immutable, and emitted events, artifact media types, and artifact IDs must satisfy the manifest.

## Runtime, Provider, and Host Boundaries

Runtime streams require one run ID, contiguous sequences, matched tool calls/results, and one terminal event. `asterion list` remains metadata-only; loading imports one selected entry point. Provider resources stay under their root, and all identities must agree exactly.

Runners receive a resolved plan, runtime, implementations, cancellation signal, and read-only host services. They do not discover, authorize, retry, persist, schedule, start services, or choose runtimes. Execution stays sequential and stops on failure/cancellation.

Host services are operator-owned and explicitly injected. `executor.controlled` does not itself authorize commands. The Rust executor applies trusted policy, direct invocation, cleared environments, deadlines, output caps, and cancellation; it is not an OS sandbox.

### Prime 应用入口与私有底层

应用通过 `src/asterion/agents/prime/application.py` 的 `prepare_prime_application`、`PrimeApplicationSpec` 与 `PrimeOperatorContext` 使用标准库；prepare 不启动 Pi。Pi、RPC、扩展加载、会话与工作区生命周期及清理由 Prime 内部管理；应用提供领域目标、工具、数据与完成/续跑条件，不自行创建 Pi/RPC 对象注入 Prime。Task40 已按用户授权迁移 P1、P3–P7 的已有真实模型路径（包括 P7 narrator）；operator 解析配置并注入上下文，通用核心不读取 `.env` 或认证 profile。P1–P6 使用 `deepseek/deepseek-flash`，P7 使用 `openai-codex/gpt-6.1-sol`；P2 当前仍为无模型的本地检索机制，其自主能力补全另列。独立应用不以中央注册或 CLI 为前提；CLI 定位待定。统一接入与实际解题能力的验证分开，最终打包/实跑状态见 Task40 与当前 checkpoint。D-2026-10-10-03 取代此前暂缓迁移的范围限制；专用代码摘要接通仍单独验证。

### Prime 应用级工具（当前以 P7 验证）

应用级工具注册是 Prime 应用的通用机制：通用 TypeScript `registerPrime` 注册 IPython 与声明的应用工具；P7 领域描述与上下文 hooks 位于 `p7-tools.ts`。wheel 同时打包 `src/asterion/applications/prime/resources/` 下的 `ipython-extension.mjs`、`p7-research-extension.mjs` 和 `p7-legacy-extension.mjs`，分别用于通用、P7 research 和 legacy 模块。Prime 管理扩展加载与 bridge 传输，P7 的 `p7/tool_dispatch.py` 将领域工具映射到 `P7ClientFacade`（`p7_mechanics_prior` 对应 `mechanics_prior`）。注册集合必须与 artifact 描述及 Pi allowlist 精确一致。当前实用领域验证以 P7 为主；不要用 prompt 伪造注册，也不要在通用 runtime 另造一套注册机制；改工具时同步更新 TypeScript、打包资源、对应应用 bridge 和测试。

必需的状态/观察结果由应用直接追加到模型上下文；只把有明确使用场景的查询或动作工具注册给模型，并在工具描述中写清调用时机、输入和返回结果。减少或新增工具时同步修改 Pi allowlist、TypeScript 注册、Python bridge、prompt 说明和测试。

### NOTES、P7 研究适配与验证范围

通用 Prime 负责上下文归档、cursor／projection、资源与恢复边界；P7 提供 NOTES 研究内容、真实观察和领域工具。当前工作上下文以已接受 NOTES 为 epoch，旧明细按引用读取；普通 NOTES 与 Pi 原生手动／自动压缩分开。Task43 的原生上下文、ACK／checkpoint／resume、worker 连续性及 metadata 修复有具体验证，不能因此宣称专用代码摘要已接通或完整历史认知等价。

P7 新研究默认不加载历史经验，过去运行材料须明确 process opt-in 或选定 resume。现代 solve／resume／sweep 与监督研究的 actor-model rollout 只执行模型自己写出的程序；逐动作宿主评估和已识别致命风险拦截不证明模型正确或未来安全。主动调用与 host_auto 独立记录。模型可见 cell 历史只包含 actor cells，私有 kernel 证据保持完整。通用 Prime 不接收 ARC 机制或隐藏引擎语义。

历史官方 100.00 属于原代码身份和有经验累计研究口径；Task40 接入验证、Task43 局部迁移修复及 Task52 用户中止的 5/9 均按各自范围记录。后续 cache／cost 字段已实现，Task52 原实跑明细不可补回；缺失／部分覆盖仍为 unknown，`pi_sdk_estimate` 不等于账单。不能从 token 总量推断实际支付，不能将后续接口测试推广为原实跑验收。

### 应用调用容量

有限调用容量由应用／operator 配置，经 selection、不可变 options、实际 Prime authorization 与执行计数器传递同一个值；预设缺省值不能被当成框架硬上界。普通 P7 solve／sweep 缺省 model1024／tool4096，可通过 operator 的 `ASTERION_PRIME_P7_MODEL_CALLBACKS` 与 `ASTERION_PRIME_P7_TOOL_CALLBACKS` 配置正整数容量，配置不进入模型环境。冻结 witness／official／autonomy 与显式监督模式保留独立授权规则；配置不能产生无上限授权。触限必须记录实际配置值、观测值及具体资源代码，不得因记录阶段为 `pi.prompt` 而归因为 RPC 管道故障。

### P7 覆盖审查与明确探针

覆盖未知默认先返回 `model-coverage-review`，保留缺口、微步与证据；不得报告完就自动推进。仍需探索时，使用匹配当前观察／动作／登记／内核代际的已返回审查，提交单步 `purpose: probe`、非空 goal 和 `risk:`／`cost:` assumptions。所有未评估探针还必须由应用通过 `build_p7_operator_resources(..., unknown_probe_action_limit=N)` 注入有限额度，缺省 0；模型声明、计划字段、改名或 NOTES 不授予或补充权限。额度作用域为新建 host／attempt，续跑默认不继承，实际派发前消耗，未知执行结果不退还，缓存计划不重复消耗。应用明确接受未知风险仍不能称安全；缺失模型／检查器、计算失败、非法或不可用证据不得凭额度绕过。探针不是安全证明，不能绕过致命风险、适用性未知、执行未知、取消或预算。RESET 保留恢复边界，不清除反例。新登记模型的当前运行同关回测保留矛盾、未知及不可比较项；只改名字或 NOTES 不算修复。回测同时保留 predicted_outcome、predicted_risk、coverage、findings 和证据引用；条件性致命识别不等于完整死亡轨迹复现，覆盖不完整仍为 unknown，未评估探针实际死亡记 death_not_assessed。不要将任意模型 JSON 硬比为真实画面，也不要把局部回测推广为完整规则认证。见 D-2026-10-13-02 与当前 checkpoint。

### P7 改动与部署验证

研发阶段优先复审变更后的实现，按触及边界运行定向 TypeScript／Python 检查；改打包资源、入口、schema 或发布假设时运行 `make promotion-check`。工具注册改动须核对 wheel、扩展 artifact、Python bridge 与 allowlist 身份一致。源码或 provider-free 打包检查只能记为相应软件验证，不能宣称真实部署或解题效果完成。

新模型／游戏实跑不由代码改动、文档收口或已有配置自动授权；只有用户授权相应实验时才使用 `make asterion-prime-p7-level-witness GAME=<...> LEVEL=<...>` 等预设，冻结源码／wheel 身份并记录实际运行、清理及未完成边界。已停止试验不得自动续跑。纯文档变更以 `make docs-check` 与内容／索引一致性检查为准，不追加全量回归或真实试跑。

The repository `.env` already contains operator-owned backend LLM configuration. Application or operator integration may resolve that configuration and inject an exact host service; framework modules must never read `.env`, credentials, or provider settings directly. A user-facing “small verification” is one preset action: it must not ask the user for provider, model, cost, or deadline knobs. The integration enforces finite controls internally and exposes only public-safe status. Missing Native host wiring is an application-integration task, not a request for the user to budget or configure a backend.

## Route Changes by Intent

- **Runtime:** add `src/asterion/runtimes/<name>.py`, an exact factory binding, capability mapping, and tests. Do not fork capability manifests by runtime.
- **Capability/package:** add manifests and implementations under `src/asterion/capabilities/`, composition/output tests, then exact assembly/provider bindings.
- **Independent Prime application:** use the standard library owner; supply domain goals, tools, data and completion/continuation hooks. Keep backend resources private to Prime and resolve operator configuration outside generic code. No central registration or CLI is required.
- **Provider/assembly application integration:** add exact refs under `src/asterion/applications/<provider>/assemblies/`, allowed runtimes, and provider exposure. Keep executable paths out of JSON.
- **Protocol:** update canonical schema, Python validator/types, TypeScript types/validation, and `valid-*` plus `invalid-*` fixtures under `tests/fixtures/<protocol>/v1/`.
- **Host service:** define a narrow protocol, declare the assembly capability, inject it only after host preflight, and test missing-service/redaction paths.

## Security, Privacy, and Cost

Trust-boundary failures must fail closed. Public surfaces must not expose prompts, answers, credentials, provider payloads, corpus text, raw output, host-service values, or private paths. Assert redaction with sentinel secrets.

`list`, `describe`, `acceptance`, `make test`, and `make check` are provider-free; `preflight` checks readiness only. `basic`/`complete` may perform bounded Agent/Judge work. Full benchmarks and paper reproduction require separate authorization and a finite budget. Configuration, caches, and prior evidence never grant execution authority.

## Browser Session Continuity

When browser interaction is required, reuse the already-open browser instance and
its authenticated profile. Do not create a separate browser profile, isolated
context, or temporary session that would require the operator to sign in again.
If the existing session has expired or is unavailable, report that exact
condition before requesting any operator action.

## Verification and Evidence

Review the changed implementation first. Use focused `unittest` (`test_<surface>.py`, `Test...`, `test_<behavior>`) and `subTest` matrices for affected behavior and trust boundaries: relevant success/failure, immutability, identity, determinism, cancellation and redaction. Avoid excessive test expansion for research-stage changes. The commands below are available checks, not an unconditional sequence for every change; broaden only when scope or evidence requires it.

```bash
uv run python -m unittest -v tests.test_package_execution
make test
make lint
make docs-check
make check
```

Run `make promotion-check` for packaged resources, entry points, schemas, or distribution assumptions. **Implemented** means code and an entry point exist; **Verified** requires a named passing command in its stated boundary. **External-limited** and **Not rerun** must never be promoted to PASS.

## Review Checklist

Before review, confirm ownership, dependency direction, identities, schema/fixture updates, pre-execution rejection, redaction, and boundary tests. PRs must state the architectural surface, verification commands, cost class, and compatibility impact. Keep commits focused.
