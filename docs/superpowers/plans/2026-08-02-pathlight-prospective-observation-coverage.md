# Pathlight 前瞻结构化采集与 DCI Coverage 实验实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 `asterion.agent-runtime/v1` 的前提下，为每次真实运行生成可验证的 ContextFrame、模型调用和工具调用安全主线，并执行已定义的 Bright 四项加 SciFact 共 50 条 coverage-instrumentation 受控实验。

**Architecture:** 运行时实现一个可选、内容安全、运行后读取的 observation side channel；公共 runtime event stream 继续保持闭合且原样返回。`ObservedRuntimeClient` 只在公共事件流完整验证后吸收 observation batch，并原子投影为 Pathlight Trace/Span/ContextFrame。DCI 产品层提供 document-level gold coverage registry、显式 proposal authorization 和五实例顺序协调器；它可以依赖通用 Pathlight，通用框架不得导入 DCI。

**Tech Stack:** Python 3.14、`dataclasses`、`unittest`、现有 Pathlight/Workflow Evidence、Pi/Claude runtime adapters、DCI benchmark host、canonical JSON、descriptor-relative private files。

## Global Constraints

- `asterion.agent-runtime/v1`、`asterion.capability-package/v1` 和 `asterion.application-assembly/v1` 不增加字段或事件类型。
- Pathlight 默认层只允许 digest、长度、计数、固定枚举、token、成本、时延、状态和 opaque reference；禁止 prompt、answer、corpus text、tool/model payload、credential、provider 配置和私有路径。
- Native observation 缺失时必须显式记录 `missing_evidence`；不得重建或猜测未观察到的模型请求。
- Observation、Trace、coverage registry、Experiment/Evaluation 输出均不可变、canonical、内容寻址，并对 symlink、FIFO、TOCTOU、竞态和 hostile mapping fail closed。
- Observation 失败不得改变 runner/runtime 的事件、结果、重试、取消或本地私有 evidence。
- Coverage proposal 固定为 Bright Biology/Earth Science/Economics/Robotics 和 SciFact 各源序前 10 条，共 50 次 Agent operation；总成本上限 5 USD，连续 2 次基础设施失败停止；不调用 Judge。
- Proposal digest、scope digest、预算和 stop rule 必须与已发布 `pathlight-diagnosis.json` 精确一致；已有 trace、缓存和 evidence 不能授予执行权限。
- Opik SDK、网络 exporter 和 Dashboard 不在本计划内；本计划完成后分别制定 Opik interop 计划，Dashboard 最后。

---

## File Structure

- `src/asterion/pathlight/runtime_observation.py`：领域中立的安全 observation batch 契约和 source protocol。
- `src/asterion/runtimes/pi_observation.py`：Pi native event → ContextFrame/model/tool observation 投影。
- `src/asterion/runtimes/claude_observation.py`：Claude stream-json → 已观察摘要与显式缺口投影。
- `src/asterion/workflow_evidence/runtime.py`：公共 runtime stream 与 native observation 的交叉验证和 TraceGraph 投影。
- `src/asterion/pathlight/flow.py`：从已验证 TraceGraph 生成只读、安全、顺序化的数据流视图。
- `src/asterion/capabilities/dci/implementation/pathlight/coverage.py`：DCI coverage registry 生成、document-level trajectory coverage 和安全 projection。
- `src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py`：proposal prepare/execute/status 的产品协调器。
- `src/asterion/capabilities/dci/resources/retrieval-coverage-manifest.schema.json`：coverage-only 私有 manifest schema。
- `src/asterion/capabilities/dci/resources/retrieval-coverage-registry.schema.json`：exact query closure registry schema。

---

### Task 1: 定义内容安全的 Runtime Observation 闭包

**Files:**
- Create: `src/asterion/pathlight/runtime_observation.py`
- Modify: `src/asterion/pathlight/__init__.py`
- Test: `tests/test_pathlight_runtime_observation.py`

**Interfaces:**
- Consumes: canonical SHA-256、exact primitive、sorted-unique tuple 规则。
- Produces: `ContextSegmentSummary`、`ContextFrameObservation`、`ModelCallObservation`、`ToolCallObservation`、`RuntimeObservationBatch`、`RuntimeObservationSource`、`validate_runtime_observation_batch()`。

- [ ] **Step 1: 写失败测试，覆盖完整闭包和红线字段**

```python
def test_runtime_observation_is_canonical_content_safe_and_closed(self) -> None:
    segment = ContextSegmentSummary(
        segment_index=0,
        role="user",
        structure_kind="message",
        content_sha256=_digest("secret input"),
        content_length=12,
        source_call_sha256=None,
        missing_evidence=False,
    )
    frame = ContextFrameObservation(frame_index=1, segments=(segment,))
    call = ModelCallObservation(
        request_index=1,
        frame_sha256=frame.frame_sha256,
        model_sha256=_digest("model identity"),
        request_sha256=_digest("request"),
        response_sha256=_digest("response"),
        response_length=8,
        input_tokens=10,
        output_tokens=3,
        status="completed",
        boundary_observed=True,
    )
    batch = RuntimeObservationBatch.build(
        run_sha256=_digest("run"), frames=(frame,), model_calls=(call,), tools=()
    )
    self.assertEqual(validate_runtime_observation_batch(batch.to_mapping()), batch)
    self.assertNotIn("secret input", json.dumps(batch.to_mapping()))

def test_runtime_observation_rejects_unknown_fields_and_noncanonical_order(self) -> None:
    mapping = _valid_batch_mapping()
    mapping["frames"][0]["segments"].reverse()
    with self.assertRaisesRegex(PathlightError, "runtime observation is invalid"):
        validate_runtime_observation_batch(mapping)
    mapping = _valid_batch_mapping()
    mapping["private_prompt"] = "SENTINEL_PRIVATE"
    with self.assertRaisesRegex(PathlightError, "runtime observation is invalid"):
        validate_runtime_observation_batch(mapping)
```

- [ ] **Step 2: 运行 RED**

Run: `uv run python -m unittest -v tests.test_pathlight_runtime_observation`

Expected: import failure because `asterion.pathlight.runtime_observation` does not exist.

- [ ] **Step 3: 实现最小闭合类型**

```python
@dataclass(frozen=True, slots=True)
class ContextSegmentSummary:
    segment_index: int
    role: Literal["system", "user", "assistant", "tool-result", "unknown"]
    structure_kind: Literal["message", "tool-result", "contract", "missing"]
    content_sha256: str | None
    content_length: int | None
    source_call_sha256: str | None
    missing_evidence: bool
    segment_sha256: str = field(init=False)

@dataclass(frozen=True, slots=True)
class RuntimeObservationBatch:
    run_sha256: str
    frames: tuple[ContextFrameObservation, ...]
    model_calls: tuple[ModelCallObservation, ...]
    tools: tuple[ToolCallObservation, ...]
    missing_evidence: tuple[str, ...]
    batch_sha256: str = field(init=False)

@runtime_checkable
class RuntimeObservationSource(Protocol):
    def pathlight_runtime_observation(self, run_id: str) -> Mapping[str, object] | None: ...
```

Validation must copy exact `dict/list/tuple` primitives before invoking nested methods, reject subclasses, require contiguous indexes, require every model call frame reference to resolve exactly once, require tool call digests unique, and calculate every identity with domain-separated canonical JSON.

- [ ] **Step 4: 运行 GREEN 和静态检查**

Run: `uv run python -m unittest -v tests.test_pathlight_runtime_observation && uv run pyright src/asterion/pathlight/runtime_observation.py tests/test_pathlight_runtime_observation.py && uv run ruff check src/asterion/pathlight/runtime_observation.py tests/test_pathlight_runtime_observation.py`

Expected: all tests PASS, Pyright 0 errors, Ruff PASS.

- [ ] **Step 5: 提交**

```bash
git add src/asterion/pathlight/runtime_observation.py src/asterion/pathlight/__init__.py tests/test_pathlight_runtime_observation.py
git commit -m "feat: define safe runtime observations"
```

---

### Task 2: 从 Pi native events 生成逐调用 ContextFrame

**Files:**
- Create: `src/asterion/runtimes/pi_observation.py`
- Modify: `src/asterion/runtimes/pi.py`
- Modify: `src/asterion/runtime/defaults.py`
- Test: `tests/test_pi_pathlight_observation.py`
- Test: `tests/test_asterion_pi_runtime.py`

**Interfaces:**
- Consumes: Task 1 `RuntimeObservationBatch` types；Pi `provider_request_context`、`message_end`、`tool_execution_start/end` native events。
- Produces: `PiObservationBuilder.consume(event, timestamp_ns)`、`checkpoint()`、`rollback(checkpoint)`、`complete(run_id)`；`PiRuntimeClient.pathlight_runtime_observation(run_id)`。

- [ ] **Step 1: 写失败测试，证明每次 provider request 有独立 frame/call**

```python
def test_pi_builder_links_tool_result_into_the_next_model_frame(self) -> None:
    builder = PiObservationBuilder(_clock())
    builder.consume(_provider_context(1, [_user("q")]), 10)
    builder.consume(_tool_start("c1", "grep", {"pattern": "secret"}), 20)
    builder.consume(_tool_end("c1", "secret result", False), 30)
    builder.consume(_provider_context(2, [_user("q"), _tool_result("c1", "secret result")]), 40)
    builder.consume(_assistant_end("answer", input_tokens=20, output_tokens=4), 50)
    batch = builder.complete("run-private")

    self.assertEqual(len(batch.frames), 2)
    self.assertEqual(len(batch.model_calls), 2)
    self.assertEqual(batch.frames[1].segments[-1].source_call_sha256, _digest_call("c1"))
    self.assertNotIn("secret", json.dumps(batch.to_mapping()))
```

Add cases for retry rollback, duplicate request index, malformed context, tool error, repeated timestamps, cancellation and no `provider_request_context`.

- [ ] **Step 2: 运行 RED**

Run: `uv run python -m unittest -v tests.test_pi_pathlight_observation`

Expected: import failure for `PiObservationBuilder`.

- [ ] **Step 3: 实现 Pi builder 和 runtime source**

```python
@dataclass(frozen=True, slots=True)
class PiObservationCheckpoint:
    frame_count: int
    model_call_count: int
    tool_count: int

class PiObservationBuilder:
    def consume(self, event: Mapping[str, object], timestamp_ns: int) -> None: ...
    def checkpoint(self) -> PiObservationCheckpoint: ...
    def rollback(self, checkpoint: PiObservationCheckpoint) -> None: ...
    def complete(self, run_id: str) -> RuntimeObservationBatch: ...
```

`_collect_runtime_snapshot()` 在读取每条 native JSON 后立即调用 builder，但只把 completed batch 放入 `_RuntimeSnapshot`；`willRetry` 必须同时回滚 adapter events 和 observation checkpoint。`PiRuntimeClient` 仅在 normalized stream 验证并发布私有 evidence 后保存 batch mapping。`pathlight_runtime_observation()` 验证 run ID 属于本实例的已完成 run，再返回深拷贝 mapping；异常只返回 `None`。

- [ ] **Step 4: GREEN、回归和隐私检查**

Run: `uv run python -m unittest -v tests.test_pi_pathlight_observation tests.test_asterion_pi_runtime tests.test_runtime_adapter_redaction`

Expected: PASS；JSON/repr 中无 sentinel prompt、tool args/result、provider/model 名或私有路径。

- [ ] **Step 5: 静态检查并提交**

```bash
uv run pyright src/asterion/runtimes/pi_observation.py src/asterion/runtimes/pi.py tests/test_pi_pathlight_observation.py
uv run ruff check src/asterion/runtimes/pi_observation.py src/asterion/runtimes/pi.py src/asterion/runtime/defaults.py tests/test_pi_pathlight_observation.py tests/test_asterion_pi_runtime.py
git add src/asterion/runtimes/pi_observation.py src/asterion/runtimes/pi.py src/asterion/runtime/defaults.py tests/test_pi_pathlight_observation.py tests/test_asterion_pi_runtime.py
git commit -m "feat: observe Pi model context flow"
```

---

### Task 3: 为 Claude stream-json 生成显式不完整的调用主线

**Files:**
- Create: `src/asterion/runtimes/claude_observation.py`
- Modify: `src/asterion/runtimes/claude_code.py`
- Test: `tests/test_claude_pathlight_observation.py`
- Test: `tests/test_asterion_claude_runtime.py`

**Interfaces:**
- Consumes: Task 1 contracts；Claude `assistant`、`user/tool_result`、`result` events。
- Produces: `ClaudeObservationBuilder` 和 `ClaudeCodeRuntimeClient.pathlight_runtime_observation()`。

- [ ] **Step 1: 写 RED 测试，禁止伪造 provider request boundary**

```python
def test_claude_builder_records_known_segments_and_marks_request_boundary_missing(self) -> None:
    builder = ClaudeObservationBuilder()
    builder.consume(_assistant_tool_use("c1", "Grep", {"pattern": "secret"}), 10)
    builder.consume(_user_tool_result("c1", "secret result"), 20)
    builder.consume(_assistant_text("answer"), 30)
    batch = builder.complete("run-private")

    self.assertTrue(all(not call.boundary_observed for call in batch.model_calls))
    self.assertIn("model-request-boundary", batch.missing_evidence)
    self.assertEqual(batch.frames[-1].segments[-1].role, "tool-result")
    self.assertNotIn("secret", json.dumps(batch.to_mapping()))
```

- [ ] **Step 2: 运行 RED**

Run: `uv run python -m unittest -v tests.test_claude_pathlight_observation`

Expected: import failure.

- [ ] **Step 3: 实现保守 builder**

Claude builder 只累计 stream 中实际出现的 assistant/tool-result 摘要；初始 system/user 内容只记录 host 已知 input digest 和 `missing_evidence=True`，不声称拥有完整 provider request。失败 `result` 形成 failed model call；重放同一 raw stream 得到相同 batch digest。

- [ ] **Step 4: GREEN、静态检查和提交**

```bash
uv run python -m unittest -v tests.test_claude_pathlight_observation tests.test_asterion_claude_runtime tests.test_runtime_adapter_redaction
uv run pyright src/asterion/runtimes/claude_observation.py src/asterion/runtimes/claude_code.py tests/test_claude_pathlight_observation.py
uv run ruff check src/asterion/runtimes/claude_observation.py src/asterion/runtimes/claude_code.py tests/test_claude_pathlight_observation.py
git add src/asterion/runtimes/claude_observation.py src/asterion/runtimes/claude_code.py tests/test_claude_pathlight_observation.py tests/test_asterion_claude_runtime.py
git commit -m "feat: observe Claude context boundaries safely"
```

---

### Task 4: 交叉验证 observation 并投影为 Pathlight 数据流

**Files:**
- Modify: `src/asterion/pathlight/protocol.py`
- Modify: `src/asterion/workflow_evidence/runtime.py`
- Modify: `src/asterion/workflow_evidence/storage.py`
- Test: `tests/test_workflow_evidence_runtime.py`
- Test: `tests/test_workflow_evidence_storage.py`
- Test: `tests/test_pathlight_protocol.py`

**Interfaces:**
- Consumes: Task 1 batch mapping and unchanged Agent Runtime v1 stream。
- Produces: rich ContextFrame/model/tool spans in the existing `TraceGraph`; fallback projection when no valid native observation exists。

- [ ] **Step 1: 写 RED 测试，要求原子 rich projection 和 mismatch fallback**

```python
async def test_native_observation_projects_frame_segments_model_calls_and_tool_flow(self) -> None:
    runtime = ObservedFixtureRuntime(_valid_batch_mapping())
    recorder = MemoryPathlightRecorder(TRACE_ID)
    observed = ObservedRuntimeClient(runtime, pathlight=recorder, monotonic_ns=IncrementingClock())
    yielded = [event async for event in observed.run(_request())]
    graph = recorder.snapshot()

    self.assertEqual(yielded, runtime.yielded)
    self.assertEqual(_kinds(graph).count("model-call"), 2)
    self.assertEqual(_segment_indexes(graph), [0, 1, 2])
    self.assertIn("consumed-by", _relations(graph))
    self.assertIn("produced-by", _relations(graph))

async def test_mismatched_native_tool_digest_does_not_publish_a_partial_rich_trace(self) -> None:
    runtime = ObservedFixtureRuntime(_batch_with_wrong_tool_digest())
    recorder = MemoryPathlightRecorder(TRACE_ID)
    observed = ObservedRuntimeClient(runtime, pathlight=recorder)
    _ = [event async for event in observed.run(_request())]
    graph = recorder.snapshot()
    self.assertNotIn("model-call", _kinds(graph))
    self.assertTrue(_context_frames(graph)[0]["attributes"]["missing_evidence"])
```

- [ ] **Step 2: 运行 RED**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_runtime tests.test_pathlight_protocol`

Expected: rich model/context assertions fail.

- [ ] **Step 3: 扩充固定安全 attributes 并实现投影**

Add only these scalar attributes to `protocol.py`: `boundary_observed`, `frame_index`, `request_index`, `segment_count`, `segment_index`, `segment_role`, `source_call_sha256`, `request_sha256`, `response_sha256`, `response_length`, `observation_sha256`。Roles and structure kinds use fixed enums; counts are non-negative exact ints.

`ObservedRuntimeClient` sequence:

```python
evidence = collect_workflow_evidence(events, input_digest=input_digest)
native = _validated_runtime_observation(self._runtime, request, events)
_RuntimePathlightProjection(self._pathlight).project(
    request, observations, evidence=evidence, native_observation=native, ...
)
```

Cross-validation requires run digest match, every native tool call digest/name/arguments/result/error match the normalized stream summary, model/frame references close, and batch canonical digest verify. Rich events are assembled in memory and committed once with `record_many()`；任何异常都清空 rich candidate 并执行现有 missing-evidence fallback，不改 runtime result。

- [ ] **Step 4: GREEN、存储重读与 hostile source 检查**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_runtime tests.test_workflow_evidence_storage tests.test_pathlight_protocol`

Expected: PASS；source property 抛出 sentinel、返回 hostile Mapping、cross-run batch、重复 frame/tool、非单调时间均不泄漏且不产生 partial rich trace。

- [ ] **Step 5: 静态检查并提交**

```bash
uv run pyright src/asterion/pathlight/protocol.py src/asterion/workflow_evidence/runtime.py src/asterion/workflow_evidence/storage.py
uv run ruff check src/asterion/pathlight/protocol.py src/asterion/workflow_evidence/runtime.py src/asterion/workflow_evidence/storage.py tests/test_workflow_evidence_runtime.py tests/test_workflow_evidence_storage.py tests/test_pathlight_protocol.py
git add src/asterion/pathlight/protocol.py src/asterion/workflow_evidence/runtime.py src/asterion/workflow_evidence/storage.py tests/test_workflow_evidence_runtime.py tests/test_workflow_evidence_storage.py tests/test_pathlight_protocol.py
git commit -m "feat: project verified runtime data flow"
```

---

### Task 5: 提供 provider-free ContextFrame 主线查询与 CLI

**Files:**
- Create: `src/asterion/pathlight/flow.py`
- Modify: `src/asterion/pathlight/__init__.py`
- Modify: `src/asterion/cli_pathlight.py`
- Test: `tests/test_pathlight_flow.py`
- Test: `tests/test_pathlight_cli.py`

**Interfaces:**
- Consumes: verified `TraceGraph` mapping。
- Produces: `project_trace_flow(trace) -> tuple[Mapping[str, object], ...]` and `asterion pathlight trace flow`。

- [ ] **Step 1: 写 RED 测试，要求明显主线而非事件堆砌**

```python
def test_flow_projects_frame_model_tool_frame_mainline(self) -> None:
    flow = project_trace_flow(_rich_trace())
    self.assertEqual(
        [(node["kind"], node["status"]) for node in flow],
        [("context-frame", "completed"), ("model-call", "completed"),
         ("tool-call", "completed"), ("context-frame", "completed"),
         ("model-call", "completed")],
    )
    self.assertEqual(flow[3]["caused_by_sequence"], flow[2]["sequence"])
    self.assertNotIn("SENTINEL", json.dumps(flow))
```

- [ ] **Step 2: 运行 RED**

Run: `uv run python -m unittest -v tests.test_pathlight_flow tests.test_pathlight_cli`

Expected: missing `project_trace_flow` / `trace flow`.

- [ ] **Step 3: 实现只读投影和 CLI**

Flow node 只返回 sequence、kind、status、parent sequence、caused/consumed/produced link sequence、固定安全 attributes 和 missing evidence；拒绝断链、循环、未知 relation 或未闭合 trace。CLI：

```text
asterion pathlight trace flow --evidence-file /ABS/workflow-evidence.json --trace-id UUID
```

输出单行 canonical JSON；读取仍为 0600 regular no-follow；所有错误固定为 `asterion pathlight: request is invalid`。

- [ ] **Step 4: GREEN、静态检查和提交**

```bash
uv run python -m unittest -v tests.test_pathlight_flow tests.test_pathlight_cli tests.test_pathlight_query
uv run pyright src/asterion/pathlight/flow.py src/asterion/cli_pathlight.py tests/test_pathlight_flow.py tests/test_pathlight_cli.py
uv run ruff check src/asterion/pathlight/flow.py src/asterion/cli_pathlight.py tests/test_pathlight_flow.py tests/test_pathlight_cli.py
git add src/asterion/pathlight/flow.py src/asterion/pathlight/__init__.py src/asterion/cli_pathlight.py tests/test_pathlight_flow.py tests/test_pathlight_cli.py
git commit -m "feat: query Pathlight context flow"
```

---

### Task 6: 生成 coverage-only gold registry 并计算逐例 coverage

**Files:**
- Create: `src/asterion/capabilities/dci/implementation/pathlight/coverage.py`
- Create: `src/asterion/capabilities/dci/resources/retrieval-coverage-manifest.schema.json`
- Create: `src/asterion/capabilities/dci/resources/retrieval-coverage-registry.schema.json`
- Modify: `src/asterion/capabilities/dci/implementation/research/trajectory_resolution.py`
- Modify: `src/asterion/capabilities/dci/implementation/_provenance.py`
- Modify: `src/asterion/capabilities/dci/implementation/reproduction/provenance.py`
- Test: `tests/test_dci_pathlight_coverage.py`
- Test: `tests/test_dci_trajectory_resolution.py`
- Test: `tests/test_dci_complete_application.py`

**Interfaces:**
- Consumes: validated IR dataset rows、operator-owned corpus、externalized tool results、latest model context。
- Produces: `prepare_coverage_registry()`、`analyze_coverage_run()`、`DciCoverageRecord` and safe `coverage_microunits`/retained coverage projection。

- [ ] **Step 1: 写 RED 测试，证明不需要伪造 evidence spans**

```python
def test_coverage_registry_binds_exact_rows_and_documents_without_evidence_spans(self) -> None:
    registry = prepare_coverage_registry(
        dataset_id="bright.biology",
        dataset_path=dataset,
        corpus_dir=corpus,
        selected_count=10,
        output_root=output,
    )
    self.assertEqual(registry.selected_count, 10)
    manifest = json.loads((output / registry.manifests[0].relative_path).read_text())
    self.assertEqual(set(manifest), {"schema", "dataset_id", "query_id", "documents"})
    self.assertNotIn("evidence_spans", json.dumps(manifest))

def test_coverage_analysis_reports_surfaced_and_retained_without_localization_claim(self) -> None:
    record = analyze_coverage_run(run_dir=run, corpus_dir=corpus, manifest=manifest)
    self.assertEqual(record.coverage_microunits, 500_000)
    self.assertIsNone(record.localization_microunits)
    self.assertEqual(record.evidence_state, "observed")
```

- [ ] **Step 2: 运行 RED**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_coverage`

Expected: import failure.

- [ ] **Step 3: 实现 descriptor-safe registry 和 coverage-only analyzer**

Manifest v1 exact fields: `schema`、`dataset_id`、`query_id`、`documents[{id,path,sha256}]`。Registry v1 exact fields: `schema`、`dataset_id`、`selected_ids_sha256`、`manifests[{query_sha256,path,sha256}]`；公开对象只保留 query digest，私有 manifest 保留原 query/document IDs。

`prepare_coverage_registry()` 必须按 dataset source order 选前 N 条，使用现有 `normalize_retrieved_path()` 绑定 gold ID 到一个 exact non-symlink UTF-8 corpus file，双读并 revalidate size/dev/inode/mtime/digest；0700 root、0600 canonical JSON、exclusive staging publish。

`trajectory_resolution.py` 接受新的 coverage-only manifest，复用 `_externalized_observations()`、`_align()`、`compute_query_coverage()` 和 retained-context validation；`evidence_spans` 缺失时 localization 必须是 unavailable，不能把整篇文档伪装为 gold span。

- [ ] **Step 4: GREEN、schema/provenance/promotion 检查**

```bash
uv run python -m unittest -v tests.test_dci_pathlight_coverage tests.test_dci_trajectory_resolution tests.test_dci_complete_application
make docs-check
make promotion-check
```

Expected: PASS，packaged schemas present，provider operations 0。

- [ ] **Step 5: 静态检查并提交**

```bash
uv run pyright src/asterion/capabilities/dci/implementation/pathlight/coverage.py src/asterion/capabilities/dci/implementation/research/trajectory_resolution.py
uv run ruff check src/asterion/capabilities/dci/implementation/pathlight/coverage.py src/asterion/capabilities/dci/implementation/research/trajectory_resolution.py tests/test_dci_pathlight_coverage.py tests/test_dci_trajectory_resolution.py
git add src/asterion/capabilities/dci/implementation/pathlight/coverage.py src/asterion/capabilities/dci/resources/retrieval-coverage-manifest.schema.json src/asterion/capabilities/dci/resources/retrieval-coverage-registry.schema.json src/asterion/capabilities/dci/implementation/research/trajectory_resolution.py src/asterion/capabilities/dci/implementation/_provenance.py src/asterion/capabilities/dci/implementation/reproduction/provenance.py tests/test_dci_pathlight_coverage.py tests/test_dci_trajectory_resolution.py tests/test_dci_complete_application.py
git commit -m "feat: measure DCI retrieval coverage"
```

---

### Task 7: 将 coverage registry 接入 exact DCI benchmark invocation

**Files:**
- Modify: `src/asterion/capabilities/dci/implementation/operator_inputs.py`
- Modify: `src/asterion/capabilities/dci/implementation/benchmark_bindings.py`
- Modify: `src/asterion/applications/dci_agent_lite/operator_config.py`
- Modify: `src/asterion/applications/dci_agent_lite/benchmark_executor.py`
- Modify: `src/asterion/capabilities/dci/implementation/evaluation/benchmark.py`
- Test: `tests/test_dci_operator_inputs.py`
- Test: `tests/test_dci_benchmark_real_executor.py`
- Test: `tests/test_asterion_dci_benchmark.py`

**Interfaces:**
- Consumes: Task 6 coverage registry mapping。
- Produces: private `coverage_registry_roots` binding and `BenchmarkRequest.coverage_registry` execution path。

- [ ] **Step 1: 写 RED 测试，要求 exact task/root binding 和 IR-only execution**

```python
def test_real_ir_executor_enables_externalized_results_and_exact_coverage_registry(self) -> None:
    executor.execute(_invocation("bright.biology", coverage_registry=registry), ...)
    request = runner.call_args.args[0]
    self.assertEqual(request.coverage_registry, registry)
    self.assertTrue(request.conversation_features.externalize_tool_results)
    self.assertIsNone(request.judge_config.api_key)

def test_qa_or_cross_task_registry_fails_before_agent_execution(self) -> None:
    with self.assertRaisesRegex(DciBenchmarkExecutorError, "not executable"):
        executor.execute(_invocation("qa.bamboogle.paper-full125", coverage_registry=registry), ...)
    runner.assert_not_called()
```

- [ ] **Step 2: 运行 RED**

Run: `uv run python -m unittest -v tests.test_dci_operator_inputs tests.test_dci_benchmark_real_executor`

Expected: missing coverage input fields/assertions fail.

- [ ] **Step 3: 实现 private binding 和 request branch**

`DciBenchmarkOperatorInputs` 增加 `coverage_registry_roots: Mapping[str, Path]`，但不进入 public arguments、manifests、plan 或 repr。`load_operator_config()` 只从显式 `ASTERION_DCI_COVERAGE_ROOT` 构造五个 exact registry path；未配置时 mapping 为空。Invocation payload 增加 repr-redacted `coverage_registry: Path | None`。

IR request 有 registry 时：`conversation_features=DciConversationFeatures(externalize_tool_results=True)`、`coverage_registry=...`、no Judge connectivity probe；registry dataset/task/scope mismatch 在 Agent 调用前失败。没有 registry 的既有 benchmark 行为不变。

- [ ] **Step 4: GREEN、静态检查和提交**

```bash
uv run python -m unittest -v tests.test_dci_operator_inputs tests.test_dci_benchmark_real_executor tests.test_asterion_dci_benchmark tests.test_dci_capability_payload
uv run pyright src/asterion/capabilities/dci/implementation/operator_inputs.py src/asterion/capabilities/dci/implementation/benchmark_bindings.py src/asterion/applications/dci_agent_lite/benchmark_executor.py
uv run ruff check src/asterion/capabilities/dci/implementation/operator_inputs.py src/asterion/capabilities/dci/implementation/benchmark_bindings.py src/asterion/applications/dci_agent_lite/operator_config.py src/asterion/applications/dci_agent_lite/benchmark_executor.py tests/test_dci_operator_inputs.py tests/test_dci_benchmark_real_executor.py
git add src/asterion/capabilities/dci/implementation/operator_inputs.py src/asterion/capabilities/dci/implementation/benchmark_bindings.py src/asterion/applications/dci_agent_lite/operator_config.py src/asterion/applications/dci_agent_lite/benchmark_executor.py src/asterion/capabilities/dci/implementation/evaluation/benchmark.py tests/test_dci_operator_inputs.py tests/test_dci_benchmark_real_executor.py tests/test_asterion_dci_benchmark.py
git commit -m "feat: bind DCI coverage observations"
```

---

### Task 8: 实现 proposal prepare/execute/status 协调器

**Files:**
- Create: `src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py`
- Modify: `src/asterion/applications/dci_agent_lite/cli.py`
- Modify: `src/asterion/applications/dci_agent_lite/pathlight_cli.py`
- Modify: `src/asterion/capabilities/dci/implementation/pathlight/coverage.py`
- Test: `tests/test_dci_pathlight_experiment_cli.py`

**Interfaces:**
- Consumes: exact diagnosis/proposal digest、Task 6 registry、existing DCI benchmark host/authorization。
- Produces: `asterion-dci pathlight experiment prepare|execute|status` and immutable `pathlight-coverage-experiment.json`。

- [ ] **Step 1: 写 RED 测试，证明 prepare provider-free、execute 需独立 authority**

```python
def test_prepare_builds_exact_five_by_ten_scope_without_loading_provider(self) -> None:
    code = main(["pathlight", "experiment", "prepare", "--diagnosis-file", diagnosis,
                 "--proposal-sha256", proposal, "--output-root", output],
                entry_points=(FailIfLoadedEntryPoint(),))
    self.assertEqual(code, 0)
    plan = _read_plan(output)
    self.assertEqual(plan.agent_operation_limit, 50)
    self.assertEqual(plan.case_counts, (10, 10, 10, 10, 10))
    self.assertFalse(plan.execution_authorized)

def test_execute_rejects_missing_or_changed_authority_before_provider_or_network(self) -> None:
    with patch("...DciBenchmarkHost.run") as run:
        code = main(["pathlight", "experiment", "execute", "--plan-file", plan,
                     "--authorization-file", wrong_authority])
    self.assertEqual(code, 2)
    run.assert_not_called()
```

Add matrices for `$5` exact cap, 50 operations, five exact instance selectors, repeated/cross-swapped plan, partial roots, resume, cancellation, first and second infrastructure failure, third never launched, sentinel `.env` values and fixed stderr.

- [ ] **Step 2: 运行 RED**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_experiment_cli`

Expected: command route missing.

- [ ] **Step 3: 实现三阶段 CLI**

`prepare`：读取已验证 diagnosis，精确选择 code=`coverage-instrumentation` 的 proposal，生成五个 coverage registry 和不可执行 plan。`execute`：要求独立 0600 authorization document，内容包含 plan/proposal/scope digest、`max_agent_operations=50`、`max_cost_microusd=5_000_000`、`max_infrastructure_failures=2`、`execution_authorized=true` 和 operator approval digest；预检全部五项后顺序调用既有 DCI host，每项 `case_limit=10`，不调用 Judge。`status`：只读 plan/receipts，输出 safe counts/cost/status/digests。

所有输出用 Task 7 已验证的 private staging + exclusive link + dev/inode rollback 模式；execute 可 resume 已完成项，但不得重用不同 plan/registry/variant 的 generation。前台执行，不使用 nohup/background。

- [ ] **Step 4: GREEN、静态检查和提交**

```bash
uv run python -m unittest -v tests.test_dci_pathlight_experiment_cli tests.test_dci_pathlight_cli tests.test_dci_benchmark_host tests.test_dci_benchmark_authorization
uv run pyright src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py
uv run ruff check src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py src/asterion/applications/dci_agent_lite/pathlight_cli.py tests/test_dci_pathlight_experiment_cli.py
git add src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py src/asterion/applications/dci_agent_lite/cli.py src/asterion/applications/dci_agent_lite/pathlight_cli.py src/asterion/capabilities/dci/implementation/pathlight/coverage.py tests/test_dci_pathlight_experiment_cli.py
git commit -m "feat: coordinate DCI coverage experiment"
```

---

### Task 9: 执行 50 条 coverage 实验并刷新 Bright 诊断

**Files:**
- Modify: `src/asterion/capabilities/dci/implementation/pathlight/diagnosis.py`
- Modify: `src/asterion/applications/dci_agent_lite/pathlight_cli.py`
- Modify: `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md`
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Modify: `docs/status/INDEX.md` only if a new status report file is added
- Test: `tests/test_dci_pathlight_diagnosis.py`
- Test: `tests/test_dci_pathlight_cli.py`

**Interfaces:**
- Consumes: completed 50-case coverage experiment receipts and original six-run diagnosis。
- Produces: observed coverage metrics、updated findings、query-decomposition proposal gate decision、safe Chinese report。

- [ ] **Step 1: 写 RED 测试，要求事实/假设/缺口随 coverage evidence 更新**

```python
def test_completed_coverage_experiment_replaces_missing_coverage_with_observed_metrics(self) -> None:
    report = diagnose_dci_runs(_six_historical_packs(), coverage_experiment=_coverage_pack())
    self.assertNotIn("retrieval-coverage", report.missing_evidence)
    self.assertEqual(report.datasets[0].coverage_available_queries, 10)
    self.assertEqual(report.datasets[0].coverage_total_queries, 10)
    self.assertTrue(all(item.coverage_median_microunits is not None for item in report.datasets[:5]))
    self.assertFalse(any(finding.claims_causality for finding in report.findings))
```

- [ ] **Step 2: 运行 RED**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_diagnosis tests.test_dci_pathlight_cli`

Expected: diagnosis does not yet accept coverage experiment.

- [ ] **Step 3: 在获得精确 authorization 后前台执行**

Before this step, verify the authorization document matches the committed plan and the operator has explicitly authorized the finite external operation. Then run from a shell with inherited variables cleared and `.env` sourced exactly once:

```bash
env -i HOME="$HOME" PATH="$PATH" SHELL="$SHELL" zsh -lc '
  set -a
  source .env
  set +a
  uv run asterion-dci pathlight experiment execute \
    --plan-file "$ASTERION_PATHLIGHT_COVERAGE_PLAN" \
    --authorization-file "$ASTERION_PATHLIGHT_COVERAGE_AUTHORIZATION" \
    --output-root "$ASTERION_PATHLIGHT_COVERAGE_OUTPUT"
'
```

Expected: foreground canonical progress; five datasets each 10/10, total 50/50, Judge operations 0, cost ≤ 5 USD, infrastructure failures < 2. If stopped or interrupted, rerun the exact command and verify digest-bound resume.

- [ ] **Step 4: 实现 diagnosis merge 和中文 renderer**

Add exact safe fields per dataset: coverage available/total, median any/mean/all microunits, retained availability/value, tool observations, surfaced gold count, model-call count, context-frame count and missing boundary count. Findings must state correlations only. Enable the existing `retrieval-query-decomposition` proposal only when all five datasets have 10/10 valid coverage and no integrity failure; it remains unauthorized until its own explicit authority.

- [ ] **Step 5: 验证真实 artifacts、文档和回归**

```bash
uv run python -m unittest -v \
  tests.test_pathlight_runtime_observation \
  tests.test_pi_pathlight_observation \
  tests.test_claude_pathlight_observation \
  tests.test_workflow_evidence_runtime \
  tests.test_pathlight_flow \
  tests.test_dci_pathlight_coverage \
  tests.test_dci_pathlight_experiment_cli \
  tests.test_dci_pathlight_diagnosis \
  tests.test_dci_pathlight_cli
make test
make lint
make docs-check
make check
make promotion-check
```

Expected: every command PASS；public docs contain no operator path/case ID/provider/model/config/prompt/answer/tool payload/corpus text；report states actual 50-case coverage results and whether query decomposition is warranted。

- [ ] **Step 6: 提交**

```bash
git add src/asterion/capabilities/dci/implementation/pathlight/diagnosis.py src/asterion/applications/dci_agent_lite/pathlight_cli.py tests/test_dci_pathlight_diagnosis.py tests/test_dci_pathlight_cli.py docs/status/PATHLIGHT-DCI-DIAGNOSIS.md docs/status/DCI-BENCHMARK-INSTANCES.md docs/status/INDEX.md
git commit -m "feat: close Bright coverage diagnosis"
```

---

## Plan Self-Review

- Spec coverage: runtime/model/tool/context mainline → Tasks 1–5；DCI retrieval coverage → Tasks 6–7；explicit proposal authority/budget/stop/resume → Task 8；real 50-case diagnosis closure → Task 9。
- Dependency direction: framework tasks never import DCI；DCI coverage/CLI depend on Pathlight only in product direction。
- Protocol boundary: no Runtime v1 schema/event changes；native observation is optional and post-validation。
- Privacy: every raw native value is reduced to digest/length/fixed enum before leaving runtime-owned memory；sentinel tests exist in every boundary task。
- Scope: Opik exporter and Dashboard are intentionally separate successor plans, because neither is required to make coverage evidence authoritative。
- No placeholders: all tasks name concrete files, interfaces, RED/GREEN commands, exact authority and real-run acceptance criteria。

## Completion Audit

This plan is complete only when:

1. Pi real runs expose one verified ContextFrame/model-call/tool data-flow mainline per observed provider request.
2. Claude records all stream-visible segments and explicitly marks unavailable provider request boundaries.
3. Invalid or absent native observation never changes runtime output and never publishes partial rich trace.
4. Provider-free CLI can show the ordered context/model/tool flow from persisted evidence.
5. Five exact IR datasets have valid 10-case coverage registries and document-level coverage evidence.
6. The 50-operation experiment runs only under an exact, finite, separate authorization; Judge operations are zero and cost/stop rules are enforced.
7. Updated diagnosis distinguishes observed coverage facts, residual hypotheses and evidence gaps, and records whether the 80-operation query-decomposition proposal should proceed.
8. Full tests, lint, docs, check and promotion gates pass, followed by independent whole-stage review with no Critical or Important findings.
