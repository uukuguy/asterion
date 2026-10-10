# Prime 标准应用入口与私有后端所有权

日期：2026-10-10

状态：书面设计已获用户批准；本文纳入随后明确的独立应用、模型及 CLI 边界，供实施计划复审；实现尚未开始。

本设计落实 [DECISIONS.md](../../status/DECISIONS.md) D-2026-10-10-02 的入口边界，新增范围由 D-2026-10-10-03 记录。
实施工作归入 [canonical worklist](../plans/2026-10-08-prime-autonomous-research-interface.md) 的 Task 40，不另建并行任务体系。
本次只统一已有真实模型路径的入口与资源所有权；P2 只明确目标边界，保持现有行为。

## 1. 目标与批准范围

应用以目标、领域工具、数据服务及完成/续跑条件使用 Prime。
P1–P7 是各自独立的应用；按 Prime 标准构造即可直接运行，不要求登记 provider、assembly、inventory 或 CLI 命令。
CLI 定位仍待定；现存 CLI/provider/assembly 仅作为兼容适配，本轮不设计统一 CLI，也不借 DCI/Native 推导其定位。
Prime 在内部管理模型进程、Pi/RPC、扩展装载、会话与适用的执行保障。
operator 解析本地配置并显式注入授权；通用层只使用注入的私有配置，不自行发现或读取 `.env`、凭据文件及邻接项目。

这次变更保持现有 Prime 稳定基础：复用执行内核、会话、持久后端和通用 runner。
不创建第二套编排器，不扩展四个已关闭协议，不把私有启动数据写入 manifest。
框架新增模块继续由根 `pyproject.toml` 定义的同一个 wheel 交付，不拆独立 SDK 或包；独立应用可以另行打包自己的领域代码和工具 artifact。

批准范围覆盖 P7 solving/gameplay、official operator、run-story narrator、P1 和 P3–P6 live。
确定性机制 witness 保留自己的任务与实现；真实模型调用统一进入 Prime。
范围批准不等于新增基准、官方提交或付费实测授权，也不授权新一轮 BP35。
专用自动压缩归属 Prime，但恢复其行为接线与真实验证是后续独立变更。
本轮应用配置固定 P1–P6 为 `deepseek/deepseek-flash`，P7 全部模型路径含 narrator 为 `openai-codex/gpt-6.1-sol`。
当前本地 metadata 支持这些精确 ID；尚无 `deepseek-flash` 与 `deepseek-v4-flash` 等价证据，禁止猜别名或静默 fallback。
core 不按 P 编号选择模型；应用 operator 注入精确选择、已核实价格及已有上限，缺少匹配配置在执行前拒绝。
P2 仍只记录目标模型与边界，不因此增加模型执行；机制 witness 继续无模型。

## 2. 已验证源码事实

以下是源码事实，不代表本次重新运行过测试或模型实测。
路径均相对仓库根，行号用于定位当前基线，迁移后以符号名为准。

| 路径 | 当前事实 | 对设计的约束 |
| --- | --- | --- |
| `src/asterion/agents/prime/session.py:54,118` | 公共构造参数接收 RPC/lease；内部使用 `PrimeExecutionKernel` | 收回构造所有权，保留内核 |
| `src/asterion/agents/prime/backend.py:257,319,405` | 持久后端使用同一内核；attach 校验同一活资源 | 保留 attachment 与未知结果隔离语义 |
| `src/asterion/runtimes/asterion_prime.py:31` | runtime 适配器转发 session 的 `run()` | runtime identity 不能证明后端已经统一 |
| `src/asterion/applications/prime/runtime_binding.py:44` | 现有 provider 路径按精确应用 ID 分派 P1–P7 | 保留兼容适配，直接入口不能依赖此分派 |
| `src/asterion/applications/prime/p7/operator.py:3924` | 创建 socket、扩展 lease、环境和 Pi argv | 迁到 Prime 私有启动/桥接设施 |
| `src/asterion/applications/prime/p7/runtime_binding.py:602,616,642` | 构造 binding、RPC 和 Prime session | 应用改为提供领域描述与服务 |
| `src/asterion/applications/prime/p1/operator.py:1105,1119` | operator 创建 RPC 并注入持久 backend | operator 只保留配置和授权解析 |
| `src/asterion/applications/prime/live_model.py:22,106` | P3–P6 live 使用真实 Pi，配置无工具/无扩展 | text-only 是必须保留的真实执行形态 |
| `src/asterion/applications/prime/p6/live.py:255` | 候选模型调用发生在后续 composed run 之前 | 调用纳入标准入口的受控执行阶段 |
| `src/asterion/applications/prime/p7/official_operator.py:253` | official gameplay 复用 P7 启动资源 | 一并迁移，不留下官方旁路 |
| `src/asterion/applications/prime/p7/run_story/operator_narrator.py:169` | narrator 自行创建 RPC | 改用 text-only 入口，保留叙述领域逻辑 |
| `packages/typescript/asterion-prime-extension/src/ipython-extension.ts:1054` | 既有 register 同时接入核心机制和 P7 memory/tools | 分离应用模块选择，沿用注册通道 |

P3–P6 的确定性 witness 与 live 必须分别标注；存在 witness 不代表没有真实模型路径。
现有 `live_model.py` 同时承担 operator 配置解析和模型会话，两种职责迁移时分开。
`applications/prime/services.py` 混有通用 continuity/child 包装和 P5/P6 领域类型，不能整文件下沉。

## 3. 最小 Python 边界

采用少量进程内 Python 类型和协议，不新增序列化协议、注册中心或扩展配置语言。
下列名称表达职责，最终符号名可在实现计划中对齐现有命名。

| 角色 | 所有者与内容 | 不得承担 |
| --- | --- | --- |
| `PrimeApplicationSpec` | 应用：本地 application ID/version、目标、执行形态、领域工具 artifact | 注册前置条件、Pi 对象、argv、fd、模型进程创建 |
| `PrimeOperatorContext` | operator：经预检的配置、授权上限、工作根、私有诊断/证据服务 | 以配置或缓存自行授予执行权 |
| `PrimeApplicationServices` | 应用/host：数据查询、工具 dispatch、结果与未知 effect 状态 | 启停 RPC、注册私有传输、重置预算 |
| `prepare_prime_application(...)` | Prime：校验并接管资源，提供 runtime/model/backend 窄视图 | 查询目录、另造 composer/runner 或隐式发现应用 |
| 私有 session owner | Prime：进程、lease、桥接、适用会话和清理顺序 | 将私有 owner 暴露给应用去拼装 |

应用数据与回调可以包含私有领域材料，但只能进入显式私有通道。
operator 注入的凭据保持不可公开表示；错误与公开事件沿用现有脱敏边界。
工厂创建对象本身不得启动模型调用；模型效果只能发生在明确受控的执行阶段。
已有 runtime adapter 保持协议投影职责；领域产物投影仍属于应用。

目标调用方向：

```text
独立 application + operator 注入 → prepare_prime_application
                                → Prime 私有 session/backend → 既有执行内核/RPC
现存 CLI/provider/assembly 适配 → 同一直接入口（可选兼容路径）
既有 runner → 已解析 plan、runtime、implementation、只读 host services
```

直接构造不查询应用目录、不要求 provider_id；本地 application ID/version 用于 trace 与资源身份。
现有装配路径仍维持其依赖方向和 runner 合同；独立使用 Prime 无需采用这条集成路径。
Prime 入口只集中后端资源与运行职责；应用目标、证据解释和研究策略仍由领域层提供。

## 4. 两种执行形态与保障范围

### Text-only model

用于 P3–P6 已有 live 回调和 run-story narrator 等只需要模型输出的任务。
保留现有无工具/无扩展策略、提示次数、输入输出限制、成本和截止时间约束；模型按第 1 节明确要求更新。
Prime 接管 RPC、计量、取消与关闭；应用提供目标文本和领域结果解析。
这是真实模型执行，但不因此声称具有持久 Python 状态、长程研究或进程恢复能力。
需要多次模型调用的任务仍由已有领域工作流组织，Prime 统一资源与额度入口。
不强制安装 IPython，不伪造 `prime.tool.ipython` 工具使用证据。

### Persistent-code/tools

用于 P1/P7 等需要持久代码环境、领域工具和自然轮次续跑的路径。
保留 `PrimeExecutionKernel` 与现有 session/backend 的实现关系。
Prime 负责桥接传输和 worker 生命周期控制；应用提供 worker 内可用的领域服务。
P7 的 broker、动作日记、终止判断和研究 NOTES 内容仍在领域层。
正常续轮和受控 prompt 恢复继续使用存活内核及其 generation。
若内核丢失，仍按现有显式 source/JSON 恢复合同建立新 generation，并保留数据来源与效果边界；不恢复任意进程对象，也不重放动作单元。

持久后端与 attachment 只在实际使用该能力的路径启用。
P1 的 clean attach 指向同一个仍活着的 owner，不把磁盘文件重开等同于进程复活。
P7 现有 retained-process 恢复继续检查 ledger 和领域 effect guard。
统一入口不自动把 P1 的持久恢复保障宣称为全部应用已有能力。

## 5. 扩展与工具所有权

继续使用打包 TypeScript 扩展的 `register(pi)`/`registerTool` 通道。
Prime 核心扩展承担 IPython 桥接、归档/投影、计量和适用的压缩机制。
应用以显式选定的 typed tool module 提供工具定义、描述、schema 与领域 dispatch。
应用将该 module 与 Prime 通用注册函数在构建时合为一个自包含 `.mjs` artifact，提供路径及既有工具注册表。
Prime 使用现有 ExtensionBinding/Lease 固定文件描述符和 digest，仍由既有 loader 调用 `default register(pi, dependencies)`。
模块身份与完整工具名在注册前和 Python 期望值核对；不新增 wire protocol、插件扫描或核心应用列表。
当前固定源码只允许 `node:` import，故第三方依赖必须构建时 bundle，不放宽运行时路径/包 import。
Python 注册表、Pi allowlist、TypeScript 注册和实际 bridge 必须来自同一选择。
不依靠 prompt 假装注册工具，也不在 runtime 下另造第二套注册机制。

P7 专用 memory hook 和工具组按 P7 模块显式装入。
通用 Prime core 不默认安装 P7 策略、游戏状态结构或领域约束。
research/legacy 选择属于 P7 自己的打包入口；core 不维护 P7 selector switch，独立应用增加工具不需要修改框架。
应用必需的状态注入继续走现有上下文机制；只读回调与执行动作维持原有区别。
第一阶段保持 P7 工具名字、schema、描述及可见状态行为一致。
解耦注册位置时不得顺便改变 NOTES 淘汰策略、领域提示或动作执行语义。

扩展源码、wheel 中 `.mjs`、绑定身份、allowlist 与 Python bridge 必须一致。
接管 pinned lease 时转移单一所有权，不重新按路径解析已固定文件，避免 TOCTOU。
关闭顺序覆盖模型、扩展、桥接与 worker；构造失败同样回收已接管资源。

## 6. P7/P1 控制边界

P7 保留 solving/gameplay 的不同完成条件、action cap 和原有 trace/projector。
自然轮次 admission、模型/工具累计次数、任务总 deadline 继续使用原有控制来源。
续轮、RESET、prompt 恢复、模型 profile 选择和入口包装均不能刷新任务预算。
既有特殊 sweep 模式保留显式授权边界，不被推广为统一入口默认值。

动作是否已生效由领域 action journal/receipt 判断。
Prime 不推断“取消成功等于动作未执行”，不重放未知 effect，也不将缺失 receipt 当作安全。
只有 ledger settled、effect guard 明确通过且期限仍有效，才允许现有有限恢复。
P1 的预算预拒绝、durable acknowledgement、未知状态 fencing 与 clean attach 原样保留。
迁移不能因统一 API 将这些路径降为不带证据的布尔重试。

P6 候选模型调用移入 Prime 入口管理的候选生成执行阶段。
其总授权与计量覆盖候选生成和后续 workflow；不能在后续 run 重新获得一份完整额度。
候选解析、Task A 证据、Task B 验证及发布资格仍由 P6 决定。
最终可失败或被取消，不因生成候选完成而提前宣称整个 P6 任务成功。

## 7. 默认专用压缩的独立边界

目标由 Prime 持有 code-aware 摘要策略，并支持应用补充领域保留材料。
Pi 原生触发、准备、持久化和工具组完整性继续沿用；应用不自行拼压缩后端。

当前存在摘要模板（`agents/prime/summarization.py:44,123`）和见证材料。
`context-witness.ts:369` 构造专用请求用于 proposal；`:390` 批准后返回 `undefined`。
这不能证明专用摘要文本实际进入选定模型请求；P7 当前也未注入该 witness 的 FD/nonce。
P1 手工 `custom_instructions` 不能作为默认专用自动压缩已经完成的证据。

先完成入口所有权重构，再单独接通专用摘要行为并核对实际 prompt/provider usage。
低阈值 P7 验证应检查 kernel generation、变量/函数复用、NOTES/反例保留与继续解题。
该验证使用已有授权的具体有限范围；超出已授权范围时单独明确执行范围。
本设计不运行该验证，不把 provider-free 测试或原生通用摘要列为专用压缩 PASS。

## 8. 迁移顺序与完成标准

### 阶段 A：冻结行为基线并增加入口

按现有路径登记配置来源、授权、资源所有者、公开产物和执行形态。
增加小型 Python 入口，将资源创建集中到 Prime，保留现有执行实现。
完成标准：可用替身验证两种形态的创建/执行/关闭；创建本身无模型效果。
未登记的临时独立应用能够直接运行 fake-backend text 与自带 artifact 的 persistent 工具路径；禁用 provider/catalog lookup 仍成功。
检查应用边界不再要求 RPC/lease 对象，generic runtime/runner 没有领域导入。
过渡期保持旧消费者可用：先添加新 resolver/view，再迁移调用方；旧 `.command`/factory 适配至全部消费者迁完后删除。
扩展拆分时在同一提交修改 P1/P7 的 artifact/identity producer，不能先切资源再等待后续应用迁移。

### 阶段 B：先迁移 P7 全部真实路径

迁移 operator/runtime binding 和 official gameplay 的启动调用链。
run-story narrator 迁入 text-only 形态，保留 narration schema 与证据引用验证。
领域 broker、研究回调、工具 dispatch 和证据产物继续由原模块负责。
完成标准：上述路径没有应用自行构造 Pi/RPC、fd/lease 或命令行的旁路。
与基线对比工具集合、完成条件、预算累计、未知 effect、公开事件及资源关闭行为。

### 阶段 C：迁移 P1 与 P3–P6 live

P1 改由 Prime 创建 backend/store/RPC 等私有资源，保持已有 authority 和 attach 校验。
P3–P6 live 共用 text-only owner；operator 的 `.env` 解析留在集成层。
P6 候选调用进入受控阶段，明确共享总计量与取消范围。
完成标准：真实模型启动统一，机制 witness 的确定性行为和证据分类仍准确。
P2 仅记录未来可接入的应用目标、工具/数据和保障边界，不新增 live backend 或修改结果。

### 阶段 D：打包复核与收口

静态搜索应用层的 Pi/RPC 构造、扩展 fd/lease、原生命令参数，逐项消除或解释 operator 配置用途。
复审重心是变更后的所有权、依赖方向、预算与未知结果处理，不扩张无关测试矩阵。
运行受影响的 session/backend、应用 binding/live、run-story 的既有 focused unittest。
扩展有变更时先跑 `npm --prefix packages/typescript/asterion-prime-extension test`，再跑相关 Python 测试。
运行 `make promotion-check`，核对安装 wheel、资源、入口和工具 allowlist 的同版性。
按仓库部署合同完成适用且已授权的有限打包 witness，并单独记录具体命令、范围与结果。
若未运行真实打包 witness，明确标为 Not rerun/未完成部署闭环，不宣称真实部署验证通过。
不得用新的 BP35 长实验替代有针对性的接线检查；本设计不授予该实验权限。

整体完成须同时满足：真实路径无后端构造旁路、资源所有者唯一、现有控制边界不变、打包一致。
源码统一与实测能力分别登记；不存在的 live/continuity 能力不能因接口相同被标记为已验证。

## 9. 方案取舍与主要风险

选用分阶段集中所有权：先建立标准入口，再迁移已有路径，保持同一执行内核。
只重命名 `PrimeLaunch` 或公开导出 session 会留下接线泄漏，不能满足目标。
一次重写全能 session 会同时改变 P1 durability、P7 续跑和 text-only 计量，风险过高。

主要风险是 lease 双重关闭/泄漏、P6 预算重复授予、P7 未知动作误重放和应用工具集合漂移。
用单一 owner、既有授权来源、effect journal 断言及同版打包检查分别控制这些风险。
压缩提示行为与入口迁移分开提交和验证，避免把模型行为变化归因于机械重构。

## 10. 当前证据分类

- 已验证事实：第 2、7 节的现有源码结构与调用位置。
- 当前判断：统一资源所有权、保留两种执行形态是最小且可渐进的方案。
- 历史归档：P7 应用自行组织 Pi 初始化可以作为迁移基线，不能作为新应用模板。
- 未完成边界：本设计尚未实现；统一 backend、默认专用压缩和跨应用恢复能力均未新增验证。

下一步是按最新明确边界复审 Task 40 实施计划；此文不构成已实现或已部署声明。

复审记录（2026-10-10）：独立 Sol 合同评审 APPROVE；自审补清注入配置与内核 generation 恢复语义。同步更正 P2 验收指南的语料格式和公开收据字段。`make docs-check` 通过（312 Markdown 文件、221 个本地链接），`git diff --check` 通过；无运行代码变更或模型实测。
后续修订记录：依用户明确要求补入独立直接入口、精确模型和 CLI 定位待定；上述历史复审结果不自动覆盖本次新增文字，本次没有生产实现或模型实测。
