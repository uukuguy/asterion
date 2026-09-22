# Next-Session Handoff

> Updated: 2026-09-22 19:05 CST. Final closeout of the 2026-09-22 review remediation session.

## 当前任务与位置

九项设计与代码评审改进已在独立工作树 `.worktrees/review-implementation` 的 `codex/review-implementation-20260922` 分支实施并提交；起点是主分支评审提交 `1b52e778`，本轮收口前的实现与状态提交头为 `1ba7f12b`。主分支尚未合入这 23 个提交。完整方案和应用证据矩阵在 `../reviews/2026-09-22-architecture-and-execution-review.md`。

## 已验证事实

- R1/R6：`00d5008a`、`3f92df84` 以精确 request-ID ack 与本次 settlement 关闭 Pi prompt，覆盖授权重试和 compact wire 一致性；通过模拟 producer 的定向测试。真实 P1 模型未重跑。
- R2：`b8f2f914`、`86f8ad63`、`11a4d00a` 让 P3/P5/P6 的 selected provider→assembly→runner 路径实际调用注入的 host/worker 并签发结果。P3 定向 26 项、P5/P6 定向 139 项及身份/取消回归通过；这些是确定性驱动证据。
- P6 入场后的取消执行一次精确逆向；逆向失败或 revision 变化进入 `recovery-required`，不签成功产物。组合 host 核验 coordinator revision 与 baseline；旧底层 tuple 的 `rolled-back` 文字本身不是逆向证明。
- R3/R4：`91ca07b1` 绑定已验证包内容并拒绝事件/产物自消费环。最终复审又复现 `source_id`、`source_kind` 漂移绕过；`6baffd9e` 修复失败关闭路径，包准备 10 项测试通过。
- R5：`fc947d87`、`d6a888c9` 约束 Python/Rust 执行器的取消、超时、EOF 和进程组回收；Rust package tests、Python managed executor 定向测试及全套检查通过。
- R7/R8/R9：增加公开脱敏的私有诊断关联；合并日志同一操作中的重复验证读取；抽取唯一 journal codec、Prime 精确发布清单和 P6 candidate-store 所有者。定向测试分别覆盖这些边界。
- `make check` 通过：2990 项 Python 测试，2 项跳过，TypeScript、lint、docs、Rust tests/clippy 和 build 均通过。`make promotion-check` 隔离通过：`promotion full PASS commands=25 provider_operations=0 full_dataset=no`。最终 `make docs-check` 检查 224 个 Markdown 文件与 57 个本地链接。全部检查已退出，无遗留测试、模型或 benchmark 进程。
- `921200d6` 修正隔离 wheel 的 Prime 资源清单；`cbf4ccab` 为 wheel 的 DCI 产品检查安装其声明的 extra。此前 promotion 失败是这两处发行检查配置缺口，分别复现并修正。

## 当前判断

- 公开 v1 协议保持封闭。下一步宜先复审独立分支的 23 个提交，再决定如何合入主分支；发行门槛已通过，不必在没有代码变化时机械重复全套测试。
- 应用能力必须按应用 × 入口 × driver × 环境 × 命令/收据记证据。旧 P1/P7 live 收据、这次 P3/P5/P6 组合确定性测试和未运行的真实模型场景不能互相替代。

## 历史归档

- D-2026-09-19-03 把 `agent_settled` 当作下一 prompt 隐式 ack 的解释已被跨轮延迟事件复现否决；现用精确 ack 加 settlement 屏障。
- Phase 10 的共享 PiRpcSession 双 kernel 草案不能提供独立 verify 进程；其取消也不能被解释为已执行工具副作用的通用回滚。
- 原评审报告的九项缺陷探针是修复前基线，不可直接拿附录的预期输出评价当前代码。2026-09-19 的“7/7 完成”仅是历史实现记录，不是当前七个应用端到端能力证明。

## 未完成边界

- 本轮没有真实 P1 模型重跑、ARC 全量 benchmark 或论文复现；如需 P1 能力证据，应执行一次有界 preset 并保存准确收据。完整 benchmark 仍需单独授权和有限预算。
- R8 仍对每次独立文件追加重验旧前缀，累计解析量仍可能平方增长；分段封存需单独审查篡改发现时机与恢复合同。R7 默认诊断 sink 只在进程内。P6 的 `recovery-required` 不是持久恢复机制。
- Rust 受控执行不是 OS sandbox；同步 spawn 与取消之间没有原子调度门闩。真实 P3/P5/P6 live worker 能力没有被确定性 host 测试证明。

## 下一动作

1. 从项目根目录进入 `.worktrees/review-implementation`，核对 `git status --short`、`git log --oneline main..HEAD` 和评审报告“实施跟进”及证据矩阵。
2. 复审并集成该独立分支；主分支这次只接收状态交接文件，尚无实现合并。若集成代码产生冲突或修改，再运行受影响的定向测试、`make check` 与相应发行门槛。
3. 若研究目标要求真实 P1 完成证据，执行一次现有有界验证入口；记录应用、driver、环境和 receipt，不用模拟测试代替。

## 工作树与进程

- 两个工作树在 handoff 收口后应为 `git status --short` 为空。主工作树的本地 `.codex/config.toml` 是操作者配置，保存在原位并由本地 Git exclude 排除；不要把它并入发行包。
- 本轮未启动模型或 benchmark。测试与 promotion 命令均已退出；未发现遗留 Pi、受控执行器或测试进程。
