# Live Session Checkpoint

> Updated: 2026-09-24 20:19 CST. **Session remains active — not a final handoff.**

## 当前任务

用户自行正在运行 `make asterion-prime-p7-solve`，完成后会贴终端输出；本会话不要启动第二次或干扰其进程。下一题为 ARC-AGI-3 `tu93-0768757b` / seed `0`。用户同时要求可操作的题目/结果指南和只读清单命令，已完成。此前 P1–P6 真实运行和边界见 `docs/status/PRIME-P1-P7-ACCEPTANCE.md` 与 JOURNAL。

## 已验证事实

- 设计和计划已提交：`2215d638`；精确双题选择和本地资源检查已提交：`fe44bb3c`。
- 新题文件存于仓库外 `../external-prime/arc-agi-3/environment_files/tu93/0768757b/`。打包安装的 Asterion 加 ARC wheels 已在本地零动作加载 tu93：9 关，`ACTION1`–`ACTION4`，动作数 0。
- `343592ed` 已使 Makefile 经 Orb 传入 game ID/seed，并使引擎、Broker、回放、密封 trace、私有摘要和公开回执使用同一身份。公开 `selection_receipt_sha256` 绑定题目、seed、能力收据和回放摘要；旧能力收据结构不变。
- 定向测试 51 项、Ruff lint、docs-check 通过；证据查看器现拒绝录制题目换标及 broker 回放摘要篡改。`make promotion-check` 已通过：25 条隔离发行命令，模型操作 0。另一个重复的 `make test` 已主动停止，以免重复消耗；它不能记为通过。
- `e858b084` 已把 Makefile 默认题设为 tu93/seed 0，并从仓库旁定位 ARC 题库。旧 shell 环境选题值不会覆盖此 preset；显式 Make 参数仍可复现旧题。Orb 无模型检查确认默认身份和题库文件可见；Make preset 3 项测试、lint、docs-check 通过。
- 最新两次 P7 私有摘要 `p7-live-20260924094143`、`p7-live-20260924112844` 均是 `ApplicationProviderError`，动作数、IPython 单元数均为 0，没有能力收据；公开 provider 已包含 7 个应用，但 P7 入口只注入 1 个能力包。将 P7 入口改用只含 P7 的 provider 后，安装 wheel 在 Orb 中无模型组合通过；P7 相关定向测试 41 项通过，`make promotion-check` 25 条隔离命令通过且模型操作 0。
- `de619f03` 已提交这项修复及回归测试；真实付费求解未重跑。
- `30950d1c` 已提交 `make asterion-prime-p7-games` 和 `docs/guides/prime-p7-games-and-official-results.md`。本地清单显示 ls20 已验证 1/7 关（最佳 20 动作、3.571429），tu93 当前无已验证完成记录；8 项定向测试、lint、docs-check 通过。此命令只读、不启动模型或访问网络。
- `cbb33b86` 已修复清单对未知历史题号的异常，以及负分、超界分数误算为已验证的问题；9 项定向测试与 lint 通过。

## 边界与下一动作

- 等用户提供当前 P7 运行的完整终端输出，再核对最新运行记录并更新 tu93 状态；目前不能宣称这次运行成功或失败。
- P7 当前在首关完成时停止，且 ARC SDK 使用 OFFLINE；本地 receipt 不是官方在线 scorecard。指南记录了官方在线及 Competition Mode 的生成流程；Asterion 在线 scorecard 集成和多关延续尚未实现。
- 用户在 Makefile 增加的两条题号注释保留为未提交工作区改动，未纳入 `30950d1c`。
