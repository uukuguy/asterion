# 推荐核验包执行计划

## 目标

完成六个实例的完整数据运行、评分和 resume 验证：Bright Biology、Earth Science、Economics、Robotics、Bamboogle、SciFact（共 848 条）。每个结果必须记录完整案例数、分数、成本、run ID 与 resume 是否零新增调用。

## 约束

- 用户批准预算：约 $54；执行前与运行中均不得扩大到计划外实例。
- 运行配置保持当前 Asterion Agent/Judge 与工具限制；不能宣称为论文复现。
- 全量实例必须以 `--all-cases` 执行，不能把扩大样本误称全量。
- 每次真实运行后执行同范围、同 lock、同 evidence root 的 resume。

## 阶段

| 阶段 | 状态 | 完成条件 |
|---|---|---|
| 1. 保存计划与 preflight | 完成 | 本文件已创建；preflight 全部 PASS。 |
| 2. 修复全量授权通路 | 进行中 | `--all-cases --execute` 对一个真实实例能越过第 0 条授权检查，且预算/范围仍 fail-closed。 |
| 3. 完成 Bright 四项 | 待开始 | 四项均 completed、评分、resume 零新增调用。 |
| 4. 完成 Bamboogle 与 SciFact | 待开始 | 两项均 completed、评分、resume 零新增调用。 |
| 5. 发布结果与验证 | 待开始 | 中文台账更新、测试与文档检查通过。 |

## 已知失败与处理

| 现象 | 根因 | 后续动作 |
|---|---|---|
| Bright Biology `--all-cases` 返回 failed、0/103 | 真实 executor 未把全量的有限授权传入 `BenchmarkRequest`；底层对超过 50 条的论文标记数据 fail-closed。 | 先以测试定义受限授权路径，再实现并重跑；不重复原命令。 |
