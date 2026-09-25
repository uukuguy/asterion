# Live Session Checkpoint

> Updated: 2026-09-26 CST. Session active; this is a recovery checkpoint, not a handoff.

## 当前任务与授权

用户已授权完成首关/二关广度重扫、做一次官方批量提交，并对失败题逐项诊断、修复和重试。广度轮及**一次**官方提交均已完成。当前在修复 P7 重试证据读取器，之后仅跑定向测试与真实 OFFLINE 重试；不得把失败动作视作已独立回放的答案，不要重复提交官方卡片。用户要求付费验证前避免大规模无关回归，维持每关人类动作上限、每题 30 分钟、5 分钟无动作停止线。

## 已验证事实

- `make p7-breadth` 退出 0，独立账本 `.asterion-private/prime-p7-live/breadth-resweep-campaign.json` 有 26 条，24 次新尝试。新首关 3/7 通过（CD82、S5I5、TU93）；新二关 5/17 通过（AR25、CN04、LS20、RE86、TU93）。本地 25 题中 21 题有首关已验证前缀；未解首关为 G50T、KA59、SK48、TN36。新二关 8 次封存未解、4 次执行停滞，详见账本。通过题均有离线中文网页。
- 官方 Competition 批量提交 `make asterion-prime-p7-official-submit GAME=all` **只运行一次**，退出 0。卡片 `403c8b05-ae64-4dd9-b6f6-1d22910a2e24`，21 题执行、4 题跳过，score `6.498124098124098`，status `closed-confirmed`。私有权威回执 `.asterion-private/prime-p7-official/p7-live-20260925194924-200e3e5e7a7b26c04ea21d67/official-receipt.json`；公开链接 `https://arcprize.org/scorecards/403c8b05-ae64-4dd9-b6f6-1d22910a2e24`。
- L2 封存失败使用 `arc.run.partial`，仅已完成关卡前缀独立 replay verified；旧 `failed_attempts.py` 只接受 `arc.run.failed`，使二关重试预检拒绝。L2 停滞有 unsealed trace 与 `stall-receipt.json`，必须作为独立受检观察。G50T 较新完整失败被较旧 78 summary / 76 recording 缺损记录阻断。设计见 `docs/superpowers/specs/2026-09-26-prime-p7-retry-evidence-recovery-design.md`（`b8f2c08f`）。
- `1040574c`、`a3ba0ff1` 已约束 L2 启动历史调用并澄清重试证据范围；定向 prompt 测试此前单独通过。当前读取器由协作 agent 改动中，不能从其中间态测试判断最终结果。

## 当前判断与未完成边界

- 历史读取可能造成零动作停滞，属待实地验证假设；没有证据表明框架/SDK 动作映射错误。未解关不是已证明不可解。
- 提示词、证据读取器改动还没有实地结果；不能声称提高通过率。官方卡片是截至提交时的已解前缀成绩，后续 OFFLINE 重试结果没有进入这张卡片。

## 下一动作

1. 完成 `failed_attempts.py` 三类来源校验和定向测试，包括 BP35 L2、G50T 较旧缺损记录、停滞；Ruff 通过。检查 prompt/provider gate 仍可装载。
2. 对代表性的一个 L1 和一个 L2 做 `make p7-retry-preflight GAME=<alias>`，再运行 `make p7-retry GAME=<alias>`。观察动作、token、状态；每题结束核对 seal/replay/cleanup、manifest 和已验证进度。
3. 根据实地结果及逐题诊断，一题一次重试其余未解首关/二关。只对有明确证据的通用缺陷修复；勿写死场景或重跑已解关。更新中文网页、指南、JOURNAL 与本检查点。
