# Live Session Checkpoint

> Updated: 2026-10-11 14:26 CST. Session remains active — not a final handoff.

## 最新实测已结束

- 用户授权一次BP35完整九关冷实测；唯一真实试验已结束，未重跑/续跑。
- 5/9关、255动作/4RESET，L1–L5为20/47/40/62/45，L6未完成41动作。
- 1581.984秒至summary，128结算模型调用。129次before-request与末turn_start强烈支持128回调上限拒绝；原summary只记录ApplicationRunError，具体原因属推断。
- 独立386trace seal/255known事务通过；前五关214动作新SDK重放通过。完整失败后缀没有独立SDK重放。
- host已退出、guestunit不存在/0PID/空cgroup、trial临时.env删除，原console保留。
- [实测报告](../reviews/2026-10-11-p7-bp35-full-game-trial.md)；私有证据 `.asterion-private/p7-full-bp35-20261011-135551/`。
- 当前无运行工作包。下一候选：核对完整评估回调预设及失败原因保留；专用摘要接通仍独立未完成。本次不授权新一轮评估。

## 既有交接事实（本次运行不改写历史证据）




- 分支 `feat/prime-research-notes`；Project route: managed。唯一工作清单：[Prime自主研究接口](../superpowers/plans/2026-10-08-prime-autonomous-research-interface.md)。Task39与Task40均已关闭；没有在执行的工作包。
- Task40标准入口迁移全部完成，独立源码复审、完整打包检查和有限P7首关部署验收通过。最终验收提交 `edd19f62`，日志同步 `d96e323f`；本轮没有push/merge。
- 下一步候选：专用代码摘要接通及低阈值P7实战验证。先恢复设计与未知边界，确认独立实施范围，再推进；不得自动应用stash或启动BP35。

## 已验证事实

### 标准入口迁移

Prime复用既有kernel/session/composer/runner，统一管理Pi/RPC、扩展、工具装配、workspace和生命周期。应用提供领域目标、工具、数据、完成/续跑条件；operator解析配置并注入有限授权。通用层不读取 `.env`、认证或operator profile。

P1、P3–P7已有真实模型路径（含P7 narrator）已迁移；P2仍是无模型本地检索。独立应用直接调用标准库，无需中央登记。模型策略：P1/P3–P6 `deepseek/deepseek-flash`，P7所有模型路径 `openai-codex/gpt-6.1-sol`。P1隔离settings-only profile和环境key preflight保留；P4历史启动/绑定指纹不匹配在模型前拒绝，不隐式转换。

源码与修复提交见[实施计划](../superpowers/plans/2026-10-10-prime-standard-application-entry.md)。最终Sol领域复审和Astra合同复审均批准；取消清理缺口由 `37b6ab71` 修复。安装fixture隔离 `f1252307`，核心清单修正 `3d3f9f10`。

验证：TS93 PASS/6既有External-limited跳过；相关Python155 PASS；`make promotion-check` full PASS（25命令、provider_operations=0、full_dataset=no）；lint通过；最终docs-check313文件/229本地链接通过。首次安装fixture/core inventory失败已修复并重跑，不能把首跑记PASS。

### 本次真实打包部署

`make asterion-prime-p7-level-witness GAME=r11l LEVEL=1` 退出0，run `p7-live-20261010121949-382b0155f3024254a2e37e1b`。精确Sol模型，1关/4 primitive actions，receipt PASS，replay_verified/sealed_trace/cleanup_complete成立；13条sealed trace。沿用900秒总期限+180秒清理。

wheel SHA `319936b1c77942c36da78b1a2ff23f7508f8cdf25b3c21de68339be333c9306d`；实际research扩展SHA `a859ff5532124625feabd143b2c6ae2babe86dd5e9a515f251aab9bcc471e8a7` 与wheel一致；tool registry为 `ipython/p7_execute_plan/p7_workspace`。receipt SHA `fdb3830f9447383672ffa3c7f4c464274265e14527b58b610d9deaf0aaa0ccf2`。

私有证据 `.asterion-private/p7-task40-entry-witness-20261010-195033/`：source-manifest610文件、wheel-identity、guest-live、public-receipt、cleanup-observation和final-audit；独立审计PASS。435 wheel Python文件及三扩展资源与冻结源码一致。不要打印其中原始prompt、认证或模型输出。

### Task39历史证据

普通NOTES工作epoch实现 `2930fbd8` 已验证；保留引用读取、反例和未知执行结果。冷测前六关242paid/1死亡RESET/1605.836404秒；输入峰235052→73098、累计13474659→4699481，但解题质量整体回退。完整分析见[历史评估](../reviews/2026-10-09-p7-bp35-task32-interrupted-analysis.md)。

Task39 BP35私有归档 `.asterion-private/p7-task39-cold-bp35-20261010/trial` 已封存，2037项manifest SHA `736c1fcf4bc8ddc1a9c1a68005e230e2c0c0f2b0361bcc77b573b923b1bdde29`。不能改写、续L7或继承预算。

## 当前判断

- Prime标准入口已具备本轮迁移合同和P7首关部署证据，可作为稳定基础底层。跨领域长程能力仍需具体评估。
- 后续认知工作应聚焦专用摘要真实接通与压缩后继续正确研究；NOTES输入减少不能替代解题质量证明。

## 历史归档

- 应用自行构造Pi/RPC和扩展是Task40已修复的旧缺口，不作为新应用模板。
- CLI定位待定，不属于本次迁移；DCI属于Native线，不能用来推导Prime CLI用途。
- 不重走小窗口盲切、额外强制模型checkpoint或细碎认知门禁。
- 用户撤回截图投诉和“小石：”前缀输入，本轮未据此创建修复任务。

## 未完成边界与下一动作

1. 默认专用代码摘要尚未接通：旧Prime fork改写真实存在，迁移启动链没有该改写；默认阈值与专用摘要语义是不同问题。先核对[设计](../superpowers/specs/2026-10-10-prime-standard-application-entry-design.md)、D-2026-10-10-03和canonical未完成条目。
2. 草稿stash `30ec751b8219f52c55e265e94ca965f65c0c85f7` 保留，未apply或删除。未来验证要覆盖实际摘要模型/usage/预算、kernel变量与generation、NOTES/反例及压缩后解题。
3. P2自主检索、P1/P3–P6本次版本真实模型端到端实测、跨领域稳定率、模型质量和长程压缩重放不从本次P7首关推断完成。
4. 原生Pi逐组正文未全程持久化、长epoch内部增长、约23KB重复初始材料和大stdout开销仍未解决。BP35六关结果不是九关全通。

## 清理与恢复

本会话Make已退出；guest unit `asterion-p7-7f6c886044684433a14e0a38bd517342.service` inactive，MainPID=0、ControlGroup空；观察PID358519/358561/358593/358608全部消失。无本会话遗留实测进程。用户console历史PID52024/port56659不属于清理范围，保留。

```bash
git status --short
git log --oneline -6
git stash list
rg -n 'Task40|D-2026-10-10-03' docs/status/DECISIONS.md docs/superpowers/plans/2026-10-08-prime-autonomous-research-interface.md
```

下次执行 `$project-state resume` 即可恢复；本交接不授权新付费全量评估。
