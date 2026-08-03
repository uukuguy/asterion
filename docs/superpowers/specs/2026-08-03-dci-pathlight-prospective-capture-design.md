# DCI Pathlight 前瞻采集设计

**日期：** 2026-08-03  
**状态：** 已获一次最小真实运行授权  
**目标：** 让新执行的 DCI benchmark case 在不改变 Agent/Judge 结果的前提下，直接产生可供 Pathlight Dashboard 验证的 ContextFrame、模型调用和工具调用证据。

## 当前缺口

通用 `asterion run --workflow-evidence-file` 已通过 `ObservedRuntimeClient` 生成
`workflow-evidence.json`，但 DCI benchmark 使用独立的 Pi 原生执行器。原生执行器保存了
conversation、protocol event 和 `latest_model_context.json`，却没有把运行中的模型/工具边界投影为
通用 Pathlight trace。因此历史 DCI 结果可评估，却无法在 Dashboard 中显示真实工作流主线。

## 方案选择

采用实时投影方案：DCI 原生 recorder 在接收 Pi event 时复用框架已有的
`PiObservationBuilder`，同步记录只含摘要的 ContextFrame、模型调用和工具调用边界；完成后调用
通用的“已完成 runtime 证据投影”接口，生成统一 workflow record 与 trace，并通过 recorder 已持有的
目录描述符写入 `workflow-evidence.json`。

不采用以下方案：

- 事后解析 `conversation_full.json` 或 `events.jsonl`：会丢失可靠的实时边界和单调时序，并扩大私有内容读取面。
- 把整个 DCI benchmark 改写到通用 application runner：影响执行、恢复、预算和论文复现语义，超出本次最小验证范围。
- 从最终答案反推 ContextFrame：属于伪造过程证据，禁止实施。

## 架构边界

框架层新增一个 domain-neutral 的完成态投影接口。它只接受已验证的
`RunRequest`、完整 `dci.agent-runtime/v1` event stream、可选的
`RuntimeObservationBatch`、已观察到的单调时间戳和显式 trace ID；输出安全 workflow record 与
Pathlight trace，不导入 DCI。

storage 层新增纯构建函数，用与现有 writer 相同的闭合校验生成
`asterion.workflow-observation-bundle/v1` mapping。原有路径 writer 继续调用该函数；DCI recorder
则把同一 mapping 写入自己已经固定的 evidence 目录，不新增路径扫描或第二套格式。

DCI 层只做适配：原生 recorder 消费 Pi event、处理 retry rollback、捕获当前成功 attempt 的
normalized stream 与时间戳，并在成功 finalization 后写一次 bundle。Pathlight 失败属于可观察性侧路，
不得改变 Agent/Judge 结果、重试、成本、授权或 benchmark 终态，也不得留下部分文件。

## 数据流

```text
Pi JSONL event
  -> DciRunRecorder（原有私有证据）
  -> PiObservationBuilder（digest/length/status only）
  -> 完整 normalized runtime stream
  -> 通用 completed-runtime projection
  -> workflow record + Pathlight trace
  -> pinned native generation/workflow-evidence.json
  -> Pathlight Dashboard 显式 evidence-file 输入
```

公开 bundle 不保留 prompt、answer、工具参数/输出、provider payload、模型/provider 名称、语料、
凭据或私有路径。内容只以摘要、长度、计数、固定状态和不可变引用出现。

## 失败与恢复

- malformed/native observation 退化为显式 missing evidence，不伪造节点。
- Pi retry 回滚被放弃 attempt 的观察草稿，只发布最终成功 attempt。
- 失败或取消运行仍保持原有 benchmark 语义；本次只要求成功运行闭合 trace。
- 目标已存在、目录身份变化、序列不闭合或 bundle 校验失败时不覆盖现有文件。
- resume 只为新完成的 attempt 生成 bundle；已完成 evidence 不被重新写入。

## 验收

1. 单元测试证明 DCI recorder 对含 model/tool event 的成功运行写出合法、无私密正文的
   `workflow-evidence.json`。
2. retry、malformed observation、写入冲突和 redaction 路径 fail closed，且不改变运行结果。
3. 相关 Pathlight、Pi runtime、DCI artifact、benchmark 测试以及 `make check` 通过。
4. 清空当前 shell 中相关配置后 `source .env`，以前台方式执行 Bright Biology 1 条；不调用 Judge。
5. 用真实新文件启动/构建 Dashboard snapshot，确认至少 1 条 trace、1 个 ContextFrame、1 次模型调用，
   并如实记录工具调用数和 evidence gap；不把一次运行推广为 benchmark 分数结论。

## 授权边界

本次授权仅覆盖 Bright Biology 的 1 个新 case、当前 `.env` 中的 DeepSeek Agent 配置、现有工具集合、
一个全新的 source lock/evidence root，以及完成态 Pathlight/Dashboard 核验。不得复用已废止计划，
不得启动 Judge、其它数据集、历史重跑、并行批次或优化实验。
