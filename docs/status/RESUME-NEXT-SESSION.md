# Live Session Checkpoint

> Updated: 2026-09-25 13:22 CST. **Session remains active — not a final handoff.**

## 本会话新增的二关轮次入口

用户要求继续广度优先研究，并确认网页可与求解并行。`98ba8b75` 新增 `make asterion-prime-p7-second-round`：固定 17 道已验证首关的题目，各自只尝试第 2 关一次，先严格重放首关；本关人类基准动作数或 30 分钟先到为停止线，无整轮 token/时长上限，不进入第 3 关。独立 `second-round-campaign.json` 让中断后的同命令续跑跳过已记载的成功、失败与有证据超时。普通旧 `sweep` 仍有 350 万 token 总上限，不能用作此轮。定向 30 项测试、lint、docs-check、打包推广检查（25 命令、0 provider）通过；刚打包 wheel 的零模型预检显示固定 17 题的首关前缀均可重放，`ready=true`。Sol 独立复审未发现运行阻断项。**二关轮次当前仍在执行**：AR25 第2关新增50步达到人类基准仍未解，其运行 `p7-live-20260925051436-ac98d5fbc33737780c790c44` 已封存、回放和清理，账本记为 `unsolved`；当前正在 CN04 第2关，运行 `p7-live-20260925052111-fa3bb4a805881d80f121d1f9` 尚未封存。网页只可对封存且回放通过的新运行生成；求解不同运行可并行，网页目录的 compile/analyze/render 写入必须串行。此轮不提交新官方卡片。

## 当前任务

按用户授权完成 ARC-AGI-3 首关本地 OFFLINE 轮次：25 题中 LS20、AR25 的第 1 关原已验证，本轮其余 23 题各尝试一次，不自动进入第 2 关。每题以人类基准动作数或 30 分钟先到为停止线，无总 token/总时长上限。23 题中 15 题 L1 过关且回放、封存、清理均核验；8 题在各自人类动作数上限未解。现有 17/25 题具有已验证首关前缀，没有任何整题通关。本轮输入 41,713,134、输出 1,547,660，共 43,260,794 已回报 token，输入含缓存读写，无法从总 token 推算账单费用。用户当天 2.42 元人民币为此前报告的账单数，不是这轮的已核验费用。本轮没有创建或提交官方 scorecard。详见指南的逐题表与私有 campaign ledger。

之后用户另行授权一次官方提交：`GAME=all` 在一张新 Competition 卡中重放 17 个已验证首关前缀，正常关闭并写出本地 `closed-confirmed` 回执；官方总分 `2.5044733044733043`，17 题各完成首关但无整题通关。用户随后要求每个已完成题目有与 LS20 类似的解题总结网页；`220ae2ea` 修复旧 reader 对新首关 summary、点击数据、计数 RESET、恢复版 AR25 的读取，并加回执摘要/清理校验。17 题均已由既有 `arc-story compile → analyze → render → export` 流水线生成通过校验的中文讲解和离线单文件 HTML；历史 LS20 23 步页面仍保留，本次官方提交对应的 LS20 20 步页面另行生成。`make asterion-prime-p7-stories` 可打开本地目录。

## 已验证事实与历史过程

- 本轮 `make asterion-prime-p7-first-round` 退出码 0，终端报告 `attempted=23`、`stopped_reason=completed`、15 个 `newly_verified_level_one`、8 个 `attempted_unsolved_level_one`，没有 timeout 或 unsealed 中断。ledger 中 23 条记录的题号唯一，逐条核验 `summary.json` 的 `replay_verified`、`sealed_trace`、`cleanup_complete` 均为 true；每条动作数不超过对应 metadata 第 1 关人类基准，未解的 8 题均正好达到基准。逐条 trace usage 求和为输入 41,713,134、输出 1,547,660，与终端累计一致。`make asterion-prime-p7-games` 显示 17 题已验证首关、8 题无已验证关卡，25 题 `full_win=False`。宿主及 Orb 来宾均无遗留 P7 求解进程或 systemd unit。
- `make asterion-prime-p7-official-preflight` 只读通过，25 题 catalog 就绪。随后 `make asterion-prime-p7-official-submit GAME=all` 退出码 0，在卡 `fb3e52a2-2bfe-473e-9e5c-30bcf7f2355d` 正常关闭；回执 `.asterion-private/prime-p7-official/p7-live-20260925031809-dabd0f7fd2131740a0cbfacc/official-receipt.json` 的 `status=closed-confirmed`、`selected_count=played_runs=17`、`skipped_count=8`、`overall_score=2.5044733044733043`、`games_completed=0`。17 条已选题结果均为 `levels_completed=1`、`state=NOT_FINISHED`。逐题分数已记录于 `ASTERION-PRIME-P7-EVIDENCE.md`。
- Run-story 修复经 22 项定向 `unittest`、`make lint` 通过；17 题当前首关 run 均成功编译，均有 `status=accepted` 的分析、一个 web render 和单文件 HTML export。`catalog.json` 共 18 条 run（含旧 LS20 历史 23 步页），当前 17 条 run 的动作数逐题与官方回执一致，点击题归一化 actions 含 `x/y`，单文件 HTML 的 SHA-256 与 export 回报一致且无外部资产路径。本地 `ArtifactApplication` 对目录、catalog 和 VC33 页面均返回 200。网页制品在忽略 Git 的 `artifacts/arc-agi-3/`，源码及指南为受版本控制文件。
- 新网页模板属于 wheel 打包资源；变更后 `make promotion-check` 完整 PASS：25 条命令、0 provider 操作、无完整数据集。`make docs-check` 检查 235 个 Markdown 和 61 个本地链接通过，`git diff --check` 通过；`make -n asterion-prime-p7-stories` 指向只读本地 catalog 服务。

- 本轮开始前，`make asterion-prime-p7-games` 列出 25 题，只有 LS20 与 AR25 各有已验证第 1 关前缀。官方既有卡 `14868b83-3f40-4afd-84b0-4d25176f97d0` 只有 LS20 第 1 关的部分成绩，其他题未选，不能视为整题通关。
- LS20 第 1 关的可计量运行记录为 20 步、输入 32,830、输出 36,418，共 69,248 旧口径 token，历时 272 秒。其余 24 题首关的人类上限合计 851 步，按每步消耗机械推算约 295 万 token、3 小时 13 分钟，旧记录漏计缓存输入。用户确认首轮总停止线为 350 万 token、4 小时；每次尝试时间按关卡步数估算，10 至 30 分钟；运行中每 250 毫秒核对已上报用量，到上限即停止本次尝试。
- 此前 LS20 第 2 关续解重放 20 个已验证第 1 关动作后，新记约 242 个第 2 关动作，超过 123 的人类基准才被人工停止；该运行未封存且没有用量事件，不复用作前缀，不推算其 token。
- `1a178f4a` 将 Prime runtime 用量事件流式落到 trace，`f38143c4` 将 Pi 缓存读写计入输入 token；`987ca598` 加精确本地扫题动作上限，`a8ef4d53` 加轮转调度器，`3f1499ba` 将扫题接入 P7 operator/Make，`4d820313` 验证中断 trace 哈希链并在用量缺失时停机。
- 刚构建 wheel 的隔离环境中，调度器 `--max-attempts 0` 预检成功：attempted=0、token=0。`make promotion-check` 完整通过：25 条命令、0 次 provider 操作、无完整数据集。`make lint`、`make docs-check` 和定向测试通过；独立复审批准付费首轮。
- 首次付费 sweep 只尝试 AR25 第 1 关。运行 `p7-live-20260924230447-46fc1ea55b4041a6f56f8786` 的 broker 到 22 步过关并经离线 broker replay，但 usage/action 并发写 trace 导致序号 9 重复、哈希链断裂；summary 的 `sealed_trace=false`，不能成为已验证可复用前缀。调度器正确拒绝继续其他题并返回 `usage-missing-after-model-activity`，但其 `0 token` 汇总是假象：原始 27 条 usage 事件逐条合计输入 1,157,891、输出 39,235，共 1,197,126 token，因链损坏仅作保守预算扣减。没有遗留求解进程。
- `4a030f99` 已串行化 trace 的写入、封存与快照，八线程并发回归前红后绿。`3fa408c1` 从原 trace 的 22 个连续动作、live/replay/prefix-replay 三份录制和新 OFFLINE 引擎中核对 AR25 L1，在全新目录 `p7-live-20260924232709-af0888dd036743f4566e6b7c` 封存带来源哈希的 22 步过关记录。原损坏 trace 字节保持不变；首次诊断恢复目录已无损移到 `.asterion-private/prime-p7-recovery-diagnostics/`。已安装 wheel 的 `load_best_prefix` 现选中最终恢复记录；`make asterion-prime-p7-games` 显示 AR25 已验证 1 关、分数 2.777778。
- `d3f670f9` 每 250 毫秒读取当前子进程 hash-valid 用量，达到已回报 token 上限即终止进程组，并按总剩余时间截断单题。它不能限制模型当前尚未回报的用量；定向模拟子进程测试通过。完整 `make promotion-check` 在 trace 并发修复后再次通过（25 命令、0 provider 操作），恢复与调度器后续变更有聚焦测试。
- 独立零模型 Orb 进程树探针曾发现 `killpg(SIGTERM)` 只结束本机 Orb 和客体父 Python，客体子 Python 仍存活；探针残留已清理。`f8486f80` 改为每次尝试独立的来宾 systemd cgroup，在宿主预算停止后精确停止并核验该 cgroup。真实 Orb 零模型回归在 10 token 模拟上限达到 11 时，父进程与脱离会话的子进程均退出，无关进程保持运行；22 项定向测试、lint、docs-check、完整 promotion-check（25 命令、0 provider 操作）通过。刚构建 wheel 的零动作调度器预检返回 `attempted=0`、token=0；独立最终复审未发现付费续跑阻断项。
- 续跑 `p7-live-20260924234525-17d9c6c33b0fa14a39b1256f` 仅尝试 BP35 L1，在 18 个动作时触发本次 220 万已回报 token 上限；40 条 usage 共输入 2,213,365、输出 86,316，合计 2,299,681。58 条 trace 记录哈希链有效；但运行被预算中断，无 summary 或封存回执，BP35 不算过关。BP35 L1 人类基准是 21 步。调度器报告 `token-cap` 并退出，Orb 没有遗留 P7 求解进程或 systemd unit。
- AR25 原始暂计 1,197,126 加 BP35 已核验 2,299,681，总计 3,496,807/3,500,000 已回报 token；离上限仅 3,193 token，不再启动任何付费尝试。此轮没有触及 4 小时上限。`make asterion-prime-p7-games` 仍仅有 LS20 L1 与 AR25 L1 已验证，其他 23 题尚无已验证前缀；官方既有 scorecard 未新增提交。
- BP35 的前 10 次模型调用输入合计 170,107 token，后 10 次 1,004,287，显示随会话推进每次输入显著增加；trace 只存总输入/输出，不能区分缓存价格或直接断定增长根因。
- `291d909d` 新增专用首关扫题入口并移除扫题器/来宾 cgroup 的时间及 token 限制，`1cfdf28b` 改用新 OFFLINE 回放确认 AR25 已解首关。精确安装 wheel 加两只 ARC wheel 预检为 24 题中 AR25 已验证、23 题待尝试（含 BP35）；普通 repo 虚拟环境缺 ARC wheel，会错误地把 `load_best_prefix` 显示为 None，不能据此重复付费。
- `e77ddb75` 与 `0b1cf1d7` 使题库及 guest 秒数缺失在付费前拒绝，且只在受控首轮模式透传运行标记。`be5c1e66` 使首轮 OFFLINE 原生运行可选无内部 deadline/回调预算，保留动作数，并已通过 160 项定向测试；普通和官方路径仍用有限预算。`5f5993e3` 固定本轮 25 题清单，`cc4ae812` 加入单题 30 分钟与私有 campaign 续跑，`234058bb` 要求每条续跑记录重新核对真实运行证据。Sol 独立复审最终 APPROVE；108 项 P7/Prime 定向测试、真实 Orb 零模型清理探针、lint、docs-check 通过。精确 wheel 零模型预检当时显示 24 个非 LS20 题中 AR25 已验证、23 题待尝试，首题 BP35。完整 `make promotion-check` PASS：25 条命令、0 provider 操作、无完整数据集。此为付费运行前的检查点。
- 官方 Competition 远端不接收 seed；本地 `seed=0` 是 OFFLINE 前缀身份。LS20 本地第 1 关初始观察在 seed 0 两次及 seed 1 一次零动作检查中相同，不能推断后续关卡或其他游戏。官方不能跳关；本轮按连续关进度轮转。

## 当前判断与未完成边界

- 上一轮 350 万 token 上限只新增 AR25 L1 一个已验证首关，BP35 L1 未过；这是历史预算结果。新一轮已全部完成，以 15 个新验证首关和 8 个达到人类动作上限的未解首关结束。8 个未解题有封存运行证据，但没有可复用的过关前缀。
- 每次本地尝试保留独立运行目录；本次官方提交已另开 Competition 会话逐动作对照，成绩以本地回执和官方卡片为准。后续提交仍需新的显式授权。
- 用户先前确认的 350 万 token 总预算、其 3,496,807 已回报 token 使用与绝对截止均属旧轮次历史，不适用于本轮。AR25 源 trace 因链断不作封存用量证据，后由独立新运行恢复验证。新轮次的 43,260,794 token 仅是已回报总量，不区分缓存命中/未命中价格；用户截图中的当日账户总量也不能单独归因本轮。指南为 `docs/guides/prime-p7-games-and-official-results.md`。
- 网页生成期间一次进程诊断工具输出意外包含 `DEEPSEEK_API_KEY` 的值；本文件和受版本控制文件均不包含该值，但会话工具日志可能保留它。应提醒操作者轮换该 key；后续只查 PID/进程名，不打印包含环境变量的完整进程命令行。

## 下一动作

1. 启动 `make asterion-prime-p7-second-round` 并监看本地 campaign 与已封存运行；新过关运行可并行生成单文件中文网页。若轮次中断，先核对证据和来宾进程，再重跑同命令。完成后更新逐题结果、指南与状态。新官方提交需再次获得明确授权。
