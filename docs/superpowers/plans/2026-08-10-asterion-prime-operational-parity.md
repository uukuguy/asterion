# Asterion Prime Operational Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the six pinned Prime Gateway `operation.*` rows with provider-free, host-owned operational packages and exact, redacted real-Prime receipts.

**Architecture:** Add one closed sibling `asterion.operation/v1` protocol, then a host-owned journaled operation manager that accepts exactly one authority-bound transaction and delegates to six injected services. Each service is independent, has no provider authority, and returns a public-safe receipt; a single atomic Prime parity reducer promotes all six rows only when the complete six-receipt closure verifies. Existing `command.invoke` remains the client request path; the client stream adds only a generic `operation.receipted` event.

**Tech Stack:** Python 3.10+ standard library and `unittest`; JSON Schema; TypeScript/Node `>=22.8.0 <23`; existing Asterion control journal/client protocol and Prime Gateway; Make; locked real-Prime fixture harness.

## Global Constraints

- Prime evidence is pinned to `3th-party/prime-agent` commit `a18809e00ea30638584d87b3afea7285a9d7296c`; do not move the baseline or use a next build. The contract floor is Node `>=22.8.0 <23`; clean receipts record the exact Node runtime used without making it a protocol constraint.
- The six rows are exactly `operation.auth`, `operation.model-selection`, `operation.settings-keybindings`, `operation.telemetry-usage`, `operation.doctor`, and `operation.controlled-update-restart`; native rows remain `missing`.
- Preserve `asterion.agent-control/v1`, `asterion.agent-runtime/v1`, application-assembly, catalog, composer, runner, and existing one-shot CLI contracts unchanged. No alternate runner, composer, catalog, resolver, authorization source, retry loop, scheduler, or provider selection path is allowed.
- `asterion.operation/v1` is a closed, immutable, body-free sibling protocol. Python schema/validator/types and TypeScript schema/validator/types must accept and reject the same valid/invalid fixtures.
- Each feature request document (`auth`, `model-selection`, `settings-keybindings`, `telemetry-usage`, `doctor`, and `controlled-update-restart`) has its own closed schema, Python validator/type, TypeScript validator/type, and valid/invalid fixture pair. It is private input to its service and is never a public event/journal projection.
- Reuse `asterion.agent-client/v1` `command.invoke`; add only `operation.receipted`, with opaque receipt/evidence references, status/reason, operation ID, and effect counters. Never add feature-specific client events.
- Every transaction has an exact host-issued revisioned one-use authority, canonical idempotency key, expiry, feature ID, and opaque references only. Extend the canonical `AuthorityEnvelope`/`AuthorityLedger`; do not create a second authority store. For a reserved transaction, persist intent/admission/reservation/`dispatch-started`/`handoff-fenced` before external handoff and settle only after a durable terminal receipt. Pre-validation or authority-rejected terminal records have no reservation and are durable but non-settled. Retry identical work only; conflicting retry fails closed; uncertain handoffs require reconciliation and never become success by inference.
- Auth is private host storage/status/precedence with mocked OAuth refresh only. Model selection consumes an injected fixture catalog only. Settings/keybindings allow only typed, allowlisted nonsecret values; free/private strings are digest-only and preference is never authority. Telemetry is injected and network-disabled; a sink failure is observation-only. Doctor is read-only and cannot fix. Update/restart uses an injected deterministic fake coordinator only: no package manager, process replacement, or network.
- Public values, journal records, exceptions, stdout/stderr, receipts, fixtures, exported artifacts, and parity reports must redact `SENTINEL_SECRET`, `SENTINEL_TOKEN`, `SENTINEL_BODY`, private paths, OAuth/API-key values, provider payloads, and raw configuration text. Record counters for provider/model/network/credential/package-manager/process/upload effects; this plan requires all to be zero.
- Receipts prove only real-Prime provider-free functional reachability, preserved authority, stable identity, public redaction, and the named fault/recovery behavior. They do not prove live OAuth, model availability, telemetry delivery, package updates, system parity beyond the six rows, or native parity.

## Prerequisite

Before Task 1, the planner-owned commit containing this approved plan must exist on the implementation branch. Preserve the already-uncommitted `docs/status/JOURNAL.md` line; it is not part of this plan or its commit. Inspect `git status --short` before each task and stage only the files named by that task.

---

## Planned File Structure

| Path | Responsibility |
| --- | --- |
| `schemas/operation/v1/{operation-request-descriptor,operation-transaction,operation-receipt}.schema.json` | Closed portable descriptor, transaction, and receipt contract. |
| `src/asterion/operation/{protocol,manager,services}.py` | Immutable protocol, ControlHost extension, durable dispatch/recovery, and narrow injected-service interfaces. |
| `src/asterion/operation/{auth,model_selection,settings,telemetry,doctor,update_restart}.py` | Six independent host-owned operational service implementations. |
| `src/asterion/control/{authority,recovery,journal,manager}.py` | Canonical authority admission/reservation/settlement, ordered recovery bridge, and journal records; no changed control event semantics. |
| `src/asterion/client/{protocol,session,interactive,cli}.py` | One generic body-free receipt event and `command.invoke` projection/view/CLI access. |
| `packages/typescript/asterion-runtime/{src,test}` | Matching operation protocol types, validation, exports, copied-schema and fixture contract tests. |
| `packages/typescript/prime-gateway/src/{operation,main,private-store,index}.ts` | Private generic `operation.execute`/`operation.cancel`/`operation.reconcile` IPC adapter; no public credential/config body. |
| `src/asterion/control/providers/prime/{operation,operational_parity_testing,parity_testing}.py` | Prime bridge and all-or-nothing six-receipt reducer. |
| `tests/test_operation_*.py`, `tests/test_prime_operational_*.py` | TDD, fault, redaction, recovery, service, gateway, receipt, and parity tests. |
| `tests/fixtures/{operation,prime_gateway}/v1/*` and `packages/typescript/prime-gateway/resources/prime-operational-*` | Valid/invalid contract fixtures and locked real-Prime module/harness evidence. |

### Task 1: Define the closed shared operation protocol

**Files:**
- Create: `schemas/operation/v1/operation-request-descriptor.schema.json`, `schemas/operation/v1/operation-transaction.schema.json`, `schemas/operation/v1/operation-receipt.schema.json`
- Create: `src/asterion/operation/__init__.py`, `src/asterion/operation/protocol.py`
- Create: `tests/fixtures/operation/v1/{valid-request-descriptor,valid-transaction,valid-receipt,invalid-protocol-missing,invalid-identity-mismatch,invalid-recursive-forbidden-key,invalid-timestamp,invalid-unsafe-integer,invalid-nested-extra,invalid-canonical-array,invalid-transaction-secret,invalid-transaction-unknown,invalid-receipt-effect-counter}.json`
- Create: `tests/test_operation_protocol.py`
- Modify: `packages/typescript/asterion-runtime/src/{types,validation,index}.ts`, `packages/typescript/asterion-runtime/scripts/copy-schemas.mjs`, `packages/typescript/asterion-runtime/test/type-contract.ts`, `packages/typescript/asterion-runtime/test/runtime.test.mjs`, `pyproject.toml`, `tests/test_distribution.py`, `tools/check_promotion.py`

**Interfaces:** Produces `OPERATION_PROTOCOL = "asterion.operation/v1"`, immutable `OperationRequestDescriptor`, `OperationTransaction`, `OperationReceipt`, `OperationProtocolError`, `validate_operation_request_descriptor()`, `validate_operation_transaction()`, and `validate_operation_receipt()` in Python and TypeScript. `OperationRequestDescriptor` is the only request-body boundary: `{request_kind, request_ref, request_sha256, media_type, byte_count, purpose, client_id, session_id, generation, authority_revision}`. A transaction has `operation_id`, the descriptor, matching `session_id`/`client_id`/`generation`/`authority_revision`, `authority_id`, `idempotency_key`, `feature_id`, and `requested_at`; a receipt has matching identity, `status` (`succeeded|rejected|failed|cancelled|uncertain`), `reason_code`, opaque `receipt_ref`, optional opaque `reconciliation_ref`, canonical `effect_counts`, and `completed_at`.

- [ ] **Step 1: Write failing cross-language fixture and immutability tests**

```python
def test_transaction_and_receipt_are_closed_body_free_and_immutable(self) -> None:
    descriptor = OperationRequestDescriptor.from_mapping(_fixture("valid-request-descriptor.json"))
    transaction = OperationTransaction.from_mapping(_fixture("valid-transaction.json"))
    receipt = OperationReceipt.from_mapping(_fixture("valid-receipt.json"))
    self.assertEqual(transaction.protocol, "asterion.operation/v1")
    self.assertEqual(receipt.effect_counts["network_operations"], 0)
    self.assertEqual(transaction.request, descriptor)
    self.assertNotIn("SENTINEL_BODY", repr((transaction, receipt)))
    with self.assertRaises(OperationProtocolError):
        OperationTransaction.from_mapping(_fixture("invalid-transaction-secret.json"))
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_operation_protocol tests.test_distribution
npm --prefix packages/typescript/asterion-runtime test
```

Expected: FAIL because the operation protocol, schemas, fixtures, and TypeScript exports do not exist.

- [ ] **Step 3: Implement the exact values and validators**

```python
OPERATION_PROTOCOL = "asterion.operation/v1"
OPERATION_FEATURE_IDS = frozenset({
    "operation.auth", "operation.controlled-update-restart", "operation.doctor",
    "operation.model-selection", "operation.settings-keybindings", "operation.telemetry-usage",
})
EFFECT_COUNTERS = (
    "credential_value_reads", "provider_model_requests", "network_operations",
    "package_manager_operations", "os_process_restart_operations",
    "external_telemetry_deliveries", "uploads",
)

@dataclass(frozen=True, repr=False)
class OperationTransaction: ...

@dataclass(frozen=True, repr=False)
class OperationReceipt: ...
```

Require `additionalProperties: false` at every schema object; no array-bearing public fields (arrays fail closed); RFC3339 UTC timestamps; safe integers only (`0 <= n <= 9007199254740991`); positive revisions; 64-lower-hex request digest; opaque references; nonnegative counters; and exact descriptor/transaction/receipt identity and purpose retention. The prohibited external vector is exactly `EFFECT_COUNTERS` and is zero for every provider-free receipt. Scenario counters are separate: `scenario_calls`, `host_service_calls`, `mock_refresh_calls`, `injected_sink_calls`, `fake_coordinator_calls`, and `reconcile_calls`; only the feature-specific allowed counter may be nonzero and its expected value is fixed by the scenario. Metadata/digest describe and private-document resolution are not credential-value reads. Reject body-bearing field names recursively (`api_key`, `authorization`, `body`, `credential`, `destination`, `path`, `prompt`, `refresh_token`, `text`, `token`). Exercise every listed valid/invalid fixture in both Python and TypeScript, including missing protocol, identity mismatch, recursive forbidden keys, malformed timestamp, unsafe integer, nested additional property, and array rejection. Copy the schemas into the runtime package and implement equivalent TypeScript discriminated types and validators.

- [ ] **Step 4: Run both protocol gates twice and commit**

```bash
uv run python -m unittest -v tests.test_operation_protocol tests.test_distribution
npm --prefix packages/typescript/asterion-runtime test
uv run python -m unittest -v tests.test_operation_protocol tests.test_distribution
npm --prefix packages/typescript/asterion-runtime test
git add schemas/operation src/asterion/operation/protocol.py tests/fixtures/operation tests/test_operation_protocol.py packages/typescript/asterion-runtime pyproject.toml tests/test_distribution.py tools/check_promotion.py
git commit -m "feat: define closed operation protocol"
```

### Task 2: Extend canonical authority and ControlHost with durable operation recovery

**Files:**
- Create: `src/asterion/operation/manager.py`, `src/asterion/operation/services.py`
- Create: `tests/test_operation_manager.py`, `tests/test_operation_private_resolver.py`
- Modify: `src/asterion/control/authority.py`, `src/asterion/control/recovery.py`, `src/asterion/control/journal.py`, `src/asterion/control/manager.py`, `tests/test_control_authority.py`, `tests/test_control_recovery.py`, `tests/test_control_journal.py`, `tests/test_control_host.py`

**Interfaces:** Consumes Task 1. Produces canonical `OperationDecision` and `OperationSettlement` from `asterion.control.authority`, `OperationPrivateRequestResolver`, `OperationService`, and an injected domain-neutral `OperationManager` used only by `ControlHost.execute_operation()`. `AuthorityEnvelope.allowed_operations` accepts the six exact `operation.*` IDs; `AuthorityLedger` owns evaluate/admit/reserve/settle/replay. Journal records are `operation.transaction.accepted`, `operation.admitted`, `operation.reserved`, `operation.dispatch.started`, `operation.handoff.fenced`, `operation.receipted`, and `operation.reconciliation.recorded`; there is no `OperationAuthorityStore` and no parallel orchestrator.

- [ ] **Step 1: Write failing persist-before-effect/retry/recovery tests**

```python
async def test_identical_retry_reuses_receipt_and_conflict_never_calls_service(self) -> None:
    host, service, journal = _host_with_operation()
    first = await host.execute_operation(_transaction("op-1"))
    again = await host.execute_operation(_transaction("op-1"))
    self.assertEqual(first, again)
    self.assertEqual(service.execute_calls, ["op-1"])
    with self.assertRaises(OperationManagerError):
        await host.execute_operation(_transaction("op-1", request_ref="private-other"))
    self.assertEqual(service.execute_calls, ["op-1"])

async def test_restart_after_started_dispatch_is_uncertain_until_exact_reconcile(self) -> None:
    host, service, journal = _host_with_operation(fail_after="operation.dispatch.started")
    receipt = await host.execute_operation(_transaction("op-2"))
    self.assertEqual(receipt.status, "uncertain")
    recovered = ControlHost.recover_operation_host(journal, _envelope(), services={"operation.auth": service})
    self.assertEqual((await recovered.reconcile_operation(_transaction("op-2"))).status, "uncertain")

async def test_private_descriptor_rechecks_purpose_digest_revision_and_cancellation(self) -> None:
    host, _, _ = _host_with_operation()
    with self.assertRaises(ControlHostError) as raised:
        await host.execute_operation(_transaction("op-3", purpose="operation.auth.read", authority_revision=2))
    self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

async def test_reconcile_reuses_the_original_descriptor_purpose_for_one_second_read(self) -> None:
    host, resolver, private_store = _host_with_evictable_private_request()
    transaction = _transaction("op-4")
    await host.execute_operation(transaction)
    private_store.evict(transaction.operation_id)
    await host.reconcile_operation(transaction)
    self.assertEqual(resolver.purposes, [transaction.request.purpose, transaction.request.purpose])
    self.assertEqual(resolver.read_count, 2)
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_operation_manager tests.test_operation_private_resolver tests.test_control_authority tests.test_control_recovery tests.test_control_journal tests.test_control_host
```

Expected: FAIL because canonical authority operation decisions, private resolver, durable records, and ControlHost operation APIs are absent.

- [ ] **Step 3: Implement one-use authority and state machine**

```python
class OperationPrivateRequestResolver(Protocol):
    def resolve(self, descriptor: OperationRequestDescriptor, *, purpose: str, max_bytes: int, deadline_ms: int, authority_revision: int, cancelled: bool) -> bytes: ...

class OperationPrivateRequestStore(Protocol):
    def put(self, transaction: OperationTransaction, typed_request: object) -> str: ...
    def get_digest(self, transaction: OperationTransaction) -> str | None: ...

@dataclass(frozen=True)
class OperationReconciliationContext:
    operation_id: str
    authority_revision: int
    reconciliation_attempt: int

class OperationService(Protocol):
    feature_id: str
    request_kind: str
    request_purpose: str
    max_request_bytes: int
    async def execute(self, transaction: OperationTransaction, typed_request: object) -> OperationReceipt: ...
    async def cancel(self, transaction: OperationTransaction) -> OperationReceipt: ...
    async def reconcile(self, transaction: OperationTransaction, typed_request: object, context: OperationReconciliationContext) -> OperationReceipt: ...

class OperationManager:
    async def execute(self, transaction: OperationTransaction) -> OperationReceipt: ...
    async def cancel(self, operation_id: str, *, authority_revision: int) -> OperationReceipt: ...
    async def reconcile(self, transaction: OperationTransaction) -> OperationReceipt: ...
```

`ControlHost.execute_operation()` first performs protocol/identity/descriptor validation. Invalid syntax, unknown feature/request kind, malformed descriptor, stale session/generation, and client-intent conflict are pre-validation rejections: no authority evaluation or service call, and a fixed redacted `rejected` receipt is durable only after a valid transaction identity exists. A valid transaction then asks the existing `AuthorityLedger` to evaluate/admit/reserve; expired, cancelled, missing-grant, or budget/one-use conflict is an authority rejection with a durable `rejected` receipt and no external call. Services never admit, consume, reserve, or settle authority.

For admitted work, append/fsync the transaction, admission, reservation, `dispatch.started`, and `handoff.fenced` records in that order before the external service call. On first execute only, the manager resolves the descriptor once through the injected read-only resolver using the service-declared kind/purpose/maximum/deadline; it rechecks descriptor digest, byte count, media type, client/session/generation identity, stale revision, and cancellation both before and after read, parses the matching closed typed document, and stores only an encrypted/operator-owned private typed-request reference plus its digest. It then calls `service.execute(transaction, typed_request)`. Identical execute retries use the recorded receipt or private typed-request reference and never reread. Resolver failures are fixed redacted errors and never expose values.

Implement this globally ordered durable state table in `recover_control_host_state()` and `ControlHost`:

| Durable prefix at crash | Recovery action | Retry rule |
| --- | --- | --- |
| accepted, not admitted/reserved | rebuild transaction | identical retry may admit/reserve and continue; conflict rejects |
| admitted/reserved, not dispatch-started | retain reservation | recovery may perform the first dispatch exactly once |
| dispatch-started/handoff-fenced, no receipt | append/replay `uncertain` | reconcile only; never redispatch; authority remains reserved/unsettled |
| receipt, not client projection | replay durable receipt | re-project exactly one public client event |
| uncertain reconciliation | re-resolve only same descriptor/transaction/service when private typed value is unavailable | reuse `descriptor.purpose` exactly, pass `OperationReconciliationContext` separately, require exact current-authority/descriptor revalidation and same typed digest, then append monotonic terminal receipt plus settlement or retain `uncertain` |

For reconciliation, this plan deliberately re-resolves if the operator-owned private store no longer retains the typed request: it performs exactly one second read using the original `descriptor.purpose`, requires identical descriptor and typed-request digests, and keeps both request bytes and typed value out of public records/journal. The manager constructs `OperationReconciliationContext` separately and passes it only to `service.reconcile(transaction, typed_request, context)`; reconciliation context never changes the request purpose. Tests assert first execute read count `1`, identical execute retry read count `0`, retained-value reconciliation read count `0`, missing-private-value reconciliation read count `1`, the unchanged original purpose on both reads, and any mismatch read/call fails closed. Settle the AuthorityLedger only after a durable terminal `succeeded`, `rejected`, `failed`, or `cancelled` receipt for a reserved transaction; an `uncertain` receipt never settles or releases reservation. Reservation consumes the one-use ability; reservation/settlement are idempotent by operation ID and full transaction digest. The manager never reads configuration directly, calls a provider, performs network/process work, or treats a preference as authority.

- [ ] **Step 4: Run twice and commit**

```bash
uv run python -m unittest -v tests.test_operation_manager tests.test_operation_private_resolver tests.test_control_authority tests.test_control_recovery tests.test_control_journal tests.test_control_host
uv run python -m unittest -v tests.test_operation_manager tests.test_operation_private_resolver tests.test_control_authority tests.test_control_recovery tests.test_control_journal tests.test_control_host
git add src/asterion/operation/{manager,services}.py src/asterion/control/{authority,recovery,journal,manager}.py tests/test_operation_manager.py tests/test_operation_private_resolver.py tests/test_control_authority.py tests/test_control_recovery.py tests/test_control_journal.py tests/test_control_host.py
git commit -m "feat: journal ControlHost operations"
```

### Task 3: Implement private auth storage and status precedence

**Files:**
- Create: `schemas/operation/v1/auth-request.schema.json`, `src/asterion/operation/auth.py`, `tests/fixtures/operation/v1/{valid-auth-request,invalid-auth-request-secret}.json`, `tests/test_operation_auth.py`, `tests/test_prime_operational_auth.py`
- Modify: `src/asterion/operation/__init__.py`, `packages/typescript/asterion-runtime/src/{types,validation,index}.ts`, `packages/typescript/asterion-runtime/test/type-contract.ts`, `packages/typescript/asterion-runtime/test/runtime.test.mjs`, `Makefile`

**Interfaces:** Produces closed `auth-request` document validation, `AuthStorageBackend`, `OAuthRefresher`, `AuthOperationService`, and body-free `AuthStatus`. The typed private document accepts only `action`, opaque `credential_ref`/`refresh_ref`, `subject_digest`, and exact precedence; it is read through the Task 2 resolver and never appears in a public projection.

- [ ] **Step 1: Write failing precedence/redaction/mock-refresh tests**

```python
async def test_status_uses_exact_precedence_without_rendering_secret(self) -> None:
    service, effects = _auth_service(api_key="SENTINEL_SECRET", oauth="oauth-ref-1")
    receipt = await service.execute(_auth_transaction("auth-status-1"), _auth_request("auth.status"))
    self.assertEqual(receipt.status, "succeeded")
    self.assertEqual(effects.mock_refresh_calls, 0)
    self.assertNotIn("SENTINEL_SECRET", repr(receipt))

async def test_mock_refresh_is_injected_and_never_authorizes_model_work(self) -> None:
    service, effects = _auth_service(refresh_result="oauth-ref-2")
    await service.execute(_auth_transaction("auth-refresh-1"), _auth_request("auth.refresh"))
    self.assertEqual((effects.network_operations, effects.provider_model_requests), (0, 0))
    self.assertEqual(effects.mock_refresh_calls, 1)
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_operation_auth tests.test_prime_operational_auth
npm --prefix packages/typescript/asterion-runtime test
```

Expected: FAIL because the auth package and its Prime receipt test do not exist.

- [ ] **Step 3: Implement the minimal injected service**

```python
class AuthStorageBackend(Protocol):
    def put(self, credential_ref: str, *, subject_digest: str, precedence: int) -> str: ...
    def status(self) -> tuple[AuthStatus, ...]: ...
    def clear(self, credential_ref: str) -> None: ...

class OAuthRefresher(Protocol):
    async def refresh(self, refresh_ref: str) -> str: ...
```

Use the exact Prime candidates with stale filtering: runtime first; for Prime Inference, `runtime > environment > prime_cli > stored > fallback`; for other providers, `runtime > stored > environment > fallback`. Store only opaque refs and subject/value digests. Authority reservation is performed solely by Task 2 before `auth.store`; `auth.clear` remains idempotent. The optional refresher is a test-double boundary: it may return an opaque replacement ref but no real HTTP/token exchange code exists. All status fields are identifiers, candidate kind, stale/not-stale state, precedence, and digest; no key/token/provider payload is journaled or emitted.

- [ ] **Step 4: Run twice and commit**

```bash
uv run python -m unittest -v tests.test_operation_auth tests.test_prime_operational_auth
npm --prefix packages/typescript/asterion-runtime test
uv run python -m unittest -v tests.test_operation_auth tests.test_prime_operational_auth
npm --prefix packages/typescript/asterion-runtime test
git add schemas/operation/v1/auth-request.schema.json src/asterion/operation/{auth,__init__}.py tests/fixtures/operation/v1/{valid-auth-request,invalid-auth-request-secret}.json tests/test_operation_auth.py tests/test_prime_operational_auth.py packages/typescript/asterion-runtime/src/{types,validation,index}.ts packages/typescript/asterion-runtime/test/type-contract.ts packages/typescript/asterion-runtime/test/runtime.test.mjs packages/typescript/asterion-runtime/scripts/copy-schemas.mjs Makefile
git commit -m "feat: add host auth operation"
```

### Task 4: Implement exact fixture-catalog model selection

**Files:**
- Create: `schemas/operation/v1/model-selection-request.schema.json`, `src/asterion/operation/model_selection.py`, `tests/fixtures/operation/v1/{valid-model-selection-request,invalid-model-selection-request-extra}.json`, `tests/test_operation_model_selection.py`, `tests/test_prime_operational_model_selection.py`
- Modify: `src/asterion/operation/__init__.py`, `packages/typescript/asterion-runtime/src/{types,validation,index}.ts`, `packages/typescript/asterion-runtime/test/type-contract.ts`, `packages/typescript/asterion-runtime/test/runtime.test.mjs`, `Makefile`

**Interfaces:** Produces closed `model-selection-request` validation, `ModelCatalog`, `ModelSelection`, `ModelSelectionStore`, and `ModelSelectionOperationService` for `operation.model-selection`. The private typed document identifies an exact injected catalog version, model ID, thinking level, service tier, and transport ID; no raw body is projected.

- [ ] **Step 1: Write failing fixture-only/admission tests**

```python
async def test_selection_requires_exact_catalog_tuple_and_is_not_provider_discovery(self) -> None:
    service, catalog = _model_service()
    receipt = await service.execute(_model_transaction("model-1", model_id="fixture.model.small"), _model_selection_request("fixture.model.small"))
    self.assertEqual(receipt.status, "succeeded")
    self.assertEqual(catalog.lookup_calls, [("fixture-catalog-1", "fixture.model.small")])
    self.assertEqual(catalog.network_operations, 0)

async def test_unknown_model_or_stale_authority_rejects_before_mutation(self) -> None:
    service, store = _model_service()
    with self.assertRaises(OperationServiceError):
        await service.execute(_model_transaction("model-2", model_id="unknown.model"), _model_selection_request("unknown.model"))
    self.assertEqual(store.writes, [])
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_operation_model_selection tests.test_prime_operational_model_selection
npm --prefix packages/typescript/asterion-runtime test
```

Expected: FAIL because the fixture catalog and operation service are absent.

- [ ] **Step 3: Implement selection without discovery or authority escalation**

```python
@dataclass(frozen=True)
class ModelSelection:
    catalog_id: str; model_id: str; thinking_level: str; service_tier: str; transport_id: str

class ModelCatalog(Protocol):
    catalog_id: str
    def select(self, selection: ModelSelection) -> ModelSelection: ...
```

Require exact catalog ID and an allowlisted tuple from the injected fixture. Persist only selection identifiers and a canonical selection digest. Return `failed/model-selection-unavailable` for absence and do not fall back, infer credentials, construct a provider, make a model request, or mutate an existing runtime/session. The receipt has zero model/provider/network/credential counters.

- [ ] **Step 4: Run twice and commit**

```bash
uv run python -m unittest -v tests.test_operation_model_selection tests.test_prime_operational_model_selection
npm --prefix packages/typescript/asterion-runtime test
uv run python -m unittest -v tests.test_operation_model_selection tests.test_prime_operational_model_selection
npm --prefix packages/typescript/asterion-runtime test
git add schemas/operation/v1/model-selection-request.schema.json src/asterion/operation/{model_selection,__init__}.py tests/fixtures/operation/v1/{valid-model-selection-request,invalid-model-selection-request-extra}.json tests/test_operation_model_selection.py tests/test_prime_operational_model_selection.py packages/typescript/asterion-runtime/src/{types,validation,index}.ts packages/typescript/asterion-runtime/test/type-contract.ts packages/typescript/asterion-runtime/test/runtime.test.mjs packages/typescript/asterion-runtime/scripts/copy-schemas.mjs Makefile
git commit -m "feat: add fixture model selection"
```

### Task 5: Implement typed settings and keybindings as preference only

**Files:**
- Create: `schemas/operation/v1/settings-keybindings-request.schema.json`, `src/asterion/operation/settings.py`, `tests/fixtures/operation/v1/{valid-settings-keybindings-request,invalid-settings-keybindings-secret}.json`, `tests/test_operation_settings.py`, `tests/test_prime_operational_settings.py`
- Modify: `src/asterion/operation/__init__.py`, `packages/typescript/asterion-runtime/src/{types,validation,index}.ts`, `packages/typescript/asterion-runtime/test/type-contract.ts`, `packages/typescript/asterion-runtime/test/runtime.test.mjs`, `Makefile`

**Interfaces:** Produces closed `settings-keybindings-request` validation, `SettingsAllowlist`, `PreferenceRecord`, `KeybindingRecord`, `PreferenceStore`, and `SettingsOperationService` for `operation.settings-keybindings`. The typed private document supports exact `global` and `project` scope and returns only type/name/scope/value digest/revision in its receipt.

- [ ] **Step 1: Write failing scope/allowlist/no-authority tests**

```python
async def test_project_preference_overrides_global_but_cannot_admit_operation(self) -> None:
    service, store = _settings_service()
    await service.execute(_settings_transaction("settings-global", scope="global", key="theme", value="dark"), _settings_request("global", "theme", "dark"))
    await service.execute(_settings_transaction("settings-project", scope="project", key="theme", value="light"), _settings_request("project", "theme", "light"))
    self.assertEqual(store.resolve("theme", project_id="project-1").value, "light")
    self.assertFalse(store.resolve("theme", project_id="project-1").is_authority)

async def test_secret_key_free_text_and_unknown_key_are_rejected_without_leakage(self) -> None:
    with self.assertRaises(OperationServiceError) as raised:
        await _settings_service()[0].execute(_settings_transaction("bad", key="app.new_session", value="SENTINEL_SECRET"), _settings_request("global", "app.new_session", "SENTINEL_SECRET"))
    self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_operation_settings tests.test_prime_operational_settings
npm --prefix packages/typescript/asterion-runtime test
```

Expected: FAIL because typed settings/keybinding records are absent.

- [ ] **Step 3: Implement exact preference resolution**

```python
SettingsAllowlist = MappingProxyType({
    "theme": ("enum", ("dark", "light", "system")), "telemetry.enabled": ("boolean",),
    "app.session.new": ("key-chord",), "app.input.clear": ("key-chord",),
    "app.interrupt": ("key-chord",),
})
```

Accept only allowlisted booleans, bounded integers, enums, and validated key chords. Reject legacy aliases including `ui.theme`, `keybinding.command_palette`, `app.new_session`, and `app.cancel` before persistence. Global applies only where project has no exact value; project precedence does not create capability, authority, provider/model choice, command permission, or host-service access. If a future allowed value needs arbitrary text, accept an opaque private reference but journal/emit only its SHA-256 and byte count. Reject secret-shaped key names and any body-bearing fields before persistence.

- [ ] **Step 4: Run twice and commit**

```bash
uv run python -m unittest -v tests.test_operation_settings tests.test_prime_operational_settings
npm --prefix packages/typescript/asterion-runtime test
uv run python -m unittest -v tests.test_operation_settings tests.test_prime_operational_settings
npm --prefix packages/typescript/asterion-runtime test
git add schemas/operation/v1/settings-keybindings-request.schema.json src/asterion/operation/{settings,__init__}.py tests/fixtures/operation/v1/{valid-settings-keybindings-request,invalid-settings-keybindings-secret}.json tests/test_operation_settings.py tests/test_prime_operational_settings.py packages/typescript/asterion-runtime/src/{types,validation,index}.ts packages/typescript/asterion-runtime/test/type-contract.ts packages/typescript/asterion-runtime/test/runtime.test.mjs packages/typescript/asterion-runtime/scripts/copy-schemas.mjs Makefile
git commit -m "feat: add typed operational preferences"
```

### Task 6: Implement network-disabled telemetry and safe usage observation

**Files:**
- Create: `schemas/operation/v1/telemetry-usage-request.schema.json`, `src/asterion/operation/telemetry.py`, `tests/fixtures/operation/v1/{valid-telemetry-usage-request,invalid-telemetry-usage-request-body}.json`, `tests/test_operation_telemetry.py`, `tests/test_prime_operational_telemetry.py`
- Modify: `src/asterion/operation/__init__.py`, `packages/typescript/asterion-runtime/src/{types,validation,index}.ts`, `packages/typescript/asterion-runtime/test/type-contract.ts`, `packages/typescript/asterion-runtime/test/runtime.test.mjs`, `Makefile`

**Interfaces:** Produces closed `telemetry-usage-request` validation, `TelemetrySink`, `UsageSnapshot`, `TelemetryOperationService`, and public-safe `TelemetryObservation`. The only sink is injected; receipt fields contain source IDs, event names, counts, token/cost totals, result digest, and `delivery_status`.

- [ ] **Step 1: Write failing observation-only sink failure tests**

```python
async def test_sink_failure_is_observed_but_does_not_rewrite_completed_usage(self) -> None:
    service, journal = _telemetry_service(sink_error=RuntimeError("SENTINEL_TOKEN"))
    receipt = await service.execute(_telemetry_transaction("telemetry-1"), _telemetry_request())
    self.assertEqual((receipt.status, receipt.reason_code), ("succeeded", "telemetry-observation-failed"))
    self.assertEqual(receipt.effect_counts["external_telemetry_deliveries"], 0)
    self.assertEqual(service.effects.injected_sink_calls, 1)
    self.assertNotIn("SENTINEL_TOKEN", repr((receipt, journal.replay(JournalCursor(0)))))
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_operation_telemetry tests.test_prime_operational_telemetry
npm --prefix packages/typescript/asterion-runtime test
```

Expected: FAIL because telemetry service and safe observation receipt do not exist.

- [ ] **Step 3: Implement injected, offline observation**

```python
class TelemetrySink(Protocol):
    async def record(self, observation: TelemetryObservation) -> None: ...

@dataclass(frozen=True, repr=False)
class UsageSnapshot:
    aggregate_tokens: int; application_tokens: int; child_tokens: int; controller_tokens: int; cost_micros: int
```

Validate nonnegative usage totals and source attribution. Build an immutable metadata-only observation; do not import HTTP, environment, provider SDK, or file discovery. A sink exception records a redacted observation-failure entry and leaves the original operation result intact; the package receipt still proves the failure path. The prohibited external vector remains zero; `injected_sink_calls` is exactly one for a sink scenario and is distinct from `external_telemetry_deliveries`, which remains zero.

- [ ] **Step 4: Run twice and commit**

```bash
uv run python -m unittest -v tests.test_operation_telemetry tests.test_prime_operational_telemetry
npm --prefix packages/typescript/asterion-runtime test
uv run python -m unittest -v tests.test_operation_telemetry tests.test_prime_operational_telemetry
npm --prefix packages/typescript/asterion-runtime test
git add schemas/operation/v1/telemetry-usage-request.schema.json src/asterion/operation/{telemetry,__init__}.py tests/fixtures/operation/v1/{valid-telemetry-usage-request,invalid-telemetry-usage-request-body}.json tests/test_operation_telemetry.py tests/test_prime_operational_telemetry.py packages/typescript/asterion-runtime/src/{types,validation,index}.ts packages/typescript/asterion-runtime/test/type-contract.ts packages/typescript/asterion-runtime/test/runtime.test.mjs packages/typescript/asterion-runtime/scripts/copy-schemas.mjs Makefile
git commit -m "feat: add offline telemetry observation"
```

### Task 7: Implement read-only doctor diagnostics

**Files:**
- Create: `schemas/operation/v1/doctor-request.schema.json`, `src/asterion/operation/doctor.py`, `tests/fixtures/operation/v1/{valid-doctor-request,invalid-doctor-request-fix}.json`, `tests/test_operation_doctor.py`, `tests/test_prime_operational_doctor.py`
- Modify: `src/asterion/operation/__init__.py`, `packages/typescript/asterion-runtime/src/{types,validation,index}.ts`, `packages/typescript/asterion-runtime/test/type-contract.ts`, `packages/typescript/asterion-runtime/test/runtime.test.mjs`, `Makefile`

**Interfaces:** Produces closed `doctor-request` validation, `DoctorProbe`, `DiagnosticResult`, `DoctorOperationService`, and a `doctor.report` receipt descriptor. Probes receive no mutable host service and return only check ID/status/code/evidence digest.

- [ ] **Step 1: Write failing no-fix/redaction/read-only tests**

```python
async def test_doctor_reports_failed_probe_without_fix_or_private_value(self) -> None:
    service, probe = _doctor_service(result=DiagnosticResult.failed("storage.private", "not-ready", "SENTINEL_BODY"))
    receipt = await service.execute(_doctor_transaction("doctor-1"), _doctor_request())
    self.assertEqual((receipt.status, receipt.reason_code), ("succeeded", "doctor-report-ready"))
    self.assertEqual(probe.mutation_calls, 0)
    self.assertNotIn("SENTINEL_BODY", repr(receipt))
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_operation_doctor tests.test_prime_operational_doctor
npm --prefix packages/typescript/asterion-runtime test
```

Expected: FAIL because doctor probes and report reduction are absent.

- [ ] **Step 3: Implement deterministic probe reduction**

```python
class DoctorProbe(Protocol):
    check_id: str
    def inspect(self) -> DiagnosticResult: ...

def reduce_diagnostics(results: tuple[DiagnosticResult, ...]) -> DoctorReport: ...
```

Sort unique probe IDs, reject duplicates/noncanonical results, and report pass/warn/fail with stable reason codes and digests. Invoke `inspect()` only; no probe has a `fix`, write, refresh, install, restart, provider, or network method. Treat probe exceptions as one redacted failed result. The operation succeeds when it produces a complete report, even if checks fail; diagnostic failure is not evidence of repair.

- [ ] **Step 4: Run twice and commit**

```bash
uv run python -m unittest -v tests.test_operation_doctor tests.test_prime_operational_doctor
npm --prefix packages/typescript/asterion-runtime test
uv run python -m unittest -v tests.test_operation_doctor tests.test_prime_operational_doctor
npm --prefix packages/typescript/asterion-runtime test
git add schemas/operation/v1/doctor-request.schema.json src/asterion/operation/{doctor,__init__}.py tests/fixtures/operation/v1/{valid-doctor-request,invalid-doctor-request-fix}.json tests/test_operation_doctor.py tests/test_prime_operational_doctor.py packages/typescript/asterion-runtime/src/{types,validation,index}.ts packages/typescript/asterion-runtime/test/type-contract.ts packages/typescript/asterion-runtime/test/runtime.test.mjs packages/typescript/asterion-runtime/scripts/copy-schemas.mjs Makefile
git commit -m "feat: add read only doctor operation"
```

### Task 8: Implement controlled update/restart through a deterministic coordinator

**Files:**
- Create: `schemas/operation/v1/controlled-update-restart-request.schema.json`, `src/asterion/operation/update_restart.py`, `tests/fixtures/operation/v1/{valid-controlled-update-restart-request,invalid-controlled-update-restart-request-path}.json`, `tests/test_operation_update_restart.py`, `tests/test_prime_operational_update_restart.py`
- Modify: `src/asterion/operation/__init__.py`, `packages/typescript/asterion-runtime/src/{types,validation,index}.ts`, `packages/typescript/asterion-runtime/test/type-contract.ts`, `packages/typescript/asterion-runtime/test/runtime.test.mjs`, `Makefile`

**Interfaces:** Produces closed `controlled-update-restart-request` validation, `ArtifactIdentity`, `RestartCapsule`, `UpdateRestartCoordinator`, and `UpdateRestartOperationService` for `operation.controlled-update-restart`. The coordinator API is `verify_next()`, `seal_checkpoint()`, `handoff()`, `reconcile()`, and `cancel()`; production composition supplies no live package-manager implementation in this phase.

- [ ] **Step 1: Write failing checkpoint/fencing/uncertainty tests**

```python
async def test_verified_next_identity_seals_checkpoint_then_handoffs_once(self) -> None:
    service, coordinator = _restart_service()
    receipt = await service.execute(_restart_transaction("restart-1"), _restart_request())
    self.assertEqual(receipt.status, "succeeded")
    self.assertEqual(coordinator.calls, ["verify_next", "seal_checkpoint", "handoff"])
    self.assertEqual(receipt.effect_counts["package_manager_operations"], 0)

async def test_handoff_disconnect_is_uncertain_until_same_capsule_reconciles(self) -> None:
    service, coordinator = _restart_service(disconnect_after_handoff=True)
    first = await service.execute(_restart_transaction("restart-2"), _restart_request())
    self.assertEqual(first.status, "uncertain")
    context = OperationReconciliationContext("restart-2", authority_revision=1, reconciliation_attempt=1)
    self.assertEqual((await service.reconcile(_restart_transaction("restart-2"), _restart_request(), context)).status, "succeeded")
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_operation_update_restart tests.test_prime_operational_update_restart
npm --prefix packages/typescript/asterion-runtime test
```

Expected: FAIL because controlled coordinator and capsule contracts are absent.

- [ ] **Step 3: Implement exact fake-coordinator sequence**

```python
class UpdateRestartCoordinator(Protocol):
    async def verify_next(self, expected: ArtifactIdentity) -> ArtifactIdentity: ...
    async def seal_checkpoint(self, capsule: RestartCapsule) -> str: ...
    async def handoff(self, capsule: RestartCapsule) -> str: ...
    async def reconcile(self, operation_id: str, capsule_digest: str) -> str | None: ...
    async def cancel(self, operation_id: str) -> str: ...
```

Require exact current/next artifact ID, daemon ID, protocol compatibility ID, checkpoint reference, and capsule digest before handoff. Journal checkpoint seal and fence before `handoff`; reject an unexpected daemon/capsule/result identity. A disconnect after handoff returns `uncertain` and stores no success claim. Reconcile accepts only the exact operation/capsule/next-artifact tuple. Do not invoke package managers, `exec`, network, process spawning, or daemon restart in this phase; all relevant counters remain zero.

- [ ] **Step 4: Run twice and commit**

```bash
uv run python -m unittest -v tests.test_operation_update_restart tests.test_prime_operational_update_restart
npm --prefix packages/typescript/asterion-runtime test
uv run python -m unittest -v tests.test_operation_update_restart tests.test_prime_operational_update_restart
npm --prefix packages/typescript/asterion-runtime test
git add schemas/operation/v1/controlled-update-restart-request.schema.json src/asterion/operation/{update_restart,__init__}.py tests/fixtures/operation/v1/{valid-controlled-update-restart-request,invalid-controlled-update-restart-request-path}.json tests/test_operation_update_restart.py tests/test_prime_operational_update_restart.py packages/typescript/asterion-runtime/src/{types,validation,index}.ts packages/typescript/asterion-runtime/test/type-contract.ts packages/typescript/asterion-runtime/test/runtime.test.mjs packages/typescript/asterion-runtime/scripts/copy-schemas.mjs Makefile
git commit -m "feat: add controlled restart operation"
```

### Task 9: Add generic Prime private operation IPC and Python bridge

**Files:**
- Create: `packages/typescript/prime-gateway/src/operation.ts`, `packages/typescript/prime-gateway/test/operation.test.mjs`, `src/asterion/control/providers/prime/operation.py`, `tests/test_prime_operation_bridge.py`
- Modify: `packages/typescript/prime-gateway/src/{main,private-store,index}.ts`, `packages/typescript/prime-gateway/test/{main.test.mjs,private-store.test.mjs}`, `src/asterion/control/providers/prime/{client,factory}.py`, `tests/test_prime_control_factory.py`

**Interfaces:** Consumes Tasks 1–8. Produces private IPC envelope types `operation.execute`, `operation.cancel`, and `operation.reconcile`, private result `operation.receipt`, `PrimeOperationClient.execute()/.cancel()/.reconcile()`, and the exact factory capability `operations-v1`. The IPC accepts/returns only validated operation protocol mappings and opaque private-reference descriptors.

- [ ] **Step 1: Write failing IPC/body isolation/fence tests**

```typescript
test("operation IPC stores private input and returns one redacted receipt", async () => {
  const result = await sidecar.handle({ protocol: IPC, id: "op-1", type: "operation.execute", transaction });
  assert.equal(result.type, "operation.receipt");
  assert.equal(JSON.stringify(result).includes("SENTINEL_SECRET"), false);
  assert.equal(result.receipt.effect_counts.network_operations, 0);
});
```

```python
async def test_gateway_rejects_identity_conflict_without_reinvoking_private_operation(self) -> None:
    client = _client()
    first = await client.execute(_transaction("op-1"))
    with self.assertRaises(PrimeOperationError):
        await client.execute(_transaction("op-1", request_ref="private-conflict"))
    self.assertEqual(first.status, "succeeded")

async def test_gateway_reconciles_only_exact_uncertain_transaction(self) -> None:
    client = _uncertain_client()
    receipt = await client.reconcile(_transaction("op-uncertain"))
    self.assertEqual(receipt.status, "succeeded")
    with self.assertRaises(PrimeOperationError):
        await client.reconcile(_transaction("op-uncertain", request_ref="private-conflict"))
```

- [ ] **Step 2: Run RED**

```bash
npm --prefix packages/typescript/prime-gateway test -- test/operation.test.mjs test/main.test.mjs test/private-store.test.mjs
uv run python -m unittest -v tests.test_prime_operation_bridge tests.test_prime_control_factory
```

Expected: FAIL because operation IPC and the Prime bridge do not exist.

- [ ] **Step 3: Implement generic private envelope handling**

```typescript
export type OperationEnvelope =
  | { readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL; readonly id: string; readonly type: "operation.execute"; readonly transaction: OperationTransaction; readonly private: Readonly<Record<string, never>> }
  | { readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL; readonly id: string; readonly type: "operation.cancel"; readonly operation_id: string; readonly authority_revision: number; readonly private: Readonly<Record<string, never>> }
  | { readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL; readonly id: string; readonly type: "operation.reconcile"; readonly transaction: OperationTransaction; readonly private: Readonly<Record<string, never>> };
```

Validate exact keys and the copied `asterion.operation/v1` schema before dispatch. `operation.execute` serializes by operation ID/digest, persists no unredacted input, and returns a validated receipt; cancellation uses exact ID/revision. `operation.reconcile` requires the exact prior transaction digest and may only reconcile a fenced uncertain record; it cannot redispatch. Map all sidecar/transport failures to fixed redacted errors, preserve durable duplicate behavior, and expose no feature-specific Prime endpoint, live auth/model/update behavior, or raw configuration.

- [ ] **Step 4: Bind the Python service adapter, run twice, and commit**

```bash
npm --prefix packages/typescript/prime-gateway test -- test/operation.test.mjs test/main.test.mjs test/private-store.test.mjs
uv run python -m unittest -v tests.test_prime_operation_bridge tests.test_prime_control_factory
npm --prefix packages/typescript/prime-gateway test -- test/operation.test.mjs test/main.test.mjs test/private-store.test.mjs
uv run python -m unittest -v tests.test_prime_operation_bridge tests.test_prime_control_factory
git add packages/typescript/prime-gateway/src/{operation,main,private-store,index}.ts packages/typescript/prime-gateway/test/{operation.test.mjs,main.test.mjs,private-store.test.mjs} src/asterion/control/providers/prime/{operation,client,factory}.py tests/test_prime_operation_bridge.py tests/test_prime_control_factory.py
git commit -m "feat: bridge private Prime operations"
```

### Task 10: Project the one generic operation receipt through existing clients

**Files:**
- Modify: `src/asterion/client/{private,protocol,session,interactive,cli,__init__}.py`, `tests/test_agent_client_protocol.py`, `tests/test_client_session.py`, `tests/test_client_interactive.py`, `tests/test_asterion_cli.py`
- Modify: `packages/typescript/asterion-runtime/src/{types,validation,index}.ts`, `packages/typescript/asterion-runtime/test/type-contract.ts`, `packages/typescript/asterion-runtime/test/runtime.test.mjs`
- Create: `tests/test_client_operations.py`

**Interfaces:** Adds `operation.receipted` to `CLIENT_EVENT_TYPES` with payload exactly `{operation_id, feature_id, status, reason_code, receipt_ref, effect_counts}`. `HostClientSessionEndpoint` receives a narrow `OperationCommandDispatcher`, implemented by `ControlHost.execute_operation()`, immutable `OperationCommandRegistry`, and metadata-only `OperationPrivateRequestDescriber`; `ClientViewState` retains generic operation receipts and CLI JSON/text displays only their safe metadata.

- [ ] **Step 1: Write failing generic-event and command-routing tests**

```python
async def test_command_invoke_projects_one_generic_operation_receipt(self) -> None:
    endpoint = _operation_endpoint()
    await endpoint.submit(_command_intent(command_name="operation.auth"))
    events = [event async for event in endpoint.events()]
    self.assertEqual(events[-1].type, "operation.receipted")
    self.assertEqual(set(events[-1].payload), {"effect_counts", "feature_id", "operation_id", "reason_code", "receipt_ref", "status"})
    self.assertNotIn("SENTINEL_SECRET", repr(events[-1]))

async def test_unknown_stale_or_conflicting_command_cannot_select_service_or_dispatch_control(self) -> None:
    self.assertEqual(_operation_endpoint().command_registry.names, (
        "operation.auth", "operation.controlled-update-restart", "operation.doctor",
        "operation.model-selection", "operation.settings-keybindings", "operation.telemetry-usage",
    ))
    with self.assertRaises(ClientSessionError):
        _operation_endpoint().command_registry.invoke("operation.auth.hidden")
    with self.assertRaises(ClientSessionError):
        await _operation_endpoint(authority_revision=2).submit(_command_intent(authority_revision=1))
    with self.assertRaises(ClientSessionError):
        await _operation_endpoint().submit(_command_intent(intent_id="same", arguments_ref="private-conflict"))

async def test_describe_rejects_hostile_metadata_before_body_resolution(self) -> None:
    endpoint = _operation_endpoint(describe_result=_descriptor_metadata(media_type="text/plain", size=999999))
    with self.assertRaises(ClientSessionError):
        await endpoint.submit(_command_intent(command_name="operation.auth"))
    self.assertEqual(endpoint.private_values.read_calls, [])
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_agent_client_protocol tests.test_client_session tests.test_client_interactive tests.test_client_operations tests.test_asterion_cli
npm --prefix packages/typescript/asterion-runtime test
```

Expected: FAIL because the client event, command bridge, and generic view state are absent.

- [ ] **Step 3: Add the one public projection without changing control/runtime contracts**

```python
CLIENT_EVENT_PAYLOAD_FIELDS["operation.receipted"] = (
    "effect_counts", "feature_id", "operation_id", "reason_code", "receipt_ref", "status",
)

@dataclass(frozen=True)
class OperationCommandBinding:
    command_name: str; feature_id: str; request_kind: str; request_purpose: str
    accepted_media_type: str; max_request_bytes: int; deadline_ms: int

class OperationCommandRegistry(Protocol):
    @property
    def names(self) -> tuple[str, ...]: ...
    def resolve(self, command_name: str, *, revision: int) -> OperationCommandBinding: ...

class OperationCommandDispatcher(Protocol):
    async def execute_operation(self, transaction: OperationTransaction) -> OperationReceipt: ...

@dataclass(frozen=True, repr=False)
class OperationPrivateRequestMetadata:
    request_ref: str; request_sha256: str; media_type: str; byte_count: int
    client_id: str; session_id: str; generation: int; authority_revision: int

class OperationPrivateRequestDescriber(Protocol):
    def describe_operation_request(self, request_ref: str, *, client_id: str, session_id: str, generation: int, authority_revision: int) -> OperationPrivateRequestMetadata: ...
```

The registry accepts exactly six client command names: `operation.auth`, `operation.model-selection`, `operation.settings-keybindings`, `operation.telemetry-usage`, `operation.doctor`, and `operation.controlled-update-restart`; each is one immutable binding with feature ID, request kind, request purpose, accepted media type, byte limit, and deadline. For `command.invoke`, validate exact client ID, session ID, generation, authority revision, command revision, full-intent SHA-256 idempotency digest, and this binding. Call the metadata-only describer for `arguments_ref`; it returns only SHA-256, media type, byte count, generation, and identity. Reject hostile describe result, mismatched identity/purpose/media/size/digest, stale revision, or cancellation before constructing `OperationRequestDescriptor`; it never reads request bytes. The descriptor then carries binding purpose and all verified metadata. Only Task 2's resolver reads body bytes with the selected purpose/limit/deadline. Call only the injected dispatcher (`ControlHost.execute_operation()`), never `ControlHost.dispatch()` or a provider command. Generic `operation.execute` remains private IPC only. Validate and journal one `operation.receipted` public client event for every durable `OperationReceipt`, including `uncertain`: it is observable to clients but non-settled/nonterminal for authority. An exact later reconciled terminal receipt has the same operation identity and follows the uncertain event monotonically; it produces one later `operation.receipted` event. JSON emits validated public events; text renders status/feature/reason/counters only. Existing client SDK/RPC/ACP/TUI/export behavior and one-shot CLI remain unchanged.

- [ ] **Step 4: Run twice and commit**

```bash
uv run python -m unittest -v tests.test_agent_client_protocol tests.test_client_session tests.test_client_interactive tests.test_client_operations tests.test_asterion_cli
npm --prefix packages/typescript/asterion-runtime test
uv run python -m unittest -v tests.test_agent_client_protocol tests.test_client_session tests.test_client_interactive tests.test_client_operations tests.test_asterion_cli
npm --prefix packages/typescript/asterion-runtime test
git add src/asterion/client packages/typescript/asterion-runtime/src packages/typescript/asterion-runtime/test tests/test_agent_client_protocol.py tests/test_client_session.py tests/test_client_interactive.py tests/test_client_operations.py tests/test_asterion_cli.py
git commit -m "feat: project generic operation receipts"
```

### Task 11: Build locked real-Prime operational harness infrastructure

**Files:**
- Create: `packages/typescript/prime-gateway/resources/{prime-operational-module.mjs,prime-operational-module-lock.json}`, `packages/typescript/prime-gateway/test/operational-interface.test.mjs`, `tests/fixtures/prime_gateway/v1/real-prime-operations.mjs`, `tests/test_prime_operational_harness.py`
- Modify: `packages/typescript/prime-gateway/{package.json,src/gateway.ts,test/main.test.mjs}`, `Makefile`

**Interfaces:** Produces a repository-resource harness API and lock verifier for later six package gates. The lock records source and built-distribution anchors, source commit, built workspace digest, module digest, dependency lock digest, and actual Node runtime. It locks `core/auth-storage.ts: AuthStorage`; `core/agent-session.ts: setModel/setServiceTier/setThinkingLevel`; `core/settings-manager.ts: SettingsManager`; `core/keybindings.ts: KeybindingsManager`; `core/telemetry.ts: TelemetryClient`; `core/usage.ts: emptyUsage`; `core/diagnostics.ts: ResourceDiagnostic`; and `package-manager-cli.ts: resolveUpdateDaemonSocketPath`, `prepareDaemonUpdateRestart`, and `runDaemonUpdateRestartCoordinator`, plus corresponding `dist/**/*.js` artifacts.

- [ ] **Step 1: Make every operational gate require an absent real harness**

```python
def test_harness_rejects_source_or_built_distribution_anchor_drift(self) -> None:
    locks = verify_operational_locks(_external_pinned_root(), _resource_root())
    self.assertIn("dist/core/auth-storage.js", locks.built_anchor_digests)
    with self.assertRaises(OperationalHarnessError):
        verify_operational_locks(_drifted_pinned_root(), _resource_root())
```

- [ ] **Step 2: Run the infrastructure RED gate**

```bash
npm --prefix packages/typescript/prime-gateway test -- test/operational-interface.test.mjs test/main.test.mjs
uv run python -m unittest -v tests.test_prime_operational_harness
```

Expected: FAIL because repository-resource harness, source/built anchor lock, and effect hooks are absent.

- [ ] **Step 3: Implement the locked repository-resource harness and effect hooks**

```javascript
export async function runOperationalPackage(frame) {
  const locks = await verifyOperationalLocks(frame.sourceRoot, frame.resourceRoot);
  return runWithDeterministicEffects(frame.package, locks, frame.failureCase ?? null);
}
```

Run the repository resource only against a temporary external pinned Prime root, never by importing the repository checkout. Rebuild locked workspaces under Node `>=22.8.0 <23`, record the exact Node runtime in later receipts, and verify source and `dist` anchor digests before importing. Install effect hooks for the prohibited external vector and separate scenario counters: `scenario_calls`, `host_service_calls`, `mock_refresh_calls`, `injected_sink_calls`, `fake_coordinator_calls`, and `reconcile_calls`. Metadata/digest lookup and typed private-document resolution are not credential-value reads. This task creates infrastructure only; Tasks 12–13 supply the six individual receipts.

- [ ] **Step 4: Run infrastructure twice and commit**

```bash
npm --prefix packages/typescript/prime-gateway test -- test/operational-interface.test.mjs test/main.test.mjs
uv run python -m unittest -v tests.test_prime_operation_bridge tests.test_prime_operational_harness
npm --prefix packages/typescript/prime-gateway test -- test/operational-interface.test.mjs test/main.test.mjs
uv run python -m unittest -v tests.test_prime_operation_bridge tests.test_prime_operational_harness
git add packages/typescript/prime-gateway/resources/{prime-operational-module.mjs,prime-operational-module-lock.json} packages/typescript/prime-gateway/test/operational-interface.test.mjs packages/typescript/prime-gateway/{package.json,src/gateway.ts,test/main.test.mjs} tests/fixtures/prime_gateway/v1/real-prime-operations.mjs tests/test_prime_operational_harness.py Makefile
git commit -m "test: lock Prime operation harness"
```

### Task 12: Prove locked auth, model-selection, and settings/keybindings receipts

**Files:**
- Modify: `tests/test_prime_operational_{auth,model_selection,settings}.py`, `tests/fixtures/prime_gateway/v1/real-prime-operations.mjs`, `packages/typescript/prime-gateway/test/operational-interface.test.mjs`, `Makefile`

**Interfaces:** Produces exactly three receipts: `auth`, `model-selection`, and `settings-keybindings`. Each has one feature/scenario, source+dist lock identities, complete prohibited external vector set to zero, `scenario_calls=1`, `host_service_calls=1`, and only `mock_refresh_calls=1` in the explicit mocked-auth-refresh scenario.

- [ ] **Step 1: Write failing receipt/failure-matrix tests**

```python
def test_auth_model_settings_receipts_have_exact_allowed_scenario_counters(self) -> None:
    auth, model, settings = (_real_prime_receipt(name) for name in ("auth", "model-selection", "settings-keybindings"))
    self.assertEqual(auth["scenario_counts"]["mock_refresh_calls"], 1)
    self.assertEqual(model["scenario_counts"], _base_scenario_counts())
    self.assertEqual(settings["scenario_counts"], _base_scenario_counts())
    self.assertEqual(settings["effect_counts"], _zero_effect_counts())
```

- [ ] **Step 2: Run RED**

```bash
make test.prime-operational-auth.provider-free
make test.prime-operational-model-selection.provider-free
make test.prime-operational-settings-keybindings.provider-free
```

Expected: FAIL because the three package receipts and their actual failure matrices are absent.

- [ ] **Step 3: Implement three exact receipt scenarios**

The auth receipt proves runtime-first and stale filtered Prime Inference `runtime > environment > prime_cli > stored > fallback`, non-Prime `runtime > stored > environment > fallback`, and a mocked refresh failure/success with private values redacted. The model receipt proves an exact fixture-catalog tuple transition; it makes no provider/model request. The settings receipt proves `theme`, `telemetry.enabled`, `app.session.new`, `app.input.clear`, and `app.interrupt`, plus legacy-alias rejection. Every receipt records `restart-after-admission`, all four ledger assertions, `redaction_status="pass"`, zero prohibited external counts, and only its explicitly allowed scenario count.

- [ ] **Step 4: Run twice and commit**

```bash
make test.prime-operational-auth.provider-free && make test.prime-operational-model-selection.provider-free && make test.prime-operational-settings-keybindings.provider-free
make test.prime-operational-auth.provider-free && make test.prime-operational-model-selection.provider-free && make test.prime-operational-settings-keybindings.provider-free
git add tests/test_prime_operational_{auth,model_selection,settings}.py tests/fixtures/prime_gateway/v1/real-prime-operations.mjs packages/typescript/prime-gateway/test/operational-interface.test.mjs Makefile
git commit -m "test: prove Prime auth model settings"
```

### Task 13: Prove locked telemetry, doctor, and controlled-update/restart receipts

**Files:**
- Modify: `tests/test_prime_operational_{telemetry,doctor,update_restart}.py`, `tests/fixtures/prime_gateway/v1/real-prime-operations.mjs`, `packages/typescript/prime-gateway/test/operational-interface.test.mjs`, `Makefile`

**Interfaces:** Produces exactly three receipts: `telemetry-usage`, `doctor`, and `controlled-update-restart`. Each has one feature/scenario, source+dist lock identities, zero prohibited external vector, `scenario_calls=1`, and `host_service_calls=1`; only the telemetry sink, fake coordinator, and exact reconciliation scenarios may increment their named allowed scenario counters.

- [ ] **Step 1: Write failing receipt/failure-matrix tests**

```python
def test_telemetry_doctor_restart_receipts_keep_external_vector_zero(self) -> None:
    telemetry, doctor, restart = (_real_prime_receipt(name) for name in ("telemetry-usage", "doctor", "controlled-update-restart"))
    self.assertEqual(telemetry["scenario_counts"]["injected_sink_calls"], 1)
    self.assertEqual(doctor["scenario_counts"], _base_scenario_counts())
    self.assertEqual((restart["scenario_counts"]["fake_coordinator_calls"], restart["scenario_counts"]["reconcile_calls"]), (1, 1))
    self.assertEqual(restart["effect_counts"], _zero_effect_counts())
```

- [ ] **Step 2: Run RED**

```bash
make test.prime-operational-telemetry-usage.provider-free
make test.prime-operational-doctor.provider-free
make test.prime-operational-controlled-update-restart.provider-free
```

Expected: FAIL because the three package receipts and their actual failure matrices are absent.

- [ ] **Step 3: Implement three exact receipt scenarios**

The telemetry receipt uses a network-disabled injected sink and proves sink failure is observation-only. The doctor receipt proves a read-only diagnostic failure with no fix. The restart receipt exercises the locked `prepareDaemonUpdateRestart` and `runDaemonUpdateRestartCoordinator` anchors, exact fake-coordinator handoff disconnect, and one exact reconciliation. Every receipt records `restart-after-admission`, all four ledger assertions, `redaction_status="pass"`, zero prohibited external counts, and only its explicitly allowed scenario count.

- [ ] **Step 4: Run twice and commit**

```bash
make test.prime-operational-telemetry-usage.provider-free && make test.prime-operational-doctor.provider-free && make test.prime-operational-controlled-update-restart.provider-free
make test.prime-operational-telemetry-usage.provider-free && make test.prime-operational-doctor.provider-free && make test.prime-operational-controlled-update-restart.provider-free
git add tests/test_prime_operational_{telemetry,doctor,update_restart}.py tests/fixtures/prime_gateway/v1/real-prime-operations.mjs packages/typescript/prime-gateway/test/operational-interface.test.mjs Makefile
git commit -m "test: prove Prime telemetry doctor restart"
```

### Task 14: Reduce six receipts atomically and promote only six ledger rows

**Files:**
- Create: `src/asterion/control/providers/prime/operational_parity_testing.py`, `tests/test_prime_operational_parity.py`
- Modify: `src/asterion/control/providers/prime/parity_testing.py`, `tests/test_prime_parity_ledger.py`, `tests/test_check_prime_parity.py`, `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`, `Makefile`

**Interfaces:** Produces `PRIME_OPERATION_FEATURES`, `build_prime_operational_observations(receipts)`, and exactly six Prime Gateway observations. The reducer takes one immutable mapping of all six package receipts and has no API that mutates a partial ledger.

- [ ] **Step 1: Write failing closure/reducer tests**

```python
PRIME_OPERATION_FEATURES = MappingProxyType({
    "auth": ("operation.auth",), "model-selection": ("operation.model-selection",),
    "settings-keybindings": ("operation.settings-keybindings",), "telemetry-usage": ("operation.telemetry-usage",),
    "doctor": ("operation.doctor",), "controlled-update-restart": ("operation.controlled-update-restart",),
})

def test_atomic_reducer_rejects_missing_extra_or_dirty_receipts(self) -> None:
    for receipts in (_five_valid_receipts(), _seven_receipts(), _nonzero_network_receipts(), _built_anchor_drift_receipts()):
        with self.subTest(receipts=type(receipts).__name__), self.assertRaises(PrimeOperationalParityError):
            build_prime_operational_observations(receipts)
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_prime_operational_parity tests.test_prime_parity_ledger tests.test_check_prime_parity
uv run python tools/check_prime_parity.py --features operation.auth,operation.model-selection,operation.settings-keybindings,operation.telemetry-usage,operation.doctor,operation.controlled-update-restart --provider asterion.prime-gateway
```

Expected: FAIL because the atomic reducer is absent; the exact checker remains BLOCKED with six `result-missing` rows.

- [ ] **Step 3: Implement all-or-nothing validation and narrow promotion**

```python
def build_prime_operational_observations(
    receipts: Mapping[str, Mapping[str, object]],
) -> tuple[PrimeParityObservation, ...]:
    _require_exact_six_receipts(receipts)
    validated = tuple(_validate_operational_receipt(name, receipts[name]) for name in sorted(receipts))
    return tuple(_observation(item) for item in validated)
```

Reject missing/extra package, duplicate feature/scenario, source/built-distribution/module/artifact/anchor lock drift, unsupported Node runtime, prohibited external count other than zero, scenario count outside its package-specific expectation, body sentinel, noncanonical arrays, missing `restart-after-admission` or one of the four ledger assertions, and nonterminal or unreconciled uncertain outcome. An `uncertain` receipt alone is observable evidence but never PASS evidence: the reducer requires the exact same-operation reconciled terminal receipt and its monotonic transition. Change all six Prime Gateway rows only when the one complete tuple validates; native rows remain `missing`. Together with the existing H-035 nine rows, `interfaces.operations` then reports PASS at exactly `15/15`. The exact six-feature checker reports selected `6`, passed `6`, blocking `0`; `Verified-system-parity` remains BLOCKED on all other mandatory rows.

- [ ] **Step 4: Run twice and commit**

```bash
uv run python -m unittest -v tests.test_prime_operational_parity tests.test_prime_parity_ledger tests.test_check_prime_parity
uv run python tools/check_prime_parity.py --features operation.auth,operation.model-selection,operation.settings-keybindings,operation.telemetry-usage,operation.doctor,operation.controlled-update-restart --provider asterion.prime-gateway
uv run python -m unittest -v tests.test_prime_operational_parity tests.test_prime_parity_ledger tests.test_check_prime_parity
uv run python tools/check_prime_parity.py --features operation.auth,operation.model-selection,operation.settings-keybindings,operation.telemetry-usage,operation.doctor,operation.controlled-update-restart --provider asterion.prime-gateway
git add src/asterion/control/providers/prime/{operational_parity_testing,parity_testing}.py tests/test_prime_operational_parity.py tests/test_prime_parity_ledger.py tests/test_check_prime_parity.py tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json Makefile
git commit -m "feat: reduce Prime operation receipts"
```

### Task 15: Package operational resources and prove installed-wheel promotion

**Files:**
- Create: `tests/test_prime_operational_packaging.py`
- Modify: `pyproject.toml`, `tests/test_distribution.py`, `tools/check_promotion.py`, `tests/test_check_promotion.py`, `packages/typescript/prime-gateway/package.json`

**Interfaces:** Makes operation schemas, private IPC code, locked module, lock file, and real harness package resources. `tools/check_promotion.py` invokes the installed wheel against an external pinned Prime root and returns source/built-lock identities and zero effect counters.

- [ ] **Step 1: Write failing installed-wheel/resource rejection tests**

```python
def test_installed_wheel_runs_operational_resource_only_against_external_pinned_root(self) -> None:
    report = _promotion_report(external_prime_root=_pinned_root())
    self.assertEqual(report["source_commit"], "a18809e00ea30638584d87b3afea7285a9d7296c")
    self.assertTrue(report["external_prime_root"])
    self.assertEqual(report["effect_counts"], _zero_effect_counts())
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_prime_operational_packaging tests.test_distribution tests.test_check_promotion
```

Expected: FAIL because operational resources are not included or installed-wheel promotion accepts a repository-local source root.

- [ ] **Step 3: Force include and verify sealed resource identity**

Add exact schemas and lock/harness paths to the wheel include list and schema-copy test. Promotion builds and installs a wheel in isolation, locates resources through package metadata, rejects a source root inside the repository/worktree, and executes the six-package harness against a separately prepared pinned root. It redacts private paths/raw output and fails closed on missing resource, lock mismatch, nonzero prohibited effect, or Node outside `>=22.8.0 <23`.

- [ ] **Step 4: Run twice and commit**

```bash
uv run python -m unittest -v tests.test_prime_operational_packaging tests.test_distribution tests.test_check_promotion
make promotion-check
uv run python -m unittest -v tests.test_prime_operational_packaging tests.test_distribution tests.test_check_promotion
make promotion-check
git add pyproject.toml tests/test_distribution.py tools/check_promotion.py tests/test_check_promotion.py tests/test_prime_operational_packaging.py packages/typescript/prime-gateway/package.json
git commit -m "build: package Prime operation evidence"
```

### Task 16: Run the clean H-036 closure without widening claims

**Files:**
- Modify: `docs/superpowers/plans/2026-08-10-asterion-prime-operational-parity.md`, `docs/status/{PRIME-PARITY-LEDGER,CURRENT-STATE,RESUME-NEXT-SESSION,JOURNAL}.md`
- Modify: `docs/status/climb/{hypotheses.yaml,runs.csv,session-state.json,research-tree.md}`, `tools/climb/{cycle.sh,regen-tree.py}`, `tests/test_prime_climb.py`
- Create: `.superpowers/sdd/operational-parity-task-16-report.md`

**Interfaces:** Consumes Tasks 1–15. Produces exactly one `H-036` passed run with command ID `check.operational-parity-closure`. This plan does not invent an `H-037`: it preserves the canonical future-work queue until a separately approved hypothesis defines the next scope.

- [ ] **Step 1: Write failing climb and nonclaim tests**

```python
EXPECTED_H036 = {
    "hypothesis": "H-036", "outcome": "passed",
    "command_id": "check.operational-parity-closure",
}

def test_h036_requires_all_six_receipts_and_does_not_invent_successor_or_native_claim(self) -> None:
    result = _run_cycle("H-036")
    self.assertEqual(result, EXPECTED_H036)
    self.assertEqual(_new_hypothesis_ids(), ())
    self.assertNotIn("Verified-native-parity", _ledger_claims())
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_prime_climb tests.test_prime_parity_ledger tests.test_check_prime_parity
```

Expected: FAIL because H-036 has no cycle gate or six-receipt closure transition.

- [ ] **Step 3: Teach the cycle to require the exact clean boundary**

`tools/climb/cycle.sh H-036` must invoke all six `test.prime-operational-*.provider-free` targets, the exact six-feature checker, `make check`, `make promotion-check`, and `git diff --check`. It must reject missing real-Prime receipts, dirty input, duplicate/noncontiguous cycles, Node outside `>=22.8.0 <23`, source/built-distribution/module lock drift, nonzero prohibited effect counters, a skipped command, or a promoted broader claim. `regen-tree.py` derives the transition only from canonical `runs.csv` evidence.

- [ ] **Step 4: Run the detached Node 22 closure twice**

From two fresh clean detached worktrees, each with a separately rebuilt pinned Prime root under Node `>=22.8.0 <23` and no credentials/configuration copied in:

```bash
tools/climb/cycle.sh H-036
tools/climb/cycle.sh H-036
```

Expected: only the first clean canonical run writes `runs.csv` and its evidence ID. The second is a disposable confirmation run recorded only in `.superpowers/sdd/operational-parity-task-16-report.md` and must append no cycle/evidence identity. Both report six exact receipts, selected `6`, passed `6`, blocking `0`, prohibited external vector all zero (`credential_value_reads`, `provider_model_requests`, `network_operations`, `package_manager_operations`, `os_process_restart_operations`, `external_telemetry_deliveries`, `uploads`), package-specific scenario counters exactly as Tasks 12–13 require, and `full_dataset=no`.

- [ ] **Step 5: Record exact claims/nonclaims, verify twice, and commit**

Record the six named Prime Gateway rows and six receipt identities only after the primary clean gate passes. With H-035's nine rows, record `interfaces.operations` PASS at exactly `15/15`; `Verified-system-parity` remains BLOCKED on every other mandatory ledger row and native parity remains missing. Do not claim live OAuth/model/telemetry/update behavior or any native behavior.

```bash
uv run python -m unittest -v tests.test_operation_protocol tests.test_operation_manager tests.test_operation_private_resolver tests.test_operation_auth tests.test_operation_model_selection tests.test_operation_settings tests.test_operation_telemetry tests.test_operation_doctor tests.test_operation_update_restart tests.test_prime_operation_bridge tests.test_prime_operational_auth tests.test_prime_operational_model_selection tests.test_prime_operational_settings tests.test_prime_operational_telemetry tests.test_prime_operational_doctor tests.test_prime_operational_update_restart tests.test_prime_operational_parity tests.test_prime_operational_packaging tests.test_agent_client_protocol tests.test_client_operations tests.test_prime_climb tests.test_prime_parity_ledger tests.test_check_prime_parity tests.test_check_promotion
make check
make promotion-check
git diff --check
uv run python -m unittest -v tests.test_operation_protocol tests.test_operation_manager tests.test_operation_private_resolver tests.test_operation_auth tests.test_operation_model_selection tests.test_operation_settings tests.test_operation_telemetry tests.test_operation_doctor tests.test_operation_update_restart tests.test_prime_operation_bridge tests.test_prime_operational_auth tests.test_prime_operational_model_selection tests.test_prime_operational_settings tests.test_prime_operational_telemetry tests.test_prime_operational_doctor tests.test_prime_operational_update_restart tests.test_prime_operational_parity tests.test_prime_operational_packaging tests.test_agent_client_protocol tests.test_client_operations tests.test_prime_climb tests.test_prime_parity_ledger tests.test_check_prime_parity tests.test_check_promotion
make check
make promotion-check
git diff --check
git add docs/superpowers/plans/2026-08-10-asterion-prime-operational-parity.md docs/status/PRIME-PARITY-LEDGER.md docs/status/CURRENT-STATE.md docs/status/RESUME-NEXT-SESSION.md docs/status/JOURNAL.md docs/status/climb tools/climb/{cycle.sh,regen-tree.py} tests/test_prime_climb.py .superpowers/sdd/operational-parity-task-16-report.md
git commit -m "docs: close H036 operational parity"
```

---

## Final Review Checklist

- [ ] `asterion.operation/v1` descriptor/transaction/receipt schemas, Python validators, TypeScript validators, and exhaustive valid/invalid fixtures agree exactly.
- [ ] Canonical `AuthorityEnvelope`/`AuthorityLedger`, not a parallel authority store, owns durable reservation and settlement across every crash window.
- [ ] Private request resolution rechecks descriptor identity/purpose/digest/media/size/revision/cancellation and redacts all errors.
- [ ] Each of the six host-owned packages has a closed Python/TypeScript typed private request validator, independent injected services, provider-free redaction, and complete effect-counter assertions.
- [ ] Auth has private precedence/status and mocked refresh only; model selection uses only fixture catalog entries; Prime-compatible `theme`, `telemetry.enabled`, and `app.*` keybindings remain preference only.
- [ ] Telemetry is network-disabled and observation-only on sink failure; doctor is read-only; update/restart uses only a deterministic fake coordinator.
- [ ] Prime IPC exposes only generic `operation.execute`/`operation.cancel`/`operation.reconcile`; client invokes a narrow ControlHost dispatcher and adds only generic `operation.receipted`.
- [ ] Locked harness verifies source and built-distribution anchors for auth, model tuple, settings/keybindings, telemetry/usage, diagnostics, and all three controlled-update/restart anchors.
- [ ] Six independent receipts feed the atomic reducer; incomplete/dirty closure cannot mutate any ledger row and native rows remain missing.
- [ ] Installed-wheel promotion resolves resources through package metadata and uses an external pinned root under Node `>=22.8.0 <23`.
- [ ] The exact six-feature checker reports selected `6`, passed `6`, blocking `0`; H-035 plus H-036 reports `interfaces.operations` PASS at `15/15`, while `Verified-system-parity` stays BLOCKED.
- [ ] Only the canonical clean closure writes its H-036 run/evidence ID; the second disposable confirmation is retained only in the Task 16 report.
