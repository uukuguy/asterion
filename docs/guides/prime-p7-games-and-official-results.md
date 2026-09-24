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

每次调用都会创建独立的 UTC 时间戳 `run_id` 目录，不会覆盖之前的尝试。一个经过验证的运行包含封存 trace、动作前后状态摘要、动作哈希链和 summary；清单只读这些记录，不运行题目源码。续解或官方提交前会再用新本地游戏严格重放校验。

如果整题尝试在后面的关卡失败，只要前面关卡的动作能够独立重放并通过校验，已完成关卡仍会作为可复用前缀保留；失败关卡的动作不会被当作已解答案。每个关卡的边界从同一条逐动作记录中截取，不覆盖原始记录。

当目标是第 2 关时，求解器会在新的本地游戏实例中从第 1 关重新执行已保存且已验证的第 1 关动作，再开始第 2 关。这样每个关卡都可单独保存和校验，同时仍遵守“同一局按顺序过关”的 ARC 规则。初始状态或任一动作后的状态不一致时，运行在启动模型前停止；不会把不确定的动作当作成功。

同一次没有中断的游戏里，从第 1 关进入第 2 关无需重放；重放只发生在新开的本地游戏或官方 Competition 游戏中，因为那是另一局。保存动作的作用是校验和重新执行，不是让服务端直接恢复到旧关卡。

查看某次运行的私有记录：

```bash
find .asterion-private/prime-p7-live/<run_id> -maxdepth 2 -type f -print
jq '{run_id, replay_verified, sealed_trace, cleanup_complete, completed_prefix, broker, diagnostics}' \
  .asterion-private/prime-p7-live/<run_id>/summary.json
```

不同时间的重跑是不同的运行，不会覆盖旧记录。保存的动作记录用于本地校验、关卡续解和之后的官方重新执行；它不是官方上传文件。

### 25 题广度优先本地扫题

```bash
make asterion-prime-p7-sweep
make asterion-prime-p7-games
```

扫题按题号轮转：每题只尝试当前最早未解的一关；成功并经重放校验后，下一轮再试该题的下一关；失败则本次扫题先转到别题。每关新增动作（包括 RESET）达到目录给出的人类基准步数就停止；已验证的前几关动作会在新本地游戏里先重放，它们不占本关步数。已有 LS20 第 2 关超基准的失败尝试会暂缓，不再作为这轮的付费重试。每次尝试保存在单独的私有运行目录，扫题仅使用 OFFLINE 游戏，不创建官方 scorecard。

LS20 第 1 关的可计量样本用了 20 步、32,830 输入和 36,418 输出，共 69,248 旧口径 token，耗时 4 分 32 秒。其余 24 题首关的人类步数上限合计 851；按样本的每步消耗机械外推，约需 295 万 token、3 小时 13 分钟。旧样本未计缓存输入，且不同题难度不同，这不是完成首轮的保证。用户确认的首轮停止线为 350 万已回报 token、4 小时；每题时间按人类步数及样本速度估算，最少 10 分钟、最多 30 分钟。部分后续关卡的人类步数很高，可能先触发 30 分钟时间上限，不能把这种超时当作达到人类步数上限。总 token 上限在每次尝试结束后检查，最后一次可能使总量略高于上限。子进程没有有效运行证据、运行回放或封存失败，以及尝试没有任何可记录用量时，调度器均停止后续尝试。新用量来自 DeepSeek Flash 经 Pi 返回的计数：`input_tokens` 包括缓存读写 token，`output_tokens` 为输出 token；旧的中断运行若没有 usage 事件，准确 token 数保持未知。扫题结束的 JSON 列出运行 ID、已解题号、暂缓题号和 token 总量。实际费用受缓存命中、时段和服务商价格影响，token 总量不是账单金额。

查看单次运行中已落盘的 token 事件：

```bash
jq -s '[.[] | select(.kind == "arc.usage.reported") | .payload] |
  {input_tokens: (map(.input_tokens) | add // 0),
   output_tokens: (map(.output_tokens) | add // 0)}' \
  .asterion-private/prime-p7-live/<run_id>/trace/prime-trace.jsonl
```

本地固定 `seed=0` 只属于 OFFLINE 游戏和本地动作前缀身份。官方 Competition 远端会话不提供玩家选 seed 的操作；P7 官方适配器的 `seed=0` 是 broker 兼容字段，不证明官方局面由该 seed 控制。官方提交只凭实际返回的初始观察及每一步观察与本地记录严格一致才继续。

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

本地动作不会被上传。官方端实际发生的是一组新的动作执行，因此官方 receipt 的动作数、关卡状态和分数以 ARC 服务返回值为准。Competition 关闭 scorecard 时，官方 SDK 会为未选题目建立零动作、零分的 `NOT_FINISHED` 占位 run；这些占位不表示 Asterion 执行过该题。回执分别报告实际执行的 `played_runs` 和未选题目的 `skipped_count`。

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
https://arcprize.org/scorecards/<card_id>
```

`overall_score` 是服务端 scorecard 的值；本地估算、部分关卡分数和 replay 成功都不能替代它。中断、关闭失败、远端状态分歧或字段校验失败只会留下 `official-recovery.json`，不能当作官方成绩。

如果提交命令在官方卡**已正常关闭**后因结果校验失败而留下恢复记录，可只读核对官方公开成绩并补写回执。把该次运行目录名填入 `RUN`：

```bash
make asterion-prime-p7-official-recover RUN=<run_id>
```

此命令只对 `https://arcprize.org/api/v3/scorecards/<card_id>` 发起一次不带密钥的 GET，不建新卡、不重放动作。它要求私有恢复记录确认正常关闭，并逐项核对卡号、完整题目目录、已选题目的运行 ID 及未选题目的零动作占位；校验通过才在同一目录创建 `official-receipt.json`，不会覆盖已有回执。只有 `recovery-required` 或 GET 不可用时，不能把公开页面或本地记录单独当作有效回执。

ARC Competition 的官方说明见 [Competition mode](https://docs.arcprize.org/toolkit/competition_mode) 和 [methodology](https://docs.arcprize.org/methodology)。社区排行榜与 Kaggle 提交是后续独立流程，当前命令不会自动发布排行榜。
