# Live Session Checkpoint

> Updated: 2026-09-25 21:43 CST. Session remains active; this is a recovery checkpoint.

## 当前任务与授权

用户最新指示先广度优先再扫未解的第 1、2 关，暂缓深入第 4 关以后。已验证动作日志与逐步预测核对的设计稿、计划和核心代码已落地。既有首轮 25 题 L1、二轮 17 题 L2 都各首次尝试过；新广度轮应对仍未解的 8 题 L1 各补一次，再对仍未解的 L2 题（原有 13 题，外加新通过 L1 的题）各补一次。已验证关卡必须跳过，仍执行人类动作上限、每题 30 分钟及 5 分钟无动作停止线。新官方 scorecard 提交**未获授权**。

用户已批准独立广度重扫设计并启动本地扫题，但在 BP35 首关未解后说“稍等，分析一下为什么没解开”，随后要求对照修订和 Retrodict 经验找原因。**现已暂停付费扫题，不自行续跑。**设计稿 `8563543d`、计划 `3877757c`/`8b4ffaa6`、停滞校验 `a06b139a`、控制器 `bcf988b7`/`60aab633`/`de36d268`、短命令与指南 `95ee410d` 已提交。安装版零模型预检列出 8 道未解 L1、13 道未解 L2；53 项聚焦测试、Ruff、docs-check 和独立复审通过。旧 first/second-round 账本哈希不变。

## 已验证事实

- 首轮 25 题中有 17 题获得已封存、回放验证、清理完整的 L1 前缀；8 题首关未解。17 道 L1 的中文网页齐全；一次已授权官方提交总分 `2.5044733044733043`、17 题各完成首关、0 整题通关。详见 `docs/guides/prime-p7-games-and-official-results.md`。
- 二关私有账本 `.asterion-private/prime-p7-live/second-round-campaign.json` 现有 **17/17** 个唯一题目。四题 L2 已验证：旧结果 DC22（新增 61 步）、M0R0（90 步）；本次新增 VC33（14 步，`p7-live-20260925110850-b61955289cb652fe638ac65d`）、WA30（58 步，`p7-live-20260925111620-c1c66d732b4e873ecfc2da32`）。11 题达到动作额度未解，LP85 为 `execution-failed`，TR87 为 `execution-stalled`，后二者不能记作正常解题失败或成功。VC33、WA30 均有封存、回放和来宾清理验证；最后两题续跑命令退出 0。
- TR87 `p7-live-20260925083030-5d512d1827058d7dd1a16dac` 停在 62 总动作：前 40 步与历史封存且 replay verified 的 L1 逐项相同，L2 新增 22 步。`2ceec52d` 校验历史摘要、seal、哈希链、身份、逐项前缀、关卡不回退及按实际 L1 长度计算的 L2 额度。独立审查用前缀篡改、关卡回退、额度缩小、seal 破坏四种变异证实拒绝。刚构建 wheel 加 ARC 两只 wheel 的零模型 `--adopt-execution-stalled` 于 17:17 退出码 0，账本记为 `execution-stalled`；未运行模型，也未改原轨迹。
- `c069914c` 修正 P7 文本观察工具读取动画**末帧**并显示全部 16 色；`48521df1` 将该语义写入离线/官方共享提示。离线检查真实 L2 录制中多帧首末不等，证明旧 helper 会读错稳定状态；实际通过率收益未验证。`63c79ebb` 更新两个 provider 的提示词准入摘要，修复安装版路径拒绝。后续完整 `make check` PASS（3354 项 Python 测试，4 skip，连同 TypeScript、Rust、文档、构建），`make promotion-check` PASS（25 个隔离命令，零 provider 操作）；最终日志在 `.asterion-private/p7-final-make-check.log` 和 `.asterion-private/p7-final-promotion-check.log`。
- 代码审计确认 L2 重放首关动作后新建空 Python worker，只继承游戏状态，不继承 L1 的规则、观察或笔记。Retrodict/Tycho 等社区实现保留逐步记录并用历史检查可执行规则；模型/成本/公开题目条件不同，不能直接比较排行榜通过率。既有失败如 FT09 L2 12/12 次点击、SB26 26/28 次点击，多数动作改变状态，尚不足以断言具体游戏规则或模型能力上限。
- 已实现本次运行的稳定帧历史与有界分页、`frame_at`、逐项 `act_checked` 与首次不符停步（`a2202614`、`983af587`、`1d03db09`、`544a836c`、`4cf293f6`、`1323af25`）。`c48f1426` 和 `93544849` 将已验证首关前缀在模型启动前注入同一 broker，并修正共享提示词。`1b42a616`、`3b5e11ae`、`3d93461b` 记录私有计数；`6ffbaebc` 使显式本地 legacy 选用原有提示词。独立复审批准核心代码。定向测试、`make lint`、`make docs-check`、最终 `make check` 和 `make promotion-check` 均通过；早期失败日志只属修复前历史。
- 单题 A/B 入口曾对已解的 DC22 付费重复运行。首轮 intended legacy 实际运行在 verified 模式，因为 guest systemd 缺 `ASTERION_PRIME_P7_HISTORY_VARIANT` 转发；它以新增 **99 步**通过 DC22 L2，慢于之前的 **61 步**，工具正确拒绝将其计入 A/B 并未启动第二臂。`03cc46b1` 修复转发，安装版只读检查确认 guest 接收 legacy；随后按用户要求中断另一场 DC22 重复，不具封存成功证据，不计成绩。**不得再对已解关卡做付费对照，也不得声称 99 步显示改进。**
- `4b5dc9df` 新增 `make asterion-prime-p7-next GAME=<题号>`，自动选最高已回放验证前缀的下一关，固定人类动作、30 分钟和 5 分钟停止线，只有新运行封存、回放与清理成功才记 verified。`f97207d8`、`2b487922` 修正私有路径输出泄漏；独立复审批准，21 项聚焦测试及 Ruff 通过。VC33 L3 新增 31/44 步、M0R0 L3 新增 84/203 步均已验证通过。WA30 L3 用满 183 新增动作未解，失败运行封存、回放、清理通过，不自动重试。DC22 L3 `p7-live-20260925115050-aa51a29c969b32fa07662b18` 重放104步前缀后零新增动作，五分钟停滞；原始 stall receipt 记载清理完成，旧 manifest 仍以 `execution-stalled-evidence-invalid` 标记。`cbdf0a86` 修复 L3+ 严格停滞验证，48 项聚焦测试和 Ruff 通过，独立复审批准本单题入口；安装版含 ARC wheels 的只读验收对原始 DC22 记录返回 `True`，不改原始证据或称其过关。VC33 L4 `p7-live-20260925121649-7604f40b2427eb2a2b401679` 按用户最新广度优先指示中断：只有 52 个已验证 L3 前缀动作，无 L4 新动作；manifest `unverified/not-started`，原始运行未封存，不能计过关或失败。已确认来宾无残留 P7 单元。当前无付费游戏运行。
- 广度重扫 BP35 L1 `p7-live-20260925131956-015b9ec7016434350579a0c0` 用满 21/21 步、0/9 关，封存/回放/清理通过；账本记 `unsolved`，输入 3,166,683、输出 86,477 token。动作 2–8 连点七个绿色块，绿色像素归零仍未过关；动作 12 向右触发大幅新布局。动作 9、13、19 只有底边 `(x,63)` 计步条各变一个格，棋盘内部不变；当前 `diff()` 仍计入该变化，提示缺显式 HUD 排除。两组 `act_checked` 共 8 项预测命中、0 失配，只证明局部动作效果，不证明“清空绿色即目标”。用户要求停止分析，CD82 L1 在 4 步时中断，原 run 未封存，新账本保留 `running`；来宾无残留 P7 服务。自动续跑会因人工审计门槛而拒绝，**不得修改/清除账本后直接重付费**。详见 `ASTERION-PRIME-P7-EVIDENCE.md`。

## 当前判断与未完成边界

- 已修复的动画帧错误是确定的实现缺陷；L1 经验丢失和缺少预测核对是可测的设计缺口。本次 VC33、WA30 通过 L2 是新成功，但并无同条件对照证明改造提高总体通过率。用户明确将付费优先级转向下一未解关卡，不再做已解关卡 A/B。
- `e128f3b1` 修复网页 reader 拒绝新版 summary 中 `experiment`、`prediction_accounting` 的问题；VC33 L2 的 recording 两个 RESET 去重后与 21 个 trace 动作逐项匹配。26 项 run-story 测试、Ruff 和独立代码复审通过。VC33、WA30 L2 以及 VC33、M0R0 L3 均有身份和 SHA 绑定的离线中文 HTML；WA30 L2、VC33 L3 分析 accepted，VC33 L2、M0R0 L3 使用事实核验的中文 fallback 摘要。
- P7 框架与应用边界保持不变：只在应用/host 注入当前游戏证据，不使通用框架读取 ARC 数据、凭据或 `.env`；不从游戏源码、其他题目或未验证 run 取模型知识。旧未封存失败不能成为过关前缀。
- `load_best_prefix` 在普通源码虚拟环境缺 ARC wheels 时可能返回 `None`；判定真实可复用前缀应使用刚构建项目 wheel 加两只 ARC wheel 的隔离环境。TR87 的历史封存关联为独立离线恢复证据，不等同于对 TR87 本次轨迹做完整回放。

## 下一动作

1. 回答用户对 BP35 的原因分析：清绿块的局部效果与通关目标被混同；底边计步条造成三次“全帧变化但棋盘无变化”；核对 Retrodict 的日志、HUD 和规则假设做法，区分已验证事实、当前判断和模型差异。暂不启动新模型。
2. 若用户决定改进再续跑，先设计最小的 HUD/目标假设区分与 Retrodict 式日志核对，不依赖游戏源码或答案；实现并验证后，对 CD82 `running` 记录做只读审计并制定安全恢复，不得抹掉四步证据或自动重试。当前 `make p7-breadth` 会停在 `breadth-running-entry-requires-audit`。
3. 暂缓 VC33、M0R0 L4 以及其他深关；不提交新官方 scorecard。
