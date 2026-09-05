# Asterion 框架与能力包集成评估

日期：2026-09-05。基线：本地 `main`，HEAD `625c351`，含评估开始时的既有未提交文档。本文记录初始评估证据及按用户校正后的调整方案；随后完成的有限实现与复验另见 canonical worklist，不表示所有建议均已实现。

> 用户后续校正（2026-09-05）：Prime 与 Native 是并行 runtime；先收口已经投入的 Prime 七项端到端功能复现。本文技术发现保留，但下文“先进行通用框架调整、暂缓 P1”的实施排序已被此指令替代。当前执行顺序以 `docs/status/PRIME-TYPICAL-APPLICATIONS.md` 为准：P1 真实执行主干 → P2/P3 → P4/P5 → P6 → P7 有限功能验证；Native 不作为这七项的前置条件。广泛拆包/协议升级在七项收口后再推进，直接阻塞七项的核心缺陷可插入修复。

## 结论

Asterion 已具备有价值的协议、确定性组合、精确装配、运行器和外部能力包 SDK 基础。主要问题是项目完成标准、交付顺序与发行边界偏离了“统一智能体框架，接入多种能力包”的目标。

建议采用**保留核心、收敛主线、通过独立扩展验证通用性**的增量方案。把 Prime、DCI、Native 和研究复现放到明确的参考集成或可选扩展轨道；框架发布不再以完整 Prime/Native 对等、ARC 成绩或 P1 专用安全执行栈全部完成为前提。

核心成功标准应是：新增独立能力包无需修改框架核心；公共协议可发现、装配、执行和验证它；不同包可组合；兼容 runtime 可替换；安装和验证不依赖仓库私有路径、外部 Prime 源码或产品数据。

## 范围与证据限制

- 阅读当前状态、canonical roadmap、Prime 能力设计和 P1 权威进程设计，以及框架架构、集成、安全文档。
- 检查 Python 发行配置、CLI、默认 runtime 注册、能力声明与绑定、SDK、组合/执行边界，以及 TypeScript schema 构建入口。
- 使用独立代码审查核对核心扩展路径；本报告区分实现缺陷、已知未实现边界和设计约束。
- 本次运行 13 个定向 unittest 模块，共 146 项通过；`make docs-check` 通过，报告检查 174 个 Markdown 文件、57 个本地链接。
- Prime CLI `acceptance`、`preflight` 均返回固定 fixture 的 PASS，provider 操作数为 0。`asterion list` 显示三个内置 application providers。
- 独立审查另检查 24 个核心/契约文件，运行 75 项 Python 测试（与上述部分重叠）、相关 Ruff 检查，以及 TypeScript runtime 的 30 项测试，均通过。
- 初始评估阶段未运行全量 `make check`、promotion、Prime Gateway/Rust 全量测试或真实模型、Docker、benchmark。后续复验单列于工作清单及 JOURNAL；不能据本报告的定向测试宣称全仓库无缺陷或生产执行已验证。

## 一、值得保留的设计

1. **依赖方向清楚。** `CLI/host → provider → assembly → catalog/composer → implementation → runner → runtime/services` 是可持续的基础；不要因为 Prime 工作过重而重写整套框架。
2. **兼容性与授权分离。** manifest 不承载凭据、命令或执行授权，host 显式注入服务；选择后执行的 Python 扩展属于可信计算基，协议验证不等于沙箱。
3. **组合结果确定。** 精确版本、显式来源、歧义拒绝、循环检测和不可变快照适合作为跨包集成的稳定地基。
4. **外部扩展基础已经存在。** `capability_sdk`、distribution/local source、SDK conformance 和 external-wheel 测试值得继续完善，不应重新设计一个平行插件系统。
5. **执行与控制分层。** 顺序 runner 不承担发现、调度和持久化；长运行 control plane 保持可选，有助于同时支持简单工具型能力和复杂智能体。
6. **证据等级诚实。** provider-free、bounded、External-limited、Not rerun 的区分应保留；后续优化应提高集成证据价值，而不是放宽 PASS。

## 二、主要问题与调整建议

### F0a — 高：公共脚手架可生成被 runner 静默跳过的 capability

证据：`cli_capability.py:397` 生成 `kind: research`；`capabilities/protocol.py:13` 接受该类型；`capability_sdk/conformance.py:32` 将其视为可执行类型。但 `capabilities/execution.py:19` 的 EXECUTABLE_CAPABILITY_KINDS 不含 research；`applications/provider.py:86` 按该集合过滤 implementation；`runner/composed.py:101` 跳过该类型。

本次最小运行复现使用仓库 runner fixture 构造 research plan、一个真实 implementation binding 及 InstalledApplication。包中 binding 数为 1，application 投影后为 0；runner 正常返回 ApplicationRunResult，implementation_called=False，events=0，artifacts=0。第一次探针使用空 input，被正常 preflight 拒绝；改为有效非空输入后得到上述静默跳过结果。

这是真正的跨层执行契约不一致，优先于新增产品能力。修复需要先确定 research 的公开语义，再统一 schema/validator、脚手架、SDK conformance、binding 与 runner。若它应执行，纳入统一 executable 集合；若仅作分类，脚手架改用 capability 并明确旧 research 值的兼容处理。不能静默移除 closed v1 已接受的值。必须新增“公共脚手架 → 独立安装 → implementation 被调用”的回归，而不仅测试 manifest 被接受。

### F0b — 中高：builtin source 的原始 discovery 结果不能直接使用精确 digest lock

证据：`capability_packages/sources/builtin.py:49` 返回 payload_sha256=None；`capability_packages/resolution.py:51` 精确锁路径要求 candidate digest 匹配。DCI source-form 测试在 resolver 前打开 payload，并补写 digest-bearing candidate。

本次探针通过 BuiltinCapabilitySource 取得候选并打开实际 payload，用真实 digest 构造 lock；把原始 discovery candidate 传给通用 resolver，收到 `capability source digest is rejected`。

这不是完整 DCI 执行故障，DCI 已有适配；问题是公共 API 组合仍需 source-specific 处理。建议在保留 metadata-only discovery 的前提下，提供统一的候选验证/锁定阶段，由 host 明确调用，生成各 source form 一致的 lockable candidate。不要为了修复而加载 provider code 或让 discovery 隐式扫描所有资源。

### F1 — 高：canonical roadmap 的完成条件与当前项目目标冲突

证据：`docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md:5` 将完整 Prime/Native 对等设为目标；第 21 行规定 Phase 4 才算完成整个项目。相反，`docs/architecture/agent-framework.md:5` 以可安装、可执行、可移植的能力包为目标；`docs/superpowers/specs/2026-09-02-asterion-prime-capability-program-design.md:5` 又排除了完整 CLI/TUI、认证和模型目录对等。

影响：自动续接会继续追逐外部产品的功能清单，通用协议缺口与接入成本没有成为主路线图的排序依据。

调整：当前 canonical worklist 先闭合 Prime 七项真实端到端场景，以其检验统一框架与集成协议。旧 Prime 计划保留历史证据；Native 并行演进，不作为 Prime 七项的前置条件。不得删除历史验收记录或把未完成项改成完成。

### F2 — 高：Prime 验收场景尚未转化为同等数量的可集成能力

证据：`src/asterion/capabilities/prime_agent/payload/capability-package.json` 只列出 `prime.ipython-coding`；`applications/prime_agent/provider.py:66` 暴露两个 application identity，`prime-capability-program.json` 同样只装配 P1。P2–P7 有 acceptance、receipt、worker 等模块，但没有对应的包声明和装配入口。

影响：七类场景的 provider-free 实现不能直接计作七项能力包集成完成。框架用户仍无法通过统一装配选择这些行为。

调整：先建立“行为 → 所属层 → 公共入口 → 证据”映射。不要机械地把七个测试场景都变成七个包：长上下文、递归与连续性可能是 runtime/control 的服务能力；ARC 是领域应用；只有可独立组合的行为才成为 capability。先用两个领域不同的独立扩展检验边界。

### F3 — 高：公共 readiness 与 fixture 验证混在同一 preflight 层级

证据：`applications/prime_agent/product.py:160` 使用内部固定 `_fixture_observation()`；第 183 行让 preflight 返回 `fixture-contract: PASS`。`runtime/defaults.py:91` 拒绝 Prime runtime 的 options 与 host services；`runtimes/prime_agent.py:45` 的默认实现只发出 started/failed，错误为 worker unavailable。P1 authority 进程 `authority_process.py:268` 也明确在准入后停止为 unavailable。

这是刻意的未完成安全边界，不应通过解除保护来“修复”。问题在于公共 preflight 的含义与用户所需 readiness 不一致。

调整：acceptance 保留 provider-free contract 检验；preflight 调用真正无副作用的 readiness 检查，检查所选 provider/runtime、host-service 工厂和必需资源，并以稳定状态码报告未就绪。basic 保持 NOT RUN，直到真实执行链成立。固定 fixture PASS 不能升格为安装执行就绪。

### F4 — 高：P1 强隔离产品执行栈正在吞噬框架主线

证据：`docs/security.md:13` 将精确加载后的 Python 扩展列入 TCB；P1 redesign 的 threat model 则防御恶意、可 monkeypatch 的应用，并要求独立 OS 身份、权威进程、service manager、Docker 与 ELF 锁。两者对应不同信任配置，不应混为一个框架准入前提。

规模观察：`applications/prime_agent/operator/` 有 13,464 行 Python；最近 100 个提交标题中 90 个涉及 Prime/P1。行数和提交数不是缺陷证明，但结合 basic 仍未运行，表明交付目前集中在安全准入的局部闭环。

调整：保留所有现有拒绝与隔离约束，将其定位为可选 restricted-execution host service 的具体实现。核心只定义请求、身份、授权前置、取消、结果和公开证据接口；Linux、seccomp、Docker、FD 与 ELF 属于具体服务实现。先完成威胁模型及部署可行性决策，再决定继续投入该实现。绝不把同进程私有对象包装当作恶意插件隔离。

### F5 — 中高：逻辑模块化尚未形成轻量发行边界

证据：`pyproject.toml:16` 强制安装 matplotlib、pyarrow、python-dotenv；前两者在当前 Python 源码中用于 DCI 分析/导出。wheel 打包整个 `src/asterion`，内置 DCI/Prime provider、host-service 与 Prime Gateway 资源也随核心发布。

影响：只想使用协议与简单能力包的开发者仍需承担产品依赖和发行资源。把模块放进产品命名空间，不能单独解决安装与发布耦合。

调整：先建立“core-only 安装测试”并梳理 imports，再把产品依赖移到明确 extras/独立发行包；使用现有 entry points 保留兼容入口。逐步形成 core、runtime adapter、capability package、control provider 和 operator service 的发行归属，不做一次性大搬迁。

### F6 — 中高：v1 有明确组合上限，应由真实跨包用例决定演进

证据：`capabilities/composition.py:42` 建立全局 edge provider 映射，事件类型和 artifact media type 的多提供者会拒绝；`runner/composed.py` 按类型筛选上游结果。现有设计文档明确 v1 只声明输出允许类型，不保证输出数量或必有输出。

这不是当前 v1 的实现错误。但是多个包都生产 JSON、多个节点产生相同事件、需要明确选择某一个来源时，单凭 media type 无法表达丰富路由。公共 invocation 主要以 input_text、upstream artifacts/events 与 host services 传递输入，包作者也需要明确了解其边界。

调整：先增加独立跨包组合场景。v1 继续维持严格拒绝和兼容性；只有场景确实需要时才提出独立 v2/新契约，评估命名端口、显式 source/target binding、输入输出 schema identity、基数和必要输出约束。禁止给 closed v1 偷加字段，也不应为了通用性预先加入 DAG 调度、动态发现或版本范围。

### F7 — 中：runtime 的第三方接入体验弱于 capability source

证据：`cli.py:82` 支持嵌入方传入 RuntimeFactoryRegistry；`runtime/defaults.py:67` 的默认 CLI 注册表硬编码 Pi、Claude Code、Prime 三项。当前并非“无法扩展”，但外部作者与标准 CLI 的集成仍需代码级宿主装配。

调整：先明确支持承诺：嵌入宿主显式注入是否足够；若要求安装 adapter wheel 即可使用 CLI，再补精确、metadata-only、selected-only 的 runtime 注册发现路径。不得引入静默优先级或启动时导入所有扩展。

### F8 — 中：全仓库验证与核心发布验证耦合过紧

证据：`Makefile:61` 的 test 全量 discovery；check 同时运行 TypeScript、Python、Rust 与 build；`tools/check_promotion.py` 包含外部 Prime 源码绑定、重建与运行资源校验。已有完整门禁很有价值，但核心变更缺少清晰的独立发行验收边界。

调整：新增 core、contracts-cross-language、extension-wheel、provider-integration、bounded-e2e 五类门禁。保留全量 check 作为周期性及发布回归；受影响产品的集成门禁仍必须运行。核心 wheel 门禁不应要求模型、Docker 或外部 Prime checkout。能力包接入的首要证据应是 isolated installed execution，而不只是越来越多的内部 object/receipt 单元测试。

### F9 — 中：状态与文档检查无法阻止目标漂移

证据：CURRENT-STATE 仍将旧 Prime roadmap 设为 canonical，结构快照之后已有 212 个提交；框架接入指南仍展示不存在的 `src/asterion/dci/`；README 写六个 assembly 资源，而当前源码有十个。`make docs-check` 仍通过，说明链接/规则检查不等于语义与库存一致性。

调整：生成 provider/application/package/runtime 的公共库存摘要；主路线图增加 goal、owner、dependency、deliverable、acceptance、status、supersedes 字段。每个项目级完成判断必须回到 framework acceptance。状态更新只保留当前事实，旧证据留在原记录。

### F10 — 中：TypeScript 公共集成发行身份仍依附 DCI

证据：`packages/typescript/asterion-runtime/package.json:2` 名为 `@dci/agent-runtime`，第 4 行为 private=true；若目标包括独立 Node 消费者，当前缺少可发布的框架契约发行路径。runtime schema 的 `$id` 也仍使用 dci.local。

建议先明确 TypeScript 契约包的公共支持边界，再为其建立 Asterion-owned 发行名、打包测试及兼容迁移。schema `$id` 是引用身份，不能仅为去品牌而原地全量替换。尤其 `schemas/executor/v1/` 仍明确采用产品协议 `dci.executor/v1`，不应误当作命名错误直接改掉；先确认契约归属，再以单独迁移维护兼容。

## 三、目标架构与协议职责

```text
安装元数据 / 精确 source lock
              ↓
外部宿主或 CLI → 精确 provider/application → assembly → composer
                                                    ↓
                                             sequential runner
                                             ↙              ↘
                                  capability implementations  runtime adapter
                                             ↓
                                   显式注入 host services

可选 control provider → host authority / journal → 同一 application 路径
```

| 层 | 应承诺 | 不应承诺 |
|---|---|---|
| core | 生命周期、组合、身份、不可变输入输出、错误/取消语义、插件装配 | Prime/ARC/DCI 的业务算法或部署策略 |
| capability package | 独立领域行为、兼容声明、implementation、可公开输出 | 凭据发现、越过宿主授权、隐式选择 runtime |
| runtime adapter | 原生命令/事件到公共协议的翻译 | 另一套 composer/runner 或领域工作流 |
| optional control | 长运行会话、恢复、递归协调的公共边界 | 让所有简单 capability 必须依赖长运行系统 |
| operator service | 受控外部效果、部署隔离、后端接入与资源生命周期 | 把 private 配置塞进 portable manifest |
| reference application | 证明以上层能共同完成真实任务 | 定义整个框架的完成条件 |

协议工作先补齐公共作者文档和 conformance matrix：metadata discovery、exact selection、implementation loading、resolve、preflight、execute、cancel、release 各阶段有哪些数据、错误、作用与授权。优先统一已有概念，只有已验证的表达缺口才增加协议。

## 四、三种调整路径

| 路径 | 收益 | 代价/风险 | 建议 |
|---|---|---|---|
| 先闭合 Prime 七项，再按复用证据收敛框架；Native 并行 | 保全已有投入，获得真实集成证据 | 需限制专用部署逻辑扩散，逐项定义退出条件 | 当前采用 |
| 收敛核心，补外部集成闭环，再逐步拆包 | 保留已有协议与测试，验证扩展性 | 需要定义验收、划清发行边界 | 七项收口后推进 |
| 立即重写核心或一次性拆成多个仓库 | 目录结构看起来清晰 | 公共 API、资源、source lock 和已有证据易同时失效 | 暂不采用 |

## 五、七项优先顺序及后续框架工作包

当前执行：P1 共享执行主干与多轮/compaction 语义 → P2/P3 复用该主干 → P4/P5 真实恢复与有限自治 → P6 局部改进/回滚 → P7 有限公开子集。各项须经过实际 worker、可信 oracle、取消清理和 installed public route；完整 ARC benchmark 不在本轮范围。具体缺口与负责人见 canonical worklist。下表是七项收口后的候选工作，不是当前前置条件。

| 顺序 | 工作包 | 产物与退出条件 |
|---|---|---|
| W0 | 目标与库存校准 | 一个 framework-first canonical worklist；Prime/Native/ARC 子计划明确非阻塞；所有可发现入口与证据等级一一对应 |
| W1 | 核心一致性与扩展边界 | 先修复 research 静默跳过与 builtin lockable candidate 链；core-only 安装/导入/测试通过；审计 core→product imports；产品依赖归属清晰 |
| W2 | 公共集成契约与作者体验 | 一个可复制、可独立构建的最小 extension；从 manifest 到 CLI 执行只使用公共 API；文档示例在 CI 中执行 |
| W3 | 跨包与跨 runtime 证据 | 两个不同领域的扩展 wheel 在无源码树环境安装、组合、执行；同一中立 capability 在两个符合声明的 adapter 下通过共同语义测试；取消/失败/缺服务均覆盖 |
| W4 | 按证据演进协议 | 对 v1 无法表达的真实用例形成小型决策；若不需要新协议则记录沿用 v1；若需要则同步 schema/Python/TS/fixtures 和迁移规则 |
| W5 | 分层发布门禁与参考集成 | core 发布不依赖外部产品 checkout；保留完整回归；DCI/Prime 分别提供独立 readiness 与有限端到端证据 |

W3 是框架可扩展性的首个关键里程碑，不能由两个同源 fixture 或仅能 list/describe 的空壳代替。两个 runtime 的测试可以 provider-free 验证协议；真实外部效果另列有限授权验证，不能混报。

先完成 Prime 七项，再以 W0–W3 验证通用扩展边界；Native 深化、registry 或更丰富 workflow 按独立需求排序。暂缓新增 Prime UX 对等、ARC 全集复现和仅为消除某个产品 Missing 标签而扩展核心。

## 六、实施节奏与度量

- 工作单元由“一个安全检查/receipt 包装”改为“一个可观察的集成行为”，内部仍保留必要的原子提交与边界测试。
- 抽象必须有独立消费者证明：先证明两种包/adapter 共用边界，再抽出共性；不把 P1 类型批量改名为 generic 就算抽象完成。
- 每个里程碑记录：外部作者需修改的 core 文件数、独立 wheel 安装执行率、跨包组合通过率、兼容 adapter 数、core-only 依赖和门禁耗时。数值目标在 W0 建立基线后确定。
- 安全关键修复继续及时做；新增强隔离能力只有在明确部署需求、TCB、平台及可运行最小链后进入主开发队列。
- 不以提交数、测试总数、内部 receipt 数或 Prime parity 行数作为框架完成率。

## 七、本次实际验证命令

```bash
uv run python -m unittest -q \
  tests.test_capability_composition tests.test_capability_catalog \
  tests.test_capability_execution tests.test_capability_sdk \
  tests.test_capability_conformance tests.test_distribution_capability_source \
  tests.test_dci_package_ownership
# 75 tests, OK

uv run python -m unittest -q \
  tests.test_runtime_protocol tests.test_capability_package_protocol \
  tests.test_capability_source_protocol tests.test_installed_application_provider \
  tests.test_default_runtime_factory tests.test_protocol_canonical_ordering
# 71 tests, OK

make docs-check
uv run asterion verify --provider prime-agent --level acceptance
uv run asterion verify --provider prime-agent --level preflight
uv run asterion list
```

原建议的立即下一步为 W0/W1/W2；用户后续已校正优先级：先收口 Prime 七项，当前继续 P1 executable-lock 聚合接入和真实运行主干的契约核对。W0–W5 保留为七项收口后的框架调整候选，不抢占当前工作。
