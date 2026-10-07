# arc-skill 自主试跑与 BP35 机制对照

> 2026-10-07。用户要求真实检验原版 skill 配合 `gpt-6.1-sol` 的自主解题，并对照 P7 后期关卡的困难。本报告区分启动故障、实际求解、公开轨迹观察与归因判断。

## 1. 范围与试跑条件

- 用户写的 `r111` 对应 `r11l-495a7899`；`bp25` 对应 `bp35-0a0ad940`。
- 第三方源码固定在 [dba53c3799eab600a512dd73ed037d7ab6958c66](https://github.com/pbshgthm/arc-skill/tree/dba53c3799eab600a512dd73ed037d7ab6958c66)。完整阅读原版 skill，源码与复制的 skill 做哈希检查，不修改求解逻辑。
- `arc start` 启动游戏会话，不调用 LLM。测试的是 coding agent 读取原版 skill 后持续执行工具的完整路径。
- 原生 Codex 请求 `gpt-6.1-sol`、high effort，单个空白 local run；预设 900 秒 actor 期限、180 秒清理期限。宿主睡眠造成截止信号迟送，严格绝对墙钟边界未验证，见下节。操作者仅准备依赖、启动原版 broker、注入已有配置和监控，不提供关卡提示、旧路线或中途继续消息。
- actor 工作区在仓库外，避开父级 Asterion instructions；禁止读取 P7 历史与游戏源码。关闭 web search。只运行本地游戏，不创建官方 Competition 卡。
- 原版源码、启动配置、完整私有模型/工具日志、ARC 事件与进程清理证据保存于私有实验目录。公开报告只给必要摘要。

## 2. r11l 实测状态

**完成 4/6 关、49 次真实动作；没有完成全游戏。操作者期限守卫中断了待完成的模型回合，不是模型主动宣布失败。** 原版 skill 配合该模型能自主推进，但本次没有验证它可以自动过完 r11l。

- 首次操作者包装在 2.083 秒内使 Codex Node launcher SIGABRT；没有模型事件和游戏动作。相关进程全部清理。
- provider-free `codex --version` 对照定位为：外层读写拒绝下继承了指向受拒绝目录的日志句柄。将实时日志置于外部 operator 目录后，版本检查通过。此修正没有修改原版 skill/harness。
- 有效模型会话于 18:03:16 启动，预设截止 18:18:16。实际 turn context 确认 `gpt-6.1-sol`、high effort、外部空白工作区；没有中途继续或策略提示。
- ARC 最终状态 `NOT_FINISHED`，共 50 个连续事件（含初始观察）、49 次真实动作、4/6 关。全部动作发生在原截止时间之前；最后动作时间为 18:17:51。
- 宿主 18:17:53 睡眠、18:27:19 唤醒，守卫唤醒后发送 SIGTERM。单调时钟耗时 879.746 秒，UTC 起止差 1444.705 秒；不能声称严格 900 秒墙钟限额已生效。原始 supervisor 的退出码 0 / `timed_out=false` 不能解释为模型自然结束；没有 `turn.completed` 或最终模型报告。
- 原版 15 个源码文件哈希前后相同，上游 checkout 干净。有限命令/工具输入审计未发现读取游戏源码、P7 历史或联网提交的迹象；这不构成绝对隔离证明。
- 清理耗时 2.259 秒，全部本次拥有进程退出、临时认证副本删除，既有 P7 控制台保留。语义校正后的结果、原始日志与宿主睡眠证据保存在私有 `evidence/valid-run/`。

### 中断后如何续跑

原版在同一运行目录重新执行 `arc start r11l-495a7899`：现存 broker 可用则连接，已退出则从已记录动作重建本地 simulator，逐动作核对重建观察，再核对最新事件。若动作已发生但主事件账本尚未写入，先用 broker mutation journal 补齐。出现重放差异则拒绝继续，而不是把新状态假装成旧进度。代码见 [start](https://github.com/pbshgthm/arc-skill/blob/dba53c3799eab600a512dd73ed037d7ab6958c66/skills/arc-skill/scripts/arc_skill/cli.py#L224) 与 [local replay](https://github.com/pbshgthm/arc-skill/blob/dba53c3799eab600a512dd73ed037d7ab6958c66/skills/arc-skill/scripts/arc_skill/broker.py#L428)。重建不是新的探索尝试，历史与计数保留；已完成关卡和当前关内进度都可恢复。

研究状态分开处理：同一 coding agent 会话可以接续；新会话读完整 skill 并运行 `arc status`，通过 `.arc/NOTES.md`、事件历史及自己保存的 Python/模型文件重建思路。笔记由模型负责及时更新，未落盘的思考或只在进程内的计算不能靠游戏日志自动恢复。原版没有负责重新启动模型并分配下一轮时间的 supervisor。本次游戏目录与模型会话记录已保留，但没有实际启动续跑，因此此处是源码确认的能力边界。

本次是 local 模式。远端 Competition 模式有约 15 分钟动作闲置租约，失去远端 owner 或租约过期时不能通过本地 replay 延续该远端游戏。

本次隔离配置不允许 actor 读取 simulator 源码缓存；实际续跑仍应由可信 operator 先恢复 broker，再向模型提供同一运行目录和现有状态。已清理的 broker token 可重新生成，模型认证由 operator 重新注入，不依赖保留临时凭据。此准备不提供关卡解法。

## 3. BP35：公开记录支持什么

证据来自作者的 [完整会话](https://arc-skill.vercel.app/data/transcripts/bp35.json)、[逐动作记录](https://arc-skill.vercel.app/data/runs/bp35.json) 与 [游戏统计](https://arc-skill.vercel.app/data/games.json)。源码仍以固定提交为准。

BP35 共 482 动作、478 次预测评分、22 次预测失误、4 次 RESET、266 次 Python 调用、72 个执行批次。记录有三条用户消息：初始任务后，两条续跑指令；一次因为会话额度停止，一次因为模型在 L8 主动停止并认为无解。没有记录到关卡解法提示或人工代码接管，但无法排除记录之外的协助。因此可以说同一连续事件账本完成九关，不能说一次命令后无需任何人工交互。

| 关卡 | 真实动作 | 预测失误 | RESET 事件 |
|---|---:|---:|---|
| L5 | 31 | 1 | 无 |
| L6 | 73 | 2 | e186 |
| L7 | 54 | 1 | e250 |
| L8 | 106 | 9 | e339 |
| L9 | 82 | 0 | 无 |

作者全程探索动作与 P7 最终保存路线的动作数属于不同范围，不能据此比较整体效率。

## 4. P7 BP35 后期：外围实际承担了哪些工作

用户明确纠正：L5 之后是外围 Codex 分析进展并持续修正 P7 才艰难完成。提交与运行证据支持将整体归类为**有外部研究协助的研发过程**；局部 actor 自主纠错不能替代整体自主完成的证据。

| 外围介入 | 可检索证据 | 自主性边界 |
|---|---|---|
| 修复拒绝真实探针、bridge 转发和 RESET episode 问题 | `eda6a5d6`、`3108995d`、`2f258ff3`；旧 L6 某次动作 163 被跨关坐标拒绝且零派发 | 部分属于工具缺陷；actor 无权修改正在运行的可信 broker |
| 判断旧正向认知妨碍探索，选择隔离并重启研究 | `d406e298` fresh-target policy 隔离 79 个旧来源的正向认知/研究/产物/cell，保留真实历史与前五关认证 | 外围承担了研究判断；不能仅称为工程修复 |
| 发现上下文膨胀并部署 compact delivery | `b5c24693`；此前八次修订约 90,506 新增 token、九次计划约 84,101 | 修复后的通关不是同一固定版本单次运行 |
| 检查进展、安排有限重试、确认经验消费 | L8 两轮、L9 两轮；`23a1b19c`、`35e9f605` | operator 调度扩展了尝试机会；不能归入 actor 自身完成 |

同时要保留 actor 确实完成的推理：`d406e298` 第二轮自行发现屏外对象、更新地图、搜索约 35,038 状态并得到 28 步候选，截止前未执行；后续 `b5c24693` actor 读取这轮经验，自行重建 43 步路线、修正真实预测，在序号 193 完成 L6。现有证据没有显示外围直接写出最终地图或路线提示。这证明有局部自主研究能力，但整体仍依赖上述外围判断、工具改动和重试。

L9 的坐标门控诊断是只读分析，没有当轮补丁或解法注入；最后通关仍使用 `2f258ff3` 并绕过限制。也不能把这个特定问题描述为“外围改好后才过 L9”。

## 5. 五项具体差异

### 5.1 有效点击与不变预测像素

原版 [cell 评分](https://github.com/pbshgthm/arc-skill/blob/dba53c3799eab600a512dd73ed037d7ab6958c66/skills/arc-skill/scripts/arc_skill/predictions.py#L176) 检查动作后的值，不要求该像素相对动作前发生变化；[批次执行](https://github.com/pbshgthm/arc-skill/blob/dba53c3799eab600a512dd73ed037d7ab6958c66/skills/arc-skill/scripts/arc_skill/live.py#L194) 在实际执行后评分，遇 miss 停止。公开 BP35 L8 e368–378 连续十一次同坐标点击，在相机移动下保持某些 screen-space 像素断言，全部通过。

P7 `2f258ff3` 的 L9 记录在观察 305 两次 `prefix-action-reuse` 零派发。预期的角色与球体像素已与当前值相同；同一球内部另一个点随后实际改变 973 像素，原来的两个预测像素保持不变。之后原坐标动作又改变 1113 像素。这是门控阻塞合法实验的直接证据，而非游戏反例。

当前 [Solver](../../src/asterion/applications/prime/p7/solver.py) 仍按计划初始画面为每步挑一个 native cell；[Broker](../../src/asterion/applications/prime/p7/broker.py) 仍将跨关历史坐标复用与 changed-cell/frame 预测绑定。全体 cells 的事后核对与这一派发前要求是不同问题。诊断还展示了后来动作的区分性 cell 被初始帧选择丢弃；不能把该翻译缺口误称为第一处拒绝的唯一原因。

普通 `no-effect` 门控也曾有修复，但最直接的 BP35 证据是跨关坐标门控。不能把 SK48 的具体失败替代为 BP35 归因。

### 5.2 搜索失败后，继续验证地图覆盖

作者 L6 先在已有地图上多次得出不可达，后来发现相机未覆盖的上方一行，e218 观察到第三个开关。L8 再次把已观察的 300 格当作完整地图并停止；续跑后利用 L6 的经验，e368–382 通过爬升扩大观察，e383 确认屏外开关，e400 过关。

P7 L6 有真实 IPython 搜索，不能说缺少计算工具。但某次后续尝试仍沿用部分模型，把模型内不可达用来撤回真实探针，仅执行十二个新动作后结束。具体差别在搜索结果如何触发补充观察、修正覆盖边界，而不是是否存在 WorldMap。

### 5.3 程序真的生成预测，还是仅陈述历史结果

作者在 L8 续跑后才首次写 `rules.py`；之前已自行写临时模拟、BFS 和路线验证。L8 回放修复屏外球体、门占据状态、noop/undo 等遗漏，从 72/72 扩展到 88/88。L9 重建该关模型，校验范围依次扩大为 19/19、47/47、58/58、80/80，整关 82 动作零预测 miss。

这是局部关卡模型。原版 [replay](https://github.com/pbshgthm/arc-skill/blob/dba53c3799eab600a512dd73ed037d7ab6958c66/skills/arc-skill/scripts/arc_skill/rules.py#L296) 区分 MISMATCH、INCOMPLETE 与 HISTORY_FIT；较早关卡仍有未建模缺口。

P7 某次 L6 的十项 checked 报告直接列历史位置，并非由 `step` 独立生成，因此只能说明陈述与观察一致。我们的接口已区分这些证据类型，实际 actor 如何生成报告仍需观察；不能把 checked 标签当作可执行模型已校准。

### 5.4 有限时间内的研究节奏

P7 L6 一轮恢复后 289.6 秒才派发第一个新动作，十六个 cell 的报告执行耗时合计 2.881 秒，900 秒截止时尚剩 75 动作。另一轮首次动作延迟 168.043 秒，两个动作批次间隔 283.690 秒，十一个 cell 的报告执行仅 728 毫秒。余下时间不能精确归因于推理、传输或编排。

作者也遇到 BFS 状态膨胀和 A* 超时，但改为局部搜索观察位置、手工构造路线并用程序验证。两次续跑提供了更多探索机会；不能假设它与 P7 每级 900 秒的预算条件一致。

### 5.5 工具反馈与上下文负担

原版 [分析工具](https://github.com/pbshgthm/arc-skill/blob/dba53c3799eab600a512dd73ed037d7ab6958c66/skills/arc-skill/scripts/arc_skill/analysis.py#L148) 直接预载当前/历史/动画网格与算法，[观察工具](https://github.com/pbshgthm/arc-skill/blob/dba53c3799eab600a512dd73ed037d7ab6958c66/skills/arc-skill/scripts/arc_skill/inspect.py#L403) 提供变化描述及按需完整网格。

旧 P7 L6 轮次每次修订重复回传画面与元数据；八次修订约 90,506 新增上下文 token，九次计划约 84,101，最大单次输入 255,314。随后 compact delivery 已针对这一具体问题修复。旧负担不能直接描述成当前状态；上下文缩小与后续通关也不能证明唯一因果。

## 6. 当前判断与未完成边界

- 最直接的基础设施改进候选是：按每步实际起点保留/选择预测，分开当前点击 grounding 与是否预测画面变化，保留真实执行后的完整比较。此报告没有修改这些行为。
- 模型研究方面，搜索不可达应保留在局部模型范围；用新的观察检验地图覆盖，把真实 `step` 回放与事后陈述分开。作者的轨迹提供实际例子，不保证换模型后自动复制。
- P7 已有任意 Python、历史/动画读取、模型修订和可选执行代码；问题不是缺少计算能力。后续验收要指出外围哪项研究判断已由 actor 自身完成，并在固定代码、明确续跑与预算条件下验证，不能用合同数量或已有 100 分替代。
- 外部 BP35 用 Opus 5；本次短游戏试跑用 `gpt-6.1-sol`。宿主、预算、历史起点与提示条件不同，不能用两组成绩宣布某 harness 全面优于另一套。
- 本次 r11l 的有效 actor 被期限守卫截断、只完成四关；没有证明模型最终不能完成。公开全部二十五游戏结果、不同模型的短游戏试跑及未知游戏能力是不同证据边界。

## 私有证据定位

- 固定第三方源码与有效/失败试跑记录：`.asterion-private/arc-skill-original-trial/`。
- BP35 公开资料持久副本和逐文件 SHA256：`.asterion-private/arc-skill-bp35-comparison/`。
- P7 原始诊断保留在 `prime-p7-live/launches`：`bp35-l9-prefix-coordinate-diagnosis-20261007.md`、`bp35-l6-second-attempt-cognition-diagnosis-20261006.md`、`bp35-sk48-causal-diagnosis-20261006.md`、`bp35-fresh-round-followup-20261006.md`、`bp35-l6-compact-delivery-plan.md`。
