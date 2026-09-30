# Live Session Checkpoint

> Updated: 2026-10-01 09:20. **Session remains active — not a final handoff.**

## 已验证事实

- `b37121be` 修复 P7 续推理的动作白名单漂移：每次续推理先刷新 `available_actions`；`p7_act_checked` 顶层返回 `available_actions` 与 `invalid_action`。
- 修复前 VC33 L2 运行 `p7-live-20260930054039-85d4a123e7fc09e7e57a5904` 在首轮预测失败后反复构造 `ACTION1–ACTION7`，最终被取消；摘要记录 `retrodiction_status=conflict`、7 次 prediction mismatch。
- 修复后纯 P7 VC33 L2 重跑 `p7-live-20260930060858-fd59b7d7a32f682b92e51468` 曾被错误历史路线源压成当前 7 步；该记录不能作为正式 L2 baseline 或能力结果。
- VC33 L2 正式 baseline 为 **18 步**，worldmap 接入前纯 P7 已有 **14 步通关**证据；该历史能力结果不能被当前回归覆盖。
- `p7-live-20260930062144-db789f549f958e74a8bd0509` 按 L2 baseline 18、L1 前缀 3 计算总上限 21；运行超过 30 分钟后停止，完成 L1、L2 未完成，模型后续多次猜测非法 ACTION1/2/3，未执行。
- 根因已定位并修复为 `8c58db5e` 引入的提示回归：删除固定 ACTION1-7 语义，要求模型从仅含名字的 `available_actions` 自行推断；`0f33947c` 恢复通用固定动作契约，worldmap 工具保留。
- 修复后重跑 `p7-live-20260930065824-a70c98390eca57b41fc5dc85` 验证到 L2 第 1 步：模型重复 L1 坐标 `(61,33)` 后转入无效探测，未产生最终 summary；这是未确认跨级视觉候选的隔离问题，不能宣称能力已恢复。
- 修复后动作全为当前白名单 `ACTION6`，没有再出现非法 `ACTION1–ACTION7`；模型尝试 `(61,33)`、`(28,41)`、`(9,54)`、`(11,54)`、`(29,42)`、`(8,52)`，未形成 L2 过关。
- 修复后 P7 回归测试 174 项通过，`make lint` 通过。
- `6e537239` 增加通用前缀坐标保护：当前级别复用前级 ACTION6 坐标且没有当前帧 cell/frame 证据时，Broker 不派发并返回 `prefix-action-reuse`；130 项 native/live 回归与 lint 通过。
- VC33 L2 纯 P7 重跑 `p7-live-20260930074625-ef0bc3c614461a31088ed5c7`：L1 3 步完成；L2 当前步数 9（总 primitive 12），动作坐标为 `(0,0),(32,32),(16,16),(32,16),(32,48),(16,32),(48,32),(32,32)`；未复用 `(61,33)`，未通关，因长时间推理手动取消。
- 来源澄清：上述 L1 3 步是已验证前缀回放，不是本轮纯 P7 重新解题；L2 退化与本轮 IPython 分析工具失败同时出现。
- `1d536fc9` 修复 Pi tool call ID 含 `|` 时 IPython 桥接拒绝请求的问题；旧 transcript 中 `print('test')` 失败、worker_cell_count=0，说明模型分析代码未执行。

## 当前判断

- 动作接口与续推理的非法动作循环已修复；本次仍失败不再归因于动作名漂移。
- WorldMap/Playbook 已被读取，但本轮结束时 confirmed mechanics/entities/relations 仍为 0；模型执行分散点击，未从候选稀有对象建立可验证通用点击机制。
- 纯 P7 VC33 L2 尚未证明可独立过关；历史 7 步 L2 路线仍属于路线证据，不得当作能力结果。

## 历史归档

- 离线优化默认关闭；精确候选路线不得注入能力运行。
- 修复前的长重试运行已停止并保留原始证据，不再等待同类无效循环。

## 未完成边界

- 尚未完成通用机制：如何把视觉候选（稀有颜色/组件/重复变化）转成有信息增益的 `ACTION6` 探测点与次数策略。
- 尚未重新验证同一题内持久化 WorldMap 在 L2 中能否产生 confirmed 关系。

## 下一动作

1. 用 `1d536fc9` 重建 P7 wheel，重跑纯 P7 VC33 L2，确认 IPython `worker_cell_count` 大于 0，并观察世界模型是否开始产生 confirmed facts。
2. 再重跑纯 P7 VC33 L2；不得启用 `ASTERION_PRIME_P7_OFFLINE_OPTIMIZATION`，按当前 L2 步数报告，不混淆总动作数。
