# DCI Pathlight Prospective Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each newly completed native DCI run persist one validated, content-safe Pathlight workflow bundle, then prove the path with one authorized Bright Biology case.

**Architecture:** A domain-neutral completed-runtime projector turns an already validated runtime event stream plus an optional native observation batch into one workflow record and one Pathlight trace. The DCI recorder feeds the existing Pi observation builder during execution and writes the resulting standard bundle through its pinned native evidence directory; observation failures never change benchmark execution.

**Tech Stack:** Python 3.10+, existing Agent Runtime v1, Pathlight, workflow-evidence, DCI Pi adapter, descriptor-relative evidence writer, and `unittest`.

## Global Constraints

- Framework modules must not import DCI; DCI may consume framework observation interfaces.
- Never persist prompt, answer, provider/model name, tool arguments/output, provider payload, corpus text, credential, or private path in the Pathlight bundle.
- Reuse `PiObservationBuilder`, workflow-evidence validation, Pathlight protocol, and the DCI recorder's pinned directory; define no second trace or bundle format.
- Observation is a non-authoritative side channel and must not alter Agent/Judge results, retry, cancellation, cost, authorization, or benchmark terminal state.
- Publish only a complete successful attempt; rollback retried attempts and never overwrite an existing `workflow-evidence.json`.
- The authorized live check is exactly one Bright Biology case, foreground execution, current `.env` DeepSeek Agent configuration, zero Judge calls, fresh lock/evidence roots, and no historical rerun.

---

### Task 1: Domain-Neutral Completed Runtime Projection

**Files:**
- Modify: `src/asterion/workflow_evidence/runtime.py`
- Modify: `src/asterion/workflow_evidence/__init__.py`
- Modify: `tests/test_workflow_evidence_runtime.py`

**Interfaces:**
- Consumes: `RunRequest`, one complete normalized event sequence, `RuntimeObservationBatch | None`, observed event timestamps, explicit runtime ID, and trace ID.
- Produces: `CompletedRuntimeEvidence(record, trace)` and the exact `project_completed_runtime_evidence` signature shown in Step 3.

- [x] **Step 1: Write failing completed-projection tests**

Add tests which reuse the existing valid Pi-native observation fixtures and assert:

```python
projected = project_completed_runtime_evidence(
    request=RunRequest(RUN_ID, "SENTINEL_PRIVATE_PROMPT"),
    event_observations=tuple((event, index * 10 + 1, index * 10 + 2) for index, event in enumerate(events)),
    native_observation=native,
    runtime_id="pi.reference",
    trace_id=TRACE_ID,
    invocation_started_ns=1,
    invocation_ended_ns=len(events) * 10 + 3,
)
self.assertEqual(projected.record["run_id"], RUN_ID)
self.assertGreater(len(_context_frames(projected.trace)), 0)
self.assertNotIn("SENTINEL_PRIVATE_PROMPT", json.dumps(projected.trace))
```

Add fail-closed cases for an incomplete stream, a mismatched native run digest, tool lineage mismatch, nonmonotonic timestamps, an invalid trace ID, and hostile mappings. The native mismatch must degrade to the existing fallback trace, not invent rich frames.

- [x] **Step 2: Run the focused tests and confirm the API is absent**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_runtime`

Expected: FAIL because `CompletedRuntimeEvidence` and `project_completed_runtime_evidence` are not exported.

- [x] **Step 3: Implement the immutable completed-runtime projector**

Add this public shape:

```python
@dataclass(frozen=True, slots=True)
class CompletedRuntimeEvidence:
    record: Mapping[str, object]
    trace: Mapping[str, object]

def project_completed_runtime_evidence(
    *,
    request: RunRequest,
    event_observations: Sequence[tuple[Mapping[str, object], int | None, int | None]],
    native_observation: RuntimeObservationBatch | None,
    runtime_id: str,
    trace_id: str,
    invocation_started_ns: int | None,
    invocation_ended_ns: int | None,
) -> CompletedRuntimeEvidence:
    request.to_mapping()
    observations = _validate_completed_event_observations(
        request, event_observations, invocation_started_ns, invocation_ended_ns
    )
    events = [mapping for mapping, _started, _ended in observations]
    evidence = collect_workflow_evidence(
        events,
        input_digest=hashlib.sha256(request.input_text.encode("utf-8")).hexdigest(),
    )
    checked_native = _validated_supplied_runtime_observation(
        native_observation, request, events, evidence=evidence
    )
    recorder = MemoryPathlightRecorder(trace_id)
    _RuntimePathlightProjection(recorder).project(
        request,
        observations,
        evidence=evidence,
        native_observation=checked_native,
        runtime_id=runtime_id,
        invocation_started_ns=invocation_started_ns,
        invocation_ended_ns=invocation_ended_ns,
    )
    trace = recorder.snapshot()
    if trace is None:
        raise WorkflowEvidenceError("completed runtime evidence is invalid")
    return CompletedRuntimeEvidence(
        _freeze_public_mapping(evidence), _freeze_public_mapping(trace)
    )
```

Validate `request.to_mapping()`, the complete event stream, identities, timestamp order, and supplied native observation. Cross-check the native run digest and tool summaries against the normalized stream using the same rules as `ObservedRuntimeClient`. Create a fresh `MemoryPathlightRecorder`, call the existing `_RuntimePathlightProjection`, require one valid snapshot, and return deep-frozen safe mappings. If native observation is absent or cross-checking fails, produce the existing explicit missing-evidence fallback; malformed event streams or public arguments fail closed.

- [x] **Step 4: Run runtime and Pathlight protocol tests**

Run:

```bash
uv run python -m unittest -v \
  tests.test_workflow_evidence_runtime \
  tests.test_pathlight_protocol \
  tests.test_pathlight_flow
```

Expected: PASS.

- [x] **Step 5: Commit the completed-runtime boundary**

```bash
git add src/asterion/workflow_evidence/runtime.py \
  src/asterion/workflow_evidence/__init__.py \
  tests/test_workflow_evidence_runtime.py
git commit -m "feat: project completed runtime evidence"
```

### Task 2: Reusable Workflow Bundle Construction

**Files:**
- Modify: `src/asterion/workflow_evidence/storage.py`
- Modify: `src/asterion/workflow_evidence/__init__.py`
- Modify: `tests/test_workflow_evidence_storage.py`

**Interfaces:**
- Consumes: safe workflow records and validated Pathlight trace mappings.
- Produces: `build_workflow_observation_bundle(records, *, pathlight_traces) -> Mapping[str, object]`; the existing file writer delegates to it.

- [x] **Step 1: Write failing pure-bundle tests**

```python
mapping = build_workflow_observation_bundle(
    (record,),
    pathlight_traces=(trace,),
)
self.assertEqual(mapping["schema"], "asterion.workflow-observation-bundle/v1")
self.assertEqual(read_workflow_observation_bundle_mapping(mapping).bundle_sha256, mapping["bundle_sha256"])
```

Assert byte-for-byte semantic equivalence with the existing writer, deterministic digest/order, duplicate run/trace rejection, hostile mapping rejection, and no sentinel leakage.

- [x] **Step 2: Run storage tests and confirm the builder is absent**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_storage`

Expected: FAIL because the pure builder and mapping reader are not exported.

- [x] **Step 3: Refactor construction out of the path writer**

Implement:

```python
def build_workflow_observation_bundle(
    records: Sequence[Mapping[str, object]],
    *,
    pathlight_traces: Sequence[Mapping[str, object]] = (),
) -> Mapping[str, object]:
    mapping = _build_bundle_mapping(records, pathlight_traces)
    read_workflow_observation_bundle_mapping(mapping)
    return json.loads(json.dumps(mapping, sort_keys=True, separators=(",", ":")))

def read_workflow_observation_bundle_mapping(
    document: Mapping[str, object],
) -> WorkflowObservationBundle:
    try:
        detached = json.loads(json.dumps(document, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError):
        raise WorkflowEvidenceError("workflow observation bundle is invalid") from None
    return _validate_and_freeze_bundle(detached)
```

Use the current writer's exact closed validation and serialization path, calculate `bundle_sha256` once, validate the resulting mapping through the same immutable reader, and return a detached ordinary mapping. Change `write_workflow_observation_bundle` to validate the target and serialize this mapping without changing its on-disk contract.

- [x] **Step 4: Run storage, query, Dashboard, and CLI tests**

Run:

```bash
uv run python -m unittest -v \
  tests.test_workflow_evidence_storage \
  tests.test_pathlight_query \
  tests.test_pathlight_dashboard \
  tests.test_pathlight_cli
```

Expected: PASS.

- [x] **Step 5: Commit reusable bundle construction**

```bash
git add src/asterion/workflow_evidence/storage.py \
  src/asterion/workflow_evidence/__init__.py \
  tests/test_workflow_evidence_storage.py
git commit -m "refactor: expose validated workflow bundles"
```

### Task 3: DCI Native Recorder Integration

**Files:**
- Modify: `src/asterion/capabilities/dci/implementation/evaluation/artifacts.py`
- Modify: `src/asterion/capabilities/dci/implementation/runtime/run.py`
- Create: `tests/test_dci_pathlight_capture.py`
- Modify: `tests/test_dci_pathlight_coverage.py`

**Interfaces:**
- Consumes: raw Pi events, normalized adapter emissions, `PiObservationBuilder`, completed-runtime projection, and pure workflow bundle construction.
- Produces: a descriptor-relative, immutable `workflow-evidence.json` inside each newly completed native generation.

- [x] **Step 1: Write failing DCI recorder integration tests**

Build a fake Pi RPC client that emits a closed sequence containing:

```python
{"type": "provider_request_context", "requestIndex": 1, "provider": "private-provider", "model": "private-model", "messages": [{"role": "user", "content": "SENTINEL"}]}
{"type": "tool_execution_start", "toolCallId": "call-1", "toolName": "read", "args": {"private": "SENTINEL"}}
{"type": "tool_execution_end", "toolCallId": "call-1", "toolName": "read", "result": "SENTINEL", "isError": False}
{"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "SENTINEL"}], "usage": {"input": 10, "output": 3}}}
```

Run `run_pi_research`, read `workflow-evidence.json` with the public reader, and assert one trace, one ContextFrame, one model call, one completed tool call, correct lineage, and absence of every sentinel/provider/model/path string. Add retry rollback, missing observation, existing-target, failed-run, cancellation, and writer-exception cases. None may change the native terminal result or overwrite evidence.

- [x] **Step 2: Run the new tests and confirm no bundle exists**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_capture`

Expected: FAIL because native DCI completion does not write `workflow-evidence.json`.

- [x] **Step 3: Capture Pi observation and normalized timing as a side channel**

Initialize a `PiObservationBuilder` and observation checkpoint per recorder attempt. In `record_event`, consume the raw event, reset the checkpoint at `agent_start`, and rollback when an `agent_end` carries `willRetry`. In `_emit_normalized`, retain the mapping and strictly increasing monotonic start/end values without changing protocol emission. Any observation exception disables only rich observation for that attempt.

- [x] **Step 4: Project and write the completed bundle through pinned authority**

After successful `recorder.finalize(status="completed", final_text=final_text, stderr_text=stderr_text, release_lock=False)`, build a generic `RunRequest` from the exact DCI run identity/question/capabilities, complete and validate the native observation, project completed runtime evidence, and build the standard bundle. Add a narrow recorder method:

```python
def write_workflow_evidence(self, bundle: Mapping[str, object]) -> None:
    self._ensure_open()
    read_workflow_observation_bundle_mapping(bundle)
    if self.state.get("status") != "completed" or not self._finalized:
        raise DciArtifactError("DCI workflow evidence state is invalid")
    _write_exclusive_json_at(self._root_fd, "workflow-evidence.json", dict(bundle))
```

Use the actual canonical mapping method implemented in Task 2 rather than inventing fields. Catch observation/persistence errors outside execution semantics, clean any staging file, and return the already completed `DciRunResult` unchanged.

- [x] **Step 5: Run DCI capture, artifact, runtime, and benchmark tests**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_pathlight_capture \
  tests.test_dci_pathlight_coverage \
  tests.test_dci_trajectory_resolution \
  tests.test_asterion_dci_benchmark \
  tests.test_asterion_pi_runtime \
  tests.test_workflow_evidence_runtime \
  tests.test_workflow_evidence_storage
```

Expected: PASS.

- [x] **Step 6: Commit DCI prospective capture**

```bash
git add src/asterion/capabilities/dci/implementation/evaluation/artifacts.py \
  src/asterion/capabilities/dci/implementation/runtime/run.py \
  tests/test_dci_pathlight_capture.py \
  tests/test_dci_pathlight_coverage.py
git commit -m "feat: persist DCI Pathlight traces"
```

### Task 4: Authorized One-Case Closure and Documentation

**Files:**
- Modify: `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md`
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/superpowers/plans/2026-08-03-dci-pathlight-prospective-capture.md`

**Interfaces:**
- Consumes: one fresh `dci.bright.biology@1.0.0` execution and its native `workflow-evidence.json`.
- Produces: exact trace/frame/model/tool/gap counts, snapshot digest, cost and terminal-state evidence, plus reproducible foreground commands.

- [x] **Step 1: Run provider-free verification before spending**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_pathlight_capture \
  tests.test_pathlight_dashboard \
  tests.test_pathlight_cli
make lint
make docs-check
make promotion-check
```

Expected: PASS before any provider call.

- [x] **Step 2: Prepare fresh exact inputs in the foreground shell**

Clear relevant inherited Agent/Judge/proxy variables, source the repository `.env`, confirm DeepSeek readiness without printing secrets, create a fresh canonical source lock and a fresh evidence root, and record their non-secret digests. Do not reuse v7/v8 roots or authorization receipts.

- [x] **Step 3: Execute exactly one Bright Biology case in the foreground**

Run `uv run asterion-dci benchmark run` with:

```text
--instance dci.bright.biology@1.0.0
--case-limit 1
--capability-source-lock <fresh-lock>
--evidence-root <fresh-evidence>
--execute
```

Expected: one terminal completed task, one Agent operation, zero Judge operations, no background process, and one immutable native `workflow-evidence.json`. If preflight or execution fails, diagnose from the structured failure boundary; do not silently rerun or expand scope.

Actual: the authorized case completed 1/1 in the foreground with zero Judge work. Pre-provider failures were retained and diagnosed before the successful attempt; they consumed zero model tokens. The successful run wrote one immutable native bundle.

- [x] **Step 4: Validate the real trace and Dashboard snapshot**

Read the new bundle through `read_workflow_observation_bundle`, query it through `asterion pathlight trace list/flow`, and build/start a Dashboard snapshot using the exact `--evidence-file`. Confirm at least one trace, one ContextFrame, and one model call; record the actual tool count, missing-evidence labels, terminal status, bundle digest, trace digest, snapshot digest, time, and actual cost. Stop the foreground Dashboard with `Ctrl-C`.

Actual: the native bundle remains immutable and truthfully contains fallback evidence because two observer defects existed at execution time. After fixing them, an independent offline companion was projected from that exact run's retained raw and protocol events. It contains 6 ContextFrames, 6 completed model calls, and 18 completed tool calls; CLI and the foreground Dashboard agree. Its synthetic monotonic timestamps prove ordering only, not execution timing. Exact provider request/context segments remain explicit gaps.

- [x] **Step 5: Run repository-wide verification**

Run:

```bash
make check
make promotion-check
```

Expected: PASS with no provider execution in either verification command.

Actual: `make check` passed 1192 Python tests plus TypeScript, Rust, lint, docs, and build gates. `make promotion-check` passed 22 commands with `provider_operations=0` and `full_dataset=no`.

- [x] **Step 6: Update Chinese status documents truthfully**

Record the new one-case evidence separately from historical 848-case results. State whether final ContextFrame persistence is verified, which gaps remain, and why this does not change or reproduce any benchmark score. Mark every plan checkbox only after its exact evidence exists.

- [x] **Step 7: Commit verified closure**

```bash
git add docs/status/PATHLIGHT-DCI-DIAGNOSIS.md \
  docs/status/DCI-BENCHMARK-INSTANCES.md \
  docs/superpowers/plans/2026-08-03-dci-pathlight-prospective-capture.md
git commit -m "docs: verify prospective DCI Pathlight capture"
```
