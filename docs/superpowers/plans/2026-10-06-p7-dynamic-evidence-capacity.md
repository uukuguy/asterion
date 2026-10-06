# P7 Dynamic Evidence Capacity Implementation Plan

> For agentic workers: use subagent-driven execution with explicit file ownership and changed-code review. Preserve other workers' edits.

**Goal:** 接收并完整保存长动画，处理后释放动态数据，明确区分本地失败与真实动作结果未知；所有异常有可追溯警告。

**Architecture:** 实现[已确定的动态容量设计](../specs/2026-10-06-p7-dynamic-evidence-capacity.md)。P7应用持有动画arena/ref/分页，旧完整观察规范哈希语义不变；模型、研究、回放和认证用专用小视图或迭代器。通用Prime/Pi仍执行其传输与运行控制。

**Tech Stack:** Python应用、既有SDK adapter、Prime工作区、现有console JavaScript；unittest，打包promotion。

## Global Constraints

- 动画没有人为单批/单run总帧、总cell、总字节上限，不能纳入context/RPC/console/经验正文累计预算。
- 每块、每页、并发驻留缓冲有界；实际资源错误明确记录。不能读回全部块再拼成一条大消息。
- 完整观察哈希保持v1规范字节语义；原sealed route、后续关卡、分数和失败记录不改写。
- 存活guest及其部署、期限不变；新代码仅在验证和自然关卡边界后接入。用户已明确授权最多四路并行。
- 不开新官方卡；不做全目录模型评估；旧证书静态兼容不得调用SDK重放。
- public diagnostics不包含私有路径、凭据、provider原始数据或模型思维链。

## Task 1 — 动态证据区与旧哈希

**Owner:** Astra。核心新模块、`broker.py`、`live.py`应用adapter、`replay.py`、`animation_replay.py`、`solutions.py`、`solution_certificates.py`及专属测试。先向集成worker发布精确类型/接口，再开始集成。

**Required interfaces:** 应用持有的只读动画handle；完整帧迭代与有界页读取；完整规范流式哈希；稳定末帧视图；明确release/耐久引用；安全typed processing fault。选择具体接口名后在本计划登记，两个worker使用同一合同。

- [x] 以已存BP57帧/G95帧记录建立无SDK复现，并加入旧小观察规范字节等价fixture。
- [x] 实现内容寻址chunk、分段索引、最后原子manifest发布、原始uint8/shape/hash校验；根引用不嵌入全索引。
- [x] 完整元数据规范化与动画token增量哈希；每种chunk边界得到同一v1完整sha。
- [x] 将adapter/broker/replay witness的长期全动画引用替换为handle，明确临时与耐久所有权；避免重复整批冻结与复制。
- [x] 原结果与完整digest提交后的稳定观察直达actor，不先经过全动画ObservationState的小消息上限。
- [x] 流式读取recording/动画来源；现有动画等价规则、来源scope及内容hash校验保留。
- [x] 实现精确冻结verifier兼容路径及静态旧证书检查，源码/SDK/游戏变动仍fail closed；不通配verifier或伪造新见证。

**Verification:** BP/G四批纯数据通过；旧规范hash矩阵、不同chunk、损坏块/索引、取消/写盘失败、释放引用和静态证书无SDKfixture。运行新增专属unittest与既有broker/replay/certificate相关检查；不重复真实SDK路线评测。

## Task 2 — 结果阶段、警告与应用集成

**Owner:** Sol。`solver.py`、`research_bridge.py`、`research_runtime.py`、`experience.py`、`console_events.py`、`console_snapshot.py`、`console_prepared.py`、`operator.py`及对应测试。不修改Task1核心模块或网页assets。

**Consumes:** Task1动画handle、完整身份/稳定状态接口、typed fault。向root提供公开诊断和帧分页的精确HTTP/data shape；不得新造通用runner或工具注册机制。

- [x] 将SDK dispatch、收回复、协议验证、原始持久化、身份提交、派生视图等阶段分开；只有未确认回复进入真正unknown。
- [x] 处理已知GAME_OVER及可RESET状态；本地失败不丢已知结果，不再重派原动作。不能修复时有限收口、释放槽、明确基础设施分类。
- [x] 将安全诊断传播到日志、模型context/feedback、summary与public console投影；保留诊断身份、阶段、单位、实际值/限额、已知/耐久状态和恢复方式。
- [x] 修研究响应最终wire预算；合法分页给引用，异常拒绝不可静默吞掉。
- [x] 失败经验动画使用动态引用，摘要预算保持原用途，不由32/64MiB正文上限拒绝完整动画来源。
- [x] 替换console独立64层限制和全量SDK parser路径；准备时分页完整动画，取消动画累计32MiB level/8192帧等人为拒绝。完整hash/scope验证保留。
- [x] 必要的public event/prepared schema显式版本化；旧来源读取保留，缺页/损坏有明确警告，不落回空认知或0动作。

**Verification:** returned-result容量/磁盘/投影失败与no-reply区别，no redispatch、GAME_OVER可识别、secret redaction、同一诊断贯穿各层；>64帧分页/历史cursor/动作数/认知不回归。Focused Python及已有准备/经验/actor检查。

## Task 3 — 网页显示与集成收口

**Owner:** Root。网页assets/DOM测试、设计状态文档、跨worker集成、打包和部署证据；不改worker的核心合同来掩盖集成失败。

- [x] 使用Task2公开诊断：总览及当前运行状态持久小图标/短文，详细信息展开；重复轮询不撑开布局、不闪烁，不抹掉已恢复诊断。
- [x] 使用帧分页，稳定frame ID/cursor，播放跨页连续；动作面板标识和点击位置、稳定游戏认知绑定原source，缺页只影响该页。
- [ ] 核对全部已保存游戏关卡的来源、动作数、认知和ready证书；静态校验禁止SDK构造。
- [x] 交叉变更评审，运行必要Python/DOM检查；若Prime工具扩展资源变动，先跑TypeScript测试并同步打包资源。
- [x] `make promotion-check`通过后冻结exact wheel/source/resources，保留已有guest原版本和deadline；parent/future guest自然边界接入。
- [x] 使用已授权BP35L6/G50TL3验证真实打包路径：57/95帧回复完整保存；G50L3通过，BP实际GAME_OVER。未遇到的故障分支不宣称验证。
- [ ] 提交代码、named checks和活动恢复检查点；原官方成绩不变，README仍保持用户暂停范围。

## Completion Boundary

纯数据fixtures与检查通过只证明这些容量/错误路径；真实部署、自然长动画再遇到、被卡关卡最终通过分别记录。BP/G框架修复不等于已通关；LF52交互模型问题保持独立。

## Named evidence / active boundary

Core `42c3a6cb`: 108 focused checks, five real historical BP/G/SB replies with unchanged hashes, lazy8200frames>64MiB; zero SDK/model/API. Integration `1d0c5e6b`:336 focused PASS. UI `102c5086`/`f44f8367`:122 DOM PASS/1conditional SKIP; actual Python-exported95-animation-frame HTML last-frame seek1PASS/0SKIP/0network. Independent changed-code review CLEAR. Final resource snapshot `4bb89296` only corrects broker contract wording; native dependency-boundary test1PASS. Exact4bb wheel558resources, Darwin/Linux PASS; clean promotion PASS25/provider0; parent-only adoption released preserving existing guests. BP35L6/G50TL3 real experiments queued at natural slots; no puzzle completion is inferred.

Exact public paging protocol is frame-page/v1 (32frames/page) bound to run/level/replay_revision/source_token; frontend keeps4pages/2requests. Offline HTML streams inert `console-frame-page-{level}-{start}` tags and parses only requested pages. No new Prime tool or allowlist is introduced. Old certificate audit21sourcesPASS; a pre-existing BP failure membership gap was repaired solely as one rejected descriptor, with winner5/150, certificate bytes and oldmetadata unchanged, zero recertification.
