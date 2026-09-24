# P7 ARC-AGI-3 题目与官方结果指南

这份指南把三件事分开：本地题库里有哪些题、Asterion 本地运行实际完成了什么、怎样生成 ARC 官方 scorecard 或参加官方流程。`make asterion-prime-p7-games` 是只读清单命令；它不加载游戏源码、不启动模型、不联网，也不改变任何运行记录。

## 一条命令查看本地题目和已验证进度

在仓库根目录运行：

```bash
make asterion-prime-p7-games
```

输出表格中的 `game_id` 是 ARC-AGI-3 的完整题目身份，格式是 `<短题号>-<版本号>`。短题号对应 ARC 题库目录，版本号用于区分题目版本；不要只用短题号合并不同版本。ARC 官方工具包也把 `game_id` 定义为短题号或带版本的 `<game>-<version>` 形式。[ARC-AGI 游戏结构文档](https://github.com/arcprize/docs/blob/main/game-schema.mdx)

本地题库位置是：

```text
../external-prime/arc-agi-3/environment_files/
├── ls20/9607627b/
│   ├── metadata.json
│   └── ls20.py
└── tu93/0768757b/
    ├── metadata.json
    └── tu93.py
```

当前本地可用题目：

| 完整 `game_id` | 本地标题 | 输入标签 | 总关卡 | 本地状态 | 官方 scorecard |
|---|---|---|---:|---|---|
| `ls20-9607627b` | LS20 | `keyboard` | 7 | 已验证完成 Level 1；没有全游戏完成证据 | 无 |
| `tu93-0768757b` | TU93 | `keyboard_click` | 9 | 曾运行 50 个动作后进入 `GAME_OVER`，未完成首关；以清单命令为准 | 无 |

清单命令只会把满足以下条件的运行计入“已验证”：存在 receipt、trace 已封存、replay 已验证、cleanup 已完成，并且 Broker 的完成关卡、动作数和终止原因与 receipt 一致。失败、进行中、字段缺失或身份冲突的摘要不会计入。终端输出只显示安全摘要，不显示 prompt、原始帧、密钥、私有路径或 worker 内容。

## 当前 Asterion 本地证据

目前唯一有完整成功证据的题目是 `ls20-9607627b` 的 Level 1：

| 运行 | 完成关卡 | 原始动作 | 本地 partial score | receipt |
|---|---:|---:|---:|---|
| `p7-live-20260909065351` | 1 | 23 | `3.267621` | `72dbca77…` |
| `p7-live-20260914141314` | 1 | 20 | `3.571429` | `c00e3263…` |

两次运行均为 sealed trace、replay verified、cleanup complete，并标记为 `unpromoted`。它们是本地 Asterion 证据，不是 ARC 官方排行榜成绩。

## 重新解同一题与保留每次结果

仓库当前选中的题目是 `tu93-0768757b`。在仓库根目录运行一次以下命令，就从该题的第一关、seed 0 开始一次**全新**尝试：

```bash
make asterion-prime-p7-solve
```

想重解上一题 `ls20-9607627b` 的第 1 关，运行：

```bash
make asterion-prime-p7-solve GAME=ls20
```

要挑战同一题的第 2 关，运行：

```bash
make asterion-prime-p7-solve GAME=ls20 LEVEL=2
```

`LEVEL=2` 表示以第 2 关为成功终点。官方离线引擎每次都从第 1 关开始，因此这条命令须在**同一次新尝试**中先解第 1 关，再继续解第 2 关；不能直接跳关，也不能接续历史运行。默认 `GAME=tu93 LEVEL=1`。当前短题号只支持 `ls20` 和 `tu93`，可用 `make asterion-prime-p7-games` 查询它们的完整题号和本地已验证进度。`LEVEL` 必须在所选游戏的总关卡范围内。每次真实求解都会启动模型并产生费用，运行前可先核对命令中的题号与目标关卡。

每次尝试都有独立的 `run_id`，格式为 `p7-live-UTC时间戳-唯一后缀`，分别保存在 `./.asterion-private/prime-p7-live/<run_id>/`。同一秒发起的重试也使用不同目录；创建目录时拒绝覆盖已有目录。目录中的 `summary.json` 是私有诊断文件，可能包含不宜公开的运行细节，请勿直接贴到公开渠道。可只列目录名查看历次尝试：

```bash
ls -1dt .asterion-private/prime-p7-live/p7-live-*
```

失败尝试也保留独立目录和安全终端回执。Broker 可用时，回执中的 `primitive_action_count` 是已记录的实际动作数；若尚未取得 Broker 证据，该字段为 `null`。`GAME_OVER` 会显示为 `terminal_reason: game-over` 和 `status: unsuccessful`。若在第 1 关完成后、第 2 关完成前失败，仍是目标 `LEVEL=2` 的失败尝试，不会记作成功完成两关。`make asterion-prime-p7-games` 只汇总通过封存与回放校验的成功运行，因此失败重试不会覆盖或冲掉此前的已验证成绩。重新运行会从第一关开始，不会续接上一轮的游戏状态。整次尝试共用 500 个原始动作的上限。

可视化回放和派生制品在：

```text
artifacts/arc-agi-3/catalog.json
artifacts/arc-agi-3/games/ls20-9607627b/runs/p7-live-20260909065351/
```

当前 P7 preset 使用 `OperationMode.OFFLINE`，到指定 `LEVEL` 完成时停止。单次运行的本地 partial score 按已完成关卡的逐关动作数计算，但它不能变成官方 scorecard 或全游戏结果。已有的 Level 1 receipt 也不能用于跳过第 1 关。官方评分仍需另行接入在线评估流程。

**其它关卡怎么做：**把 `LEVEL=2` 换成所需目标关卡数；每次都会从第 1 关按顺序解到目标关卡。目标越远，越可能受共用动作、模型回调和运行时限约束而未完成。也可在 [ARC 官方任务页面](https://arcprize.org/tasks)人工游玩。多关自动运行目前只有无模型假引擎验证，尚无 `ls20` 第 2 关真实付费通关证据。

## 查看官方完整题目集合

本地清单不是官方完整题目集合。官方工具包的 `Arcade.get_environments()` 返回当前账号可见的环境列表；可见数量可能受 API key 和发布状态影响。官方 README 给出的基本方式是：

```python
from arc_agi import Arcade

arc = Arcade()
for env in sorted(arc.get_environments(), key=lambda item: item.game_id):
    print(env.game_id, env.title)
```

也可以在官方任务浏览器切换到 ARC-AGI-3：

- [ARC Prize 任务浏览器](https://arcprize.org/tasks)
- [ARC-AGI-3 总览与 Public Game Set](https://arcprize.org/arc-agi/3)
- [ARC-AGI Toolkit 官方仓库](https://github.com/arcprize/ARC-AGI)

`OperationMode.OFFLINE` 只读取本地环境文件；`NORMAL` 可以使用本地环境和 API；`ONLINE` 只走 API；`COMPETITION` 是官方竞争评分模式。官方工具包 README 明确说明 Competition Mode 需要 API、对所有可用环境评分，并限制每个环境只能创建一次以及只能打开一个 scorecard；Kaggle 比赛会强制使用这一模式。[官方 Toolkit README](https://github.com/arcprize/ARC-AGI#competition-mode)

## 官方 scorecard 的生成与对照

要生成可由 ARC 服务识别的 scorecard，应使用官方工具包的在线模式，并在一次评估中创建、运行、关闭 scorecard。要用于 Community Leaderboard，还须使用 Competition Mode 并遵守其单次环境创建、单一 scorecard 和全题评分约束。实际操作顺序是：

1. 在 [ARC 平台](https://three.arcprize.org/)获取 API key，并在运行官方 Toolkit 的环境中设置 `ARC_API_KEY`。
2. 用官方 Toolkit 的 `Arcade(operation_mode=OperationMode.COMPETITION)` 创建一个 scorecard；在同一个 scorecard 下，以完整 `game_id` 创建环境，并由被评估的 agent 依照 observation 持续执行动作，直到每个游戏结束或达到事先确定的上限。
3. 关闭 scorecard，保存返回的 `card_id` 和服务端结果；在 `https://arcprize.org/scorecards/<card_id>` 查看每道游戏的 `WIN`、完成关卡、动作数与成绩。对照本地清单时，先核对完整版本号，再比较相同游戏的完成范围与动作数；本地首关 `partial_game_score` 不是整套题成绩。

官方的 [Full Play Test](https://docs.arcprize.org/full-play-test) 给出包括获取游戏列表、打开 scorecard、`RESET`、执行动作和关闭 scorecard 的完整 API 示例。Toolkit 的关键接口是：

```python
from arc_agi import Arcade, OperationMode

arc = Arcade(operation_mode=OperationMode.COMPETITION)
scorecard_id = arc.create_scorecard(
    source_url="https://github.com/<公开仓库>",
    tags=["asterion-prime", "p7"],
)
# 必须用同一个 scorecard_id 创建环境并实际运行 agent；仅打开/关闭会留下空结果。
final_scorecard = arc.close_scorecard(scorecard_id)
print(final_scorecard)
```

官方 Toolkit 还提供 `arc.get_scorecard(scorecard_id)` 和 `arc.close_scorecard(scorecard_id)`；上述代码只展示 scorecard 生命周期，不能替代中间的 agent 游戏循环。在线 scorecard 的地址和是否进入官方排行榜，以 ARC 服务返回结果为准，不能用本地 receipt、离线 replay 或私有摘要自行替代。[官方 Toolkit API README](https://github.com/arcprize/ARC-AGI#api-reference)

本仓库当前没有把 P7 的本地 solver 自动接到官方 scorecard，也没有执行在线或 Competition Mode 运行。因此当前没有可填写到官方排行榜的 Asterion scorecard URL。

## Community Leaderboard 与 Kaggle 是两条不同路径

ARC-AGI Community Leaderboard 是开源方法展示，不是官方排名。提交方式是 fork 官方仓库，把 `submissions/.example/` 复制为自己的目录，填写 `submission.yaml`，然后提交 Pull Request。ARC-AGI-3 提交需要填写由 Competition Mode 生成的 `scorecard_url`；社区仓库明确说明不会运行或验证社区代码，网站展示的数字只包括 ARC Prize Verified 分数。[Community Leaderboard README](https://github.com/arcprize/ARC-AGI-Community-Leaderboard)

Kaggle 是 ARC Prize 2026 ARC-AGI-3 正式比赛的独立提交路径。比赛页明确要求通过指定 Kaggle competition 提交，评估期间禁止联网，代码和方法必须开源才符合奖励资格。[ARC Prize 2026 ARC-AGI-3 Competition](https://arcprize.org/competitions/2026/arc-agi-3)

因此，Asterion 当前的两条可选后续路径分别是：

1. 先完成符合 Competition Mode 约束的官方在线评估，取得 scorecard URL，再按 Community Leaderboard 的 PR 模板提交公开方法。
2. 按 Kaggle 比赛规则制作独立的比赛提交包，在 Kaggle 规定的环境中运行；这不等于把本地离线 receipt 上传到排行榜。

两条路径都需要单独的代码适配、公开材料和明确的真实运行授权。本地 `make asterion-prime-p7-games` 只负责列出本地身份和已验证本地进度。
