# P7 ARC-AGI-3 游戏与官方成绩指南

P7 有两条运行路径：本地离线路径用于研究本地游戏并保留可回放证据；官方 Competition 路径连接 ARC 服务，在一张官方 scorecard 下尝试账号可见的全部游戏。`asterion-prime-p7-games` 只查看本地清单和本地已验证进度，不启动模型或连接 ARC。

## 1. 查看本地游戏清单

在仓库根目录运行：

```bash
make asterion-prime-p7-games
```

清单显示本地元数据中的完整 `game_id`、标题、关卡数和本地最佳已验证进度。完整 ID 由短题号和版本组成，例如 `ls20-9607627b`。命令只读取本地游戏元数据以及 `.asterion-private/prime-p7-live/` 下的运行摘要；只有 trace 已封存、replay 已验证、cleanup 已完成且身份与动作数据一致的记录才计入进度。失败或未完成的尝试不会取代成功记录。

本地游戏文件位于仓库旁的 `../external-prime/arc-agi-3/environment_files/`。这份清单不是账号可见的官方游戏目录；官方目录由 ARC 服务在官方 preflight 时返回。

## 2. 本地离线整题求解

运行一款本地游戏的整题尝试：

```bash
make asterion-prime-p7-solve GAME=ls20
```

`GAME` 接受本地短题号别名或清单中的完整 `game_id`。默认值是 `tu93`。整题求解总是从第 1 关开始，按顺序继续到 SDK 报告整题 `WIN`；不要给此命令传 `LEVEL`。它不能接续此前运行，也不能跳过已完成关卡。单次运行内，若当前关在采取普通动作后进入 `GAME_OVER`，solver 可以对同一游戏实例执行 `RESET` 重试当前关，已完成关卡仍保留；RESET 也计入动作上限。

只想检查从第 1 关推进到指定关卡的局部能力时，使用 partial diagnostic：

```bash
make asterion-prime-p7-level-witness GAME=ls20 LEVEL=2
```

Witness 同样从第 1 关开始，并依序完成到 `LEVEL` 指定的目标关卡后结束；它不是整题通关声明。它不能从历史运行恢复到第 2 关。`LEVEL` 必须是正整数且不超过该游戏的关卡总数。

每次本地调用都会生成新的 UTC 时间戳与随机后缀 `run_id`，例如 `p7-live-20260925093000-…`，证据保存在：

```text
.asterion-private/prime-p7-live/<run_id>/
```

每次运行创建独立目录，既有运行不会被重写。目录中的 `summary.json` 和 trace 是私有诊断数据，不应公开分享。可视化运行制品（若该次 SDK 运行生成）位于 `artifacts/arc-agi-3/`。重新运行会启动新游戏，从第 1 关开始；本地 OFFLINE receipt 和 replay 不能上传或转换成官方 scorecard。

`games` 清单中的本地状态和分数只描述通过本地封存与重放校验的运行范围。partial witness 不是整题 `WIN`，本地 partial score 也不是 ARC 服务端官方 score。

## 3. 官方目录只读检查

在尝试官方运行前，可执行只读 readiness 检查：

```bash
make asterion-prime-p7-official-preflight
```

Preflight 检查 operator 环境中的模型配置和 Pi/Node 入口、官方 API key，以及 ARC Competition SDK 返回的游戏目录，并输出账号当前可见的游戏 ID、每款游戏及总计的动作上限、模型回调上限和运行时限。总运行时限是各游戏限额相加的保守上界，并非预计耗时；模型回调上限也不能直接换算成费用，因为每次调用的 token 用量不同。它不创建 scorecard、不创建游戏实例、不调用模型，因此不能证明模型服务实际可调用。输出 `ready` 只说明当前检查通过，不表示已经提交或获得成绩。

官方 API key 在 [ARC Prize 平台](https://arcprize.org/platform) 创建：用 Google 或 GitHub 登录，点击右上角头像，在个人资料的 **API Keys** 中创建并复制。详见[官方 API Keys 指南](https://docs.arcprize.org/api-keys)。把 key 存入仓库已有的 operator `.env`，格式为 `ARC_API_KEY=...`，并确保运行容器能读取。不要把 key 写进命令参数、文档、提交或聊天记录；缺少 key 时 preflight 会拒绝运行。API key 与本地模型 host 配置是两项独立的运行前提。

## 4. 官方 Competition scorecard 提交

真正连接 ARC 并运行模型的唯一 P7 官方入口是：

```bash
make asterion-prime-p7-official-submit
```

这是有费用、会对外创建官方记录的操作。执行前先完成上面的 preflight，并确认 operator 已配置官方 API key 和模型 host。命令的行为固定如下：

1. 获取当前账号可见的官方游戏目录并按完整 `game_id` 排序。
2. 创建一张 Competition scorecard。
3. 对目录中每款游戏各调用一次 SDK `make`，在同一张卡下运行 P7 gameplay。
4. 尝试所有目录游戏后正常关闭 scorecard。某款游戏初始化或求解失败时会继续下一款；命令不会因为单款失败而跳过后续游戏。若初始化失败导致服务端缺少该题运行记录，最终校验会拒绝把这张卡当作已验证成绩。

Competition 路径使用官方环境，不接受 `GAME` 选择，也不能跳过关卡。每款游戏由 ARC SDK 初始化；之后 P7 在该次游戏运行里按顺序游玩，并可在当前关失败后对同一个远端游戏实例执行 `RESET` 重试当前关。每款官方游戏只有这一次 `make`，不能通过再调用 `make` 重开或跳到后续关卡。

官方 scorecard 只在正常关闭并通过返回数据校验后才会形成已验证回执。校验要求关闭结果、卡片身份以及每个预期游戏的一条匹配运行记录都齐全。若运行被中断、关闭失败或结果字段校验失败，只保留 recovery 记录；这种情况不能当作有效成绩，也不能据此生成官方 URL。

成功运行的私有证据保存在：

```text
.asterion-private/prime-p7-official/<run_id>/official-receipt.json
```

官方 receipt 包含已验证的 `card_id`、总分、每款游戏的服务端分数/状态/完成关卡/动作数和关闭摘要。只有存在 `status: closed-confirmed` 的已验证 receipt 时，才可使用其 `scorecard_url`，格式为：

```text
https://three.arcprize.org/scorecards/<card_id>
```

不要根据本地 OFFLINE receipt 拼接或宣称官方链接。未完成的官方运行可能生成私有 `official-recovery.json`；应按恢复记录处理，不能将其升级为成绩。

## 5. 当前验证边界与后续发布路径

当前实现提供本地清单、离线整题求解、partial witness、官方只读 preflight 和官方整目录 Competition 提交命令。官方目录、scorecard 生命周期与回执校验已经有本地假 SDK 测试覆盖；这些测试不创建真实 scorecard，也不证明模型实际解出游戏。**目前没有 API key 支持下的真实官方提交证据，因此没有 Asterion 官方 scorecard URL 或官方成绩可报告。**

ARC Community Leaderboard 和 Kaggle 是独立的后续流程，当前命令没有自动提交排行榜或 Kaggle 包。它们都不能接收或把本地 OFFLINE receipt 转成官方成绩。

参考资料：[ARC Competition Mode](https://docs.arcprize.org/toolkit/competition_mode)、[Full Play Test 与 scorecard](https://docs.arcprize.org/full-play-test)、[ARC-AGI Toolkit](https://github.com/arcprize/ARC-AGI)、[ARC Prize 2026 ARC-AGI-3 比赛](https://arcprize.org/competitions/2026/arc-agi-3)。
