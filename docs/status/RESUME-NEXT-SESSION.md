# Live Session Checkpoint

> Updated: 2026-09-26 CST. Session active; this is a recovery checkpoint, not a handoff.

## 当前任务与授权

用户已授权完成首关/二关广度重扫、做一次官方批量提交，并对失败题逐项诊断、修复和重试。广度轮、**一次**官方提交、G50T 首关诊断修复与一次成功重试均已完成。继续逐题诊断其余失败关卡；不得把失败动作视作已独立回放的答案，不要重复提交官方卡片。用户要求付费验证前避免大规模无关回归，维持每关人类动作上限、每题 30 分钟、5 分钟无动作停止线。

## 已验证事实

- `make p7-breadth` 退出 0，独立账本 `.asterion-private/prime-p7-live/breadth-resweep-campaign.json` 有 26 条，24 次新尝试。新首关 3/7 通过（CD82、S5I5、TU93）；新二关 5/17 通过（AR25、CN04、LS20、RE86、TU93）。本地 25 题中 21 题有首关已验证前缀；未解首关为 G50T、KA59、SK48、TN36。新二关 8 次封存未解、4 次执行停滞，详见账本。通过题均有离线中文网页。
- 官方 Competition 批量提交 `make asterion-prime-p7-official-submit GAME=all` **只运行一次**，退出 0。卡片 `403c8b05-ae64-4dd9-b6f6-1d22910a2e24`，21 题执行、4 题跳过，score `6.498124098124098`，status `closed-confirmed`。私有权威回执 `.asterion-private/prime-p7-official/p7-live-20260925194924-200e3e5e7a7b26c04ea21d67/official-receipt.json`；公开链接 `https://arcprize.org/scorecards/403c8b05-ae64-4dd9-b6f6-1d22910a2e24`。
- L2 封存失败使用 `arc.run.partial`，仅已完成关卡前缀独立 replay verified；旧 `failed_attempts.py` 只接受 `arc.run.failed`，使二关重试预检拒绝。L2 停滞有 unsealed trace 与 `stall-receipt.json`，必须作为独立受检观察。G50T 较新完整失败被较旧 78 summary / 76 recording 缺损记录阻断。设计见 `docs/superpowers/specs/2026-09-26-prime-p7-retry-evidence-recovery-design.md`（`b8f2c08f`）。
- `1040574c`、`a3ba0ff1`、`f9645609` 已约束 L2 启动历史调用、说明证据范围并要求可恢复局面 RESET 前给出证据；定向 prompt 测试通过。
- `11905bae`、`89f8ee62`、`23df5003` 完成三类证据读取与身份、动作帧、前缀、停滞目标关卡校验。13 项聚焦测试及 Ruff 通过。安装版预检 G50T、FT09、CD82 都返回 ready，分别覆盖新完整首关、封存二关失败、零新增动作停滞。
- `make p7-retry GAME=g50t` 第一次实跑未建立 run 目录、无新动作，最终报告 `retry produced ambiguous run evidence`，不可记为解题失败。当时零模型 OrbStack 执行命令也超时。`8ac5bcae` 已加入付费运行前的 20 秒来宾连通性探针，避免再次长时间空等。
- 用户已授权 `orbctl restart --all`；四台来宾恢复 running，P7 ubuntu 零模型 echo 及无遗留服务检查通过。随后 G50T 新 run `p7-live-20260925220255-bedfcba9ad8301dd6c41279b` 运行到 30 动作/0 关时，用户指出尚无具体解题策略修复，操作员立即停止。该 run **未封存、未验证，不可视为正式失败或重试建议来源**；私有 `operator-interruption.json` 保存动作和用量计数，来宾无遗留进程。
- `f44ce686`、`63072044`、`d8e4af70`、`0177f592` 实现并修订仅 OFFLINE 同题重试的稳定末帧无效动作守卫、局部预测与目标进展区分、可信前缀旁路。80 项相关测试、Ruff、安装版 G50T 零模型预检通过；预检只选旧封存失败 run，没有选中中断 run。
- G50T 首关独立重试 `p7-live-20260925223031-f6d803c700b5000bf6a527f7` 在 **58/78 步**完成；`sealed_trace=true`、`replay_verified=true`、`cleanup_complete=true`，终态 `level-completed`，输入 7,923,704、输出 187,016 已回报 token。独立 retry manifest 未改广度账本；本地现有 **22/25** 题具已验证首关前缀，未解首关为 KA59、SK48、TN36。G50T 中文事实摘要网页在 `artifacts/arc-agi-3/exports/`，模型讲解未通过格式校验。

## 当前判断与未完成边界

- 历史读取可能造成零动作停滞，属待实地验证假设；没有证据表明框架/SDK 动作映射错误。未解关不是已证明不可解。
- G50T 修订后一次实跑成功，但该 run 没有触发 `REPLAN_REQUIRED` 或 `observation-no-change`，不能把成功归因于守卫，也不能声称稳定通过率提高。官方卡片是截至提交时的已解前缀成绩，后续 OFFLINE 重试不会自动进入这张卡片。

## 下一动作

1. 对 FT09 L2 做已授权的独立 OFFLINE 重试，验证封存部分失败证据读取、已校验 L1 前缀重放与新的守卫；先做安装版零模型预检，再按人类动作、30 分钟、5 分钟停止线运行。
2. 逐题处理 KA59、SK48、TN36 首关及其余未解二关；先诊断，再做相关最小修复和单题重试。只修复有证据的通用缺陷，勿写死场景或重复已通过的关卡。
3. 每次新通过关卡核验 seal/replay/cleanup 与用量，导出中文网页，更新指南、证据和本检查点；不得擅自再次提交官方卡片。
