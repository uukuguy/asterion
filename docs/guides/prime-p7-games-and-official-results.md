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

### P7 自主求解控制台

一条命令打开本地工作区：

```bash
make p7-console
```

进入控制台后，页面自动打开上次选择的题目和关卡。首次进入时打开默认题目的第 1 关。人工试玩可点击关卡列表直接选关，不需要先通过前面的关卡。已玩关卡会自动保存。切换回来、刷新页面或重启服务后，会恢复该关最后保存的位置和动作历史。没有存档的关卡显示真实初始画面。恢复时程序通过 SDK 重放已记录动作，并核对每步结果；恢复完成后才开放操作。点击动作按钮可手动玩；当前动作只用按钮高亮显示。人工局不调用模型，也不写入 P7 的认知或运行记录。点击“启动 P7”会先结束人工局，再从第 1 关开始执行固定有限的求解预设。真实游戏帧、动作反馈和已记录的认识持续刷新。点击“结束运行”会终止本次任务并检查 guest 后代是否清理；清理未确认时不允许重开。浏览器断线不会自动结束有限自主任务，服务退出会执行清理。

P7 自行观察、规划和执行。简短目标、依据、预期由 P7 的真实 `p7_decision` 调用提供，缺失时不补造。动作面板在 P7 运行模式只用于观察。独立人工试玩可直接点击 ACTION 按钮；ACTION6 先点按钮，再点击游戏画面中的目标格。画面获得焦点后可用数字 1–7，按住不连发。RESET 重试当前局。人工局连续闲置 5 分钟、累计 30 分钟或达到 1000 个动作时自动结束。人工动作旁显示发送、已执行或结果未确认的状态。画面没变也可能是已执行的动作。存档保留实际动作记录；页面显示最近 1001 个已记录结算帧；用帧时间轴、播放或历史动作队列回看。查看历史时不能执行新动作，点击“返回当前画面”后继续试玩。RESET 也会更新该关存档，并保留在历史中。若要删除当前关卡的动作历史并从真实初始画面重新开始，点击“清空并重新开始”。该操作只替换当前关卡存档，动作计数、时间轴和队列归零；其他关卡存档保留。存档只属于人工试玩，不进入 P7 经验。关卡列表用“已保存”标记存档。若自动过关进入已有存档的下一关，程序先保留原存档；在新关执行动作后再更新。返回上一关会恢复过关前最后可玩的画面。保存失败时会明确提示，并保留当前操作状态供重试。可恢复 P7 暂停仍未实现。

### 单 HTML 过程回放

只导出最近记录，不启动服务或调用模型：

```bash
make asterion-prime-p7-console
```

生成运行目录中的 `p7-console.html`。文件内含画面、Tailwind CSS、JavaScript 和证据数据，无需联网或构建。可选 `RUN=<历史运行目录>`；`make p7-console RUN=...` 仍可直接生成并打开历史文件。`OUTPUT=/tmp/p7-console.html` 可改输出位置。
实时工作区也可选择历史回放。滑块和播放按钮只控制回放动画，不暂停后台 P7。过程区查看已记录的 P7 摘要、动作结果和认识更新。
画面旁的动作面板按当前帧列出可用动作，高亮当前动作；回放中按键可定位已录动作。含义只采用明确记录，冲突保持未知。旧记录的最终认识标注范围，不能当作历史时点已经获得的认识。
P7 观察模式中，已有已验证过关路线时默认显示保存路线；尚未过关、没有保存路线时默认显示当前求解记录或最新尝试，包含已录帧、动作与认知。列表中的“尝试”可明确查看最新尝试，“跟随最新画面”恢复实时跟随。尚未通关的状态不表示记录为空；尝试记录不计入已保存过关分数。

默认只显示原始画面。变化格和点击位置标记需手动开启，均属于回放辅助。颜色文字使用名称和编号，例如“蓝色（9）”。
动作的“画面对比（自动测量）”仅报告结算帧的像素位移或数量变化，不解释部件用途，也不代表 P7 的认知结论。缺少可关联的 P7 分析时会明确提示。

每份文件展示一次运行中一个游戏的各关卡。离线文件如需新动作须重新导出，实时工作区无需重新导出。旧记录没有保存的规划文字显示为未记录。
最终认知不代表较早帧当时的知识；缺少轮次关联的模型信号也不会强行绑定到动作。导出不调用模型、不执行游戏动作。

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

### 路线策略

默认使用 `replay`：已有验证路线只作为逐步核验的上界。研究更短路线时显式启用通用 `explore`：

```bash
ASTERION_PRIME_P7_STRATEGY=explore make asterion-prime-p7-solve GAME=ls20 LEVEL=2
```

探索候选必须经过离线 fresh replay、身份和终态校验后才能复用；策略变量不会传给模型后端。

每次调用都会创建独立的 UTC 时间戳 `run_id` 目录，不会覆盖之前的尝试。一个经过验证的运行包含封存 trace、动作前后状态摘要、动作哈希链和 summary；清单只读这些记录，不运行题目源码。续解恢复新本地游戏仍严格重放；官方提交读取保存时产生的 SDK 认证证书，只静态核对选中路线和当前游戏/验证器身份，不在提交时重放全部历史候选。

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

受控的单题 A/B 命令会从相同的已验证首关起点连续运行两个独立的本地二关尝试，先 `legacy`、后 `verified`；每臂沿用二关人类动作上限、30 分钟与 5 分钟停滞线，不写第二轮进度账本，也不创建官方卡片：

```bash
make asterion-prime-p7-targeted-ab GAME=m0r0
```

命令必须显式指定 `GAME`。私有对照记录写入 `.asterion-private/prime-p7-targeted-ab/`，两次单题运行仍各有独立的 `.asterion-private/prime-p7-live/<run_id>/`。若第一臂的封存、回放、动作前缀或来宾清理证据不完整，命令会停止且不启动第二臂；第二臂证据不完整时记录为中止，不能把它当成完成的对照。尤其部分失败运行只重放校验了首关，没有完成二关动作的独立回放，当前入口会拒绝将它算作有效 A/B。完成一对样本也只能观察本题这次差异，不能证明总体通过率提升。

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

### 未解首关和二关的广度重扫

需要优先覆盖容易的首关和二关时，使用新的独立轮次：

```bash
make p7-breadth-preflight
make p7-breadth
make asterion-prime-p7-games
```

`p7-breadth-preflight` 只构建并加载本地 wheel，列出当前未解的首关队列和二关候选，不启动 Orb、不调用模型，也不写账本。确认题号后，`p7-breadth` 先按题号顺序各尝试一次未解首关；首关结束后重新计算二关队列，再各尝试一次已有首关前缀的未解二关。已验证的关卡会跳过，同一新轮次中的 `(题号,关卡)` 不会重复付费尝试。

每题沿用人类基准动作数、30 分钟单题上限和连续 5 分钟无新动作停止线。没有整轮 token 或时间上限。每次尝试有独立 UTC `run_id`，结果追加到 `.asterion-private/prime-p7-live/breadth-resweep-campaign.json`；中断后再次运行 `make p7-breadth` 会跳过账本中已核验的终态尝试。若中断时仍有 `running` 记录，命令会停下要求人工核对，不会自动重付费。账本只接受封存、回放、来宾清理、题号/关卡身份和用量都能绑定到同一运行的证据；停滞、达到上限和执行错误都不是过关。

若账本因操作员中断而保留 `running`，先确认来宾 P7 单元已结束，再运行零模型审计命令 `make p7-breadth-reconcile`。它核对未封存轨迹、录制身份和用量后，将原条目标为 `interrupted` 并保留原运行；重启 `make p7-breadth` 会对该题重新做一次正式尝试。无法确认来宾清理或证据不一致时，不应手改账本绕过审计。

这一轮仍是本地 OFFLINE 实验，不创建或提交官方 scorecard。成功关卡通过回放后，可以用 `make asterion-prime-p7-stories` 查看或生成对应的本地解题总结网页；提交官方成绩前仍需单独运行第 3 节的 preflight 和第 4 节的官方提交命令。

要在某关已有封存且回放验证的失败记录后，明确付费重试**同一题的下一未解关**，可先零模型检查，再单次运行：

```bash
make p7-retry-preflight GAME=bp35
make p7-retry GAME=bp35
```

重跑只读取同题、同 seed、同关最多两次已校验的旧记录；每次建立新的运行目录和时间戳重跑记录，不覆盖旧运行，也不触碰广度账本。证据可来自首关封存失败、二关封存但只重放了已解首关前缀的部分失败，或经过独立首关前缀核对的执行停滞。后二者不会被说成“失败二关动作已独立回放”。没有符合条件的旧记录时，预检会拒绝。BP35 首关已在 20/21 步通过，上述 BP35 示例现在会选择第 2 关；广度重扫留下的二关失败记录可供预检核对。真实重试前还会检查 OrbStack 来宾能否执行零模型命令，避免来宾失联时空等付费解题。

某题已有通过封存和回放校验的关卡前缀时，只尝试它的**下一关**：

```bash
make asterion-prime-p7-next GAME=vc33
```

`GAME` 可填题号短名或精确 game ID。命令自动选择该题最高的已验证关卡，重放动作前缀，只尝试紧接的一关一次；例如 VC33 已解到第 2 关时，命令尝试第 3 关。新增动作以对应人类基准为上限，单题最多 30 分钟，连续 5 分钟无新动作即停。每次尝试写入独立运行目录和 `.asterion-private/prime-p7-next-level/` 时间戳记录，不覆盖既有解法；只有新运行封存、回放和清理均验证通过，才显示 `status=verified`。失败后再次执行会重新付费尝试同一未解关卡，因此须明确决定是否重试；已解关卡不会再次求解。此命令只运行本地 OFFLINE 游戏，不提交官方成绩。

2026-09-25 首关首轮已完成：除原已验证的 LS20、AR25 外，23 题各尝试一次，其中 15 题通过第 1 关并完成封存、回放和清理核验，8 题到人类基准动作数仍未解。**该轮结束时**25 题中有 17 题具首关前缀；后续 BP35 重跑通过后，本地变为 18 题。整题通关数仍为 0。下表保留首轮原始成绩，不用新重跑覆盖历史；输入包括缓存 token，不能按总量直接计算费用。

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

已验证关卡均有带动作和画面回放的本地网页制品，文字采用通过引用校验的讲解或中文事实摘要。广度重扫结束时 25 题中有 21 题具已验证首关前缀；后续 G50T 重试通过后本地增至 22 题；FT09 二关同题重试通过后本地首关前缀仍为 22 题，但 FT09 升至 2/6 关。打开本地目录：

```bash
make asterion-prime-p7-stories
```

广度重扫新增的 TU93 首关网页已导出到 `artifacts/arc-agi-3/exports/arc-agi-3-tu93-0768757b-p7-live-20260925164956-a2ddcdca8d104314b5dbed63-web-14c538e19938c6bed3dc.html`；对应运行 19/19 步通过，封存、回放和清理均已校验。

广度重扫新增的 TU93 二关网页已导出到 `artifacts/arc-agi-3/exports/arc-agi-3-tu93-0768757b-p7-live-20260925193805-a8874a79515315781b66f456-web-b922d3b97764b323d656.html`；对应运行共 35 步完成前两关，封存、回放和清理均已校验。该页使用不调用模型的确定性事实摘要。

后续独立重试完成的 G50T 首关网页为 `artifacts/arc-agi-3/exports/arc-agi-3-g50t-5849a774-p7-live-20260925223031-f6d803c700b5000bf6a527f7-web-6ad3325e78cf648c5c82.html`；58/78 步通过，封存、回放、清理均已校验。模型讲解未通过格式校验，页面使用中文事实摘要；这次 OFFLINE 结果没有进入此前关闭的官方卡片。

后续同题重试通过的 FT09 二关网页为 `artifacts/arc-agi-3/exports/arc-agi-3-ft09-0d8bbf25-p7-live-20260925224920-33b4e846d793e3327a2ecd51-web-d3b09034f81b21375173.html`；共 19 步完成前两关，封存、回放、清理均已校验。该网页使用确定性事实摘要（`analysis.status=accepted` 但讲解未经过模型生成）。这次 OFFLINE 结果没有进入此前关闭的官方卡片。

后续同题重试通过的 SC25 二关网页为 `artifacts/arc-agi-3/exports/arc-agi-3-sc25-635fd71a-p7-live-20260925234916-0788304c8a848397a46dacb5-web-7fb30ed74df18ef89b7d.html`；共 28 步完成前两关（22 首关前缀 + 6 二关动作，恰好用完 6 动作上限），封存、回放、清理均已校验。该网页使用确定性事实摘要。这次 OFFLINE 结果没有进入此前关闭的官方卡片。

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

提交完整公开目录（当前25题；已有认证路线的题目执行动作，其他题目建立零进度实例）：

```bash
make asterion-prime-p7-official-submit GAME=all
```

这个入口不启动 Pi，也不调用模型。它先读取保存时的认证证书并静态核对所选路线，再创建一张新的官方 Competition scorecard；对每个选定题目只调用一次官方 `make`，从官方返回的初始状态开始逐动作执行，并检查每次动作后的状态。远端初始状态或中间状态和本地证据不一致时立即停止，不重试不确定动作，也不伪造成功回执。

不上传本地成绩或动作文件；程序通过API逐动作执行。官方端实际发生的是一组新的动作执行，因此官方 receipt 的动作数、关卡状态和分数以 ARC 服务返回值为准。Competition 关闭 scorecard 时，官方 SDK 会为未选题目建立零动作、零分的 `NOT_FINISHED` 占位 run；这些占位不表示 Asterion 执行过该题。回执分别报告实际执行的 `played_runs` 和未选题目的 `skipped_count`。

旧的全目录模型评估入口改名为：

```bash
make asterion-prime-p7-official-live-eval
```

它是独立的有限预算模型评估，不是已保存动作提交；除非已经明确安排费用和运行范围，不要使用它代替 `official-submit`。

## 5. 回执和 scorecard 对照

2026-10-06 最新正常关闭的完整25题提交：[官方卡片](https://arcprize.org/scorecards/15ffcc07-6484-437b-9c66-54d4dccfcf0c)，得分 **59.7982683982684**，25题已执行、0跳过、14题全通、109/183关、4097动作。回执状态为 `closed-confirmed`，保存在 `.asterion-private/prime-p7-official/p7-live-20261006050112-67fb895d89586479d9da2cdf/official-receipt.json`。相比上一张正常卡29.834632，增加7题全通和55关。本批冻结开卡时路线；后续本地新增过关另行保存，不改写本卡成绩。提交过程不调用模型，也不重新离线重放历史候选；在线动作仍按官方要求逐次执行。

以下为2026-09-25历史结果；最新会话成绩以[活动检查点](../status/RESUME-NEXT-SESSION.md)为准。当天已执行两次 `GAME=all` 官方提交。该日最新批量回执是 `.asterion-private/prime-p7-official/p7-live-20260925194924-200e3e5e7a7b26c04ea21d67/official-receipt.json`；[官方卡片](https://arcprize.org/scorecards/403c8b05-ae64-4dd9-b6f6-1d22910a2e24)的总分为 `6.498124098124098`。21 道题重新执行了本地已验证动作前缀，4 道题（G50T、KA59、SK48、TN36）未选并由官方服务记录零动作占位。所选题中 M0R0、VC33 完成到第 3 关，AR25、CN04、DC22、LS20、RE86、TU93 完成到第 2 关，其余完成首关；没有整题通关。逐题官方动作数、关卡数、状态和分数保存在该回执的 `games` 数组，并列于[证据记录](../status/ASTERION-PRIME-P7-EVIDENCE.md)。这次命令正常关闭并直接写出 `closed-confirmed` 回执，无需恢复命令。

上一张 17 题批量卡片仍保留为历史记录：回执 `.asterion-private/prime-p7-official/p7-live-20260925031809-dabd0f7fd2131740a0cbfacc/official-receipt.json`，总分 `2.5044733044733043`，卡片为 [fb3e52a2-2bfe-473e-9e5c-30bcf7f2355d](https://arcprize.org/scorecards/fb3e52a2-2bfe-473e-9e5c-30bcf7f2355d)。

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


## 6. 官方提交与社区展示的策略

保存成功与官方结果是两个状态：本地路线在封存、独立重放和收口完成后发布认证；认证缺失或失效时明确待准备，并在开卡前拒绝提交。提交过程另写 `submission-progress.json`，立即记录实际卡号、已完成路线及中断动作序号；该进度文件不能代替关闭后的服务端回执。

研究阶段按关保存、校验和准备网页数据。完整官方提交在阶段性进展后执行：同一张新卡覆盖全部25题，从初始局面在线执行已保存动作；关闭卡后保留服务端最终回执。保存时的认证消除重复离线验证，不能消除官方在线动作，也不能把多张旧卡合成一张新卡。单题通道检查与完整25题总分使用不同覆盖范围，不能混报。[Competition Mode](https://docs.arcprize.org/toolkit/competition_mode)规定每卡每环境只能创建一次实例，分数按全部可用游戏计算，运行中不可读取得分。

`Open Scorecard` 的0/0不是一次已完成评测。先比对卡号：浏览器手动卡与后台API卡可不同，`human`只是标签。完成后由程序调用关闭成绩卡，取得最终结果；不要为了检查进度而关闭正在执行的卡。官方自动关闭的15分钟指无活动时间。[Scorecards](https://docs.arcprize.org/scorecards)、[Close Scorecard](https://docs.arcprize.org/toolkit/close-scorecard)

社区展示另走GitHub流程：公开可复现的通用求解系统，在官方社区仓库建立 `submissions/<id>/submission.yaml`，填写方法、作者、模型版本、公开 `code_url` 与 Competition Mode 的 `scorecard_url`，向 `main` 提交PR。ARC-AGI-3条目不能手填数值成绩；审核合并后展示方法。当前README说明只有ARC Prize Verified成绩显示数字，社区接收条目不等于官方验证。[提交说明](https://github.com/arcprize/ARC-AGI-Community-Leaderboard/blob/main/CONTRIBUTING.md)、[社区资格](https://github.com/arcprize/ARC-AGI-Community-Leaderboard/blob/main/README.md)

发布应包含P7的WorldMap推理、Prime工作区与经验复用代码，说明预先探索和保存路线复放的评估口径。仅发布逐题答案表不符合社区的通用系统要求；已有路线复放证明执行与提交通道，不单独证明首次陌生游戏的泛化能力。当前尚未发布社区PR。


## Vercel 只读控制台

远端地址：[https://asterion-p7-console.vercel.app](https://asterion-p7-console.vercel.app)。展示本地保存成绩、稳定认知与回放；默认打开已验证存档，没有存档时展示预构建初始画面。动作及求解控制仍在本地执行。

本地发布器 `tools/p7_console_cloud_sync.py` 从57515端口读取公开投影，主动上传至私有Blob；远端不连接本地网络。普通过程数据每30分钟合并上传，新过关记录优先（至少间隔60秒），远端页面每5分钟检查更新。打开游戏或关卡立即读取。标题显示数据更新时间，不代表无变化时也刷新心跳。

首次上传包含25题、183预览、24份保存记录及580页画面，压缩数据约4.9MB，含索引约5.5MB；不是全部历史私有记录。Hobby计划免费Blob存储1GB、下载10GB/月，写入类操作2000次/月；参考[官方额度](https://vercel.com/docs/vercel-blob/usage-and-pricing)。上传器记录操作次数，默认1500次保护线；存储750MiB警告、900MiB拒绝。达到保护线暂停上传并记录错误，本地解题和已有成绩保留。

运维入口：`node deploy/p7-console-vercel/upload.mjs --spool <private-spool> --token-file <private-token-file>`；持续发布：`python tools/p7_console_cloud_sync.py --spool <private-spool> --watch --uploader-script deploy/p7-console-vercel/upload.mjs`，由操作者环境提供 `BLOB_READ_WRITE_TOKEN`。密钥只存私有文件或服务环境，不能放进仓库、页面或参数值。Vercel界面源码改动需先 `npm --prefix deploy/p7-console-vercel run refresh-assets` 和 `npm --prefix deploy/p7-console-vercel test`，再部署该独立目录；数据更新不需要重新部署。
