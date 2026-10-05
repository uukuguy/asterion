# P7 游戏经验认知主合同

状态：2026-10-02 批准的历史认知合同，保留给显式 legacy/cognition 路径。2026-10-05 起，默认求解器以[WorldMap/Prime 重设计](../superpowers/specs/2026-10-05-p7-worldmap-solver-redesign.md)及 D-2026-10-05-01 为主合同；本文的固定认知模式、共享记忆和 DSL 门槛不约束新的默认研究路径。实现完成与真实能力验证仍须分别记录。

## 1. 目标与范围

从完全不了解一个游戏开始，像人一样看画面、提出玩法假说、选择能区分假说的动作、观察结果、修正认识。一次 L1 探索后必须能用语言回答：这是什么游戏、哪些对象可能是玩家/地板/墙/坑/目标、ACTION 各代表什么、如何算成功、哪些已经证实/证伪/尚不确定、下一次准备验证什么。

再次玩同一 L1 必须加载前次认识，记录哪些知识改变了本次实验或策略。当前验收限同游戏同 seed 同 L1，不要求跨关泛化。旧成功路线、历史坐标序列、RESET 前的试错不能伪装成“新学会的经验”或从官方动作记录中删去。

## 2. 两条执行管道

```text
认知探索：新本地会话 → 加载语义账本 → 看图/提出假说 → 选实验
                       ↑                       ↓
                 认知图景 ← 证据分析 ← 执行一步/短实验
                       ↓
                 RESET 清理 → 下一实验
                       ↓ 足以尝试即可进入通关测试
通关测试：加载已有认知 → worldmap 背景规划 → 实际反馈
                                      ↓         ↑
                         新疑问/反例 → 写入假说/验证 → 继续规划
```

探索不受人类 baseline 或官方得分步数限制，也不使用官方 session 做试验。它仍有独立有限的运行时长、每 episode 动作数、RESET 数和输出大小限制；限制到达是 `stopped`，不能冒充认知就绪。预算是应用预置，不要求用户配置模型/成本参数。

通关测试保持现有动作记账、封存、replay 和 cleanup；认知更新可以在通关反馈需要时回写同一精确游戏账本，但不进入最佳路线/排行榜成功结果。已有一个可用的游戏特定假说即可尝试通关，不必先穷尽所有对象和规则。首次实现以本地 L1 为入口，探索中意外过关也必须生成认知报告，不将通关自动等同于理解游戏。再次探索创建全新引擎实例重新开始 L1。

## 3. 组件职责

| 组件 | 职责 | 边界 |
| --- | --- | --- |
| LLM 认知者 | 根据画面、语言常识和当前图景提出游戏类型、对象、控制、规则、目标、策略假说；解释实验选择和结果 | 不能凭自述宣布已证实，不能注入旧路线 |
| SemanticCognitionStore | 精确身份下的语义主账本、证据索引、三态、语言报告与原子落盘 | 不保存可执行路线、不授予执行权 |
| CognitionSession | episode 状态机、实验预注册、动作绑定、结果评估、事件、就绪与停止、RESET 清理 | 程序依据实际前后观察计算证据，不接受伪造转移 |
| ArcBroker | 唯一真实动作入口，核对当前帧和实验动作，产生权威证据 | 始终保留完整实际动作历史 |
| WorldMap / 模拟器 | 当前对象定位、条件/效果候选、区分实验和短计划的辅助计算 | 未覆盖结果必须 unknown；模拟预测不是实测证据 |
| Operator / Prime 工具 | 提供独立模式、注入画面及图景、持久化事件/报告、跨会话重新加载、封存与清理 | 通用框架不依赖 P7，也不读模型配置 |

## 4. 语义主账本

schema 为 `asterion.prime.p7-semantic-cognition/v1`；精确作用域为 `game_id + seed + win_levels + level`，内部 L1 的 level 为 0。每条假说包含稳定 id、kind、subject、claim、reason、falsifier、next_test、可选适用 context、可选 ASCII `hypothesis_group`、status 及程序绑定的证据索引。kind 为 `game_type / object_role / control / success_condition / rule / strategy`；status 为 `undetermined / certain / falsified`。

每个 cognition episode 的首个 `start_episode` 幂等写入三条基础未定假说：初始画面的语义尚未识别、离散动作的含义尚未识别、题目成功条件尚未识别。它们可以带 0 到 1 的非权威 `confidence` 以排序注意力（其中部分启动假说可有较高先验置信度），但 confidence 永远不能把 status 变成 `certain`，也不授予执行权；基础账本不保存路线或坐标。

认知报告按游戏类型、动作控制、画面物件表示、规则/目标和策略分层。`undetermined` 表示尚未获得程序绑定的确定证据，不表示不能用于推理；高置信未定假说可以作为工作模型指导下一步规划。动作验证应优先选择能打开一片认知的关键假说，而不是为每条假说分配一个动作。报告中的 `coverage`、`guidance` 和 `cognition_layers` 只读地说明当前全景与关键探针候选。

`hypothesis_review` 会检视语义重复、同类型/同对象候选和显式 `hypothesis_group` 互斥候选；它只提供压缩线索，保留各假说及其证据，不自动删除、合并或把互斥标记当成结论。

普通 `report()` 返回按认知类型限额的当前工作集，优先保留有证据或高置信的代表项；同类历史项仍留在账本和 review 索引中。需要审计完整记录时使用 `full_report()`，不会把历史堆直接注入每轮规划上下文。

其中 `confirmed_knowledge` 是从程序绑定证据生成的固定游戏认识层：它描述当前已确认的动作、对象、规则和目标，是 WorldMap/规划背景的一部分。P7 应直接用它展开过关路线；只有新观察形成反例时才重新打开对应认识，不能因为仍有开放假说就重复验证已确认控制。

控制台和模型收到的中文认知叙事以“稳定游戏认知（规划背景）”为主视图，按游戏类型、画面物件、动作操作、规则和过关条件分类展示；动作后的画面变化与认知更新紧随其后。规划投影的 `semantic_cognition.stable_game_description_zh` 是 P7 的主要 WorldMap 文字背景，`confirmed_knowledge` 仍保留逐条确定事实，完整证据保留在私有 JSONL 与查询报告中。描述和新假说使用短句、主动语态、一个句子表达一个事实，并用统一名称表示同一对象；这达到 ASD-STE100 的简化目标。探索假说只显示活动数量、置信度摘要、关键未决问题和少量规划建议，避免假说列表遮蔽已经确定的游戏认识。

LLM 只能新建待定假说。certain 的含义是“在记录的条件和实验范围内获得实测支持”，不声称普遍真理。视觉类比可以长期待定；例如“像迷宫”不需要为了就绪强制变成确定。反例保留，不能删除原反例后把同一 id 复活；修改适用条件必须新 id。协议成功（levels_completed / WIN）和题目成功条件（如何操作会获胜）分开，协议已知不能自动确认题目目标。

落盘只保存语言认知、状态和证据索引，原始画面、坐标及动作序列属于独立私有实验记录。所有加载的认知固定 `execution_authority=none`。语言 certainty 不等于模拟器证书。持久化必须原子写入、有限大小；写入失败不能对外声称更新成功。实验过程每个变化都发出图景，报告是账本的投影，不是第二个真相来源。

## 5. 实验与证据

每个实验必须在动作前声明：待检验 claim ids、自然语言问题、为什么比其他动作更有信息、当前可执行的动作/短序列、预期支持结果、预期反例，以及适用条件。程序将实验绑定到当前 run、episode、frame 和动作顺序。每次只执行一步并核对结果；计划遇到偏差立即停止。实验不是历史成功路线。

一个动作可以同时检验多条假说，实验设计应把直接相关的假说一起纳入。比如一次位移可以同时提供动作方向、可控对象身份、所进入区域可通行性的证据。LLM 必须根据同一份前后观察逐条判断支持、反驳或尚不确定，并解释各自依据；不得把一个总谓词的成立等同于所有假说成立。局部可通行证据与整类区域的泛化判断要区分，颜色、对象和动作含义由当前游戏的观察与 LLM 假说决定，不能写死在通用提示中。每次分析的多条认知变化和原因都应出现在运行日志并持久化。

结果可来自确定的可观察谓词（具体预测帧、level 是否增加、终态、颜色对象平移/计数、当前格子变化等）或带实际证据的 LLM 语义解释。前者由程序从 Broker 观察计算，后者必须保留解释来源和有限观察范围，不能仅凭 LLM 状态字段晋升。`frame_changed` 只能证明画面发生了某种变化，不能单独证实方向、对象角色或目标；这类假说必须给出具体预测帧或其他特异证据。预测支持、反例和两者皆无法判定必须分开；缺少可判定结果时维持 undetermined。局部支持不能被描述为完整玩法已被证明。

程序必须拒绝不存在的 claim、过期帧/episode、错误动作、尚未执行即分析、重复消费证据、LLM 自造 evidence、无证据直接 certain。确认成功条件必须有真实 level/WIN 变化；帧变化不等于目标进展。

规划时，WorldMap 与持续更新的语义认知通过只读组合投影
`asterion.prime.p7-planning-background/v1` 一起提供给 P7 LLM。投影带有精确身份、当前帧摘要、WorldMap 版本、认知事件序号、语义报告、机制记忆和 `execution_authority=none`。确认事实用于解释当前状态，未定假说用于选择区分实验；语义认知不能写入 WorldMap、模拟器证书或路线。每次 `observe`、`act_checked` 和 `cognition_update` 完成后返回最新投影，模型在下一动作前重新读取；实际执行仍只能通过 `p7_act_checked`，当前观察和证书校验仍是权威。

## 6. 状态机与 RESET

状态依次为 `OBSERVE → PROPOSE → EXPERIMENT_SELECTED → ACTION_EXECUTED → ANALYZED → SNAPSHOT`，随后继续实验、RESET、READY 或 STOPPED。RESET 清空 pending experiment、当前 episode 动作历史/已试计数、帧绑定、临时计划、模拟证书和 episode 临时对象；保留语义主账本、反例与完整审计历史。不得把旧 pending probe 或旧帧证书带过 RESET。RESET 后重新观察再选择实验。

事件包含 session/episode id 和单调序号，至少覆盖：`cognition.session.started`、`cognition.episode.started`、`cognition.hypothesis.proposed`、`cognition.experiment.selected`、`cognition.action.executed`、`cognition.observation.analyzed`、`cognition.hypothesis.confirmed`、`cognition.hypothesis.falsified`、`cognition.hypothesis.remains_undetermined`、`cognition.snapshot`、`cognition.episode.reset`、`cognition.ready_for_solve`、`cognition.stopped`。

模型上下文自动追加当前图景及最新实验反馈，操作者私有事件文件按顺序落盘。工具读报告不能成为唯一获得必要状态的方式。

## 7. 工具与交接

沿用 `p7_cognition()` 读取语义图景及 session 状态，新增 `p7_cognition_update(payload)` 提出假说、选择实验、分析/记录解释、请求就绪或停止。操作封装为明确 op，不让 LLM 直接调用 store.resolve。工具注册同步 TypeScript 源码、资源 bundle、Pi allowlist、Python facade、worker RPC 和 operator dispatch。工具调用必须返回真实 Prime AgentToolResult。

初始画面和既有认知由应用直接注入。自然语言语义是主入口，低层 WorldMap/candidate/DSL 是可按需使用的工件。通关动作的历史和证书仍不可改写；通关反馈触发的新假说可以写入同一精确游戏账本，并在下一次规划前重新组合为背景。每次实验/决策记录使用了哪些 claim ids 及因此选择/排除了什么，使“经验生效”可审计。

READY 表示“可以开始一次基于当前认知的尝试”，最低要求是账本中存在至少一个游戏特定的待定或已支持假说；不要求类型/对象/控制/目标/策略全部确定。尝试过程中发现未知或反例时，必须回到提出/选择/分析假说的分支，再用新的规划背景继续动作。只有达到动作/时间限制且没有可行动假说、或只有空报告，才必须 STOPPED。完整语义覆盖仍可作为诊断指标，READY 不保证已经认识全部隐藏机制。

## 8. 验收

1. 合成闭环：未知题 → LLM 形状提案 → 真实 Broker 实验 → 支持/反例/未定 → RESET 清理 → 重载同 L1；确认执行入口、证据、状态均一致。
2. 以读写隔离的第二次会话验证加载认知改变实验选择，不能靠拷贝旧坐标/动作路线。
3. 真实本地 L1 探索：保存语言图景、假说演变和实际动作总数；能明确回答认识了什么、还不知道什么、下一次怎么验证。若答不出来，功能未达到目标。
4. 新会话通关测试：报告认知引用、实际当前动作数、RESET 数、sealed/replay/cleanup；失败也如实记录。单次过关不能证明“越玩越熟”，需要同 L1 多次认知变化证据。
5. 独立代码评审；TypeScript 测试、相关 Python 测试、lint/docs、promotion-check 和真实打包运行。External-limited 或 Not rerun 不得写为 PASS。

## 9. 实施顺序

语义账本与合同 → 实验/episode 状态机及 Broker 集成 → Prime 工具与上下文 → 独立探索入口、事件报告和通关交接 → 聚焦测试与独立评审 → 打包门禁 → 真实 L1 认知/通关验证。旧进度统计仍可留作诊断，不再称为核心游戏经验。
