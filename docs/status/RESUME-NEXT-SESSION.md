# Live Session Checkpoint

> Updated: 2026-09-25 17:18 CST. Session remains active; this is a recovery checkpoint.

## 当前任务与授权

用户要求检查 P7 二关低通过率，参考社区代码代理，并**先实现**已验证动作日志与逐步预测核对，再继续付费二关扫描。设计稿 `docs/superpowers/specs/2026-09-25-prime-p7-verified-history-and-prediction-design.md` 已获用户确认；实现计划正在写。既有二关扫描授权为：17 道已验证首关的题目每题只尝试二关一次，新增动作不超过该关人类基准，每题最多 30 分钟，连续 5 分钟无 `arc.action` 即停，没有整轮 token/时间上限。新官方 scorecard 提交**未获授权**。

## 已验证事实

- 首轮 25 题中有 17 题获得已封存、回放验证、清理完整的 L1 前缀；8 题首关未解。17 道 L1 的中文网页齐全；一次已授权官方提交总分 `2.5044733044733043`、17 题各完成首关、0 整题通关。详见 `docs/guides/prime-p7-games-and-official-results.md`。
- 二关私有账本 `.asterion-private/prime-p7-live/second-round-campaign.json` 现有 **15/17** 个唯一题目：DC22、M0R0 的 L2 已验证并有中文单文件网页；12 题未解或执行失败（AR25、CN04、FT09、LF52、LP85、LS20、R11L、RE86、SB26、SC25、SP80、SU15）；TR87 为 `execution-stalled`。余下 VC33、WA30 未尝试。LP85 与 TR87 是独立执行问题分类，不能记作正常解题失败或成功。
- TR87 `p7-live-20260925083030-5d512d1827058d7dd1a16dac` 停在 62 总动作：前 40 步与历史封存且 replay verified 的 L1 逐项相同，L2 新增 22 步。`2ceec52d` 校验历史摘要、seal、哈希链、身份、逐项前缀、关卡不回退及按实际 L1 长度计算的 L2 额度。独立审查用前缀篡改、关卡回退、额度缩小、seal 破坏四种变异证实拒绝。刚构建 wheel 加 ARC 两只 wheel 的零模型 `--adopt-execution-stalled` 于 17:17 退出码 0，账本记为 `execution-stalled`；未运行模型，也未改原轨迹。
- `c069914c` 修正 P7 文本观察工具读取动画**末帧**并显示全部 16 色；`48521df1` 将该语义写入离线/官方共享提示。离线检查 R11L、SB26 等真实 L2 录制中多帧首末不等，证明旧 helper 会读错稳定状态；实际通过率收益未验证。`63c79ebb` 更新两个 provider 的提示词准入摘要，修复随后安装版 P7 路径拒绝；35 项相关测试 PASS。完整 `make promotion-check` 在摘要修复前失败 5 项/报错 7 项，修复后尚未重跑；不得声称全套 PASS。
- 代码审计确认 L2 重放首关动作后新建空 Python worker，只继承游戏状态，不继承 L1 的规则、观察或笔记。Retrodict/Tycho 等社区实现保留逐步记录并用历史检查可执行规则；模型/成本/公开题目条件不同，不能直接比较排行榜通过率。既有失败如 FT09 L2 12/12 次点击、SB26 26/28 次点击，多数动作改变状态，尚不足以断言具体游戏规则或模型能力上限。

## 当前判断与未完成边界

- 已修复的动画帧错误是确定的实现缺陷；L1 经验丢失和缺少预测核对是可测的设计缺口。它们对 L2 成绩的因果影响须由固定模型与动作/时间上限的 A/B 运行验证。用户选定先做“已验证日志＋预测核对”，不是完整复刻 Retrodict。
- P7 框架与应用边界保持不变：只在应用/host 注入当前游戏证据，不使通用框架读取 ARC 数据、凭据或 `.env`；不从游戏源码、其他题目或未验证 run 取模型知识。旧未封存失败不能成为过关前缀。
- `load_best_prefix` 在普通源码虚拟环境缺 ARC wheels 时可能返回 `None`；判定真实可复用前缀应使用刚构建项目 wheel 加两只 ARC wheel 的隔离环境。TR87 的历史封存关联为独立离线恢复证据，不等同于对 TR87 本次轨迹做完整回放。

## 下一动作

1. 完成并自审 `docs/superpowers/plans/2026-09-25-prime-p7-verified-history-and-prediction.md`；按已确认设计执行，采用仓库要求的 subagent 任务复审。先确认 provider 摘要修复后的安装版 P7 聚焦测试；提示词再次改动时同步更新准入摘要。
2. 实现当前游戏已验证 L1 与后续动作的有界稳定帧历史查询、`act_checked` 逐步预测及首次不符停步，保留原 broker 计数和证据合同。做零模型回放/失败边界测试及至少一组有限 A/B；未通过前不启动 VC33/WA30 的付费扫描。
3. 新能力经测试和复审后再完成 VC33、WA30 的首次 L2 扫描，为新验证关卡生成中文网页，更新指南、状态与逐题账本。最终运行 `make promotion-check`、`make lint`、`make docs-check`；不得提交新官方卡片。
