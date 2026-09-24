# Live Session Checkpoint

> Updated: 2026-09-25. **Session remains active — not a final handoff.**

## 当前任务

用户要求 P7 按官方游戏行为在 `GAME_OVER` 后重置当前关，不要无故重做已过关卡。此前 tu93 失败及逐次留存修复见下文；此前 P1–P6 真实运行和边界见 `docs/status/PRIME-P1-P7-ACCEPTANCE.md` 与 JOURNAL。此轮未启动新的付费解题。

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
- 新失败运行 `p7-live-20260924115415` 的私有证据显示 50 个已记录动作、0 关完成、官方离线引擎在第 50 步返回 `GAME_OVER`；此前终端回执的 0 动作和 cleanup false 是异常路径默认值，不是实际结果。原因是 Broker 未将 `GAME_OVER` 当终局、worker 在终局动作后再次调用已关闭的 Broker，以及失败路径丢弃了 Broker 证据。
- `d1c094cd` 已提交 `GAME_OVER` 终局与严格回放、终局动作响应的状态快照、失败回执的安全动作数/终局/清理投影，以及 `p7-live-UTC时间戳-唯一后缀` 独立运行目录。既有目录仍使用拒绝覆盖创建。运行器在任何 Broker 终局后停止继续请求模型，但能力 PASS 仍只接受首关完成。指南增补了重解和查找历次运行的命令。
- 此轮最终 P7 相关 58 项无模型测试通过；新增 500 动作上限、第 500 动作 `GAME_OVER`、同一步过关与 `GAME_OVER` 的回放边界测试通过。`make lint` 和 `make docs-check` 在最终源码上通过；提示词与打包摘要改动后 `make promotion-check` 通过 25 条隔离发行命令、provider 操作 0。随后调整的终局谓词与回放边界由最终 58 项测试覆盖。无付费求解，因此不能宣称 tu93 已通关。
- `07d2c63d` 新增 `GAME=ls20|tu93` 与 `LEVEL=N`：`make asterion-prime-p7-solve GAME=ls20` 重跑首关，`make asterion-prime-p7-solve GAME=ls20 LEVEL=2` 在新尝试中从第 1 关顺序做到第 2 关；官方离线 SDK 不提供从历史运行直接跳关。目标级别进入题目选择、Broker、worker 状态、逐关计分、能力收据、回放与公开回执。历史成功收据不重写。独立运行目录继续保留每次尝试。
- 本轮定向测试 79 项、安装 wheel 无模型第 1/2 关集成测试、`make lint`、`make docs-check` 已通过；`make promotion-check` 通过 25 条隔离发行命令，provider 操作 0。真实 LS20 第 2 关付费解题未运行。
- 2026-09-25 本地 SDK 核验：`GameAction.RESET` 在 `GAME_OVER` 后仍可送入同一游戏实例；已有游戏动作时它重置当前关并保留已过关数，零动作时 OFFLINE 模式可能重置整局。P7 据此加入受控 `RESET`：当前关至少执行过一个普通动作才允许重置，失败后仅允许 `RESET`，重置计入 500 个原始动作，同局保留已过关卡。官方 `ACTION6` 的整数 `x,y` 坐标也已贯通 SDK、私有 trace、摘要和回放；旧无数据动作摘要保持兼容。设计和实施计划见 `docs/superpowers/specs/2026-09-25-prime-p7-level-reset-design.md` 与 `docs/superpowers/plans/2026-09-25-prime-p7-official-level-reset.md`。
- `cd1f918b` 提交上述 P7 实现和指南。本轮新增先失败后通过的边界测试覆盖 `GAME_OVER` 后重置、点击坐标、初始状态异常、同步过关与死亡、回放及分数。最终 P7 定向测试 83 项通过；安装 wheel 假引擎的第 1 关通过→第 2 关失败→同一实例重置→第 2 关通过路径包含在内。`make lint`、`make docs-check` 通过。首次 `make promotion-check` 在无关的 Rust `service` 测试失败；该测试单独复跑 5 项通过，完整发行检查再次运行通过 25 条隔离命令，provider 操作 0。真实 LS20/TU93 未付费重跑，不能宣称真实解题能力已提高。

## 边界与下一动作

- 当前修复支持同局失败重置；真实付费求解尚未重跑。模型是否能识别题目并通关，不能由无模型测试推断。命令 `make asterion-prime-p7-solve GAME=ls20 LEVEL=2` 从第 1 关新开局，同局里第 2 关失败可只重置第 2 关。命令结束后 SDK 无可恢复的游戏存档，下次运行仍从第 1 关开始。
- P7 在指定目标关卡完成时停止，且 ARC SDK 仍使用 OFFLINE；500 原始动作上限跨关与重置共用。本地 receipt 不是官方在线 scorecard。指南记录了官方在线及 Competition Mode 的生成流程；Asterion 在线 scorecard 集成尚未实现。
- 用户在 Makefile 增加的两条题号注释保留为未提交工作区改动，未纳入本轮提交。
