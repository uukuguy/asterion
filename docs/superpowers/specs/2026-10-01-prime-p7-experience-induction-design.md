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
  → 区分性探测
  → act_checked 回放验证
  → confirmed fact / ModelCertificate
  → Playbook 持久化
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

每个候选最多有一个 pending probe。没有区分性探测时返回 `no-discriminating-probe`，继续普通单步探索，不阻塞运行。

## 5. 验证与晋级

1. 归纳器提交候选和 probe，不直接派发动作；
2. P7 用现有 `act_checked` 执行单个 probe；
3. Broker 比较完整 after-frame、after-state、changed cells、level 和 state；
4. 完全匹配后重新对完整当前 history 做 retrodiction；
5. 通过后将依赖 facts、`world_model_version`、model digest 和 coverage 写入 `ModelCertificate`；
6. 机制、实体或关系 fact 晋级为 confirmed，并写入同题 Playbook；
7. 不匹配则将候选置为 contradicted/retired，保存冲突 evidence，清除 planner eligibility，允许重新归纳。

`TransitionModel` 在本设计中明确表示观察历史链；只有带 `ModelCertificate` 的 `MechanismSpec` 才是可预测模型。

## 6. 持久化和上下文投影

### 6.1 同题 Playbook

持久化以下内容：

- confirmed mechanics/entities/relations；
- advisory/stale 视觉候选及证据摘要；
- effect summaries 和候选状态；
- verified model digest、coverage 和冲突分支；
- checked route 作为回放证据，独立于机制经验。

加载时要求 `game_id + seed + win_levels` 完全匹配。视觉候选恢复为 advisory/stale，必须用当前级别的新证据重新激活；confirmed mechanics 也必须对当前前缀重新回放后才能 planner-eligible。

### 6.2 类型 cognition

`keyboard`、`click`、`keyboard_click` 只保存跨游戏输入/观察先验，权限固定为 `prior-only`。它不保存坐标、路线或关卡结论。

### 6.3 模型提示

提示中同时提供：

- 当前 effect summaries；
- 候选机制及支持证据；
- pending probe 和预期信息增益；
- confirmed facts、certificate 状态和冲突原因。

提示不得直接注入纯 P7 禁止使用的 exact offline route。

## 7. 权限和失败处理

- 候选生成、effect 读取和模型搜索是计算操作，不派发动作；
- 只有 `act_checked` 能消耗 action slot；
- identity、当前 prefix、frame/state/level witness 不匹配时停止当前批次；
- 普通单步探索和 probe 失败不被全局权限阻断；
- cache/Playbook 写入失败只记录诊断，不阻塞合法动作；
- 冲突事实不得继续作为 active planner input；
- exact route、candidate actions 和 route adoption 继续属于 integration replay，不进入 pure capability run。

## 8. 实现拆分

1. 新增有界 `experience_induction.py`：ActionEffect、EffectHypothesis、归并和 probe ranking；
2. Broker 在 `_record_world_evidence` 后生成 effect/candidate projection；
3. 增加 P7 只读工具展示 candidates/effects/probe plan，保留现有 hypothesis/probe 验证入口；
4. 扩展 Playbook schema 保存 candidate/effect/retired evidence；
5. 完善 WorldModel rehydration，使 advisory candidates 可在当前级别重新激活；
6. 将 frame/state digest 字段强类型化，避免 prediction mismatch 污染语义学习；
7. 维持 pure/integration 模式隔离，禁止 route hint 进入能力评估。

## 9. 验证计划

### 合成测试

- keyboard、click、keyboard_click 三类 ActionEffect 提取；
- 重复动作的 delta 归并和候选生成；
- 两个候选的 probe ranking；
- frame/state/changed-cell/level/state 全字段匹配才晋级；
- mismatch、no-effect、GAME_OVER、冲突和过期候选安全失败；
- Playbook 保存、加载、stale rehydration 和 identity 隔离；
- 不产生 route injection 或 action dispatch。

### 纯 P7 实战评估

每次只报告当前关卡步数：

1. 运行纯 P7，确认没有 offline optimization、route hint 或 candidate action；
2. 观察 effect/candidate/probe/confirmed 计数和 worker trace；
3. 完成后重做同一 identity 或推进下一低级别；
4. 比较无信息动作数、探测次数、confirmed facts 和当前关卡步数；
5. 连续三次失败或出现通用机制缺陷时停止，先修复再继续。

成功标准不是“某一关碰巧过关”，而是至少有一条通用、回放验证的语义经验在后续同题运行中被读取并减少重复探索。

## 10. 非目标

- 不针对 BP35、VC33、SP80 编写规则；
- 不把离线搜索路线注入 pure P7；
- 不承诺候选机制一定能解释任意 ARC 游戏；
- 不把 TransitionModel 历史链误称为已学会的世界模型；
- 不在没有证据时把视觉常识升级为 confirmed fact。
