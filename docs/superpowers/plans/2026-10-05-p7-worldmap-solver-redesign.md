# P7 WorldMap Solver Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在既有 Asterion-prime 持久 Python 能力上实现 WorldMap 驱动的研究、规划、短计划执行与纠错，并让网页控制台复原和控制同一个求解过程。

**Architecture:** 一个主解题者复用 Prime kernel，以只读真实证据构造和修正程序模型。P7 工作区接纳有版本的研究成果，主解题者通过独立入口提交行动计划；唯一 Broker 按真实反馈停止后缀。控制台消费同一权威事件及生命周期，不自行解释 stdout 或派发研究代码。

**Tech Stack:** Python 3.10+、现有 Asterion-prime/Pi runtime、持久 Python subprocess、TypeScript Pi extension、现有 P7 HTML/JavaScript console、unittest。

## Global Constraints

- 设计依据：`docs/superpowers/specs/2026-10-05-p7-worldmap-solver-redesign.md`；三个实现分工共同验收，不能将单个工具或页面片段称为重设计完成。
- “Python 编排；应用调用既有 runtime 与 runner；真实动作只有一个受控入口”。不增加 composer、runner、模型后端服务或第二套环境执行器。
- “Host 持有只追加的权威动作/观察历史”。研究代码只能操作快照或副本，不能发布真实观察事件。
- “这些是可用的编程约定，不是进入求解前必须全部完成的闭合协议”。部分模型、未知目标和不确定前沿必须可用。
- “只恢复纯模型/分析代码、数据和已分析历史序号，不重播含真实动作的 cells”。不用 pickle 恢复任意进程对象。
- “计算中的暂停请求立即阻止新行动，当前有界 cell 完成或主动让出后才进入 paused”。停止与暂停是不同操作。
- “人工动作不进入 P7 的模型证据和经验”。已有 HUMAN 独立试玩、存档和回放不作为自主求解的数据源。
- 所有执行设置由固定应用预设给出有限值；不向用户索要 provider/model/cost/deadline 参数，不据暂停延长绝对运行期限。
- 研究 Python 与 actor bridge 的能力路由隔离不是 OS 沙箱。当前同 UID 进程不能声称抵御任意宿主文件访问、进程内省或越权系统调用；不以隐藏 Python 属性当安全边界。
- 通用 Prime 代码不导入 `applications.prime.p7`；P7 通过 operator 显式注入 bootstrap、证据服务与 observer。JSON manifest 不放源码、路径、环境值或执行配置。
- 使用针对性 unittest 与实现复审，避免发布级测试膨胀。生成扩展、wheel、allowlist 与源码同步；全量 benchmark 不在本计划授权内。
- Workers 共享代码库，不得回退他人的编辑。按下述所有权修改；主线程集成并及时提交，各任务通过后不反复跑无关检查。
- 默认 verified solve 完整切到三工具研究路径；旧 cognition/legacy/DSL 可保留为显式历史路径。本次不扩展为全仓旧代码清理。

---

## 文件所有权与依赖

| 分工 | 拥有文件 | 对外产物 |
|---|---|---|
| Task 1 / Prime | 新建 `src/asterion/agents/prime/ipython.py`、`ipython_worker.py`、`tests/test_prime_ipython.py` | 通用持久执行、候选 export、源码/JSON 恢复 |
| Task 2 / P7 | 新建 `src/asterion/applications/prime/p7/research.py`、`research_bridge.py`、`solver.py`、`solver_events.py`；修改 `prompt.py`、`tool_registry.py`、TS extension 源码及契约测试 | 只读研究端、WorldMap 工作区、actor plan、三工具入口 |
| Task 3 / Console | 新建 `src/asterion/applications/prime/p7/solver_control.py`；修改 `console_events.py`、`console_snapshot.py`、`console_session.py`、`console_server.py`、`console_assets/{app.js,index.html,styles.css}` 及对应测试 | 生命周期、事件投影、历史查看、暂停/继续/停止 |
| Task 4 / 集成 | 新建 `p7/research_runtime.py`；`p7/operator.py`、`p7/live.py`、`p7/ipython_host.py`、`p7/official_operator.py`、现有 runtime_binding 和必要的 Prime session 接点、打包资源、核心状态文档 | 实际安装运行同一闭环与证据 |

Task 1 可独立实施。Task 2/3 按下面冻结接口工作；集成方拥有旧 operator 接线，避免并行编辑 5,000 行文件。若接口确需改变，先给相邻 worker 发精确签名，再同步本文件。

## 冻结的核心接口

以下是 Python/application 内部接口，不新增公共 runtime protocol。`JSONValue` 表示有限 JSON 值；映射输入均由接收方复制、校验并冻结，返回值不暴露可变 host 状态。

### A. Prime kernel（Task 1）

```python
@dataclass(frozen=True)
class KernelBootstrap:
    modules: Mapping[str, str]       # operator 提供的模块源码，名字为标识符
    initial_data: Mapping[str, JSONValue]
    workspace: Path                 # operator 指定的独立可写研究目录

@dataclass(frozen=True)
class KernelLimits:
    max_code_bytes: int = 16 * 1024
    max_output_bytes: int = 64 * 1024
    deadline_seconds: float = 60.0
    max_export_bytes: int = 256 * 1024   # 每 cell 的聚合候选 export 大小

@dataclass(frozen=True)
class KernelExport:
    export_id: str                  # host 对 kind/value 的 sha256
    name: str
    kind: Literal['text', 'json']
    value: JSONValue
    source_call_id: str

class PersistentIpythonHost:
    def __init__(self, *, worker, bootstrap: KernelBootstrap,
                 limits: KernelLimits = KernelLimits(), observer=None): ...
    async def execute(self, call_id: str, code: str,
                      signal: CancellationSignal) -> PrimeToolResult: ...
    def read_export(self, export_id: str) -> KernelExport: ...
    async def restore(self, *, source_exports: tuple[KernelExport, ...],
                      data_exports: Mapping[str, KernelExport],
                      signal: CancellationSignal) -> None: ...
    async def close(self) -> None: ...
```

`SubprocessPythonWorker()` 无参构造，保持 `start/execute_cell/close` 生命周期。`start` 接收 bootstrap，不接收 P7 facade。cell 注入通用 `prime_workspace.export(name, value)`：字符串为 text，其余有限 JSON 为 json；它只缓冲候选产物。成功 cell 结束后 host 接收 export、计算 ID、冻结值，在结果中返回引用；普通 Python 错误的 exports 不接纳，但既有 namespace 保留。host 以 `workspace/exports/<digest>.json` 保存导出，仅显式 export ID 可读取/恢复。stdout 不是 export 协议，不能从 print 文本生成 artifacts、事件或真实动作。

`execute` 的结构化结果内容包含 `execution_status=ok|python-error|interrupted|lost`、有界 stdout、export refs、kernel generation；以既有 PrimeToolResult 允许的 text 内容承载 JSON，不能发明违反其闭合类型的 content block。普通语法/运行错误作为可修复结果交给 actor，不误杀进程；timeout/传输失败使该 generation 失效。observer 接收 host 产生的 `cell_started/cell_finished/cell_interrupted/kernel_lost`，不接受 cell 自报完成状态。`restore` 只用于空 namespace，按顺序运行 text 源码，然后将 JSON 数据绑定到合法标识符；恢复代码仍在无行动能力的 worker 内运行。

### B. P7 三工具与只读研究模块（Task 2）

模型工具面只保留：

```text
ipython(code: string)
p7_workspace(request: ReadRequest | PublishRequest | CheckpointRequest | FocusRequest)
p7_execute_plan(plan: ActorPlan)
```

`ReadRequest={op:'read', revision?:string}` 返回当前或历史 WorldMap、模型工件引用、目标、未解问题、证据范围、最新真实观察和生命周期。当前观察也在初始上下文和每次行动反馈中自动追加，不要求每步再读一次工具。

`PublishRequest={op:'publish', base_revision:string, draft_export_id:string}`：host 从 kernel export 读取下面的 Draft，核对父版本、工件引用及证据序号，产生新 revision。发布只改变研究状态，不执行动作。旧版本保留，修改与回退都形成新 revision。

```text
Draft = {
  worldmap: {description_zh, state_summary, rules, unknowns, competing_hypotheses},
  task: {goal, obstacles, question, next_operation, public_basis},
  model: {source_export_ids, state_export_id?, coverage, assumptions},
  reports: [{kind: 'projection'|'dynamics'|'goal'|'search', export_id,
             evidence_sequences, claim_status: 'reported'|'checked'|'unknown'}],
  evidence_sequences: [int],
  correction: {counterexample_sequence?, changed, retained}
}
```

语义字段有固定有限大小，不要求填满所有 WorldMap 槽位。`checked` 只能由应用比较程序预测与 host 权威观察后产生，不能直接采信 Draft 自报；未知或模型声明的报告标 `reported/unknown`。模型没有完整 source 或终局判断时仍允许研究、单步探针与基于已有规则的子目标规划。

`CheckpointRequest={op:'checkpoint', revision:string, state_export_id?:string, frontier_export_id?:string, analyzed_through:int}`：host 原子保存已接纳 source/JSON exports 的引用和 kernel generation，不抓取任意 Python 对象，不扫描 namespace。

`FocusRequest={op:'focus', task:{goal,obstacles,question,next_operation,public_basis}}`：更新公开任务声明，关联当前 revision/observation；不改变模型，不授予行动权限。`next_operation` 固定为 `analyze|model|validate|search|probe|execute`，host 将下一个真实 cell/plan 关联该 task，缺少声明显示通用 calculation，不能猜测阶段。

worker 只导入 `p7_research`：

```python
def context() -> dict: ...
def history(start: int, limit: int) -> list[dict]: ...
def frame(sequence: int) -> list[list[int]]: ...
def artifact(export_id: str) -> JSONValue: ...
```

这是独立的只读 server-side allowlist。`act`、`act_checked`、`execute_plan`、`publish`、任意通用 method eval 都不存在；伪造 wire request 也被拒绝且 engine 调用次数保持零。真实行动仅经 Pi extension → operator 已持有的 socketpair；worker `close_fds=True`，不继承该 FD、actor bridge 环境或路径。删除新求解路径上的旧 P7ClientServer 混合读写入口；仅删除 facade 方法不算完成。

### C. Actor plan 与证据（Task 2，Task 4 接线）

```text
ObservationRef = {run_id, attempt_id, level, sequence, observation_sha256}
ActorPlan = {
  plan_id: string,
  start: ObservationRef,
  workspace_revision: string,
  goal: string,
  purpose: 'advance'|'probe',
  assumptions: [string],
  steps: [{action:{name, data}, expect:{cells?,frame_sha256?,state?,levels_completed?}}]
}
```

`steps` 为 1–20 项、无重复提交副作用。`expect` 中 cells 为明确 `(x,y,value)` 集合；frame hash、状态、关数取一致交集；允许不完整覆盖，不接受任意 Python predicate 在 host 内执行。未知机制可用一个明确预测的短探针；不能把证书作为全部探针前置条件。进度条件允许“关数不变”作为附加断言，但不能单独冒充信息充分的预测。

```python
class Solver:
    def __init__(self, *, broker, kernel, control, workspace_root: Path,
                 run_id: str, attempt_id: str,
                 event_sink: Callable[[str, Mapping[str, JSONValue]], None]): ...
    def workspace(self, request: Mapping[str, JSONValue]) -> dict: ...
    def execute_plan(self, plan: Mapping[str, JSONValue]) -> dict: ...
    def current_context(self) -> dict: ...
```

构造时从 broker 的精确 game identity 建立工作区作用域，kernel 提供 read_export，control 提供派发门禁，event_sink 接收上面冻结的 kind/payload。`research_bridge.py` 产出 `ResearchReadServer(context, history, frame, artifact)`（四个 keyword-only callable）；`start()->str` 返回要注入的 `p7_research` 模块源码，`close()->None` 关闭只读服务。context callable 为 `solver.current_context`，history/frame 为 broker 的只读方法，artifact 为仅允许已接纳工件的读取函数；不要把 broker 对象本身传入 worker。构造循环使用延迟闭包，只有资源全部组装完成后才允许 kernel execute。

Solver 仅是应用调度/校验，不实现第二套 runner 或 engine step。它核对起点与 revision，记录提交，交给唯一 Broker 的顺序行动入口；每步都检查暂停、运行期限及剩余计划。结果含 `applied_count, stop_reason, feedback, unexecuted_steps, observation, workspace_revision`。反馈至少包含预测/实际差异和对应 observation ref；实际新观察使当前 plan 的旧起点不可重用。相同 plan_id+相同内容返回已记录状态，内容不同拒绝；结果未知时不得重派。

权威动作历史在 host 持有并只追加；读取返回副本。程序输出预测只登记为计算产物。恢复后或进入新关卡必须读取真实当前观察重建 state，不用旧 frame 当现实。终局由 engine 信号判定，模型 outcome 不能使 run 完成。

### D. 生命周期与控制台（Task 3）

```python
class SolverControl:
    def __init__(self, run_root: Path, run_id: str, deadline: float,
                 *, clock=time.monotonic): ...
    def poll(self, source_action_sequence: int,
             observation_sha256: str) -> dict: ...
    def snapshot(self) -> dict: ...
    def enter(self, operation: Literal['cell','action','model_round']) -> bool: ...
    def leave(self, operation: Literal['cell','action','model_round']) -> None: ...
    def action_allowed(self) -> bool: ...
```

生命周期：`starting → running → pause_requested → paused → running`；停止为 `stop_requested → stopping → stopped`；清理失败为 `cleanup_failed`，不能伪装 stopped。状态和当前活动计数由 host 锁保护；读到暂停请求立即使 `action_allowed=False`。`enter` 在 paused 不接纳新工作，pending model round/cell 可以完成，当前 action 必须先记录真实结果；没有在途工作才确认 paused。stop 复用现有 supervisor cleanup/cancellation 路径，不伪造尚未返回的动作结果；证据标 unknown/interrupted。绝对 deadline 不因 resume 改写。

ConsoleSession 的 `pause(session_id,command_id)`、`resume(session_id,command_id)` 与现有 stop 一致实现幂等。跨现有 console/guest 进程使用共享 run_root，不部署新 daemon。Task 3 的 `solver_control.py` 同时提供：

```python
def write_control_request(run_root: Path, *, run_id: str, command_id: str,
                          request_sequence: int,
                          operation: Literal['pause','resume']) -> dict: ...
def read_control_ack(run_root: Path, *, run_id: str) -> dict | None: ...
```

Mac 单写者原子替换 `control-request.json`，guest/operator 单写者原子替换 `control-ack.json`。请求闭合字段为 `schema='asterion.prime.p7-run-control/v1',run_id,command_id,request_sequence>=1,operation`。ack 闭合字段为 `schema,run_id,command_id,request_sequence,state,reason,source_action_sequence,observation_sha256`，不重复 operation。state 为 `running|pause_requested|paused|stop_requested`；reason 为 `null|deadline_expired|request_invalid|control_stale|command_conflict|stop_requested`。拒绝 symlink、超限文件、身份不符；request sequence 单调，每次仅一个在途 pause/resume；同 command ID 内容一致返回原状态，内容不同拒绝。浏览器等 ack 才确认暂停完成。

事件保留现有 console row：`schema,run_id,game_id,sequence,kind,payload`；host 分配连续 sequence，它就是 as-of 的 `event_sequence`。不要另建并行时间轴；同一 observation 上多次模型修订也由 sequence 精确区分。Task 2 `solver_events.py` 提供公共 payload 构造，Task 3 的 console_events 执行同一校验；现有 observation/action 历史可继续读取。

新增 payload 的共同闭合字段：`source_action_sequence:int, observation_sha256:hash, level:int, workspace_revision:str|null, task_id:str|null, origin:actor|calculation|environment|operator`。run 已标識 attempt；不能补造不存在的关联。各 kind 再加下列字段：

| kind | 额外字段 |
|---|---|
| `compute_task` | `status:declared|started|completed|failed|interrupted`, `operation:analyze|model|validate|search|probe|execute`, `goal:str`, `obstacles:list[str]`, `question:str`, `summary:str`, `elapsed_ms:int|null`, `completed_units:int|null` |
| `model_revision` | `revision:str`, `parent_revision:str|null`, `description_zh:str`, `state_summary:str`, `rule_summaries:list[str]`, `unknowns:list[str]`, `coverage_summary:str`, `validation_summary:str`, `correction_summary:str`, `evidence_sequences:list[int]` |
| `plan` | `plan_id:str`, `status:proposed|executing|completed|stopped`, `goal:str`, `assumptions:list[str]`, `actions:list[{name,data}]`, `applied_count:int`, `stop_reason:str|null` |
| `feedback` | `plan_id:str`, `expected_summary:str`, `actual_summary:str`, `mismatch_kind:none|state|dynamics|goal|implementation|unknown`, `unexecuted_count:int`, `counterexample_sequence:int|null` |
| `run_control` | `state:str`, `command_id:str|null`, `request_sequence:int`, `reason:str|null` |

origin 由调用路径赋值，模型不可伪造 environment/operator 来源；actor 的 declared task 不等于 calculation started。文本使用既有 public_text/public_narrative，摘要600字符、description_zh最多8000字符，列表最多32项，actions最多20项。公共 payload 不含 prompt、provider payload、stdout、私有路径和源码；历史查看按 event_sequence 冻结当时版本，当前全局 stop 始终作用于现场运行。

## 恢复合同

1. **聊天压缩**：保留原 kernel，不重建 namespace；摘要记录当前 revision、关键变量/函数名称、分析到的 observation sequence、未解问题。复用 Prime 现有 kernel note。
2. **普通 cell 异常**：保留 namespace，但本 cell 未成功的 exports 不发布；actor 看错误后修正代码，不自动执行动作。
3. **kernel 丢失**：冻结正在依赖它的候选计划；host 标记 generation lost。新 kernel 注入同样只读模块，加载最近一次完整 checkpoint 的纯源码和 JSON，标明未保存 frontier 丢失；对当前观察校准后产生新 revision，旧计划不能直接继续。
4. **环境/Broker 进程丢失**：停止当前 attempt 并标注不确定边界。没有真实环境恢复能力时，不把 kernel checkpoint 称为游戏可继续；新 attempt 使用新真实环境与新身份，复用规则/程序但不自动重放历史动作。
5. **原子性**：先完整写入按内容寻址的 exports，再原子替换 checkpoint 清单；加载核对 hash/完整性/本游戏适用性，不在缺少 source 或 data 时声称恢复成功。

## Task 1: 通用 Prime 持久 kernel 与候选产物

**Files:** 创建所有权表 Task 1 的三个文件。阅读 `p7/ipython_host.py:324`、`p7/live.py:326` 和 `agents/prime/summarization.py:123`；不修改 P1 oracle 或搬入 P1 任务限制。

**Interfaces:** 产出接口 A，消费既有 `PrimeToolResult`、`CancellationSignal`。不认识 ARC、WorldMap、模型证书或 console。

- [x] 添加最小真实 subprocess 测试：cell 1 定义函数与可变状态，cell 2 修改，cell 3 读取；一次 SyntaxError/ValueError 后仍可使用此前函数。
- [x] 添加候选导出与恢复断言：后续修改原字典不改变已导出 JSON；恢复仅运行显式 source，恢复 data 值正确，不读取/replay cell log。重复 call ID 不执行第二次。

```python
class TestPrimeIpython(unittest.IsolatedAsyncioTestCase):
    async def test_export_is_a_snapshot(self):
        await self.host.execute('one', "x={'v':1}; prime_workspace.export('state', x)", self.signal)
        exported = self.exports_from_last_result()[0]
        await self.host.execute('two', "x['v']=9", self.signal)
        self.assertEqual(self.host.read_export(exported).value, {'v': 1})
```

测试 fixture 创建临时 workspace、真实 SubprocessPythonWorker、未取消 signal，退出时必关闭；`exports_from_last_result` 仅解析最后一次 execute 的结构化结果。

- [x] 实现源码中的 host/worker 解耦、JSON exports 通道与 observer；以正常 stdout 输出不能冒充 exports/host lifecycle 为断言。`restore` 校验 kind、hash、变量名和空 namespace 后执行，无 pickle。
- [x] 跑 `uv run python -m unittest -v tests.test_prime_ipython`；增加一个有限超时 cleanup case，确认 worker 被收回。确认 `rg 'applications|p7|arcengine' src/asterion/agents/prime/ipython*.py` 无产品依赖。
- [x] 提交本任务文件与测试，向 Task 2/4 报告精确导入路径、结果 JSON 和 observer 签名；未适配实际 P7 前只声明 kernel 边界通过。

## Task 2: P7 研究工作区、程序推演与行动计划

**Files:** 所有权表 Task 2；创建 `tests/test_prime_p7_research.py`、`tests/test_prime_p7_solver.py`；修改 `tests/test_prime_p7_tool_registry.py`、`tests/test_prime_p7_bridge_dispatch.py`、`packages/typescript/asterion-prime-extension/test/pi-contract.ts`。

**Interfaces:** 消费接口 A 和 D；产出接口 B/C 及 solver event envelope。Task 4 为它注入 Broker、host evidence reader、kernel、control、公共事件 sink。

- [ ] 用两个短历史转移构造研究数据：正确移动模型能解释两次，错误目标仍 unknown；错误转移返回最小反例序号。验证模型变量更改不会覆盖 host 原始 frame。
- [ ] 实现 `research.py`：内容寻址 artifacts、revision、Draft 接纳、checkpoint、当前 context；作用域绑定 game/seed/attempt，source/model/reports 通过 ID 关联，不重复保存独立“确定认知”账本。
- [ ] 实现 `research_bridge.py` 只读四方法，伪造旧 `act_checked` 请求必须在 server 拒绝。输入返回有限副本；任何 unknown 方法、越界序号或非本 run artifact 都明确拒绝。

```python
def test_research_wire_cannot_dispatch(self):
    response = self.read_server.dispatch({'method': 'execute_plan', 'args': [{}]})
    self.assertEqual(response['status'], 'rejected')
    self.assertEqual(self.engine.actions, [])
```

- [ ] 实现 `solver.py` 三工具入口，发布/行动均核对父 revision；host 比较预测与真实证据，报告 projection/dynamics/goal 分离。程序建模/search helper 输出候选和 unknown，不自动提交行动、不扫描真实 SDK。
- [ ] 使用实际现有 Broker 行动路径验证短计划：正确首步、错误第二步、第三步未执行；过关/暂停也停止后缀；旧起点、重复 ID、旧 revision 在动作前拒绝或返回既有结果。source/revision 不完整时仍允许有起点和明确预期的单步 probe。
- [ ] 将 prompt 重写成“读取当前证据→在 IPython 定义/检验模型→推进目标或区分未知→发布成果→明确提交短计划→分析反馈”的主路径。允许 stdlib 研究编程，移除只导入旧 p7_client、只能 fallback 和强制旧账本实验流程。解释变量跨压缩保留、源码/JSON checkpoint、无模型证书前置门槛。
- [ ] TypeScript 注册精确三工具；allowlist、Python registry 和描述统一。`p7_workspace` 的 tagged union 及 ActorPlan 参数可由模型实际表达；不只改工具文案。旧应用工具退出新默认路径，需要保留的历史解析不可成为双执行入口。
- [ ] 跑 `npm --prefix packages/typescript/asterion-prime-extension test` 与 `uv run python -m unittest -v tests.test_prime_p7_research tests.test_prime_p7_solver tests.test_prime_p7_tool_registry tests.test_prime_p7_bridge_dispatch`；针对 obsolete 接口的测试更新为新行为，保留权限/identity/redaction边界。
- [ ] 提交所属文件，并向 Task 3/4 交付一条脱敏 fixture 事件链：任务→计算→发布→计划→动作→失配→修订，用于同一故事的 UI 与集成验收。

## Task 3: 控制台协同、历史与生命周期

**Files:** 所有权表 Task 3；创建 `tests/test_prime_p7_solver_control.py`，更新 `tests/test_prime_p7_console_events.py`、`test_prime_p7_console_snapshot.py`（不存在则创建）、`test_prime_p7_console_session.py`、`test_prime_p7_console_server.py`。

**Interfaces:** 实现 D；消费 Task 2 的 solver events，输出 console public snapshot 和 operator 可读取的控制命令。不要解析 arbitrary stdout 补猜事件。

- [ ] 实现独立 `SolverControl`：幂等 pause/resume/stop、活动计数、边界确认及绝对期限。暂停中的行动派发必须零增长；当前动作返回后才进入 paused，停止尚未清理时不能显示 stopped。

```python
def test_pause_waits_for_dispatched_action(self):
    self.assertTrue(self.control.enter('action'))
    write_control_request(self.root, run_id=self.run_id, command_id='pause-1',
                          request_sequence=1, operation='pause')
    self.control.poll(0, self.observation_sha256)
    self.assertFalse(self.control.action_allowed())
    self.assertEqual(self.control.snapshot()['state'], 'pause_requested')
    self.control.leave('action')
    self.assertEqual(self.control.snapshot()['state'], 'paused')
```

- [ ] ConsoleSession/server 增加 pause/resume 路由与确认回执；控制请求到 operator 的路径复用本 run guest 映射，不能写入 worker 可发布产物集合。断连或未知回执显示请求未确认，不猜为成功。
- [ ] 消费公共事件构建画面/任务/WorldMap/研究计划/反馈五区：真实帧与预测区分，已执行/未执行后缀明确；修订链接到反例，错误来源可区分状态/动力学/目标/实现。
- [ ] 使用同一 Task 2 fixture 检查历史 event N 展示 revision N，而不是最终 revision；现场停止按钮不作用于被查看的历史 run。HUMAN 试玩与自主证据保持独立。
- [ ] 在浏览器当前已登录实例验证开始、暂停请求、已暂停、继续、停止请求、已清理状态以及历史回看；只用 provider-free fixture/synthetic adapter 做 UI 阶段验证，不能称为真实求解胜利。无可计算总量时不显示百分比。
- [ ] 跑针对 console/control unittest。用 sentinel 对公共 snapshot 断言不出现 stdout、prompt、provider payload、路径、源码；提交所属文件并交付 Task 4 控制握手格式。

## Task 4: 实际接线、共同复审与有限真实验证

**Files:** 所有权表 Task 4；修改 `src/asterion/applications/prime/resources/ipython-extension.mjs` 由构建产生，更新 `tests/test_prime_p7_native_installed.py`、`tests/test_prime_p7_official_installed.py` 与相关资源检查；同步 `CURRENT-STATE.md`、`DECISIONS.md`、`docs/status/INDEX.md`、`RESUME-NEXT-SESSION.md`。

**Interfaces:** 在 existing `build_p7_operator_resources` 注入 Prime host、只读研究 server、Solver、SolverControl、事件 sink。既有 runtime/runner/assembly 继续负责执行；只替换应用工具 dispatch 和 kernel host 接线。

- [ ] 移除新运行路径上的旧可写 worker API，适配 native 与 official operator 到同一个通用 kernel；`p7/ipython_host.py` 仅保留必要兼容导出或删除重复实现。generic Prime 不反向依赖应用，不把 P1 coding assembly 当通用 kernel 启动器。
- [ ] 默认 verified 路径的 `build_strategy_prompt`、`_initial_game_context` 与 continuation 同时切换：不因历史默认值 `replay` 注入旧认知表单、DSL 自动搜索或精确路线。显式 legacy/cognition 路径可保留原实现，不默认加载共享 Playbook/GameCognitionStore/SemanticCognitionStore 或成功 prefix；研究记忆是否复用必须由当前运行模式明确决定。
- [ ] actor method_call 只接受新三工具对应请求；research server 与 action bridge 分离。为每次 cell/action 用真实取消 signal 替换当前 `_BridgeSignal.cancelled=False`，暂停门禁位于新派发之前。
- [ ] 在既有 Prime continuation/round 边界接应用提供的 admission hook，暂停不继续生成新轮模型请求；通用 hook 不认识 P7 目标。应用明确注入 continuation prompt，移除默认提示中对 `p7_client` 的依赖。不增加外层自主循环来复制 PrimeSession。
- [ ] 在 root 拥有的 `p7/research_runtime.py` 写薄适配器 `P7ResearchRuntime`，组合 generic host、Solver、control 和 read server，提供 `execute/admit_round/continuation_prompt/close`；现有 runtime_binding 接受它并向 generic Prime 注入 `before_round` async hook。不要给 PrimeLaunch plain-data 附加 live callback。一次模型 round 内含 tool cells，不能把整个 round 记作控制活动计数，否则暂停等待 round 结束、tool 又等待暂停解除会死锁；`before_round` 只做 admission 等待，活动计数仅覆盖真正的有界计算/环境动作。
- [ ] 用一条实际 wiring 的 provider-free story 验证：cell 建模导出→publish→actor plan→Broker action→真实差异→workspace 修订→console 历史；checkpoint 重建 kernel 后强制校准；环境丢失不自动恢复游戏或重派未知动作。
- [ ] 实现复审重点：WorldMap 是否改变下一次计算/动作、程序是否实际执行、原始证据与派生报告是否分离、pause是否真正截断后缀、旧工具是否仍暴露行动捷径、公共投影是否越界。修复结论后再扩大检查。
- [ ] 依次跑 `npm --prefix packages/typescript/asterion-prime-extension test`、本次相关 Python tests、`make promotion-check`；执行 `make lint`、`make docs-check` 并按仓库要求完成必要 `make check`，既有无关失败记录其边界。确认 wheel 内新 Prime worker、新 P7 modules、打包扩展与 allowlist 一致。
- [ ] 用固定预设执行 `make asterion-prime-p7-level-witness GAME=<已选择的本地游戏> LEVEL=1`。只选一个有限新运行，隔离旧 knowledge stores，不能注入人工路线、成功 prefix 或真实 SDK 离线搜索答案。选择已有数据且允许本地运行的游戏，由集成方在执行记录中写清确切 GAME 与 preset；命令成功仅证明实际结果，不据synthetic story预先宣称过关。现有 witness action cap 基于 human baseline，不能为得到成功偷偷扩大。
- [ ] 检查真实证据中至少有一次“程序模型/搜索结果→明确计划→真实反馈”的可追溯连接；若失败，记录第一个模型/控制/目标断点而不是盲目扩大预算。下一关迁移必须在全新 run 中自然连续过关，使用固定有限预设；旧 LEVEL=2 自动 replay prefix 的 witness 不能作跨关能力证据。再次求解只复用明确保存的规则/程序，不复用精确动作路线；无授权或外部阻塞则明确留作未完成边界，不标完整能力通过。
- [ ] 记录实际命令、结果、动作数、RESET、停止原因、模型修订与控制台事件位置；修订 DSL-only 的旧设计决策。提交代码、生成资源、测试与状态文档，确保本次成果没有散落为未跟踪文件。

## 完成边界

Task 1–3 的单元验证仅证明各自接口，Task 4 的实际 wheel 运行才证明部署闭环。只有真实环境终局与可检索的模型→计划→反馈证据支持求解能力结论。没有下一关或恢复观察证据时，不把这些能力从代码存在推断为 Verified；最终状态分别记录已验证事实、当前判断、历史归档和未完成边界。
