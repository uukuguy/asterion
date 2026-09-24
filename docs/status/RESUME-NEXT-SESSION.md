# Live Session Checkpoint

> Updated: 2026-09-24 17:47 CST. **Session remains active — not a final handoff.**

## 当前任务

用户指出 P7 运行命令不该要求记住题目 ID 或 ARC 目录；下一题是 ARC-AGI-3 `tu93-0768757b` / seed `0`，现在只需 `make asterion-prime-p7-solve`。本轮只改入口并做无模型验证，不启动付费求解。此前 P1–P6 真实运行和边界见 `docs/status/PRIME-P1-P7-ACCEPTANCE.md` 与 JOURNAL。

## 已验证事实

- 设计和计划已提交：`2215d638`；精确双题选择和本地资源检查已提交：`fe44bb3c`。
- 新题文件存于仓库外 `../external-prime/arc-agi-3/environment_files/tu93/0768757b/`。打包安装的 Asterion 加 ARC wheels 已在本地零动作加载 tu93：9 关，`ACTION1`–`ACTION4`，动作数 0。
- `343592ed` 已使 Makefile 经 Orb 传入 game ID/seed，并使引擎、Broker、回放、密封 trace、私有摘要和公开回执使用同一身份。公开 `selection_receipt_sha256` 绑定题目、seed、能力收据和回放摘要；旧能力收据结构不变。
- 定向测试 51 项、Ruff lint、docs-check 通过；证据查看器现拒绝录制题目换标及 broker 回放摘要篡改。`make promotion-check` 已通过：25 条隔离发行命令，模型操作 0。另一个重复的 `make test` 已主动停止，以免重复消耗；它不能记为通过。
- 本轮已把 Makefile 默认题设为 tu93/seed 0，并从仓库旁定位 ARC 题库。旧 shell 环境选题值不会覆盖此 preset；显式 Make 参数仍可复现旧题。Orb 无模型检查确认默认身份和题库文件可见；Make preset 3 项测试、lint、docs-check 通过。

## 边界与下一动作

- tu93 仅做过零动作加载，未真正求解，不能宣称 P7 对新题 PASS。不要运行 `make asterion-prime-p7-solve`，除非用户另行授权付费求解。
- 一条命令入口与无模型验证已完成；实际求解仍需独立授权。
- 后续用户若批准真实运行，直接使用 `make asterion-prime-p7-solve`；Makefile 默认选 tu93/seed 0，并从仓库旁定位 ARC 题库。该命令会实际调用模型。
