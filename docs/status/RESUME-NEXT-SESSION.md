# Live Session Checkpoint

> Updated: 2026-10-10 17:50 CST. Session remains active — not a final handoff. 用户已要求继续实施；计划 Task 1 已实现并复审；Task 2/3 执行中。

## 恢复摘要

- 分支 `feat/prime-research-notes`；managed，唯一工作清单：[Prime自主研究接口](../superpowers/plans/2026-10-08-prime-autonomous-research-interface.md) Task40。用户已同意先统一已有真实模型路径的标准接入和资源所有权，保持 Prime 稳定底层；P2 本轮记录目标与边界，自主检索能力补全另列。
- 当前产物：[标准应用入口设计](../superpowers/specs/2026-10-10-prime-standard-application-entry-design.md)已经用户确认；[实施计划](../superpowers/plans/2026-10-10-prime-standard-application-entry.md)已完成自审。当前执行：Task 1 已由 d5668e8c/ae185b25 完成无效果入口与输入合同，8 项测试/复审通过；Task 2 模型会话和 Task 3 工具扩展分离进行中，后续依赖完成后继续 Task 4–8；代码所有权、迁移兼容和验收条件已列明。执行方式沿用 AGENTS 的子代理分工，无需再选择模式。计划文档验证：docs-check313文件/228链接、diff-check通过。代码实施已授权并进行中；尚未启动付费运行。
- 用户补充：P1–P7 是独立应用，直接使用 Prime 标准接口，不需要中央注册；CLI 定位待定，本轮不设计统一应用管理 CLI。不得以 DCI/Native 的用途推导 Prime CLI 需求。现存 provider/assembly 仅保留兼容。工具注册与应用登记分开。
- 模型要求：P1–P6 精确使用 `deepseek-flash`，P7 全部模型路径（含 narrator）使用 `gpt-6.1-sol`。P2 当前无模型调用；不得以改模型要求扩张检索能力。计划移除必填 provider 身份和核心应用分派，并验收未登记外部应用。
- Prime 复用既有执行核心；收回 Pi/RPC、扩展加载、工具装配及会话生命周期。应用保留目标/工具/数据/领域完成条件；operator 显式注入配置和有限授权。先 P7，后 P1 与 P3–P6 live；P2 本地 witness 的行为保留。
- 源码更正：P3–P6 已有真实 Pi 文本 live 路径，也保留确定性 witness；P2 当前无模型或 IPython 子进程。共用 runtime 名称不能证明共用 Prime 后端。P1 手动压缩说明与专用材料不代表默认专用摘要已接通。
- Task39 已封存：NOTES 输入减少、解题质量回退。下列事实与未完成边界继续有效。P7 L2/L5 推理改进仍待研究，本轮不改变游戏策略。
- 专用摘要接通及未来低阈值 P7 实战测试独立验证；既有 stash 保留。新 BP35 和广泛自主能力改造未开始，也不继承历史试验预算。

## 已验证事实

生产实现 `2930fbd8`：普通接受的NOTES建立可信工作epoch，旧明细按引用读取，近期反馈、有效用户约束、重要错误及未知执行结果受保护，无额外模型checkpoint流程。P7研究prompt自由组织有效认识、反例、未决问题和程序引用；数据层保留实际反馈。轮包SHA `a6ad55934e4104a67ad978fd8694197c2bb9e7b0c9094208ef4963966706e863`，扩展SHA `13bfee2e2990b7556950ea9a440f610263ab3f03f82a0ffe1f7f1ea54329272b`。

验证：TS88 PASS/6外部skip、相关Python48 PASS、promotion25 PASS/provider0、实际安装Pi离线探针通过。真实r11l L1为7paid/Q115/128.140348秒，无RESET或undo；4次NOTES实际退休0→2→4→7完整组，输入61073→21105tokens。与历史4步相比回退3步，主要为局部点击判断；单次轨迹不能证明NOTES导致回退。

### Task39 BP35冷测

Sol `gpt-6.1-sol / medium`，seed0，原生目标6，5400+180有限预算；无继承笔记/路线，无外围提示/代码修订。run `p7-live-20261009190243-2748a9d086a6d077c0aeba73`。严格mint19:02:42.396297Z至SDKgoal19:29:28.232701Z为1605.836404秒；receipt自身started口径1605.835612秒，相差0.000792秒。

| 关 | 全部paid / 成功段 | 单关分 | 秒 |
| --- | ---: | ---: | ---: |
| L1 | 20 / 20 | 110.25 | 148.369237 |
| L2 | 68 / 40 | 49.826990 | 308.256073 |
| L3 | 34 / 34 | 115 | 189.407939 |
| L4 | 23 / 23 | 115 | 171.997174 |
| L5 | 46 / 46 | 51.465028 | 496.445278 |
| L6 | 51 / 51 | 115 | 291.360703 |

合计242paid、一次L2死亡RESET；L5六/L6四次ACTION7均计费。初始化2RESET单列。官方九关partial43.605092；六关比较归一化93.439482不是官方整局分。baseline21/48/44/38/33/87，115门槛19/44/41/35/30/81；q=min(115,100*(baseline/allpaid)^2)，失败和RESET不退款。115顶格后更少步不增加得分；用户认可探索性一次过关不必每关满分。

Task38为215paid/0死亡RESET/1482.657593秒/九关partial46.666667，本轮多27步、慢123.178811秒。历史最好17分钟版1023.279883秒/221paid/2RESET，版本不同不作单一因果对照。原arc-skill为6of9/271paid/3RESET，19/48/34/23/45/102，约56分钟含自然续跑/宿主恢复；不能误称九关全通。

Goal126请求input4639960/output42760；final127 input4699481/output42803/raw637785/cacheRead4061696/cacheWrite0，峰73098tokens。相比Task38 final13474659/峰235052分别减少65.12%/68.90%。NOTES16次/final1387B，context峰237717B/累计14864874B。L5同epoch查询和动作累积后，L6新NOTES将237717B收拢至87802B；字节不等于tokens。37纯计算继发请求完整保留前次serializedinput前缀；compute加权cache92.8861%、plan89.4950%、workspace44.5688%。

244完整SDK逐data除guid回放、242known事务、373trace及seal、125研究链和69文件引用、127双metrics通过。最终2037项manifest逐bytes/hash/五roots覆盖独立READY，SHA `736c1fcf4bc8ddc1a9c1a68005e230e2c0c0f2b0361bcc77b573b923b1bdde29`。源码570/wheel和20launch冻结身份一致；570source/588install核验。独立analysis SHA `e7059ee2aaa7da14f313411aa7860bbd8d91c3fc93ebee288d3d1c94ee4ffa2e`。

私有trial `.asterion-private/p7-task39-cold-bp35-20261010/trial` 已封存，不改写、续L7或重新执行。r11l在 `.asterion-private/p7-task39-witness-20261010/trial`，138manifest SHA `0f4e44188e4977da6edfdb29e67bcb23a53e7b654f1bc7daf6624f6530f8d201`。只读原档检索不等于新执行授权。

## 当前判断

- L2已怀疑15危险，却以远程点击无效及“无其它出口”削弱危险判断，删除停点死亡。自主回看后找到横向通道并40步成功；是可避免推理失误候选，不宜笼统称随机或必要探索费。
- L5自主修正漏第8列、滚屏格心问题，随后把局部未见返程8推成路线不可行。撤销6步试直行，实际被8挡，重新下降才见新8并成功；不能称最初点8已证明多余。NOTES记住反例，没有重复遗忘同一已知失误。
- L6补返程停点后反转/分段返回实际成功；4undo理由明确但未证明全部必要或最优。上下文机制奏效不等于策略质量改善，也不能把所有耗时归于tokens。

## 历史归档与不要重走的路径

- Task38“NOTES短但全部原生历史仍累积”是Task39前的真实诊断；不能继续写成当前尚未实现。历史评估保留在原分析，不装入恢复上下文全文。
- 小窗口盲切、额外强制模型checkpoint、细碎认知门禁不是当前方向。提供完整客观信息及可追溯证据，让模型自主推理。
- P7当前确实通过AsterionPrimeSession执行，但应用仍构造底层RPC/扩展接线；不代表统一私有Prime入口已完成，也不是绕过Prime的独立解题器。D-2026-10-10-02替代旧D-2026-09-27-01临时许可。私有Pi不意味着所有会话共享一个进程。

## 未完成边界

- 原生Pi正文未持久化；stderr前14条primary及退休0→4→12可直接审计，此后diagnostics-suppressed，完整FD指标不能替代全程逐组正文审计。另有1oversize旁路省略，原字节完整转发。native context_archive是否实际调用未知（17workspace中16NOTES、另一次op/body未保存）；已有cell/history/frame/patches实际回读。
- 未观察到native compaction，不验证专用摘要。旧Prime fork确实改写原生摘要生成，当前迁移启动链未接通该改写；默认高阈值约255616与专用语义是两件事。未来低阈值验证需真实选定模型摘要、usage/预算、持久kernel变量/函数/generation、NOTES/反例以及继续正确解题。
- 全部 Pi 启动/配置/扩展/RPC 及默认专用摘要应归 Prime 私有接入。P1/P7 仍有应用侧接线；P3–P6 live 直接创建真实 Pi 文本会话，另有确定性 witness；P2 是本地 worker/context。Task40 已确认标准接入设计范围，源码迁移尚未开始，统一真实长程 agent 能力未验证。
- 专用摘要未完成初稿隔离在stash `30ec751b8219f52c55e265e94ca965f65c0c85f7`（3个TS文件）；保留，不自动apply或删除。没有新的Python迁移源码。约23KB重复初始指令/快照及大stdout仍有开销，未修复。
- 跨领域能力、稳定成功率、压缩后重放范围、评分/时延的稳定改进未证明。六关目标不是BP35九关全通。

## 清理与恢复命令

Ownedhost50540/50542/50543、observer50665消失，guestunit notfound/cgroupempty，auth/env已移除；cleanup1621.535325秒。用户console PID52024/port56659保留；不要停止。无正在运行的本会话实测。

```bash
git status --short
git log --oneline -6
rg -n 'Task39|D-2026-10-10-0[12]' docs/status/DECISIONS.md docs/reviews/2026-10-09-p7-bp35-task32-interrupted-analysis.md
git stash list
```

Task39 已提交核心2930fbd8、r11l1046624f、架构记录f9f4b512、低阈值验证0fb15c7c、最终评估f0760ab8；前次最终交接b08bc5a2、日志be028db7。本轮仅设计与状态修订，没有执行push/merge；这是活动会话 checkpoint，不是新的最终收口。
