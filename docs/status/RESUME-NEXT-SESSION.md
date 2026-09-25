# Live Session Checkpoint

> Updated: 2026-09-25 08:29 CST. **Session remains active — not a final handoff.**

## 当前任务

按用户最新授权，将 ARC-AGI-3 目录中除历史 LS20 L1 外的 24 题首关完成一轮本地 OFFLINE 尝试。AR25 L1 已验证过关，故尚需尝试 23 题（含上轮预算中断的 BP35）。这次只做各题第 1 关，不自动进入第 2 关；每关以公布的人类动作基准和每题 30 分钟双重停止线为准。用户根据当天实际支出 2.42 元人民币撤销总 token 和总时间上限；这是用户报告的账单数，不是仓库核验的价格。首关专用原生运行已移除内部 1 小时/128 回调上限；正在把单题 30 分钟、题库固定清单及中断后的轮次续跑接入调度器。实现与验证完成前不启动付费运行；只保存本地证据，不创建新的官方 scorecard。

## 已验证事实

- `make asterion-prime-p7-games` 列出 25 题；目前 LS20 与 AR25 各有已验证第 1 关前缀。官方既有卡 `14868b83-3f40-4afd-84b0-4d25176f97d0` 只有 LS20 第 1 关的部分成绩，其他题未选，不能视为整题通关。
- LS20 第 1 关的可计量运行记录为 20 步、输入 32,830、输出 36,418，共 69,248 旧口径 token，历时 272 秒。其余 24 题首关的人类上限合计 851 步，按每步消耗机械推算约 295 万 token、3 小时 13 分钟，旧记录漏计缓存输入。用户确认首轮总停止线为 350 万 token、4 小时；每次尝试时间按关卡步数估算，10 至 30 分钟；运行中每 250 毫秒核对已上报用量，到上限即停止本次尝试。
- 此前 LS20 第 2 关续解重放 20 个已验证第 1 关动作后，新记约 242 个第 2 关动作，超过 123 的人类基准才被人工停止；该运行未封存且没有用量事件，不复用作前缀，不推算其 token。
- `1a178f4a` 将 Prime runtime 用量事件流式落到 trace，`f38143c4` 将 Pi 缓存读写计入输入 token；`987ca598` 加精确本地扫题动作上限，`a8ef4d53` 加轮转调度器，`3f1499ba` 将扫题接入 P7 operator/Make，`4d820313` 验证中断 trace 哈希链并在用量缺失时停机。
- 刚构建 wheel 的隔离环境中，调度器 `--max-attempts 0` 预检成功：attempted=0、token=0。`make promotion-check` 完整通过：25 条命令、0 次 provider 操作、无完整数据集。`make lint`、`make docs-check` 和定向测试通过；独立复审批准付费首轮。
- 首次付费 sweep 只尝试 AR25 第 1 关。运行 `p7-live-20260924230447-46fc1ea55b4041a6f56f8786` 的 broker 到 22 步过关并经离线 broker replay，但 usage/action 并发写 trace 导致序号 9 重复、哈希链断裂；summary 的 `sealed_trace=false`，不能成为已验证可复用前缀。调度器正确拒绝继续其他题并返回 `usage-missing-after-model-activity`，但其 `0 token` 汇总是假象：原始 27 条 usage 事件逐条合计输入 1,157,891、输出 39,235，共 1,197,126 token，因链损坏仅作保守预算扣减。没有遗留求解进程。
- `4a030f99` 已串行化 trace 的写入、封存与快照，八线程并发回归前红后绿。`3fa408c1` 从原 trace 的 22 个连续动作、live/replay/prefix-replay 三份录制和新 OFFLINE 引擎中核对 AR25 L1，在全新目录 `p7-live-20260924232709-af0888dd036743f4566e6b7c` 封存带来源哈希的 22 步过关记录。原损坏 trace 字节保持不变；首次诊断恢复目录已无损移到 `.asterion-private/prime-p7-recovery-diagnostics/`。已安装 wheel 的 `load_best_prefix` 现选中最终恢复记录；`make asterion-prime-p7-games` 显示 AR25 已验证 1 关、分数 2.777778。
- `d3f670f9` 每 250 毫秒读取当前子进程 hash-valid 用量，达到已回报 token 上限即终止进程组，并按总剩余时间截断单题。它不能限制模型当前尚未回报的用量；定向模拟子进程测试通过。完整 `make promotion-check` 在 trace 并发修复后再次通过（25 命令、0 provider 操作），恢复与调度器后续变更有聚焦测试。
- 独立零模型 Orb 进程树探针曾发现 `killpg(SIGTERM)` 只结束本机 Orb 和客体父 Python，客体子 Python 仍存活；探针残留已清理。`f8486f80` 改为每次尝试独立的来宾 systemd cgroup，在宿主预算停止后精确停止并核验该 cgroup。真实 Orb 零模型回归在 10 token 模拟上限达到 11 时，父进程与脱离会话的子进程均退出，无关进程保持运行；22 项定向测试、lint、docs-check、完整 promotion-check（25 命令、0 provider 操作）通过。刚构建 wheel 的零动作调度器预检返回 `attempted=0`、token=0；独立最终复审未发现付费续跑阻断项。
- 续跑 `p7-live-20260924234525-17d9c6c33b0fa14a39b1256f` 仅尝试 BP35 L1，在 18 个动作时触发本次 220 万已回报 token 上限；40 条 usage 共输入 2,213,365、输出 86,316，合计 2,299,681。58 条 trace 记录哈希链有效；但运行被预算中断，无 summary 或封存回执，BP35 不算过关。BP35 L1 人类基准是 21 步。调度器报告 `token-cap` 并退出，Orb 没有遗留 P7 求解进程或 systemd unit。
- AR25 原始暂计 1,197,126 加 BP35 已核验 2,299,681，总计 3,496,807/3,500,000 已回报 token；离上限仅 3,193 token，不再启动任何付费尝试。此轮没有触及 4 小时上限。`make asterion-prime-p7-games` 仍仅有 LS20 L1 与 AR25 L1 已验证，其他 23 题尚无已验证前缀；官方既有 scorecard 未新增提交。
- BP35 的前 10 次模型调用输入合计 170,107 token，后 10 次 1,004,287，显示随会话推进每次输入显著增加；trace 只存总输入/输出，不能区分缓存价格或直接断定增长根因。
- `291d909d` 新增专用首关扫题入口并移除扫题器/来宾 cgroup 的时间及 token 限制，`1cfdf28b` 改用新 OFFLINE 回放确认 AR25 已解首关。精确安装 wheel 加两只 ARC wheel 预检为 24 题中 AR25 已验证、23 题待尝试（含 BP35）；普通 repo 虚拟环境缺 ARC wheel，会错误地把 `load_best_prefix` 显示为 None，不能据此重复付费。
- `e77ddb75` 与 `0b1cf1d7` 使题库及 guest 秒数缺失在付费前拒绝，且只在受控首轮模式透传运行标记。`be5c1e66` 使首轮 OFFLINE 原生运行可选无内部 deadline/回调预算，保留动作数，并已通过 160 项定向测试；普通和官方路径仍用有限预算。`5f5993e3` 固定本轮 25 题清单，`cc4ae812` 加入单题 30 分钟与私有 campaign 续跑，`234058bb` 要求每条续跑记录重新核对真实运行证据。Sol 独立复审最终 APPROVE；108 项 P7/Prime 定向测试、真实 Orb 零模型清理探针、lint、docs-check 通过。精确 wheel 零模型预检显示 24 个非 LS20 题中 AR25 已验证、23 题待尝试，首题 BP35。完整 `make promotion-check` 仍在运行，尚未付费启动。
- 官方 Competition 远端不接收 seed；本地 `seed=0` 是 OFFLINE 前缀身份。LS20 本地第 1 关初始观察在 seed 0 两次及 seed 1 一次零动作检查中相同，不能推断后续关卡或其他游戏。官方不能跳关；本轮按连续关进度轮转。

## 当前判断与未完成边界

- 上一轮 350 万 token 上限已触发，实际只新增 AR25 L1 一个已验证首关，BP35 L1 未过；这是历史预算结果。用户现明确授权继续剩余首关，不设总 token 或时间上限。仍不得把尝试等同于通关；每题最终状态要以封存与重放核验为准。
- 每次本地尝试保留独立运行目录；官方提交需要另开 Competition 会话并逐动作对照，当前预算不含官方运行。
- 用户确认的 350 万 token 总预算已用去 3,496,807 已回报 token；AR25 源 trace 因链断不作封存用量证据，但从原始事件保守扣减。BP35 中断 trace 的 2,299,681 用量通过完整哈希链核验，不等于已验证通关；provider 侧未回报 token 无法量化。绝对截止原设 2026-09-25 03:04 UTC，实际先触发 token 上限。指南为 `docs/guides/prime-p7-games-and-official-results.md`。

## 下一动作

1. 等待正在运行的完整 `make promotion-check` 结束；如失败，按失败边界修复并复验，不把定向测试等同完整安装包通过。提交本轮文档及状态更新。
2. 完整检查通过后运行 `make asterion-prime-p7-first-round`，直到 23 题都尝试完。每题在其人类动作基准或 30 分钟先到时停止；逐题核验封存/回放、用量和无遗留客体进程。超时且未封存只在精确题号、哈希链用量、来宾清理均核对后记为 `timed-out-unsealed` 并换题；遇到其他证据或基础设施故障先修复，再用同一 campaign ledger 续跑。未经另行安排，不创建官方 scorecard。
