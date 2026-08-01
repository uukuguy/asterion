# Live Session Checkpoint

> Updated: 2026-08-01 18:55. **Session remains active — not a final handoff.**

## TL;DR

- 推荐核验包：Bright 四项和 SciFact 300 条全量已完成；Bamboogle 等待有效 Judge 凭据。
- 用户将优先级调整为先建设 Asterion 通用工作流观察、跟踪、评估与受控优化基础设施；Bright 仅为首个验收适配器。
- `65f5a28` 固化架构规格；通用 evidence foundation 已完成 collector、完整性校验、范围门控比较、证据型诊断和受控优化提案（至 `6c61d16`）。

## Current execution

- SciFact run：`run-6639f380eb0c4e8ab7632c6bf05979dc`，300/300、0 失败、nDCG@10 `0.7524`、成本 `$14.9801`。batch state 为 completed、300 份 result、无 batch error；同源 lock/evidence 的无密钥 resume 已返回 completed，未新增 Agent 调用。
- Bright 完整结果：Biology 103/103 0.4456；Earth 116/116 0.4382；Economics 103/103 0.3097；Robotics 101/101 0.3367；均 0 失败、无密钥 resume 已验证。
- Bamboogle 全量：先修复了资源根遗漏；最新完整范围尝试已确认 125 条数据与 Agent 都可执行，但首个 Judge 请求遭 HTTP 401，随后安全取消。不能 resume 失败批次；替换为远端接受的 `DEEPSEEK_API_KEY` 后使用新的 evidence root。`2029427` 已让未来 `--execute` 在 Agent 启动前进行无题目 Judge 连通性检查，避免再次消耗无效 Agent。

## Framework work

- 新模块：`src/asterion/workflow_evidence/collector.py`。
- 当前能力：从已验证的 `asterion.agent-runtime/v1` 完整 event stream 生成安全摘要：run identity、input digest、工具调用/错误计数、token、artifact digest、终态；不保留 prompt、工具参数/输出或 artifact URI。摘要有确定性 digest，篡改 fail-closed。
- 比较：仅相同 scope 的两次有效记录产生差异；scope 不同返回 `not-comparable`，不会伪造可比结论。诊断只输出可观察的 token/终态变化，不把相关性伪装为因果。
- 优化：仅可从可比诊断生成摘要化、非执行的待审批提案；不携带命令、配置或执行权。`509af33` 同时修复 DCI IR 工具分析，使用逐题 nDCG 而非 QA 正确率字段。
- 测试：`tests/test_workflow_evidence.py`、`tests/test_workflow_comparison.py`、`tests/test_workflow_diagnosis.py` 已以 RED→GREEN 验证。
- 已批准计划：`docs/superpowers/plans/2026-08-01-workflow-evidence-runtime-integration.md`。先在 runtime 边界增加通用观察器和显式 bundle 写入；Bright 只作为首个消费/诊断适配器。

## Immediate next action

1. 按已批准计划实施 runtime-bound 通用工作流观察；不要把 DCI 字段放入 framework。
2. 不对 IR 的 SciFact/Bright 强制 Judge 检查；`3c82ed8` 已确保仅 QA 任务在 Agent 前做 Judge 连通性探针。
3. 获得远端接受的 Judge 凭据后，使用新的根运行 Bamboogle 125 条；它将先做无内容鉴权探针。

## Ruled-out paths

- 不将 DCI 字段、论文语义或 benchmark 实现导入 framework 模块。
- 不把 IR 的 `is_correct: null` 误读成“所有工具使用错误”；现有工具质量关联未接 nDCG，是待修的分析缺口。
- 不在公开 artifact 或文档写入 prompt、答案、工具原文、语料、凭据或私有路径。
