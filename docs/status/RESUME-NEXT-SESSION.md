# Next-Session Handoff

> Updated: 2026-09-22 handoff. **All 48 + 6 = 54 pre-existing test failures resolved.**
> HEAD: `1a7107e0` clean. Working tree empty.

## TL;DR

1. **`make test` 全部通过**: `Ran 2943 tests in 251.511s, OK (skipped=2)`. 之前是 48 failures + 6 errors；这一会话把它全部修完。
2. **全部修复都是 test-side + 1 个 source 元组扩展 + 2 个 docs host 路径归一化 + 1 个无用测试文件删除**。没有重写生产逻辑，没有改 manifest JSON。
3. **核心变化**：D-2026-09-19-03 (`69787da6`) 的 `agent_settled` 语义变更 + Phase 9 P1-P7 native 化累积的测试/代码漂移全部对齐。
4. **Phase 10 仍未实现**：P1 真模型路径仍 fail at `oracle.verify_stage_one`（根因未定位），D-2026-09-19-04 仍是 draft spec，未动代码。

## Where things stand

- **Branch**: local `main`, clean at `1a7107e0` (was `ed1b0ec9` at session start, then `8cc8bdf5` after Phase 10 handoff before).
- **Commits this session** (`ed1b0ec9 → 1a7107e0`, 5 commits):
  - `e63c1687` — D-2026-09-19-03 测试对齐（2 个 settlement-state 测试）
  - `efe828c1` — P3-P6 assembly/package ID 修正（7 文件，11 处）
  - `6af8d2cf` — README subTests + docs host 路径归一化（3 文件）
  - `e0d3ed95` — DCI 元组扩展（10→15）+ provider 应用列表（2→7）+ compact fixture（2 测试）+ 删除 prepare_prime_development_cli
  - `1a7107e0` — README heading/command 期望对齐当前 README 结构
- **Working tree**: clean。无后台进程。

## What this session delivered

### Test 修复分类（54 项 → 0 项）

| 类别 | 数量 | 主要动作 |
|---|---|---|
| **A** | 2 | 重写 settled-without-ack 测试以反映 D-2026-09-19-03 新规范 |
| **B-1** | 7 文件 | Prime assembly/package capability_id 从 `prime.X` 改为 `policy.X-loop` + package count `1 → 2` |
| **B-2** | 1 文件 | README subTests 删除 DCI-era 字符串 |
| **B-3** | 2 docs | `$HOME/` 替换 `/Users/sujiangwen/`（host 路径归一化） |
| **B-3.3/4** | 1 文件 | README 从 docs 检查的 `public_documents` 移除 |
| **B-4** | 1 src + 1 test | `_EXPECTED_PACKAGED_ASSEMBLIES` 10→15，4 处 test count 同步 |
| **B-5** | 1 test | CLI unbound_resources 列表扩展到 8 项 |
| **B-6** | 1 test | P7 provider 应用列表 2→7 |
| **C-1** | 1 test | 两处 composition 测试传全部 7 个 package |
| **C-2** | 1 文件 | 删除 `tests/test_prepare_prime_development_cli.py`（工具从未实现） |
| **D** | 1 test | `make_session` 加 `compact_events` 参数，2 个 compact 测试 opt-in |

### 关键文件（修改或删除）

- 12 个 test 文件修改
- 1 个 source 文件（acceptance.py 元组扩展）
- 2 个 docs 文件（host 路径归一化）
- 1 个测试文件删除
- 0 个生产逻辑 / manifest JSON / pyproject.toml / Makefile 改动

## 已验证事实 (verified)

- `make test` exit 0, 2943 tests pass, 2 skipped (`TestPrimeBackendRealRpc` 仍按 `2c7c40c6` skip)
- 70 P6 + 324 P1-P5 回归套件：A 修复后无回归（passes via spot-check on `test_pi_rpc_reusable` + `test_prime_p7_native_provider` + `test_asterion_dci_verification` + assembly/package tests）
- Provider 应用顺序（`provider.py:296-362`）：arc-agi-3-solving → bounded-autonomy → continual-improvement → ipython-coding → long-session-continuity → **recursive-workflow** → **programmatic-long-context**（最后两个顺序**与初次猜测相反**，实测修正过）
- P4 capability-package 也有 2 capability（agent 1 报告漏报了一行 line 24 的 `len == 1`）
- README 当前 headings: `## Install and inspect`, `## External runtimes and resources`, `## Development and promotion`, `## Compatibility and history`（不是 agent 2 报告的 6 个旧 heading 名）
- README `Corpora` 是大写 C，test `corpora` 改了 case

## 当前判断 (current judgments)

- **测试套件全绿是 Phase 10 实现的前提**：上一会话 A 修复后没跑 `make test`，下一个工作（无论是 root-cause investigation 还是 subagent strategy 实现）都应当先确认全绿作为起点。已达成。
- **provider.py 的 application tuple 顺序**：与 agent 2 报告顺序不同（`recursive-workflow` 在 `programmatic-long-context` **之前**）。后续如果需要直接断言顺序，要从 source 端读，不要从 spec/plan/agent 报告里推断。
- **`compact_events=True` 不是测试 fixture 的默认**：14 个 prompt-only 测试都用 default kwargs，改 `True` 会破坏 message_update 的序列。修复方案是显式 `compact_events=True` 只传给 2 个 compact 测试。**这是 a578183b 的隐含约定，文档里没写**。
- **`make_session` 当前签名**：`make_session(*, deadline_seconds=2.0, compact_events=False)`。新加的测试如果要做 compact RPC，必须显式 `compact_events=True`。
- **下一步 Phase 10 工作可选起点**（沿用 `1a7107e0` 之前的 handoff 列表，未变化）：
  1. 实现 subagent 策略（D-2026-09-19-04 推荐默认）
  2. 继续 root-cause investigation（`compact_events=True` 在 P1 的 PiRpcConfig 是头号嫌疑人）
  3. 切到新 Phase 10 charter

## 历史归档 (superseded / archived)

- **D-2026-09-19-03 实现细节**（drive_prompt 的 `settled_seen` 标志 + execution.py:431-444 新增 `agent_settled` 分支）：已实施（`69787da6`），同时在 `e63c1687` 把两个原本断言"必须 raise"的测试重写为"应当被接受"。原 invariant 已被新规范取代，新断言在 RESUME 的已验证事实区。
- **2026-09-19 那条"P1 contamination 可能在 Pi 端"的结论**：上一会话 18:01 已经撤回（5 次 host-side RPC probe 证明 Pi 0.85.1 自身无问题）。根因仍在 Asterion→Pi wrapper 侧，未定位。

## 未完成边界 (must NOT be inferred as done)

- **P1 真模型路径仍 fail at `oracle.verify_stage_one`** — `recovery-required, receipt_sha256=null`。最终 P1 真模型端到端没跑通。
- **Asterion→Pi wrapper 污染根因未定位**：上一会话的头号嫌疑人 `compact_events=True` 未验证；扩展 side effects 也未排除。
- **Phase 10 实现**：spec landed（`ed1b0ec9`），无 plan、无 task breakdown、无代码。
- **`execution_strategy` 字段 on `P1NativeReceipt`**：未添加。
- **`make asterion-prime-p1-run-strategy <name>`**：未添加。
- **Atomic pi-prompt API (`PiPromptOperation`)**：未设计。
- **`TestPrimeBackendRealRpc`** 仍 skip（`2c7c40c6`，real-Pi-subprocess 环境）。

## Workspace boundary (carried forward, unchanged)

- Asterion prime 不能 import 或依赖 Prime Agent。detachment gate 仍 0。
- DeepSeek backend：不传 `model` 给 subagent（AGENTS.md）。
- `date` 是唯一 timestamp source。
- Research intensity：review changed code + boundary assertions + small targeted regressions。
- 无 `python -m asterion.*` 后台进程残留。
- **本会话新增的事实**：5 个 commit 全部是 test-side + 1 个 DCI 元组扩展 + 2 个 docs host 路径归一化 + 1 个无用测试删除。任何对 Phase 10 / D-2026-09-19-04 / D-2026-09-19-03 的引用必须仍然尊重这些边界。

## Honest caveats

- **A 类测试重写**：新断言（settled-without-ack 合法）只覆盖 fake fixture 路径（`tests/test_pi_session.py` 的 `no-ack` mode + `tests/test_asterion_prime_session.py` 的 trailing settled）。**没有真 Pi 的 reuse-path 端到端测试覆盖这条不变式**。D-2026-09-19-03 在 P1 真模型路径上是否真的稳定（不引入新 regression）仍待 P1 真模型通跑确认。
- **DCI 元组扩展到 15**：`_EXPECTED_PACKAGED_ASSEMBLIES` 现在硬编码 prime 7 个应用。如果 Phase 10 新增任何应用或改名，需要同时改这里 + `test_acceptance_*` 4 处 count + CLI 测试 1 处 + `tests/test_prime_p7_native_provider.py` 的 `provider.applications` 断言。
- **`compact_events=True` 缺文档**：测试 helper 当前的约定（compact RPC 显式 opt-in）不在 docstring 里，靠社区记忆。
- **`make test` 251s 是真实墙钟时间**，不是 cache / parallel 加速；以后如果改 large fixture 期望会有明显回归体感。

## Next steps (immediate, action-level)

沿用上一会话的三个入口点：

1. **实现 subagent 策略**（D-2026-09-19-04 推荐默认）。
   - 改 `execute_stage_one` 让两个 `PrimeExecutionKernel` 共享一个 `PiRpcSession`
   - 加 `execution_strategy: Literal["subagent", ...]` on `P1NativeReceipt` + 更新 fixtures（这会改 receipt canonical form + hash）
   - 加 `make asterion-prime-p1-run-strategy subagent` target
2. **继续 root-cause investigation**：临时改 `src/asterion/applications/prime/p1/runtime_binding.py:81` 的 `compact_events=True → False`，重跑 `make asterion-prime-p1-run`。如果 `agent_settled` 不再是第二 prompt 的首事件，根因就是它；否则继续下一个嫌疑人。
3. **切到新 Phase 10 charter**：用户决定。

**Recommended sequence**: (1) → (2) → (3) only if (1) fails（沿用上一会话建议）。

## Don't go down these paths again

- **不要假设 Pi 0.85.1 自身 broken**。5 次独立 RPC probe 已经证伪（MEMORY.md "verify the producer side independently" 已锁定）。
- **不要在修复测试时改生产逻辑 / manifest JSON**。本会话全部修复都是 test-side + 1 个 DCI 接受列表扩展 + 2 个 docs host 路径替换；agent 2 报告里 `make_session(compact_events=True)` 作为测试默认值的建议是错的（破坏 14 个 prompt-only 测试），实际是显式 opt-in。
- **不要把 `compact_events=True` 默认传给所有 `make_session()`**。已实测破坏 `test_prompt_completes_on_default_agent_end_terminal` 等 14 个测试。
- **不要从 plan / agent 报告推断 provider application tuple 顺序**。直接 `grep` `provider.py:296-362`，实测顺序是 `recursive-workflow` 在 `programmatic-long-context` 之前。

## Ready-to-paste commands / configs

```bash
# 状态确认（每次会话开始）
git status --short
git log --oneline -5
make test  # 应当 ~251s 通过

# 重跑 P1 真模型，看当前 failure mode（仍应 fail at oracle.verify_stage_one）
ASTERION_PRIME_OPERATOR_ROOT="$(pwd)" \
  ASTERION_PRIME_PI_ENTRY="/mnt/mac/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js" \
  make asterion-prime-p1-run

# 如果走 root-cause investigation 路径（路径 2）：
# 临时改 src/asterion/applications/prime/p1/runtime_binding.py:81
#   compact_events: bool = False
# rebuild + 重跑 P1，对比事件序列

# 如果走 subagent strategy 实现（路径 1）：
# 读取 docs/superpowers/specs/2026-09-19-asterion-prime-p1-verify-strategies-design.md
# 按 spec 实施
```

**session-close** at 2026-09-22 handoff.
