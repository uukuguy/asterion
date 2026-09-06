# Live Session Checkpoint

> Updated: 2026-09-07. **Prime command closure is complete at the development boundary.**

## Direction

Asterion 的核心是统一智能体框架与能力包集成协议；Prime 和 Native 是并行 runtime。Prime P1-P7 的端到端实现已全部保留，当前 Make 入口已完成可重复准备、用途说明、安全进度和重启后恢复收口。

研发验证覆盖正常链路和关键边界断言。不要把当前证据提升为发布、promotion、完整 benchmark 或论文复现实验结论。

## Verified state

- `make prime-apps-preflight` 在所选 Orb/root/worktree 中完成 P1-P7 锁定资源准备和 host context 开关，固定七行全部 `PASS`，退出 0。它不执行 runtime、模型、工具、worker workload 或应用容器。
- `PRIME_RUN_ID=prime-p2-20260907-final-b make prime-p2-run` 退出 0；stderr 显示用途和完整受控阶段，stdout 恰好一个最终 JSON，且没有 `file://` 私有路径。trace 为 `b32283e764e9d2192ab13bb5825b3e7d01b5e38491b9ae002c873f4c7cadda86`。
- P2 最终运行后的容器、gateway/Node 进程、`/tmp`、仓库和 `.asterion-private` run-specific residue 为零。
- `make test.framework-provider-free` 通过；聚焦 126 个 unittest、`make docs-check` 和 `git diff --check` 通过。P3-P7 的 host/progress 修复另有 40 个聚焦测试通过。
- Sol 对 `739e207b^..8ce70a69` 的最终材料复审为 APPROVE，无剩余 Critical、Major 或 Minor finding。

## Prior bounded E2E evidence

P1-P7 均有此前真实开发边界成功证据，trace 分别为：P1 `9672ba00a1b439c39e319a7f6ae8607e7d00a14795047c7b42f9e56c7686dbcf`、P2 `4ec38c0cb80010941892523610bb9cdbf8b37c213ed6c759fcd794f30d57a62e`、P3 `b961b0ffc13a1e686a73361b9b25b9169690c942a5a84a3604d52f87e5ebe796`、P4 `0bd39b78189f739dcb07123947599276d3f91e7dc24da9407be14ee283e5bebf`、P5 `64268243e6e95133a7379e7e9819cc8e4d6609608d8af5375a7b4b6164c55103`、P6 `51f6454e90a2286dfd0fabaa3f3cf7f7870cd57abf95890845b4efd01048b335`、P7 `a2c1fa78367c4eb4e5b424ca5a717c9cb83f5db8661f57cec22a58a9ff2f0ef1`。这些结果均为 development-only、`unpromoted`；P7 只证明一个最多四步的离线 episode，不代表完整 game WIN 或 benchmark。

## Command contract

- `make prime-p1-run` … `make prime-p7-run` 各自先在 stderr 显示固定用途，再在同一 Orb 中准备所选场景并以 `asterion run --progress` 执行。
- 长期 Node、seccomp、Gateway、source、image 与 P7 资源收据位于 ignored `.asterion-private/prime-development/`，不再依赖 Orb `/tmp`。
- `uv` 使用 quiet 模式；准备和 host 进度仍在 stderr，应用结果保留在 stdout。
- 开发 seccomp/image authority 与 promoted catalogs 分离；四个 closed v1 协议、manifests、runner authority、provider selection、budgets、prompts 和 result schemas 未改变。

## Evidence boundary

七项均为 **Implemented**，且聚合 provider-free host preflight 为 **Verified**。P1 与 P2 有真实命令成功证据；本轮没有逐个重跑 P3-P7 的模型执行，因此不要声称七项都在当前会话完成了真实付费端到端执行。

## Next concrete action

Prime 七项命令入口已收口。下一阶段回到框架主线：围绕统一能力包接入协议审查剩余计划，优先选择一个独立能力包做跨 provider/runtime 集成证明。若需要增加 runtime、capability/package、application、protocol 或 host service，严格按 `AGENTS.md` 的 intent 路由和依赖方向实施。

## Preservation

- Operator LLM 配置仍只由应用/operator integration 从仓库 `.env` 解析和注入。
- 保留无关 `.superpowers/sdd/task-1-report.md`、未跟踪旧 plan/spec 和现有 `tmp*` 目录。
- 不 broad-stage、reset、clean、push 或 promote。
- Native 与 Prime 保持并行 runtime。
