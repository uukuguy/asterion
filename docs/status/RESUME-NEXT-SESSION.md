# Live Session Checkpoint

> Updated: 2026-09-25 04:22 CST. **Session remains active — not a final handoff.**

## 当前任务

P7 面向完整 ARC-AGI-3 游戏与官方 Competition scorecard，而非单关见证。整题求解、官方逐题会话、回执校验和操作指南已在 `main` 的 `85177b5e` 合并；隔离 worktree 已核对并清理。

## 已验证事实

- `make asterion-prime-p7-solve GAME=<短号或完整ID>` 从第 1 关按序解完整游戏，仅 SDK `WIN` 与关卡数一致才可签收。`asterion-prime-p7-level-witness GAME=<题号> LEVEL=N` 是独立的局部诊断命令，仍从第 1 关开始。
- `make asterion-prime-p7-games` 从严格校验的本地题目元数据列目录，区分完整 `WIN` 与局部见证；每次本地运行保留独立 `run_id` 和目录。
- 官方 `p7/official.py` 的假 SDK 测试覆盖 Competition 目录、单卡每题一次 `make`、SDK 自动首重置、身份绑定、ACTION6、当前关 RESET、正常关闭与中断关闭。官方 `ArcGameContract` 不借用本地 baseline、回放或局部分数。
- 新的 `prime.arc-agi-3-gameplay` 能力、assembly、provider 与运行时只给出无分数逐题证据；`reset-required` 时会继续给模型机会重置当前关。官方 coordinator 在所有目录题目尝试后关闭 scorecard，按完整目录、guid、状态与有限分数校验 SDK 返回，再写私有正式回执；异常写恢复记录。官方 API key 不传入 Pi 模型进程。
- 操作指南 `docs/guides/prime-p7-games-and-official-results.md` 记录本地和官方命令。主分支 83 项 P7 定向测试、`make lint`、`make docs-check`、`git diff --check` 已通过；关键代码独立复审未发现 Critical/Important。
- 打包 `make promotion-check` 初次因新 gameplay assembly 未登记资源清单失败；`8bfc7009` 修复后完整复跑通过：25 条隔离命令、provider 操作 0、`full_dataset=no`。
- `19fd0772` 新增多游戏贯通测试：同一张卡、一题 `WIN`、一题 `GAME_OVER`，缺少服务端行时仅留恢复记录。`ee8d5787` 使用真实 `arc_agi==0.9.9` SDK、完全拦截 HTTP，核对目录、建卡、`make` 自动首 RESET、关闭及回执解析。`9d33cb5d` 让预检公开逐题和总动作、模型回调、期限上界，测试与实际运行时固定值一致。
- `32c508db` 修复 host 初始化失败时官方游戏引擎未关闭的问题。`2d81c767` 使用离线 wheel、已安装 assembly 和假 Pi 执行真实 `_run_game`，确认确定性整题 `WIN`、trace 封存和引擎清理。最新 35 项官方定向测试、`make lint`、`make docs-check` 通过；无网络或付费模型调用。
- Operator 已在仓库 `.env` 配置 `ARC_API_KEY`。`make asterion-prime-p7-official-preflight` 实际通过，官方账号目录返回 25 题，合计上界 38,142 动作、3,200 模型回调和 90,000 秒逐题期限。该检查只读取官方目录；没有创建 scorecard、游戏实例或调用模型，也没有真实整题通关证据。
- 官方文档确认 Competition 对全部可见题计分，但可只对选定题调用 `make`；部分通关按关卡得分。OFFLINE 本地回执不能补传，正式成绩须在新官方会话执行动作。当前本地目录仅有 LS20、TU93 两题，历史验证记录只有 LS20 第一关。
- 本地历史 trace 保存了动作与前后状态摘要，现有 `replay_arc_run` 只使用运行中的内存 journal，未提供历史解题计划导入。官方 `CompetitionSession.close` 和回执校验要求全部目录题目各有一条运行，阻止选题提交；必须区分完整目录、选中题目和未玩题目，并保留服务端总分。官方 seed 不能仅凭适配器写入的 0 推断，远端执行前须比对初始观测。
- 已安装 ARC SDK 的 `NORMAL make` 可下载题目元数据和源码，但会先自动创建默认 scorecard；远端 Competition wrapper 不接收 `seed`，所以本地同版本、同 seed 也不能保证官方动作复现。扩展本地 2 题目录应设计独立受控下载路径；提交时逐动作比对，遇到分歧立即停止。

## 当前判断与未完成边界

- 官方 Competition 命令的安装包路径与打包门禁已验证。真实官方运行是有费用的完整评估，按仓库授权边界另行进行。
- 如官方某题初始化失败，协调器继续后续游戏，但缺少对应服务端运行行时最终回执会失败并保留恢复记录；不能虚构 0 分或官方链接。

## 下一动作

1. 用户提出本地按 `GAME`、`LEVEL` 选题选关，保存已验证动作，再只对已解题目形成官方成绩。已说明官方新会话必须重新执行动作；`brainstorming` 技能要求设计获确认后才修改行为。确认后实现严格历史 trace 导入、顺序关卡前缀、选题官方执行和未玩题回执校验；无模型测试先行。
2. 仓库 `AGENTS.md` 要求完整付费评估另行授权和有限预算。真实官方 scorecard 操作须在设计实现、边界测试与单独授权后执行。
