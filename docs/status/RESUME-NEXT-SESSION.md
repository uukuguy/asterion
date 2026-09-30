# Live Session Checkpoint

> Updated: 2026-10-01 01:55 (Asia/Shanghai). **Session remains active — not a final handoff.**

## 最新现场验证（2026-10-01）

- 纯 P7 `SP80` L2 推进 run `p7-live-20260930191902-d0ad69f1eb7e640c51d6d3ca` 使用同一 6 步 L1 replay 前缀、`gpt-6.1-sol`、`offline_optimization_enabled=false`；L2 实际执行到 **46 步**（总 primitive 52，含 1 次 RESET），`levels_completed=1`，未通关。因超过 10 分钟仍未完成而停止；`sealed_trace=true`、`replay_verified=true`、`cleanup_complete=true`，分类为 `external_cancel`，无运行时错误。Experience snapshot 持久化 `effects=50`、`candidates=13`，但 `confirmed=0`、simulator=`absent`，并记录 6 次 `act_checked_output_too_large`、多次 prediction mismatch；这证明经验采集/持久化生效，但当前候选仍无法升级为可搜索机制。

- 纯 P7 `SP80` L1（实际别名 `sp80`）运行 `p7-live-20260930174531-72d55dc672bc34f8481c3f8a` 已通过：当前关卡 **6 步**，`levels_completed=1`，`replay_verified=true`、`sealed_trace=true`、`cleanup_complete=true`；模型为 `gpt-6.1-sol`，`offline_optimization_enabled=false`，没有路线注入。
- 运行期间可观察到 13 个 worker cell、逐次 `status/history` 和动作后的 changed-cell 证据；`ACTION4` 连续动作各产生 34 个变化单元，后续 `ACTION1` 产生 163/2 个变化单元，说明决策输入与动作结果可在运行中追踪。
- `world_model_version=22`，最终 `confirmed` mechanics/entities/relations 仍为 0/0/0，hypotheses=12；因此本次只能证明 worldmap 被读取、更新和保存，不能证明已形成可复用机制。
- 诊断记录 3 次 `prediction-mismatch`，以及一次 `act_checked_output_too_large` 告警；实际动作仍成功完成，`pi_rpc_private.error_events=[]`、returncode=0。后续要检查预测证据填充和大输出降级是否进一步影响长推理。
- 现场发现认知快照把历史最佳步数写入 `primitive_actions`，在运行中可能把 1 步误读为当前进度 6 步。已新增 `current_primitive_actions` 并用回归测试固定语义；`primitive_actions` 继续表示历史最佳值。
- 同一现场还暴露成功摘要把 `failure=null` 分类为 `application_failure`；已补成功分支并固定为 `category=none`，旧 SP80 摘要保留为修复前证据。
- 进一步审计确认旧 cognition 的 `primitive_actions=1` 来自未通关中间观察，不是成功路线；现改为仅目标级别完成后写入，并在加载旧 v1 记录时清除未 verified 的最佳步数。

## 已验证事实

- 新增 `GameCognitionStore`：按 `keyboard`、`click`、`keyboard_click`、`unknown` 汇总类型先验，并按精确 `game_id + seed + win_levels` 持久化游戏经验；通过 `p7_cognition()` / `p7_client.cognition()` 只读暴露。
- 类型认知固定为 `prior-only`，经验不含可执行路线；Broker 每次绑定历史和动作后持续更新缓存，缓存异常不会阻断探索。
- 执行权限边界已收窄为身份/当前前缀/checked witness 不匹配才停批；普通探索、单步 probe、受证模型搜索都保持可用。设计见 `docs/architecture/prime-p7-cognition-and-experience.md`。
- 认知持久化与 Broker 集成测试通过；定向 P7 回归 147 项通过，`make lint` 通过。

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
- 新增 `model_search.py`：只接受已由当前历史完整 retrodict 的 `MechanismSpec`，执行有界 BFS/A*，返回每步 frame hash/level/state 预期；不会自动派发动作。
- `ArcBroker.model_search()`、P7 operator、worker bridge、live RPC 和 prompt 已接入 `p7_model_search()`；`retrodiction_status()` 增加 planner `absent/hypothesis/verified/stale` 与证书摘要。
- 已验证：3 个 simulator 单元测试、certified broker search、139 项 native/live/bridge/model-search 回归通过；`compileall` 通过。尚未跑完整 `make check`。
- 正式设计在 `docs/architecture/prime-p7-world-model-simulator.md`，明确 WorldMap 三层记忆、模型生命周期、Tycho/Retrodict 采纳边界和当前限制。

## 当前判断

- 动作接口与续推理的非法动作循环已修复；本次仍失败不再归因于动作名漂移。
- WorldMap/Playbook 已被读取，但本轮结束时 confirmed mechanics/entities/relations 仍为 0；模型执行分散点击，未从候选稀有对象建立可验证通用点击机制。
- 纯 P7 VC33 L2 尚未证明可独立过关；历史 7 步 L2 路线仍属于路线证据，不得当作能力结果。
- SP80 L1 的一次通过不足以证明长期学习生效；必须在同一精确 identity 的后续重做或下一等级中比较探测数量、确认事实和步数，才能评估持久化经验是否改变行为。

## 历史归档

- 离线优化默认关闭；精确候选路线不得注入能力运行。
- 修复前的长重试运行已停止并保留原始证据，不再等待同类无效循环。

## 未完成边界

- 尚未完成通用机制：如何把视觉候选（稀有颜色/组件/重复变化）转成有信息增益的 `ACTION6` 探测点与次数策略。
- 尚未重新验证同一题内持久化 WorldMap 在 L2 中能否产生 confirmed 关系。
- 尚未进行 live 能力验证：需要一次纯 P7 运行观察 GPT-6.1-Sol 是否主动提交机制假设、得到 verified planner 状态并使用 `p7_model_search`；不得注入离线路线。
- 尚未完成同一游戏的二次重做对照；当前 cognition 快照没有可执行路线，只有类型先验与进度摘要。

## 下一动作

1. 提交并验证 `current_primitive_actions` 修复，保持纯 P7 运行默认关闭离线优化。
2. 在同一精确 identity 上重做一个低级关卡或推进 SP80 L2，比较持久化 cognition/worldmap 是否减少无信息探测；按当前关卡步数报告，不混淆总动作数。
3. 若仍出现预测不匹配，优先修复通用 frame/state 证据映射；若 3 个连续关卡失败或出现明确机制缺陷，停止扩展并先修复机制。
