# P7 ARC-AGI-3 游戏、解题与官方成绩指南

P7 把“本地研究”和“官方提交”分成两步：先在本地选择题目和关卡，保存经过校验的动作前缀；需要提交时，在新的官方 Competition 游戏中重新执行这些动作。OFFLINE receipt、trace 或本地分数不能上传，也不能直接转换成官方 scorecard。

## 1. 准备本地题目

查看本地题目及已验证进度：

```bash
make asterion-prime-p7-games
```

同步官方公开题目到 operator-owned ARC 根目录（只做 GET，不创建 scorecard）：

```bash
make asterion-prime-p7-sync-games
make asterion-prime-p7-games
```

清单中的 `game_id` 是带版本的完整 ID，例如 `ls20-9607627b`；命令参数也接受短 ID `ls20`。默认题目仍由 Makefile 的 `GAME` 默认值决定，建议每次显式写出 `GAME`。本地游戏文件位于仓库旁的 `../external-prime/arc-agi-3/`，运行记录位于仓库内的 `.asterion-private/prime-p7-live/`。

同步脚本拒绝 symlink、路径越界和覆盖不同版本的已有文件。它只打印数量和题号，不打印 API key、题目内容或动作。

## 2. 本地选择题目和关卡

从第 1 关开始解一题：

```bash
make asterion-prime-p7-solve GAME=ls20
```

只做到指定关卡：

```bash
make asterion-prime-p7-solve GAME=ls20 LEVEL=2
```

`LEVEL=N` 表示按官方顺序完成第 1 到第 N 关，不能跳到第 N 关。没有 `LEVEL` 时运行整题，直到题目结束或失败。旧命令仍可用于独立的关卡 witness：

```bash
make asterion-prime-p7-level-witness GAME=ls20 LEVEL=2
```

每次调用都会创建独立的 UTC 时间戳 `run_id` 目录，不会覆盖之前的尝试。一个经过验证的运行包含封存 trace、动作前后状态摘要、动作哈希链和 summary；清单只把满足身份、封存和 replay 校验的运行计入进度。

如果整题尝试在后面的关卡失败，只要前面关卡的动作能够独立重放并通过校验，已完成关卡仍会作为可复用前缀保留；失败关卡的动作不会被当作已解答案。每个关卡的边界从同一条逐动作记录中截取，不覆盖原始记录。

当目标是第 2 关时，求解器会在新的本地游戏实例中从第 1 关重新执行已保存且已验证的第 1 关动作，再开始第 2 关。这样每个关卡都可单独保存和校验，同时仍遵守“同一局按顺序过关”的 ARC 规则。初始状态或任一动作后的状态不一致时，运行在启动模型前停止；不会把不确定的动作当作成功。

查看某次运行的私有记录：

```bash
find .asterion-private/prime-p7-live/<run_id> -maxdepth 2 -type f -print
jq '{run_id, game_id, status, replay_verified, completed_level_count, primitive_action_count}' \
  .asterion-private/prime-p7-live/<run_id>/summary.json
```

不同时间的重跑是不同的运行，不会覆盖旧记录。保存的动作记录用于本地校验、关卡续解和之后的官方重新执行；它不是官方上传文件。

## 3. 官方提交前检查

先做只读 preflight：

```bash
make asterion-prime-p7-official-preflight
```

它检查 `ARC_API_KEY`、Competition 模式和官方题目目录，不创建 scorecard、不调用模型。API key 在 [ARC Prize 平台](https://arcprize.org/platform) 的个人资料 **API Keys** 中创建，放在 operator `.env` 中：

```dotenv
ARC_API_KEY=...
```

不要把 key 放进命令行、文档、提交或聊天记录。

## 4. 提交已保存的本地解法

提交一题已验证的本地解法：

```bash
make asterion-prime-p7-official-submit GAME=ls20
```

提交所有本地已有验证前缀的题目：

```bash
make asterion-prime-p7-official-submit GAME=all
```

这个入口不启动 Pi，也不调用模型。它会先读取并重新验证本地动作前缀，然后创建一张新的官方 Competition scorecard；对每个选定题目只调用一次官方 `make`，从官方返回的初始状态开始逐动作执行，并检查每次动作后的状态。远端初始状态或中间状态和本地证据不一致时立即停止，不重试不确定动作，也不伪造成功回执。

本地动作不会被上传。官方端实际发生的是一组新的动作执行，因此官方 receipt 的动作数、关卡状态和分数以 ARC 服务返回值为准。未选题目保持未运行；不会为它们伪造 run 或 score。

旧的全目录模型评估入口改名为：

```bash
make asterion-prime-p7-official-live-eval
```

它是独立的有限预算模型评估，不是已保存动作提交；除非已经明确安排费用和运行范围，不要使用它代替 `official-submit`。

## 5. 回执和 scorecard 对照

验证通过的官方回执保存于：

```text
.asterion-private/prime-p7-official/<run_id>/official-receipt.json
```

查看卡号、服务端总分和官方链接：

```bash
jq '{status, card_id, overall_score, catalog_count, selected_count,
    played_runs, skipped_count, scorecard_url}' \
  .asterion-private/prime-p7-official/<run_id>/official-receipt.json
```

只有 `status` 为 `closed-confirmed` 时，`scorecard_url` 才是已验证的官方链接：

```text
https://three.arcprize.org/scorecards/<card_id>
```

`overall_score` 是服务端 scorecard 的值；本地估算、部分关卡分数和 replay 成功都不能替代它。中断、关闭失败、远端状态分歧或字段校验失败只会留下 `official-recovery.json`，不能当作官方成绩。

ARC Competition 的官方说明见 [Competition mode](https://docs.arcprize.org/toolkit/competition_mode) 和 [methodology](https://docs.arcprize.org/methodology)。社区排行榜与 Kaggle 提交是后续独立流程，当前命令不会自动发布排行榜。
