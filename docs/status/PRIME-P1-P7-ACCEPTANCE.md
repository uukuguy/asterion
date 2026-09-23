# Asterion Prime P1–P7 验收指南

> Updated: 2026-09-24. P3–P6 默认 `-run` 命令已改为有界真实模型应用运行；旧确定性路径改名 `-witness`。
> 这份文档给"想要快速理解每个应用在做什么、跑得通什么、还有哪些没验证"
> 的人看。

2026-09-24 本地已安装 wheel 实跑：P3 两个独立 Pi 会话完成子任务与汇合；P4 两个独立进程完成固定任务状态的提交与恢复；P5 模型首轮候选通过语义校验（0 次修复）；P6 模型候选经独立 holdout 改进检查并在项目范围促升。四者都只有一次固定小任务成功，不是稳定率、通用编码能力或完整论文复现。以下旧章节中的 deterministic 结果仅指各自 `-witness` 和 `-run-limits` 路径。

## 文档怎么读

- **7 个应用每个一节**,顺序按官方迁移顺序:**P7(锚)→ P1 → P2 → P4 → P3 → P5 → P6**。
- 每节包含 5 块:
  1. **用它做什么** —— 一句话目的 + 它解决什么具体问题。
  2. **怎么设计的** —— 它依赖哪些底层服务,核心套路是什么。
  3. **Prime 能力** —— 它展示了 Asterion Prime 的什么原生能力。
  4. **怎么验收** —— 跑哪条命令,期望什么退出码,关键 receipt 摘要。
  5. **边界与未验证项** —— 哪些是已证明的、哪些是设计选择但还没端到端证明的。
- **附录 A**:每个应用对应的设计/计划/决策条目,以及遵循的架构约束。
- **附录 B**:跨应用的硬约束(所有应用都遵守的)。
- **全文术语表**见附录 C。说人话为主,黑话只在第一次出现时标注一次,后面直接用。

## 验收前置条件

所有应用都跑同一条路(已安装在 `src/asterion/applications/prime/`),都需要这几样东西:

| 项目 | 怎么来 |
|---|---|
| 安装好的 Pi(`@earendil-works/pi-coding-agent@0.85.1`) | Homebrew 全局 npm;在 Orb 内通过 `/mnt/mac/opt/homebrew/...` 访问 |
| `node@22` | 必须是 v22+(Pi 用了 `node:fs.globSync`);Orb 默认 v20 不行 |
| `DEEPSEEK_API_KEY` | 仓库根 `.env` 里(已存在) |
| `ASTERION_PRIME_OPERATOR_ROOT` | 当前 checkout 根 |
| `ASTERION_PRIME_PI_ENTRY` | 装好的 Pi 的 RPC 入口路径 |
| `ASTEROID_PRIME_P{N}_PRIVATE_ROOT` | 每个应用一个独立私有根(`mktemp` 即可) |

**一个跑通 P1 的最小命令例子**(其它应用换变量名即可):

```bash
export ASTERION_PRIME_OPERATOR_ROOT="$(pwd)"
export ASTERION_PRIME_PI_ENTRY="/mnt/mac/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js"
make asterion-prime-p1-run
# 期望:退出码 0,输出最后一行是 JSON receipt,digest 字段非空
```

如果你只看一眼"系统是不是真的跑通了",**最简单的方法是直接跑每个应用的 `make` 命令看退出码 0**。详细 receipt 校验留给自动化。

---

## P7 — 跑通 ARC-AGI-3 第一关(research preset)

### 用它做什么

让模型在浏览器/IPython 环境里**玩 ARC-AGI-3 这种多关谜题游戏**,通过调用工具、做动作、记笔记、看反馈,直到过关。它是整个 Asterion Prime 计划的"锚应用"——其他 6 个应用的能力都在它之上扩展。

### 怎么设计的

- **离线题库 + 在线推理**:ARC-AGI-3 的题通过 `ASTERION_PRIME_ARC_ROOT` 注入(operator 拥有的目录,带两个 wheel:`arc_agi-0.9.9-py3-none-any.whl` 和 `arcengine-0.9.3-py3-none-any.whl`)。
- **可观测、可回放**:每次跑都封一条带 SHA-256 摘要的 trace,事后能用 `compare_prime_p7_runs.py` 对比历史日志。
- **资源隔离**:动作通过 IPython worker 跑,worker 是受限的(`prime.ipython` host service),不能任意访问文件系统。

### Prime 能力

**端到端的 LLM agent 完整循环**——接收题面、思考、执行、观察反馈、根据结果调整,直到分出胜负或时间耗尽。这是 Asterion Prime 的"招牌能力"。

### 怎么验收

```bash
export ASTERION_PRIME_ARC_ROOT="$HOME/sandbox/agentic-2026/external-prime/arc-agi-3"
make asterion-prime-p7-solve
```

上面的命令保留历史默认题 `ls20-9607627b` / seed `0`。要选择本地已准备的新题 `tu93-0768757b` / seed `0`，在同一条 preset 上设置精确身份：

```bash
export ASTERION_PRIME_ARC_ROOT="$HOME/sandbox/agentic-2026/external-prime/arc-agi-3"
make asterion-prime-p7-solve \
  ASTERION_PRIME_P7_GAME_ID=tu93-0768757b \
  ASTERION_PRIME_P7_SEED=0
```

选择值由 Makefile 经 Orb 注入给应用；引擎、Broker、回放、密封 trace 和公开 receipt 使用同一 `game_id`/`seed`。公开 receipt 的 `selection_receipt_sha256` 还将题目身份、能力收据和 Broker 回放摘要绑定在一起；原 `receipt_sha256` 仍是能力层收据摘要。这个 preset 在完成**一关**后停止，内部上限为 500 个原始动作、128 次 callback 和 1 小时；它会实际调用模型。新题目前只做无模型预检，尚未启动该付费求解。

**期望**:退出码 0;输出有 `receipt_sha256`、`partial_game_score`、`terminal_reason`。历史通过跑(receipt `c00e3263cb...`,2026-09-14)——20 个原始动作、40 个 IPython 单元、`ls20-9607627b` 第 1 关、`partial_game_score=3.571429`、`terminal_reason=level-completed`。

### 边界与未验证项

✅ **已验证**:Level 1 / 种子 0 / `deepseek-v4-flash` 下通过;trace 完整、回放通过、清理干净。
⚠️ **设计选择但未端到端验证**:多关 / 多种子 / 多游戏 / 完整 benchmark;`promotion` 仍是 `unpromoted`(只跑过一次的边界)。
ℹ️ **历史说明**:P7 是原验收文档写作时唯一直接跑真模型的见证。P1 与 P3–P6 后来已有各自固定有界真实运行；P2 的能力边界仍见本节。
ℹ️ **P7 没有独立的"native spec"**:它是 Phase 3 的产物,设计沉淀在 `docs/superpowers/specs/2026-09-12-asterion-prime-p1-p7-native-detachment-design.md` 的 P7 应用章节里。

---

## P1 — IPython 代码编写(支持上下文压缩)

### 用它做什么

让模型在**长会话里持续写 Python 代码**,而且会话撑爆 context 窗口时**自动压缩 context 但保留已执行的代码状态**。压缩后,之前定义的变量、文件、计算结果都还在——只是 context 里被替换成摘要,需要时再通过 IPython 拿回来。

### 怎么设计的

- **两阶段执行**:先写文件、校验、再用 IPython 单元执行(IPython 作为受限 worker,不是完整 Python)。
- **自有压缩逻辑**:压缩 prompt 不来自 Pi 自己的内置实现(那个会泄露 IPython 内置状态);Asterion 用 Pi 提供的扩展点 `session_before_compact` 在自己侧接管压缩,自己向 Pi 发起一次模型调用来生成摘要。
- **Oracle 验证**:最后有一个 `prime.p1-oracle` 检查所有执行结果是不是符合预期——不通过就拒收。

### Prime 能力

**长会话下的有状态执行**——这是 Prime Agent 论文的核心卖点,也是 Prime Agent 最自豪的能力。

### 怎么验收

```bash
make asterion-prime-p1-run
```

**期望**:退出码 0;最终公开 JSON 包含 `run_id`、`status="completed"` 与 64 位 `receipt_sha256`。stderr 的阶段流应经过 `stage1.oracle.complete`、`compact.persist`、`resume.persist`、`stage2.complete`、`oracle.pass`、`runner.terminal`。

**2026-09-24 当前证据**:旧 main (`cbe668f3`) 的一次有界 installed-wheel 实跑在 `stage1.oracle.start` 后返回 `recovery-required`;私有、只打印谓词名的诊断确认 oracle 当时只见 **1 个 cell**,要求是 2 个。评审分支 `43fea703` 用相同 operator 配置、相同入口与有界设置实跑到 `oracle.pass`,最终 `run_id=p1-9991055483f5334e0339320c`、`status=completed`、`receipt_sha256=ab24c3d0ca04b760d377fcd225bb222cea907aaea9fc2ff4316f5d773ac74354`。两次 wheel SHA-256 分别为 `376e1da1178ea72ecaa1bc3e2f7473d42be9ccc139e91aeb2a257218996f73bb` 与 `7e869fdb0ec6ef84c82fd4cd36b11ced9b04cda8be89332eb3e1b8f0bac39e0b`。私有安全日志在 `.asterion-private/p1-safe-run-20260924.log` 与 `.asterion-private/p1-review-safe-run-20260924.log`;本文件只记公开阶段与摘要。评审分支已合入 main,但合并后的 main 未再次执行付费 preset。这是一轮完成证据,不是稳定成功率统计。

### 2026-09-19 历史诊断（以下路线判断已被后续修复取代）

**2026-09-19 实测**(`make asterion-prime-p1-run` 现场跑):退出码 **1**,JSON 是 `{"receipt_sha256": null, "run_id": "p1-03b3eb6b55e94c5950aae07f", "status": "recovery-required"}`。stage 流:`backend.open → host1.open → runner.start → stage1.setup.start → stage1.setup.complete → stage1.verify.start → host1.close → worker.close → backend.close → runner.terminal` —— verify 阶段没 emit `stage1.verify.complete`,host/worker 立刻被关,runner 直接出 terminal。也就是说**verify 还没回,会话就被回收了**。

**2026-09-19 第二次实测** (在应用协议层 A 修复后):stage 流**部分进展**到 `stage1.verify.start → stage1.verify.complete → stage1.oracle.start`,然后 `host1.close` —— 协议层完全通过,但 oracle.verify_stage_one 在 worker.snapshot 上拒收。

**重要更正 (2026-09-19 18:01, 后续独立验证)**: 之前在 journal 17:24 那条里写的 "剩余 bug 是 Pi 0.85.1 reuse path 功能回退, 第二次 prompt 没让 IPython cell 执行" **是错的**。host 上独立 RPC probe (直接 spawn pi-coding-agent rpc-entry.js 连发两条 prompt) **完整确认 Pi 0.85.1 能正常连续处理多次 prompt** —— 两次都产生完整 `message_start → message_update × N → message_end → turn_end → agent_end → agent_settled`。**真实根因在 Asterion 端**, 不是 Pi 端 —— 嫌疑是 Asterion 发的 prompt request 带了某种参数 (sessionId / generation / flag) 让 Pi 走 reuse early-settled 路径, 或 Asterion 在两次 prompt 之间调了 session.compact 让 Pi session 进入 settled-but-reuseable 状态。在没查清 Asterion→Pi 状态污染的精确路径之前, **绕过 reuse 是最干净的解法** (用户的判断: "verify 用另一个 pi 进程是符合隔离独立策略的")。

**历史 6 次跑的 digest**(`d97808e2` / `f4a4c19a` / `ac3fbb1c` / `d15c9b45` / `400c45dc` / `838f2db6`)是 **D-2026-09-16-01 接管式压缩方案落地之前**的早期形态跑出来的;它们证明"压缩后跨会话状态保持完整"的合约在那个旧实现下成立,**但不能套到当前代码**。

**Root cause (2026-09-19 完整定位, user-driven debug)**: 5 次诊断 traceback 找出完整链 —

1. Asterion 第二次 `_prompt` (`p1-verify`) 时,Pi 发的事件**第一条就是 `agent_settled`**,完全跳过 `response`(prompt acknowledgement)事件。setup 那轮走的是「先 `response` 后 `agent_start/.../agent_end`」顺序;verify 那轮是「直接 `agent_settled`」(没 response)。**这条是事实**,但解读需要更新 —— Pi 自身能连续 prompt,Asterion 这边的某种状态让 Pi 走 reuse early-settled。
2. `runtimes/pi_rpc.py:725-772` 的 `drive_prompt` 状态机**只看 `response` 事件作为 ack**(`line 757: if event.get("type") == "response": ... acknowledged = True`)。`agent_settled` 到达时 on_event 返回 COMPLETE,line 766 收 COMPLETE,line 767 `not acknowledged` 为真 → `raise RuntimeError("Received agent_settled before prompt acknowledgement")`。
3. RuntimeError propagate 到 `execution.py:469` driver call → `execution.py:479 except Exception:` 接住 → emit `run.failed` (`code="asterion_prime_failed"`) → backend.py:766 `status="failed" != "completed"` 抛 PrimeBackendError → backend.py:797/818 `except Exception: ... from None` 又吞掉原始 cause → 转 `recovery-required`。
4. **`a581a56c` (2026-09-19) 修了 bug 的第一半**(`execution.py:366` 把 `agent_settled` 加入 benign-trailing 集, 让 `handle_event` 接受它)。**A 修复 (commit `69787da6`) 修了 bug 的另一半**——`drive_prompt` 的 ack 状态机 + `execution.py` 的 round-terminal check 都没把 `agent_settled` 当合法 round 终结。

**应用的修复 (A 方案, 已 commit `69787da6`, 2026-09-19)**:

1. `runtimes/pi_rpc.py:751-781` — `drive_prompt` 新增 `settled_seen` 标志,`agent_settled` 事件出现时设它,COMPLETE gate check 改成 `if not acknowledged and not settled_seen: raise`(允许 `agent_settled` 当 implicit ack)。
2. `agents/prime/execution.py:362-372` — 把 `agent_settled` 从 benign-trailing 集拿出来(不让它绕开 round-terminal 处理)。
3. `agents/prime/execution.py:431-444` — 新加 `if event_type == "agent_settled"`: leading 位置(轮未终止)时设 `round_terminal_seen=True`,trailing 位置(已 agent_end)时 silently ignore。
4. `agents/prime/execution.py:539` — round-terminal check `current_round[-1].type != "agent_end"` 改成 `current_round[-1].type not in {"agent_end", "agent_settled"}`。

**修复进展**: 协议层完全通过(stage 流从 `verify.start → close` 进展到 `verify.start → verify.complete → oracle.start`)。**剩余 bug**: oracle.verify_stage_one 在 worker.snapshot 上拒收,因为 verify 那条 prompt 物理上没让 IPython cell 执行。**这条不是因为 Pi 0.85.1 不能连续 prompt**, 而是因为 Asterion 端跟 Pi session reuse 之间有未查清的状态污染(下一次 P1 真模型路径 session 应该走"verify 用独立 Pi 进程"策略, 见 D-2026-09-19-04)。

### 当前边界

- P1 本次完成运行使用真实 Pi 子进程与模型;此前用户失败运行的内部临时记录已清理,不能当作可回放证据。
- 一次成功不证明跨模型、跨任务或多次运行的稳定率。P2 的零 token witness 与 P3–P6 的旧确定性 worker witness 不能替代各自后来完成的固定小任务真实运行，也不能据此推断广泛能力。
- 2026-09-19 的独立 verify 进程提案是历史方向;后续精确 request-ID ack 与 settlement 屏障已修复本次复现的连续 prompt 缺陷,不应把旧提案当作当前必做修复。

---

## P2 — 程序化长 Context(用一个外部 corpus 做检索)

### 用它做什么

让模型处理**比它的 context 窗口大得多的资料**(比如一大坨代码库或文档),通过**程序化的方式**(不是直接塞 prompt 里)拿需要的片段,再根据片段回答问题。整个 corpus **不会进 prompt**——只让模型"看"它需要的部分。

### 怎么设计的

- **外部语料作为 operator 资源**:`ASTERION_PRIME_P2_CORPUS` 指向一个目录(不绑定任何 Python 代码到 Asterion),模型通过 `prime.p2-oracle` 这个 host service 程序化检索。
- **零知识证明**:oracle 不仅回答问题,还告诉调用方"我读到的片段摘要是 X",用来证明"我确实读了,没瞎编"。
- **这是 P1 的超集**:P2 复用 P1 的 IPython session 和 oracle 形态,只换掉语料来源。

### Prime 能力

**程序化长 Context 处理**——Prime Agent 论文强调的"用代码读写 context"能力,而不是"context 装不下就放弃"。

### 怎么验收

```bash
export ASTERION_PRIME_P2_CORPUS="/path/to/some/corpus"
make asterion-prime-p2-run
```

**期望**:退出码 0;输出 JSON 含 `answer` + `slice_digest`(oracle 检索到的片段摘要)。历史通过跑(receipt `cac924edc5e12b9cb5d1d88e17ac547bd82ac00328dbab74de5157cc7217e0e5`,deterministic across host and Orb)。

### 边界与未验证项

✅ **已验证**:50 个 P2 单元测试通过;oracle 的 slice digest 一致;P1 的 102 个测试 0 回归。
ℹ️ **fake-worker 还是真模型**:make 目标走**真 Pi 子进程**(同 P1)。
ℹ️ **隐含约束**:语料不进 prompt——这是验证的一部分,oracle 会在 evidence digest 里记录"实际读了哪些文件",事后比对可证。

---

## P4 — 长会话的断点续传

### 用它做什么

让一个长任务**进程死了之后能从断点继续**——不是在原进程恢复(那太脆弱),而是**新进程接管旧进程留下的状态**,从上次成功提交的地方往下做。

### 怎么设计的

- **新 host service `prime.continuity-store`**(operator 拥有的私有目录):持久化身份快照 + 已提交的 checkpoint。
- **跨进程不变量**:新进程接管时,**身份字段必须严格匹配**(`pi_command_sha256` / `extension_binding_fingerprint` / `ceilings_sha256` 必须一致);只有 generation 可以 +1,worker 身份可以换。如果不匹配,直接拒收。
- **固定双进程 preset**:`make asterion-prime-p4-run` 在本地已安装 wheel 中启动独立 commit/recover 进程，共用一个新的私有 checkpoint 根。旧 Orb 确定性路径为 `make asterion-prime-p4-witness`。

### Prime 能力

**跨进程的 session 续接**——这是 Asterion Prime 的"恢复合同"能力,Prime Agent 自己实现的代价是引入一个 supervisor 进程,Asterion 用更强的身份绑定来避免。

### 怎么验收

```bash
make asterion-prime-p4-run
```

**期望**:退出码 0；输出 commit/recover 两条真实模型结果，二者各有 `model_call_count == 1`，recover 的 `prior_checkpoint_sha256` 等于 commit 的 `checkpoint_sha256`，generation 增 1。

### 边界与未验证项

✅ **已验证**:2026-09-24 本地真实 Pi 两个独立进程完成固定任务状态恢复，并封存第二代 checkpoint；注入测试证明暂态模型失败后同根可重试；旧 deterministic fake-worker 可用 `-witness` 重跑。
ℹ️ **恢复范围**:固定任务 transcript 被新进程消费；任意 IPython 内存或任意长任务状态恢复尚未验证。
ℹ️ **为什么不是 supervisor**:Phase 6 原本考虑过引入 supervisor 进程(Pi 实现的做法),但那是 Phase 1 已经砍掉的"跨进程运行时依赖"模式。新设计用更强的不变量(identity 字段对齐)替代 supervisor 守护。

---

## P3 — 递归子任务

### 用它做什么

让一个 Asterion Prime 会话**在执行中召唤子会话**,把子任务交给子会话做完,再把结果合并回主会话。同时**严格限制**深度、并发、预算、取消——一旦触碰红线,直接拒收、不再继续。

### 怎么设计的

- **新 host service `prime.child-runner`**(默认进程内):主会话用一个 `asyncio` 工厂在同一进程里创建子会话,共用 session 后端的预算闸门。
- **5 条硬约束(同时生效)**:
  - `MAX_DEPTH = 2`(主 + 1 层子)
  - `MAX_CONCURRENT_CHILDREN = 1`
  - `MAX_CHILD_COST_USD = 0.10`
  - `MAX_TOTAL_DURATION_MS = 60_000`
  - 任一触碰 → 结构化 `child-admission-refused::*` 拒收,**不重试不 fallback**
- **限额路径是独立 target**:`make asterion-prime-p3-run-limits` 在同进程跑 4 条不同拒收(depth / concurrency / budget / cancellation),每条一条 JSON。

### Prime 能力

**有限度的递归合成**——可以自己召唤自己做事,但有边界。Prime Agent 论文里 RLM (recursive language model) 的概念在 Asterion 这边变成"显式的 child session + 显式的限额"。

### 怎么验收

```bash
make asterion-prime-p3-run            # 正常路径
make asterion-prime-p3-witness        # 旧确定性结构见证
make asterion-prime-p3-run-limits     # 4 条拒收路径
```

**期望(正常路径)**:退出码 0;JSON 含 `child_run_id` 非空、`depth_reached == 2`、`child_generation == root_generation + 1`、`refusal_reason == null`。

**期望(限额路径)**:退出码 0;输出是**4 条记录**(用 `jq -s slurp + .[N]` 索引),每条对应一条限额场景:`depth-exceeded` / `concurrency-exceeded` / `budget-exceeded` / `cancelled`。

### 边界与未验证项

✅ **已验证**:子会话被接纳 + 结果合并 + 4 条限额路径都按预期拒收。
ℹ️ **真实运行边界**:默认 `-run` 用两个真实 Pi 文本会话；`-witness` 与 `-run-limits` 仍用 deterministic fake-worker。没有验证 IPython worker 中的递归工具调用。
ℹ️ **深度 > 2 没测**:`MAX_DEPTH = 2` 是见证合约,不是框架硬限。框架层面其实可以更深,但 P3 不证明。
ℹ️ **subprocess supervisor 路径没实现**:`D-2026-09-18-02` 明确把"用 supervisor 隔离大 context 子会话"作为后备方案保留,但 Phase 7 没动。如果以后真有需要,可以单独开 phase。

---

## P5 — 有限自主(提议-校验-修复循环)

### 用它做什么

让模型**自己做事、自己检查、做错了自己改**,但**改几次就要停**——不是无限的 agent loop,有明确的"够了"信号。这是 Prime Agent 论文里 bounded autonomy 的实践。

### 怎么设计的

- **新 host service `prime.bounded-autonomy`**(单一服务,不是三个):内部三个动词 `_propose_step` / `_verify_step` / `_repair_step` 是私有方法,**不暴露成三个独立注入点**(避免把一个紧凑约束拆散)。
- **3 条硬停机条件(封闭枚举)**:
  - 成功(oracle 通过)
  - `iteration-cap-exceeded`(`MAX_ITERATIONS = 3`)
  - `duration-cap-exceeded`(`MAX_TOTAL_DURATION_MS = 120_000`)
  - `no-progress`(工作区摘要连续两步不变)
  - `cancelled`(取消)
- **"够了"信号在 receipt 里**:公开 surface 上 `terminal_reason` 是封闭枚举,绝对不可能是 `still-running` 或空字符串。这是"停止必须清晰可证"的硬约束。
- **取消折叠**:取消不算第 4 个独立停机理由,而是其他闸门的副作用——`terminal_reason` 仍然只是上面 4 种之一(具体哪个取决于哪个闸门先触发)。

### Prime 能力

**有限度的自主性**——模型有自我修正能力,但不能无穷无尽。Prime Agent 论文强调的 "give the model autonomy but bound it"。

### 怎么验收

```bash
make asterion-prime-p5-run            # 成功路径
make asterion-prime-p5-run-limits     # 3 条限额路径
```

**期望(成功路径)**:退出码 0；JSON 含 `terminal_reason == "success"`、`propose_step_count == 1`，验证/修复次数反映实际模型候选。2026-09-24 实跑首轮答对：`verify_step_count == 1`、`repair_step_count == 0`。

**期望(限额路径)**:退出码 0;输出是**3 条记录**:
- `[0]` `iteration-cap-exceeded`(3 次 verify 失败)
- `[1]` `duration-cap-exceeded`(一次慢 propose)
- `[2]` `no-progress`(连续两步工作区摘要不变)

### 边界与未验证项

✅ **已验证**:成功路径 + 3 条限额路径都按预期停机。
ℹ️ **修复边界**:真实首轮修复尚未发生；注入测试覆盖失败反馈与修复。旧 deterministic 成功见证保留为 `make asterion-prime-p5-witness`。
ℹ️ **为什么是单一服务**:`D-2026-09-19-01` 明确反对拆成 `proposer` / `verifier` / `repairer` 三个独立 host service——那会人为切碎一个紧凑约束。

---

## P6 — 持续改进(candidate 评估 + 显式推广)

### 用它做什么

让模型(或它产生的工具)**提议改进**(比如某个策略或脚本),**用一个 holdout 任务评估它到底有没有变好**,然后**显式批准**(让它生效)或**显式回滚**(撤销改动)。**没有任何隐式推广**——之前跑过的成绩、缓存的配置,统统不能授予推广权力。

### 怎么设计的

- **新 host service `prime.candidate-store`**(封装 `HarnessCoordinator`):**不重新实现**框架已经有的"只追加的修订 + 范围映射 + 反向回滚 + 快照投影",而是组合调用(`HarnessCoordinator.apply(proposal)` / `rollback(...)`)。
- **3 种结果,2 种公开声明**:oracle 内部有 3 种判定(`preserved` / `rolled-back` / `global-rejected`),但**公开 receipt 的 `terminal_outcome` 只暴露 2 种**——`global-rejected` 折叠成 `rolled-back` + `global_activation_approved=False`。这是 `D-2026-09-19-02` 锁定的:公开枚举封闭,2 个就 2 个。
- **所有错误折叠成 `rolled-back`**:取消、admission 错误、holdout 评估错误、推广动作错误——全都在 receipt 里标一个诊断 digest,**不开新枚举值**。
- **3 条 witness**(每条一个 Orb invocation,因为这 3 种结果差异太大,不像 P5 那样合并):
  - `preserved`:候选改进、holdout 通过、显式推广动作 → `terminal_outcome="preserved"`
  - `rolled-back`:候选改进、holdout 失败、**恰好一次**反向回滚 → `terminal_outcome="rolled-back"`
  - `global-rejected`:范围=global 但 `global_activation_approved=False` → 编排前直接拒,`terminal_outcome="rolled-back"` + `global_activation_approved=False`

### Prime 能力

**带显式批准的持续学习**——模型可以提议改进,但永远不能"自己悄悄改完就上线"。这是 Prime Agent 论文里 continual harness 的核心。

### 怎么验收

```bash
make asterion-prime-p6-run            # 一个真实候选与独立 holdout
make asterion-prime-p6-witness        # 旧确定性成功见证
make asterion-prime-p6-run-limits     # 旧确定性拒收见证
```

**期望(默认 `-run`)**:退出码 0；一条结果中 `terminal_outcome="preserved"`、`model_call_count == 1`、`rollback_invocation_count == 0`、`global_activation_approved=false`。

**旧确定性见证**分别覆盖以下结果:
- `[0]` `terminal_outcome="preserved"`、`rollback_invocation_count=0`、`global_activation_approved=false`、`task_b_result_digest` 与 baseline 不同
- `[1]` `terminal_outcome="rolled-back"`、`rollback_invocation_count=1`、`baseline_snapshot.revision_id` 已回到 `None`
- `[2]` `terminal_outcome="rolled-back"`、`global_activation_approved=false`、`rollback_invocation_count=0`、`candidate_revision_digest == baseline_snapshot_digest`(没有真实 admission)

### 边界与未验证项

✅ **已验证**:`HarnessCoordinator` 被正确包装而非重写;3 种结果都按公开 enum 输出。
ℹ️ **真实运行边界**:默认 `-run` 用模型候选和独立数值 holdout；真实回滚/全局拒收未发生，相关路径只有注入测试与旧 deterministic witness 证据。
ℹ️ **为什么是"封装"而非"重写"**:`D-2026-09-19-02` 明确禁止拆分 `HarnessCoordinator` 的"只追加修订权"。如果未来有人想做"独立的修订引擎",这一禁令适用。

---

## 附录 A:每应用对应的设计/计划/决策

| 应用 | 设计文档 | 计划文档 | 主要决策约束 |
|---|---|---|---|
| P7 | 总 detachment spec P7 章节 | `2026-09-12-asterion-prime-p1-p7-native-detachment.md` | D-2026-09-12-01, D-2026-09-14-01/02/03 |
| P1 | 总 detachment spec P1 章节 | 同上 | D-2026-09-14-01, D-2026-09-16-01/02/03, D-2026-09-17-01/02/03/04 |
| P2 | 总 detachment spec P2 章节 | 同上 | D-2026-09-14-01 |
| P4 | 总 detachment spec P4 章节 | 同上 | D-2026-09-14-01, D-2026-09-18-01 |
| P3 | `2026-09-18-asterion-prime-p3-native-design.md` | `2026-09-18-asterion-prime-p3-native.md` | D-2026-09-14-01, D-2026-09-18-02 |
| P5 | `2026-09-19-asterion-prime-p5-native-design.md` | `2026-09-19-asterion-prime-p5-native.md` | D-2026-09-14-01, D-2026-09-19-01 |
| P6 | `2026-09-19-asterion-prime-p6-native-design.md` | `2026-09-19-asterion-prime-p6-native.md` | D-2026-09-14-01, D-2026-09-19-02 |

---

## 附录 B:跨应用硬约束(7 个都遵守)

### 1. 完全脱离 Prime Agent(`D-2026-09-12-01`)

- 7 个应用都**不导入 Prime Agent 源代码、SDK、Gateway**。
- 全仓库 `grep -rnE 'Pi[A-Z]|pi_extension|pi_rpc|runtimes\.pi' src/asterion/applications/prime/` 必须返回**空**。这是 source-detachment gate,Phase 1 之后始终 0。

### 2. 应用层不带实现名(`D-2026-09-14-01`)

- `src/asterion/applications/prime/**` 里的代码**只能引用 Asterion 抽象**,不能出现 Pi 实现类型、模块路径、能力名。
- 跨运行时边界的 seam 叫 `prime.launch`,传输的是**纯数据**(批准过的 argv、环境变量、扩展资源身份 + 已拿到的文件描述符)。
- 中性的运行时抽象放在 `asterion.runtime.pinned_extension` / `asterion.runtime.native_rpc`。

### 3. Pi 是 operator 注入的独立包(`D-2026-09-14-03`)

- Pi 来自上游 npm 包 `@earendil-works/pi-coding-agent@0.85.1`(MIT、不是 Prime 的 fork)。
- 通过 `ASTERION_PRIME_PI_ENTRY` 注入,**不带任何 prime-agent 依赖**。
- Orb 内的访问路径是 `/mnt/mac/opt/homebrew/...`,Mac host 路径在 Orb 里看不到。

### 4. 公开 receipt 严格脱敏

- 公开 surface **不包含**:prompt、模型回答、生成代码、worker 输出、credentials、provider payload、私有路径、源文件位置、原始外部日志。
- 内部事件流可以包含诊断信息,但**公开出口必须脱敏**。

### 5. 错误折叠到封闭枚举

- 任何异常路径都不能"开新枚举值",必须折叠到既有的某个封闭枚举项 + 一个诊断 digest。
- 例:P6 的 `global-rejected` 折叠成 `rolled-back` + `global_activation_approved=False`(D-2026-09-19-02)。

### 6. Witness 用 deterministic fake-worker(P2–P6)

- P2–P6 的历史 witness 用 fake-worker(可重复、可验签)。2026-09-24 起 P3–P6 的默认 `-run` 已换成有界真模型路径，历史路径改为 `-witness`；P2 零 token 见证仍保留原边界。
- fake-worker 接收 `(mode, candidate_kind, run_id)` 这样的元组,SHA 按元组不同——这样"子会话确实做了事"和"代际不混淆"是可证的不是可猜的。

---

## 附录 C:术语对照表(说人话版)

| 文档用语 | 黑话对应 | 解释 |
|---|---|---|
| 见证 / witness | witness | 用 fake-worker 跑的"接住行为合约的最小测试"。不证明能力,只证明"合约守住了" |
| Receipt | receipt | 一段跑完留下的不可变记录,带 SHA-256,事后比对可证"那次跑确实是这样" |
| Oracle | oracle | 见证里的"裁判",检查结果是不是符合预期——不通过就拒收 |
| In-process(默认路径) | in-process default | 默认在同一进程里创建子会话或开 loop,不用 supervisor 进程 |
| Subprocess supervisor(后备) | subprocess supervisor fallback | 进程隔离方案,通过 `mk` 起新进程——目前 P3/P5/P6 都明确**不实现**,只保留设计 |
| Host service / 注入能力 | host capability | 应用启动时由 operator 注入的能力(IPython、oracle、trace、continuity store...)——不是 framework 默认带,必须显式给 |
| 能力包 | capability package | 一个应用的实现细节+入口打包(`prime-ipython-coding-native@1.0.0` 这种),与 assembly 是"声明 vs 实现"的关系 |
| 公开枚举 | closed public enum | 公开 surface 上某个字段只能取封闭的几个值——加新值要开新版本,不算兼容更新 |
| 折叠到 | fold into | 一个新发现的语义被映射成既有枚举值 + 一个诊断字段,而不是开新枚举值 |
| Source-detachment gate | source-detachment gate | 静态扫描"代码里有没有偷偷 import Prime Agent"的工具,失败直接拒 |
| Restricted worker | restricted worker | 受限的代码执行环境(默认 IPython),不是完整 Python——只能读特定目录、特定内置 |
| Holdout | holdout | P6 用来评估"候选改进到底有没有变好"的那个**没用过的**测试样本——专门留出来的,不能拿训练数据 |
| Operator root | operator root | operator 拥有的资源目录(本仓库根、P2 corpus、P6 私有根等),与 framework 自带资源严格分开 |
| Authority | authority | "这段代码是被授权的、能动用什么资源、不能动用什么资源"的边界声明 |

---

## 已知未做但已记录的事(供后续阶段参考)

下列都是**已知但本 9 阶段计划范围外**的项——它们不影响 P1–P7 验收,但你下次开 Phase 10 时可能要决定怎么处理:

1. **P3 递归深度 > 2 没测**:`MAX_DEPTH = 2` 是见证合约,框架能力不止于此。
2. **subprocess supervisor(P3/P5/P6)未实现**:设计保留了,但代码没写。
3. **`TestPrimeBackendRealRpc` 跳过**:因为要真 Pi 子进程 + Node 22+ 的环境,当前测试套件没接好。类和 skip 理由都保留了(`2c7c40c6`),以后开环境再补。
4. **pyright 一些静态类型告警未修**:不影响功能,只是噪音——`runtime_binding.py:294` 还有遗留。
5. **P7 真模型跑只跑过一次**(Level 1 / 种子 0 / `deepseek-v4-flash`):多关、多种子、多模型都没跑——`promotion` 仍是 `unpromoted`。

> 这份文档是基于 9 阶段收尾时的实际状态写的(`git log -1` = `8efc9671`,2026-09-19)。
> 后续 P1–P7 任何应用有变更,请相应更新本文档对应章节,而不是另起一份。
