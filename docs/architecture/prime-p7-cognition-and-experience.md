# P7 游戏认知、通关经验与长考

## 目标

P7 每次运行都要增加可复用的认知，同时保持当前游戏的探索自由。记忆分成三层：

1. **类型认知**：按输入面和游戏行为类别汇总跨游戏先验，例如
   `keyboard`、`click`、`keyboard_click`。它只回答“应该观察什么、哪些动作形态可能存在”，不能提供坐标、路线或通关结论。
2. **具体游戏经验**：按精确的 `game_id + seed + win_levels` 持久化观察次数、当前动作数、已完成级别、已验证的最佳动作数和模型摘要。未到达目标级别的观察只更新当前进度，不会生成“最佳路线”。它保存进展和证据索引，不保存可直接执行的路线。
3. **当前关卡长考**：模型先读取类型认知、具体游戏经验、WorldMap、Playbook 和 retrodiction 状态，再决定是单步探测、提交机制假设，还是调用受证模型搜索。搜索结果每步都带当前前缀下的 frame/state/level 预期，仍需 `act_checked` 验证。

类型认知和具体游戏经验都会持续更新。只有目标级别完成后才写入最佳动作数；写入失败只影响学习缓存，不影响本轮合法探索。

## 持久化边界

`GameCognitionStore` 写入 `.asterion-private/prime-p7-live/cognition.json`，采用临时文件、`fsync`、原子替换和 `0700/0600` 权限。记录有大小和数量上限，不保存原始帧、提示词、凭据或路线。

类型档案的 `authority` 固定为 `prior-only`。同一类型档案可帮助模型选择信息增益较高的观察方式，但不能使旧坐标、旧动作序列或旧结论自动获得执行权。

具体游戏经验只有在当前游戏身份完全匹配后才显示。它仍然是进度记忆；旧机制或路线要进入执行路径，必须由当前前缀和当前历史重新验证。不同游戏的经验不会互相授予执行权。旧版未标记为 verified 的动作计数会在加载时作废，避免把未完成探测误当成成功经验。

## 执行权限原则

权限控制只守住会污染能力评估或造成不可验证批量执行的边界：

- 拒绝跨游戏、跨 seed、跨 `win_levels` 的路线复用；
- 拒绝 checked batch 中 identity、当前前缀、frame/state/level witness 不匹配的后续动作；
- 证据冲突时停止当前批次，返回原因并允许模型重新观察、单步探测和重规划。

以下操作不应被权限门阻断：

- 普通 `act` 单步或小批次探索；
- 当前画面产生的未知动作探测；
- 形成新机制假设前的观察和信息增益探测；
- 受证模型搜索本身；搜索只计算，不派发动作；
- checked batch 的第一步，只要其 witness 与当前状态匹配。

无效果保护是重试提示，不是全局禁止。连续相同动作无变化时，原始探索可显式请求一次有区分度的 probe；只有继续重复同一无信息动作才要求重规划。记忆读取和缓存故障也不能让正常推理停摆。

## 长考流程

长考不是无界等待，而是一个有预算、有停止条件的决策循环：

1. 读取 `p7_cognition`，区分类型先验和本游戏经验；
2. 读取 WorldMap、Playbook、`retrodiction_status` 和当前观察；
3. 形成候选机制或探测点，说明预期信息增益和失败后的下一步；
4. 若已有完整证书，调用 `p7_model_search` 做有界 BFS/A*；
5. 把返回的 checked plan 交给 `p7_act_checked`，在首个 mismatch/no-effect/terminal 处停批；
6. 将新观察和结果写回 WorldMap、Playbook、TransitionModel 以及本地 cognition store。

长考的输出是下一步决策和停止条件，不是绕过执行边界的路线注入。失败也会留下可复用的类型和游戏进度证据，避免下次从零开始。

## confirmed model 的形成保证

“有经验”必须能改变规划行为，单纯保存 `effects` 或 `candidates` 不算学会。
因此 broker 对每次新转移自动执行晋升检查，不要求模型先发现工具或手工提交假设：

1. 同一动作在相同游戏身份下形成一致的可编译候选；普通帧效果至少需要两次独立证据，
   关卡跃迁或终局效果有直接的结果证据，可以从一次跃迁记录开始；
2. `MechanismSpec` 在所引用的历史序列上重放，逐帧匹配 frame、state、level 和 changed-cell
   witness；
3. 通过后写入 WorldMap 的 confirmed mechanics，并产生 planner-eligible certificate；
4. 已有 confirmed model 时，broker 自动触发一次有界 `model_search`，结果仍必须经过
   `act_checked` 的 witness 校验；模型不需要自行记住“先调用搜索工具”。

证书有两个明确范围：

- `mechanism-retrodicted`：模型解释完整连续历史；
- `mechanism-evidence`：模型只解释列出的候选证据序列，其他探索动作保持 unknown。

第二种范围解决了“一个小机制必须解释所有无关探索动作才能被确认”的设计断点。它不是放宽
安全性：每个被列入的转移仍需完整帧重放通过，未覆盖动作不会获得任何执行权；当前帧变化后
搜索计划仍以最新 frame witness 为准，出现偏差立即停批。

跨级经验继续保留 level guard。它可以作为下一关的一次 probe prior，但只有在当前关卡出现
同样的证据后才晋升为当前关卡模型。这样游戏会越玩越熟，同时不会把一个关卡的偶然动作
误当成全局规则。

### 全局能力边界

上述闭环保证的是“可证明的局部经验会改变规划入口”，不是任意游戏都能自动得到完整的
人类式世界模型。当前确认模型必须同时满足三项条件：差分能被受限的声明式 effect vocabulary
表达、同一动作的上下文没有未建模的分叉、被选中的历史转移能逐帧重放。复杂的多对象同步运动、
边界进出、隐藏状态和同一动作的条件行为会保持为 hypothesis 或 conflict，并继续允许普通探索。

`TransitionModel` 仍是逐步历史账本；只有带 planner-eligible `ModelCertificate` 的
`MechanismSpec` 才能预测未见状态。`model_search` 是有界的规划查询，结果通过
`act_checked` 逐步核验；它不保证最短路线，也不强制模型一定选择搜索结果。离线回放路线、
Playbook checked route、模拟器搜索和普通探索目前是不同的候选来源，不能把任一来源的存在
误报为最终动作由确认模型产生。

因此实跑评估必须分别报告：候选是否形成、是否晋升为 confirmed model、是否触发模型搜索、
搜索结果是否被执行，以及最终动作是否仍来自普通探索。合成测试已覆盖完整晋升、搜索、执行和
Playbook 热启动；真实关卡仍需逐次提供这些运行证据，不能由单元测试替代。

运行评估必须区分“收集到了经验”和“经验改变了行为”。私有 run summary 记录
effect/candidate 数量、当前级别与过期候选、probe 提交及 pending 状态、证书是否
planner-eligible、模型搜索调用/命中、预测匹配/冲突和当前级别动作数。跨级候选只
能作为当前帧的 hypothesis probe，不能直接成为路线；只有 probe 通过并取得
retrodiction certificate，才算进入模拟器搜索。这样可以直接判断某次过关是否真的
复用了经验，而不是把前缀回放或离线路线误计为学习收益。

## 支持的输入类型

当前分类从实际 `available_actions` 推导：

- 只有 `ACTION1`–`ACTION5`/`ACTION7`：`keyboard`；
- 只有 `ACTION6`：`click`；
- 两者都有：`keyboard_click`；
- 没有可用动作：`unknown`。

`ACTION6` 的坐标仍必须来自当前证据或 checked witness。拖拽、按键保持等未来动作扩展需要新增明确的能力契约，不能从类型档案猜出来。
