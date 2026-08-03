# Pathlight Dashboard 设计

**状态：** 已批准，待实施  
**边界：** operator-local、provider-free、只读、默认安全层

## 目标

Pathlight Dashboard 是 Asterion 对一次智能体任务工作流数据流的本机观察界面。
它把 ContextFrame、模型调用、工具调用、评估、实验和诊断串成一条可查证的
主线，同时把未采集到的边界明确显示为 `missing`，不用推测填补。

Dashboard 不是新的执行器、授权者、证据库或 Opik 替代品。它只消费已经通过
Pathlight 验证器的安全投影。

## 方案比较与决策

1. **本机只读 API + 静态应用（采用）。** Python 进程在启动时读取操作员明确
   指定的安全文件，验证后建立内存快照，通过同源 GET API 提供给界面。它不增加
   前端或网络依赖，可随 wheel 安装，也符合 Asterion 的 Python 编排责任。
2. **纯静态 HTML 报告（不采用）。** 便于携带，但会把数据内嵌到页面，无法建立
   稳定 API 边界，也不利于 trace tail 和后续查询。
3. **仅使用 Opik Dashboard（不采用）。** 它适合作为可选外部工作台，但不能成为
   Pathlight 数据语义、安全层或操作员授权的权威。

## 架构和数据流

```text
操作员显式选择的安全文件
  workflow-evidence / evaluations / experiment / diagnosis
                         │
                         ▼
             闭合协议验证器（fail closed）
                         │
                         ▼
              DashboardSnapshot（不可变）
                         │
                         ▼
           127.0.0.1 只读同源 HTTP API
                         │
                         ▼
             Pathlight Dashboard 静态应用
```

API 主机不扫描 evidence root，不跟随符号链接，不加载 provider，不调用模型，
不发起外部网络请求。每个输入都必须是绝对路径和既定文件名；启动时一次性
验证并固定快照，运行期不重读私有证据。

## API 契约

API 前缀为 `/api/pathlight/v1`，只接受 `GET` 和 `HEAD`：

- `/summary`：快照身份、数量、状态分布、证据缺口数量；
- `/traces`：安全 trace 列表；
- `/traces/{trace_id}`：经验证的 trace graph；
- `/traces/{trace_id}/flow`：ContextFrame/model/tool 有序主线；
- `/evaluations`：指标契约和 evaluation 投影；
- `/experiments`：dataset、variant、plan、trial 和 evaluation 关联；
- `/diagnoses`：finding、proposal 与缺口；
- `/snapshot`：以上已验证数据的同一快照，供首屏一次加载。

响应字段只来自现有 Pathlight 安全类型或固定汇总值。不引入 prompt、answer、tool body、
provider payload、凭据、模型/provider 名称或本机路径。错误响应只包含固定类别。

## 界面信息架构

界面名为 **Pathlight Dashboard**，定位为密度适中的“运行路径工作台”，不使用
通用管理后台卡片堆叠。

- **顶部状态条：** 快照摘要、trace/evaluation/experiment/finding 数量和安全状态。
- **左侧运行列表：** 按状态和节点类型筛选 trace，只显示 opaque ID 短摘要。
- **中央主线：** 用纵向时序节点表示 ContextFrame → model-call → tool-call →
  ContextFrame；每个节点明确显示 completed/failed/cancelled/missing 和边界缺口。
- **右侧检查器：** 显示所选节点的 digest、长度、token、时延、失败类别和链接，
  永不显示内容正文。
- **辅助视图：** 评估表、实验历史和诊断/缺口三个标签页；指标契约或
  coverage 不可比时不渲染伪差值。

视觉使用深蓝灰底色、暖金强调、高对比状态色和等宽数据字体。桌面屏为三栏；
窄屏按“运行列表 → 主线 → 检查器”单栏排列。所有交互可键盘操作，支持
`prefers-reduced-motion`。

## 安全与运行边界

- 只允许绑定 `127.0.0.1`、`::1` 或 `localhost`；其他地址启动前拒绝。
- 无 CORS，拒绝 `POST`/`PUT`/`PATCH`/`DELETE`，设置 CSP、`nosniff`、`DENY`、
  `no-referrer` 和 `no-store`。
- 不提供任务执行、proposal 批准、provider 选择、重试、调度或文件上传接口。
- 静态资源从 wheel 包内加载，不使用 CDN、远程字体或外部分析。
- 启动命令在前台阻塞；`Ctrl-C` 正常退出。只有显式 `--open` 才打开浏览器。

## 验收

1. 未安装 provider 和 Opik 也能启动并查询 Dashboard。
2. API 对同一组输入产生确定性快照和顺序。
3. 恶意、篡改、语义不闭合或文件名不匹配的输入在开端口前失败。
4. sentinel prompt、answer、tool payload、凭据和私有路径不出现在 API、HTML、JS、
   CSS 或错误响应中。
5. 一条含 ContextFrame/model/tool 的 trace 能正确呈现主线；缺失 frame 的历史运行
   显示证据缺口，不伪造节点。
6. `unittest`、`make lint`、`make docs-check`、`make promotion-check` 和隔离 wheel 验证通过。
