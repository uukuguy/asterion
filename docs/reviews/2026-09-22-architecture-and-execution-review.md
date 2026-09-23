# Asterion 设计与代码深度评审及改进方案

日期：2026-09-22。代码基线：`f7c4f97b`。状态：**原始评审基线；后续实现与验证边界见文末“实施跟进”。本报告不授予新的运行权限或协议变更。**

## 结论与范围

保留现有的 Python 编排、精确 package/assembly 组合、顺序 runner、注入式 host services、TypeScript 契约验证与 Rust 受控执行分工。当前最有收益的工作是修复“接受、实际执行、完成、证据”之间断开的连接，然后沿已有边界收敛代码。

本次重点检查运行时会话、Prime P1–P7 集成、组合与来源绑定、日志、受控子进程，以及对应测试和设计文档。使用三个独立代码复审任务和有限的 provider-free 探针。生产 Python 共 336 个文件、139,441 行；这是范围背景，不表示逐行审查了全部文件，也不以代码行数评判质量。

没有运行真实模型、ARC benchmark、全量测试或 promotion。此前 `make test` 的 2943 项、2 项跳过是上一会话记录，本次未重跑。新的复现证明这些测试不能替代具体执行路径的验收。

## 已验证事实与优先级

| 编号 | 优先级 | 发现 | 本次证据 |
|---|---|---|---|
| R1 | 高 | 前一 prompt 的 settlement 被当成后一 prompt 的完成 | 真实本地子进程模拟 producer；两种 compact 配置均复现 |
| R2 | 高 | P3/P5/P6 公开组合路径可空执行成功 | compose + runner 探针：三者 runtime 调用、事件、产物全部为零 |
| R3 | 高 | 已验证包摘要没有绑定随后组合使用的 manifest 内容 | 临时 payload 同 ID/version 改内容后，原 bound package 得到不同 plan |
| R4 | 高 | 组合器忽略自身消费自身产物的依赖环 | 单 workflow 自消费事件通过 compose |
| R5 | 高 | 子进程取消与总时限不覆盖完整生命周期 | Python 入场取消遗留进程；Rust 500ms 请求 1223ms 后报 completed |
| R6 | 中 | compact_events 改变合法 compaction 的接受结果 | 同 transcript：False 被拒，True 通过 |
| R7 | 中 | 失败投影保密，但缺少稳定的诊断链 | runner/preparation 的异常转换代码与既有故障定位过程 |
| R8 | 中 | 文件日志逐次全量重读，累计解析量平方增长 | 64/128/256 次追加解析 2144/8384/33152 行 |
| R9 | 中 | 应用装配、验证证据与状态文档存在重复维护和过度推断 | provider/package/Make/acceptance 路径及状态文件交叉核对 |

“高”表示应在依赖该行为开展后续研究前修复，不等于已证明可被外部攻击。所有原始代码仍保持基线状态。

## R1：让一次 prompt 具有真实的操作边界

### 现状及原因

- `src/asterion/runtimes/pi_rpc.py:1065` 在 `agent_end` 返回 COMPLETE，后续 `agent_settled` 留在共享队列。
- 同文件 `:750` 已发送下一请求，`:770` 又把无请求 ID 的 settlement 当成该请求的 implicit ack。
- `src/asterion/agents/prime/execution.py:434` 接受 leading settlement 为本轮 terminal；`backend.py:771` 随后可以保存完成记录和 checkpoint。
- `tests/test_pi_rpc_reusable.py:53` 的常用 producer 只发 agent_end，不能揭示真实 producer 的尾随事件问题。

本机安装的 Pi 0.85.1 中，`dist/modes/rpc/rpc-mode.js:298` 在 preflight 后发 exact request-ID response；`dist/core/agent-session.js:771` 在 prompt 与 post-run continuation 后于 finally 发 settlement。不能用一个迟到的 settlement 推断新请求已被接受。

确定性复现结果：

```text
first  -> response, agent_start, message_update, agent_end；text='first'
second -> agent_settled；text=''
third  -> Pi RPC response did not match the prompt
```

`compact_events=False/True` 均复现。**这证明了队列归属缺陷；尚未重跑原始 P1 真模型，不能把该发现写成真实 P1 已修复或全部根因已穷尽。**“Pi 根本没有执行第二条 prompt”也不是现有 trace 能证明的结论：Asterion 可能提前返回并关闭仍在执行的资源。

### 建议设计

在现有 PiRpcSession 内建立单一操作所有者，集中负责请求 ID、session/generation、原生事件序列范围、ack、settlement、绝对 deadline 和预算引用。一个 session 同时只允许一个在途操作。

```text
ready → dispatched → acknowledged → running → settled → ready
             └─ 发送后失联/取消/归属不明 → uncertain → fenced
发送前取消 → cancelled（没有已发送副作用）
```

此图是内部状态语义建议，事件可能先于 ack 到达，实际 reducer 必须保留并验证这种先后关系。完成条件必须同时具备当前请求的 exact-ID 接受证据和该操作的 settlement 屏障；agent_end 只关闭一次 agent cycle，不能提前开放下一个 prompt。

settlement 只证明操作已停止，不代表任务成功；Pi 在失败路径的 finally 中也会发送它。签出 completed receipt 前仍须验证原生失败状态、工具调用与结果配对、应用结果和 oracle。

原生事件没有请求 ID 时，归属依赖串行所有权与明确结束屏障。对未知遗留事件不能简单丢弃后继续，也不能重新归属新请求。归属不确定时 fence，进入显式恢复或关闭。

不需要为此新增公共 runtime v2；先收口内部驱动契约，保持现有公共 stream 语义。

### 对 Phase 10 草案的修正建议

`docs/superpowers/specs/2026-09-19-asterion-prime-p1-verify-strategies-design.md:104` 让两个 kernel 共用 PiRpcSession、管道和队列，无法形成新的会话隔离。`execution.py:242` 每次 invoke 已重置事件列表，`:334` 的 round 状态本来就是局部状态。新 kernel 重置 sequence 又会与持续递增的 RPC sequence 冲突。

因此建议先修复 R1，再设计 verify 策略。需要独立审查者时，定义真正的 child session、独立 transcript、权限和预算归属；需要进程隔离时显式选择新 Pi subprocess。策略应服务于隔离要求，不作为未定位故障的自动 fallback。

草案 `:179` 的“close 撤销操作中一切状态变更”应撤回：IPython 工具副作用不具备通用回滚能力。atomic 应表示独占操作、精确归属和一次确定签出；发送后副作用不明必须保留 uncertain，不能声称回滚成功。同 live worker/RPC 的 attachment reconstruction 也不能写成任意新进程 restoration。

### 有限验收

连续三条 prompt；延迟 settlement；一次 post-run continuation；错误/缺失 ack；发送前取消与工具已执行后的取消。断言请求归属、文本、连续 sequence、receipt 和 fence；随后按已有有限 preset 重跑一次真实 P1 才能提升真实路径证据。

## R2：公开 application 的成功必须对应实际工作

P3/P5/P6 的 assembly 只选择 `policy.recursive-loop`、`policy.bounded-loop`、`policy.continual-loop`；对应 package provider 的 `implementations=()`。其 payload 虽然还包含可执行 capability manifest，但 assembly 没选入，package 也没绑定实现。

证据入口：

- `src/asterion/applications/prime/assemblies/prime-recursive-workflow.json:1`，以及同目录 bounded-autonomy、continual-improvement assembly。
- `src/asterion/capabilities/prime_recursive_workflow_native/provider.py:36`，以及相应 P5/P6 provider。
- `src/asterion/runner/composed.py:101` 跳过 policy；`:190` 返回空 ApplicationRunResult。

通过公开 Python compose/runner 接口实测：

```text
P3 bindings=0 runtime_calls=0 events=0 artifacts=0
P5 bindings=0 runtime_calls=0 events=0 artifacts=0
P6 bindings=0 runtime_calls=0 events=0 artifacts=0
```

这不是只看 runtime.run 空实现得出的猜测：该路径根本没有调用 runtime。修改 runtime.run 一处不能解决问题。独立 operator 的 fake-worker witness 不能证明这条公开路径执行了任务。

### 改进

1. 给每个应用装配其确切可执行 capability，增加唯一 implementation binding，接入已有 runtime/host workflow，并输出应用约定的 receipt。
2. 将 operator preset 变成同一组合执行路径的 host 配置与调用入口；fake/live 只替换边界外的驱动或服务，不复制业务 orchestrator。
3. 无法完成连接的 selector 暂时明确拒绝执行。metadata listing 可以保留其说明，但不能把空执行称为研究任务完成。
4. 在 application/provider 的“可运行应用”验证中要求至少一个可执行绑定及该应用必需的结果。不要粗暴禁止所有 policy-only 组合；纯策略组合在其他场景可能合法。

P6 还需清除 `p6/runtime_binding.py:220` 后的固定 identity/proposal 占位内容，确保 oracle verdict 决定结果；复用现有 HarnessCoordinator，保持单一授权、journal 和 rollback 所有者。

验收只需从选中 provider 出发的完整组合路径，加一个记录真实调用的 injected host：成功有工作与 receipt，失败/取消不会签成功。涉及 package/entry-point/resource 变更时再运行仓库要求的 promotion-check。

## R3：锁定摘要必须绑定实际执行计划

`capability_packages/preparation.py:107` 验证 payload；`applications/provider.py:318` 却从 catalog_roots 重新读取 manifest，`:330` 只比较 capability refs。ID/version 不变时，内容变化没有被原摘要约束。

复审者在临时副本中完成 payload 打开与 authority binding，再仅添加 `emits_events=['probe.changed']`；同一个 bound package 二次 compose 从 `()` 变成 `('probe.changed',)`，identity 相同。没有改动仓库 fixture。

**建议：** Prepared package 携带冻结的已验证 catalog 内容，后续 compose 从该快照产生 plan；若接口仍必须按路径读文件，须对实际解析并组成 plan 的同一份字节快照核对已绑定摘要，核对后不得重新打开文件读取内容。来源锁、验证、解析和组装必须引用同一个字节快照。不要扩展成全新注册中心或隐式扫描机制。

验收：相同 ref、不同内容的 load→compose 间修改被拒绝，或者组成原快照；两者必须选定一种明确语义。多包所有权、安装顺序独立性和既有 exact-lock 行为保持成立。

## R4：按边类型处理自身依赖

`capabilities/composition.py:107` 无条件删除自身 dependency，使一个 workflow 同时声明 emits/consumes `loop.done` 时通过组合。runner 只能提供先前能力的输出，无法满足这条执行前输入。

建议保留事件/产物自依赖并让拓扑环检测拒绝，或在构边时明确报自消费错误。先区分 capability 自描述与执行前数据依赖，不直接删除全部 self-edge 过滤而误伤允许的声明。

验收：自消费 event/artifact 两例拒绝，正常 DAG 不变；拒绝发生在任何 runtime/implementation 副作用之前。

## R5：取消和 deadline 覆盖资源的完整寿命

### Python 入场取消

`services/managed_controlled_executor.py:43` 持有已启动的进程，`:46` 在首次让出执行时被取消会跳过清理；失败的 __aenter__ 不会得到 __aexit__。复审者用真实 sleep 进程确定性取消，确认进程仍活着，并在探针 finally 手动清理。

建议进程一经取得立即建立资源 guard；所有入场失败和取消都执行有界清理，再传播原始异常。退出清理应拥有被等待完成的 task，不能只加 shield 后留下 detached cleanup。

### Rust 输出回收超出时限

`packages/rust/controlled-executor/src/process.rs:89` 只给 child.wait 设置 deadline；`:105` 后 join_capture 没有 deadline。子进程退出后，其后代若仍持有 stdout/stderr，捕获任务会继续等待 EOF。

对当前代码执行 offline cargo build 后，授权一个有限本地 Python fixture：parent 立即退出，fork 的 child 继承管道并睡眠 1.2 秒。请求 deadline=500ms，实测 1223ms 后返回 completed。该探针的所有子进程均已自然退出。

建议用一个绝对 deadline 覆盖启动、等待、输出读取和停止阶段，并明确有限的清理宽限。POSIX 下为受控任务建立可清理的 process group，超时/取消时清理组、关闭管道、终止并 join reader。声明其进程生命周期边界即可，仍不得声称它是 OS sandbox。

[Tokio Child 官方文档](https://docs.rs/tokio/latest/tokio/process/struct.Child.html#method.start_kill)明确区分发送 kill 与等待回收；本次缺陷的直接证据来自本仓库代码与探针。

验收：入场取消、普通超时、parent 提前退出但后代持有 pipe 三种情况；返回有界、进程已回收、reader task 结束。无需构造大规模进程压力测试。

## R6：先规范化 wire response，再做可选事件投影

`runtimes/pi_rpc.py:432` 要求 compact response 仅有 id/success；`_compact_rpc_event` 只在 compact_events=True 时删除 command/data。相同合法 producer 在 False 下报 `Pi RPC compact terminal is invalid`，True 下通过。

建议将 wire validation、command result normalization 与可选 trace/event 压缩分开。request ID、command 和必要结果首先验证，再投影为内部规范形态；不能让性能选项决定协议是否合法。

验收：同一正常、错误 ID、失败响应 transcript 在两种配置下语义一致。按 producer 真实消息契约构造 fixture。

## R7：保密与可诊断性同时成立

`runner/composed.py:173` 将不同执行失败收敛为一个分类；`capability_packages/preparation.py:85` 也丢失 unavailable、ambiguous、digest mismatch 的区别。`raise ... from None` 隐藏展示链但不删除 __context__；不能据此声称进程内原始异常已经彻底消失。问题在于缺少稳定、可检索的诊断捕获入口。

建议使用现有 host/service 注入方式提供私有诊断 sink，在异常首次被公共投影替换前捕获有限信息。公开结果只给封闭 reason code 和不透明 correlation ID；私有记录保存 stage、request/session identity、异常类型和受限上下文。默认不记录 prompts、答案、原始 provider payload、环境或凭据。

诊断关联优先使用协议已有允许字段或纯私有索引。若新增公共字段，必须按仓库契约变更流程同步 schema、Python、TypeScript 与有效/无效 fixtures，不能随意扩展 closed v1。

先覆盖 prompt/worker/oracle、package prepare、capability execution 三条高价值路径；复用 Pathlight/现有 private store，避免再搭一个平行日志系统。增加 sentinel 脱敏断言和一条可从公开 ID 定位私有原因的验证即可。

## R8：先减少重复工作，再改变日志存储设计

`control/journal.py:996` 每次 append 从头解析；position `:975`、replay `:1047` 也触发同一全量读取。客户端与 harness 又经常先取 position 再 append。

在空临时目录建立两个 binding 后，每次明确传 expected_position，保留实际 fsync：

| 追加条数 | 全量读取次数 | 重解析行数 | 本机耗时 |
|---:|---:|---:|---:|
| 64 | 64 | 2,144 | 0.0552s |
| 128 | 128 | 8,384 | 0.1944s |
| 256 | 256 | 33,152 | 0.7226s |

解析量为 `N*(N-1)/2 + 2*N`；先 position 再 append 的调用会额外扫描。本机耗时只说明本探针，不外推为模型任务提速比例。

建议分两步：

1. 在一个已加锁的操作内复用已验证视图，消除重复的 position/replay/append 读取与重复构造索引；上层 receipt projection 用增量 cursor。先保留原有前缀校验强度。
2. 真正长会话需要时，再设计分段封存、绑定摘要和派生 snapshot。必须先决定并审查“何时发现旧前缀被修改”的契约；不能仅凭 file size/mtime 缓存就取消现有篡改检测。派生 snapshot 永远不能自行恢复授权或覆盖 journal。

验收关注解析条数、恢复状态一致、idempotency、旧前缀变化与截断仍拒绝。数据库替换暂不作为首选。

## R9：把维护单位收敛到职责与证据路径

### 小范围重构

- `applications/prime/services.py` 2308 行横跨 context、child、continuity、autonomy、candidate。按现有 host protocol 拆模块，保留兼容导入和一个 operator composition root；P6 继续组合 framework HarnessCoordinator。
- `control/journal.py` 2318 行兼有文件存储、各子域 record 构造和验证。可以先拆 record codec/validators 与存储实现，保持一种 canonical encoding 和一个权威 journal；暂不做通用插件式 reducer 平台。
- `applications/prime/provider.py` 的重复记录构造、pyproject index、DCI acceptance 的 Prime assembly 硬编码应从同一份应用层精确 inventory 校验。metadata-only list 仍不得 import provider；不能为了去重增加源扫描或隐藏优先级。
- DCI acceptance 验证自己的产品契约，跨产品 distribution inventory 由单独的发行 gate 验证。新增 Prime 应用不应要求到 DCI 接受列表中维护同一组数量。

这些拆分服务于降低变更传播范围。先完成 R1/R2，避免在有缺陷的行为上做大规模搬家。

### 证据状态

当前建议使用以下边界描述，详细 receipt 继续指向已有 evidence 文件：

| 场景 | 可支持的结论 | 不可推断的结论 |
|---|---|---|
| P1 | 原有实现和历史 receipt 存在；最新交接仍记录真模型失败；本次复现队列缺陷 | 当前真实 P1 已完成 |
| P2 | 组合路径确实执行本地语料 retrieval 与 oracle | 仅凭该 operator 的零 token witness 推断真实模型长上下文能力 |
| P3/P5/P6 | 独立 operator 的 deterministic witness 与相关组件存在 | 公开组合路径已执行任务；本次已测为空执行 |
| P4 | fake-worker continuity/recovery 路径及其命名边界 | 真模型跨会话连续性全部完成 |
| P7 | 既有已记录的限定关卡 live evidence | 全游戏、多 seed、多任务或本次重跑通过 |

采用“应用 × 执行入口 × worker/driver × 环境 × 验证命令/receipt”的证据矩阵。优先补现有 ledger/verifier 的 provenance，是否向封闭 receipt 增加字段另做契约评审。

旧的 2026-09-05 review 已记录过 executable 被 runner 跳过的同类缺陷；当时的 research-kind 修复不能防止今天的 policy-only 应用。应增加“选中公开应用确实触达工作且产生该应用结果”的少量契约测试，而不是继续复制数量和 golden strings。

CURRENT-STATE 应精简为结构快照，去掉相互矛盾的“7/7”与“P6 未实现”段落；RESUME 保存最新事实和下一动作；MEMORY 只保存协作偏好。状态清理是证据修正的一部分，不应扩张成新的管理体系。

## 建议实施顺序

| 批次 | 范围 | 交付/验收 | 依赖与兼容性 |
|---|---|---|---|
| 1 | R1、R6 与 Phase 10 草案纠偏 | exact ack + settlement 操作边界；三 prompt/取消/compact 复现转回归；有限真实 P1 复验单列 | 保留现有公共 v1；先明确内部完成语义 |
| 2 | R2 与直接需要的 R7 | P3→P5→P6 共用公开执行路径，host fake 可替换；receipt 与副作用对应 | package/assembly 变更后按要求 promotion；模型能力另列 |
| 3，可与 1/2 独立并行 | R3、R4、R5 | 冻结来源绑定、自依赖拒绝、取消/超时清理 | 不改变合法 manifest 形状；收紧原本违反约束的行为 |
| 4 | R8、R9 | 有证据支持的日志优化、局部模块拆分、inventory 与状态清理 | 首先保持授权/摘要/恢复契约；避免全面重写 |

每批只做相关代码复审、边界回归和直接受影响路径；不要以反复全套门禁替代实现。性能优化看读取量和工作负载；正确性改进看副作用、receipt 和恢复状态。实际模型研究效果必须靠另行命名的有限真实任务证明。

## 本次验证记录

- 根代理独立重跑 R1、R2，输出与复审者一致；全部 provider-free。
- 复审者临时副本探针复现 R3、R4，真实本地 sleep 子进程探针复现 R5 入场取消；事后清理完毕。
- `cargo build --offline --quiet --manifest-path packages/rust/controlled-executor/Cargo.toml` exit 0；根代理随后用当前 binary 复现 R5 pipe 生命周期问题。
- 复审者对相同 compact transcript 复现 R6 两种配置不一致。
- 根代理 `_read_file_entries` 计数探针实测 R8，保留 fsync，不调用模型。
- 生产代码、schema、manifest、测试与配置未改；已有未跟踪 `.codex/config.toml` 保留。

后续修复不得把本报告中的局部复现直接提升为应用能力完成。新 evidence 应记录对应修复提交、入口和真实边界。

## 实施跟进（2026-09-22）

本节记录后续修复，原始复现和当时的“未实施”描述保留为基线。R1/R6 的 prompt 屏障与 wire 验证见 `00d5008a`、`3f92df84`；R2 的 P3 与 P5/P6 公共组合路径见 `b8f2f914`、`86f8ad63`、`11a4d00a`；R3/R4 见 `91ca07b1`，最终复审发现的来源身份漂移拒绝见 `6baffd9e`；R5 见 `fc947d87`、`d6a888c9`；R7 见 `5d2fdbef`、`8f5bd9aa`；R8 第一阶段见 `fe30a6cf`；R9 的 journal codec、Prime inventory、服务拆分及隔离 wheel 资源校验见 `5890f261`、`49cbb550`、`11a4d00a`、`921200d6`。所有变更保持公共 v1 contract，不等同于真实模型能力证明。

| 应用 | 执行入口 | Driver / worker | 环境 | 本次命令或既有 receipt 与结论 |
|---|---|---|---|---|
| P1 `prime.ipython-coding` | 已发布 provider + operator | Pi RPC / model | 操作者注入；本次为本地模拟 producer | `tests.test_pi_rpc_reusable` 验证精确 ack、settlement、三次连续 prompt 与取消。历史真模型 receipt 存在；本次**未重跑**真模型。 |
| P2 `prime.programmatic-long-context` | 已发布 provider + operator | 本地检索与 oracle，历史 preset | 操作者语料 | 历史 `make asterion-prime-p2-run` receipt `cac924ed…`；本次**未重跑**，零 token witness 不证明模型长上下文能力。 |
| P3 `prime.recursive-workflow` | 选中 provider → assembly → runner | 注入 child runner，确定性 fake worker | 本地临时 operator root | `tests.test_prime_p3_composed_runtime` 及 P3 operator 26 项通过；证明执行调用、期限、取消、身份与 receipt，**未验证 live worker**。 |
| P4 `prime.long-session-continuity` | 已发布 provider + operator | 确定性 fake worker | 持久 private root 的历史 preset | 历史 `make asterion-prime-p4-run`；本次**未重跑**，不推断真实模型跨会话能力。 |
| P5 `prime.bounded-autonomy` | 选中 provider → assembly → runner | 注入 loop，确定性 propose/verify/repair | 本地 operator root | `tests.test_prime_p5_p6_composed_execution` 与 P5/P6 139 项通过；证明成功路径确实工作并封签，limits preset 仍单独拒绝。 |
| P6 `prime.continual-improvement` | 选中 provider → assembly → runner | 注入 candidate store / 单一 HarnessCoordinator / oracle | 本地 operator root | 同上；覆盖真实 candidate admission、holdout、promotion、取消逆向与 recovery-required。**未证明持久恢复或 live model**。 |
| P7 `prime.arc-agi-3-solving` | 已安装 wheel 的 operator preset | 独立安装的 Pi + 外部 ARC engine | 历史 Orb / 外部数据 | 历史限定 Level-1 receipt `c00e3263…`，见 `../status/ASTERION-PRIME-P7-EVIDENCE.md`；本次**未重跑**，不代表全游戏或多 seed。 |

**2026-09-24 后续 P1 证据**：上表记录的是 2026-09-22 评审修复当日边界。之后，旧 main `cbe668f3` 的有界 installed-wheel 运行在 stage-one oracle 因仅有 1 个 cell 被拒收；评审分支 `43fea703` 在相同 operator 配置和 preset 下完成两阶段并签发收据 `ab24c3d0ca04b760d377fcd225bb222cea907aaea9fc2ff4316f5d773ac74354`。两次轮次的阶段和 wheel 摘要见 `../status/PRIME-P1-P7-ACCEPTANCE.md`。这是一轮真实模型成功，不是长期稳定性结论；用户原始失败运行没有可回放的内部记录。

验证：`make check` 通过（2990 项 Python 测试，2 项跳过，并通过 TypeScript、lint、文档、Rust 测试与构建）；`make promotion-check` 在隔离副本中通过（25 条命令，provider 操作 0，完整数据集未运行）。最终复审额外发现来源身份漂移绕过，`6baffd9e` 补了 `source_id`/`source_kind` 拒绝测试并修复。详细命令与证据边界见当前 `RESUME-NEXT-SESSION.md`。

边界：R8 仍对每次独立文件追加验证全部旧前缀，保留篡改发现时机；长会话分段封存须先审查恢复契约。R7 私有 sink 是操作者可注入的进程内关联点，未提供持久诊断存储。R5 用进程组清理可控命令树，但不能约束改变凭据或脱离进程组的后代，也不是 OS sandbox；取消与同步 `spawn()` 之间尚无原子化调度门闩。P6 旧的底层结果 tuple 含历史错误分类，不能单凭文字 `rolled-back` 当作实际逆向证据；公共组合 host 另行核验 coordinator revision 与 baseline，并在无法证明时拒绝成功。真实 P1 模型路径、完整 benchmark、持久恢复与诊断均未由本次通过的命令证明。

## 附录：两个关键缺陷的最小复现

在仓库根目录执行。命令打印观察值，exit 0 仅表示探针运行完毕；判断缺陷须看输出。它们不读取 operator 配置、不调用模型、不修改仓库文件。

### R1：连续 prompt

```bash
uv run python - <<'PY'
import asyncio, sys
from pathlib import Path
from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcSession

class Signal:
    cancelled = False

producer = '''import json,sys,time
for line in sys.stdin:
 r=json.loads(line)
 if r['type']!='prompt': continue
 if r['message']=='second': time.sleep(0.15)
 for e in [
  {'type':'response','id':r['id'],'success':True},
  {'type':'agent_start'},
  {'type':'message_update','assistantMessageEvent':
   {'type':'text_delta','delta':r['message']}},
  {'type':'agent_end'}, {'type':'agent_settled'}
 ]:
  print(json.dumps(e),flush=True)
'''

async def main():
    for compact in (False, True):
        session = PiRpcSession(PiRpcConfig(
            (sys.executable, '-u', '-c', producer), Path.cwd(), {},
            deadline_seconds=3, compact_events=compact,
        ))
        await session.open(signal=Signal())
        try:
            for prompt in ('first', 'second', 'third'):
                try:
                    result = await session.prompt(
                        prompt, signal=Signal(), on_event=lambda e: None)
                    print(compact, prompt, [e.type for e in result.events],
                          repr(result.final_text))
                except Exception as error:
                    print(compact, prompt, str(error))
        finally:
            await session.close()

asyncio.run(main())
PY
```

### R2：公开组合路径是否执行工作

```bash
uv run python - <<'PY'
import asyncio
from asterion.applications.provider import compose_installed_provider
from asterion.applications.prime import provider as providers
from asterion.applications import first_party_packages as packages
from asterion.runtime.factory import RuntimeFactoryRegistry
from asterion.runtime.host import RuntimeManifest
from asterion.runner.composed import run_composed_application

class SpyRuntime:
    def __init__(self, capabilities):
        self.calls = 0
        self.manifest = RuntimeManifest(
            runtime_id='asterion.prime', capabilities=capabilities)

    async def run(self, request, *, signal=None):
        self.calls += 1
        raise AssertionError('runtime.run reached')
        yield

async def main():
    for name in ('recursive_workflow', 'bounded_autonomy',
                 'continual_improvement'):
        package = getattr(packages, f'create_prime_{name}_native_package')()
        provider = getattr(providers, f'create_prime_{name}_provider')()
        composed = compose_installed_provider(
            provider, runtime_factories=RuntimeFactoryRegistry(()),
            installed_packages=(package,))
        plan = composed.applications[0].assemblies[0].plan
        runtime = SpyRuntime(plan.runtime_capabilities)
        result = await run_composed_application(
            plan,
            implementations=tuple((b.capability_ref, b.implementation)
                                  for b in package.implementations),
            runtime=runtime, run_id='review-run', input_text='review',
            host_services={key: object() for key in plan.host_capabilities})
        print(name, 'bindings', len(package.implementations),
              'runtime_calls', runtime.calls, 'events', len(result.events),
              'artifacts', len(result.artifacts))

asyncio.run(main())
PY
```

SpyRuntime 若真正被调用会抛错；基线上三个应用均正常返回且所有计数为零，正是需要修复的结果。补上 executable 连接后，这个探针应改变观察结果，再改为有实际 host 行为与 receipt 断言的正式回归。
