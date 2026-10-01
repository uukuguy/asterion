# Live Session Checkpoint

> Updated: 2026-10-01. Session paused at the user's request; this is not a final handoff.

## TL;DR

- 已把全局经验设计的三项基础能力落到代码：统一 `ObservationState`、游戏级机制持久化、候选反事实模拟/子目标进度。
- 已接入 P7 Broker、Operator、IPython facade、live worker tool registry 和 prompt；持久化读取明确 `execution_authority=none`。
- SP80 纯 P7 L1→L2→L3 尚未重新验证；最近一次 L2 在约 10 分钟停止，L1 使用已验证前缀回放，不能算本轮重新求解。

## 已验证事实

- `d85b03b8` / `f7c51d1b`：`ObservationState` 支持 frame、输入类型、HUD、timers、resources、entities、relations、events；值递归冻结、JSON 安全、可哈希。
- `00b4544e` / `b03b6368`：`GameMechanicsStore` 按精确 game identity 原子持久化机制、条件、效果、scope、证据和冲突；文件有界；读取不授予执行权限。
- `63492b13` / `74f26d89` / `eb43b2ed` / `5a2f8d95`：反事实模拟保留 confirmed/hypothesis 分支、分歧与子目标进度，history-only 账本不会伪造状态，始终不执行动作。
- `b1a114a3`：上述能力已接入 Broker 和 P7 工具面；Broker 会把动作候选证据写入游戏级机制存储，冲突会落盘为 conflict；统一观察摘要已修复只读映射不可序列化问题。
- 最小回归通过：164 项 P7/Broker/工具/新模块测试；官方 Operator 12 项通过；`py_compile` 和 `git diff --check` 通过。
- 离线优化保持关闭；没有路线注入。

## 当前判断

- 受限规则闭环已经实现；全局人类式玩法模型仍未完成。
- 新增持久化机制目前是 advisory memory，不能直接进入 `act_checked`；真正的 planner authority 仍来自当前 WorldMap 证书和 retrodiction。
- `ObservationState` 已支持扩展字段，但 ARC native adapter 的历史记录仍主要以 frame/state/level 为证据；HUD、对象关系和事件需要真实适配器数据才能形成可验证经验。
- 反事实模拟已经能比较假设分支，但尚未在真实 SP80 中证明它减少重复探索或提高步数效率。

## 未完成边界

1. 修正或复核 `GameMechanicsStore` 与 Broker 的跨级证据合并策略，并补全冲突/确认的真实运行统计。
2. 让 native observation/history 在不破坏 ARC 协议的情况下保留可验证的 metadata 证据。
3. 在纯 P7、offline disabled 条件下重跑 SP80 L1→L2→L3；报告当前级别步数、候选/confirmed/simulator、prediction match/conflict、是否使用持久化经验。
4. 用冷启动和热启动对照确认“越玩越熟练”。三次连续失败或发现机制缺陷时先修复，再继续扩展。

## 下一动作

1. 恢复后先运行 `make lint`、`make docs-check` 和新旧 P7 聚焦回归，确认暂停前接入没有协议回归。
2. 检查 Broker/Operator 的新工具在真实 worker 中可调用，再执行一次短时 SP80 运行。
3. 只有出现 confirmed model、反事实分支实际影响决策并完成 L2/L3，才能推进全局能力结论。

## 关键文件

- `src/asterion/applications/prime/p7/observation_state.py`
- `src/asterion/applications/prime/p7/game_mechanics.py`
- `src/asterion/applications/prime/p7/hypothesis_simulator.py`
- `src/asterion/applications/prime/p7/broker.py`
- `src/asterion/applications/prime/p7/operator.py`
- `src/asterion/applications/prime/p7/live.py`
- `docs/architecture/prime-p7-cognition-and-experience.md`
- `docs/superpowers/specs/2026-10-01-prime-p7-experience-induction-design.md`
