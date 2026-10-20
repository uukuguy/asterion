# Prime 应用编写地图

七个已发布身份覆盖现有 Prime 能力。新的领域能力出现之前，示范集停在这七个。应用从 `prepare_prime_application` 进入，见 `src/asterion/agents/prime/application.py`。应用提供目标、工具、数据和完成条件。Pi、RPC 和会话由 Prime 持有。

| 应用 | 身份 | 先读 |
|---|---|---|
| P1 | `prime.ipython-coding` | `src/asterion/applications/prime/p1/operator.py` |
| P2 | `prime.programmatic-long-context` | `src/asterion/applications/prime/p2/live.py` |
| P3 | `prime.recursive-workflow` | `src/asterion/applications/prime/p3/live_entry.py` |
| P4 | `prime.long-session-continuity` | `src/asterion/applications/prime/p4/live_entry.py` |
| P5 | `prime.bounded-autonomy` | `src/asterion/applications/prime/p5/live.py` |
| P6 | `prime.continual-improvement` | `src/asterion/applications/prime/p6/live.py` |
| P7 | `prime.arc-agi-3-solving` | `packages/typescript/asterion-prime-extension/src/p7-tools.ts` |

## 文本回合

P5 和 P2 都用 `PrimeApplicationSpec(..., "text-only")`，再取 `prime.text_model`。P3、P4、P6 是同一形状。P5 展示有界提议、核验和一次修复。

P2 的模型写一条 Python 语句，只能是 `retrieve(start, end)` 或 `transform(start, end, "key", ...)`，赋值名只能是 `result`。`p2/program.py` 用语法树读出这一次调用，不执行任意代码。`p2/context_service.py` 读取语料。查询提示只包含任务和记录数，不包含语料正文。`p2/inquiry.py` 在片段摘要一致后把回答写入 `ResearchNotes`。缺省 `make asterion-prime-p2-run` 仍是零 token 本地检索。`make asterion-prime-p2-live` 是单独的有限实跑。

## 持久内核

P1 的规格是 `persistent-code-tools`。它准备应用后启动自己的 IPython worker，压缩指令由应用交给 Prime。专用摘要保留任务陈述，延续回合继续使用同一个内核里的累加器。公开阶段日志在通过时打印 `oracle.pass`，失败时打印一条 `oracle.reject.*`。容量和探针保持预设原值。

## 声明工具、笔记和证据

P7 同样使用 `persistent-code-tools`。工具名单写在 `p7-tools.ts`，通用 `registerPrime` 注册 IPython 和这些工具。`src/asterion/applications/prime/p7/tool_dispatch.py` 把调用交给领域客户端。已接受笔记是 `src/asterion/agents/prime/research_notes.py` 的 `ResearchNotes`。证据索引是 `src/asterion/agents/prime/research_record.py` 的 `ResearchRecordStore`。P7 是第一个消费者。世界模型、动作和探针准入留在 P7。

## 边界

Prime CLI 的用途仍未定。控制面、Rust 策略执行器、第二个运行时和第二个研究领域留在各自的框架边界。框架定位见 [agent-framework.md](../architecture/agent-framework.md)。
