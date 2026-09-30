# Live Session Checkpoint

> Updated: 2026-09-30. Session remains active.

## 已验证事实

- 同题 WorldModel、TransitionModel、Playbook、声明式机制证书和 replay expectation gate 已实现；设计与计划见 `docs/superpowers/specs/2026-09-30-prime-p7-same-game-world-model-design.md` 与对应 plan。
- P7 应用级工具链已注册到 `P7ToolRegistry`，并同步 Python bridge、worker RPC、TypeScript extension 与打包资源；工具包括 world model、Playbook、retrodiction 和 hypothesis writer。
- 活动提示已移除固定 `ACTION1` 到 `ACTION7` 语义，要求按当前游戏证据推断动作槽位，并在批量动作前读取同题模型与 retrodiction 状态。
- VC33 L1 已完成可提交的部分关卡前缀：3 个当前关卡动作，baseline/action cap 7，sealed trace 与 replay verified 均为真；`promotion=unpromoted` 不否定部分提交资格。
- 初始帧视觉先验已接入：每次运行最多记录 32 个候选，作为 `entities` 层 hypothesis 注入同题上下文；不会自动确认墙、地板、物品或终点。
- retrodiction 诊断现在暴露机器可读 `reasons`；VC33 本次为两次 `prediction-mismatch`、第三步预期匹配，路线采用 3/3 完成。根因是前两步把 state hash 填入 frame hash 字段；Playbook 的三条 conflict 包含历史元数据，不能当作本次计数。
- VC33 初始模型为 12 个视觉 hypothesis；通关后刷新为下一级的 15 个，版本 28 = 12 + 刷新 1 + 15。无 hypothesis/probe 写调用，0 confirmed facts；本次证明路线执行有效，未证明规则学习有效。完整复盘见 `ASTERION-PRIME-P7-EVIDENCE.md` 的 2026-09-30 节。
- VC33 L1 重跑后 Playbook 已实际保存 12 个 L0 `visual_hypotheses`，并保留 3 步 checked route；这是首次验证视觉候选跨运行持久化。confirmed facts 仍为 0，尚未证明 L2 模型会有效利用这些候选。
- 离线 ARC fresh-engine replay 为每个候选动作生成 bounded expectation；在线采用候选前要求期望数量完整，首个 action 或 expectation mismatch 即停止采用。
- 223 个组合 P7 测试通过；`make lint`、`make docs-check`、变更模型模块 Pyright 和 `git diff --check` 通过。
- 完整仓库 gate 跑完 3509 项测试，唯一失败是 `test_full_promotion_python_environment_keeps_real_npm_ci_offline` 观察到一次网络请求；这是环境 gate 失败，不是 P7 回归。
- 近期测试夹具修复已提交于 `cc9c991e`；此前核心提交包括 `8c58db5e` 和 `e06f69ff`。

## 当前判断

- 机制实现已达到代码与离线回放验证边界，可以进入一次受控 live P7 验证；尚不能把 focused tests 解释为通关率或步数提升。
- 同题确认事实可以复用，未确认假设只做一次区分探测；任何跨游戏迁移仍被 identity gate 拒绝。

## 历史归档

- 旧 checkpoint 中“Task 3 进行中”、固定 ACTION 方向语义、单独等待 subagent 的判断均已过时。
- 旧 BP35/DC22 运行记录只作为历史证据，不可直接当作当前 P7 路线或模型能力证明。

## 未完成边界

- 完整仓库 gate 已完成，但离线 npm-ci 环境测试失败，后续若需发布必须单独修复或复现实验环境。
- TU93 L1 受控练手运行已执行但由操作者主动取消：当前关卡 18 个动作、0 关完成；external_cancel，未封存/未回放验证，不计通关。离线候选 19→18 步，但 P7 首动作偏离候选 ACTION4，route adoption 跟随 0；世界模型版本 0，说明在线机制事实没有建立。
- VC33 L2 显式运行 `p7-live-20260930021849-b4a26cbd9f741b76de1b4172` 在 22 总动作（19 个当前 L2 动作）后由操作者停止，levels_completed=1；这是 unsuccessful evidence，不是新 L2 结果。此前 `next` 自动选择 L4 的错误目标运行同样不计结果。

## 下一动作

1. 用显式 L2 运行验证 `p7_playbook` 能读到这 12 个 L0 visual hypotheses，并记录模型是否据此减少盲试；不要使用自动 `next` 选择高于目标的关卡。
2. 防止 checked plan 的 state/frame hash 混用，并将 caller prediction mismatch、replay witness 成功、确认机制冲突和历史 Playbook 元数据分层。
3. 继续保留 hypothesis 只能被动作证据升级的边界；不要把视觉候选直接当成 confirmed 规则。
