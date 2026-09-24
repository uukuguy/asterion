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
| `tu93-0768757b` | TU93 | `keyboard_click` | 9 | 截至本指南编写时只做过零动作加载预检；以清单命令为准 | 无 |

清单命令只会把满足以下条件的运行计入“已验证”：存在 receipt、trace 已封存、replay 已验证、cleanup 已完成，并且 Broker 的完成关卡、动作数和终止原因与 receipt 一致。失败、进行中、字段缺失或身份冲突的摘要不会计入。终端输出只显示安全摘要，不显示 prompt、原始帧、密钥、私有路径或 worker 内容。

## 当前 Asterion 本地证据

目前唯一有完整成功证据的题目是 `ls20-9607627b` 的 Level 1：

| 运行 | 完成关卡 | 原始动作 | 本地 partial score | receipt |
|---|---:|---:|---:|---|
| `p7-live-20260909065351` | 1 | 23 | `3.267621` | `72dbca77…` |
| `p7-live-20260914141314` | 1 | 20 | `3.571429` | `c00e3263…` |

两次运行均为 sealed trace、replay verified、cleanup complete，并标记为 `unpromoted`。它们是本地 Asterion 证据，不是 ARC 官方排行榜成绩。

可视化回放和派生制品在：

```text
artifacts/arc-agi-3/catalog.json
artifacts/arc-agi-3/games/ls20-9607627b/runs/p7-live-20260909065351/
```

当前 P7 preset 使用 `OperationMode.OFFLINE`，并在第一关完成后停止。改变 Make 的题目 ID 只能选择已准备的本地题目，不能把一次 Level 1 的本地 receipt 变成全游戏结果，也不能生成官方 scorecard。要进行多关继续运行或官方评分，必须另行实现对应的应用边界并单独授权真实运行。

**其它关卡现在怎么做：**在 [ARC 官方任务页面](https://arcprize.org/tasks)可以人工选择 ARC-AGI-3 游戏并继续玩完整游戏。当前 `make asterion-prime-p7-solve` 是固定的“首关完成即停止”研究 preset：Broker 在关卡数增加时终止，能力 receipt 也只接受完成一关。若要让 Asterion 自动做第 2 关及之后的关卡，需要改 Broker 的停止条件、跨关卡上下文与动作上限、逐关计分和 receipt、回放校验，再用无模型假引擎验证各关边界。单纯重跑首关命令会从初始状态开始，不能接着上一关玩。

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
