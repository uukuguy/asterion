# Live Session Checkpoint

> Updated: 2026-09-25 03:24 CST. **Session remains active — not a final handoff.**

## 当前任务

P7 面向完整 ARC-AGI-3 游戏与官方 Competition scorecard，而非单关见证。整题求解、官方逐题会话、回执校验和操作指南已在 `main` 的 `85177b5e` 合并；隔离 worktree 已核对并清理。

## 已验证事实

- `make asterion-prime-p7-solve GAME=<短号或完整ID>` 从第 1 关按序解完整游戏，仅 SDK `WIN` 与关卡数一致才可签收。`asterion-prime-p7-level-witness GAME=<题号> LEVEL=N` 是独立的局部诊断命令，仍从第 1 关开始。
- `make asterion-prime-p7-games` 从严格校验的本地题目元数据列目录，区分完整 `WIN` 与局部见证；每次本地运行保留独立 `run_id` 和目录。
- 官方 `p7/official.py` 的假 SDK 测试覆盖 Competition 目录、单卡每题一次 `make`、SDK 自动首重置、身份绑定、ACTION6、当前关 RESET、正常关闭与中断关闭。官方 `ArcGameContract` 不借用本地 baseline、回放或局部分数。
- 新的 `prime.arc-agi-3-gameplay` 能力、assembly、provider 与运行时只给出无分数逐题证据；`reset-required` 时会继续给模型机会重置当前关。官方 coordinator 在所有目录题目尝试后关闭 scorecard，按完整目录、guid、状态与有限分数校验 SDK 返回，再写私有正式回执；异常写恢复记录。官方 API key 不传入 Pi 模型进程。
- 操作指南 `docs/guides/prime-p7-games-and-official-results.md` 记录本地和官方命令。主分支 83 项 P7 定向测试、`make lint`、`make docs-check`、`git diff --check` 已通过；关键代码独立复审未发现 Critical/Important。
- 打包 `make promotion-check` 初次因新 gameplay assembly 未登记资源清单失败；`8bfc7009` 修复后完整复跑通过：25 条隔离命令、provider 操作 0、`full_dataset=no`。
- `19fd0772` 新增多游戏贯通测试：同一张卡、一题 `WIN`、一题 `GAME_OVER`，缺少服务端行时仅留恢复记录。`ee8d5787` 使用真实 `arc_agi==0.9.9` SDK、完全拦截 HTTP，核对目录、建卡、`make` 自动首 RESET、关闭；与其他官方测试合计 33 项通过，全程无网络。`9d33cb5d` 让预检公开逐题和总动作、模型回调、期限上界，测试与实际运行时固定值一致。
- 仓库 `.env` 和当前进程环境均没有 `ARC_API_KEY`。本轮没有实际官方 API、模型求解或 scorecard 提交；没有真实整题通关证据。假 SDK、拦截 HTTP 的真实 SDK 与安装包装配均不能被表述为官方成绩。

## 当前判断与未完成边界

- 官方 Competition 命令的安装包路径与打包门禁已验证。真实官方运行是有费用的完整评估，按仓库授权边界另行进行。
- 如官方某题初始化失败，协调器继续后续游戏，但缺少对应服务端运行行时最终回执会失败并保留恢复记录；不能虚构 0 分或官方链接。

## 下一动作

1. operator 配置 `ARC_API_KEY` 后先运行只读 `make asterion-prime-p7-official-preflight`，记录官方目录与逐题/总上界。仓库 `AGENTS.md` 要求完整付费评估另行授权；取得有限预算授权后再执行 `make asterion-prime-p7-official-submit`，报告服务端真实结果。
