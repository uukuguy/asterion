# Live Session Checkpoint

> Updated: 2026-09-24 05:40 CST. **Session remains active — not a final handoff.**

## 当前任务

用户批准 P7 受控切题并只做无模型预检。下一题是官方 ARC-AGI-3 `tu93-0768757b` / seed `0`；本轮不得启动付费求解。此前 P1–P6 真实运行和边界见 `docs/status/PRIME-P1-P7-ACCEPTANCE.md` 与 JOURNAL。

## 已验证事实

- 设计和计划已提交：`2215d638`；精确双题选择和本地资源检查已提交：`fe44bb3c`。
- 新题文件存于仓库外 `../external-prime/arc-agi-3/environment_files/tu93/0768757b/`。打包安装的 Asterion 加 ARC wheels 已在本地零动作加载 tu93：9 关，`ACTION1`–`ACTION4`，动作数 0。
- 尚未提交的应用改动已使 Makefile 经 Orb 传入 game ID/seed，并使引擎、Broker、回放、密封 trace、私有摘要和公开回执使用同一身份。公开 `selection_receipt_sha256` 绑定题目、seed、能力收据和回放摘要；旧能力收据结构不变。
- 定向测试 51 项、Ruff lint、docs-check 通过；证据查看器现拒绝录制题目换标及 broker 回放摘要篡改。`make promotion-check` 正在运行其隔离全量回归。另一个重复的 `make test` 已主动停止，以免重复消耗；它不能记为通过。

## 边界与下一动作

- tu93 仅做过零动作加载，未真正求解，不能宣称 P7 对新题 PASS。不要运行 `make asterion-prime-p7-solve`，除非用户另行授权付费求解。
- 等待 promotion-check；随后复核工作区、提交本轮实现与文档、追加 JOURNAL，并记录验证结论。若 promotion-check 因外部工具失败，准确记录限制。
- 后续用户若批准真实运行，使用 `make asterion-prime-p7-solve ASTERION_PRIME_P7_GAME_ID=tu93-0768757b ASTERION_PRIME_P7_SEED=0`，并设置仓库外 `ASTERION_PRIME_ARC_ROOT`。该命令会实际调用模型。
