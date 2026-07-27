# Live Session Checkpoint

> Updated: 2026-07-27 08:28. **Session remains active — not a final handoff.**

## TL;DR

- 用户确认 Asterion 需要来源无关的能力包规范；built-in 只是扩展能力包的一种
  source form，不是特权类型。
- 正式设计 `e667e31` 已获用户批准；四阶段实施计划及总索引已提交为
  `e873093`。
- 尚未开始协议迁移、通用 benchmark runner 或 DCI 能力包重构。

## Where things stand

- 规格：
  `docs/superpowers/specs/2026-07-27-asterion-capability-package-protocol-design.md`。
- 总计划：
  `docs/superpowers/plans/2026-07-27-asterion-capability-package-rollout.md`；
  依次执行协议基础、来源与 SDK、通用 benchmark、DCI 外置优先迁移。
- 设计硬迁移到 `asterion.agent-runtime/v1`、
  `asterion.capability/v1`、`asterion.capability-package/v1`、
  `asterion.application-assembly/v1` 和 `asterion.benchmark-suite/v1`；
  不保留旧 `dci.*` 通用协议。
- source forms 为 builtin、installed distribution、explicit local directory，
  后续增加 archive 和 registry；所有 form 产生同一种
  `InstalledCapabilityPackage`。
- portable payload、source envelope 和 operator source lock 相互分离；
  不存在 builtin、local 或 latest 的隐式优先级。
- 通用 benchmark planning/execution 属于 Asterion；DCI 只提供 suite、
  task binding、数据/指标契约、资源和实现。
- DCI 必须先通过 external distribution conformance，再以相同 payload
  materialize 为 builtin form，并证明身份等价。
- 完成迁移后移除顶层 `asterion.dci`、根目录 DCI benchmark tools 和 launcher。

## Next action

1. 由用户选择 Subagent-Driven 或 Inline Execution。
2. 从
   `2026-07-27-asterion-capability-protocol-foundation.md`
   Task 1 开始，严格按计划 TDD 和原子提交执行。
3. 每个阶段通过自身 gate 后再进入下一阶段；Plans 1-4 完成后运行总闭环。

## Boundaries and ruled-out paths

- 不跳过 Plan 1-4 的依赖顺序，不在计划执行前修改实现。
- 不为错误的 `dci.*` 通用协议保留兼容层。
- built-in 不绕过 schema、closure、digest、binding 或 conformance 验证。
- application assembly 不选择来源；operator capability lock 精确选择 source。
- 不通过路径扫描、版本范围、隐藏优先级或动态 registry 解析能力包。
- DCI 先证明 installed-distribution form，再注册同 payload 的 built-in form。
- 迁移和验证阶段不执行 provider-backed benchmark。
