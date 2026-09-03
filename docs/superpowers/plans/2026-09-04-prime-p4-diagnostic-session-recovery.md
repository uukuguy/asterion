# Prime P4 Diagnostic Session Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver sealed, authorization-gated evidence for one fixed Prime IPython offline diagnostic that survives detach/attach, compaction, and supervisor recovery without replaying uncertain effects.

**Architecture:** Python defines the fixed workload and private trace. A narrow adapter calls already-existing gateway lifecycle operations through an injected protocol; it stores only digest projections, permits no continuation/replay operation, and rejects identity, cursor, generation, or durability mismatches. Provider-free fakes return only a provider-free receipt; a pure reducer produces bounded evidence only after explicit live attestation.

**Tech Stack:** Python 3.11 frozen dataclasses, `unittest`, SHA-256, existing Prime TypeScript gateway lifecycle semantics; no Docker, provider request, network, `.env`, or changes under `3th-party/prime-agent`.

## Global Constraints

- Scenario ID is `prime.long-session-continuity/v1`; root and child action surfaces are exactly `("ipython",)`.
- The manifest fixes fixture, root/child roles, model, schema, oracle, action ceilings, and exactly one detach, attach, compaction, and supervisor recovery.
- Callers supply no diagnostic text, prompt, file, path, identity, model, cursor, recovery policy, environment, or credential.
- Checkpoints/reports contain SHA-256 projections and booleans only; public exceptions and reprs contain none of the private values.
- Provider-free tests prove protocol semantics only. Bounded evidence requires separately authorized real Prime/IPython, checkpoint, gateway recovery, broker-quiescence, and worker-destruction attestation.

---

### Task 1: Fixed workload and immutable recovery trace

**Files:**

- Create: `src/asterion/applications/prime_agent/operator/diagnostic_session_recovery_workload.py`
- Create: `src/asterion/applications/prime_agent/diagnostic_session_recovery_receipt.py`
- Create: `tests/test_prime_diagnostic_session_recovery_workload.py`
- Create: `tests/test_prime_diagnostic_session_recovery_receipt.py`
- Modify: `src/asterion/applications/prime_agent/long_session_continuity_receipt.py`
- Modify: `tests/test_prime_long_session_continuity_receipt.py`

**Interfaces:**

~~~python
P4_DIAGNOSTIC_RECOVERY_SCENARIO_ID: Final = "prime.long-session-continuity/v1"
P4_DIAGNOSTIC_RECOVERY_ROLE_ID: Final = "prime.long-session-continuity"
P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST: Final
P4_DIAGNOSTIC_RECOVERY_MODEL_SHA256: Final
P4_DIAGNOSTIC_RECOVERY_ORACLE_SHA256: Final
P4_DIAGNOSTIC_RECOVERY_SCHEMA_SHA256: Final

@dataclass(frozen=True, repr=False)
class DiagnosticSessionRecoveryTrace:
    workload_sha256: str
    root_pre_recovery_artifact_sha256: str
    root_post_recovery_artifact_sha256: str
    child_registry_sha256: str
    checkpoint_sha256: str
    compaction_summary_sha256: str
    recovery_cursor_sha256: str
    diagnostic_result_sha256: str
    oracle_sha256: str
    schema_sha256: str
    model_sha256: str
    usage_sha256: str
    root_tool_names: tuple[str]
    child_tool_names: tuple[str]
    root_pre_recovery_actions: int
    root_post_recovery_actions: int
    child_actions: int
    detach_count: int
    attach_count: int
    compaction_count: int
    supervisor_recovery_count: int
    checkpoint_cursor_matches_attach: bool
    compaction_on_active_path: bool
    same_session_identity: bool
    same_transcript_identity: bool
    recovery_required_before_continue: bool
    durable_assets_only: bool
    uncertain_effect_fenced: bool
    oracle_passed: bool
    disposed: bool
    reaped: bool

def diagnostic_session_recovery_workload_manifest_bytes() -> bytes:
    return _MANIFEST_BYTES
def is_diagnostic_session_recovery_workload(value: object) -> bool:
    return type(value) is str and value == P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST
def verify_diagnostic_session_recovery_trace(
    trace: object,
    requested_level: PrimeEvidenceLevel = PrimeEvidenceLevel.BOUNDED,
) -> PrimeEvidenceReceipt:
    raise DiagnosticSessionRecoveryReceiptError("diagnostic session recovery trace is invalid")
~~~

- [ ] **Step 1: Write failing workload and trace tests.**

~~~python
manifest = json.loads(diagnostic_session_recovery_workload_manifest_bytes())
self.assertEqual(manifest["scenario_id"], "prime.long-session-continuity/v1")
self.assertEqual(manifest["model_tool_names"], ["ipython"])
self.assertEqual(manifest["detach_count"], 1)
self.assertEqual(manifest["attach_count"], 1)
self.assertEqual(manifest["compaction_count"], 1)
self.assertEqual(manifest["supervisor_recovery_count"], 1)

receipt = verify_diagnostic_session_recovery_trace(_trace())
self.assertIs(receipt.level, PrimeEvidenceLevel.BOUNDED)
for field in ("checkpoint_cursor_matches_attach", "compaction_on_active_path",
              "same_session_identity", "same_transcript_identity",
              "recovery_required_before_continue", "durable_assets_only",
              "uncertain_effect_fenced", "oracle_passed", "disposed", "reaped"):
    with self.subTest(field=field), self.assertRaises(DiagnosticSessionRecoveryReceiptError):
        verify_diagnostic_session_recovery_trace(replace(_trace(), **{field: False}))
~~~

Assert canonical bytes/digest stability, a fixed fixture/root/child/model/oracle/schema identity, finite positive ceilings, and no prompt/path/environment/credential manifest field. Reject extra trace fields introduced through `object.__setattr__`, malformed/substituted digests, unequal pre/post root artifact digests, non-`ipython` tool tuples, bool/zero counts, nonexact lifecycle counts, evidence-level downgrade/upgrade, and mutation. Assert repr and errors omit a private sentinel.

- [ ] **Step 2: Verify RED.**

Run: `uv run python -m unittest -v tests.test_prime_diagnostic_session_recovery_workload tests.test_prime_diagnostic_session_recovery_receipt`

Expected: FAIL because P4 workload and trace modules do not exist.

- [ ] **Step 3: Implement the closed boundary.**

Build a sorted compact JSON manifest with `json.dumps(value, sort_keys=True, separators=(",", ":"))` and derive its SHA-256. The trace verifier must require exact dataclass type and field set, full `sha256:[0-9a-f]{64}` values, exact P4 workload/model/oracle/schema identities, equal root artifact projections, both `("ipython",)` tuples, one of every lifecycle event, positive integer actions, and true required booleans. It returns only a bounded receipt through `validate_prime_evidence_receipt`.

Retain `LongSessionContinuityObservation` as provider-free compatibility evidence. Its verifier remains provider-free only and never calls this bounded verifier.

- [ ] **Step 4: Verify GREEN and commit.**

Run:

~~~bash
uv run python -m unittest -v tests.test_prime_diagnostic_session_recovery_workload tests.test_prime_diagnostic_session_recovery_receipt tests.test_prime_long_session_continuity_receipt tests.test_prime_worker_gate
uv run ruff check src/asterion/applications/prime_agent/operator/diagnostic_session_recovery_workload.py src/asterion/applications/prime_agent/diagnostic_session_recovery_receipt.py tests/test_prime_diagnostic_session_recovery_workload.py tests/test_prime_diagnostic_session_recovery_receipt.py
uv run pyright src/asterion/applications/prime_agent/operator/diagnostic_session_recovery_workload.py src/asterion/applications/prime_agent/diagnostic_session_recovery_receipt.py tests/test_prime_diagnostic_session_recovery_workload.py tests/test_prime_diagnostic_session_recovery_receipt.py
git diff --check
git add src/asterion/applications/prime_agent/operator/diagnostic_session_recovery_workload.py src/asterion/applications/prime_agent/diagnostic_session_recovery_receipt.py src/asterion/applications/prime_agent/long_session_continuity_receipt.py tests/test_prime_diagnostic_session_recovery_workload.py tests/test_prime_diagnostic_session_recovery_receipt.py tests/test_prime_long_session_continuity_receipt.py
git commit -m "feat(prime): define diagnostic recovery trace"
~~~

Expected: PASS with no runtime launch or external operation.

### Task 2: Canonical fixed diagnostic completion parser

**Files:**

- Create: `src/asterion/applications/prime_agent/operator/diagnostic_session_recovery_completion.py`
- Create: `tests/test_prime_diagnostic_session_recovery_completion.py`
- Create: `tests/fixtures/prime_gateway/v1/prime-diagnostic-session-recovery.json`

**Interfaces:**

~~~python
@dataclass(frozen=True, repr=False)
class DiagnosticSessionRecoveryCompletion:
    trace: DiagnosticSessionRecoveryTrace

def parse_diagnostic_session_recovery_completion(
    payload: object,
) -> DiagnosticSessionRecoveryCompletion:
    raise DiagnosticSessionRecoveryCompletionError("diagnostic session recovery completion is invalid")
~~~

- [ ] **Step 1: Write the failing parser contract tests.**

~~~python
completion = parse_diagnostic_session_recovery_completion(
    json.loads(FIXTURE.read_text(encoding="utf-8"))
)
self.assertEqual(completion.trace.workload_sha256, P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST)
self.assertTrue(completion.trace.uncertain_effect_fenced)
with self.assertRaises(DiagnosticSessionRecoveryCompletionError):
    parse_diagnostic_session_recovery_completion({"format": "wrong"})
~~~

The fixture has only a format/version, fixed identities, digest projections, exact counts, and booleans. Reject missing/extra keys, non-`["ipython"]` tool arrays, duplicate lifecycle values, changed checkpoint cursor, nonactive compaction, missing recovery fence, restored non-durable state, private fields, and substituted workload/model/oracle/schema. Assert no raw payload is retained in the result or errors.

- [ ] **Step 2: Verify RED.**

Run: `uv run python -m unittest -v tests.test_prime_diagnostic_session_recovery_completion`

Expected: FAIL because parser and fixture do not exist.

- [ ] **Step 3: Implement the canonical parser.**

Require an exact dict field set and `asterion.prime-diagnostic-session-recovery/v1`; normalize only the exact JSON `["ipython"]` arrays to tuples; construct the Task 1 trace; call `verify_diagnostic_session_recovery_trace` before return. Convert parsing/receipt failures to the one redacted completion error. Static fixture digests derive from nonsecret labels and do not imply any gateway/kernel/provider execution.

- [ ] **Step 4: Verify GREEN and commit.**

Run:

~~~bash
uv run python -m unittest -v tests.test_prime_diagnostic_session_recovery_completion tests.test_prime_diagnostic_session_recovery_receipt
uv run ruff check src/asterion/applications/prime_agent/operator/diagnostic_session_recovery_completion.py tests/test_prime_diagnostic_session_recovery_completion.py
uv run pyright src/asterion/applications/prime_agent/operator/diagnostic_session_recovery_completion.py tests/test_prime_diagnostic_session_recovery_completion.py
git diff --check
git add src/asterion/applications/prime_agent/operator/diagnostic_session_recovery_completion.py tests/test_prime_diagnostic_session_recovery_completion.py tests/fixtures/prime_gateway/v1/prime-diagnostic-session-recovery.json
git commit -m "feat(prime): parse diagnostic recovery completion"
~~~

Expected: PASS locally and provider-free.

### Task 3: Sealed checkpoint and recovery adapter

**Files:**

- Create: `src/asterion/applications/prime_agent/diagnostic_session_recovery_adapter.py`
- Create: `tests/test_prime_diagnostic_session_recovery_adapter.py`

**Interfaces:**

~~~python
@dataclass(frozen=True, repr=False)
class DiagnosticRecoveryCheckpoint:
    workload_sha256: str
    root_artifact_sha256: str
    child_registry_sha256: str
    oracle_sha256: str
    model_sha256: str
    cursor_sha256: str

@dataclass(frozen=True, repr=False)
class DiagnosticRecoveryGatewayState:
    session_sha256: str
    transcript_sha256: str
    cursor_sha256: str
    supervisor_generation: int
    recovery_required: bool
    compaction_on_active_path: bool
    durable_assets_only: bool
    uncertain_effect_fenced: bool

class DiagnosticRecoveryGateway(Protocol):
    async def detach(self) -> DiagnosticRecoveryGatewayState:
        raise NotImplementedError
    async def attach(self, cursor_sha256: str) -> DiagnosticRecoveryGatewayState:
        raise NotImplementedError
    async def compact(self) -> DiagnosticRecoveryGatewayState:
        raise NotImplementedError

async def recover_diagnostic_session(
    gateway: object,
    checkpoint: object,
    before_detach: object,
) -> DiagnosticRecoveryGatewayState:
    raise DiagnosticSessionRecoveryAdapterError("diagnostic session recovery is invalid")
~~~

- [ ] **Step 1: Write failing ordering and closure tests.**

~~~python
state = await recover_diagnostic_session(
    fake_gateway, _checkpoint(), _state(generation=1, recovery_required=False)
)
self.assertEqual(fake_gateway.calls, ["detach", "attach", "compact"])
self.assertEqual(state.supervisor_generation, 2)

with self.assertRaises(DiagnosticSessionRecoveryAdapterError):
    await recover_diagnostic_session(
        _Gateway(_state(generation=1, recovery_required=True)),
        _checkpoint(),
        _state(generation=1, recovery_required=False),
    )
~~~

Reject malformed checkpoint before reading gateway attributes; P4 identity mismatch; already-recovery-required input; session/transcript/cursor substitutions; same/lower generation; final false recovery-required/active-path/durable-only/uncertainty flags; operation exception; extra state fields; and private sentinels. Test that the protocol intentionally has no `continue`, `run`, `replay`, subprocess, or network method.

- [ ] **Step 2: Verify RED.**

Run: `uv run python -m unittest -v tests.test_prime_diagnostic_session_recovery_adapter`

Expected: FAIL because the adapter module does not exist.

- [ ] **Step 3: Implement the narrow adapter.**

Validate checkpoint and initial state before gateway inspection. Invoke `detach()`, `attach(checkpoint.cursor_sha256)`, then `compact()` exactly once. Require exact state type/fields after every operation; stable session/transcript identities; attach cursor equal to checkpoint cursor; final strict generation increase, recovery-required, active-path compaction, durable-only restore, and uncertainty fence. Convert expected type/value failures to one generic redacted exception. Do not invoke continuation or replay.

- [ ] **Step 4: Verify GREEN and commit.**

Run:

~~~bash
uv run python -m unittest -v tests.test_prime_diagnostic_session_recovery_adapter tests.test_prime_diagnostic_session_recovery_receipt tests.test_prime_diagnostic_session_recovery_completion
uv run ruff check src/asterion/applications/prime_agent/diagnostic_session_recovery_adapter.py tests/test_prime_diagnostic_session_recovery_adapter.py
uv run pyright src/asterion/applications/prime_agent/diagnostic_session_recovery_adapter.py tests/test_prime_diagnostic_session_recovery_adapter.py
git diff --check
git add src/asterion/applications/prime_agent/diagnostic_session_recovery_adapter.py tests/test_prime_diagnostic_session_recovery_adapter.py
git commit -m "feat(prime): fence diagnostic session recovery"
~~~

Expected: PASS with fakes only.

### Task 4: Provider-free acceptance and authorization-gated live reducer

**Files:**

- Create: `src/asterion/applications/prime_agent/diagnostic_session_recovery_acceptance.py`
- Create: `src/asterion/applications/prime_agent/diagnostic_session_recovery_live_validation.py`
- Create: `tests/test_prime_diagnostic_session_recovery_acceptance.py`
- Create: `tests/test_prime_diagnostic_session_recovery_live_validation.py`
- Modify: `docs/status/CURRENT-STATE.md`

**Interfaces:**

~~~python
@dataclass(frozen=True, repr=False)
class DiagnosticRecoveryProviderFreeObservation:
    completion: DiagnosticSessionRecoveryCompletion
    disposed: bool
    reaped: bool

async def accept_diagnostic_session_recovery(
    *, gateway: object, checkpoint: object, before_detach: object,
    observation: object,
) -> PrimeEvidenceReceipt:
    raise DiagnosticSessionRecoveryAcceptanceError("diagnostic session recovery acceptance is invalid")

@dataclass(frozen=True, repr=False)
class DiagnosticSessionRecoveryLiveAuthorization:
    platform_lock_sha256: str
    real_prime_ipython_attested: bool
    durable_checkpoint_attested: bool
    gateway_recovery_attested: bool
    broker_quiescent: bool
    worker_destroyed: bool

def validate_diagnostic_session_recovery_live_result(
    observation: object,
    authorization: object,
) -> PrimeEvidenceReceipt:
    raise DiagnosticSessionRecoveryLiveValidationError("diagnostic session recovery live evidence is invalid")
~~~

- [ ] **Step 1: Write failing fake full-chain and live-rejection tests.**

~~~python
receipt = await accept_diagnostic_session_recovery(
    gateway=fake_gateway, checkpoint=_checkpoint(),
    before_detach=_state(generation=1, recovery_required=False),
    observation=DiagnosticRecoveryProviderFreeObservation(_completion(), True, True),
)
self.assertIs(receipt.level, PrimeEvidenceLevel.PROVIDER_FREE)
self.assertEqual(fake_gateway.calls, ["detach", "attach", "compact"])

authorization = DiagnosticSessionRecoveryLiveAuthorization(
    "sha256:" + "a" * 64, True, True, True, True, True
)
with self.assertRaises(DiagnosticSessionRecoveryLiveValidationError):
    validate_diagnostic_session_recovery_live_result(object(), authorization)
~~~

Use a probe gateway to prove malformed checkpoint/state/observation denies before injected-service access. Reject false cleanup and every false authorization field. Assert acceptance never returns bounded evidence and all fakes lack model invocation, process launch, Docker, network, continuation, and replay operations.

- [ ] **Step 2: Verify RED.**

Run: `uv run python -m unittest -v tests.test_prime_diagnostic_session_recovery_acceptance tests.test_prime_diagnostic_session_recovery_live_validation`

Expected: FAIL because acceptance and live reducer modules do not exist.

- [ ] **Step 3: Implement the two evidence boundaries.**

Acceptance validates an exact observation/cleanup, invokes Task 3 recovery, parses/verifies Task 2 completion, and returns only provider-free P4 evidence. The live reducer requires exact authorization type, full SHA-256 lock, every attestation true, exact completion type, then calls `verify_diagnostic_session_recovery_trace(completion.trace, PrimeEvidenceLevel.BOUNDED)`. It is pure: no gateway, broker, worker, Docker, model, or provider object is injected or started.

Update `CURRENT-STATE.md` to name P4 recovery as an active structural boundary and mark provider-free verification non-promotable; real P4 execution remains External-limited.

- [ ] **Step 4: Verify GREEN and commit.**

Run:

~~~bash
uv run python -m unittest -v tests.test_prime_diagnostic_session_recovery_workload tests.test_prime_diagnostic_session_recovery_receipt tests.test_prime_diagnostic_session_recovery_completion tests.test_prime_diagnostic_session_recovery_adapter tests.test_prime_diagnostic_session_recovery_acceptance tests.test_prime_diagnostic_session_recovery_live_validation tests.test_prime_long_session_continuity_receipt tests.test_prime_worker_gate
uv run ruff check src/asterion/applications/prime_agent/operator/diagnostic_session_recovery_workload.py src/asterion/applications/prime_agent/operator/diagnostic_session_recovery_completion.py src/asterion/applications/prime_agent/diagnostic_session_recovery_receipt.py src/asterion/applications/prime_agent/diagnostic_session_recovery_adapter.py src/asterion/applications/prime_agent/diagnostic_session_recovery_acceptance.py src/asterion/applications/prime_agent/diagnostic_session_recovery_live_validation.py tests/test_prime_diagnostic_session_recovery_workload.py tests/test_prime_diagnostic_session_recovery_receipt.py tests/test_prime_diagnostic_session_recovery_completion.py tests/test_prime_diagnostic_session_recovery_adapter.py tests/test_prime_diagnostic_session_recovery_acceptance.py tests/test_prime_diagnostic_session_recovery_live_validation.py
uv run pyright src/asterion/applications/prime_agent/operator/diagnostic_session_recovery_workload.py src/asterion/applications/prime_agent/operator/diagnostic_session_recovery_completion.py src/asterion/applications/prime_agent/diagnostic_session_recovery_receipt.py src/asterion/applications/prime_agent/diagnostic_session_recovery_adapter.py src/asterion/applications/prime_agent/diagnostic_session_recovery_acceptance.py src/asterion/applications/prime_agent/diagnostic_session_recovery_live_validation.py tests/test_prime_diagnostic_session_recovery_workload.py tests/test_prime_diagnostic_session_recovery_receipt.py tests/test_prime_diagnostic_session_recovery_completion.py tests/test_prime_diagnostic_session_recovery_adapter.py tests/test_prime_diagnostic_session_recovery_acceptance.py tests/test_prime_diagnostic_session_recovery_live_validation.py
git diff --check
git add src/asterion/applications/prime_agent/diagnostic_session_recovery_acceptance.py src/asterion/applications/prime_agent/diagnostic_session_recovery_live_validation.py tests/test_prime_diagnostic_session_recovery_acceptance.py tests/test_prime_diagnostic_session_recovery_live_validation.py docs/status/CURRENT-STATE.md
git commit -m "feat(prime): accept diagnostic session recovery"
~~~

Expected: PASS with provider-free fakes only. Do not run Docker, model, network, benchmark, or promotion commands.

## Self-Review

- Spec coverage: Task 1 locks P4 identity and redacted trace while preserving old compatibility evidence; Task 2 admits only canonical completion data; Task 3 enforces lifecycle ordering, identity/cursor/generation binding, durability, and no replay; Task 4 proves fake full-chain behavior and isolates real bounded issuance behind authorization.
- Placeholder scan: no unspecified implementation, deferred work marker, or implicit error-handling instruction remains.
- Type consistency: Task 2 creates Task 1's trace; Task 3 exports the checkpoint/state consumed by Task 4; Task 4 consumes Task 2 completion and Task 1 verifier.
