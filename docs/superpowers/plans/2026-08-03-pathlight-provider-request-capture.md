# Pathlight Provider Request Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture every Pi provider request through an Asterion-owned 0600 private descriptor, cross-check it against an independent body-free summary, and publish verified request structure in the generic Pathlight mainline without changing task semantics.

**Architecture:** A separate DCI observation extension observes Pi's supported `before_provider_request` hook. Raw JSON goes only to a host-created private FD; a safe custom entry crosses the RPC boundary. Python recomputes and compares both views, converts them to generic `ProviderRequestObservation` values, reconciles the Pi observation batch, and exposes only digest/shape/count metadata through Pathlight.

**Tech Stack:** Python 3.14, `unittest`, TypeScript/Node 23, Pi extension hooks, descriptor-relative POSIX I/O, Asterion Pathlight runtime observation v2, immutable JSON bundles.

## Global Constraints

- Do not modify the external Pi checkout or add a Pi patch dependency.
- Framework modules must not import DCI; the DCI adapter may depend on generic Pathlight observation types.
- Raw prompt, payload, tool schema, answers, credentials, provider/model/config values, and private paths never enter public bundles, CLI, API, Dashboard, Opik envelopes, or errors.
- `provider-requests.jsonl` is descriptor-relative, exclusive, no-follow, immutable, and mode 0600.
- Each private record is limited to 64 MiB and one native generation to 512 MiB; overflow degrades observation but never blocks Agent/Judge execution.
- Provider request order is exact; the absent Asterion monotonic hook timestamp remains an explicit `model-request-boundary` gap.
- Observation failure never changes the authoritative DCI result, retry decision, score, or authorization.
- Use `unittest`, run every RED before production edits, and keep commits focused.

---

### Task 1: Generic Verified Provider Request Observation

**Files:**
- Modify: `src/asterion/pathlight/runtime_observation.py`
- Modify: `src/asterion/pathlight/__init__.py`
- Modify: `src/asterion/pathlight/protocol.py`
- Modify: `src/asterion/workflow_evidence/runtime.py`
- Modify: `src/asterion/runtimes/pi_observation.py`
- Test: `tests/test_pi_pathlight_observation.py`
- Test: `tests/test_workflow_evidence_runtime.py`

**Interfaces:**
- Produces: `ProviderRequestObservation.build(...)`, `PiObservationBuilder.reconcile_provider_requests(values)`, and `RuntimeObservationBatch.provider_requests` under `asterion.pathlight-runtime-observation/v2`.
- Consumes: existing digest-only `ContextSegmentSummary`, inferred Pi frames/model calls, and Pathlight model-call projection.

- [ ] **Step 1: Write failing protocol and reconciliation tests**

Add tests that construct:

```python
request = ProviderRequestObservation.build(
    request_index=1,
    payload_sha256=_digest("exact-payload"),
    payload_bytes=13,
    shape_sha256=_digest("shape"),
    field_count=9,
    leaf_count=5,
    text_characters=42,
    private_reference_sha256=_digest("private-record"),
    segments=(
        ContextSegmentSummary(0, "system", "contract", _digest("sys"), 3, None, False),
        ContextSegmentSummary(1, "user", "message", _digest("question"), 8, None, False),
    ),
)
builder.reconcile_provider_requests((request,))
batch = builder.complete("run")
self.assertEqual(batch.model_calls[0].request_sha256, request.payload_sha256)
self.assertEqual(batch.provider_requests, (request,))
self.assertNotIn("model-request", batch.missing_evidence)
self.assertIn("model-request-boundary", batch.missing_evidence)
```

Cover duplicate/non-contiguous indexes, segment index drift, request count mismatch, reconciliation before/after rollback, raw sentinel redaction, v1 rejection, v2 round-trip, and projection attributes `request_shape_sha256`, counts, and `private_reference_sha256`.

- [ ] **Step 2: Run RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_pi_pathlight_observation \
  tests.test_workflow_evidence_runtime
```

Expected: FAIL because `ProviderRequestObservation`, v2 batch fields, and reconciliation do not exist.

- [ ] **Step 3: Implement the closed generic values and reconciliation**

Add a frozen value with exact validation:

```python
@dataclass(frozen=True, slots=True)
class ProviderRequestObservation:
    request_index: int
    payload_sha256: str
    payload_bytes: int
    shape_sha256: str
    field_count: int
    leaf_count: int
    text_characters: int
    private_reference_sha256: str
    segments: tuple[ContextSegmentSummary, ...]
    provider_request_sha256: str = field(init=False)

    @classmethod
    def build(cls, **values: object) -> ProviderRequestObservation:
        return cls(**values)  # validation remains in __post_init__
```

Bump only the internal Pathlight runtime observation mapping to v2, add exact `provider_requests`, validate one request per reconciled model call, and include it in `batch_sha256`. Reconciliation must atomically replace inferred request digests/segments only when the complete tuple matches; otherwise retain the original inferred batch and explicit gaps. Extend model-call trace attributes with body-free request shape/count/private-reference fields and exact validation.

- [ ] **Step 4: Run GREEN and the neighboring query/storage tests**

```bash
uv run python -m unittest -v \
  tests.test_pi_pathlight_observation \
  tests.test_workflow_evidence_runtime \
  tests.test_workflow_evidence_storage \
  tests.test_pathlight_query \
  tests.test_pathlight_cli
```

Expected: PASS; sentinel request content is absent from every serialized mapping.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/pathlight src/asterion/workflow_evidence/runtime.py \
  src/asterion/runtimes/pi_observation.py tests/test_pi_pathlight_observation.py \
  tests/test_workflow_evidence_runtime.py
git commit -m "feat: model verified provider requests"
```

### Task 2: TypeScript Observation Extension and Shared Fixtures

**Files:**
- Create: `packages/typescript/dci-context-extension/src/dci-pathlight-observation.ts`
- Create: `packages/typescript/dci-context-extension/test/pathlight-observation.test.mjs`
- Create: `tests/fixtures/pathlight-provider-request/v1/valid-simple.json`
- Create: `tests/fixtures/pathlight-provider-request/v1/valid-tools.json`
- Create: `tests/fixtures/pathlight-provider-request/v1/invalid-summary.json`
- Modify: `packages/typescript/dci-context-extension/scripts/sync-runtime-resource.mjs`
- Modify: `packages/typescript/dci-context-extension/package.json`

**Interfaces:**
- Produces: extension default export, `summarizeProviderPayload(payload)`, private record schema `dci.private-provider-request/v1`, and safe custom entry schema `dci.provider-request-observation/v1`.
- Consumes: inherited `ASTERION_DCI_PATHLIGHT_PRIVATE_FD` and `ASTERION_DCI_PATHLIGHT_CAPTURE_CONTRACT` exactly once at module load.

- [ ] **Step 1: Write failing Node tests and canonical fixtures**

Tests must use a pipe/temp 0600 descriptor and a fake Pi with only `on`/`appendEntry`. Assert:

```javascript
const returned = handler({ type: "before_provider_request", payload }, {});
assert.equal(returned, undefined);
assert.equal(pi.entries[0].customType, "dci-provider-request-observation");
assert.equal(JSON.stringify(pi.entries).includes("SENTINEL_PRIVATE_PAYLOAD"), false);
assert.equal(privateRecord.payload_json.includes("SENTINEL_PRIVATE_PAYLOAD"), true);
assert.equal(privateRecord.payload_sha256, pi.entries[0].data.payload_sha256);
```

Add independent cases for object-key order, arrays, explicit roles, instructions, tool results, unknown structures, circular/BigInt/non-finite values, partial `writeSync`, closed FD, append failure, 64 MiB record boundary, and 512 MiB cumulative boundary. Verify the hook never throws and never modifies the payload.

- [ ] **Step 2: Run RED**

```bash
npm test --prefix packages/typescript/dci-context-extension
```

Expected: FAIL because the observation module and fixtures are absent.

- [ ] **Step 3: Implement safe summarization and complete FD writes**

Use deterministic helpers with no provider imports:

```typescript
export function summarizeProviderPayload(payload: unknown): SafeObservation {
  const payloadJson = strictJsonStringify(payload);
  const payloadBytes = Buffer.byteLength(payloadJson, "utf8");
  const shape = summarizeShapeAndSegments(JSON.parse(payloadJson));
  return closeAndDigestObservation(payloadJson, payloadBytes, shape);
}

function writeAll(fd: number, value: Uint8Array): void {
  for (let offset = 0; offset < value.length;) {
    const written = writeSync(fd, value, offset, value.length - offset);
    if (written <= 0) throw new Error("private capture unavailable");
    offset += written;
  }
}
```

The default extension deletes the two environment variables immediately, registers exactly one `before_provider_request` handler, writes raw first, appends safe second, catches every observation error, and returns `undefined`. Safe entries contain no JSON key/value text, provider/model/config identity, or path.

- [ ] **Step 4: Run GREEN**

```bash
npm run build --prefix packages/typescript/dci-context-extension
node --test packages/typescript/dci-context-extension/test/pathlight-observation.test.mjs
```

Expected: the new observation tests PASS. The package-wide resource check is intentionally deferred to Task 3, which creates and syncs the packaged artifact.

- [ ] **Step 5: Commit**

```bash
git add packages/typescript/dci-context-extension tests/fixtures/pathlight-provider-request
git commit -m "feat: observe Pi provider payloads safely"
```

### Task 3: Packaged Extension Integrity and Resolution

**Files:**
- Create: `src/asterion/capabilities/dci/resources/pi/dci-pathlight-observation.ts`
- Create: `src/asterion/capabilities/dci/resources/pi/pathlight-observation-manifest.json`
- Create: `src/asterion/capabilities/dci/implementation/research/pathlight_observation.py`
- Create: `tests/test_dci_pathlight_observation_extension.py`
- Modify: `packages/typescript/dci-context-extension/scripts/sync-runtime-resource.mjs`
- Modify: `src/asterion/capabilities/dci/implementation/_provenance.py`
- Modify: `src/asterion/capabilities/dci/implementation/reproduction/provenance.py`

**Interfaces:**
- Produces: `ResolvedPathlightObservationExtension(path, version, sha256, contract_version)` and `resolve_pathlight_observation_extension()`.
- Consumes: checked-in TS source and manifest; accepts no path override.

- [ ] **Step 1: Write failing integrity tests**

Copy the context extension trust-boundary matrix: missing resource, symlink, non-regular file, size/digest/version/schema mismatch, forbidden runtime import, mutable manifest, and installed-wheel resolution. Require that the source contains exactly the supported hook and no provider/tool/command registration.

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_dci_pathlight_observation_extension
```

Expected: FAIL because the resolver and packaged artifacts do not exist.

- [ ] **Step 3: Implement resolver and sync both resources atomically**

Mirror the existing context resolver but use closed identities:

```python
_MANIFEST_SCHEMA = "dci.pathlight-observation-extension-manifest/v1"
_RESOURCE_NAME = "dci-pathlight-observation.ts"
_MANIFEST_NAME = "pathlight-observation-manifest.json"
```

The sync script must validate and update both extension resources in one invocation; `--check` compares bytes and exact manifests without mutation. Add both resource digests to DCI implementation provenance.

- [ ] **Step 4: Sync, run GREEN, and promotion resource checks**

```bash
npm run sync-resource --prefix packages/typescript/dci-context-extension
npm test --prefix packages/typescript/dci-context-extension
uv run python -m unittest -v tests.test_dci_pathlight_observation_extension
make promotion-check
```

Expected: PASS and `provider_operations=0`.

- [ ] **Step 5: Commit**

```bash
git add packages/typescript/dci-context-extension/scripts \
  src/asterion/capabilities/dci/resources/pi \
  src/asterion/capabilities/dci/implementation/research/pathlight_observation.py \
  src/asterion/capabilities/dci/implementation/_provenance.py \
  src/asterion/capabilities/dci/implementation/reproduction/provenance.py \
  tests/test_dci_pathlight_observation_extension.py
git commit -m "feat: package Pathlight Pi observation extension"
```

### Task 4: Private Capture and Cross-Language Validation

**Files:**
- Create: `src/asterion/capabilities/dci/implementation/evaluation/provider_requests.py`
- Create: `tests/test_dci_provider_request_capture.py`
- Modify: `src/asterion/capabilities/dci/implementation/evaluation/__init__.py`

**Interfaces:**
- Produces: `ProviderRequestCapture.open_at(directory_fd)`, `.child_fd`, `.validate(safe_entries) -> tuple[ProviderRequestObservation, ...]`, `.close()`, and fixed `ProviderRequestCaptureError`.
- Consumes: private JSONL records, safe custom entries, shared fixtures, and Task 1 generic observations.

- [ ] **Step 1: Write failing descriptor and validation tests**

Test a real descriptor-relative directory and assert mode 0600, `O_EXCL`, no symlink/FIFO/directory target, immutable existing target, bounded read, strict UTF-8/JSONL, exact schemas/fields/types, contiguous indexes, timestamp shape, digest/byte/shape/summary/count/segment parity, and fixed redacted errors. Include all valid/invalid cross-language fixtures and SENTINEL values.

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_dci_provider_request_capture
```

Expected: FAIL because `ProviderRequestCapture` is absent.

- [ ] **Step 3: Implement the focused private capture module**

Open with descriptor-relative flags and validate the resulting inode:

```python
fd = os.open(
    "provider-requests.jsonl",
    os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
    0o600,
    dir_fd=directory_fd,
)
metadata = os.fstat(fd)
if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
    raise ProviderRequestCaptureError("provider request capture is invalid")
```

Read through the held FD after `fsync`, enforce 512 MiB before allocation, validate every raw line, independently recompute the generic shape/segments, compare to safe entries using `hmac.compare_digest`, and return immutable generic observations. Errors never include data, keys, paths, indexes, or supplied digests.

- [ ] **Step 4: Run GREEN and security tests**

```bash
uv run python -m unittest -v \
  tests.test_dci_provider_request_capture \
  tests.test_dci_reproduction \
  tests.test_asterion_dci_benchmark
```

Expected: PASS with no sentinel in output or exception text.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/capabilities/dci/implementation/evaluation/provider_requests.py \
  src/asterion/capabilities/dci/implementation/evaluation/__init__.py \
  tests/test_dci_provider_request_capture.py
git commit -m "feat: validate private provider request capture"
```

### Task 5: Pi RPC Injection and Safe Entry Retrieval

**Files:**
- Modify: `src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py`
- Modify: `tests/test_dci_pi_rpc_proxy.py`
- Create: `tests/test_dci_pi_rpc_observation.py`

**Interfaces:**
- Produces: `PiRpcClient(..., observation_extension_path, observation_fd, observation_contract)`, deterministic repeatable extension argv, child-only FD environment, and `get_provider_request_entries()`.
- Consumes: Task 3 resolved extension and Task 4 capture descriptor.

- [ ] **Step 1: Write failing command/environment/RPC tests**

Assert context extension precedes observation extension, paths stay out of environment values except existing extension argv, FD number/contract stay out of argv, caller `os.environ` is unchanged, `pass_fds` includes the exact FD once, child environment holds the two values, and get-entries returns only closed body-free provider observations. Reject raw payload/key/path fields, duplicates, malformed counts/segments, foreign custom types, and cursor drift with one redacted error.

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v \
  tests.test_dci_pi_rpc_proxy \
  tests.test_dci_pi_rpc_observation
```

Expected: FAIL because observation arguments/environment/retrieval do not exist.

- [ ] **Step 3: Implement explicit injection and a separate entry validator**

Keep `get_entries()` context-policy-only. Add a shared private `_request_entries()` RPC reader and two closed projections:

```python
def get_provider_request_entries(self) -> tuple[dict[str, Any], ...]:
    return _validated_provider_request_entries(self._request_entries())
```

The child environment gets copied values only when all observation inputs are present. `start()` passes the union of resource FDs and the observation FD as a sorted unique tuple. Reject partial configuration before resolving Node or starting Pi.

- [ ] **Step 4: Run GREEN and runtime tests**

```bash
uv run python -m unittest -v \
  tests.test_dci_pi_rpc_proxy \
  tests.test_dci_pi_rpc_observation \
  tests.test_asterion_pi_runtime
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py \
  tests/test_dci_pi_rpc_proxy.py tests/test_dci_pi_rpc_observation.py
git commit -m "feat: inject private Pi observation channel"
```

### Task 6: DCI Execution and Native Bundle Integration

**Files:**
- Modify: `src/asterion/capabilities/dci/implementation/runtime/run.py`
- Modify: `src/asterion/capabilities/dci/implementation/evaluation/artifacts.py`
- Modify: `tests/test_dci_pathlight_capture.py`
- Modify: `tests/test_asterion_dci_benchmark.py`

**Interfaces:**
- Produces: one native generation containing immutable private request evidence and a directly rich `workflow-evidence.json`.
- Consumes: Task 1 reconciliation, Task 3 resolver, Task 4 capture, and Task 5 Pi client inputs/entries.

- [ ] **Step 1: Write failing completed/failure/retry/resume tests**

Use a fixture client that writes private records to the injected FD, returns matching safe entries, and emits model/tool native events. Assert the completed native bundle has exact provider request metadata, no `model-request` gap, a retained `model-request-boundary` gap, complete tool lineage, and no sentinel. Add mismatch, missing entry, FD write failure, client construction failure, provider error, cancellation, retry rollback, completed-target conflict, and resume-new-generation cases; every authoritative DCI status/result must match the pre-observation behavior.

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v \
  tests.test_dci_pathlight_capture \
  tests.test_asterion_dci_benchmark
```

Expected: FAIL because DCI does not create, inject, validate, or reconcile provider requests.

- [ ] **Step 3: Integrate without changing execution authority**

Resolve the observation extension and open capture after the recorder pins its generation. Pass the exact path/FD/contract to Pi, fetch safe entries after prompt completion, validate raw/safe evidence, call `recorder.reconcile_provider_requests(observations)`, then finalize/persist through the existing path. Any observation exception sets a fixed safe state and continues with inferred/fallback observation. Close all resource/capture descriptors in `finally`.

Do not add retries, provider selection, scheduling, authorization, or output discovery to the recorder or runner.

- [ ] **Step 4: Run GREEN and the combined DCI boundary suite**

```bash
uv run python -m unittest -v \
  tests.test_dci_pathlight_capture \
  tests.test_dci_provider_request_capture \
  tests.test_dci_pi_rpc_observation \
  tests.test_dci_trajectory_resolution \
  tests.test_asterion_dci_benchmark \
  tests.test_workflow_evidence_runtime \
  tests.test_workflow_evidence_storage
```

Expected: PASS with no provider calls.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/capabilities/dci/implementation/runtime/run.py \
  src/asterion/capabilities/dci/implementation/evaluation/artifacts.py \
  tests/test_dci_pathlight_capture.py tests/test_asterion_dci_benchmark.py
git commit -m "feat: capture exact DCI provider requests"
```

### Task 7: Public Surfaces, Documentation, and Provider-Free Gates

**Files:**
- Modify: `tests/test_pathlight_cli.py`
- Modify: `tests/test_pathlight_dashboard.py`
- Modify: `tests/test_pathlight_opik.py`
- Modify: `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md`
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/superpowers/plans/2026-08-03-pathlight-provider-request-capture.md`

**Interfaces:**
- Produces: provider-free evidence that CLI/Dashboard expose exact request structure but never private bodies, plus a separately authorized real-run handoff.
- Consumes: Tasks 1–6 only; this task does not execute a model.

- [ ] **Step 1: Add public redaction and workflow-first UI tests**

Build a bundle with verified provider request metadata and sentinel private input. Assert `trace list/show/tail/flow`, Dashboard snapshot/API/assets, and Opik export contain request digest/shape/count/private-reference fields, retain `model-request-boundary`, omit `model-request`, and contain none of the sentinel, raw payload, provider/model/config values, FD, or path.

- [ ] **Step 2: Run RED/GREEN for public surfaces**

```bash
uv run python -m unittest -v \
  tests.test_pathlight_cli \
  tests.test_pathlight_dashboard \
  tests.test_pathlight_opik
```

Expected: PASS after only fixture/assertion adjustments needed by the v2 observation contract; no network operations.

- [ ] **Step 3: Update Chinese status documents truthfully**

Document the implemented boundary, provider-free fixture proof, remaining monotonic-boundary gap, and the fact that the old one-case native bundle remains immutable. Mark the next real Bright Biology case as requiring separate explicit authorization; do not claim the existing offline companion became native or that a score changed.

- [ ] **Step 4: Run complete provider-free verification**

```bash
make check
make promotion-check
```

Expected: `make check` PASS; promotion full PASS with `provider_operations=0` and `full_dataset=no`.

- [ ] **Step 5: Commit verified implementation closure**

```bash
git add tests/test_pathlight_cli.py tests/test_pathlight_dashboard.py \
  tests/test_pathlight_opik.py docs/status/PATHLIGHT-DCI-DIAGNOSIS.md \
  docs/status/DCI-BENCHMARK-INSTANCES.md \
  docs/superpowers/plans/2026-08-03-pathlight-provider-request-capture.md
git commit -m "docs: verify exact Pathlight request capture"
```

### Task 8: Separately Authorized Real One-Case Closure

**Files:**
- Modify after execution: `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md`
- Modify after execution: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Modify after execution: `docs/status/RESUME-NEXT-SESSION.md`
- Modify after execution: `docs/status/JOURNAL.md`

**Interfaces:**
- Produces: one foreground Bright Biology native bundle with directly verified exact request capture, CLI flow, Dashboard snapshot, actual cost/time, and explicit gaps.
- Consumes: a fresh operator authorization, fresh source lock, fresh evidence root, and Tasks 1–7 passing gates.

- [ ] **Step 1: Stop and request exact one-case authorization**

Do not infer authority from this implementation plan or prior runs. Request one Bright Biology case, zero Judge, foreground execution, current `.env`, fresh lock/evidence, and no optimization experiment.

- [ ] **Step 2: Execute only after approval**

Clear inherited Agent/Judge/proxy variables, source `.env`, create fresh exact inputs, and run:

```bash
uv run asterion-dci benchmark run \
  --instance dci.bright.biology@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$FRESH_LOCK" \
  --evidence-root "$FRESH_EVIDENCE" \
  --execute
```

Expected: 1/1 completed, zero Judge, foreground only, one immutable native private capture and public bundle.

- [ ] **Step 3: Validate without exposing private content**

Use the public reader, `pathlight trace list/flow`, and foreground Dashboard. Record only counts, digests, modes, terminal status, actual cost/time, and missing labels. Verify private capture mode 0600 internally and stop Dashboard with `Ctrl-C`.

- [ ] **Step 4: Update docs, rerun gates, and commit**

Run `make check` and `make promotion-check`, update the Chinese single-case section without generalizing its score, mark this plan complete, and commit the verified closure.
