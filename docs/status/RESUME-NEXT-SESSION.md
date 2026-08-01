# Live Session Checkpoint

> Updated: 2026-08-01 17:30. **Session remains active — not a final handoff.**

## TL;DR

- 推荐核验包已有 Bright Biology、Earth Science、Economics、Robotics 四项全量闭环结果。
- `00a69f7` 新增官方 BEIR SciFact 300 条范围、全量授权和安装态验收；实际全量运行正在进行。
- Bamboogle 125 条唯一外部阻塞是当前 `DEEPSEEK_API_KEY` 被 Judge 服务以 HTTP 401 拒绝。

## Current execution

- SciFact：运行 `run-6639f380eb0c4e8ab7632c6bf05979dc`，300 条、双并发、无 Judge；当前 Agent 已完成 12 条，尚无失败或最终 case 汇总。
- 已验证 SciFact 本地全量输入由官方 BEIR `scifact.zip` 的 test qrels 生成：300 查询、339 个正相关文档；原 50 条逐条一致。
- SciFact 输出根：`outputs/asterion-dci-full-validation-scifact-20260801-retry2`。不要修改其数据、锁或证据目录。
- Bright 已完成全量：Biology 103/103，0.4456，$5.6353；Earth 116/116，0.4382，$6.4950；Economics 103/103，0.3097，$6.8860；Robotics 101/101，0.3367，$7.2845。四项均零失败且无密钥 resume 已验证。

## Immediate next action

1. 监控 SciFact 至终态；验证 300/300、摘要、证据清单和无密钥 `benchmark resume`。
2. 获得有效 `DEEPSEEK_API_KEY` 后，以新的输出根重跑 Bamboogle 125 条。
3. 将六项推荐核验包的真实结果、论文参照、覆盖规模和阻塞原因同步到中文实例文档。

## Ruled-out paths

- 不要将 50 条 SciFact 输入宣称为 300 条全量；范围、ID 摘要与官方 qrels 必须一致。
- 不要把 Bamboogle 的 Judge 401 归因于并发或预算；Agent 已启动，Judge 远端拒绝凭据。
- 不要用失败的 Bamboogle 输出根 resume；终态失败批次必须使用新输出根。
- 不要在公共文档写入 prompts、答案、语料文本、模型输出、凭据或私有路径。
