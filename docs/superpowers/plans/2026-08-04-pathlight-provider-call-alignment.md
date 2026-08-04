# Pathlight Provider Call Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Pathlight represent every verified provider call, including compaction and retry calls without an assistant response, while preserving safe public evidence and immutable historical runs.

**Architecture:** The domain-neutral Pi observation builder receives only monotonic request markers and response event sequences, then atomically aligns each response to the latest unmatched preceding request. DCI owns extraction of its closed marker and descriptor-safe recovery of historical private evidence; public workflow projection derives missing labels per model call so one request-only call does not contaminate completed calls.

**Tech Stack:** Python 3.10+ standard library, immutable Pathlight runtime observations v2, DCI private JSONL capture, descriptor-relative POSIX file operations, `unittest`, existing CLI/Dashboard/Opik projections.

## Global Constraints

- Preserve the dependency direction `CLI/host → selected provider → assembly → catalog/composer → exact implementations → runner → runtime/host services`.
- Framework modules remain domain-neutral; `src/asterion/runtimes/pi_observation.py` must not import DCI code or DCI schema constants.
- Do not modify external Pi, disable compaction, discard retries, synthesize responses, or change Agent/Judge/benchmark/retry/scoring semantics.
- `RuntimeObservationBatch` remains `asterion.pathlight/runtime-observation/v2`; do not change its serialized shape.
- Raw provider payloads, prompts, answers, credentials, provider payloads, corpus text, tool bodies, private paths, FDs, and provider configuration must not enter public bundles, CLI, Dashboard, Opik, logs, or errors.
- Provider request markers contain exactly `request_index` and recorder-owned `native_event_sequence`; marker candidates are non-authoritative until raw/safe validation succeeds.
- Reconciliation is atomic: any index, order, sequence, rollback, validation, or projection failure retains the original inferred batch with explicit gaps.
- Historical native evidence is immutable. Recovery writes a separately named offline companion and never replaces `workflow-evidence.json`.
- Provider-free tests, `make check`, and `make promotion-check` must perform zero provider operations. A fresh native one-case run requires separate finite authorization after all provider-free gates pass.

---

## File Structure

- Modify `src/asterion/runtimes/pi_observation.py` — generic request-marker capture, response sequencing, rollback-safe latest-preceding alignment, and request-only model calls.
- Modify `src/asterion/capabilities/dci/implementation/evaluation/artifacts.py` — extract the closed DCI marker from native events and supply recorder-owned sequence numbers.
- Modify `src/asterion/capabilities/dci/implementation/evaluation/provider_requests.py` — descriptor-relative sealed readback and raw/safe cross-validation without exposing payloads.
- Create `src/asterion/capabilities/dci/implementation/pathlight/provider_call_recovery.py` — DCI-private, provider-free reconstruction of an offline workflow companion from one explicitly selected generation.
- Modify `src/asterion/capabilities/dci/implementation/pathlight/__init__.py` — export only the operator-private Python recovery API; do not add a public CLI command.
- Modify `src/asterion/workflow_evidence/runtime.py` — compute model-call missing labels locally rather than copying the batch union to every call.
- Modify `tests/test_pi_pathlight_observation.py` — generic 4-request/3-response alignment and atomic fallback matrices.
- Modify `tests/test_dci_pathlight_capture.py` — DCI marker extraction, exact compaction mainline, retry/rollback, and sentinel redaction.
- Modify `tests/test_dci_provider_request_capture.py` — sealed-reader trust-boundary matrix.
- Create `tests/test_dci_provider_call_recovery.py` — immutable historical companion publication and rollback tests.
- Modify `tests/test_workflow_evidence_runtime.py` — per-call gap projection tests.
- Modify `tests/test_dci_pathlight_cli.py`, `tests/test_pathlight_cli.py`, `tests/test_pathlight_dashboard.py`, and `tests/test_pathlight_opik.py` only where the request-only fixture crosses that surface; do not create duplicate suites.
- Modify `docs/status/DCI-BENCHMARK-INSTANCES.md` — Chinese explanation of the verified 4/3/7 native call topology and offline/native distinction.
- Modify `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md` — explain how request-only calls affect diagnosis without claiming a benchmark improvement.
- Modify `docs/cli.md` — document that existing public commands show safe request-only nodes but cannot read private captures.

### Task 1: Add generic monotonic request/response alignment

**Files:**
- Modify: `src/asterion/runtimes/pi_observation.py:20-430`
- Test: `tests/test_pi_pathlight_observation.py:1-410`

**Interfaces:**
- Produces: `PiObservationCheckpoint(marker_count: int, response_sequence_count: int, ...)` with the existing counts retained.
- Produces: `PiObservationBuilder.observe_provider_request_marker(request_index: int, native_event_sequence: int) -> None`.
- Changes: `PiObservationBuilder.consume(event: Mapping[str, object], timestamp_ns: int, *, native_event_sequence: int | None = None) -> None`.
- Retains: `PiObservationBuilder.reconcile_provider_requests(values: tuple[ProviderRequestObservation, ...]) -> None`; success still yields equal-length `frames`, `model_calls`, and `provider_requests`.

- [ ] **Step 1: Write the failing compaction-alignment test**

Add helpers that emit four marker candidates and three assistant responses, with response 3 after marker 4. Assert the verified result is request ordered and only request 3 is response-missing:

```python
def test_reconciles_request_only_compaction_call_by_native_sequence(self) -> None:
    builder = PiObservationBuilder(lambda: 0)
    for index, sequence, response_sequence, text in (
        (1, 2, 10, "first"),
        (2, 20, 30, "second"),
        (3, 40, None, None),
        (4, 60, 70, "final"),
    ):
        builder.observe_provider_request_marker(index, sequence)
        if response_sequence is None:
            continue
        builder.consume(
            {
                "type": "message_start",
                "message": {
                    "role": "assistant",
                    "provider": "provider",
                    "model": "model",
                    "content": [],
                },
            },
            response_sequence - 1,
            native_event_sequence=response_sequence - 1,
        )
        builder.consume(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "provider": "provider",
                    "model": "model",
                    "content": text,
                    "usage": {"input": 3, "output": 1},
                    "stopReason": "stop",
                },
            },
            response_sequence,
            native_event_sequence=response_sequence,
        )
    requests = tuple(_verified_request(index) for index in range(1, 5))
    builder.reconcile_provider_requests(requests)
    batch = builder.complete("run")

    self.assertEqual(tuple(call.request_index for call in batch.model_calls), (1, 2, 3, 4))
    self.assertEqual(tuple(call.status for call in batch.model_calls),
                     ("completed", "completed", "missing", "completed"))
    self.assertIsNone(batch.model_calls[2].response_sha256)
    self.assertEqual(batch.model_calls[3].response_sha256, _digest("final"))
    self.assertNotIn("model-request", batch.missing_evidence)
    self.assertIn("model-response", batch.missing_evidence)
```

- [ ] **Step 2: Write the failing atomic-fallback and rollback matrix**

Use `subTest` for duplicate/non-contiguous indexes, non-increasing marker sequences, a response before every marker, partial verified requests, and rollback across a marker/response. For every invalid case, compare the entire completed batch to a snapshot taken before reconciliation:

```python
for name, markers in (
    ("duplicate-index", ((1, 2), (1, 20))),
    ("index-gap", ((1, 2), (3, 20))),
    ("sequence-reversal", ((1, 20), (2, 2))),
):
    with self.subTest(name=name):
        builder = _builder_with_one_response(markers)
        inferred = builder.complete("run")
        builder.reconcile_provider_requests(tuple(_verified_request(i) for i in range(1, 3)))
        self.assertEqual(builder.complete("run"), inferred)
```

Include a latest-wins retry case with markers 1 and 2 before one response; request 1 must remain request-only and request 2 must receive the response.

- [ ] **Step 3: Run the focused tests to verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_pi_pathlight_observation.PiObservationBuilderTests.test_reconciles_request_only_compaction_call_by_native_sequence \
  tests.test_pi_pathlight_observation.PiObservationBuilderTests.test_reconciliation_marker_failures_are_atomic
```

Expected: FAIL because the marker method and native sequence tracking do not exist and reconciliation still requires equal inferred counts.

- [ ] **Step 4: Implement marker drafts, response sequences, alignment, and atomic commit**

Add closed internal types and extend checkpoints:

```python
@dataclass(frozen=True, slots=True)
class _ProviderRequestMarker:
    request_index: int
    native_event_sequence: int

@dataclass(frozen=True, slots=True)
class PiObservationCheckpoint:
    frame_count: int
    model_call_count: int
    tool_count: int
    message_count: int
    marker_count: int
    response_sequence_count: int
```

Store response drafts separately from provider request order. `observe_provider_request_marker()` accepts only exact positive `int` values, consecutive indexes, and strictly increasing sequences; invalid input sets a reconciliation-invalid flag without throwing. `consume()` records a sequence only for a successfully consumed assistant `message_end` and rejects `bool`, zero, negative, duplicate, or decreasing values as untrusted observation evidence.

Implement latest-preceding matching as a pure helper:

```python
def _align_responses(
    markers: tuple[_ProviderRequestMarker, ...],
    responses: tuple[tuple[int, _ModelCallDraft], ...],
) -> dict[int, _ModelCallDraft] | None:
    matched: dict[int, _ModelCallDraft] = {}
    lower_bound = -1
    for response_sequence, response in responses:
        candidates = [
            marker for marker in markers
            if lower_bound < marker.native_event_sequence < response_sequence
            and marker.request_index not in matched
        ]
        if not candidates:
            return None
        selected = candidates[-1]
        matched[selected.request_index] = response
        lower_bound = selected.native_event_sequence
    return matched
```

Build temporary frames/calls in verified request order. A matched call copies model/response/usage/status from the assistant draft; an unmatched call uses `model_sha256=None`, response and usage fields `None`, `status="missing"`, and `boundary_observed=False`. Set `request_sha256` from the verified request for every call. Validate with `_completed_batch(...)` before assigning `_provider_requests` and rebuilt call drafts; on any exception leave every original field unchanged.

Rollback truncates markers and response-sequence drafts using the new checkpoint counts and clears prior reconciliation if the rollback crosses any reconciled marker or response.

- [ ] **Step 5: Run generic observation tests to verify GREEN**

Run:

```bash
uv run python -m unittest -v tests.test_pi_pathlight_observation
```

Expected: PASS; the 4/3 fixture produces four calls, and every invalid matrix case returns the exact inferred fallback.

- [ ] **Step 6: Commit the generic runtime change**

```bash
git add src/asterion/runtimes/pi_observation.py tests/test_pi_pathlight_observation.py
git commit -m "fix: align Pathlight provider calls monotonically"
```

### Task 2: Translate DCI entry events into generic markers

**Files:**
- Modify: `src/asterion/capabilities/dci/implementation/evaluation/artifacts.py:2330-2620`
- Test: `tests/test_dci_pathlight_capture.py:730-1185`

**Interfaces:**
- Consumes: `PiObservationBuilder.observe_provider_request_marker(request_index: int, native_event_sequence: int) -> None` from Task 1.
- Changes: `DciRunRecorder._observe_pathlight_event(event: dict[str, object], native_event_sequence: int) -> None`.
- Produces: private helper `_dci_provider_request_marker(event: Mapping[str, object]) -> int | None`, returning only a closed continuous candidate index.

- [ ] **Step 1: Write the failing DCI 4/3/7 native fixture**

Extend the native capture test client so `on_event` receives four closed `entry_appended` provider observation events, three assistant `message_end` events, the real compaction telemetry ordering between request 3 and request 4, and seven matched tool start/end pairs. Assert:

```python
self.assertEqual(_started_kinds(trace).count("context-frame"), 4)
self.assertEqual(_started_kinds(trace).count("model-call"), 4)
self.assertEqual(_started_kinds(trace).count("tool-call"), 7)
model_starts = _started_events(trace, "model-call")
self.assertEqual(tuple(item["attributes"]["request_index"] for item in model_starts), (1, 2, 3, 4))
self.assertNotIn("response_sha256", model_starts[2]["attributes"])
self.assertIn("response_sha256", model_starts[3]["attributes"])
```

Assert serialized evidence excludes the sentinel prompt, answer, raw request JSON, provider/model names, tool arguments/results, generation root, and observation FD.

- [ ] **Step 2: Write malformed marker and retry rollback tests**

Feed an `entry_appended` event only when all of these exact conditions hold: outer type is `entry_appended`; `entry` is a mapping; entry type is `custom`; `customType` equals `dci-provider-request-observation`; `data` is a mapping; schema equals `dci.provider-request-observation/v1`; capture status is `captured`; request index is a positive exact `int`. Unknown custom types are ignored. A recognized but malformed marker must degrade reconciliation without failing the DCI run.

Add a retry attempt that emits markers and a response, then `agent_end` with `willRetry=True`; after rollback only the successful attempt's markers and responses may reconcile.

- [ ] **Step 3: Run the focused DCI tests to verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_pathlight_capture.DciPathlightCaptureTests.test_native_run_reconciles_request_only_compaction_call \
  tests.test_dci_pathlight_capture.DciPathlightCaptureTests.test_provider_marker_failure_is_observation_only \
  tests.test_dci_pathlight_capture.DciPathlightCaptureTests.test_retry_rolls_back_provider_markers
```

Expected: FAIL because recorder event order is not passed to the builder and entry events are not translated into markers.

- [ ] **Step 4: Add recorder-owned native event sequences and closed marker extraction**

Initialize `self._pathlight_native_event_sequence = 0`. In `record_event`, increment it once before observation and pass the value to `_observe_pathlight_event`; do not derive identity from timestamps or entry IDs.

Implement the DCI-only extractor without copying data:

```python
def _dci_provider_request_marker(event: Mapping[str, object]) -> int | None:
    if event.get("type") != "entry_appended":
        return None
    entry = event.get("entry")
    if not isinstance(entry, Mapping) or entry.get("type") != "custom":
        return None
    if entry.get("customType") != "dci-provider-request-observation":
        return None
    data = entry.get("data")
    if not isinstance(data, Mapping):
        return -1
    index = data.get("request_index")
    if (
        data.get("schema") != "dci.provider-request-observation/v1"
        or data.get("capture_status") != "captured"
        or type(index) is not int
        or index < 1
    ):
        return -1
    return index
```

`_observe_pathlight_event` calls `builder.consume(..., native_event_sequence=sequence)` first for ordinary response/tool handling, then calls `observe_provider_request_marker` for positive marker results. A `-1` result calls the marker API with invalid values so reconciliation fails closed; it must not throw into execution.

- [ ] **Step 5: Run DCI capture and runtime tests to verify GREEN**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_pathlight_capture \
  tests.test_asterion_pi_runtime
```

Expected: PASS; execution behavior is unchanged, while the compaction fixture publishes 4/3/7 safe topology.

- [ ] **Step 6: Commit the DCI translation boundary**

```bash
git add src/asterion/capabilities/dci/implementation/evaluation/artifacts.py tests/test_dci_pathlight_capture.py
git commit -m "feat: mark exact DCI provider call order"
```

### Task 3: Project missing evidence per model call

**Files:**
- Modify: `src/asterion/workflow_evidence/runtime.py:590-685`
- Test: `tests/test_workflow_evidence_runtime.py:780-880`
- Test: confirmed existing CLI/flow/Dashboard/Opik test files found with `rg --files tests | rg 'pathlight.*(cli|dashboard|opik)'`

**Interfaces:**
- Produces: private `_model_call_missing_labels(call: ModelCallObservation) -> tuple[str, ...]`.
- Retains: `project_completed_runtime_evidence(...) -> CompletedRuntimeEvidence`; no public signature or bundle schema changes.

- [ ] **Step 1: Write the failing per-call projection test**

Create a valid batch with four verified provider requests: calls 1, 2, and 4 are completed; call 3 is request-only. Assert completed nodes do not inherit call 3 gaps:

```python
labels = {
    event["attributes"]["request_index"]:
        tuple(event["attributes"].get("missing_evidence_labels", ()))
    for event in _model_starts(projected.trace)
}
self.assertEqual(labels[1], ("model-request-boundary",))
self.assertEqual(labels[2], ("model-request-boundary",))
self.assertEqual(
    labels[3],
    ("model-identity", "model-request-boundary", "model-response", "token-usage"),
)
self.assertEqual(labels[4], ("model-request-boundary",))
```

Assert the request-only node still contains request digest, shape/counts, and private reference digest, but no response/token/model fields.

- [ ] **Step 2: Run the projection test to verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_workflow_evidence_runtime.WorkflowEvidenceRuntimeTests.test_request_only_gap_does_not_contaminate_completed_calls
```

Expected: FAIL because `_project_native_model_call` currently copies all model-related batch labels onto every call.

- [ ] **Step 3: Implement exact local gap derivation**

Add:

```python
def _model_call_missing_labels(call: ModelCallObservation) -> tuple[str, ...]:
    labels: list[str] = []
    if call.model_sha256 is None:
        labels.append("model-identity")
    if call.request_sha256 is None:
        labels.append("model-request")
    if not call.boundary_observed:
        labels.append("model-request-boundary")
    if call.response_sha256 is None:
        labels.append("model-response")
    if call.input_tokens is None or call.output_tokens is None:
        labels.append("token-usage")
    return tuple(sorted(labels))
```

Use only this tuple for `missing_evidence_labels` and set the node's boolean `missing_evidence` from local labels plus `call.status == "missing"`. Keep the batch union unchanged for batch-level validation and summary.

- [ ] **Step 4: Extend public surface redaction tests**

Reuse the same safe bundle through `trace show`, `trace flow`, Dashboard snapshot serialization, and Pathlight–Opik export. Assert all four model calls remain visible, only request 3 has response/usage/identity gaps, and a sentinel set containing prompt, answer, raw payload, tool body, provider/model names, and private path is absent from every JSON representation.

- [ ] **Step 5: Run runtime and public-surface tests to verify GREEN**

Run the exact modules returned by the filename discovery, plus:

```bash
uv run python -m unittest -v tests.test_workflow_evidence_runtime
```

Expected: PASS; CLI, flow, Dashboard, and Opik agree on four calls and per-call gaps without content exposure.

- [ ] **Step 6: Commit the public projection correction**

```bash
git add src/asterion/workflow_evidence/runtime.py tests/test_workflow_evidence_runtime.py tests/test_*pathlight*.py
git commit -m "fix: localize Pathlight model call gaps"
```

Before committing, replace the broad test glob with the exact modified filenames shown by `git status --short`; never stage unrelated files.

### Task 4: Read sealed captures and publish immutable offline companions

**Files:**
- Modify: `src/asterion/capabilities/dci/implementation/evaluation/provider_requests.py:70-235`
- Create: `src/asterion/capabilities/dci/implementation/pathlight/provider_call_recovery.py`
- Modify: `src/asterion/capabilities/dci/implementation/pathlight/__init__.py`
- Test: `tests/test_dci_provider_request_capture.py:150-710`
- Create: `tests/test_dci_provider_call_recovery.py`

**Interfaces:**
- Produces: `read_sealed_provider_requests_at(directory_fd: int, safe_entries: tuple[dict[str, object], ...]) -> tuple[ProviderRequestObservation, ...]`.
- Produces: `recover_provider_call_companion(generation_root: Path, companion_path: Path) -> Mapping[str, object]` in the DCI product module.
- The recovery API requires explicit absolute paths, reads only fixed generation filenames, creates one new `0600` file exclusively, returns only the validated safe bundle mapping, and uses the fixed error `DCI provider call recovery is invalid`.

- [ ] **Step 1: Write the failing sealed-reader trust-boundary matrix**

Create a sealed 0400 regular capture with matching safe entries and assert it returns immutable observations. Add `subTest` cases for 0600 mode, symlink, FIFO, directory, foreign-owner metadata (mocked `fstat`), replacement inode, oversize file, content mutation during held-FD read, missing newline, malformed record, and raw/safe drift. Every failure must be exactly `provider request capture is invalid` with no exception cause or sentinel content.

```python
with self.assertRaisesRegex(
    ProviderRequestCaptureError, "^provider request capture is invalid$"
) as raised:
    read_sealed_provider_requests_at(directory_fd, safe_entries)
self.assertIsNone(raised.exception.__cause__)
```

- [ ] **Step 2: Run sealed-reader tests to verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_provider_request_capture.ProviderRequestCaptureTests.test_reads_sealed_capture_by_held_descriptor \
  tests.test_dci_provider_request_capture.ProviderRequestCaptureTests.test_sealed_reader_rejects_trust_boundary_drift
```

Expected: FAIL because only the writable live-capture reader exists.

- [ ] **Step 3: Implement descriptor-relative sealed readback**

Open the fixed name using `os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK` relative to the caller-held directory FD. Before and after the bounded read, require regular file, `st_uid == os.geteuid()`, mode `0400`, stable `(dev, ino, size, mtime_ns)`, size at most `_MAX_CAPTURE_BYTES`, and EOF within the bound. Reuse `_parse_records` and `_validate_pair`; do not return raw bytes or paths.

```python
def read_sealed_provider_requests_at(
    directory_fd: int,
    safe_entries: tuple[dict[str, object], ...],
) -> tuple[ProviderRequestObservation, ...]:
    descriptor = -1
    try:
        descriptor = os.open(
            _CAPTURE_NAME,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        raw, snapshot = _read_sealed_capture(descriptor)
        return _validate_raw_safe_batch(raw, snapshot, safe_entries)
    except ProviderRequestCaptureError:
        raise
    except Exception:
        _invalid()
    finally:
        if descriptor >= 0:
            _close_quietly(descriptor)
```

Refactor live and sealed readers to share only pure parsing/pair validation; keep their different mode/lifecycle checks separate.

- [ ] **Step 4: Write the failing offline companion publication tests**

Build a private fixture generation containing fixed `events.jsonl`, `provider-requests.jsonl`, and the original `workflow-evidence.json`. Include 4 markers, 3 responses, 7 tools, and compaction telemetry. Assert recovery:

- creates only the explicitly named absent companion using exclusive 0600 publication;
- leaves all source bytes, modes, mtimes, and digests unchanged;
- outputs four frames/calls/requests and seven tools;
- marks the result as offline through the fixed companion filename and operator documentation, not by adding an unvalidated free-form key;
- rolls back its owned staging inode on any validation/publication failure;
- rejects relative roots, symlink roots, missing/malformed fixed inputs, existing output, output inside a different directory, and concurrent target replacement with one fixed content-free error;
- performs zero provider, Judge, network, subprocess, runtime selection, or authorization operations.

- [ ] **Step 5: Implement DCI-private provider-free recovery**

`recover_provider_call_companion()` must:

1. require absolute `generation_root` and `companion_path`, with the companion as a direct child and exact name `workflow-evidence.provider-calls.offline.json`;
2. open the generation directory with no-follow directory semantics and hold the FD;
3. bounded-read fixed `events.jsonl`, extracting only closed safe provider entries plus feeding every event to `PiObservationBuilder` with its 1-based line sequence;
4. descriptor-open the fixed `protocol/attempt-0001.request.json` and `protocol/attempt-0001.events.jsonl`, validate both through the closed runtime protocol, and use the request only in memory to preserve the original run/input digests;
5. call `read_sealed_provider_requests_at`, reconcile, then project the validated normalized events through `project_completed_runtime_evidence` with deterministic synthetic monotonic timestamps, fixed runtime ID `pi.dci-native`, and a new digest-bound offline trace ID;
6. validate the complete bundle before exclusive atomic publication with mode 0600;
7. return the validated safe mapping only.

Do not expose a CLI. Do not copy raw event mappings, safe entry bodies, or paths into errors or the returned mapping.

- [ ] **Step 6: Run recovery tests to verify GREEN**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_provider_request_capture \
  tests.test_dci_provider_call_recovery
```

Expected: PASS; the source generation is byte-for-byte unchanged and the companion is a validated 4/3/7 safe projection.

- [ ] **Step 7: Commit sealed readback and offline recovery**

```bash
git add \
  src/asterion/capabilities/dci/implementation/evaluation/provider_requests.py \
  src/asterion/capabilities/dci/implementation/pathlight/provider_call_recovery.py \
  src/asterion/capabilities/dci/implementation/pathlight/__init__.py \
  tests/test_dci_provider_request_capture.py \
  tests/test_dci_provider_call_recovery.py
git commit -m "feat: recover sealed provider call evidence"
```

### Task 5: Reproject the authorized historical run without providers

**Files:**
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Modify: `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md`
- Modify: `docs/cli.md`
- Test: generated offline companion outside the repository; do not commit evidence or private paths.

**Interfaces:**
- Consumes: `recover_provider_call_companion(generation_root: Path, companion_path: Path) -> Mapping[str, object]` from Task 4.
- Produces: one operator-private `workflow-evidence.provider-calls.offline.json` beside the immutable historical generation and a content-safe verification summary.

- [ ] **Step 1: Record immutable source facts before recovery**

Using descriptor-safe shell metadata commands on the already authorized successful generation selected by the operator, record only locally (not in docs) the source file digest/mode/size/mtime tuple. Confirm the sealed capture is 0400 with 4 non-empty records and the original bundle is 0600. Do not print or parse raw payload content in the terminal.

- [ ] **Step 2: Invoke the provider-free Python recovery API once**

Use `uv run python -c` with the two explicit absolute operator paths passed through task-specific environment variables. Clear model/Judge credentials for this command and patching is not used; no provider is loaded. The script prints only the companion bundle digest and safe counts.

Expected safe output fields:

```text
provider_requests=4
model_calls=4
observed_responses=3
tools=7
model_request_missing=false
request_3_missing=model-identity,model-request-boundary,model-response,token-usage
```

- [ ] **Step 3: Prove the original generation remained immutable**

Recompute the source metadata tuple and require exact equality. Validate the companion through existing Pathlight readers, `trace show`, `trace flow`, Dashboard snapshot construction, and Pathlight–Opik offline export. Confirm all commands are provider-free and all serialized surfaces exclude the sentinel set and private generation path.

- [ ] **Step 4: Update Chinese status and operator documentation**

In `DCI-BENCHMARK-INSTANCES.md`, state the exact historical facts: successful Bright Biology 1/1, 0 Judge, 31.43 seconds, Agent cost $0.0480122, 47,901 tokens, 7 successful tools, 4 verified provider requests, 3 observed assistant responses, and single-case nDCG@10 0.339160. Explicitly say the score is not a benchmark score and the offline companion does not replace native evidence.

In `PATHLIGHT-DCI-DIAGNOSIS.md`, explain that request 3 was a compaction request-only call and that its missing response/usage/model identity is honest missing evidence, not an Agent failure. Do not claim the Bright paper-score gap is explained or improved by this infrastructure correction.

In `docs/cli.md`, state that public Pathlight commands may display request-only nodes from validated bundles but have no private-capture read or raw-payload endpoint.

- [ ] **Step 5: Run documentation and provider-free surface gates**

Run:

```bash
make docs-check
uv run python -m unittest -v \
  tests.test_dci_pathlight_cli \
  tests.test_pathlight_dashboard \
  tests.test_pathlight_opik
```

If the confirmed Opik module name differs, use the exact existing module returned by Task 3 discovery. Expected: PASS; provider operations remain 0.

- [ ] **Step 6: Commit documentation only**

```bash
git add \
  docs/status/DCI-BENCHMARK-INSTANCES.md \
  docs/status/PATHLIGHT-DCI-DIAGNOSIS.md \
  docs/cli.md
git commit -m "docs: verify provider call recovery"
```

Do not stage the generated companion, private evidence, `docs/status/JOURNAL.md`, or `docs/status/RESUME-NEXT-SESSION.md` in this feature commit.

### Task 6: Close provider-free gates and obtain independent review

**Files:**
- Modify only files required by concrete review findings.
- Preserve: `docs/status/JOURNAL.md` and `docs/status/RESUME-NEXT-SESSION.md` as append-only/checkpoint project state.

**Interfaces:**
- Consumes all Tasks 1–5.
- Produces a provider-free verified implementation ready for a separately authorized native one-case run.

- [ ] **Step 1: Run focused regression suites**

```bash
uv run python -m unittest -v \
  tests.test_pi_pathlight_observation \
  tests.test_dci_provider_request_capture \
  tests.test_dci_provider_call_recovery \
  tests.test_dci_pathlight_capture \
  tests.test_workflow_evidence_runtime
```

Expected: PASS.

- [ ] **Step 2: Run full provider-free gates**

```bash
make check
make promotion-check
```

Expected: PASS; promotion output explicitly reports `provider_operations=0` and no full dataset execution.

- [ ] **Step 3: Perform two independent reviews**

First review against the approved design for exact requirement coverage and architecture direction. Second review for correctness/security: descriptor ownership, symlink/FIFO/race handling, bounded reads, rollback, exact types excluding `bool`, fixed errors, atomic reconciliation, redaction, and immutable evidence. Resolve every concrete finding with a focused failing test, minimal fix, passing focused/full gate, and focused commit.

- [ ] **Step 4: Verify the worktree is self-contained**

```bash
git status --short
git log --oneline --decorate -12
git diff --check
```

Expected: only the intentionally dirty durable project-state files remain; all implementation/docs commits are on `feature/pathlight-dci-recovery`, no untracked source/test artifacts exist, and `git diff --check` is clean.

- [ ] **Step 5: Update durable project state**

Append one timestamped JOURNAL entry containing the final implementation commit SHA and provider-free gate results. Update RESUME with: completed commits, exact test counts, historical companion digest/counts, remaining honest gaps, proxy inheritance requirement, and the explicit statement that no new native run is authorized yet.

### Task 7: Run one newly authorized native Bright case and inspect Dashboard

**Files:**
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md` only after successful evidence validation.
- Do not modify code unless the native run reveals a reproducible defect; if so, return to a provider-free RED/GREEN task before rerunning.

**Interfaces:**
- Consumes the provider-free verified implementation and a new explicit authorization naming dataset, case count, Agent/Judge limits, cost cap, evidence root, source lock, environment source, foreground mode, and proxy policy.
- Produces one new native bundle that directly contains four-or-more verified provider calls as observed, plus a stopped foreground Dashboard inspection.

- [ ] **Step 1: Stop and request finite execution authority**

Do not infer authorization from approval of this plan. Present the exact command scope and estimated upper bound. Require explicit approval for one Bright Biology case, zero Judge, foreground execution, current `.env`, inherited proxy variables, new source lock/evidence root, no optimization, and a finite Agent cost cap.

- [ ] **Step 2: Preflight without providers**

Clear stale DCI/API credential variables, source the approved `.env`, preserve the explicitly approved inherited proxy variables, and run the exact DCI preflight. Confirm the source lock/evidence root are new and the operation receipt binds case limit 1, Judge 0, and the approved cost cap.

- [ ] **Step 3: Execute once in the foreground**

Run the approved command directly in the foreground. Do not background, parallelize, auto-retry, resume an already completed case, or broaden the scope. If provider authentication/network fails, stop and diagnose from the recorded safe evidence; do not spend a second call without renewed authority.

- [ ] **Step 4: Validate the native evidence directly**

Require the new native `workflow-evidence.json` itself—not an offline companion—to show verified provider requests aligned to every model-call node, request-only calls where applicable, exact per-call gaps, all tool calls, and no `model-request` gap when requests were captured. Record actual elapsed time, Agent cost, tokens, tools/errors, request count, assistant response count, Judge count, and single-case score with its non-benchmark caveat.

- [ ] **Step 5: Inspect and stop the foreground Dashboard**

Start the loopback-only Dashboard in the foreground against only the validated new bundle. Inspect workflow order, request-only node gaps, evaluations, and sentinel redaction; then stop it cleanly. Do not leave a service running.

- [ ] **Step 6: Publish the final Chinese result and commit**

Update `DCI-BENCHMARK-INSTANCES.md` with native-vs-offline provenance and exact safe metrics. Run `make docs-check`, commit only the documentation, append the JOURNAL SHA, update RESUME, and report whether all completion criteria are satisfied. Never promote a failed, external-limited, or not-rerun condition to PASS.
