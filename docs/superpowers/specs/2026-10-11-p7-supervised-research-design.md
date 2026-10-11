# P7 supervised research design

用户已确认2026-10-11设计：监督研究由外围监测和停止，自动运行保留有限总预算。

## 合同

新增显式 `research` 运行模式和 `make asterion-prime-p7-research GAME=<alias> LEVEL=<target>`。默认目标全游戏，不加载已保存路线；经验规则仍遵循现有显式/独立root选择。模式授权来自operator入口，不来自模型、manifest、缓存或deadline缺失。旧solve/witness/autonomy/sweep/official保持原授权。

监督模式总model/tool callbacks、总deadline和总action cap为None，计量连续累积，RESET/续轮/暂停不重置计量。Prime复用AsterionPrimeLimits(None,None,None)，不新增runner或领域分支。P7GameSelection新增supervised_research:bool，True时action_cap为None，不能与action_cap_override混用；ArcGameContract保持有限。动作批次保留独立有限上限、逐动作取消检查、已知/未知effect阻断。nullable字段只扩展P7领域合同和相应读取器，不改通用四个闭合协议。

去掉P7 research/control所有隐含总期限；单次kernel/工具/SDK传输/输出容量上限保留。停止后不授予新研究工作；既有已派发事务按结果结算。guest独立cgroup无限总时长、180秒有界退出宽限，最终检查cgroup空；清理与结算在停止时获得有限窗口，不因无总deadline变成无限。

监测为内容安全的 `research-status.json`：mode、run_id、起点/更新时间、elapsed、model/tool callbacks、input/output tokens、primitive actions、RESET、levels、running/settling/closed、stop_requested、cleanup_complete。无可靠费用来源不输出猜测付款；包含机密的原始prompt/答案/认证/路径不进入监测。私有原始证据与公开安全计量分离。终止的最终summary仍保留既有合同，不将active失败改写成WIN。

## 验证

先失败用例再实现：监督回调超过128继续；动作超过旧cap继续；无隐藏一小时期限；有限模式保持拒绝；逐动作取消、未知effect和有限batch；private trace与SDK replay接受明确监督模式。相关unittest、lint/docs与promotion；不启动新BP35或新付费试验。部署能力不由provider-free验证推断。
