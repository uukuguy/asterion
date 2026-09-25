# Live Session Checkpoint

> Updated: 2026-09-25 18:24 CST. Session remains active; this is a recovery checkpoint.

## 当前任务与授权

用户要求检查 P7 二关低通过率，参考社区代码代理，并**先实现**已验证动作日志与逐步预测核对，再继续付费二关扫描。设计稿 `docs/superpowers/specs/2026-09-25-prime-p7-verified-history-and-prediction-design.md` 与实现计划 `docs/superpowers/plans/2026-09-25-prime-p7-verified-history-and-prediction.md` 已获确认并已落地核心代码。既有二关扫描授权为：17 道已验证首关的题目每题只尝试二关一次，新增动作不超过该关人类基准，每题最多 30 分钟，连续 5 分钟无 `arc.action` 即停，没有整轮 token/时间上限。新官方 scorecard 提交**未获授权**。

## 已验证事实

- 首轮 25 题中有 17 题获得已封存、回放验证、清理完整的 L1 前缀；8 题首关未解。17 道 L1 的中文网页齐全；一次已授权官方提交总分 `2.5044733044733043`、17 题各完成首关、0 整题通关。详见 `docs/guides/prime-p7-games-and-official-results.md`。
- 二关私有账本 `.asterion-private/prime-p7-live/second-round-campaign.json` 现有 **15/17** 个唯一题目：DC22、M0R0 的 L2 已验证并有中文单文件网页；12 题未解或执行失败（AR25、CN04、FT09、LF52、LP85、LS20、R11L、RE86、SB26、SC25、SP80、SU15）；TR87 为 `execution-stalled`。余下 VC33、WA30 未尝试。LP85 与 TR87 是独立执行问题分类，不能记作正常解题失败或成功。
- TR87 `p7-live-20260925083030-5d512d1827058d7dd1a16dac` 停在 62 总动作：前 40 步与历史封存且 replay verified 的 L1 逐项相同，L2 新增 22 步。`2ceec52d` 校验历史摘要、seal、哈希链、身份、逐项前缀、关卡不回退及按实际 L1 长度计算的 L2 额度。独立审查用前缀篡改、关卡回退、额度缩小、seal 破坏四种变异证实拒绝。刚构建 wheel 加 ARC 两只 wheel 的零模型 `--adopt-execution-stalled` 于 17:17 退出码 0，账本记为 `execution-stalled`；未运行模型，也未改原轨迹。
- `c069914c` 修正 P7 文本观察工具读取动画**末帧**并显示全部 16 色；`48521df1` 将该语义写入离线/官方共享提示。离线检查 R11L、SB26 等真实 L2 录制中多帧首末不等，证明旧 helper 会读错稳定状态；实际通过率收益未验证。`63c79ebb` 更新两个 provider 的提示词准入摘要，修复随后安装版 P7 路径拒绝；35 项相关测试 PASS。完整 `make promotion-check` 在摘要修复前失败 5 项/报错 7 项，修复后尚未重跑；不得声称全套 PASS。
- 代码审计确认 L2 重放首关动作后新建空 Python worker，只继承游戏状态，不继承 L1 的规则、观察或笔记。Retrodict/Tycho 等社区实现保留逐步记录并用历史检查可执行规则；模型/成本/公开题目条件不同，不能直接比较排行榜通过率。既有失败如 FT09 L2 12/12 次点击、SB26 26/28 次点击，多数动作改变状态，尚不足以断言具体游戏规则或模型能力上限。
- 已实现本次运行的稳定帧历史与有界分页、`frame_at`、逐项 `act_checked` 与首次不符停步（`a2202614`、`983af587`、`1d03db09`、`544a836c`、`4cf293f6`、`1323af25`）。`c48f1426` 和 `93544849` 将已验证首关前缀在模型启动前注入同一 broker，并修正共享提示词。`1b42a616`、`3b5e11ae`、`3d93461b` 记录私有计数，区分已匹配、异常不确定与未派发；`6ffbaebc` 使显式本地 legacy 选用原有提示词，双 provider 只接受两个固定提示词摘要。独立复审已批准核心代码；P7 聚焦 111 项 PASS、`make lint` PASS、`make docs-check` PASS。最初 `make promotion-check` 与 `make check` 各有相同 2 项失败：安装版夹具用旧批量动作，提示词断言保留旧文案；`d3e3c602`、`ad9418b7` 已修正，两项定向测试 PASS，最终 `make check` 正在重跑。失败的早期检查不得标 PASS。
- 单题对照入口 `tools/run_prime_p7_targeted_ab.py`、`make asterion-prime-p7-targeted-ab GAME=<题号>` 已在 `fed1c389`、`9d4751b4`、`10eb5ef7` 落地；独立审查批准前缀逐动作、封存 sidecar、哈希链、回放摘要、额度及来宾清理边界。20 项工具/Make 零模型测试 PASS。它只把**两臂完整封存回放**的运行算有效对照；L2 部分失败记录只验证首关，入口会中止而不伪造对照。目前尚未付费运行该入口。

## 当前判断与未完成边界

- 已修复的动画帧错误是确定的实现缺陷；L1 经验丢失和缺少预测核对是可测的设计缺口。它们对 L2 成绩的因果影响须由固定模型与动作/时间上限的 A/B 运行验证。用户选定先做“已验证日志＋预测核对”，不是完整复刻 Retrodict。
- 当前新增的可读历史只传已发生观察；尚无证据显示二关通过率改善。普通独立 level witness 有一小时内部期限而无 5 分钟无动作 supervisor；固定二关扫题由外层 supervisor 执行每题 30 分钟与 5 分钟停止线，不能混作同条件 A/B。
- P7 框架与应用边界保持不变：只在应用/host 注入当前游戏证据，不使通用框架读取 ARC 数据、凭据或 `.env`；不从游戏源码、其他题目或未验证 run 取模型知识。旧未封存失败不能成为过关前缀。
- `load_best_prefix` 在普通源码虚拟环境缺 ARC wheels 时可能返回 `None`；判定真实可复用前缀应使用刚构建项目 wheel 加两只 ARC wheel 的隔离环境。TR87 的历史封存关联为独立离线恢复证据，不等同于对 TR87 本次轨迹做完整回放。

## 下一动作

1. 等待最终 `make check` 结果，并运行 `make promotion-check`、P7 聚焦测试及零模型官方 preflight，只记录实际通过的验证。单题 A/B 入口已独立复审，但尚未进行付费对照；严禁修改第二轮账本和官方 scorecard。
2. 用同一题已验证 L1 起点，固定 DeepSeek Flash、L2 人类动作上限、外层 30 分钟与 5 分钟停滞线，分别进行 legacy 与 verified 有限对照，核对独立时间戳 run、动作与 token。不能仅凭单元测试宣称成绩改善。
3. 再完成第二轮剩余 VC33、WA30 的首次 L2 扫描，为新验证关卡生成中文网页，更新指南、状态与逐题账本；不得提交新官方卡片。
