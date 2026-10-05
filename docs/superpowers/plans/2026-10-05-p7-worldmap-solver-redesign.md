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

- [x] 用两个短历史转移构造研究数据：正确移动模型能解释两次，错误目标仍 unknown；错误转移返回最小反例序号。验证模型变量更改不会覆盖 host 原始 frame。
- [x] 实现 `research.py`：内容寻址 artifacts、revision、Draft 接纳、checkpoint、当前 context；作用域绑定 game/seed/attempt，source/model/reports 通过 ID 关联，不重复保存独立“确定认知”账本。
- [x] 实现 `research_bridge.py` 只读四方法，伪造旧 `act_checked` 请求必须在 server 拒绝。输入返回有限副本；任何 unknown 方法、越界序号或非本 run artifact 都明确拒绝。

```python
def test_research_wire_cannot_dispatch(self):
    response = self.read_server.dispatch({'method': 'execute_plan', 'args': [{}]})
    self.assertEqual(response['status'], 'rejected')
    self.assertEqual(self.engine.actions, [])
```

- [x] 实现 `solver.py` 三工具入口，发布/行动均核对父 revision；host 比较预测与真实证据，报告 projection/dynamics/goal 分离。程序建模/search helper 输出候选和 unknown，不自动提交行动、不扫描真实 SDK。
- [x] 使用实际现有 Broker 行动路径验证短计划：正确首步、错误第二步、第三步未执行；过关/暂停也停止后缀；旧起点、重复 ID、旧 revision 在动作前拒绝或返回既有结果。source/revision 不完整时仍允许有起点和明确预期的单步 probe。
- [x] 将 prompt 重写成“读取当前证据→在 IPython 定义/检验模型→推进目标或区分未知→发布成果→明确提交短计划→分析反馈”的主路径。允许 stdlib 研究编程，移除只导入旧 p7_client、只能 fallback 和强制旧账本实验流程。解释变量跨压缩保留、源码/JSON checkpoint、无模型证书前置门槛。
- [x] TypeScript 注册精确三工具；allowlist、Python registry 和描述统一。`p7_workspace` 的 tagged union 及 ActorPlan 参数可由模型实际表达；不只改工具文案。旧应用工具退出新默认路径，需要保留的历史解析不可成为双执行入口。
- [x] 跑 `npm --prefix packages/typescript/asterion-prime-extension test` 与 `uv run python -m unittest -v tests.test_prime_p7_research tests.test_prime_p7_solver tests.test_prime_p7_tool_registry tests.test_prime_p7_bridge_dispatch`；针对 obsolete 接口的测试更新为新行为，保留权限/identity/redaction边界。
- [x] 提交所属文件，并向 Task 3/4 交付一条脱敏 fixture 事件链：任务→计算→发布→计划→动作→失配→修订，用于同一故事的 UI 与集成验收。

## Task 3: 控制台协同、历史与生命周期

**Files:** 所有权表 Task 3；创建 `tests/test_prime_p7_solver_control.py`，更新 `tests/test_prime_p7_console_events.py`、`test_prime_p7_console_snapshot.py`（不存在则创建）、`test_prime_p7_console_session.py`、`test_prime_p7_console_server.py`。

**Interfaces:** 实现 D；消费 Task 2 的 solver events，输出 console public snapshot 和 operator 可读取的控制命令。不要解析 arbitrary stdout 补猜事件。

- [x] 实现独立 `SolverControl`：幂等 pause/resume/stop、活动计数、边界确认及绝对期限。暂停中的行动派发必须零增长；当前动作返回后才进入 paused，停止尚未清理时不能显示 stopped。

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

- [x] ConsoleSession/server 增加 pause/resume 路由与确认回执；控制请求到 operator 的路径复用本 run guest 映射，不能写入 worker 可发布产物集合。断连或未知回执显示请求未确认，不猜为成功。
- [x] 消费公共事件构建画面/任务/WorldMap/研究计划/反馈五区：真实帧与预测区分，已执行/未执行后缀明确；修订链接到反例，错误来源可区分状态/动力学/目标/实现。
- [x] 使用同一 Task 2 fixture 检查历史 event N 展示 revision N，而不是最终 revision；现场停止按钮不作用于被查看的历史 run。HUMAN 试玩与自主证据保持独立。
- [x] 按用户纠正沿用后台 DOM、HTTP 与实际导出 HTML 验收开始、暂停请求、已暂停、继续、停止请求、清理及历史回看。105 Python / 74 DOM 检查通过；不再要求打开 Chrome，浏览器插件连接不作为门禁。此处为 provider-free UI 验证，不代表真实求解胜利；无可计算总量时不显示百分比。
- [x] 跑针对 console/control unittest。用 sentinel 对公共 snapshot 断言不出现 stdout、prompt、provider payload、路径、源码；提交所属文件并交付 Task 4 控制握手格式。

## Task 4: 实际接线、共同复审与有限真实验证

**Files:** 所有权表 Task 4；修改 `src/asterion/applications/prime/resources/ipython-extension.mjs` 由构建产生，更新 `tests/test_prime_p7_native_installed.py`、`tests/test_prime_p7_official_installed.py` 与相关资源检查；同步 `CURRENT-STATE.md`、`DECISIONS.md`、`docs/status/INDEX.md`、`RESUME-NEXT-SESSION.md`。

**Interfaces:** 在 existing `build_p7_operator_resources` 注入 Prime host、只读研究 server、Solver、SolverControl、事件 sink。既有 runtime/runner/assembly 继续负责执行；只替换应用工具 dispatch 和 kernel host 接线。

- [x] 移除新运行路径上的旧可写 worker API，适配 native 与 official operator 到同一个通用 kernel；`p7/ipython_host.py` 仅保留必要兼容导出或删除重复实现。generic Prime 不反向依赖应用，不把 P1 coding assembly 当通用 kernel 启动器。
- [x] 默认 verified 路径的 `build_strategy_prompt`、`_initial_game_context` 与 continuation 同时切换：不因历史默认值 `replay` 注入旧认知表单、DSL 自动搜索或精确路线。显式 legacy/cognition 路径可保留原实现，不默认加载共享 Playbook/GameCognitionStore/SemanticCognitionStore 或成功 prefix；研究记忆是否复用必须由当前运行模式明确决定。
- [x] actor method_call 只接受新三工具对应请求；research server 与 action bridge 分离。为每次 cell/action 用真实取消 signal 替换当前 `_BridgeSignal.cancelled=False`，暂停门禁位于新派发之前。
- [x] 在既有 Prime continuation/round 边界接应用提供的 admission hook，暂停不继续生成新轮模型请求；通用 hook 不认识 P7 目标。应用明确注入 continuation prompt，移除默认提示中对 `p7_client` 的依赖。不增加外层自主循环来复制 PrimeSession。
- [x] 在 root 拥有的 `p7/research_runtime.py` 写薄适配器 `P7ResearchRuntime`，组合 generic host、Solver、control 和 read server，提供 `execute/admit_round/continuation_prompt/close`；现有 runtime_binding 接受它并向 generic Prime 注入 `before_round` async hook。不要给 PrimeLaunch plain-data 附加 live callback。一次模型 round 内含 tool cells，不能把整个 round 记作控制活动计数，否则暂停等待 round 结束、tool 又等待暂停解除会死锁；`before_round` 只做 admission 等待，活动计数仅覆盖真正的有界计算/环境动作。
- [x] 用一条实际 wiring 的 provider-free story 验证：cell 建模导出→publish→actor plan→Broker action→真实差异→workspace 修订→console 历史；checkpoint 重建 kernel 后强制校准；环境丢失不自动恢复游戏或重派未知动作。
- [x] 实现复审重点：WorldMap 是否改变下一次计算/动作、程序是否实际执行、原始证据与派生报告是否分离、pause是否真正截断后缀、旧工具是否仍暴露行动捷径、公共投影是否越界。修复结论后再扩大检查。
- [x] 依次跑 `npm --prefix packages/typescript/asterion-prime-extension test`、本次相关 Python tests、`make promotion-check`；执行 `make lint`、`make docs-check` 并按仓库要求完成必要 `make check`，既有无关失败记录其边界。确认 wheel 内新 Prime worker、新 P7 modules、打包扩展与 allowlist 一致。
- [x] 用固定预设执行 `make asterion-prime-p7-level-witness GAME=<已选择的本地游戏> LEVEL=1`。只选一个有限新运行，隔离旧 knowledge stores，不能注入人工路线、成功 prefix 或真实 SDK 离线搜索答案。选择已有数据且允许本地运行的游戏，由集成方在执行记录中写清确切 GAME 与 preset；命令成功仅证明实际结果，不据synthetic story预先宣称过关。现有 witness action cap 基于 human baseline，不能为得到成功偷偷扩大。
- [x] 检查真实证据中至少有一次“实际计算→语义修订/明确计划→真实反馈”的可追溯连接（程序搜索为actor说明，精确算法需另有源码证据才能独立审计）；若失败，记录第一个模型/控制/目标断点而不是盲目扩大预算。下一关迁移必须在全新 run 中自然连续过关，使用固定有限预设；旧 LEVEL=2 自动 replay prefix 的 witness 不能作跨关能力证据。再次求解只复用明确保存的规则/程序，不复用精确动作路线；无授权或外部阻塞则明确留作未完成边界，不标完整能力通过。
- [x] 记录实际命令、结果、动作数、RESET、停止原因、模型修订与控制台事件位置；修订 DSL-only 的旧设计决策。提交代码、生成资源、测试与状态文档，确保本次成果没有散落为未跟踪文件。

## 完成边界

Task 1–3 的单元验证仅证明各自接口，Task 4 的实际 wheel 运行才证明部署闭环。只有真实环境终局与可检索的模型→计划→反馈证据支持求解能力结论。没有下一关或恢复观察证据时，不把这些能力从代码存在推断为 Verified；最终状态分别记录已验证事实、当前判断、历史归档和未完成边界。

## 实测后补充：直接语义修订与行动主路径

本补充落实 spec 第 9 节，继续使用原三工具和唯一 Broker；不增加 runner、DSL 或强制计算次数。

`p7_workspace` 新增闭合请求：

```text
{op:'revise', base_revision, worldmap, task, evidence_sequences, correction}
```

- `worldmap`、`task`、`correction` 复用现有 publish 同形字段与边界；`worldmap.description_zh.trim()` 和 `task.goal.trim()` 必须非空，其余列表可以为空，未知模型可以 probe。`base_revision` 精确匹配当前版本；`evidence_sequences` 升序唯一且包含当前真实 sequence。初始行动同样先 revise，没有单 probe 例外。
- revise 创建不可变子 revision，只改语言 WorldMap、task、evidence 和 correction；继承 `model`、source/state refs 和 `reports`。继承报告的 checked 只表示原报告与原历史已比较，不认证新文字。revise 不接纳 model/reports/validation 字段，不制造计算事件；公共模型修订仍标 `origin=actor`，复用既有 `model_revision` 事件。
- context 增加 `needs_revision: bool` 与 `revision_reason: initial|prediction-mismatch|reset-applied|level-advanced|null`。初始为 true/initial。真实 plan 除原身份、start、revision 校验外，需要非空语义版本且 needs_revision=false。matched 计划可复用版本，不要求逐步修订。
- 实际预测失配、RESET 已执行、level-advanced 后置 needs_revision=true；下段计划前一次满足非空语义及当前证据的 revise 或 publish 可以清除。终局仍结束运行。失败或被拒的修订不清门槛；环境结果 unknown 的行动禁令独立存在，任何修订不能清除。
- `requires_calibration` 与 needs_revision 分开。kernel 丢失/恢复继续设置校准门槛；只有当前 kernel 实际可用且本次 revise/publish 包含当前证据及非空语义，才能清除校准。同一提交可清两个标记，不新增 KernelExport generation/receipt 协议，不以修改字段冒充进程恢复。
- 计划继续用现有 `workspace_revision`、`goal`、`assumptions` 连接公开推理依据与真实反馈。actor 对语言含义负责；非空校验不是模型正确性的认证。

实施由 Task 2 扩展 research/solver/prompt/TypeScript schema 与针对测试，Task 4 更新打包资源并集成。针对检查限于：初始拒绝空版本但允许直接 revise 后 probe；matched 复用；失配/RESET/换关分别阻止未修订后缀并接受当前证据修订；stale revision/current evidence 拒绝；source/report 原语义保留；kernel lost/环境 unknown 不可被 revise 洗白；模型事件在同帧历史中保持准确。真实验证继续固定有限预设，记录语言/程序模型如何影响行动，不为满足验收强迫无用 IPython 工作。


### Task 4 最终验收边界（2026-10-05）

已执行规定检查并记录失败，checkbox不表示全仓PASS：最终promotion3965tests/13fail4error4skip；未重复make check。扩展34pass6external skip、实际installed tests、lint/docs通过。修复provider复合工具ID的提交`721c8ae5`真实新局SP80前两关16动作/0RESET/3成功cell/4修订，sealed/replayed/cleaned。实际事件22→23→40→42和49→50→51→77→79串联计算、模型、计划、反例修订与换关；详细命令/证据见implementation review。最终运行没有导出程序源码/检查点，不能据此宣称跨run程序复用、恢复或冷/热改进。25游戏全量评估未运行也未获授权。网页验收遵循用户要求的后台DOM/HTTP/导出方式。


### 已授权后续有限验证（2026-10-05）

用户要求已过关保存提交后继续过关，并要求console网页存于持久目录。两关基线已提交保存。下一次只运行SP80 verified fresh LEVEL6，固定900秒/人类baseline动作cap518；同一运行内部自然跨关，保留其Prime namespace与WorldMap。已有封存进程无resume入口，不使用legacy prefix快捷接关。完成或有限预算结束后记录真实最高关、动作/RESET/cells/revisions及停止原因，默认导出到该run/p7-console.html。25游戏范围不扩张。无需改变生产代码或重复全仓门禁。


### 用户纠正：从第三关显式接续

取代前段freshLEVEL6尝试；该run已停止并如实记cancelled。实施限于application exact prefix loader、P7Invocation显式process resume selector、verified路线恢复/先验上下文及分账diagnostics、guest env传递和针对测试。Astra合同见spec§10。生产只由Sol resume_implementation实施，root集成状态与实际运行；测试优先exact source拒绝/restore失败/保持新版工具/预算分账，冻结后Astra复核和相关检查，再一次固定900s从L3继续到L6的实际wheel运行。旧fresh模型不重启，时间/动作上限不扩大。


### 后续包：25游戏console总览与网页接续

用户明确追加25游戏目录/过关回放、官网式总统计、本地评分；合同见spec§11。求解后台持续，阻塞关卡两次失败后换题，不另启全量sweep。

- [ ] Python轻量overview：固定model/seed/catalog，封存完整/partial完成prefix核对、整场RHAE、本地固定目录平均、失败与恢复开销保留、显示缓存无执行权。
- [ ] ConsoleSession/HTTP明确target与exact source，清除ambient resume/history，维持原单次有限preset和session控制。
- [ ] 网页总统计/25游戏/按game回放，默认续关及明确fresh，外部run只读跟随，历史cursor保留。
- [ ] 重点边界tests及独立变更review，实际目录/既存封存4关的后台HTTP/DOM验收；无需重复无关fullsuite。

实施：Sol分别拥有后端与assets，root集成design/state；Luna仅后台真实求解与private证据。下一真实尝试由相同已部署solver启动；console代码完成后不改变正在运行的sealed-source和guest。

### Task 5 closure and current boundary (2026-10-06)

The four console worklist items above are implemented and targeted-verified. Evidence recorded at checkpoint: Python overview 59 PASS, export 14 PASS, CLI 3 PASS, UI 85 PASS / 1 skip. Final actual static/export DOM acceptance passed 86/86 with 0 skips using the persistent `replays/sp80.html`; command and log are recorded in the live checkpoint. Root HTTP review and commit coordination remain pending. Latest mandatory promotion is non-PASS: 3990 test cases, 14 failures, 4 errors, 4 skips; one additional failure is unclassified. Do not describe all failures as historical or repeat the full suite.

Current UI contract details: overview is fixed to 25 games / 183 levels, exact `gpt-6.1-sol`/seed 0 WorldMap P7 records, and excludes legacy dc22/vc33 history/actions. Pick per game by progress, then RHAE, then fewer actions; whole-game denominator, unplayed=0. `/api/start` takes explicit target and exact resume source. UI opens latest selected-game replay, pins history cursor, and follows external runs read-only. Aliases: `replays/sp80.html`, `p7-console.html`; Make entries `p7-replay GAME=sp80`, `p7-controller`. Canonical fixed URL is `http://127.0.0.1:57515/`; legacy 56659 remains idle and is not the primary URL.

The SP80 6/6 witness is complete: run `p7-live-20261006001222-3a7662493aa44f01b109e5f9`, 143 actions (95 restored + 48 new), RESET=2, seal/replay/cleanup true, receipt 100. Earlier text claiming RESET=0 for this run is corrected; earlier runs had 0. Local standing is 1/25 games, 6/183 levels, 4%, not a formal benchmark. The current authorized local sequence is DC22 → VC33 → remaining catalog, one finite guest at a time; skip SP80. Two failures at a blocked level switch games and a success resets that counter. Active DC22 run identity and caps are in `docs/status/RESUME-NEXT-SESSION.md`; do not duplicate it.


### 2026-10-06 运行与官方提交授权更新

DC22 run `p7-live-20261006002338-7fc5ecf2b7ca4c5e8a827607` was interrupted by `_CallbackRejected` at `prime-event-type` / `pi.prompt`: 14 actions, 0 levels, 5 cells, cleanup true, unsealed/unreplayed. Treat as runtime interruption rather than solving failure; do not relaunch until root fixes the run path. Zero-level failure-experience reuse remains unconnected; root is preparing its contract.

After finite DC22 and VC33 attempts, the user authorized exactly one complete 25-task official submission. Pause all remaining local games, have root perform that submission and record official score/channel, then resume the local sequence. This does not authorize repeated/open-ended livebench.

### Task 6：跨尝试经验完整接入（spec §12，2026-10-06）

**Goal:** 失败、零关及中断尝试的研究、反例与程序在下一次实际送达 actor，并留下可追溯的新修订；不继承旧计划/证书/执行权。用户已授权实施，不再设设计确认关。所有修改留在既有 Prime/P7 路径，三工具名称保持 `ipython,p7_workspace,p7_execute_plan`。

**Ownership:** 核心 worker 负责新 `src/asterion/applications/prime/p7/experience.py`、`research_bridge.py`、`research_runtime.py`、`solver.py` 与其对应测试；root 负责 `operator.py`、console 投影/后端/assets、状态集成与真实运行。`research.py` 如需加 provenance 由核心 worker 单独负责。其他 worker 不修改上述文件；发生接口调整先通报，不回退彼此代码。

**Interfaces:** 核心产生 `load_experience(runs_root, *, game_id, seed, win_levels, model_id, current_run_id) -> ExperienceBundle`。Bundle 持有冻结 sources、compact actor context、private manifest 与 source-scoped `read(source_run_id, kind, *, start=0, limit=32, artifact_id=None)`；kind 限 `research|history|frame|artifact|cells`，拒绝未在 bundle 的 source。root 在 verified research 模式建立 bundle 并传入 `P7ResearchRuntime(..., experience=bundle)`；不依赖 resume prefix。`Solver.current_context()` 同时返回经验摘要与原 current observation；bridge 增加同一路由的 `p7_research.experience(source_run_id, kind, start=0, limit=32, artifact_id=None)`。方法命名可按代码风格调整，但必须在交付时给 root 精确签名，不由 root 重写 reader。

- [ ] **6.1 应用级来源加载与冻结。** 复用已有 research/digest/trace 验证逻辑，新增 reader 从显式 runs root 的直接子目录按稳定 run ID 顺序索引新版 WorldMap scope；精确核对 model/game/seed/win_levels/run/attempt，禁止 legacy fallback、人工来源与 symlink。summary 缺失时以有效 trace 身份与 research scope 建立来源；有 summary 则核对一致。未封存只接受连续完整 hash chain；尾残行截止，内部断链拒绝。显式记录 sealed/replay/outcome 与 unresolved 引用，不能用 integrity 替代事实验证。固定最多扫描 4096 个直接子 run、每源 trace 32 MiB/16384 records、revision 1 MiB/最多 16384 ancestry；超过限额显示截断或拒绝原因，不能静默称穷尽历史。初始 context 16 KiB，细读历史 32 项/响应 1 MiB。冻结 manifest 在本次 research 目录原子保存，至少记 source run/revision/trace head/export hash 与 trust。
- [ ] **6.2 研究与程序的失败保存。** 默认注入最新合格研究（WorldMap、task、correction、反例与程序索引），索引保留其他来源；选择旧 prefix 时仍纳入更新失败。当前 run 的 IPython execute 入口先保存 source/hash/call/generation，再写真实 completion metadata；每 cell 沿用 16 KiB、每 run 候选源码总量上限 4 MiB/256 cells，超限记 omitted，不阻断已授权求解。现有旧 trace 的精确 IPython call 只读提取为 inert source candidate；不执行、不给未返回调用补结果。显式 source/JSON exports 单独验证 kind/scope/hash，当前 actor 可读、改写、重新 export/publish；自动启动不调用任意历史 source。已有 Prime.restore 保留原职责，不新增 namespace/runner。
- [ ] **6.3 真实 actor/read bridge 接入。** 核心通过 constructor 注入 bundle，原 history/frame/artifact 方法语义不变，新增 source-scoped experience reader 只有读取权。operator 在实际初始 context 使用同一 bundle，并取消把跨 run 经验局限在 resume_prior 的条件；不改变 exact prefix 的失败行为。把 loaded digest、成功 read 的源/种类、候选源码或 export 的访问、后续 revision 与 correction 关联原子保存。当前 evidence_sequences 只能指当前 run；未校准、kernel lost、unknown action result 不能被导入解除。actor 可见内容与回执用同一 projection，避免只在 diagnostics 宣称 loaded。
- [x] **6.4 控制台真实消费投影（有限实现）。** 在既有 `compute_task` / `model_revision` timeline 中表达 loaded/source-trust/read/revision/program-match；不新增 dedicated panel、schema 或 tool。区分发现与消费，source/revision/message 能表明实际使用边界。不得宣称专用消费面板或超出 timeline 实际投影的状态。默认 latest 当前游戏，best route 分列，历史 cursor 不移动；私有源代码、路径、stdout 不进入公共回放。
- [x] **6.5 有界边界测试与变更评审。** Focused tests cover the implemented loader/actor/research bridge/projection behaviors, including no-finalizer omission-counter validation; latest root polish: 32 tests PASS. Independent review passed within this coverage. Do not imply every originally enumerated corruption or lifecycle matrix was exercised; untested cases remain outside this verification claim.
- [ ] **6.6 打包与有限真实验收。** 集成后依序跑 `npm --prefix packages/typescript/asterion-prime-extension test`、相关 Python 检查、`make promotion-check`，如实列既有/新增失败；有针对性修复后才开始下一次 wheel witness。使用现已授权 DC22→VC33 单 guest/900 秒顺序，先修好 native callback interruption；同阻塞关两次求解失败切题，runtime interruption 不算求解失败。记录 DC22 旧 run 的 source manifest、actor context digest、实际历史/cell/export 读取、新 revision/纠错及真实 action feedback；无 export 则程序恢复仍未验证。两游戏有限尝试结束后执行已授权的一次完整 25-task 官方提交，再继续其他游戏。提交代码和既有状态文档，Implemented/Verified/External-limited 分别记。

**完成判据：** 下一次零关重试无需成功 prefix 就实际获得失败研究，既能读反例也能读旧 cell 源码；旧 source 不会自行执行，新计划仍依据当前观察。控制台和私有回执可证明读入与本次纠错链。尚未经过同条件能力比较时只能声称经验链已接通，不能声称效率必然提升。


### Task 6 implementation checkpoint (2026-10-06)

Failure-experience reuse is committed as `12542476`; focused suite 37 PASS, joint verification 43 PASS, inert subprocess regression PASS (computed result 42); root polish latest 32 tests PASS. Complete-25 official preparation is committed as `c261633c`; preflight is ready with 25 exact task IDs, but no card has been opened and no submission made.

DC22 run `p7-live-20261006005914-31079cf165a443c496c180a1` ended at 79 actions, 2/6 levels, with trace sealed, replay verified and cleanup complete; guest inactive/MainPID 0. Root fresh HTTP overview now reports combined progress 1/25 games, 8/183 levels, local score 4.571429/100, 540 actual actions (178 restored + 362 new); SP80-only prior checkpoint was 4/100. Action 79 completed L2; the feedback label says L3 transition but there was no L3 attempt, so this is not an L3 reasoning failure. The actor consumed negative hypotheses and retained prior movement/discard-click assumptions. The prior run had five missing cell sources; its semantic/history evidence was loaded; new archive has ten cells and four exports. This is evidence of consumption, not guaranteed improvement or executable program restoration.

DC22 callback compaction remains incompatible: event 271 `compaction_start` arrived after 270 `turn_end` and before `agent_end`, while the prior 986 handler requires `agent_end`; error is `prime-native-callback` at `pi.prompt`. Sol owns fix/tests; hold the next launch until root validates a new wheel. Task 6.1–6.3 implemented; 6.4 delivered through existing timeline messages with no panel/schema/tool; 6.5 focused review/tests PASS (latest 32 checks, bounded coverage); 6.6 packaging and next live verification remain open.

Promotion is 4010 tests, 13 failures / 4 errors / 4 skips, NON-PASS; Sol is investigating. Feature changes remain pending integration to `main`, which user prefers promptly after closure.


### 2026-10-06 live-console follow-up closure

Local main now includes completed WorldMap/experience/console work, generic live/finalized per-level cognition provenance (`b074b5f4`/`ebc4542c`), and refresh-safe playback (`002f37a0`). Final full promotion PASS25 commands, related Python205 PASS, DOM86 PASS/one existing skip, actual served-HTML cognition21 checkpoints PASS. Chrome visual acceptance remains external-limited. DC22 is sealed/replayed4/6 (197 actual/191 completed-prefix actions); L5 attempt2 is active. Keep the two-unfinished-attempt rule and the one official25-task submission gate after finite DC22/VC33. The recovery checkpoint owns current processes, attempts and evidence limits; earlier pending-main/held-launch addenda are historical.
