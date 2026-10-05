# Next-Session Handoff

> Updated: 2026-10-05 19:20 CST. 会话已收口。控制台已正常关闭，人工存档保留；下一会话先读取本文件，不依赖聊天记录。

## 已验证事实

- 分支：`feat/p7-live-console`。路由：managed；原生迁移工作表仍是 `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md`。本轮控制台计划：`docs/superpowers/plans/2026-10-05-prime-p7-live-console.md`，已交付实时主流程及人工功能追加项。
- 关键提交：`ed6fa64b` 实时控制台；`004442f2` 重复帧源身份；`9e98b49e` guest 代理；`83a4f404` 独立人工局；`8974457b` 直接选关及记住选择；`898f7536` 按钮反馈和帧历史；`a50044d1` 逐关存档；`bc01bd80` 当前关卡清空重开。本地提交未在本轮推送。
- `make p7-console` 是启动入口。页面包含 P7 自主运行、独立人工试玩和离线回放。人工可直接选任何有效关卡。动作按钮高亮当前动作；变化格覆盖默认关闭。P7 只在点击启动后运行，固定 L1 预设最多 900 秒。
- 人工每步自动保存。切关、刷新、服务重启会恢复该关实际位置及动作历史。存档只属于 HUMAN，不进入 P7 认知、上下文、历史、attempt 或经验。SDK 临时录制与持久人工 JSON 存档是不同文件，关闭只删除前者。
- 恢复使用实际 SDK 重放，并核对 seed、原始起点、固定 SDK/game 身份及每步观察。保留完整起点前缀，页面展示最近 1001 帧；恢复与新局操作预算分开。RESET 保留历史。自动过关保存新关，并保留上一关最后可玩的画面。进入已有存档的新关时显示 pending，首次明确动作后才替换旧槽。
- “清空并重新开始”只替换当前人工关卡存档，建立真实初始画面、新会话、零动作计数和一帧历史。其他关卡及其前缀保留。SDK 初始化和保存成功后才发布新会话；失败保留原存档和原身份/历史并允许重试。成功命令的重复请求不会清空后续动作。
- 最终针对性验证：132 项 Python、72 项最终安装包 HTML DOM 检查通过；lint、docs、JS 语法、diff 检查通过。独立恢复合同复审通过。真实 SDK/HTTP 清空 L1/L2、保留其他存档字节、重复/旧请求、重启后恢复及收尾通过：10 个人工动作，2 次清空，0 个 P7 动作。
- 存档功能的另一组真实证据：SP80 L1/L2/L6 切换、两次服务重启、RESET 和实际完成数 1 的原始前缀恢复通过。实际 HTTP 响应被最终页面用于时间轴/队列及清空按钮验证。
- 本轮真实 P7 过程证据为 `p7-live-20261005063214-b9a30b6cbfd609490469887f`：2 个公开决策、5 个真实动作、33 帧、5 个认知版本，动作源序列与决策相联。显式停止及 guest unit/cgroup/host 清理通过；完成关卡数为 0。人工过关不算 P7 成果。
- 最终全仓 promotion 未通过：3908 tests，13 failures、5 errors、4 skips。`/tmp/p7-manual-restart-promotion.log` 尾部指向已记录的 TypeScript source-detachment 字面量；仅凭尾部不能归因所有失败。早先完整 npm 也未通过；本轮未修改扩展注册。
- 收口时本地控制台为 P7 idle，人工 SP80 L2 expired/saved、85 个动作。正常关闭 PID 69559 及 Make/uv 父进程；两份人工存档字节保持一致。无本轮遗留测试、promotion 或控制台进程。清理证据：`/tmp/p7-console-handoff-cleanup.json`。

## 当前判断

- 核心目标仍是 P7 自主过关。稳定认知应是一份逐步补全的中文玩法介绍，作为 WorldMap 的主要规划背景。假说补知识缺口；常识和高置信推断可先用于规划，再从正常动作反馈校正。不要要求每条假说专项动作验证。
- 控制台已验证过程观测、生命周期和独立人工操作。下一步先做操作者验收，再围绕 P7 实际决策、反馈和认识更新推进求解；这些界面证明不能代替自主能力评估。
- 人工试玩始终独立。它便于检视游戏，不为 P7 注入路线或学习记录。公开决策摘要不是私有思维链。

## 历史归档

- 同局人工/P7 接管、manual-first 主流程、全量假说刷屏和逐假说强制验证已撤回。
- 页面只存内存、重启从初始位置开始的旧边界，已被 `a50044d1` 替代。更新前没有持久记录的人工局不能恢复。
- 曾因仅按像素匹配丢失重复帧关联；现在按实际 source 序列/hash 绑定，不从历史 SDK 行号补造关联。
- 最初真实 console RPC 失败的原因是 systemd 丢失 Orb 已转换代理。`9e98b49e` 只保留 guest 固定代理变量名，成功恢复工具/模型运行。不要据泛化 RPC 错误改模型、凭据或 CA。诊断入口已删除，`.env` 与持久 Pi 配置未更改。
- 旧门禁封装曾污染 UV_BIN/Make 标志；最终检查清理了这些变量。旧污染结果不作为最终证据。

## 未完成边界

- 可恢复 P7 暂停未实现；结束是取消，不能称为暂停。可选人工历史导出仍是后续项。
- 本轮未证明新的自主 SP80 过关、持续 L1→L2→L3 求解、冷/热启动改善、跨关学习或模拟器收益。
- 全仓 promotion 与完整扩展门禁未通过，需单独缩小范围修复；本轮不扩成全框架审计。
- 原生浏览器视觉/点击和移动端验收未完成：缓存 browser runtime 模块不可用。未创建新浏览器 profile；DOM/SDK 测试不算视觉验收。

## 下一动作

1. 执行 `project-state resume`，读取 INDEX、CURRENT、此交接、最近 JOURNAL、MEMORY 和 Git。没有遗留运行要续接，也没有未提交实现。
2. 用 `make p7-console` 做操作者验收。上次题目/关卡及持久人工进度会恢复；原端口 53747 已关闭。检查动作按钮反馈、帧回看、切回存档、“清空并重新开始”和 RESET 的区别。历史画面先点击“返回当前画面”才能操作。
3. 用户继续授权后，将主线回到 P7：启动独立有限自主局，观察公开目标/依据/预期、真实动作及对应认知变化。P7 启动会关闭人工局并从独立 L1 开始。继续保留停止与 guest 清理的证据，不把人工轨迹当模型上下文。
4. 若用户优先处理门禁、可恢复暂停或人工导出，按既有三模式设计选择一个小范围任务；不要重做已交付控制台包或合并人工/P7 工作流。

关键路径：

- 设计/计划：`docs/superpowers/specs/2026-10-05-prime-p7-console-modes-design.md`、`docs/superpowers/plans/2026-10-05-prime-p7-live-console.md`。
- 完整证据/操作：`docs/status/ASTERION-PRIME-P7-EVIDENCE.md`、`docs/guides/prime-p7-games-and-official-results.md`；认识合同：`docs/architecture/prime-p7-cognition-and-experience.md`。
- 实现：`src/asterion/applications/prime/p7/console_{server,session,manual,manual_saves,preferences,events,snapshot,export}.py`、`console_assets/`；guest 收尾：`tools/run_prime_p7_guest.py`。
- 本地附加证据：`/tmp/p7-manual-save-{http,dom}-evidence.json`、`/tmp/p7-manual-restart-{http,dom}-evidence.json`。`/tmp` 不是永久存储；关键事实已写入上面的受版本控制证据文件。
