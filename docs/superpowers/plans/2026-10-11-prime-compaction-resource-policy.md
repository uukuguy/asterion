# Prime Compaction Resource Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved design's first two increments: application-owned compaction capacities and safe, visible runtime resource alarms, without increasing execution authority.

**Architecture:** Keep resource arithmetic and validated diagnostic values in domain-neutral Python. The standard Prime entry injects immutable policy into Python and the existing authenticated Node witness; both backend identity ceiling hashes include the policy. Existing command, parent/session, callback and deadline authority remains binding, and operator-owned sinks render and persist safe numeric alarms.

**Tech Stack:** Python dataclasses and unittest, Node Buffer/socket framing, TypeScript, existing Pi extension binding, uv wheel builds.

## Global Constraints

- Approved source: `docs/superpowers/specs/2026-10-11-prime-compaction-resource-policy-design.md`.
- Framework defaults: `max_total_tokens=262144`, `max_frame_bytes=16777216`, `max_material_bytes=65536`.
- Values are positive exact JSON-safe integers. Frame <= unsigned 32-bit header maximum, selected Node Buffer maximum, and Python allocation/index maximum; material < effective frame.
- Manifests and the four public closed protocols remain unchanged. The private witness protocol may receive explicitly validated fields/phases.
- Core reads no operator environment, credentials or profiles. Existing host-created extension-binding environment is private transport injection, not a configuration resolver.
- Larger capacity is not authority. Quote <= policy AND quote <= command reservation AND reservation <= remaining session/parent authority.
- P1 authority remains 64000 tokens, 500000 micro-units, 8 model callbacks, 4 tool callbacks, and 600 seconds. Its single compaction preset becomes 48000 tokens /125000 micro-units.
- Native Pi reserveTokens, native output limits and P7 supervised controls are unchanged. Legacy `(3276,3276)` quote inputs are estimates/reservation assumptions, never witnessed actual native output caps.
- `UTF-8 bytes/4` is an estimate, not a conservative input bound. First two increments do not certify request-bound authorization, token ceilings, arbitrary-provider accounting or actual usage settlement.
- Hard violations reject/stop; soft observations only alarm. Unknown effects preserve reservation and recovery fences. Sink errors cannot alter the original decision/reason.
- No paid model/ARC/BP35 run. Finish with a fresh-wheel zero-provider witness. Synthetic usage must remain labelled synthetic.

## File ownership and execution order

1. **Shared primitives:** `services/diagnostics.py`, `agents/prime/compaction_budget.py`, `tests/test_prime_diagnostics.py`, new `tests/test_prime_resource_policy.py`.
2. **Capacity transport:** `agents/prime/application.py`, `_launch.py`, `context.py`, `summarization.py`, `backend.py` identity section; TypeScript `context-witness.ts`; corresponding context/application/backend/TS tests and shipped resources.
3. **Admission/P1:** remaining `backend.py`/`context.py` admission sites, `applications/prime/p1/compaction_policy.py` (new), `p1/operator.py`, `p1/runtime_binding.py`, P1/context/backend tests.
4. **Alarm presentation/package proof:** new `applications/prime/resource_alarms.py`; operator diagnostic wiring; existing resource-trip sites; new installed zero-provider witness test; evidence/status documents.

Execute sequentially; each worker owns only its task's changes and accommodates earlier changes. Do not restructure composers, runners or provider adapters. Review after each task, then commit the task before starting the next.

---

### Task 1: Validated resource diagnostics and compaction policy arithmetic

**Files:**
- Modify: `src/asterion/services/diagnostics.py` (`FailureDiagnostic`, `capture_failure`, `_failure_code`, `__all__`).
- Modify: `src/asterion/agents/prime/compaction_budget.py` (fixed caps, quote arithmetic).
- Modify: `tests/test_prime_diagnostics.py`.
- Create: `tests/test_prime_resource_policy.py`.

**Interfaces produced (declarations, not implementation bodies):**

```text
@dataclass(frozen=True, slots=True)
class LimitDiagnostic:
    limit_code: str
    phase: str
    action: str
    observed: int | None
    limit: int
    unit: str
    measurement: str
    config_source: str

class ResourceLimitExceeded(ValueError):
    limit_diagnostic: LimitDiagnostic
    failure_code: str
    def __init__(self, diagnostic: LimitDiagnostic) -> None:

# Add after failure_metadata; retain positional compatibility.
# FailureDiagnostic.limit_diagnostic: LimitDiagnostic | None = None

def limit_diagnostic(error: BaseException) -> LimitDiagnostic | None:
def capture_limit(sink: DiagnosticSink | None, *, stage: str,
                  diagnostic: LimitDiagnostic, subject_id: str,
                  capability_ref: str | None = None) -> str | None:

@dataclass(frozen=True, slots=True)
class PrimeCompactionPolicy:
    max_total_tokens: int = 262144
    max_frame_bytes: int = 16777216
    max_material_bytes: int = 65536

def quote_compaction_reservation(*, branch_input_caps: tuple[int, int],
    branch_output_caps: tuple[int, int], price: ModelPrice,
    policy: PrimeCompactionPolicy = PrimeCompactionPolicy(),
    config_source: str = 'framework-default'
) -> CompactionReservationQuote:
```

These declarations specify public contracts; the implementation steps below supply concrete behavior. `LimitDiagnostic` validates closed sets: codes `compaction-token-limit`, `compaction-cost-limit`, `compaction-callback-limit`, `compaction-deadline`, `compaction-input-bound-unavailable`, `prime-session-token-limit`, `prime-session-cost-limit`, `prime-parent-token-limit`, `prime-parent-cost-limit`, `witness-frame-limit`, `summarization-material-limit`, `ipython-output-limit`, `context-memory-limit`, `context-archive-limit`, `prime-model-callback-limit`, `prime-tool-callback-limit`, `prime-deadline`, `pi-output-limit`; phases `admission/execution/settlement`; actions `observed/rejected/stopped/recovery-required`; units `tokens/bytes/callbacks/milliseconds/cost-micros`; measurements `exact/conservative-bound/estimate/unavailable`; sources `framework-default/application/operator/authority`. Task3 extends the closed code set with the four session/parent codes listed here and adds accepted-code/wrong-unit validation rows; no additional diagnostic fields are introduced. Code/unit mapping must agree (frame/material/output/memory/archive -> bytes; callback -> callbacks; deadline -> milliseconds; compaction/session/parent cost -> cost-micros; session/parent token and other compaction codes -> tokens). `observed=None` iff measurement is `unavailable`. Validate exact `int` (reject bool), `0 <= observed <= 2**53-1`, `0 <= limit <= 2**53-1`. Never accept arbitrary strings through exception attributes.

- [x] **Step 1: Add failing primitive tests.**

```python
from dataclasses import FrozenInstanceError, asdict
import unittest
from asterion.agents.prime.compaction_budget import (
    ModelPrice, PrimeCompactionPolicy, quote_compaction_reservation)
from asterion.services.diagnostics import (
    LimitDiagnostic, ResourceLimitExceeded, MemoryDiagnosticSink,
    capture_failure, capture_limit)

class TestPrimeResourcePolicy(unittest.TestCase):
    def test_default_and_invalid_values(self):
        self.assertEqual(asdict(PrimeCompactionPolicy()), {
            'max_total_tokens': 262144, 'max_frame_bytes': 16777216,
            'max_material_bytes': 65536})
        for changes in ({'max_total_tokens': True}, {'max_total_tokens': 0},
                        {'max_frame_bytes': 2**32}, {'max_material_bytes': 16777216},
                        {'max_material_bytes': 1.5}, {'max_total_tokens': 2**53}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                PrimeCompactionPolicy(**changes)
        with self.assertRaises(FrozenInstanceError):
            PrimeCompactionPolicy().max_total_tokens = 1

    def test_unequal_branches_and_component_rounding(self):
        quote = quote_compaction_reservation(branch_input_caps=(40000, 1000),
            branch_output_caps=(3276, 3276), price=ModelPrice(1, 1))
        self.assertEqual(quote.reserved_tokens, 47552)
        self.assertEqual(quote.cost_micro_units, 4)
        with self.assertRaises(ResourceLimitExceeded) as caught:
            quote_compaction_reservation(branch_input_caps=(40000, 1000),
                branch_output_caps=(3276, 3276), price=ModelPrice(1, 1),
                policy=PrimeCompactionPolicy(max_total_tokens=16000))
        self.assertEqual(caught.exception.limit_diagnostic.limit, 16000)
        self.assertEqual(caught.exception.limit_diagnostic.observed, 47552)

class TestLimitDiagnostics(unittest.TestCase):
    def diagnostic(self):
        return LimitDiagnostic('compaction-token-limit', 'admission', 'rejected',
            48001, 48000, 'tokens', 'estimate', 'authority')

    def test_safe_capture_and_typed_cause(self):
        sink = MemoryDiagnosticSink()
        wrapper = RuntimeError('PRIVATE-PROMPT-CREDENTIAL-PATH')
        wrapper.__cause__ = ResourceLimitExceeded(self.diagnostic())
        identity = capture_failure(sink, stage='prime.compaction', error=wrapper,
            subject_id='PRIVATE-SESSION-ID')
        record = sink.get(identity)
        self.assertEqual(record.limit_diagnostic, self.diagnostic())
        self.assertEqual(record.failure_code, 'compaction-token-limit')
        self.assertNotIn('PRIVATE', repr(record))

    def test_no_sink_and_failed_sink_do_not_replace_reason(self):
        class Broken:
            def record(self, value):
                raise RuntimeError('PRIVATE-SINK')
        for sink in (None, Broken()):
            with self.subTest(sink=type(sink).__name__):
                self.assertIsNone(capture_limit(sink, stage='prime.compaction',
                    diagnostic=self.diagnostic(), subject_id='operation-1'))
        error = ResourceLimitExceeded(self.diagnostic())
        self.assertEqual(str(error), 'resource limit exceeded')
        self.assertEqual(error.failure_code, 'compaction-token-limit')
```

Also add `subTest` validation rows for every enum field, bool/negative/unsafe numeric values, observed/measurement mismatch, wrong code/unit, and old seven-positional-field `FailureDiagnostic` construction. Use `dataclasses.replace(self.diagnostic(), **changes)` to drive invalid rows.

- [x] **Step 2: Verify tests fail because the new imports/interfaces do not exist.**

Run: `uv run python -m unittest -v tests.test_prime_resource_policy tests.test_prime_diagnostics`.
Expected: import failure for `PrimeCompactionPolicy`/`LimitDiagnostic`; existing tests remain unchanged at this step.

- [x] **Step 3: Implement validated primitives and preserve legacy CLI input shape.**

Use this policy validation body and quote arithmetic:

```python
@dataclass(frozen=True, slots=True)
class PrimeCompactionPolicy:
    max_total_tokens: int = 262144
    max_frame_bytes: int = 16777216
    max_material_bytes: int = 65536

    def __post_init__(self) -> None:
        for value in (self.max_total_tokens, self.max_frame_bytes, self.max_material_bytes):
            if _safe_nonnegative_integer(value) == 0:
                _fail()
        if (self.max_frame_bytes > min((1 << 32) - 1, sys.maxsize - 4)
                or self.max_material_bytes >= self.max_frame_bytes):
            _fail()
```

Remove `_INPUT_CAP_MAX`, `_OUTPUT_CAP_MAX`, `_RESERVED_TOKENS_MAX`, `_COST_MICRO_UNITS_MAX`; `_validated_caps` accepts only the fixed two-element tuple and validates each exact safe nonnegative integer. Preserve `_ceil_priced_component` and existing branch dataclasses. Validate `price` and `policy` by exact type and `config_source` against the four closed sources. Callers supply the actual source; do not infer it by value equality. Validate summed token/cost/branch components with `_safe_nonnegative_integer`; arithmetic never silently exceeds safe-integer range. On total > policy, raise:

```python
raise ResourceLimitExceeded(LimitDiagnostic(
    'compaction-token-limit', 'admission', 'rejected', reserved_tokens,
    policy.max_total_tokens, 'tokens', 'conservative-bound',
    config_source))
```

The quote API receives supplied bounds; its caller must label byte-derived estimates correctly when projecting an admission alarm. `_quote_from_json` continues to accept exactly `branch_input_caps`, `branch_output_caps`, `price`; no new mandatory CLI key. `ResourceLimitExceeded` subclasses `ValueError` for existing handlers, stores only exact validated `LimitDiagnostic`, sets fixed message `resource limit exceeded` and code from that diagnostic. Add typed cause-chain extraction parallel to `failure_metadata` with cycle detection. `capture_failure` attaches the typed diagnostic and prefers its closed code; `capture_limit` calls `capture_failure` with `ResourceLimitExceeded(diagnostic)`. Sink failures return `None` exactly as before.

- [x] **Step 4: Run focused tests and adapt obsolete fixed-cap assertions.**

Run: `uv run python -m unittest -v tests.test_prime_resource_policy tests.test_prime_diagnostics tests.test_asterion_prime_context`.
Expected: PASS after changing former fixed-16000 tests to explicitly supply `PrimeCompactionPolicy(max_total_tokens=16000)`. Preserve existing request-estimate assertions and document that they prove arithmetic only. No claim of provider token accounting.

- [x] **Step 5: Review and commit this independently testable primitive boundary.**

```bash
git add src/asterion/services/diagnostics.py src/asterion/agents/prime/compaction_budget.py tests/test_prime_resource_policy.py tests/test_prime_diagnostics.py tests/test_asterion_prime_context.py
git commit -m "feat(prime): add validated resource policy and limit diagnostics"
```

### Task 2: Inject identical policy through Prime, Python and Node framing

**Files:**
- Modify: `src/asterion/agents/prime/application.py` (`PrimeBackendSpec`, `open_backend`).
- Modify: `src/asterion/agents/prime/_launch.py` (`persistent_launch`).
- Modify: `src/asterion/agents/prime/backend.py` (constructor identity validation only).
- Modify: `src/asterion/agents/prime/context.py` (`_validate_summarization`, `_validate_preparation`, `PrimeContextWitnessSession`).
- Modify: `src/asterion/agents/prime/summarization.py` (remove fixed `MAX_MATERIAL_BYTES` capacity export).
- Modify: `packages/typescript/asterion-prime-extension/src/context-witness.ts`.
- Modify: `packages/typescript/asterion-prime-extension/test/context-witness.test.mjs`.
- Modify: `tests/test_prime_application_entry.py`, `tests/test_asterion_prime_backend.py`, `tests/test_asterion_prime_context.py`.
- Rebuild: all three `.mjs` resources under `src/asterion/applications/prime/resources/` with the existing sync script.

**Interfaces:**
- Consumes: Task 1 `PrimeCompactionPolicy`, `LimitDiagnostic`, `ResourceLimitExceeded`.
- Produces: trailing `PrimeBackendSpec.compaction_policy: PrimeCompactionPolicy = PrimeCompactionPolicy()` and `compaction_policy_source: str = 'framework-default'`; keyword-only `PrimeSessionBackend(..., compaction_policy=PrimeCompactionPolicy(), compaction_policy_source='framework-default')`; `persistent_launch(..., compaction_policy=PrimeCompactionPolicy(), compaction_policy_source='framework-default')`.
- `PrimeContextWitnessSession(..., policy=PrimeCompactionPolicy(), config_source='framework-default', max_frame_bytes: int | None=None)` retains legacy explicit frame override. When provided it must agree with the policy's frame value; an old override can construct a replaced policy only when no non-default explicit policy was supplied. No silent second maximum survives.
- Correct `_validate_summarization` documentation to describe inherited reconstruction material and estimated quote input, not authoritative actual native provider requests. Python validation functions take keyword-only `policy: PrimeCompactionPolicy = PrimeCompactionPolicy()` and thread it through nested material/preparation checks.
- TypeScript `ContextWitnessOptions` adds `policy?: Readonly<PrimeCompactionPolicy>` and `configSource?: ConfigSource`. Existing `maxFrameBytes` remains an explicit compatibility alias with equality rejection when both provided.
- Private binding environment key: `ASTERION_PRIME_IPYTHON_COMPACTION_POLICY`; value is canonical JSON with exactly `max_total_tokens`, `max_frame_bytes`, `max_material_bytes`, `config_source`, <=512 UTF-8 bytes. `_launch` creates this transport value from passed dataclasses. TypeScript consumes/deletes it; Python does not resolve any external policy environment variable.
- Private `arm` envelope adds `compaction_policy` with those same four keys. Receiver verifies exact equality with the constructor policy before accepting material or initiating native summaries.
- Private resource-refusal envelope: base identity fields + `phase='limit'` + `limit_diagnostic` containing exactly the eight Task 1 fields. Only closed resource codes and valid numeric fields are accepted; no raw text.

- [ ] **Step 1: Add failing policy plumbing and transport boundary tests.**

Add the following Python tests alongside the existing `ContextMixin` helpers; existing fixture material and nonce helpers remain authoritative.

```python
async def test_incoming_frame_header_rejects_before_body_allocation(self):
    policy = PrimeCompactionPolicy(max_frame_bytes=8192, max_material_bytes=4096)
    self.session.close()
    self.peer.close()
    self.host, self.peer = socket.socketpair()
    self.host.setblocking(False)
    self.peer.setblocking(False)
    self.session = self.context.PrimeContextWitnessSession(self.host,
        launch_nonce='a' * 64, mark_uncertain=lambda: None, policy=policy)
    await asyncio.get_running_loop().sock_sendall(self.peer, struct.pack('!I', 8193))
    with self.assertRaises(ResourceLimitExceeded) as caught:
        await self.session._receive()
    self.assertEqual(caught.exception.limit_diagnostic.observed, 8193)
    self.assertEqual(caught.exception.limit_diagnostic.limit, 8192)

async def test_arm_contains_injected_policy(self):
    await self.session.arm(command_nonce=COMMAND, authority_sha256=AUTHORITY)
    observed = await receive(self.peer)
    self.assertEqual(observed['compaction_policy'], {
        'max_total_tokens': 262144, 'max_frame_bytes': 16777216,
        'max_material_bytes': 65536, 'config_source': 'framework-default'})
```

Use a fresh socketpair in the first test rather than reopening the closed fixture socket. Add frame admission tests with valid canonical payloads whose **whole encoded frame** is one byte below, equal to, and one byte above the injected cap. Include >1MiB accepted frames under the 16MiB default; a cap is for the envelope, not just a `main_summary_request` string. Test material size by padding the fixture `system_prompt` while preserving marker identities; exact encoded material <=policy passes, >policy raises `summarization-material-limit`.

Update existing TypeScript registration tests to pass constructor policy and add these assertions:

```javascript
assert.throws(() => new extension.ContextWitness(deps, {
  descriptor: sockets.peer._handle.fd, launchNonce: launch,
  policy: {max_total_tokens: 262144, max_frame_bytes: 2 ** 32,
           max_material_bytes: 65536}, configSource: 'application'
}), /resource limit|unavailable/);
```

Use the test's actual accepted socket descriptor and frozen `ContextDependencies` object. Add `subTest`/Node cases for config mismatches, Buffer `constants.MAX_LENGTH`, exact JSON keys, unsafe integers, malformed bootstrap, missing one witness bootstrap key, consumed transport environment, and conflict with operator environment. A Node child tests rejected startup without a provider. Add application tests constructing the old positional `PrimeBackendSpec` and tests that changing policy changes the identity hash, then causes an old stored identity/resume to fail closed.

- [ ] **Step 2: Run the exact focused checks and observe missing fields/old 1MiB checks.**

```bash
uv run python -m unittest -v tests.test_prime_application_entry tests.test_asterion_prime_backend tests.test_asterion_prime_context
npm --prefix packages/typescript/asterion-prime-extension test
```

Expected: new tests fail on missing policy constructor/arm fields, >1MiB frames, and missing safe peer limit metadata. Historical missing-mechanics tests may remain SKIP; do not count them as native proof.

- [ ] **Step 3: Implement policy identity, bootstrap and private refusal.**

At both identity producers/validators use exactly this payload:

```python
ceilings = {
    **asdict(limits), 'aggregate_tokens': aggregate_tokens,
    'cost_micros': cost_micros, 'compaction_policy': asdict(compaction_policy),
    'compaction_policy_source': compaction_policy_source,
}
```

`open_backend` uses spec fields; backend uses constructor fields. Validate exact policy type and closed source on `PrimeBackendSpec`; old construction gets defaults. Pass policy/source to `_launch.persistent_launch`, witness and backend. In `_launch` serialize host-created policy into `ExtensionBinding.environment`; retain its existing collision check against `operator.environment` so callers cannot replace the trusted value.

Use TypeScript validation before `new Socket` or payload Buffer allocation:

```typescript
import { constants as bufferConstants } from 'node:buffer';
const STRUCTURAL_FRAME_MAX = Math.min(0xffffffff, bufferConstants.MAX_LENGTH - 4);
function validatePolicy(raw: unknown): Readonly<PrimeCompactionPolicy> {
  const value = object(raw);
  keys(value, ['max_total_tokens', 'max_frame_bytes', 'max_material_bytes']);
  const total = integer(value.max_total_tokens);
  const frame = integer(value.max_frame_bytes);
  const material = integer(value.max_material_bytes);
  if (total < 1 || frame < 1 || frame > STRUCTURAL_FRAME_MAX ||
      material < 1 || material >= frame) fail();
  return Object.freeze({max_total_tokens: total, max_frame_bytes: frame,
    max_material_bytes: material});
}
```

The transport JSON parser validates `config_source` separately and its exact four-field shape; arm and constructor policy/source must match. Before process activation, Python validates its unsigned-header/allocation representation and serializes the **complete arm frame** with material to establish that it fits. The selected Node process validates its Buffer maximum before constructing the channel; unsupported capacity yields a safe startup capability failure and no native execution. Do not certify readiness solely from Python's structural limit.

Remove the hidden `_MAX_FRAME`/`MAX_FRAME` 1MiB ceiling everywhere, including preparation/request checks. Replace fixed material checks with the policy parameter. Node checks `Buffer.byteLength(canonicalJson(frame)) <=cap` before `Buffer.from`/write; Python checks encoded full frame before building the header/wire. Reads check the unsigned header before allocating the declared body; Node checks pending-byte bounds before concatenation. Preserve canonical equality, UTF-8 validation, identity/digest/nonce equality and duplicate-frame handling.

For Python limit violations construct `ResourceLimitExceeded` with exact byte length and injected source. For Node use an internal error storing only the validated numeric limit record. When `before()` catches that exact error, send an authenticated `phase='limit'` frame, then return `{cancel:true}`. The tiny refusal must fit the effective cap; Python's complete-arm admission implies space for it, and a refusal that itself cannot fit causes safe transport closure without approval. For `persisted()` after approval, send the record when possible, close and preserve the host recovery fence. On Python `_receive`, authenticate a `limit` envelope against launch/command/authority first, validate closed diagnostic shape, raise the typed error and preserve it through wrapping; never convert it to generic EOF. Invalid refusal shape is a protocol error, not trusted resource exhaustion. In Task3, catch typed refusal in `receive_proposal_and_decide` before the general fence path: an authenticated peer refusal before any approve bytes returns false/idle and retains `last_refusal`; a post-approval limit preserves recovery-required. A direct `_receive` test proves typed wire metadata only, not recovery behavior.

- [ ] **Step 4: Run focused checks, rebuild shipped resources, then review.**

```bash
npm --prefix packages/typescript/asterion-prime-extension test
npm --prefix packages/typescript/asterion-prime-extension run sync-resource
uv run python -m unittest -v tests.test_prime_application_entry tests.test_asterion_prime_backend tests.test_asterion_prime_context tests.test_prime_resource_policy
npm --prefix packages/typescript/asterion-prime-extension run check-resource
```

Expected: PASS; generated generic, P7 research and P7 legacy resources contain the same witness implementation. `max_material_bytes=65536` and frame=16MiB are real policy capacities on both sides; custom limits have exact safe refusal values.

- [ ] **Step 5: Commit capacity plumbing separately.**

```bash
git add src/asterion/agents/prime/application.py src/asterion/agents/prime/_launch.py src/asterion/agents/prime/backend.py src/asterion/agents/prime/context.py src/asterion/agents/prime/summarization.py packages/typescript/asterion-prime-extension/src/context-witness.ts packages/typescript/asterion-prime-extension/test/context-witness.test.mjs tests/test_prime_application_entry.py tests/test_asterion_prime_backend.py tests/test_asterion_prime_context.py src/asterion/applications/prime/resources
git commit -m "feat(prime): inject compaction capacities across witness transport"
```

### Task 3: Preserve authority and give P1 one 48k compaction preset

**Files:**
- Create: `src/asterion/applications/prime/p1/compaction_policy.py`.
- Modify: `src/asterion/applications/prime/p1/operator.py` (command budget, release, preflight/backend spec).
- Modify: `src/asterion/applications/prime/p1/runtime_binding.py` (reservation guard).
- Modify: `src/asterion/agents/prime/backend.py` (`_compact`, `reserve`, rejected receipt).
- Modify: `src/asterion/services/diagnostics.py`, `tests/test_prime_diagnostics.py`, `tests/test_prime_resource_policy.py` (closed session/parent limit code and unit validation).
- Modify: `src/asterion/agents/prime/context.py` (`receive_proposal_and_decide`, last refusal).
- Modify: `tests/test_asterion_prime_p1_operator.py`, `tests/test_asterion_prime_p1_runtime.py`, `tests/test_asterion_prime_backend.py`, `tests/test_asterion_prime_context.py`.

**Interfaces:**
- Consumes: prior immutable policy/source and typed refusal.
- Produces: `P1_COMPACTION_RESERVED_TOKENS = 48000`, `P1_COMPACTION_COST_MICROS = 125000`, `P1_COMPACTION_POLICY = PrimeCompactionPolicy()` in the application module; use these symbols in command creation, P1StageTwoRelease and runtime checks.
- `PrimeContextWitnessSession.last_refusal: LimitDiagnostic | None` reset at each arm and retained through rejected decision.
- `reserve(quote: CompactionReservationQuote) -> bool` may raise `ResourceLimitExceeded` to preserve the binding limit. `receive_proposal_and_decide` returns the same bool and sends the unchanged approve/reject decision shape; typed refusal stays host-private.

- [ ] **Step 1: Add failing authority and safe reason tests.**

```python
class TestP1CompactionPreset(unittest.TestCase):
    def test_one_preset_preserves_total_authority(self):
        from asterion.applications.prime.p1.compaction_policy import (
            P1_COMPACTION_RESERVED_TOKENS, P1_COMPACTION_COST_MICROS)
        from asterion.applications.prime.p1 import operator, runtime_binding
        self.assertEqual(P1_COMPACTION_RESERVED_TOKENS, 48000)
        self.assertEqual(P1_COMPACTION_COST_MICROS, 125000)
        self.assertEqual(operator._AGGREGATE_TOKENS, 64000)
        self.assertEqual(operator._COST_MICROS, 500000)
        self.assertEqual(operator._DEADLINE_SECONDS, 600.0)
        self.assertEqual(runtime_binding._MAX_COMPACT_RESERVED_TOKENS, 48000)
        self.assertEqual(64000 - P1_COMPACTION_RESERVED_TOKENS, 16000)
```

Extend the existing mocked backend compact harness with rows: quote tokens 48001/reservation48000; quote cost125001/reservation125000; reservation48000/session remaining tokens47999; reservation48000/parent controller or aggregate tokens47999; reservation125000/parent cost124999; parent token/cost balances zero; callbacks remaining1; expired deadline; malformed proposal; reserve sink failure. Assert rejected receipt reasons respectively `compaction-token-limit`, `compaction-cost-limit`, `prime-session-token-limit`, `prime-parent-token-limit`, `prime-parent-cost-limit`, the applicable `prime-parent-token-limit`/`prime-parent-cost-limit` for zero balances, `compaction-callback-limit`, `compaction-deadline`, existing protocol failure, and the original limit reason. Assert no reservation journal entry for refusals, no extra callback charge, and no approve bytes. For command-reservation failures `limit=48000`/`125000`, `config_source='authority'`; never report the larger framework default. For session/parent refusals assert the exact effective remaining balance and distinct code, not the command-budget configuration. Cover ample session capacity with insufficient parent controller, aggregate and cost grants; test zero balances and exact equal-boundary admission before any reservation/approve. For unknown post-approval transport outcomes assert charge retained and recovery-required.

- [ ] **Step 2: Verify the new cases fail against old literal/reason collapse.**

Run: `uv run python -m unittest -v tests.test_asterion_prime_p1_operator tests.test_asterion_prime_p1_runtime tests.test_asterion_prime_backend tests.test_asterion_prime_context`.
Expected: FAIL on old16000, `context-not-admitted` collapse or missing typed refusal.

- [ ] **Step 3: Implement the shared preset and ordered authority checks.**

```python
# applications/prime/p1/compaction_policy.py
from asterion.agents.prime.compaction_budget import PrimeCompactionPolicy
P1_COMPACTION_RESERVED_TOKENS = 48000
P1_COMPACTION_COST_MICROS = 125000
P1_COMPACTION_POLICY = PrimeCompactionPolicy()
```

Import these in P1 operator/runtime. Replace only compaction-related 16000 literals: command controller/aggregate budget; `P1StageTwoRelease.compact_reserved_tokens`; `_MAX_COMPACT_RESERVED_TOKENS`. Keep unrelated stage, model and global64k limits. Pass P1 policy/source=`application` through `PrimeBackendSpec`. Existing preflight quote uses that policy/source and supplied branch numbers; its result is feasibility arithmetic, not a measured cap. Do not change Pi `reserveTokens=16384` or native output options.

Apply the following order before durable reservation/approve:

```python
checks = (
    ('compaction-token-limit', quote.reserved_tokens,
     min(int(budget['controller_tokens']), int(budget['aggregate_tokens'])), 'tokens', 'estimate'),
    ('compaction-cost-limit', quote.cost_micro_units, int(budget['cost_micros']), 'cost-micros', 'estimate'),
    ('prime-session-token-limit', int(budget['aggregate_tokens']),
     self._token_cap - self._usage.aggregate_tokens, 'tokens', 'exact'),
    ('prime-session-cost-limit', int(budget['cost_micros']),
     self._cost_cap - self._usage.cost_micros, 'cost-micros', 'exact'),
)
if self._budget is not None:
    parent_fields = (
        ('controller_tokens', 'prime-parent-token-limit', 'tokens'),
        ('aggregate_tokens', 'prime-parent-token-limit', 'tokens'),
        ('cost_micros', 'prime-parent-cost-limit', 'cost-micros'),
    )
    for field, code, unit in parent_fields:
        granted = getattr(self._budget, field)
        consumed = getattr(self._usage, field) - getattr(self._snapshot_usage, field)
        available = granted - consumed
        if available < 0:
            raise PrimeBackendError('Prime backend authority accounting is invalid')
        checks += ((code, int(budget[field]), available, unit, 'exact'),)
for code, requested, available, unit, measurement in checks:
    if requested > available:
        raise ResourceLimitExceeded(LimitDiagnostic(code, 'admission', 'rejected',
            requested, available, unit, measurement, 'authority'))
```

Effective remaining authority can be exactly zero; diagnostics accept a zero limit while policy capacities remain positive. Test zero remaining tokens, cost and callbacks. Parent checks are explicit before durable reservation or approve: remaining `controller_tokens`, `aggregate_tokens` and `cost_micros` each equal `_budget.field - (_usage.field - _snapshot_usage.field)`. Existing controller `_charge` and context `_begin` paths skip some parent checks; do not rely on those paths to enforce this invariant. Preserve `authority_revision`, parent admission and budget journal validation. Reject nonzero application/child compaction allocations as malformed authority. Preserve exact price rounding.

Quote under the injected policy, not old generic16k/cost maxima. Byte-derived input quotes and inferred legacy output quote are `estimate`; `_input_token_ceiling` docstring/tests must stop describing `/4` as a proven ceiling. Do not enable strict certification, synthesize a reliable input bound or settle synthetic usage as provider usage. Typed callback/deadline exceptions populate `last_refusal`, send reject and return false; catch malformed `ValueError/TypeError` separately and retain protocol refusal behavior. The backend captures the diagnostic with command ID, preserves its reason code in the rejected receipt and only then returns to open when native aborted compact is authenticated. Transport limits before approval yield typed rejected receipts if native cancellation is known; after approval remain recovery-required.

- [ ] **Step 4: Run focused checks and inspect the reservation boundary.**

Run: `uv run python -m unittest -v tests.test_asterion_prime_p1_operator tests.test_asterion_prime_p1_runtime tests.test_asterion_prime_backend tests.test_asterion_prime_context tests.test_prime_resource_policy tests.test_prime_diagnostics`.
Expected: PASS. Explicit48k reservation fits existing64k authority; a later stage with insufficient remainder is budget-limited. No permission/budget controls appear in the user-facing preset.

- [ ] **Step 5: Commit application preset and admission changes.**

```bash
git add src/asterion/applications/prime/p1/compaction_policy.py src/asterion/applications/prime/p1/operator.py src/asterion/applications/prime/p1/runtime_binding.py src/asterion/agents/prime/backend.py src/asterion/agents/prime/context.py tests/test_asterion_prime_p1_operator.py tests/test_asterion_prime_p1_runtime.py tests/test_asterion_prime_backend.py tests/test_asterion_prime_context.py tests/test_prime_resource_policy.py src/asterion/services/diagnostics.py tests/test_prime_diagnostics.py
git commit -m "fix(prime): preserve compaction authority and safe refusal reasons"
```

### Task 4: Visible safe alarms and fresh-wheel zero-provider evidence

**Files:**
- Create: `src/asterion/applications/prime/resource_alarms.py`.
- Create: `tests/test_prime_resource_alarms.py`.
- Modify: `src/asterion/applications/prime/p1/operator.py`, `src/asterion/applications/prime/p7/operator.py` (operator-owned sink injection and safe evidence projection).
- Modify: `src/asterion/agents/prime/execution.py`, `src/asterion/agents/prime/tools.py`, `src/asterion/agents/prime/ipython.py` (existing known numeric callback/deadline/output trip sites only).
- Modify: `tests/test_asterion_prime_backend.py`, `tests/test_prime_ipython.py`, `tests/test_asterion_prime_runtime.py`, `tests/test_prime_p7_diagnostics.py`.
- Root-owned evidence: `.asterion-private/task43-resource-policy/native/replay.py` and `entry.mjs`; these are private native-owner evidence, not new production helpers or portable test harnesses.
- Modify: `docs/status/CURRENT-STATE.md`, `docs/status/RESUME-NEXT-SESSION.md`, `docs/status/INDEX.md` with the named evidence and remaining accounting limitation.

**Interfaces:**
- Consumes: `FailureDiagnostic.limit_diagnostic`, typed refusal and safe receipt reason from Tasks1–3.
- Produces: `resource_alarm(diagnostic: FailureDiagnostic) -> dict[str, object] | None`; `ResourceAlarmSink(path: Path, *, emit: Callable[[dict[str, object]], None], downstream: DiagnosticSink | None=None)`, implementing `record(FailureDiagnostic) -> None`; `alarms: tuple[Mapping[str, object], ...]` exposes immutable snapshots for final safe stdout/evidence.
- The operator passes this sink through existing `PrimeOperatorContext.diagnostics`. Framework modules never create files or notification services. Each diagnostic subject is the actual operation ID; sink dedupe key `(subject_sha256, limit_code)` is per operation, not whole session.

- [ ] **Step 1: Write failing visible/persisted alarm tests.**

```python
from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
from asterion.applications.prime.resource_alarms import ResourceAlarmSink
from asterion.services.diagnostics import (
    LimitDiagnostic, MemoryDiagnosticSink, capture_limit)

class TestResourceAlarms(unittest.TestCase):
    def test_hard_soft_dedupe_and_distinct_operations(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'resource-alarms.jsonl'
            visible = []
            sink = ResourceAlarmSink(path, emit=visible.append)
            diagnostic = LimitDiagnostic('witness-frame-limit', 'admission',
                'rejected', 8193, 8192, 'bytes', 'exact', 'application')
            for operation in ('op-1', 'op-1', 'op-2'):
                capture_limit(sink, stage='prime.compaction', diagnostic=diagnostic,
                    subject_id=operation)
            self.assertEqual(len(visible), 2)
            self.assertEqual(len(path.read_text().splitlines()), 2)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(visible[0]['configuration'], 'PrimeCompactionPolicy.max_frame_bytes')
            self.assertEqual(visible[0]['observed'], 8193)
            self.assertEqual(visible[0]['limit'], 8192)
            self.assertEqual(visible[0]['outcome'], 'rejected')
            soft = replace(diagnostic, action='observed', measurement='estimate')
            capture_limit(sink, stage='prime.compaction', diagnostic=soft,
                subject_id='op-3')
            self.assertEqual(visible[-1]['measurement'], 'estimate')
            self.assertEqual(visible[-1]['outcome'], 'observed')
            self.assertNotIn('PRIVATE', json.dumps(visible))

    def test_emit_and_downstream_failures_do_not_drop_safe_retained_alarm(self):
        def broken_emit(value):
            raise RuntimeError('PRIVATE-CREDENTIAL')
        class Broken:
            def record(self, value):
                raise RuntimeError('PRIVATE-PROVIDER-PAYLOAD')
        with tempfile.TemporaryDirectory() as temporary:
            sink = ResourceAlarmSink(Path(temporary) / 'alarms.jsonl',
                emit=broken_emit, downstream=Broken())
            diagnostic = LimitDiagnostic('compaction-token-limit', 'admission',
                'rejected', 1, 0, 'tokens', 'exact', 'authority')
            capture_limit(sink, stage='prime.compaction', diagnostic=diagnostic,
                subject_id='PRIVATE-OPERATION')
            self.assertEqual(len(sink.alarms), 1)
            self.assertEqual(sink.alarms[0]['limit'], 0)
            self.assertNotIn('PRIVATE', json.dumps([dict(item) for item in sink.alarms]))
```

Add a persistence-failure case using a path under a missing parent; the sink retains its immutable safe alarm and emit still receives it. Assert original backend reject reason unchanged with no sink, throwing sink, and resource alarm sink. Existing `_safe_failure_diagnostic` test verifies P7 projects only the validated eight numeric/enumerated fields; sentinel prompts, exceptions, private IDs and paths never appear.

- [ ] **Step 2: Run the focused failing test.**

Run: `uv run python -m unittest -v tests.test_prime_resource_alarms tests.test_prime_p7_diagnostics`.
Expected: missing application alarm module/limit projection until implementation.

- [ ] **Step 3: Implement the operator sink and existing numeric trip projection.**

Use fixed code-to-configuration names. Frame/material/token map to `PrimeCompactionPolicy.max_frame_bytes`, `.max_material_bytes`, `.max_total_tokens`; command codes `compaction-token-limit` / `compaction-cost-limit` with source `authority` map to `SessionContextCommand.payload.budget.controller_tokens/aggregate_tokens` / `.cost_micros`; `prime-session-token-limit` / `prime-session-cost-limit` map to `PrimeBackendSpec.aggregate_tokens` / `.cost_micros`; `prime-parent-token-limit` maps to `RemainingBudget.controller_tokens/aggregate_tokens`, and `prime-parent-cost-limit` maps to `RemainingBudget.cost_micros`; callbacks map to `AsterionPrimeLimits.model_callbacks` / `.tool_callbacks`; IPython maps to `KernelLimits.max_output_bytes`; deadline maps to the owning finite deadline.

```python
def resource_alarm(diagnostic):
    limit = diagnostic.limit_diagnostic
    if limit is None:
        return None
    return {
        'type': 'resource-limit', 'diagnostic_id': diagnostic.diagnostic_id,
        'limit_code': limit.limit_code,
        'configuration': _configuration(limit),
        'phase': limit.phase, 'observed': limit.observed, 'limit': limit.limit,
        'unit': limit.unit, 'measurement': limit.measurement,
        'config_source': limit.config_source, 'outcome': limit.action,
    }
```

`ResourceAlarmSink.record` validates exact `FailureDiagnostic`/`LimitDiagnostic`, derives a new safe dictionary, freezes a snapshot, and stores it before trying downstream/persist/emit. Dedupe per operation+code. Persist safe canonical JSONL through `os.open(path, O_WRONLY|O_CREAT|O_APPEND, 0o600)`, enforce mode0600, and close in `finally`; append only the safe projection. Downstream, persistence and emit each get independent `try/except Exception` guards. A downstream error cannot suppress emit or rewrite a rejection; a persisted alarm failure cannot grant execution. No raw body or subject identifier is emitted; retain existing hashes only in `FailureDiagnostic`.

P1 and P7 operator `emit` prints a concise immediate safe alarm to their existing visible operator progress channel. Retain safe `resource_alarms` in the final public stdout JSON/evidence object, so the alarm is visible even if no live progress consumer exists. P7 uses its existing run private evidence directory. P1's normal cleanup removes its temporary backend/journal, so publish the safe alarms with its existing external public result/progress evidence before cleanup; do not claim a deleted temporary alarm file is durable evidence. The fresh-wheel test supplies a retained operator evidence directory. Do not add user configuration knobs or expand P1's cleanup/recovery contract.

Known Python trip sites attach exact numeric records: model callbacks attempted/approved max in `execution.py`; tool callbacks attempted/max in `tools.py`/execution; effective deadline requested elapsed vs finite operation deadline in existing deadline rejection; IPython received output encoded UTF-8 length vs `KernelLimits.max_output_bytes` before its existing lost-kernel handler. Preserve callback error codes and terminal behavior by attaching typed metadata to their existing exception classes or chaining `ResourceLimitExceeded`; generic outer catches must preserve extraction. Do not manufacture output length when worker only reports `output_truncated=True`: use observed unavailable/measurement unavailable, while preserving truncation status. IPython ownership adds an optional trailing diagnostic sink argument only if required and passes it from the existing application workspace owner.

A soft threshold creates `action='observed'` and returns to normal execution; the sink never makes authorization decisions. Settlement over an approved bound emits stopped/recovery-required and preserves accounting/unknown-effect fences, but actual native branch usage settlement remains unimplemented in this scope. TS context-memory/archive capacity redesign is a subsequent scoped change: the archive currently uses character counts, which cannot be mislabeled as exact bytes. No statement that all framework ceilings now support this policy is allowed.

- [ ] **Step 4: Add and run the fresh-wheel provider-free witness.**

Root owns the already established real native-owner/RPC/persist-worker probe at `.asterion-private/task43-resource-policy/native/replay.py` with `entry.mjs`. Rebuild a fresh wheel, install it outside the source checkout, resolve all three extension resources from that wheel, and rerun this native probe. Do not add a second installed unittest/harness or import unverified native helper exports. Portable Node/Python tests in Tasks2–3 already cover frame and refusal shapes.

The root probe must record two named cases: (1) default16MiB accepts a >1MiB complete frame through actual native RPC and persistence; (2) application16KiB frame /8KiB material rejects that same proposal and emits exact `witness-frame-limit` before provider transport. It uses1,000,000-token **synthetic test authority** only to admit the approximately200k-token estimated request; that is not a P1 authority increase or verified token bound. Assertions: zero actual network attempts, zero real model calls, synthetic usage labelled synthetic, equal injected policy/source in Python and Node, proper reject/approve states, safe alarm persistence/presentation, and exact operation/limit deduplication. A paid provider is not involved.

Use the named root-owned replay command below after the fresh-wheel path has been injected into that private probe by its existing operator harness. Record wheel digest, extension digest, probe JSON and command in the status/evidence receipt. If native Pi or the probe's operator dependencies are unavailable, mark the result External-limited; portable tests cannot substitute for it.

Run in order:

```bash
npm --prefix packages/typescript/asterion-prime-extension test
npm --prefix packages/typescript/asterion-prime-extension run sync-resource
uv run python -m unittest -v tests.test_prime_resource_policy tests.test_prime_resource_alarms tests.test_prime_diagnostics tests.test_prime_application_entry tests.test_asterion_prime_context tests.test_asterion_prime_backend tests.test_asterion_prime_p1_operator tests.test_asterion_prime_p1_runtime tests.test_prime_ipython tests.test_prime_p7_diagnostics
make promotion-check
uv run python .asterion-private/task43-resource-policy/native/replay.py
make lint
make docs-check
```

Expected: all named portable tests PASS; root-owned fresh-wheel native witness PASS only with installed Pi available, both named cases pass, zero actual model requests. `make promotion-check` proves packaged resources and entry points, not request accounting. Do not replace these checks with an ARC level witness or start another full-model run.

- [ ] **Step 5: Record evidence and commit the completed first-two-increment boundary.**

State exactly: policy/capacity injection and safe alarm presentation implemented; named portable/fresh-wheel checks verified within their stated boundary; true request input bounds, actual native output limits, actual terminal usage settlement, retries and arbitrary-provider certification remain open. Preserve `External-limited` if native Pi unavailable; no paid run occurred. Existing context-memory/archive capacity expansion and complete shared-record trip coverage remain subsequent scoped work. Update only the current status/resume/index entries; do not invent a parallel status system.

```bash
git add src/asterion/applications/prime/resource_alarms.py src/asterion/applications/prime/p1/operator.py src/asterion/applications/prime/p7/operator.py src/asterion/agents/prime/execution.py src/asterion/agents/prime/tools.py src/asterion/agents/prime/ipython.py tests/test_prime_resource_alarms.py tests/test_asterion_prime_backend.py tests/test_prime_ipython.py tests/test_asterion_prime_runtime.py tests/test_prime_p7_diagnostics.py src/asterion/applications/prime/resources docs/status/CURRENT-STATE.md docs/status/RESUME-NEXT-SESSION.md docs/status/INDEX.md
git commit -m "feat(prime): surface safe resource alarms and packaged witness evidence"
```

## Separate third increment boundary

A separate plan is required after reliable provider-specific input-bound evidence exists. It must intercept actual native adapter payloads before transmission, bind effective system/messages/options/output caps, preserve auth/model/options, settle per-branch terminal usage, retain reservations after unknown results, authorize retries, and clean up/conflict-check the wrapper. The already verified public wrapper feasibility seam proves interception access only. No DeepSeek input bound has been verified to fit the P1 48k reservation; this plan does not pretend otherwise.

## Plan self-review and completion record

- Coverage: Task1 shared diagnostic/policy; Task2 capacities/identity/refusal transport; Task3 P1 and authority; Task4 visible/persisted safe alarms/package proof.
- Remaining boundary is explicit: actual requests/accounting and TS memory/archive unit/capacity work have separate verification and cannot be promoted by these tests.
- Old positional backend/diagnostic constructions remain supported. CLI quote input retains its old closed shape.
- Review focuses on code and fail-closed boundary assertions. Avoid exhaustive invented stress suites or extra architectural refactors.
- Root owns integration/commits and performs repository journal updates after each actual commit; plan commands are execution instructions, not commits already made by the planning worker.


Execution receipt: Task1 committed739f2caf; root80tests PASS and independent specification/code-quality review PASS. Task2 capacity transport in progress; no provider calls.
