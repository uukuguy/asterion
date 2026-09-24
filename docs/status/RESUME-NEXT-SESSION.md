# Live Session Checkpoint

> Updated: 2026-09-25 05:04 CST. **Session remains active — not a final handoff.**

## 当前任务

实现 P7 本地选题选关、逐关保存可校验动作，以及只对本地已验证题目执行官方 Competition 提交。用户已明确选择该方向；真实付费评估/官方建卡仍须按仓库预算边界单独确认。

## 已验证事实

- `make asterion-prime-p7-solve GAME=ls20 LEVEL=2` 现在接受显式 `LEVEL`；不传 `LEVEL` 仍是整题。每次新本地运行会在模型前把先前已验证前缀重新执行进当前 broker 和 trace。新的 `run_id` 保留独立时间戳目录，不覆盖旧运行。
- `p7/solutions.py` 从私有封存 trace、summary、recording 复原动作，核验身份/哈希链/软链接边界/RESET/ACTION6，再经新 OFFLINE 引擎逐动作复现；支持旧版 LS20 历史记录和长记录截断。已安装 wheel、阻断网络的诊断确认 LS20 第 1 关 20 动作可恢复。本地第 2 关 broker 预热实测完成第 1 关并记入 20 动作，未启动模型。
- `make asterion-prime-p7-sync-games` 经只读 GET 同步官方账号可见 25 题；`make asterion-prime-p7-games` 现列出 25 题，只有 LS20 本地第 1 关是已验证进度。旧 TU93 本地同 ID 源码与当前官方源码不同，已无损移到 `../external-prime/arc-agi-3/archived-local-games/tu93-0768757b-source-0768757bb4b3/`，官方当前源码落入正常目录。同步器不覆盖同 ID 不同内容，并可续写匹配的中断元数据。
- 官方 selected session、跳过题目 scorecard 解析、已存动作初始/逐步摘要核验、RESET 与不确定操作即停均已实现。`make asterion-prime-p7-official-submit GAME=ls20` 和 `GAME=all` 是无 Pi/模型的已存动作执行入口；缺少显式 `GAME` 在构建前拒绝。旧全目录模型路径改名 `asterion-prime-p7-official-live-eval`。
- 官方目录只读 `make asterion-prime-p7-official-preflight` 实跑通过：25 题，上界 38,142 动作、3,200 模型回调、90,000 秒。未创建 card 或调用模型。已安装 wheel 的已存 LS20 前缀预检在阻断网络下通过。
- P7 聚焦测试、Make dry-run、`make lint`、`make docs-check` 已通过。第一次 `make promotion-check` 的完整测试阶段失败，主要原因是旧 Make 测试把现在合法的 `LEVEL=2` 当错误并实际触发解题；该测试已改为 dry-run，12 个 Make 定向测试通过。完整 3208 测试复跑后还剩 3 项失败：两个安装版测试、一个误判 `live-eval` 为 shell `eval` 的静态测试。安装版缺失加载器资源和静态误判已修复，另一安装版 gameplay 失败仍在诊断；promotion-check 尚未通过。

## 当前判断与未完成边界

- 本地证据不能补传为官方成绩；正式提交必须在新的官方游戏实例重新执行动作，按远端初始和每一步状态核验。若有差异，保留 recovery 记录，不生成有效官方回执。
- 尚未创建真实官方 scorecard，没有官方分数或 URL；只完成了只读预检与无模型本地/假 SDK 验证。
- 当前完整测试及 `promotion-check` 尚未最终通过。旧测试曾意外触发一次真实本地模型尝试：新私有运行目录 `p7-live-20260924205419-06503ae29454ae2cb6950224` 有 6 条 worker-cell 记录、0 个 ARC 游戏动作；没有留下运行进程。不要再执行旧版 `tests.test_prime_make_presets` 或未修复的旧完整门禁。

## 下一动作

1. 收取安装版 gameplay 单测诊断与修复，跑 3 项定向回归，再重跑必要门禁；检查无遗留进程与 Git 状态。
2. 无网络/无模型验证已存 LS20 前缀从公开命令到假 Competition card 的安装包路径，核对回执和恢复分支；复审最后改动。
3. 确认真实官方执行的外部提交范围与费用边界，再执行选题提交；未经确认不创建真实 scorecard。
