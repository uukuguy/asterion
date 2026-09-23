# Live Session Checkpoint

> Updated: 2026-09-24 03:08 CST. Active session recovery point, not a final handoff.

## 当前任务

2026-09-22 的 R1–R9 评审修复已由 `fa889cfa` 从 `codex/review-implementation-20260922` 集成到 `main`；本轮还核对 P1–P6 日志中的实际证据与应用代码位置。云 GPU 对话已由用户撤销，不属于当前任务。

## 已验证事实

- 用户贴出的 P1 终端流在 `stage1.oracle.start` 后以 `recovery-required` 结束；该原始运行的内部临时记录不存在，不能回放或断定其具体 oracle 谓词。
- 2026-09-24 旧 main `cbe668f3` 的一次有界 installed-wheel P1 复现也在第一阶段 oracle 拒收。只输出固定谓词名的私有诊断记录 `cell_count=1`、失败谓词 `cell_count_two`；运行 ID `p1-74e7ecd319093efa3901f92f`。
- 同日评审分支 `43fea703` 使用相同 operator 配置、入口和有界设置，installed-wheel P1 跑到 `stage2.complete`、`oracle.pass`，公开结果 `p1-9991055483f5334e0339320c`、`completed`、收据 SHA-256 `ab24c3d0ca04b760d377fcd225bb222cea907aaea9fc2ff4316f5d773ac74354`。这是一次成功，不是稳定率估计。安全日志仅保留在本地忽略目录 `.asterion-private/`；公开证据在 `PRIME-P1-P7-ACCEPTANCE.md`。
- P2 是零模型 token 的检索 witness；P3–P6 所示 make 目标为确定性 worker witness。它们各自的绿色输出不能推导为真实模型端到端能力。
- 评审分支此前 `make check` 通过 2990 项 Python 测试（2 跳过）、TypeScript、Rust、lint、docs、build。合并后的 main 本轮 72 项定向测试通过（2 跳过），`make docs-check` 检查 224 个 Markdown 文件和 57 个本地链接，`make promotion-check` 使用操作者已有的 npm 缓存隔离通过 25 项命令、provider 操作 0。默认隔离 npm 缓存曾因缺 `undici-types` 而提前失败；改用已有的本机 npm 缓存后通过。最终代码复审未发现合并阻塞项。

## 当前判断与历史边界

- R1/R6 的精确 request-ID ack 和 settlement 屏障修复了本次复现的连续 Pi prompt 缺陷；2026-09-19 的“verify 改独立进程”是被替代的历史提案。
- P1 仍需更多独立运行才可讨论稳定性。真实 P3/P5/P6 worker 能力、P7 全量 benchmark 和论文复现均未由上述 witness 证明；全量 benchmark 需要单独有限预算授权。
- R8 分次追加仍可能重复解析旧 journal；P6 `recovery-required` 尚非持久恢复机制；Rust 受控执行器不是 OS sandbox。

## 下一动作

1. 核查 `main` 的 Git 状态、合并提交及无遗留测试/模型进程。
2. 向用户用简单语言说明 P1 失败原因、当前一轮成功证据、P2–P6 witness 边界与应用入口位置；不要把一轮成功写成稳定率。
3. 若下一轮要评价可靠性，先明确重复次数与有限成本，再对同一已安装 wheel 的 P1 入口保存每次公开阶段与收据；真实 P3–P6 能力须另行设计有界场景。
