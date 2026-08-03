# Pathlight–Opik Interoperability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-free, offline-first Pathlight export/import boundary that mirrors safe trace, experiment, evaluation, and proposal identities into Opik without granting Opik execution or evidence authority.

**Architecture:** Pathlight owns immutable, content-addressed records. A generic interoperability module creates digest-bound export envelopes, append-only queue batches, delivery receipts, and non-authoritative external observations; an Opik mapping module converts only already-public Pathlight fields into versioned mirror events. The CLI prepares and inspects local queues only—network delivery, credentials, retries, and Opik SDK usage remain operator-owned adapters outside the runner.

**Tech Stack:** Python 3.14, frozen dataclasses, canonical JSON/SHA-256, private 0600 files in operator-owned 0700 directories, `unittest`, existing Pathlight bundle validators and CLI.

## Global Constraints

- Framework code must remain domain-neutral and must not import DCI implementations or evidence formats.
- No Opik SDK, global client, decorator, implicit network request, credential lookup, or provider import belongs in framework core.
- Export payloads may contain only opaque/digest identities, statuses, numeric metrics, counts, versions, and safe failure categories.
- Prompts, answers, corpus text, tool/model payloads, credentials, private paths, provider configuration, and reversible encodings are forbidden.
- Opik UUIDs, names, tags, prompt registry entries, and `latest` labels never become Pathlight authority.
- Repeated export of the same local object and mapping version must produce the same idempotency key and no second logical queue event.
- Import creates only `ExternalObservation` or `ProposalCandidate`; both remain non-authoritative and non-executing.
- Queue/network failures must never alter traces, runtime execution, evaluation, experiment, diagnosis, or runner results.
- Dashboard work is outside this plan and remains last.

---

### Task 1: Generic immutable interoperability contracts

**Files:**
- Create: `src/asterion/pathlight/interop.py`
- Modify: `src/asterion/pathlight/__init__.py`
- Test: `tests/test_pathlight_interop.py`

**Interfaces:**
- Consumes: canonical JSON-compatible mappings already validated by Pathlight.
- Produces: `ExportEnvelope`, `ExportReceipt`, `ExternalObservation`, `ProposalCandidate`, `validate_*` functions, and exact schema constants.

- [x] **Step 1: Write failing closed-contract tests**

```python
def test_export_envelope_is_content_addressed_and_rejects_unknown_payload_fields():
    envelope = ExportEnvelope(
        connector="opik",
        mapping_version="1.0.0",
        event_kind="evaluation.upsert",
        local_object_sha256="a" * 64,
        payload={"evaluation_sha256": "b" * 64, "value_microunits": 750_000},
    )
    assert envelope.idempotency_key == envelope.envelope_sha256
    with self.assertRaises(PathlightError):
        ExportEnvelope(..., payload={"prompt": "SENTINEL_PRIVATE"})
```

Cover exact field sets, sorted payload keys, digest mismatch, hostile mapping subclasses, booleans-as-integers, unknown connector/event kind, and proposal candidates that attempt to set execution authority.

- [x] **Step 2: Run the test and verify it fails**

Run: `uv run python -m unittest -v tests.test_pathlight_interop`

Expected: FAIL because `asterion.pathlight.interop` does not exist.

- [x] **Step 3: Implement the minimal contracts**

```python
@dataclass(frozen=True, slots=True)
class ExportEnvelope:
    connector: Literal["opik"]
    mapping_version: str
    event_kind: ExportEventKind
    local_object_sha256: str
    payload: Mapping[str, SafeScalar]
    idempotency_key: str = field(init=False)
    envelope_sha256: str = field(init=False)

@dataclass(frozen=True, slots=True)
class ExportReceipt:
    envelope_sha256: str
    connector: Literal["opik"]
    status: Literal["delivered", "retryable-failure", "terminal-failure"]
    attempt: int
    external_object_sha256: str | None
    failure_category: Literal["authentication", "rate-limit", "network", "mapping", "service"] | None
    receipt_sha256: str = field(init=False)
```

Implement `ExternalObservation` with connector identity, mapping version, local subject digest, external event digest, observation kind, safe payload, and immutable digest. Implement `ProposalCandidate` with an external observation digest plus change/scope/success/stop/budget digests and hard-coded `execution_authorized=False`.

- [x] **Step 4: Run focused tests and checks**

Run: `uv run python -m unittest -v tests.test_pathlight_interop`

Expected: PASS.

Run: `uv run ruff check src/asterion/pathlight/interop.py tests/test_pathlight_interop.py && uv run pyright src/asterion/pathlight/interop.py tests/test_pathlight_interop.py`

Expected: both PASS.

- [x] **Step 5: Commit**

```bash
git add src/asterion/pathlight/interop.py src/asterion/pathlight/__init__.py tests/test_pathlight_interop.py
git commit -m "feat: add Pathlight interoperability contracts"
```

### Task 2: Append-only offline queue and receipt ledger

**Files:**
- Modify: `src/asterion/pathlight/interop.py`
- Test: `tests/test_pathlight_interop.py`

**Interfaces:**
- Consumes: `Sequence[ExportEnvelope]`, operator-owned queue root, and validated `ExportReceipt` values.
- Produces: `write_export_batch(root, envelopes) -> ExportBatch`, `read_export_batch(path)`, `record_export_receipt(root, receipt)`, and `read_export_receipts(root)`.

- [x] **Step 1: Write failing persistence tests**

```python
def test_offline_batch_is_private_atomic_sorted_and_idempotent():
    batch = write_export_batch(root, (second, first, first))
    assert batch.envelopes == (first, second)
    assert stat.S_IMODE((root / batch.filename).stat().st_mode) == 0o600
    assert write_export_batch(root, (second, first)).batch_sha256 == batch.batch_sha256
    assert tuple(root.glob("*.json")) == (root / batch.filename,)
```

Also test symlink rejection, root mode/ownership checks, no-replace publication races, malformed or oversized files, receipt attempt monotonicity, terminal/delivered state preventing later retries, and 401 mapping to an `authentication` receipt rather than a task failure.

- [x] **Step 2: Run the test and verify it fails**

Run: `uv run python -m unittest -v tests.test_pathlight_interop`

Expected: FAIL because queue functions are missing.

- [x] **Step 3: Implement atomic private persistence**

Use descriptor-relative open/stat/link/rename patterns already established in `pathlight/_private_file.py`; require an existing canonical 0700 root owned by the current uid, write 0600 canonical JSON, fsync before publication, never follow symlinks, and name batches by `batch-<sha256>.json`. Duplicate envelopes collapse by idempotency key only when the canonical bytes match.

- [x] **Step 4: Run tests and checks**

Run: `uv run python -m unittest -v tests.test_pathlight_interop tests.test_pathlight_private_file`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/asterion/pathlight/interop.py tests/test_pathlight_interop.py
git commit -m "feat: persist offline Pathlight export queues"
```

### Task 3: Versioned safe Opik mapping

**Files:**
- Create: `src/asterion/pathlight/opik.py`
- Modify: `src/asterion/pathlight/__init__.py`
- Test: `tests/test_pathlight_opik.py`

**Interfaces:**
- Consumes: validated `TraceGraph`, `ExperimentBundle`, `EvaluationBundle`, and `DiagnosisBundle` objects.
- Produces: `map_opik_exports(..., mapping_version="1.0.0") -> tuple[ExportEnvelope, ...]`.

- [x] **Step 1: Write failing mapping/redaction tests**

```python
def test_opik_mapping_links_experiment_trial_trace_and_feedback_without_bodies():
    envelopes = map_opik_exports(
        traces=(trace,), experiments=(experiment,), evaluations=(evaluation,), diagnoses=(diagnosis,)
    )
    assert {item.event_kind for item in envelopes} == {
        "trace.upsert", "experiment.upsert", "case-trial.upsert",
        "evaluation.upsert", "proposal.observe",
    }
    encoded = json.dumps([item.to_mapping() for item in envelopes])
    for sentinel in PRIVATE_SENTINELS:
        assert sentinel not in encoded
```

Test stable ordering, repeated mapping identity, exact local digest links, missing trace/metric references failing closed, no provider/model names, no raw event attributes, and Opik IDs absent from authoritative identities.

- [x] **Step 2: Run the test and verify it fails**

Run: `uv run python -m unittest -v tests.test_pathlight_opik`

Expected: FAIL because the mapper does not exist.

- [x] **Step 3: Implement the whitelist mapper**

Map trace status/kind/component digests and numeric timing/counts; experiment/dataset/variant/trial digests and evidence state; evaluation metric contract digest, value, coverage counts, and status; proposal/finding digests and authorization-required flags. Do not serialize source file paths, trace event attributes outside the approved scalar whitelist, or any model/tool content.

- [x] **Step 4: Run focused and redaction tests**

Run: `uv run python -m unittest -v tests.test_pathlight_opik tests.test_pathlight_protocol tests.test_pathlight_experiment tests.test_pathlight_evaluation tests.test_pathlight_diagnosis`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/asterion/pathlight/opik.py src/asterion/pathlight/__init__.py tests/test_pathlight_opik.py
git commit -m "feat: map safe Pathlight records for Opik"
```

### Task 4: Provider-free CLI export and non-authoritative import

**Files:**
- Modify: `src/asterion/cli_pathlight.py`
- Test: `tests/test_pathlight_cli.py`

**Interfaces:**
- Consumes: absolute canonical Pathlight bundle paths and an existing canonical 0700 queue root.
- Produces: `asterion pathlight export opik ... --queue-root ROOT`, `export inspect --batch-file FILE`, and `import opik-observation --observation-file FILE --output-root ROOT`.

- [x] **Step 1: Write failing CLI tests**

```python
code = main([
    "export", "opik", "--experiment-file", str(experiment),
    "--evaluation-file", str(evaluations), "--queue-root", str(queue),
], stdout=stdout, stderr=stderr)
assert code == 0
assert json.loads(stdout.getvalue())["network_operation_count"] == 0
```

Cover deterministic re-run, missing/relative/wrong-basename paths, invalid root modes, sentinel redaction, input mutation after open, unknown mapping versions, hostile imported fields, and import output remaining `execution_authorized=false`.

- [x] **Step 2: Run the test and verify it fails**

Run: `uv run python -m unittest -v tests.test_pathlight_cli`

Expected: FAIL because `export` and `import` commands are absent.

- [x] **Step 3: Implement the commands**

Extend `_parser()` with exact subcommands. Reuse current bundle readers, call the mapper and queue writer, and emit only batch digest, envelope count, mapping version, and `network_operation_count: 0`. Inspection returns canonical safe envelope mappings. Import validates a connector-signed/digest-bound local file and persists only `ExternalObservation`/`ProposalCandidate`; it never loads providers or executes a proposal.

- [x] **Step 4: Run CLI and provider-free boundary tests**

Run: `uv run python -m unittest -v tests.test_pathlight_cli tests.test_pathlight_opik tests.test_pathlight_interop`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/asterion/cli_pathlight.py tests/test_pathlight_cli.py
git commit -m "feat: add offline Pathlight Opik CLI"
```

### Task 5: Documentation, distribution, and full verification

**Files:**
- Modify: `docs/superpowers/specs/2026-08-02-asterion-pathlight-design.md`
- Modify: `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/JOURNAL.md`

**Interfaces:**
- Consumes: implemented CLI and passing commands.
- Produces: operator runbook, exact trust boundary, compatibility statement, and verified status.

- [x] **Step 1: Add the offline runbook**

Document creating a 0700 queue, exporting verified Pathlight files without network, inspecting the safe batch, handing it to an operator-owned adapter, recording a delivery receipt, and importing an external suggestion only as a non-executing candidate. State that no Opik package is required for prepare/inspect/import validation.

- [x] **Step 2: Run complete verification**

Run: `uv run python -m unittest -v tests.test_pathlight_interop tests.test_pathlight_opik tests.test_pathlight_cli tests.test_pathlight_protocol tests.test_pathlight_experiment tests.test_pathlight_evaluation tests.test_pathlight_diagnosis`

Expected: PASS.

Run: `make lint && make docs-check && make promotion-check`

Expected: PASS.

- [x] **Step 3: Verify provider-free packaging**

Build/install the wheel in an isolated environment and execute the offline export/inspect path without `opik`, provider credentials, or network. Expected: command succeeds, produces only 0600 queue files, and reports zero network operations.

- [x] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-08-02-asterion-pathlight-design.md docs/status/PATHLIGHT-DCI-DIAGNOSIS.md
git commit -m "docs: document Pathlight Opik interoperability"
```

## Self-Review

- Spec coverage: export envelopes, queue/receipts, trace–experiment–evaluation mapping, non-authoritative import, redaction, idempotency, optional Opik dependency, controlled proposals, CLI/API, and Dashboard deferral are each assigned to a task.
- Placeholder scan: no implementation step delegates unspecified error handling or testing; every boundary lists exact accepted output and rejection classes.
- Type consistency: Task 1 defines all values consumed by Tasks 2–4; Task 3 returns `ExportEnvelope`; Task 4 persists those envelopes through Task 2 and imports only Task 1 observation/candidate contracts.
