# 推荐核验包发现

- 2026-08-01 preflight：Agent、Judge、Node、Pi checkout 与资源基础检查均 PASS；尚未发生模型调用。
- 计划实例总量：Bright 四项 423 条，Bamboogle 125 条，SciFact 300 条，共 848 条；历史 50 条账单外推约 $54。
- Bright Biology 的全量锁和 plan 成功解析为 103 条；执行 run ID `run-c44693f4ccba4a9a98913ea6ad87eba2` 在案例启动前失败，结果为 0/103。
- 根因证据：`RealDciBenchmarkExecutor` 仅构造普通 `BenchmarkRequest`；`run_benchmark_async` 对超过 50 条且具有论文 scope 的选集要求 `FullExecutionAuthorization`。当前 `asterion-dci benchmark` CLI 未提供或传递这个有限授权。
- 修复后，完整实例需显式传入 `--max-cost-usd`；该值是一次运行的总授权上限，而非缩减题目数的参数。
- 测试已固定期望：完整 Bamboogle request 必须携带一次性 full execution authorization，并精确绑定 `qa.bamboogle.main.full`。
