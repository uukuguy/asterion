# Live Session Checkpoint

> Updated: 2026-09-25 05:28 CST. **Session remains active — not a final handoff.**

## 当前任务

实现 P7 本地选题选关、逐关保存可校验动作，以及只对本地已验证题目执行官方 Competition 提交。用户已明确选择该方向；真实付费评估/官方建卡仍须按仓库预算边界单独确认。

## 已验证事实

- `make asterion-prime-p7-solve GAME=ls20 LEVEL=2` 现在接受显式 `LEVEL`；不传 `LEVEL` 仍是整题。每次新本地运行会在模型前把先前已验证前缀重新执行进当前 broker 和 trace。新的 `run_id` 保留独立时间戳目录，不覆盖旧运行。
- `p7/solutions.py` 从私有封存 trace、summary、recording 复原动作，核验身份/哈希链/软链接边界/RESET/ACTION6，再经新 OFFLINE 引擎逐动作复现；支持旧版 LS20 历史记录和长记录截断。已安装 wheel、阻断网络的诊断确认 LS20 第 1 关 20 动作可恢复。本地第 2 关 broker 预热实测完成第 1 关并记入 20 动作，未启动模型。
- 后续关卡失败时，运行器现从逐动作 trace 截取最后已过关卡，使用新本地引擎核验并封存 `arc.run.partial`；读取器要求与 summary、完整 recording 和封存链一致，只复用已完成的关卡。整题失败不会抹去先前可验证进度。定向跨模块测试已通过。
- `make asterion-prime-p7-games` 现以只读方式显示正常已过关卡和失败后已封存的部分进度，不运行题目源码；后者 score 显示为 `—`。真实公开命令实测列出 25 题，LS20 第 1 关与既有分数仍显示。初次清单实现曾因脚本导入路径失败，已修复并增加真实 Make 子进程测试。
- `make asterion-prime-p7-sync-games` 经只读 GET 同步官方账号可见 25 题；`make asterion-prime-p7-games` 现列出 25 题，只有 LS20 本地第 1 关是已验证进度。旧 TU93 本地同 ID 源码与当前官方源码不同，已无损移到 `../external-prime/arc-agi-3/archived-local-games/tu93-0768757b-source-0768757bb4b3/`，官方当前源码落入正常目录。同步器不覆盖同 ID 不同内容，并可续写匹配的中断元数据。
- 官方 selected session、跳过题目 scorecard 解析、已存动作初始/逐步摘要核验、RESET 与不确定操作即停均已实现。`make asterion-prime-p7-official-submit GAME=ls20` 和 `GAME=all` 是无 Pi/模型的已存动作执行入口；缺少显式 `GAME` 在构建前拒绝。旧全目录模型路径改名 `asterion-prime-p7-official-live-eval`。
- 官方目录只读 `make asterion-prime-p7-official-preflight` 实跑通过：25 题，上界 38,142 动作、3,200 模型回调、90,000 秒。未创建 card 或调用模型。已安装 wheel 的已存 LS20 前缀预检在阻断网络下通过。
- P7 聚焦 78 项、`make lint`、`make docs-check` 已通过；`make promotion-check` 完整通过，报告 25 个命令、0 次 provider 操作、无完整数据集。首次完整测试剩余的两项安装版问题和一项 Make 静态误判已修复。旧 Make 测试曾意外触发本地模型；现已改为无模型 dry-run。
- 清单公开命令修复后，43 项关卡/清单/提交定向测试、lint 和 docs-check 再次通过；独立关键代码复审未发现实质阻塞问题。`promotion-check` 的完整通过发生在最后的清单 Make 入口改动之前，该入口已用真实命令和子进程测试单独验证。

## 当前判断与未完成边界

- 本地证据不能补传为官方成绩；正式提交必须在新的官方游戏实例重新执行动作，按远端初始和每一步状态核验。若有差异，保留 recovery 记录，不生成有效官方回执。
- 尚未创建真实官方 scorecard，没有官方分数或 URL；只完成了只读预检与无模型本地/假 SDK 验证。
- 真实官方 scorecard 仍未创建；服务器初始状态可能与本地 OFFLINE 回放不一致，提交时必须以远端逐步比对结果为准。旧测试曾意外触发一次真实本地模型尝试：新私有运行目录 `p7-live-20260924205419-06503ae29454ae2cb6950224` 有 6 条 worker-cell 记录、0 个 ARC 游戏动作；没有留下运行进程。当前测试已改为无模型 dry-run。

## 下一动作

1. 若用户选择真实官方提交，先确定单题范围（当前 LS20 仅第 1 关有本地验证动作），再执行 `make asterion-prime-p7-official-submit GAME=ls20` 并核验服务器回执；该操作创建对外 scorecard。
2. 如继续本地解题，执行 `make asterion-prime-p7-solve GAME=ls20 LEVEL=2`，会在模型前重放第 1 关的 20 个已存动作，然后继续第 2 关。
