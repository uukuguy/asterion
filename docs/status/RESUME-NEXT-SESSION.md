# Live Session Checkpoint

> Updated: 2026-09-22 17:07 CST. **Session remains active — not a final handoff.**
> Code review baseline: `f7c4f97b`. 本次只交付评审与改进方案，生产代码未改。文档检查通过（216 个 Markdown、56 个本地链接）。

## TL;DR

- 用户请求“对本项目的设计和代码提出深度专业的优化改进方案”。完整报告在 `docs/reviews/2026-09-22-architecture-and-execution-review.md`，含九项发现、优先级、修复边界和有限验收。
- Provider-free 探针已复现 prompt 跨轮 settlement 污染，以及 P3/P5/P6 公开 compose/runner 路径零调用、零事件、零产物仍返回成功。
- 建议优先修 prompt 操作边界，再连接公开应用执行路径。Phase 10 的 shared-session “subagent” 草案不能提供其声称的隔离；这是本次技术建议，尚未实施。

## 已验证事实

- 代码基线 `f7c4f97b` 是上一会话 handoff 提交；此前 `1a7107e0` 的 `make test` 记录为 2943 项、2 项 skipped、exit 0。本次未重跑全量测试。
- 两种 compact_events 配置下，连续 prompt 探针均出现：第一条正常，第二条只读到前一条的 agent_settled 并返回空文本，第三条 response ID mismatch。根代理与独立复审结果一致。
- P3/P5/P6 assembly 只引用 policy，package implementations 为空。通过公开 Python compose/runner 接口实测 runtime_calls=0、events=0、artifacts=0；修改 runtime.run 一处无法修复该路径。
- 临时副本探针确认：package authority 绑定后同 ID/version manifest 改内容，可以改变后续 compose 的 plan；自消费事件的 workflow 也通过组合。
- ManagedControlledExecutor 入场取消探针留下进程，探针 finally 已手动清理。Rust 当前代码 offline build 后的有限 fork/pipe 探针：500ms deadline，1223ms 后报 completed。
- 同 compact transcript 在 compact_events=False 被拒、True 通过。文件日志每次 append 全量解析；64/128/256 次追加分别解析 2144/8384/33152 行。
- 全部探针无模型调用；本次未运行 ARC、真实 P1 或其他 benchmark。新启动的有限探针子进程均已退出/清理。

## 当前判断

- 先统一 exact-ID ack、operation settlement、事件归属与 uncertain/fence，再选择 verify 隔离策略。
- settlement 仅证明停止，不能独立证明成功；签 completed 仍需原生失败状态、工具配对、应用结果和 oracle 验证。
- 新 kernel 共用原 PiRpcSession 不形成独立会话；可能新增 sequence/预算移交冲突。
- 保留现有 Python/TypeScript/Rust 分工和公开 v1 契约；修复完成语义、快照绑定和应用连接后再局部拆模块、优化日志。

## 历史归档与不可继承的推断

- 先前“Pi 0.85.1 无法连续 prompt”已被独立 producer probe 撤回；本次进一步定位出 Asterion 队列边界缺陷。
- 先前“verify 没执行”仅由提前截断的 Asterion trace 推断，不能证明 Pi 完整操作没有执行工具。
- CURRENT-STATE/MEMORY 的“7/7 完成”不得解释为七个公开路径均端到端通过。P3/P5/P6 的 operator simulation 与公开路径必须分开记证据。
- D-2026-09-19-03 的 implicit ack 行为虽已实现，其正确性假设受到本次复现反证；本轮未修改代码或批准替代决策。
- 2026-09-05 review 的 research-kind 修复是历史；本次 policy-only 应用空执行是另一个具体缺口，不能沿用旧修复的 PASS。

## 未完成边界

- 所有 R1–R9 仍待修复；报告和探针不是修复交付。
- 原始 P1 真模型端到端尚未重跑；不能宣称本次找到了全部失败原因或已修复 P1。
- P2 本地 retrieval 路径确有实现；其零 token operator witness 不证明模型长上下文能力。P4 是其命名 fake-worker continuity 边界；P7 仅继承历史限定关卡 live evidence。
- Phase 10 仍是 draft，无正式 implementation plan 或新代码。Atomic prompt 不得承诺通用工具副作用 rollback，也不得把 live-resource attachment 当作任意进程恢复。
- 既有未跟踪 `.codex/config.toml` 属于本轮开始前工作，保留。未读取或修改 `.env`。

## Immediate next action

用户要求推进时，先读 review R1/R6 和 Phase 10 草案，形成单一 prompt 操作边界的有限修复：以真实 producer 的 ack→agent_end→settlement 次序补回归，修复驱动，再验证两种 compact 配置一致。P3/P5/P6 连接与 R3/R4/R5 可按报告中的依赖分工推进。不要直接照旧草案先实现共享 PiRpcSession 的双 kernel。

Project route 仍为 managed；旧九阶段 worklist 的历史记录保留，本次 review 暴露了完成边界缺口，未自动改写项目里程碑或启动实现。

## Useful entry points

- `docs/reviews/2026-09-22-architecture-and-execution-review.md`
- `src/asterion/runtimes/pi_rpc.py`、`src/asterion/agents/prime/execution.py`
- `src/asterion/applications/prime/assemblies/`、相关 native capability package provider
- `src/asterion/applications/provider.py`、`src/asterion/capabilities/composition.py`
- `src/asterion/services/managed_controlled_executor.py`、`packages/rust/controlled-executor/src/process.rs`

```bash
git status --short
git log --oneline -6
make docs-check
```
