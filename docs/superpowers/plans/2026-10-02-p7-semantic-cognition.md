# P7 Semantic Cognition Implementation Plan

**Goal:** 实现 [游戏经验认知主合同](../../architecture/prime-p7-cognition-and-experience.md)。用户已授权保存后完整实现。

**Architecture:** Python 语义账本和 session 驱动实验；Broker 绑定真实动作证据；Prime 注册工具和自动上下文连接 LLM；独立本地探索入口与新会话 witness 分离。

**Tech Stack:** Python/unittest、Prime TypeScript 扩展、现有 Pi operator 与本地 ARC 引擎。

## Global constraints

同游戏同 seed 同 L1；语言假说优先；不注入旧成功路线；持久化不授予执行权；RESET 保留认知并清理 episode；探索不使用人类 baseline 作为停止条件；完整实际动作保留；真实能力与合成测试分开；完成前独立代码评审。

## Tasks

- [ ] 1. `semantic_cognition.py` 与测试：精确身份、原子持久化、提案验证、三态和自然语言报告。
- [ ] 2. `cognition_session.py`、`broker.py` 与测试：实验预注册、当前帧绑定、真实结果评估、状态与事件、RESET 清理、READY/STOPPED。
- [ ] 3. `ipython_host.py`、`live.py`、`tool_registry.py`、TS 扩展及资源：统一 `p7_cognition_update(payload: dict) -> dict` 并同步桥接契约。
- [ ] 4. `operator.py`、`prompt.py`、`Makefile` 与 guest 环境：独立 cognition 模式、上下文注入、报告/事件落盘、普通 witness 只读加载。
- [ ] 5. 独立评审变更代码；修复 findings；运行 Python/TypeScript/lint/docs/promotion 门禁及真实 L1，记录证据。

## Required commands

```sh
uv run python -m unittest -v tests.test_prime_p7_semantic_cognition tests.test_prime_p7_cognition_session
npm --prefix packages/typescript/asterion-prime-extension test
npm --prefix packages/typescript/asterion-prime-extension run check-resource
uv run python -m unittest -v tests.test_prime_p7_bridge_dispatch tests.test_prime_p7_live_command tests.test_prime_p7_tool_registry tests.test_prime_extension_tool_contract
make lint
make docs-check
make promotion-check
make asterion-prime-p7-cognition GAME=sp80 LEVEL=1
make asterion-prime-p7-level-witness GAME=sp80 LEVEL=1
```

每个组件先写有意义的边界测试并验证失败，再实现并验证通过。真实运行的认知报告、动作总数、封存和 replay 结果必须来自本次输出；未过关不冒称过关，未获得非空图景不冒称认知生效。
