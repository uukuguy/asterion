# Asterion Pathlight Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the framework-level Pathlight trace contract and capture path-safe execution traces through Asterion’s assembly, runner and runtime boundaries.

**Architecture:** Add an operator-owned `PathlightRecorder` with an immutable Trace/Span/ContextFrame graph and a no-op implementation. Inject it explicitly into `RuntimeFactoryContext` and composed execution so every core boundary can emit a safe event without changing the closed `dci.agent-runtime/v1` protocol. Preserve private content in operator evidence only through opaque references; make the existing `workflow_evidence` bundle a validated summary derived from the richer trace.

**Tech Stack:** Python 3.12, `unittest`, existing `asterion.runtime` protocol, JSON canonicalization/SHA-256, existing CLI and workflow-evidence modules.

## Global Constraints

- Framework code stays domain-neutral and must not import DCI modules, manifests, tests or adjacent source trees.
- `dci.agent-runtime/v1` remains closed: do not add runtime event types or fields in this phase.
- Default Pathlight data must never contain prompts, answers, credentials, model/tool payloads, corpus text, raw output, artifact URIs or private paths.
- Runner execution remains sequential and Pathlight cannot authorize, retry, schedule, persist private data, start services or change runtime selection.
- Inputs/results stay immutable; malformed parentage, sequence, terminal state, digest or redaction must fail closed.
- Use `unittest`; each task starts RED, reaches GREEN, then commits independently.

## File Structure

- Create: `src/asterion/pathlight/protocol.py` — immutable public Trace/Span/ContextFrame event model, validation and canonical digest.
- Create: `src/asterion/pathlight/recorder.py` — `PathlightRecorder`, no-op recorder and in-memory immutable recorder.
- Create: `src/asterion/pathlight/__init__.py` — narrow public framework exports.
- Modify: `src/asterion/runtime/factory.py` — explicit optional recorder in `RuntimeFactoryContext`.
- Modify: `src/asterion/runner/composed.py` — emit plan/task lifecycle spans around existing execution without changing result semantics.
- Modify: `src/asterion/workflow_evidence/runtime.py` — turn one runtime invocation into a Pathlight runtime/model/tool/context trace while preserving the existing summary API.
- Modify: `src/asterion/cli.py` — construct one recorder only when `--workflow-evidence-file` is explicitly requested and append derived safe trace records to the existing bundle.
- Modify: `src/asterion/workflow_evidence/storage.py` — accept the validated trace projection while preserving exclusive, body-free output.
- Create: `tests/test_pathlight_protocol.py` — graph integrity, ordering, redaction and immutability.
- Create: `tests/test_pathlight_recorder.py` — recorder lifecycle and no-op equivalence.
- Modify: `tests/test_workflow_evidence_runtime.py` — runtime/context/tool trace integration.
- Modify: `tests/test_asterion_cli.py` — opt-in lifecycle capture and no leakage.
- Modify: `tests/test_default_runtime_factory.py` and `tests/test_runner_composed.py` — explicit injection and unchanged execution behavior.

---

### Task 1: Define the public-safe Pathlight graph contract

**Files:**
- Create: `src/asterion/pathlight/protocol.py`
- Create: `src/asterion/pathlight/__init__.py`
- Test: `tests/test_pathlight_protocol.py`

**Interfaces:**
- Produces `PathlightError`, `TraceEvent`, `TraceGraph`, `validate_trace_graph(graph)` and `trace_graph_digest(graph)`.
- `TraceEvent` is a frozen dataclass with `trace_id`, `span_id`, `parent_span_id`, `sequence`, `kind`, `status`, `attributes`, `links` and `timestamp_ns`.
- Later tasks consume only `append(event: TraceEvent)` and `snapshot() -> Mapping[str, object]`.

- [ ] **Step 1: Write failing graph-contract tests**

```python
def test_trace_graph_preserves_context_flow_without_text() -> None:
    graph = TraceGraph.build(
        trace_id="trace-1",
        events=(
            TraceEvent.start("trace-1", "root", None, 1, "task"),
            TraceEvent.complete("trace-1", "root", 2),
        ),
    )
    payload = graph.to_mapping()
    self.assertEqual(payload["schema"], "asterion.pathlight-trace/v1")
    self.assertNotIn("input_text", repr(payload))
    validate_trace_graph(payload)

def test_rejects_noncontiguous_sequence_and_unknown_parent() -> None:
    with self.assertRaises(PathlightError):
        TraceGraph.build("trace-1", (TraceEvent.start("trace-1", "x", "missing", 2, "task"),))
```

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_pathlight_protocol`  
Expected: FAIL because `asterion.pathlight` does not exist.

- [ ] **Step 3: Implement the minimal canonical graph**

```python
TRACE_SCHEMA = "asterion.pathlight-trace/v1"
SAFE_KINDS = frozenset({"plan", "assembly", "task", "runtime", "context-frame", "model-call", "tool-call", "host-service", "evaluation", "artifact"})
SAFE_STATUSES = frozenset({"started", "completed", "failed", "cancelled", "skipped"})

@dataclass(frozen=True)
class TraceEvent:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    sequence: int
    kind: str
    status: str
    attributes: Mapping[str, str | int | bool]
    links: Sequence[Mapping[str, str]]
    timestamp_ns: int

def validate_trace_graph(graph: Mapping[str, object]) -> None:
    """Raise PathlightError unless a canonical safe graph is valid."""
    _validate_trace_graph(graph)
```

Reject unknown fields, unsafe attribute keys, duplicate span IDs, missing root, non-contiguous sequences, unmatched terminals, cross-trace links and a digest mismatch. Permit only safe attribute names such as `content_sha256`, `content_length`, `structure_kind`, `failure_class`, `metric_name`, `metric_value`, `unit`, `component_id` and opaque `evidence_ref` digest; reject arbitrary user-supplied keys.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_pathlight_protocol`  
Expected: PASS, including secret-sentinel and malformed-graph matrices.

- [ ] **Step 5: Commit the contract**

```bash
git add src/asterion/pathlight tests/test_pathlight_protocol.py
git commit -m "feat: define pathlight trace contract"
```

### Task 2: Add explicit, immutable recorder injection

**Files:**
- Create: `src/asterion/pathlight/recorder.py`
- Modify: `src/asterion/pathlight/__init__.py`
- Modify: `src/asterion/runtime/factory.py`
- Test: `tests/test_pathlight_recorder.py`
- Test: `tests/test_default_runtime_factory.py`

**Interfaces:**
- Consumes `TraceEvent` and `TraceGraph` from Task 1.
- Produces `PathlightRecorder.record(event)`, `snapshot()`, `NoopPathlightRecorder`, and `MemoryPathlightRecorder`.
- Extends `RuntimeFactoryContext` with `pathlight: PathlightRecorder = NOOP_PATHLIGHT_RECORDER`.

- [ ] **Step 1: Write failing recorder and factory-context tests**

```python
def test_memory_recorder_returns_valid_immutable_snapshot(self) -> None:
    recorder = MemoryPathlightRecorder("trace-1")
    recorder.record(TraceEvent.start("trace-1", "task", None, 1, "task"))
    recorder.record(TraceEvent.complete("trace-1", "task", 2))
    snapshot = recorder.snapshot()
    validate_trace_graph(snapshot)
    with self.assertRaises(TypeError):
        snapshot["trace_id"] = "mutated"  # type: ignore[index]

def test_factory_context_defaults_to_noop_pathlight(self) -> None:
    self.assertIsInstance(context.pathlight, NoopPathlightRecorder)
```

- [ ] **Step 2: Run focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_pathlight_recorder tests.test_default_runtime_factory`  
Expected: FAIL because recorder types and context field are absent.

- [ ] **Step 3: Implement recorder semantics**

```python
class PathlightRecorder(Protocol):
    def record(self, event: TraceEvent) -> None:
        """Accept one safe event for this recorder's trace."""

    def snapshot(self) -> Mapping[str, object] | None:
        """Return the validated public graph, or None for no-op."""

class NoopPathlightRecorder:
    def record(self, event: TraceEvent) -> None: pass
    def snapshot(self) -> Mapping[str, object] | None: return None

class MemoryPathlightRecorder:
    def __init__(self, trace_id: str) -> None:
        self._trace_id = trace_id
        self._events: list[TraceEvent] = []

    def record(self, event: TraceEvent) -> None:
        self._events.append(event)

    def snapshot(self) -> Mapping[str, object]:
        return TraceGraph.build(self._trace_id, tuple(self._events)).to_mapping()
```

`MemoryPathlightRecorder` must reject an event for another trace before recording it, copy allowed attribute/link mappings into immutable values, and validate the complete graph at snapshot time. The no-op implementation must neither retain events nor expose private input.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_pathlight_recorder tests.test_default_runtime_factory`  
Expected: PASS.

- [ ] **Step 5: Commit recorder injection**

```bash
git add src/asterion/pathlight src/asterion/runtime/factory.py tests/test_pathlight_recorder.py tests/test_default_runtime_factory.py
git commit -m "feat: inject pathlight recorder into runtimes"
```

### Task 3: Trace composed execution without changing its behavior

**Files:**
- Modify: `src/asterion/runner/composed.py`
- Modify: `tests/test_runner_composed.py`
- Modify: `tests/test_asterion_cli.py`

**Interfaces:**
- Consumes optional `PathlightRecorder` from the runtime factory context.
- Produces one root task span, one plan span and one capability/task span with exact completion, failure or cancellation state.
- Does not alter `run_composed_application` return value, sequencing, cancellation handling or public result projection.

- [ ] **Step 1: Write failing runner tests**

```python
async def test_composed_run_records_lifecycle_in_execution_order(self) -> None:
    recorder = MemoryPathlightRecorder("run-1")
    await run_composed_application(
        plan, implementations=implementations, runtime=runtime,
        run_id="run-1", input_text="safe input", host_services={}, pathlight=recorder,
    )
    events = recorder.snapshot()["events"]
    self.assertEqual([item["kind"] for item in events], ["plan", "task", "task"])
    self.assertEqual(events[-1]["status"], "completed")

async def test_composed_failure_records_fixed_failure_class(self) -> None:
    with self.assertRaises(ApplicationRunError):
        await run_composed_application(
            failing_plan, implementations=failing_implementations, runtime=runtime,
            run_id="run-1", input_text="safe input", host_services={}, pathlight=recorder,
        )
    event = next(item for item in recorder.snapshot()["events"] if item["status"] == "failed")
    self.assertEqual(event["attributes"]["failure_class"], "capability-execution-failed")
```

- [ ] **Step 2: Run focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_runner_composed tests.test_asterion_cli.AsterionCliTests.test_run_writes_opt_in_safe_workflow_evidence`  
Expected: FAIL because composed execution does not accept a recorder.

- [ ] **Step 3: Add boundary-only lifecycle instrumentation**

Pass `pathlight` explicitly from `_run` to `run_composed_application`; emit lifecycle events immediately before and after the existing plan and capability calls. Map only existing trusted exception classes to fixed failure classes. Re-raise exactly the same exception; never catch an exception merely to continue execution. The recorder remains optional and the default path emits nothing.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_runner_composed tests.test_asterion_cli`  
Expected: PASS; existing output and cancellation assertions remain unchanged.

- [ ] **Step 5: Commit composed tracing**

```bash
git add src/asterion/runner/composed.py src/asterion/cli.py tests/test_runner_composed.py tests/test_asterion_cli.py
git commit -m "feat: trace composed execution lifecycle"
```

### Task 4: Project runtime streams into ContextFrame, model and tool spans

**Files:**
- Modify: `src/asterion/workflow_evidence/runtime.py`
- Modify: `src/asterion/workflow_evidence/collector.py`
- Modify: `tests/test_workflow_evidence_runtime.py`
- Modify: `tests/test_workflow_evidence.py`

**Interfaces:**
- Consumes a `PathlightRecorder` and the existing validated `RunEvent` stream.
- Produces safe `context-frame`, `model-call`, `tool-call`, `usage` metric and terminal spans; original `RunEvent` objects remain byte-for-byte behaviorally unchanged.
- Continues to expose `ObservedRuntimeClient.records` as `asterion.workflow-evidence/v1` summaries for backward compatibility.

- [ ] **Step 1: Write failing integration tests**

```python
async def test_observed_runtime_links_tool_result_to_next_context_frame(self) -> None:
    recorder = MemoryPathlightRecorder("run-1")
    client = ObservedRuntimeClient(runtime, pathlight=recorder)
    events = [event async for event in client.run(request)]
    self.assertEqual(events, expected_events)
    graph = recorder.snapshot()
    tool_result = next(item for item in graph["events"] if item["kind"] == "tool-call" and item["status"] == "completed")
    self.assertIn("derived-from", [link["relation"] for link in tool_result["links"]])
    self.assertNotIn("sentinel-secret", repr(graph))
```

Include success, tool error, stream exception, cancellation, unmatched tool event and usage-only stream matrices. Verify that no raw `arguments`, `content`, `text`, `uri`, prompt or exception string enters the graph.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_runtime tests.test_workflow_evidence`  
Expected: FAIL because `ObservedRuntimeClient` cannot receive a recorder and emits no Pathlight spans.

- [ ] **Step 3: Implement safe projection**

Derive ContextFrame segment summaries only from trusted protocol fields: request input becomes a SHA-256 plus byte length; `tool.call` becomes name/call identity plus argument canonical digest and byte length; `tool.result` becomes result digest/length plus `is_error`; `usage.reported` becomes numeric metrics. Because the closed runtime protocol has no raw model-request event, create a `model-call` span only when the adapter provides an explicit safe model-call boundary through the injected recorder; otherwise emit a `missing-evidence` attribute rather than inventing a call.

Keep `collect_workflow_evidence` as a summary projection from validated trace-compatible observations; its public schema and existing tests remain compatible.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_runtime tests.test_workflow_evidence`  
Expected: PASS, including redaction sentinels and unchanged yielded event identity.

- [ ] **Step 5: Commit runtime projection**

```bash
git add src/asterion/workflow_evidence tests/test_workflow_evidence_runtime.py tests/test_workflow_evidence.py
git commit -m "feat: project runtime flows into pathlight"
```

### Task 5: Persist an opt-in public Pathlight projection

**Files:**
- Modify: `src/asterion/workflow_evidence/storage.py`
- Modify: `src/asterion/cli.py`
- Modify: `tests/test_asterion_cli.py`
- Modify: `tests/test_workflow_evidence_storage.py`
- Modify: `docs/cli.md`

**Interfaces:**
- Consumes a validated TraceGraph only when the user passed `--workflow-evidence-file`.
- Produces `workflow-evidence.json` with existing summary records plus a `pathlight_traces` array of validated public graphs.
- Does not create a trace store, directory or output on ordinary `asterion run`.

- [ ] **Step 1: Write failing persistence and CLI tests**

```python
def test_bundle_rejects_tampered_pathlight_graph(self) -> None:
    with self.assertRaises(WorkflowEvidenceError):
        write_workflow_observation_bundle(target, records, pathlight_traces=(tampered,))

def test_cli_opt_in_writes_safe_trace_projection(self) -> None:
    exit_code = main(["--provider", "fixture", "--application", "fixture.app@1.0.0", "--input", "safe input", "--workflow-evidence-file", str(target)])
    self.assertEqual(exit_code, 0)
    payload = json.loads(target.read_text())
    self.assertEqual(payload["pathlight_traces"][0]["schema"], "asterion.pathlight-trace/v1")
```

- [ ] **Step 2: Run focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_storage tests.test_asterion_cli`  
Expected: FAIL because bundle writing has no `pathlight_traces` input.

- [ ] **Step 3: Implement exclusive safe persistence and documentation**

Extend `write_workflow_observation_bundle` with keyword-only `pathlight_traces: Sequence[Mapping[str, object]] = ()`; validate all traces before opening the output file, reject duplicate trace IDs, serialize canonical JSON with the existing `0600` exclusive-create semantics, and include their digests in `bundle_sha256`. Update `docs/cli.md` with the opt-in output shape, redaction guarantee and no automatic capture claim.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_storage tests.test_asterion_cli && make docs-check`  
Expected: PASS.

- [ ] **Step 5: Commit opt-in projection**

```bash
git add src/asterion/cli.py src/asterion/workflow_evidence/storage.py docs/cli.md tests/test_asterion_cli.py tests/test_workflow_evidence_storage.py
git commit -m "feat: export pathlight trace projection"
```

### Task 6: Perform core acceptance verification

**Files:**
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md` only if the verified result report changes; otherwise no documentation mutation.

- [ ] **Step 1: Run all core tests and static gates**

Run: `make test && make lint && make docs-check && make check`  
Expected: all commands exit 0.

- [ ] **Step 2: Run a provider-free CLI trace smoke test**

Run: `uv run python -m unittest -v tests.test_asterion_cli.AsterionCliTests.test_run_writes_opt_in_safe_workflow_evidence`  
Expected: PASS; generated trace is safe and existing default CLI behavior has no trace output.

- [ ] **Step 3: Record only verified closure evidence**

Append a journal entry with the exact passing commands and commit hash. Do not claim Bright diagnosis or optimization completion in this phase; those require the later evaluation/adapter plan.

## Follow-on Plans

1. `2026-08-02-asterion-pathlight-query-evaluation.md`: local query API, `trace`/`metrics`/`evaluate` CLI and safe historical evidence recovery.
2. `2026-08-02-asterion-pathlight-diagnosis.md`: DCI adapter, Bright/SciFact/Bamboogle factual report, comparison rules and authorized small-sample proposals.
3. `2026-08-02-asterion-pathlight-dashboard.md`: API-only operator-local Dashboard after query API stability.
