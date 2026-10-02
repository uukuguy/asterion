# P7 游戏经验认知主合同

状态：2026-10-02 用户批准设计并授权完整实现。本文是实现与验收的主合同；旧的进度记忆、候选晋升和路线流程只是可选组件，不能替代本文。实现完成与真实能力验证必须分别记录。

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
                       ↓ 达到就绪条件/安全停止
通关测试：全新会话 → 只读加载认知 → 基于认知规划 → 实际反馈
                                                  ↓ 新疑问/反例
                                         写入新的待定假说/返回探索
```

探索不受人类 baseline 或官方得分步数限制，也不使用官方 session 做试验。它仍有独立有限的运行时长、每 episode 动作数、RESET 数和输出大小限制；限制到达是 `stopped`，不能冒充认知就绪。预算是应用预置，不要求用户配置模型/成本参数。

通关测试保持现有动作记账、封存、replay 和 cleanup；认知探索单独标记目的，不进入最佳路线/排行榜成功结果。首次实现以本地 L1 为入口，探索中意外过关也必须生成认知报告，不将通关自动等同于理解游戏。再次探索创建全新引擎实例重新开始 L1。

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

schema 为 `asterion.prime.p7-semantic-cognition/v1`；精确作用域为 `game_id + seed + win_levels + level`，内部 L1 的 level 为 0。每条假说包含稳定 id、kind、subject、claim、reason、falsifier、next_test、可选适用 context、status 及程序绑定的证据索引。kind 为 `game_type / object_role / control / success_condition / rule / strategy`；status 为 `undetermined / certain / falsified`。

LLM 只能新建待定假说。certain 的含义是“在记录的条件和实验范围内获得实测支持”，不声称普遍真理。视觉类比可以长期待定；例如“像迷宫”不需要为了就绪强制变成确定。反例保留，不能删除原反例后把同一 id 复活；修改适用条件必须新 id。协议成功（levels_completed / WIN）和题目成功条件（如何操作会获胜）分开，协议已知不能自动确认题目目标。

落盘只保存语言认知、状态和证据索引，原始画面、坐标及动作序列属于独立私有实验记录。所有加载的认知固定 `execution_authority=none`。语言 certainty 不等于模拟器证书。持久化必须原子写入、有限大小；写入失败不能对外声称更新成功。实验过程每个变化都发出图景，报告是账本的投影，不是第二个真相来源。

## 5. 实验与证据

每个实验必须在动作前声明：待检验 claim ids、自然语言问题、为什么比其他动作更有信息、当前可执行的动作/短序列、预期支持结果、预期反例，以及适用条件。程序将实验绑定到当前 run、episode、frame 和动作顺序。每次只执行一步并核对结果；计划遇到偏差立即停止。实验不是历史成功路线。

结果可来自确定的可观察谓词（帧是否变化、level 是否增加、终态、颜色对象平移/计数、当前格子变化等）或带实际证据的 LLM 语义解释。前者由程序从 Broker 观察计算，后者必须保留解释来源和有限观察范围，不能仅凭 LLM 状态字段晋升。预测支持、反例和两者皆无法判定必须分开；缺少可判定结果时维持 undetermined。局部支持不能被描述为完整玩法已被证明。

程序必须拒绝不存在的 claim、过期帧/episode、错误动作、尚未执行即分析、重复消费证据、LLM 自造 evidence、无证据直接 certain。确认成功条件必须有真实 level/WIN 变化；帧变化不等于目标进展。

## 6. 状态机与 RESET

状态依次为 `OBSERVE → PROPOSE → EXPERIMENT_SELECTED → ACTION_EXECUTED → ANALYZED → SNAPSHOT`，随后继续实验、RESET、READY 或 STOPPED。RESET 清空 pending experiment、当前 episode 动作历史/已试计数、帧绑定、临时计划、模拟证书和 episode 临时对象；保留语义主账本、反例与完整审计历史。不得把旧 pending probe 或旧帧证书带过 RESET。RESET 后重新观察再选择实验。

事件包含 session/episode id 和单调序号，至少覆盖：`cognition.session.started`、`cognition.episode.started`、`cognition.hypothesis.proposed`、`cognition.experiment.selected`、`cognition.action.executed`、`cognition.observation.analyzed`、`cognition.hypothesis.confirmed`、`cognition.hypothesis.falsified`、`cognition.hypothesis.remains_undetermined`、`cognition.snapshot`、`cognition.episode.reset`、`cognition.ready_for_solve`、`cognition.stopped`。

模型上下文自动追加当前图景及最新实验反馈，操作者私有事件文件按顺序落盘。工具读报告不能成为唯一获得必要状态的方式。

## 7. 工具与交接

沿用 `p7_cognition()` 读取语义图景及 session 状态，新增 `p7_cognition_update(payload)` 提出假说、选择实验、分析/记录解释、请求就绪或停止。操作封装为明确 op，不让 LLM 直接调用 store.resolve。工具注册同步 TypeScript 源码、资源 bundle、Pi allowlist、Python facade、worker RPC 和 operator dispatch。工具调用必须返回真实 Prime AgentToolResult。

初始画面和既有认知由应用直接注入。自然语言语义是主入口，低层 WorldMap/candidate/DSL 是可按需使用的工件。通关测试的基线快照只读，新假说与反例写入新的探索增量，不能改写本次测量起点。每次实验/决策记录使用了哪些 claim ids 及因此选择/排除了什么，使“经验生效”可审计。

READY 至少要求：类型/对象/控制/目标/策略已有描述；至少一个控制或规则有实际支持；关键开放问题及下一实验明确；LLM 给出可执行玩法说明及停止探索理由。仅达到动作/时间限制、仅过关或只有空报告必须 STOPPED。READY 不保证已经认识全部隐藏机制。

## 8. 验收

1. 合成闭环：未知题 → LLM 形状提案 → 真实 Broker 实验 → 支持/反例/未定 → RESET 清理 → 重载同 L1；确认执行入口、证据、状态均一致。
2. 以读写隔离的第二次会话验证加载认知改变实验选择，不能靠拷贝旧坐标/动作路线。
3. 真实本地 L1 探索：保存语言图景、假说演变和实际动作总数；能明确回答认识了什么、还不知道什么、下一次怎么验证。若答不出来，功能未达到目标。
4. 新会话通关测试：报告认知引用、实际当前动作数、RESET 数、sealed/replay/cleanup；失败也如实记录。单次过关不能证明“越玩越熟”，需要同 L1 多次认知变化证据。
5. 独立代码评审；TypeScript 测试、相关 Python 测试、lint/docs、promotion-check 和真实打包运行。External-limited 或 Not rerun 不得写为 PASS。

## 9. 实施顺序

语义账本与合同 → 实验/episode 状态机及 Broker 集成 → Prime 工具与上下文 → 独立探索入口、事件报告和通关交接 → 聚焦测试与独立评审 → 打包门禁 → 真实 L1 认知/通关验证。旧进度统计仍可留作诊断，不再称为核心游戏经验。
