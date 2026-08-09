# Pathlight 操作者手册设计

## 目标

提供一份中文、面向操作者的单一入口，说明如何从已封存的 Pathlight 证据读取工作流主线、评价、诊断和优化结果，并安全启动本地 Dashboard 或进行 Opik 离线交换。

## 范围

- 通用 Pathlight：证据文件、`trace`、`metrics`、`evaluate`、`diagnosis`、`proposal`、Dashboard、Opik 离线导入导出。
- DCI Bright 适配器：coverage、查询分解 A/B 的 prepare/status/execute/resume/finalize，以及已完成实验的正确解读。
- 明确每条命令的输入、输出、是否调用模型/网络、开发与严格生产授权差异、常见失败处理。

不把 prompt、问题、答案、case ID、provider payload、凭据或私有运行目录写入示例；不把 DCI 专属命令表述为通用框架接口。

## 文档结构

1. 快速判断：何时使用 Pathlight，哪些文件是输入。
2. 采集和读取：从 `workflow-evidence.json` 到 trace/flow/metrics/diagnosis 的只读命令。
3. Dashboard：最小可运行命令、页面内容和只读/回环网络边界。
4. 受控优化：DCI Bright 的单独流程、80 次真实 A/B 的已知结论，以及开发/生产授权开关。
5. Opik：仅离线安全 envelope，网络发送属于 operator-owned adapter。
6. 故障排查与安全清单：证据闭合、数据身份、权限、配置加载和不应公开的数据。

## 验收

- 新手仅凭此文能区分通用 CLI 和 DCI 产品 CLI，运行只读查看与 Dashboard。
- 每个示例使用占位绝对路径，不泄露运行数据。
- 文中的 A/B 状态、预算和结论与当前已封存真实结果一致：80 Agent、0 Judge、$16、0 基础设施失败、候选拒绝。
- `make docs-check` 通过，状态索引能发现该手册。
