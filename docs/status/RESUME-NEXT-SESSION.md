# Live Session Checkpoint

> Updated: 2026-07-26 20:39. **Session remains active — not a final handoff.**

## TL;DR

- Asterion DCI benchmark 编排器已在 `main@76a83d5` 闭环；隔离 worktree
  与 feature 分支均已移除。
- 默认入口仅预览 15 个任务，边界为 `--limit 1 --max-concurrency 1`；
  只有显式 `--execute` 才执行。
- 协调器没有金额、USD 或价格输入；本轮未执行任何 provider、Agent/Judge
  benchmark、下载或完整数据运行。

## Where things stand

- 操作入口：`scripts/run_dci_benchmarks.sh`。
- suite 为 `github`、`paper-main`、`all`；`all` 保留 15 个有序任务变体，
  Bamboogle GitHub sample-50 与 paper full-125 分开。
- `.env` 由 Python 解析而非 shell source；相对资源根按 env 文件位置规范化。
- 执行严格串行、失败即停、兼容恢复；子进程树有界清理。
- 任务 evidence 使用私有目录/文件权限、目录身份绑定和 descriptor-relative
  writer；公开进度不输出 child body 或私有路径。
- 最终独立审查：Critical 0、Important 0、Minor 0。
- 合并后验证：PLAN 15，聚焦测试 84/84，`make check` 536 个 Python 测试
  及 TypeScript/Rust/文档/构建全部 PASS。
- `make promotion-check`：19 条 provider-free 命令 PASS；
  resource profile：22/22 present。

## Next action

1. 预览任务：`scripts/run_dci_benchmarks.sh`。
2. 用户准备实际运行时：
   `scripts/run_dci_benchmarks.sh --suite all --limit 1 --max-concurrency 1 --execute`。
3. 查看私有输出根中的 `summary.json` 和每任务 `runner.log`，按失败任务修复后
   使用兼容恢复重跑。

## Boundaries and ruled-out paths

- `.env`、本地数据和既有 evidence 不构成自动执行授权；必须显式 `--execute`。
- 不自动下载、转换或修复用户已配置的数据。
- 不调用 `paper reproduce`，也不把 Asterion benchmark 结果表述为论文分数复现。
- 不公开 prompts、answers、provider payloads、corpus text、raw child output
  或私有绝对路径。
- 已删除的 worktree 路径和 feature 分支不再是恢复入口；后续工作从 `main` 开始。
