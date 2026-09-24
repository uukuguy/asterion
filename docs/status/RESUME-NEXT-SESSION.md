# Live Session Checkpoint

> Updated: 2026-09-25 07:13 CST. **Session remains active — not a final handoff.**

## 当前任务

按用户要求，对 ARC-AGI-3 目录中的 25 题做本地 OFFLINE 广度优先扫题：每题只试下一连续关；一关成功并验证后下轮再进一关，失败本轮转到其他题。每关新增动作到该关公布的人类基准数就停止。LS20 第 2 关旧实验已超过 123 步，因此本轮暂缓。只保存本地证据，不创建新的官方 scorecard。

## 已验证事实

- `make asterion-prime-p7-games` 列出 25 题；目前只有 LS20 第 1 关是已验证前缀。官方既有卡 `14868b83-3f40-4afd-84b0-4d25176f97d0` 只有这一关的部分成绩，24 题未选，不能视为整题通关。
- LS20 第 1 关的可计量运行记录为 20 步、输入 32,830、输出 36,418，共 69,248 旧口径 token，历时 272 秒。其余 24 题首关的人类上限合计 851 步，按每步消耗机械推算约 295 万 token、3 小时 13 分钟，旧记录漏计缓存输入。用户确认首轮总停止线为 350 万 token、4 小时；每次尝试时间按关卡步数估算，10 至 30 分钟；总上限在尝试间检查。
- 此前 LS20 第 2 关续解重放 20 个已验证第 1 关动作后，新记约 242 个第 2 关动作，超过 123 的人类基准才被人工停止；该运行未封存且没有用量事件，不复用作前缀，不推算其 token。
- `1a178f4a` 将 Prime runtime 用量事件流式落到 trace，`f38143c4` 将 Pi 缓存读写计入输入 token；`987ca598` 加精确本地扫题动作上限，`a8ef4d53` 加轮转调度器，`3f1499ba` 将扫题接入 P7 operator/Make，`4d820313` 验证中断 trace 哈希链并在用量缺失时停机。
- 刚构建 wheel 的隔离环境中，调度器 `--max-attempts 0` 预检成功：attempted=0、token=0。`make promotion-check` 完整通过：25 条命令、0 次 provider 操作、无完整数据集。`make lint`、`make docs-check` 和定向测试通过；独立复审批准付费首轮。
- 首次付费 sweep 只尝试 AR25 第 1 关。运行 `p7-live-20260924230447-46fc1ea55b4041a6f56f8786` 的 broker 到 22 步过关并经离线 broker replay，但 usage/action 并发写 trace 导致序号 9 重复、哈希链断裂；summary 的 `sealed_trace=false`，不能成为已验证可复用前缀。调度器正确拒绝继续其他题并返回 `usage-missing-after-model-activity`，但其 `0 token` 汇总是假象：原始 27 条 usage 事件逐条合计输入 1,157,891、输出 39,235，共 1,197,126 token，因链损坏仅作保守预算扣减。没有遗留求解进程。
- `4a030f99` 已串行化 trace 的写入、封存与快照，八线程并发回归前红后绿。AR25 的既有损坏 trace 保留原状；正在评估从另一份录制文件及 broker receipt 新建可验证恢复运行，避免重新调用模型。
- 官方 Competition 远端不接收 seed；本地 `seed=0` 是 OFFLINE 前缀身份。LS20 本地第 1 关初始观察在 seed 0 两次及 seed 1 一次零动作检查中相同，不能推断后续关卡或其他游戏。官方不能跳关；本轮按连续关进度轮转。

## 当前判断与未完成边界

- 这只是有限预算的首轮扫题，不保证 25 题或全部关卡在预算内过关；模型解题能力尚无新实跑证据。
- 每次本地尝试保留独立运行目录；官方提交需要另开 Competition 会话并逐动作对照，当前预算不含官方运行。
- 用户确认的 350 万 token 总预算须扣减 AR25 暂计的 1,197,126 token；未恢复和核实之前，不可按调度器错误报告的 0 token 重启完整预算。指南为 `docs/guides/prime-p7-games-and-official-results.md`。

## 下一动作

1. 收取 AR25 无模型恢复可行性调查；只以新证据目录保存恢复结果，不改写损坏原 trace。若不可安全恢复，明确记录边界。
2. 用定向测试、安装 wheel 零模型预检确认 `4a030f99` 和 sweep 续跑顺序；按剩余 token 预算设置续跑，避免重复付费解已过关的 AR25。
3. 再次运行本地 sweep，并用 `make asterion-prime-p7-games` 核对已验证进度；不得创建官方 scorecard。
