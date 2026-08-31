# Asterion Native Verified-loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and evidence the first eleven Native Prime-parity rows, while keeping real model work behind a separately authorized finite bounded run.

**Architecture:** Extend the existing Native controller through focused durable feature services, not provider logic in the controller or manifests. Provider-free conformance and Prime differential observations prove nine rows. A host-injected bounded adapter, reservation, and redacted receipt fully implement the other two rows but cannot execute without explicit finite-budget authorization.

**Tech Stack:** Python 3.14, `unittest`, existing Asterion control protocol/factory/authority, pinned Prime fixtures, JSON-safe receipt reducers, Make.

## Global Constraints

- Baseline is `3th-party/prime-agent` commit `a18809e00ea30638584d87b3afea7285a9d7296c`; validate source, artifact, and module locks before every differential comparison.
- Framework modules remain domain-neutral; production Native modules do not import Prime source, test fixtures, or adjacent repositories.
- `NativeTurnAdapter` is injected. No controller/service reads environment variables, credentials, provider configuration, executable paths, or mutable manifest data.
- Provider-free commands, `make check`, `make promotion-check`, list/describe, and acceptance execute zero provider/model/credential/network/application/upload operations.
- Public values, reports, exceptions, and logs are body-free: no prompt, answer, raw provider payload, credential, private path, or raw output.
- IDs are canonical, arrays sorted/unique, values immutable; ambiguity and recovery uncertainty fail closed.
- `rlm.generated-program` and `operation.autonomous-quality` may be promoted only by a separately authorized finite receipt; no ordinary test invokes a real provider.
- Do not mark Native `Verified-loop` or individual Native ledger results as PASS before both evidence partitions pass on the same candidate.

---

## File structure

| File | Responsibility |
|---|---|
| `src/asterion/control/providers/native/verified.py` | Immutable Native session/RLM/operation feature records and deterministic reducer. |
| `src/asterion/control/providers/native/bounded.py` | Host-side bounded reservation, safe turn-adapter protocol, receipt validation and public reduction. |
| `src/asterion/control/providers/native/controller.py` | Routes validated feature commands through the existing persisted publish path. |
| `src/asterion/control/providers/native/factory.py` | Exact host preflight for optional bounded services. |
| `tests/test_native_verified_features.py` | Unit, conformance, recovery, and redaction matrices for nine provider-free rows. |
| `tests/test_native_verified_differential.py` | Pinned-Prime scenario mapping and zero-effect differential evidence. |
| `tests/test_native_bounded_turn.py` | Reservation, no-call-before-authority, redaction, and receipt matrices. |
| `tools/verify_native_verified_loop.py` | Exact public evidence reducer; never invokes a provider. |
| `tests/test_native_verified_loop_verification.py` | Reducer exactness, incomplete receipt rejection, and CLI safety. |

### Task 1: Add immutable verified records and session semantics

**Files:**
- Create: `src/asterion/control/providers/native/verified.py`
- Modify: `src/asterion/control/providers/native/controller.py`
- Modify: `src/asterion/control/providers/native/__init__.py`
- Test: `tests/test_native_verified_features.py`

**Interfaces:**
- Produces `NativeVerifiedFeatureRecord(feature_id: str, record_id: str, payload: Mapping[str, object])`.
- Produces `reduce_verified_feature_records(records: Sequence[NativeVerifiedFeatureRecord]) -> NativeVerifiedState`.
- Covers `session.persistence-naming`, `session.resume-delete`, `session.delivery`, and `session.usage-status`.

- [ ] **Step 1: Write failing immutable-record/session tests.**

```python
def test_session_delivery_and_usage_are_immutable_and_ordered() -> None:
    state = reduce_verified_feature_records(_session_records())
    assert state.session_projection("session-1")["deliveries"] == ("input-1",)
    assert state.session_projection("session-1")["total_tokens"] == 5
    with self.assertRaises(TypeError):
        state.session_projection("session-1")["session_id"] = "mutated"
```

- [ ] **Step 2: Run `uv run python -m unittest -v tests.test_native_verified_features.TestNativeVerifiedSessions`; expect import failure for `native.verified`.**

- [ ] **Step 3: Implement the closed record/reducer model.**

```python
@dataclass(frozen=True, repr=False)
class NativeVerifiedFeatureRecord:
    feature_id: str
    record_id: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.feature_id not in VERIFIED_FEATURE_IDS:
            raise NativeVerifiedFeatureError("native verified feature is invalid")
        _require_opaque(self.record_id)
        object.__setattr__(self, "payload", _freeze_safe_payload(self.payload))

def reduce_verified_feature_records(records: Sequence[NativeVerifiedFeatureRecord]) -> NativeVerifiedState:
    state = _MutableReduction.empty()
    for record in records:
        state.apply(record)
    return state.freeze()
```

Accept only canonical payload keys. Enforce stable digest-only names, exact selectors, active-delete rejection, monotonic usage, and direct/steer/follow-up ordering. Append through the existing controller publication path, never a second journal.

- [ ] **Step 4: Run `uv run python -m unittest -v tests.test_native_verified_features tests.test_native_control_controller`; expect PASS for malformed, duplicate, replay, restart, selector, ordering, and sentinel cases.**

- [ ] **Step 5: Commit.**

```bash
git add src/asterion/control/providers/native/verified.py src/asterion/control/providers/native/controller.py src/asterion/control/providers/native/__init__.py tests/test_native_verified_features.py
git commit -m "feat: add native verified session records"
```

### Task 2: Add RLM environment, usage, and recovery semantics

**Files:**
- Modify: `src/asterion/control/providers/native/verified.py`
- Test: `tests/test_native_verified_features.py`
- Test: `tests/test_native_control_process_recovery.py`

**Interfaces:**
- Consumes Task 1 records and produces `NativeVerifiedState.rlm_projection(environment_id: str) -> Mapping[str, object]`.
- Covers `rlm.environment`, `rlm.usage-cost`, and `rlm.recovery`; generated program remains Task 5.

- [ ] **Step 1: Write failing recovery/monotonicity tests.**

```python
def test_rlm_snapshot_recovery_preserves_environment_and_usage() -> None:
    state = reduce_verified_feature_records(_rlm_restart_records())
    assert state.rlm_projection("env-1")["cost_micros"] == 11
    with self.assertRaises(NativeVerifiedFeatureError):
        reduce_verified_feature_records(_usage_regression_records())
```

- [ ] **Step 2: Run `uv run python -m unittest -v tests.test_native_verified_features.TestNativeVerifiedRlm`; expect failure because RLM records are unsupported.**

- [ ] **Step 3: Add descriptor-only RLM reduction.**

```python
def _apply_rlm_record(self, record: NativeVerifiedFeatureRecord) -> None:
    environment_id = _opaque(record.payload, "environment_id")
    if record.feature_id == "rlm.environment":
        self.bind_environment(environment_id, _sha256(record.payload, "environment_digest"))
    elif record.feature_id == "rlm.usage-cost":
        self.add_usage(environment_id, _nonnegative(record.payload, "child_tokens"), _nonnegative(record.payload, "cost_micros"))
    else:
        self.restore_snapshot(environment_id, _sha256(record.payload, "snapshot_digest"))
```

Persist only descriptors/digests/counters. Require an exact contiguous pre-restart prefix; reject missing/conflicting snapshots, counter regression, and uncertainty.

- [ ] **Step 4: Run `uv run python -m unittest -v tests.test_native_verified_features tests.test_native_control_process_recovery`; expect PASS with zero external counters and no private sentinel leakage.**

- [ ] **Step 5: Commit.**

```bash
git add src/asterion/control/providers/native/verified.py tests/test_native_verified_features.py tests/test_native_control_process_recovery.py
git commit -m "feat: add native verified rlm recovery"
```

### Task 3: Add goal and detach/attach/replay semantics

**Files:**
- Modify: `src/asterion/control/providers/native/verified.py`
- Modify: `src/asterion/control/providers/native/controller.py`
- Test: `tests/test_native_verified_features.py`
- Test: `tests/test_native_control_conformance.py`

**Interfaces:**
- Produces `operation_projection(operation_id: str)` and exact exclusive-cursor replay.
- Covers `operation.goals` and `operation.detach-attach-replay`; autonomy receipt is Task 5.

- [ ] **Step 1: Write failing terminal/replay tests.**

```python
def test_goal_detach_attach_replay_has_one_terminal_history() -> None:
    state = reduce_verified_feature_records(_goal_history())
    assert state.operation_projection("operation-1")["goal_status"] == "succeeded"
    assert state.replay("operation-1", after_cursor=2) == _expected_suffix()
    with self.assertRaises(NativeVerifiedFeatureError):
        reduce_verified_feature_records(_second_terminal_history())
```

- [ ] **Step 2: Run `uv run python -m unittest -v tests.test_native_verified_features.TestNativeVerifiedOperations`; expect failure because operation records are unsupported.**

- [ ] **Step 3: Implement strict transition/cursor reduction.**

```python
def _apply_operation_record(self, record: NativeVerifiedFeatureRecord) -> None:
    operation_id = _opaque(record.payload, "operation_id")
    if record.feature_id == "operation.goals":
        self.transition_goal(operation_id, _goal_state(record.payload))
    else:
        self.append_operation_cursor(operation_id, _positive(record.payload, "cursor"), _sha256(record.payload, "event_digest"))
```

Require contiguous cursors, one terminal state, no terminal-to-active transition, and exact cursor suffixes. Recovery must use controller state so restart cannot create a second history.

- [ ] **Step 4: Run `uv run python -m unittest -v tests.test_native_verified_features tests.test_native_control_conformance`; expect PASS for detach-before-terminal, attach-after-restart, gaps, duplicates, double terminal, cancellation, and immutability.**

- [ ] **Step 5: Commit.**

```bash
git add src/asterion/control/providers/native/verified.py src/asterion/control/providers/native/controller.py tests/test_native_verified_features.py tests/test_native_control_conformance.py
git commit -m "feat: add native verified operation state"
```

### Task 4: Build nine-row pinned-Prime differential evidence and exact reducer

**Files:**
- Create: `tests/test_native_verified_differential.py`
- Create: `tools/verify_native_verified_loop.py`
- Create: `tests/test_native_verified_loop_verification.py`
- Modify: `Makefile`

**Interfaces:**
- Produces `run_native_verified_provider_free_observations() -> tuple[Mapping[str, object], ...]`.
- Produces `build_native_verified_loop_report(root: Path, *, observation_runner=..., bounded_receipt_loader=...) -> Mapping[str, object]`.
- Reports the nine provider-free rows and exactly two bounded rows as unpromoted/required.

- [ ] **Step 1: Write failing differential/reducer tests.**

```python
def test_provider_free_receipt_cannot_promote_bounded_rows() -> None:
    report = build_native_verified_loop_report(ROOT, observation_runner=_nine_passes, bounded_receipt_loader=lambda: None)
    assert report["provider_free_passed_feature_ids"] == list(PROVIDER_FREE_FEATURE_IDS)
    assert report["promoted_feature_ids"] == []
    assert report["status"] == "INCOMPLETE"
```

- [ ] **Step 2: Run `uv run python -m unittest -v tests.test_native_verified_differential tests.test_native_verified_loop_verification`; expect import failure.**

- [ ] **Step 3: Implement mapping and fail-closed reduction.**

```python
PROVIDER_FREE_SCENARIOS = {
    "prime-parity.session.persistence-naming": "session.persistence-naming",
    "prime-parity.session.resume-delete": "session.resume-delete",
    "prime-parity.session.delivery": "session.delivery",
    "prime-parity.session.usage-status": "session.usage-status",
    "prime-parity.rlm.environment": "rlm.environment",
    "prime-parity.rlm.usage-cost": "rlm.usage-cost",
    "prime-parity.rlm.recovery": "rlm.recovery",
    "prime-parity.operation.goals": "operation.goals",
    "prime-parity.operation.detach-attach-replay": "operation.detach-attach-replay",
}
```

Reuse test-side pinned identity validation only; production does not import Prime. Require one canonical observation per scenario, public projection equality, zero external counters, and sentinel scans.

- [ ] **Step 4: Add and run the provider-free target.**

```make
.PHONY: test.native-verified-loop.provider-free
test.native-verified-loop.provider-free:
	$(UV_BIN) run python -m unittest -v tests.test_native_verified_features tests.test_native_verified_differential tests.test_native_verified_loop_verification
	$(UV_BIN) run python tools/verify_native_verified_loop.py --level provider-free
```

Run: `make test.native-verified-loop.provider-free`

Expected: PASS command with nine provider-free rows, two explicit bounded gaps, no promoted features, zero external counters.

- [ ] **Step 5: Commit.**

```bash
git add tests/test_native_verified_differential.py tools/verify_native_verified_loop.py tests/test_native_verified_loop_verification.py Makefile
git commit -m "test: add native verified-loop provider-free receipt"
```

### Task 5: Implement dormant bounded turn authority and receipt reconciliation

**Files:**
- Create: `src/asterion/control/providers/native/bounded.py`
- Modify: `src/asterion/control/providers/native/factory.py`
- Modify: `src/asterion/control/providers/native/turn.py`
- Modify: `tools/verify_native_verified_loop.py`
- Test: `tests/test_native_bounded_turn.py`
- Test: `tests/test_native_control_factory.py`
- Test: `tests/test_native_verified_loop_verification.py`

**Interfaces:**
- Produces `NativeBoundedReservation`, `NativeBoundedTurnHost`, and `NativeBoundedReceipt`.
- Produces `run_bounded_native_turn(reservation, host, request) -> NativeBoundedReceipt` only after injected exact reservation.
- Covers receipt facts for `rlm.generated-program` and `operation.autonomous-quality` without executing either during tests.

- [ ] **Step 1: Write failing authority/no-call/redaction tests.**

```python
def test_missing_reservation_never_calls_host() -> None:
    host = RecordingBoundedHost()
    with self.assertRaises(NativeBoundedTurnError):
        asyncio.run(run_bounded_native_turn(None, host, REQUEST))
    self.assertEqual(host.calls, 0)
```

- [ ] **Step 2: Run `uv run python -m unittest -v tests.test_native_bounded_turn`; expect import failure.**

- [ ] **Step 3: Implement immutable reservation and injection boundary.**

```python
@dataclass(frozen=True, repr=False)
class NativeBoundedReservation:
    reservation_id: str
    provider_digest: str
    model_digest: str
    max_turns: int
    max_cost_micros: int
    deadline_ms: int

async def run_bounded_native_turn(reservation, host, request):
    _validate_live_reservation(reservation, request)
    return _validate_private_receipt(await host.execute(reservation, request), reservation)
```

Only exact factory preflight can inject `NativeBoundedTurnHost`; it owns private configuration. Persist only digest/boolean/counter facts. Reject mismatch identities, duplicate turns, extra terminals, overage, uncertainty, and private sentinels. Do not create a default host or read an environment variable.

- [ ] **Step 4: Run `uv run python -m unittest -v tests.test_native_bounded_turn tests.test_native_control_factory tests.test_native_verified_loop_verification`; expect PASS with no model/provider/network operation.**

- [ ] **Step 5: Commit.**

```bash
git add src/asterion/control/providers/native/bounded.py src/asterion/control/providers/native/factory.py src/asterion/control/providers/native/turn.py tools/verify_native_verified_loop.py tests/test_native_bounded_turn.py tests/test_native_control_factory.py tests/test_native_verified_loop_verification.py
git commit -m "feat: add bounded native turn receipt boundary"
```

### Task 6: Integrate provider-free closure and leave explicit authorization gate

**Files:**
- Modify: `Makefile`
- Modify: `docs/status/PRIME-PARITY-LEDGER.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/climb/session-state.json`
- Test: `tests/test_native_verified_loop_verification.py`

**Interfaces:**
- Provider-free command: `make test.native-verified-loop.provider-free`.
- Bounded command: `uv run python tools/verify_native_verified_loop.py --level bounded --reservation <opaque-id>`; it is `External-limited` without operator host authority.

- [ ] **Step 1: Write failing command safety test.**

```python
def test_bounded_cli_without_reservation_is_external_limited_and_safe() -> None:
    completed = subprocess.run(BOUNDED_COMMAND, text=True, capture_output=True)
    self.assertEqual(completed.returncode, 1)
    self.assertEqual(json.loads(completed.stdout)["status"], "External-limited")
```

- [ ] **Step 2: Run `uv run python -m unittest -v tests.test_native_verified_loop_verification`; expect failure until CLI preflight is wired.**

- [ ] **Step 3: Wire truthful state and a non-executing Make guard.**

```make
.PHONY: verify.native-verified-loop.bounded
verify.native-verified-loop.bounded:
	@echo "Use explicit verifier with an operator-approved reservation; this target does not execute a provider."
	@exit 1
```

Ledger state is “implemented/provider-free evidenced; Native `Verified-loop` Missing.” Set Climb next action to explicit bounded authorization. Do not mark any Native feature passed and do not contact a real host.

- [ ] **Step 4: Run closure matrix.**

```bash
make test.native-controller-core.provider-free
make test.native-verified-loop.provider-free
uv run python tools/verify_native_verified_loop.py --level provider-free
make check
make promotion-check
git diff --check
git status --short --branch
git worktree list --porcelain
git branch --all --no-color
```

Expected: all safe checks PASS; receipt has nine provider-free rows and two bounded gaps, zero external counters, clean `main`, and no branch/worktree residue.

- [ ] **Step 5: Commit and journal exact provider-free status.**

```bash
git add Makefile docs/status/PRIME-PARITY-LEDGER.md docs/status/RESUME-NEXT-SESSION.md docs/status/climb/session-state.json tests/test_native_verified_loop_verification.py
git commit -m "docs: record native verified-loop provider-free boundary"
```

## Explicit authorization checkpoint

Do not execute this checkpoint as part of the plan. After Tasks 1–6 pass, request a new operator approval with finite provider/model budget, maximum turns, maximum cost, deadline, and one-run scope. Only then may the injected host run:

```bash
uv run python tools/verify_native_verified_loop.py --level bounded --reservation <opaque-id>
```

Reduce the private receipt and rerun both partitions on the same candidate. Any absent, uncertain, out-of-budget, or redaction-unsafe fact remains `External-limited`/`INCOMPLETE`; keep Native `Verified-loop` Missing and never retry under the same reservation.

## Self-review

- Tasks 1–3 deliver the nine provider-free feature surfaces; Task 4 locks their Prime differential evidence; Task 5 implements the two-row bounded path without execution; Task 6 preserves truthful state and repository closure.
- Every task has exact files, interfaces, a failing test, command, implementation shape, regression command, and commit.
- Task 1 produces records consumed by Tasks 2–4; Task 5 produces bounded receipt data consumed by Task 4's reducer and Task 6's CLI boundary.
