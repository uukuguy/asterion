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

### 已验证历史与预测核对

本地 P7 求解默认使用 `verified` 变体。目标为第 2 关时，操作员先用已验证的首关前缀启动新的一局；首关动作在模型开始前重放到同一个 broker，并作为本次运行的已验证历史保留。请用正常的 Makefile 参数选择题目和关卡：

```bash
make asterion-prime-p7-games
make asterion-prime-p7-level-witness GAME=ls20 LEVEL=2
make asterion-prime-p7-solve GAME=ls20 LEVEL=2
```

求解器会先读取当前状态。若 `levels_completed` 大于零，它会分页读取已重放的首关历史；历史条目只包含已经发生的动作、稳定帧的前后摘要、变化格子摘要、关卡数和 SDK 状态。提示词要求先查询历史再用 `frame_at(sequence)` 查看相应的**稳定末帧**；API 允许读取本次运行中已经发生的序号，拒绝未来序号。原始帧、完整历史和模型假设只留在私有运行证据中，不进入公开回执或故事网页。

未知机制仍只允许以单个动作调用 `act()` 探查。已有证据支持的多步方案必须调用 `act_checked(plan)`；每一步都要携带一个可区分的预期，例如指定格子的稳定颜色、完整稳定帧哈希、关卡增加或 `WIN`/`GAME_OVER` 状态。系统在第一个预期不符、动作不可用、关卡边界、`GAME_OVER` 或动作上限处停止，且不会执行或计入队列尾部动作。应读取返回的实际观察和不符信息，修订假设后再制定下一步方案。

每次本地重试均创建新的 UTC 时间戳 `run_id` 目录；不要覆盖或将一次失败运行续写为另一种方案。若需要研究性 A/B 对照，`legacy` 只可在本地 level witness 或 sweep guest 中显式选择，它保留旧的批量 `act()` 行为：

```bash
ASTERION_PRIME_P7_HISTORY_VARIANT=legacy \
  make asterion-prime-p7-level-witness GAME=ls20 LEVEL=2
```

官方入口不接受 `legacy`，官方提交也不应作为这个对照的一部分。私有 summary 已记录历史与预测计数及实验参数。对照时须在同一题目、seed、目标关卡、动作上限和**相同的外层截止与无动作停止线**下，分别保存 `legacy` 与 `verified` 时间戳目录，再比较私有动作、token 和预测核对指标。单独执行上述 `level-witness` 命令只使用普通 P7 的内部一小时期限，**没有**第二轮扫题 supervisor 的每题 30 分钟与连续 5 分钟无动作停止线，不能拿两种运行方式的数据当成同条件 A/B。一轮成功或单元测试不能证明该策略改善成绩。

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

只完成本地首关轮次时，使用：

```bash
make asterion-prime-p7-first-round
make asterion-prime-p7-games
```

`first-round` 跳过已有可验证首关的题目，其他题目各尝试一次第 1 关，结束后不进入第 2 关；失败关不会在同一轮自动重试。2026-09-25 用户依据当天账单另行授权撤销本轮总 token、总时长限制，同时指定每题以人类基准动作数及 30 分钟双重停止线为准。证据核验及来宾进程清理仍有效。该受控 OFFLINE sweep 模式移除了 Prime 会话内部的 1 小时和 128 次回调预算；普通和官方运行仍保留原限制。它不创建或提交官方 scorecard。终端的 `attempted` 表示尝试数，不等于解出数；最终以 `make asterion-prime-p7-games` 的已验证关卡为准。

已有首关解法的 17 题进入第 2 关时，运行：

```bash
make asterion-prime-p7-second-round
make asterion-prime-p7-games
```

该命令固定这 17 个题号；每题先校验并重放保存的首关动作，然后只尝试第 2 关一次，不自动进入第 3 关。第 2 关新增动作以该题的人类基准为上限，每题最多 30 分钟，没有整轮 token 或时间上限；本轮若连续 5 分钟没有新的 `arc.action`，也会停止当前题并标记为 `execution-stalled`。成功、达到动作上限、有完整用量证据的超时及执行停滞分别记入 `.asterion-private/prime-p7-live/second-round-campaign.json`；中断后重跑同一命令会跳过已记录的题目。执行停滞必须同时具备匹配的题号、seed、首关前缀、哈希链、用量和来宾清理证据，不能把它当作解题成功；SIGTERM 留下未封存 trace 时由调度器写入私有 stall receipt 后才可续跑。若首个动作前连 run 身份或 trace 都没有形成，命令会安全停止并要求人工核对，不能伪造零 token 记录。证据不完整或来宾清理未确认时，命令停止。该命令只运行本地 OFFLINE 游戏，不创建官方 scorecard。新关卡的网页可在对应运行封存并通过回放后生成；不同运行的求解和网页生成可并行，网页目录的写入需串行。

2026-09-25 首关轮次已完成：除原已验证的 LS20、AR25 外，23 题各尝试一次，其中 15 题通过第 1 关并完成封存、回放和清理核验，8 题到人类基准动作数仍未解。当前 25 题中 17 题有已验证首关，尚无整题通关。每题实际动作数、首关人类基准及本轮 trace 已回报 token 如下；输入包括缓存 token，不能按总量直接计算费用。

| 题目 | 结果 | 动作/人类基准 | 输入 token | 输出 token |
|---|---|---:|---:|---:|
| BP35 | 未解 | 21/21 | 2,449,935 | 75,096 |
| CD82 | 未解 | 55/55 | 1,897,435 | 75,372 |
| CN04 | 已验证首关 | 18/29 | 582,081 | 41,707 |
| DC22 | 已验证首关 | 43/59 | 3,112,196 | 90,886 |
| FT09 | 已验证首关 | 10/43 | 679,657 | 34,861 |
| G50T | 未解 | 78/78 | 3,840,737 | 97,306 |
| KA59 | 未解 | 28/28 | 1,604,143 | 68,169 |
| LF52 | 已验证首关 | 28/32 | 2,573,886 | 83,263 |
| LP85 | 已验证首关 | 9/17 | 462,941 | 39,166 |
| M0R0 | 已验证首关 | 17/30 | 1,520,184 | 46,206 |
| R11L | 已验证首关 | 10/22 | 1,749,624 | 60,083 |
| RE86 | 已验证首关 | 21/26 | 476,203 | 30,482 |
| S5I5 | 未解 | 20/20 | 1,307,305 | 77,268 |
| SB26 | 已验证首关 | 13/18 | 446,493 | 13,277 |
| SC25 | 已验证首关 | 22/36 | 1,849,769 | 48,591 |
| SK48 | 未解 | 61/61 | 3,876,213 | 109,276 |
| SP80 | 已验证首关 | 6/39 | 218,753 | 11,783 |
| SU15 | 已验证首关 | 13/22 | 675,639 | 20,907 |
| TN36 | 未解 | 32/32 | 3,004,767 | 144,003 |
| TR87 | 已验证首关 | 40/54 | 5,539,019 | 181,014 |
| TU93 | 未解 | 19/19 | 1,537,619 | 93,059 |
| VC33 | 已验证首关 | 7/7 | 870,877 | 59,431 |
| WA30 | 已验证首关 | 37/71 | 1,437,658 | 46,454 |
| **本轮合计** | **15 已验证、8 未解** | — | **41,713,134** | **1,547,660** |

私有逐题证据在 `.asterion-private/prime-p7-live/<run_id>/`；题号与 run ID 的对应关系在 `.asterion-private/prime-p7-live/first-round-campaign.json`。终端本轮累计 43,260,794 已回报 token。用户的 2026-09-25 账户截图曾显示 23,449,856 缓存命中输入、493,873 未命中输入和 531,567 输出；这是截图时的账户当日汇总，不是上述 23 次运行的缓存拆分。trace 暂无逐次缓存命中字段，实际人民币费用应以服务商账单为准。

### 打开已完成题目的解题总结网页

已验证首关的 17 道题均有带动作和画面回放、中文讲解、证据引用的本地网页制品。打开本地目录：

```bash
make asterion-prime-p7-stories
```

浏览器中的目录可按题号进入各次运行。LS20 有两个历史运行页面：本轮官方提交所用的 20 步记录是 `p7-live-20260914141314`，此前的 23 步研究记录是 `p7-live-20260909065351`。按 `Ctrl-C` 停止本地目录服务；单文件 HTML 仍可直接离线打开，保存在 `artifacts/arc-agi-3/exports/`。网页中的动作、画面、用量及本地分数来自封存运行；文字讲解只采用通过引用校验的分析版本。官方逐题成绩仍以本指南第 5 节的 `official-receipt.json` 为准。

首轮进度保存在 `.asterion-private/prime-p7-live/first-round-campaign.json`。重启同一命令会跳过这轮已经尝试过而未解的首关，不会把更早的 BP35 中断运行当成本轮完成；已验证过关仍以动作重放结果为准。30 分钟到点时，只有单个题号对应的运行、哈希链用量和来宾清理均得到核对，才记作 `timed_out_unsealed_level_one` 并换题；这个状态不是已验证的过关或封存失败回执。证据不完整时命令停止，修复后可再次运行同一命令。

扫题按题号轮转：每题只尝试当前最早未解的一关；成功并经重放校验后，下一轮再试该题的下一关；失败则本次扫题先转到别题。每关新增动作（包括 RESET）达到目录给出的人类基准步数就停止；已验证的前几关动作会在新本地游戏里先重放，它们不占本关步数。已有 LS20 第 2 关超基准的失败尝试会暂缓，不再作为这轮的付费重试。每次尝试保存在单独的私有运行目录，扫题仅使用 OFFLINE 游戏，不创建官方 scorecard。

LS20 第 1 关的可计量样本用了 20 步、32,830 输入和 36,418 输出，共 69,248 旧口径 token，耗时 4 分 32 秒。其余 24 题首关的人类步数上限合计 851；按样本的每步消耗机械外推，约需 295 万 token、3 小时 13 分钟。旧样本未计缓存输入，且不同题难度不同，这不是完成首轮的保证。**以下为此前有限预算的普通 `sweep` 规则及实跑记录；上面的 `first-round` 使用新停止线。**用户当时确认的停止线为 350 万已回报 token、4 小时；每题时间按人类步数及样本速度估算，最少 10 分钟、最多 30 分钟。部分后续关卡的人类步数很高，可能先触发 30 分钟时间上限，不能把这种超时当作达到人类步数上限。调度器运行中每 250 毫秒核对已经写入并通过哈希校验的用量，到上限即停止本次尝试，并核验来宾内该尝试的进程组已退出。模型调用中尚未回报的 token 可能超出停止线，因此续跑必须扣减已有用量并留出余量。子进程没有有效运行证据、运行回放或封存失败，以及尝试没有任何可记录用量时，调度器均停止后续尝试。新用量来自 DeepSeek Flash 经 Pi 返回的计数：`input_tokens` 包括缓存读写 token，`output_tokens` 为输出 token；旧的中断运行若没有 usage 事件，准确 token 数保持未知。扫题结束的 JSON 列出运行 ID、已解题号、暂缓题号和 token 总量。实际费用受缓存命中、时段和服务商价格影响，token 总量不是账单金额。

2026-09-25 首轮实跑证明旧 LS20 样本严重低估了新题消耗：AR25 第 1 关 22 步过关，原始 27 条用量记录暂计 1,197,126 token，后经三份动作录制及独立 OFFLINE 重放恢复为已验证前缀；原 trace 并发断链，故原始用量仅作保守预算扣减。续跑 BP35 第 1 关在 18 步时触发本轮 token 上限，40 条哈希链有效用量记录合计 2,299,681 token；该关人类基准为 21 步，运行被中断且无封存回执，因此不能算作过关。两次合计 3,496,807 已回报 token，接近 350 万停止线，仅新增 AR25 一个已验证首关。BP35 的前 10 次调用输入合计 170,107 token，后 10 次为 1,004,287，说明单次输入随运行显著增大；当前用量事件不区分缓存部分，无法单凭这些数确定具体费用。后续预算估算应使用这些实跑记录并分别标明封存与中断证据，不能继续按旧 LS20 每步外推数承诺扫完 24 题。

查看单次运行中已落盘的 token 事件：

```bash
jq -s '[.[] | select(.kind == "arc.usage.reported") | .payload] |
  {input_tokens: (map(.input_tokens) | add // 0),
   output_tokens: (map(.output_tokens) | add // 0)}' \
  .asterion-private/prime-p7-live/<run_id>/trace/prime-trace.jsonl
```

本地固定 `seed=0` 只属于 OFFLINE 游戏和本地动作前缀身份。官方 Competition 远端会话不提供玩家选 seed 的操作；P7 官方适配器的 `seed=0` 是 broker 兼容字段，不证明官方局面由该 seed 控制。官方提交只凭实际返回的初始观察及每一步观察与本地记录严格一致才继续。

## 3. 官方提交前检查

[官方评分方法](https://github.com/arcprize/docs/blob/main/methodology.mdx)按完成关数和动作效率计分；人类基准步数是评分参照，不是官方强制停手线。技术报告中的每题 20 分钟提醒、30 分钟截止用于[人类基准测试](https://arcprize.org/media/ARC_AGI_3_Technical_Report.pdf)，不属于 AI 单关评分规则。[Kaggle ARC-AGI-3 Code Requirements](https://www.kaggle.com/competitions/arc-prize-2026-arc-agi-3)另规定正式提交的整本 CPU/GPU Notebook 最多运行 9 小时并禁用互联网；本指南的本地 OFFLINE 扫题不是 Kaggle 提交。

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

2026-09-25 已执行一次 `GAME=all` 官方提交。最新本地回执是 `.asterion-private/prime-p7-official/p7-live-20260925031809-dabd0f7fd2131740a0cbfacc/official-receipt.json`；[官方卡片](https://arcprize.org/scorecards/fb3e52a2-2bfe-473e-9e5c-30bcf7f2355d)的总分为 `2.5044733044733043`。17 道题各完成首关、均未整题通关，8 道未选题为零动作占位。逐题官方动作数和分数保存在回执的 `games` 数组，并列于[证据记录](../status/ASTERION-PRIME-P7-EVIDENCE.md)。这次命令正常关闭并直接写出 `closed-confirmed` 回执，无需恢复命令。

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
