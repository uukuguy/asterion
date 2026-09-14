# Repository Guidelines

本项目是长时间自主研究型 AI 编程

- 任务编排
For GPT:
积极使用 subagent完成具体任务，合理选择astra, sol,terra,luna 模型完成各项具体工作。根 sol 做集成调度，机械检查简单处理等重复性工作交给 Luna；日常独立脚本代码编写修复等工作交给 terra 完成；主力编程等工作交给sol，一直出错则该任务切换成 astra 编写；最复杂的契约设计、恢复合同、训练架构、复杂故
障和最终关键复审等由 astra 处理，必要时安排 Sol 独立复审
For Claude:
积极使用 subagent完成具体任务，合理选择Fable, Opus, Sonnet, Haiku 模型完成各项具体工作。根 Opus 做集成调度，机械检查简单处理等重复性工作交给 Haiku；日常独立脚本代码编写修复等工作交给 Sonnet 完成；主力编程等工作交给 Opus，一直出错则该任务切换成 Fable 编写；最复杂的契约设计、恢复合同、训练架
构、复杂故障和最终关键复审等由 Fable 处理，必要时安排 Opus 独立复审

**DeepSeek 后端硬规则**：当 `ANTHROPIC_BASE_URL` 指向 DeepSeek（如 `https://api.deepseek.com/anthropic`）时，**禁止给任何 subagent 指定 model**——一律继承会话的 `ANTHROPIC_MODEL`，只使用该变量指定的模型。

**决定（2026-09-14，用户）**：本后端统一使用 `deepseek-flash`（即 `deepseek-v4.1-flash`），**不做分档**。该模型能力已足够，无需按任务难度切换，"最难契约用 pro"的旧分工在此后端取消。

原因（2026-09-14 实测，勿凭直觉推翻）：

- DeepSeek 的 Anthropic 兼容层把**任何 `claude-*` 模型名静默映射到 `deepseek-v4-pro`（最贵档）**。实测：`claude-opus-4-7` → 返回 `deepseek-v4-pro`。
- 裸别名直接报错：`opus` → `The supported API model names are deepseek-flash, deepseek-v4-pro, but you passed opus`。
- `Agent` 工具的 `model` 参数**只接受 `sonnet/opus/haiku/fable` 别名**，无法传 `deepseek-flash`。所以"按难度选模型"在这套后端上是不可能实现的——传任何别名都等于选最贵模型，且与意图相反（本想派 Haiku 省钱，实际跑 pro）。
- 因此唯一安全的做法是**完全不传 model**。上面的 Fable/Opus/Sonnet/Haiku 分工仅在非 DeepSeek 后端（原生 Anthropic 端点）下适用。
- 同理 `ANTHROPIC_SMALL_FAST_MODEL` 必须显式设为 `deepseek-flash`；未设置时，后台任务（文件摘要、标题生成、后台安全复审）会使用 Claude 的 haiku 模型名，**同样被映射到 `deepseek-v4-pro`**。
- 解题研究而非发布产品，测试不需要过于严苛极端，保证边界控制断言即可。不要在测试环节花费的过多时间
- 研发阶段复审和测试的重点应该是变更后代码实现的评审
- 及时完整提交，不要积累大量未跟踪、未提交的文件

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

Preserve this direction:

```text
CLI/host → selected provider → assembly → catalog/composer
         → exact implementations → runner → runtime/host services
```

Framework modules (`runtime/`, `packages/`, `assembly/`, `runner/`, `services/`) must remain domain-neutral. Products may depend on them; they must not import DCI implementations, tests, or adjacent source trees. Runtime adapters only translate native commands/events into the public protocol.

## Protocol and Composition Invariants

`asterion.agent-runtime/v1`, `asterion.capability/v1`, `asterion.capability-package/v1`, and `asterion.application-assembly/v1` are closed contracts. Schemas under `schemas/`, Python validators, and TypeScript validation must agree. IDs are canonical, versions exact, and arrays sorted and unique.

Manifests describe compatibility, not authority. Never place prompts, credentials, commands, executable paths, environment values, provider configuration, or mutable state in them. Catalogs use explicit local roots, direct JSON children, and exact `package_id@version`; do not add source scanning, ranges, registries, hidden precedence, or symlink traversal.

Composition must be deterministic and fail closed on ambiguity, missing edges, or cycles. Executable kinds require exactly one implementation binding; policies remain declarative. Inputs/results stay immutable, and emitted events, artifact media types, and artifact IDs must satisfy the manifest.

## Runtime, Provider, and Host Boundaries

Runtime streams require one run ID, contiguous sequences, matched tool calls/results, and one terminal event. `asterion list` remains metadata-only; loading imports one selected entry point. Provider resources stay under their root, and all identities must agree exactly.

Runners receive a resolved plan, runtime, implementations, cancellation signal, and read-only host services. They do not discover, authorize, retry, persist, schedule, start services, or choose runtimes. Execution stays sequential and stops on failure/cancellation.

Host services are operator-owned and explicitly injected. `executor.controlled` does not itself authorize commands. The Rust executor applies trusted policy, direct invocation, cleared environments, deadlines, output caps, and cancellation; it is not an OS sandbox.

The repository `.env` already contains operator-owned backend LLM configuration. Application or operator integration may resolve that configuration and inject an exact host service; framework modules must never read `.env`, credentials, or provider settings directly. A user-facing “small verification” is one preset action: it must not ask the user for provider, model, cost, or deadline knobs. The integration enforces finite controls internally and exposes only public-safe status. Missing Native host wiring is an application-integration task, not a request for the user to budget or configure a backend.

## Route Changes by Intent

- **Runtime:** add `src/asterion/runtimes/<name>.py`, an exact factory binding, capability mapping, and tests. Do not fork capability manifests by runtime.
- **Capability/package:** add manifests and implementations under `src/asterion/capabilities/`, composition/output tests, then exact assembly/provider bindings.
- **Application:** add exact refs under `src/asterion/applications/<provider>/assemblies/`, allowed runtimes, and provider exposure. Keep executable paths out of JSON.
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

Use `unittest` (`test_<surface>.py`, `Test...`, `test_<behavior>`) and `subTest` matrices. Cover success, failure, immutability, identity, determinism, cancellation, and redaction.

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
