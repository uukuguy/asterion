# Live Session Checkpoint

> Updated: 2026-09-26 CST. Session active; this is a recovery checkpoint, not a handoff.

## 当前任务与授权

用户已授权完成首关/二关广度重扫、做一次官方批量提交，并对失败题逐项诊断、修复和重试。广度轮及**一次**官方提交均已完成。当前在修复 P7 重试证据读取器，之后仅跑定向测试与真实 OFFLINE 重试；不得把失败动作视作已独立回放的答案，不要重复提交官方卡片。用户要求付费验证前避免大规模无关回归，维持每关人类动作上限、每题 30 分钟、5 分钟无动作停止线。

## 已验证事实

- `make p7-breadth` 退出 0，独立账本 `.asterion-private/prime-p7-live/breadth-resweep-campaign.json` 有 26 条，24 次新尝试。新首关 3/7 通过（CD82、S5I5、TU93）；新二关 5/17 通过（AR25、CN04、LS20、RE86、TU93）。本地 25 题中 21 题有首关已验证前缀；未解首关为 G50T、KA59、SK48、TN36。新二关 8 次封存未解、4 次执行停滞，详见账本。通过题均有离线中文网页。
- 官方 Competition 批量提交 `make asterion-prime-p7-official-submit GAME=all` **只运行一次**，退出 0。卡片 `403c8b05-ae64-4dd9-b6f6-1d22910a2e24`，21 题执行、4 题跳过，score `6.498124098124098`，status `closed-confirmed`。私有权威回执 `.asterion-private/prime-p7-official/p7-live-20260925194924-200e3e5e7a7b26c04ea21d67/official-receipt.json`；公开链接 `https://arcprize.org/scorecards/403c8b05-ae64-4dd9-b6f6-1d22910a2e24`。
- L2 封存失败使用 `arc.run.partial`，仅已完成关卡前缀独立 replay verified；旧 `failed_attempts.py` 只接受 `arc.run.failed`，使二关重试预检拒绝。L2 停滞有 unsealed trace 与 `stall-receipt.json`，必须作为独立受检观察。G50T 较新完整失败被较旧 78 summary / 76 recording 缺损记录阻断。设计见 `docs/superpowers/specs/2026-09-26-prime-p7-retry-evidence-recovery-design.md`（`b8f2c08f`）。
- `1040574c`、`a3ba0ff1`、`f9645609` 已约束 L2 启动历史调用、说明证据范围并要求可恢复局面 RESET 前给出证据；定向 prompt 测试通过。
- `11905bae`、`89f8ee62`、`23df5003` 完成三类证据读取与身份、动作帧、前缀、停滞目标关卡校验。13 项聚焦测试及 Ruff 通过。安装版预检 G50T、FT09、CD82 都返回 ready，分别覆盖新完整首关、封存二关失败、零新增动作停滞。
- `make p7-retry GAME=g50t` 第一次实跑未建立 run 目录、无新动作，最终报告 `retry produced ambiguous run evidence`，不可记为解题失败。当时零模型 OrbStack 执行命令也超时。`8ac5bcae` 已加入付费运行前的 20 秒来宾连通性探针，避免再次长时间空等。
- 用户已授权 `orbctl restart --all`；四台来宾恢复 running，P7 ubuntu 零模型 echo 及无遗留服务检查通过。随后 G50T 新 run `p7-live-20260925220255-bedfcba9ad8301dd6c41279b` 运行到 30 动作/0 关时，用户指出尚无具体解题策略修复，操作员立即停止。该 run **未封存、未验证，不可视为正式失败或重试建议来源**；私有 `operator-interruption.json` 保存动作和用量计数，来宾无遗留进程。正在对比旧 78 步与新 30 步的动作决策并设计通用修复，完成前不得再付费重试。

## 当前判断与未完成边界

- 历史读取可能造成零动作停滞，属待实地验证假设；没有证据表明框架/SDK 动作映射错误。未解关不是已证明不可解。
- 现有 G50T 30 动作是中断观察，不是解题策略修复后的封存结果；不能声称提高通过率。官方卡片是截至提交时的已解前缀成绩，后续 OFFLINE 重试不会自动进入这张卡片。

## 下一动作

1. 依据旧 G50T 与中断新运行的录制和 worker 决策核对目标假设为何没有在反证后撤销；提出并实施游戏无关、可测的最小决策修复。不要把局部 `act_checked matched` 当作关卡进展。
2. 修复通过相关零模型测试和审查后，再对 G50T L1 做**一次**受控重试。核对每步行动、token、关卡、seal/replay/cleanup 与新旧记录差异。
3. 再选 FT09 L2 验证二关重试，随后逐题处理其余未解首关/二关。只修复有证据的通用缺陷；勿写死场景或重跑已解关。更新中文网页、指南、JOURNAL 与本检查点。
