# P7 通用游戏经验归纳与持久化设计

**日期：** 2026-10-01  
**状态：** 待实现  
**范围：** P7 纯能力运行中的通用游戏经验学习，不包含具体关卡路线注入

## 1. 目标

让 P7 在一次游戏运行中把动作结果转成可验证的游戏经验，并在同一精确游戏身份的后续级别或重做中复用：

```text
动作结果
  → ActionEffect
  → 机制候选
  → 游戏内模拟器预测与历史回放
  → 区分性探测及真实动作校验
  → confirmed fact / ModelCertificate
  → 有界模拟搜索 → checked plan
  → Playbook 持久化和下次重用
```

目标是学习“动作对对象和状态产生什么效果”，而不是保存一条未经解释的路线。键盘、点击和混合输入都必须通过同一抽象工作。

## 2. 当前缺口

现有代码已经具备：

- `ArcHistoryRecord` 的逐动作前后帧、状态、级别和 changed-cell 证据；
- `WorldModelStore` 的 mechanics/entities/relations/hypotheses 分层；
- `MechanismSpec`、单次 distinguishing probe、retrodiction 和 `ModelCertificate`；
- `Playbook` 的同题持久化和 checked route 证据。

现有代码缺少：

- 从动作结果自动提取结构化效果；
- 从重复效果自动形成受证机制候选；
- 自动选择信息增益最高的区分性探测；
- 从候选规则编译可运行的游戏状态转移模拟器，并用它比较未来落点；
- 将确认后的语义经验投影到下一次长考上下文。

因此不能要求模型自行记住每次调用候选和探测工具。

## 3. 术语与边界

### 3.1 观察证据

`ObservedTransitionTrace` 是当前运行的历史链，包含每个动作的：

- 精确 action name/data；
- before/after frame digest 与 state digest；
- changed cells 及是否截断；
- state、levels completed、action sequence；
- 当前游戏 identity 和 evidence references。

它描述发生过什么，不表示已经理解机制。

### 3.2 动作效果

`ActionEffect` 是从一条 `ObservedTransitionTrace` 派生的不可变记录：

- `action_family`：keyboard、click 或混合动作名；
- `action_features`：按键方向、点击位置相对候选组件的关系等；
- `delta_shape`：变化单元的连通组件、颜色替换、平移向量、边界变化；
- `outcome`：普通变化、无变化、级别推进、GAME_OVER；
- `evidence`：序列、frame/state digest 和 changed-cell 引用。

动作效果不能直接获得执行权限，坐标只保留为当前证据特征。

### 3.3 机制候选

`EffectHypothesis` 将多个 ActionEffect 归并为一个有界、声明式的 `MechanismSpec` 候选。候选必须携带：

- 精确游戏 identity；
- 依赖的 entity/relation keys；
- 支持它的 effect evidence 序列；
- 至少一个可区分当前候选与替代候选的 probe；
- `hypothesis`、`verified`、`contradicted` 或 `retired` 状态。

候选不得包含任意 Python、网络、文件或进程能力，也不得把一条坐标动作序列包装成机制。

## 4. 归纳算法

### 4.1 确定性 ActionEffect 提取

每次 settled transition 后立即执行，使用已有 frame/state/history 证据：

1. 计算 changed-cell 连通组件和颜色替换集合；
2. 计算相邻重复动作的相对位移、大小和方向；
3. 标记 no-effect、级别推进、状态变化和边界变化；
4. 将当前视觉候选作为 advisory entity references；
5. 写入有界的 effect history，超过上限按同题、同级、同动作族淘汰最旧诊断数据。

提取器不依赖具体游戏颜色、坐标或关卡编号。

### 4.2 候选生成

归纳器按 action family、当前级别、候选对象关系和 delta shape 分组。默认候选类型包括：

- 固定局部 cell edit；
- 对象或组件的平移；
- 重复动作的周期变化；
- 状态/级别转换；
- no-effect 与边界约束。

候选至少需要两条相互独立且一致的 effect evidence；一次性终点推进可以生成低置信度候选，但必须通过 probe 才能确认。无法用当前声明式 effect vocabulary 表示的隐藏库存、计时器和对象生命周期保留为 hypothesis，不得进入 planner。

### 4.3 区分性探测

探测调度器比较候选的预测差异，选择满足以下条件的一个动作：

- 当前 action whitelist 中可用；
- 目标和数据来自当前帧或已确认对象，不能来自旧路线；
- 至少两个候选对结果有不同预测；
- 预期结果包含可比较的 frame/state/changed-cell/level/state witness；
- 不违反 terminal、action-cap、no-effect 和 identity 边界。

每个候选最多有一个 pending probe。候选之间没有不同预测时，可选择一个候选预测明确、与真实历史尚未重复的验证动作；仍无有效探测则返回 `no-discriminating-probe`，继续普通单步探索，不阻塞运行。探测建议不会自行派发动作。

## 5. 验证与晋级

1. 归纳器提交候选和 probe，不直接派发动作；
2. P7 用现有 `act_checked` 执行单个 probe；
3. Broker 比较完整 after-frame、after-state、changed cells、level 和 state；
4. 完全匹配后重新对完整当前 history 做 retrodiction；
5. 通过后将依赖 facts、`world_model_version`、model digest 和 coverage 写入 `ModelCertificate`；
6. 机制、实体或关系 fact 晋级为 confirmed，并写入同题 Playbook；
7. 不匹配则将候选置为 contradicted/retired，保存冲突 evidence，清除 planner eligibility，允许重新归纳。

`TransitionModel` 在本设计中明确表示观察历史链；只有带 `ModelCertificate` 的 `MechanismSpec` 才是可预测模型。

## 6. 游戏内模拟器与长考搜索

模拟器是 P7 应用内的**纯计算游戏模型**，不调用真实 ARC 引擎、不消耗游戏动作、不读取离线优化器产生的路线。它与用于验证历史路线的离线 ARC replay oracle 分属不同路径。现有 `MechanismSpec.predict` 和 `model_search` 提供了 frame/state/level 预测及有界搜索基础；本节定义从自动归纳到可用模拟器之间仍须实现的合同。

### 6.1 状态与动作合同

模拟状态 `SimState` 至少包含：当前 settled frame、当前级别、SDK state、从当前帧识别且带证据的对象及关系、已确认的内部状态。状态从**本轮最新真实观察**初始化，不能用旧关卡帧、旧路线末状态或假设库存代替。尚未观察到的钥匙库存、计时器、隐藏对象等值标记为 `unknown`；若某条规则依赖未知值，就不能预测该动作。

输入动作与真实 SDK 一致：使用当前 `available_actions`；`ACTION6` 坐标只能由当前帧组件、已观察动作结果或确认对象生成；键盘动作保持原始动作名；RESET 仅在真实运行合同允许时列入候选。动作集合有界并记录候选来源，不能枚举整个点击网格或复用旧级坐标。

模拟器对单步返回 `predicted(next_state, changed_cells, rule_ids)`、`unknown(reason)` 或 `conflict(reason)`。只有被规则完整覆盖的 frame、对象/关系、level 和 SDK state 才能返回 `predicted`；不能把未建模区域默认设为“不变”以伪造完整预测。允许在探测排序时使用部分预测，但部分预测不能获得 `ModelCertificate` 或作为 checked route 的完整 witness。

### 6.2 模型合成与版本

归纳器从第 4 节的 ActionEffect 合成受限规则库，先支持局部 cell edit、组件平移、周期变化、边界无效、state/level 转换。规则使用相对对象/局部条件表达可迁移效果；不可解释的绝对坐标、单次过关序列和自由文本结论不能编译为规则。对象及关系若尚无可预测的更新语义，仍保持 advisory，不应假装模拟器已经完整支持它们。

一组 `MechanismSpec` 形成一个不可变模型版本，包含精确游戏身份、规则摘要、依赖的 confirmed fact keys、WorldMap 版本和证据覆盖范围。候选可有多个版本；冲突后旧版本标记 stale/retired，不继续参与搜索。模型更新不修改已经保存的历史证据。

### 6.3 历史回放与可信度

候选模型必须从每条真实历史记录的 **before** 状态逐条预测其 **after** 状态，比较动作数据、完整 frame、changed cells、level 和 SDK state。Frame digest 与 observation/state digest 使用不同的类型与字段；两者不可互填。历史存在截断或缺失关键证据时，模型状态为 `insufficient-evidence`，不能宣布 verified。

历史回放只证明已见转移的一致性，不能证明未来普适正确。因此签发 `ModelCertificate` 还要求至少一次由该候选事先提交的、未参与候选拟合的区分性探测与真实结果匹配。证书记载探测序列、模型摘要、连续历史覆盖区间和当前前缀摘要；若规则没有可用的区分性探测，保持 hypothesis。模型可以继续用于建议观察，但不得参与执行路线规划。

从 Playbook 加载的 confirmed 模型也要对本轮当前前缀重新回放并核对起点状态；仅凭旧证书不能获得本轮 planner 权限。新动作与模拟预测矛盾时立即使该证书 stale，记录首个反例并返回真实观察给 P7 重规划。

### 6.4 有界反事实搜索

长考在证书有效时，从最新真实 `SimState` 搜索候选动作序列。使用现有有界 BFS/A* 框架；每个节点只扩展模拟器完整预测的动作，跳过 `unknown`/`conflict`、GAME_OVER 和重复状态。节点数、深度和耗时都有限；允许取消。搜索目标是预测中的真实 level/state 推进，不能用视觉相似度自行宣称通关。

返回值区分 `found`、`no-plan`、`budget-exhausted`、`model-unavailable` 和 `model-conflict`。`no-plan` 只表示当前模型与预算未找到路线。每个 found 步骤附带动作、起点摘要、预测 after-frame/after-state、changed cells、level、SDK state、模型证书摘要。P7 可审阅/缩短候选，但任何执行仍须逐步调用 `act_checked`；首个 witness 不匹配就停止剩余计划。模拟搜索不会自动派发，也不会把离线 ARC oracle 找到的精确路线装入纯 P7。

### 6.5 适用性与退出条件

每次决策先检查模型是否能解释当前状态和至少一个有信息量的动作。若对象识别不稳定、规则依赖未知隐藏状态、多个候选不可区分、模拟搜索耗尽预算，或模型规划比直接观察更耗时，P7 回到普通单步探索。这个绕过不清空已有证据；后续新动作可以继续修复模型。模拟器是否有用以**减少无信息探测和后续同题重学成本**衡量，而不是以“调用过搜索工具”衡量。

## 7. 持久化和上下文投影

### 7.1 同题 Playbook

持久化以下内容：

- confirmed mechanics/entities/relations；
- advisory/stale 视觉候选及证据摘要；
- effect summaries 和候选状态；
- verified model digest、规则版本、证书覆盖、探测证据和冲突分支；
- checked route 作为回放证据，独立于机制经验。

加载时要求 `game_id + seed + win_levels` 完全匹配。视觉候选恢复为 advisory/stale，必须用当前级别的新证据重新激活；confirmed mechanics 也必须对当前前缀重新回放后才能 planner-eligible。

### 7.2 类型 cognition

`keyboard`、`click`、`keyboard_click` 只保存跨游戏输入/观察先验，权限固定为 `prior-only`。它不保存坐标、路线或关卡结论。

### 7.3 模型提示

提示中同时提供：

- 当前 effect summaries；
- 候选机制及支持证据；
- pending probe 和预期信息增益；
- confirmed facts、certificate 状态和冲突原因。
- 当前模拟器的解释覆盖范围、unknown 原因、搜索预算与可绕过状态。

提示不得直接注入纯 P7 禁止使用的 exact offline route。

## 8. 权限和失败处理

- 候选生成、effect 读取和模型搜索是计算操作，不派发动作；
- 内部模拟器只能读取本轮证据和同题 Playbook，不得调用真实 ARC 引擎；离线 ARC replay oracle 仅用于隔离的诊断/集成验证；
- 只有 `act_checked` 能消耗 action slot；
- identity、当前 prefix、frame/state/level witness 不匹配时停止当前批次；
- 普通单步探索和 probe 失败不被全局权限阻断；
- cache/Playbook 写入失败只记录诊断，不阻塞合法动作；
- 冲突事实不得继续作为 active planner input；
- exact route、candidate actions 和 route adoption 继续属于 integration replay，不进入 pure capability run。

## 9. 实现拆分

1. 新增有界 `experience_induction.py`：ActionEffect、EffectHypothesis、归并和 probe ranking；
2. Broker 在 `_record_world_evidence` 后生成 effect/candidate projection；
3. 让候选规则编译为现有 `MechanismSpec` 的受限子集，并建立 `SimState`、unknown/partial-prediction 合同；不支持的对象生命周期保持 unknown；
4. 增加候选模型的逐历史 retrodiction、拟合外 probe、证书版本与失效逻辑；
5. 扩展 `model_search` 的证书/当前起点检查、完整 witness、节点/深度/时间预算及失败状态；
6. 增加 P7 只读工具展示 candidates/effects/probe plan/模拟器覆盖和搜索结果，保留现有 hypothesis/probe 验证入口；
7. 扩展 Playbook schema 保存 candidate/effect/retired evidence 与模型证书，完善同题 rehydration；
8. 将 frame/state digest 字段强类型化，避免 prediction mismatch 污染语义学习；
9. 维持 pure/integration 模式隔离，禁止 route hint 进入能力评估。

## 10. 验证计划

### 合成测试

- keyboard、click、keyboard_click 三类 ActionEffect 提取；
- 重复动作的 delta 归并和候选生成；
- 两个候选的 probe ranking；
- `SimState` 从最新观察建立，未知隐藏值保持 unknown；
- keyboard/click/mixed 规则编译、预测、unknown/conflict 和多步搜索；
- 拟合历史成功但拟合外探测失败时不得发证；旧证书重载后须验证当前前缀；
- 搜索返回带模型证书和每步完整 witness 的计划，首个真实反例停止后续动作；
- 搜索节点/深度/时间上限与取消，以及无模型时正常回退单步探索；
- frame/state/changed-cell/level/state 全字段匹配才晋级；
- mismatch、no-effect、GAME_OVER、冲突和过期候选安全失败；
- Playbook 保存、加载、stale rehydration 和 identity 隔离；
- 不产生 route injection 或 action dispatch。

### 纯 P7 实战评估

每次只报告当前关卡步数：

1. 运行纯 P7，确认没有 offline optimization、route hint 或 candidate action；
2. 观察 effect/candidate/probe/confirmed、证书覆盖、模拟器 `unknown`/conflict、搜索节点及 worker trace；
3. 完成后重做同一 identity 或推进下一低级别；
4. 比较无信息动作数、探测次数、confirmed facts 和当前关卡步数；
5. 连续三次失败或出现通用机制缺陷时停止，先修复再继续。

成功标准不是“某一关碰巧过关”，而是至少有一条通用、回放验证的语义经验在后续同题运行中被读取并减少重复探索。

## 11. 非目标

- 不针对 BP35、VC33、SP80 编写规则；
- 不把离线搜索路线注入 pure P7；
- 不承诺候选机制一定能解释任意 ARC 游戏；
- 不把 TransitionModel 历史链误称为已学会的世界模型；
- 不在没有证据时把视觉常识升级为 confirmed fact。
