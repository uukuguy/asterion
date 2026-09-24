# Live Session Checkpoint

> Updated: 2026-09-25 02:26 CST. **Session remains active — not a final handoff.**

## 当前任务

完整实现 P7 的 ARC-AGI-3 整题求解和官方 Competition scorecard 提交能力。用户纠正了先前把单关见证当作 P7 完成的设计错误。工作在隔离 worktree `.worktrees/p7-official-submission`、分支 `p7-official-submission`；尚未合入主工作区。主工作区用户自有的两条 Makefile 注释不得覆盖。

## 已验证事实

- `f3a6b14a`/`dadc431d` 让本地选题从严格校验的元数据目录解析；普通选择目标为整题 `win_levels`，短题号仅在唯一时有效。
- `d6f64306` 把整题成功限定为关卡数吻合且 SDK 状态为 `WIN`；Broker、回放和私有回执遵循按题目计算的有限动作上限。旧单关回执摘要保留。
- `21e2b3cd`/`b8097439` 把 `make asterion-prime-p7-solve GAME=<题号>` 改为整题，单关验证移至 `asterion-prime-p7-level-witness GAME=<题号> LEVEL=N`。旧 `.env` 目标关卡会被明确拒绝，避免静默降级。清单区分已验证单关与整题 WIN。
- `e9aea673` 修正运行时工厂的 500 动作硬编码；安装 wheel 的假引擎通过真实运行时装配完成 LS20 七关并达到 `WIN`。118 项 P7 测试、lint、docs-check 通过；独立复审无 Critical/Important。
- `d3a0bad6`/`bcc981a1` 新增 `p7/official.py`，假 SDK 的 19 项测试覆盖官方目录、受控空本地目录、Competition 模式、单卡每题一次 make、SDK 自动初始 reset、精确 game_id/guid、ACTION6/RESET、完整关闭与中断关闭分离。独立复审通过。此适配层尚未接入求解器。
- `70930aa8` 更新设计与计划：官方 baseline 可缺失，本地强制计算 `partial_game_score` 的能力合同不可用于官方。需要独立的无分数 gameplay 能力与回执，由关闭后的服务端 scorecard 决定官方分数。
- 当前没有 `ARC_API_KEY` 可用；尚未执行真实官方 API/model 调用，也未真实验证任一游戏整题通关。以上均为无模型或假 SDK 证据。

## 当前判断

- 用新的应用层 gameplay 能力共享 P7 Broker 与 Pi 运行循环，提供无本地分数的逐题证据；官方 coordinator 在全部可见游戏尝试后关闭一张 scorecard，并严格核对服务端结果。历史 OFFLINE 回执及打包合同保持不变。
- 官方 SDK 会混合本地目录与 API 游戏，并可能在 `make(exact_id)` 时按短题号取到不同版本；适配层已用空目录和实际 wrapper 身份校验关闭风险。

## 未完成边界与下一动作

1. 实现 `ArcBroker` 的窄游戏合同、无分数 gameplay 能力/assembly/runtime/trace，并用 baseline 缺失的假官方游戏跑通安装包装配。
2. 实现官方 coordinator：逐题运行、有限控制、异常后继续或中断、服务端逐题结果和总分校验、私有恢复记录与官方回执。不得用第二次 `make` 回放远程游戏。
3. 加入 `official-preflight` 与 `official-submit` Make 命令，更新操作指南，运行 P7 测试、lint、docs-check、promotion-check 和全分支关键复审。
4. 合并隔离分支到主工作区时保留用户 Makefile 注释，并核对主工作区现有 JOURNAL 改动；提交且保持 Git 状态清楚。
5. 真实 Competition 运行属于有费用的全套评估；目前无 API key。假 SDK 通过不能写成官方 scorecard 已生成或真实解题完成。
