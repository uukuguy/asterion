# Live Session Checkpoint

> Updated: 2026-09-26 16:25 CST. Session active; this is a recovery checkpoint, not a handoff.

## 当前任务与授权

用户已授权完成首关/二关广度重扫、做一次官方批量提交，并对失败题逐项诊断、修复和重试。广度轮、**一次**官方提交、G50T 首关诊断修复与一次成功重试、FT09 二关同题重试均已完成。继续逐题诊断其余失败关卡；不得把失败动作视作已独立回放的答案，不要重复提交官方卡片。用户要求付费验证前避免大规模无关回归，维持每关人类动作上限、每题 30 分钟、5 分钟无动作停止线。

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
- FT09 二关同题重试 `p7-live-20260925224920-33b4e846d793e3327a2ecd51` 在 **19 步**完成（10 首关前缀 + 9 新增二关动作）；`sealed_trace=true`、`replay_verified=true`、`cleanup_complete=true`，终态 `level-completed`，2/6 关卡通过，本地分 `14.285714`，输入 2,538,451、输出 77,963 已回报 token。预检选用同一题两个封存来源（首关已封存、二关 partial）加同 seed 与 22 动作上限；未改广度账本、未进入已关闭的官方卡片。Run-story bundle `sha256:1150da93a7c04edd4e52dd18d6a5228c786d0090e8d11063cb48617a3fd0fce0`，离线网页 `arc-agi-3-ft09-0d8bbf25-p7-live-20260925224920-33b4e846d793e3327a2ecd51-web-d3b09034f81b21375173.html`（SHA-256 `sha256:e699afe9e3319d43993c33311407720996e22ddee6bc2bf29b3c79a8bbc4de50`）；模型讲解未通过，网页使用确定性事实摘要。`make asterion-prime-p7-games` 现显示 FT09 升至 2/6 关；本地首关前缀仍为 22/25，未解首关为 KA59、SK48、TN36。
- SC25 二关同题重试 `p7-live-20260925234916-0788304c8a848397a46dacb5` 在 **28 步**完成（22 首关前缀 + 6 新增二关动作，恰好用完 6 动作上限）；`sealed_trace=true`、`replay_verified=true`、`cleanup_complete=true`，终态 `level-completed`，2/6 关卡通过，本地分 `14.285714`，输入 1,158,024、输出 75,764 已回报 token。预检选用同一题两个封存 L2 partial 来源（28 动作均撞人类基准）+ 同 seed + 28 动作上限；未改广度账本、未进入已关闭的官方卡片。Run-story bundle `sha256:6fdf2b220353cead57d69f1a5b5bc751a69413be85b2241567ca72884dcd4940`，离线网页 `arc-agi-3-sc25-635fd71a-p7-live-20260925234916-0788304c8a848397a46dacb5-web-7fb30ed74df18ef89b7d.html`（SHA-256 `sha256:03b0a8493087544d070cc96183a35c1d83edd91c0b9249b2340461e73e49b339`）；模型讲解未通过，网页使用确定性事实摘要。`make asterion-prime-p7-games` 现显示 SC25 升至 2/6 关。本轮 SC25 L2 在 6 动作紧 cap 下用完额度，22 worker cell 16 分析 / 6 直接 act；模型整体策略与 FT09 L2 一致（先观察 → 假设 → act_checked），SC25 没机会"边打边学"主要是 cap 限制。
- SB26 二关同题重试 `p7-live-20260926000100-aae088d67f0a841e7c4dc4f9` **失败**：28 步（13 首关前缀 + 28 新增二关动作，用完 28 动作上限）未过 L2；`sealed_trace=true`、`replay_verified=true`、`cleanup_complete=true`，终态 `human-baseline`，levels_completed 仍为 1。预检选用两个封存 L2 partial 来源 + 同 seed + 41 动作上限；未改广度账本、未进入已关闭的官方卡片。Run 不生成验证网页，仅写入证据段。预测账 9 个 checked plan，16 个 matched，5 个 mismatch（用了 act_checked 多次，FT09/SC25 几乎只用 bare act）。Token 3,842,089 输入、138,059 输出。**这是首例失败**：partial-failure 经验帮助 FT09 (cap=9)、SC25 (cap=6) 过 L2，但 SB26 (cap=28) 用尽 28 个新动作仍撞人类基准，说明 cap 宽窄不是方法可靠性因子，机制识别仍是关键。

## 当前判断与未完成边界

- 历史读取可能造成零动作停滞，属待实地验证假设；没有证据表明框架/SDK 动作映射错误。未解关不是已证明不可解。
- G50T 修订后一次实跑成功，但该 run 没有触发 `REPLAN_REQUIRED` 或 `observation-no-change`，不能把成功归因于守卫，也不能声称稳定通过率提高。
- FT09 一次实跑成功，仅说明 `partial-failed` 证据读取路径正确并能解出更少动作的解，不构成对其他 L2 重试的可靠性估计。
- SB26 一次实跑失败（28 新 L2 动作全用完仍未过），证明：cap 宽窄不是方法可靠性因子；即便有 64 条失败事实与 9 次 act_checked 调用，机制识别仍是关键。partial-failure 经验的成功率目前 2/3（FT09、SC25 过；SB26 未）。
- **2026-09-26 重构**：删除 `failed_attempts.py` 与 `build_p7_retry_prompt`、移除 pre-computed advice 注入；保留 prefix replay（数据）与 runtime 通用守卫（稳定末帧无 effect、`prediction-mismatch`）。5 次 retry 的 `failed_attempt_advice` 字段保留作历史档案但 RESUME 必须标注"其通过不能归因于通用机制"。
- **2026-09-26 对照验证**：KA59 L1 用新机制（无 advice）36 步通过，与旧 breadth resweep 在同 game 同 cap 下 78 步未过形成对照；advice 不是 P7 L1 通过的必要条件，5 次 retry 通过最可能也是通用机制在工作。
- **2026-09-26 SU15 L2 四次对照**（baseline / v1 / v3 / v4）：
  - baseline（无 compaction 无 tool）：42 L2 cap-hit，0 次 API 调用
  - v1（仅 compaction）：42 L2 cap-hit，0 次 API
  - v2（compaction + hardcoded prompt section）：13 L2 被外部 kill，2 次 API 引用
  - v3（compaction + framework 工具注入 prompt）：42 L2 cap-hit，~25 次 API 调用（含 tried_actions=1、frame_at=8、observe=9、act_checked=3）
  - **结论**：framework 工具注入（`P7ToolRegistry` + `build_solve_prompt`）通过 Pi 的 `registerTool` API 真正启用 proper function-calling，模型调用 API 频率 v3 翻倍。但 42 L2 全 click 无 advance，机制识别仍是模型归纳能力问题——框架可达性已不再是瓶颈。
- 官方卡片是截至提交时的已解前缀成绩，后续 OFFLINE 重试不会自动进入这张卡片。
- 官方卡片是截至提交时的已解前缀成绩，后续 OFFLINE 重试不会自动进入这张卡片。

## 下一动作

1. ~~对照验证：KA59 L1 用新机制跑出 36 步通过，sealed/replay/cleanup 全 true；`failed_attempt_advice=null` 确认无 advice 注入。原 4 次 retry 通过（BP35 L1、G50T L1、FT09 L2、SC25 L2）很可能也是通用机制在工作，不是 advice 的功劳。~~
2. 对照完成后继续 SP80 L2（64 ac）/ SU15 L2（55 ac）作为下一题同题重试。按 cap 由小到大推进，每题独立 retry，不修改机制。
3. 对选定题先 `make p7-retry-preflight GAME=<alias>`：必须只选到已校验 L1 前缀和已校验同题旧记录；来宾连通性、seed 一致、动作上限核对均通过。
4. 启动 `make p7-retry GAME=<alias>`：单次 OFFLINE 重试，30 分钟与 5 分钟无动作停止线维持，每次新通过关卡核验 seal/replay/cleanup 与用量，导出中文网页，更新 `prime-p7-games-and-official-results.md`、`ASTERION-PRIME-P7-EVIDENCE.md` 与本检查点。**不得擅自再次提交官方卡片。**
5. L2 全部推进后再开始 SK48/TN36 首关同题重试；这两题目前没有已校验首关前缀，需先用普通 `solve` 走一遍（KA59 已用新机制通过 L1）。
6. **不再引入** Retrodict 经验机制。原因：当前 prefix replay + runtime guards 已是合理的最小修复；再叠新机制变成多变量改动无法归因。