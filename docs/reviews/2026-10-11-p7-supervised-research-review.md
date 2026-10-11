# P7 监督研究实现与验证

## 代码结论

设计由用户确认，代码范围 `d77d9def..76b9b9a0` 独立Astra复审 APPROVE，无阻断项。测试定位修正30c454cf也独立APPROVE，未放宽有限断言。新增 `make asterion-prime-p7-research GAME=bp35 [LEVEL=9]`，默认完整游戏；模式由operator显式授权。

Prime复用既有执行器及all-None总量合同；通用层仅在runtime_observation增加无正文model/tool计数。P7显式supervised_research使action_cap/actions_remaining为None，并去掉监督模式隐含1小时控制期限。总模型/工具调用、动作、时长不自动停止；计量仍累积。有限自动预设、官方合同和历史sweep行为保留。

单批次64动作（既有checked plan20动作）、单次计算/传输/输出限额、逐动作取消、未知效果阻断继续有效。停止时创建固定180秒结算窗口，不刷新任务授权；guest无RuntimeMax，保持180秒退出宽限、最终cgroup检查和外围退出清理。

## 已验证边界

- Domain：136项focused测试通过，22项overlap/followup通过；验证旧动作限额跨越、5001动作显式来源重放、有限模式、取消、未知效果和finitebatch。
- Entry/guest/control：52项检查中1项既有External-limited跳过，其余通过；127项runtime/live/autonomy回归通过。fallback WIN修复先失败后通过14项相关检查。
- Prime owner统计：`uv run python -m unittest tests.test_prime_application_entry`，35项通过。run-story：31项通过；research runtime/context：19项通过。数字有重叠，不能相加为唯一测试总量。
- 既有真实协议fixture支持129轮RPC继续及513模型/工具事件；有限128模式拒绝下一轮。无模型mockNative进程不是实际提供商能力证明。
- 实际Ubuntu guest无模型停止探针：等待进程的RuntimeMax为infinity、TimeoutStop为3min；SIGTERM后launcher退出130，cleanup_complete=true，unit not-found/inactive、MainPID0、ControlGroup空。证据 `.asterion-private/p7-supervised-cgroup-probe-result.json`，provider_operations=0。
- 监测 `research-status.json`每秒安全更新，记录mode/run_id/time/callbacks/tokens/actions/RESET/levels/phase/stop/cleanup；通过sentinel正文排除、跨128回调与旧总期限、原子投影检查。没有可信费用来源时不伪造付款。

## 打包验证

最终30c454cf源代码 `make promotion-check` full PASS：25命令、provider_operations=0、full_dataset=no，覆盖独立复制、全量Python、安装wheel及资源、TS和Rust检查。未将初次运行或旧版本打包结果作为最终版本PASS。首次full检查4582项中3fail/1error，原因是既有测试用固定Make分组目标行定位recipe，新增research使该定位失效。30c454cf仅更新两处定位文本；root重跑69项相关检查PASS。最终代码lint、docs-check317文件/240链接通过。

## 未完成边界

本轮没有启动任何新的BP35或真实模型试验，不证明九关冷完成或解题收益。此前5/9失败运行维持原封存。

专用手工trace-race/animation recovery执行工具仍不支持监督模式，当前会拒绝且不隐式重标为有限模式；原始证据、普通已验证前缀读取及执行期kernel恢复按各自边界保留。资源监测为观察信息，不赋予动作或恢复授权。
