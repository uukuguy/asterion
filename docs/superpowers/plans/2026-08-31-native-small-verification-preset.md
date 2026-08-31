# Native Small Verification Preset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose one user-simple, single-use Native small-verification action while retaining operator-owned finite execution controls.

**Architecture:** A closed immutable preset is resolved by an injected operator host. The framework never selects a provider, reads configuration, or creates a host. Without the injected resolver, the verifier returns `External-limited`; ordinary provider-free checks remain provider-free.

**Tech Stack:** Python 3.12, `unittest`, existing Native turn adapters, JSON-safe verifier, Make.

## Global Constraints

- The user-facing action accepts no provider, model, cost, or deadline values.
- Operator-owned code supplies the host and finite controls; framework code reads no credentials, environment values, provider configuration, or executable paths.
- A preset permits exactly one turn and one terminal result; invalid, duplicate, mismatched, over-budget, or redaction-unsafe execution fails closed.
- Provider-free commands, `make check`, and `make promotion-check` perform zero provider/model/credential/network/application/upload operations.
- Native `Verified-loop` remains Missing unless complete bounded and provider-free partitions pass on the same candidate.

---

## File structure

| File | Responsibility |
|---|---|
| `src/asterion/control/providers/native/bounded.py` | Closed preset/resolver protocol and one-use adapter validation. |
| `tools/verify_native_verified_loop.py` | Public `small-verification` preflight. |
| `tests/test_native_bounded_turn.py` | Preset no-call, single-use, overage, and redaction tests. |
| `tests/test_native_verified_loop_verification.py` | CLI `External-limited` safety test. |
| `Makefile` | Non-executing small-verification guard. |
| status docs | Truthful implemented-but-unconfigured boundary. |

### Task 1: Add the closed operator-owned preset resolver

**Files:**
- Modify: `src/asterion/control/providers/native/bounded.py`
- Modify: `tests/test_native_bounded_turn.py`

**Interfaces:**
- Produces `NativeSmallVerificationPresetResolver.resolve() -> tuple[NativeBoundedReservation, NativeBoundedTurnHost]`.
- Produces `BoundedNativeTurnAdapter.from_small_verification_preset(resolver) -> BoundedNativeTurnAdapter`.

- [ ] **Step 1: Write failing preset tests.**

```python
def test_small_preset_resolver_returns_one_exact_reservation_and_host(self) -> None:
    resolver = RecordingPresetResolver(reservation=RESERVATION, host=host)
    adapter = BoundedNativeTurnAdapter.from_small_verification_preset(resolver)
    self.assertEqual(adapter.adapter_id, "native.bounded-turn/v1")
    self.assertEqual(resolver.calls, 1)

def test_invalid_small_preset_never_calls_turn_host(self) -> None:
    resolver = RecordingPresetResolver(reservation=None, host=RecordingBoundedHost())
    with self.assertRaises(NativeBoundedTurnError):
        BoundedNativeTurnAdapter.from_small_verification_preset(resolver)
    self.assertEqual(resolver.host.calls, 0)
```

- [ ] **Step 2: Verify RED.**

```bash
uv run python -m unittest -v tests.test_native_bounded_turn.TestNativeBoundedTurn.test_small_preset_resolver_returns_one_exact_reservation_and_host tests.test_native_bounded_turn.TestNativeBoundedTurn.test_invalid_small_preset_never_calls_turn_host
```

Expected: FAIL because the protocol and class method do not exist.

- [ ] **Step 3: Add minimal injected resolver support.**

```python
class NativeSmallVerificationPresetResolver(Protocol):
    def resolve(self) -> tuple[NativeBoundedReservation, NativeBoundedTurnHost]: ...

@classmethod
def from_small_verification_preset(
    cls, resolver: NativeSmallVerificationPresetResolver
) -> "BoundedNativeTurnAdapter":
    resolve = getattr(resolver, "resolve", None)
    if not callable(resolve):
        raise NativeBoundedTurnError
    try:
        reservation, host = resolve()
    except Exception:
        raise NativeBoundedTurnError from None
    return cls(reservation, host)
```

Require `max_turns == 1` in `_valid_reservation`, because an attempted turn consumes the reservation.

- [ ] **Step 4: Verify GREEN.**

```bash
uv run python -m unittest -v tests.test_native_bounded_turn
```

Expected: PASS with zero external operations.

- [ ] **Step 5: Commit.**

```bash
git add src/asterion/control/providers/native/bounded.py tests/test_native_bounded_turn.py
git commit -m "feat: add native small verification preset"
```

### Task 2: Add the public non-executing preflight

**Files:**
- Modify: `tools/verify_native_verified_loop.py`
- Modify: `tests/test_native_verified_loop_verification.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes `--level small-verification` and no user provider/budget arguments.
- Produces exact body-free `{"level":"small-verification","promoted_feature_ids":[],"status":"External-limited"}` when no operator resolver is injected.

- [ ] **Step 1: Write the failing CLI test.**

```python
def test_small_verification_cli_has_no_provider_or_budget_inputs(self) -> None:
    completed = subprocess.run(
        ["uv", "run", "python", "tools/verify_native_verified_loop.py", "--level", "small-verification"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    self.assertEqual(completed.returncode, 1)
    self.assertEqual(json.loads(completed.stdout), {
        "level": "small-verification", "promoted_feature_ids": [], "status": "External-limited",
    })
    self.assertNotIn("reservation", completed.stdout)
```

- [ ] **Step 2: Verify RED.**

```bash
uv run python -m unittest -v tests.test_native_verified_loop_verification.TestNativeVerifiedLoopVerification.test_small_verification_cli_has_no_provider_or_budget_inputs
```

Expected: FAIL because the level is rejected.

- [ ] **Step 3: Implement the preflight and guard.**

```python
parser.add_argument("--level", choices=("provider-free", "bounded", "small-verification"), required=True)
if arguments.level == "small-verification":
    print(json.dumps({"level": "small-verification", "promoted_feature_ids": [], "status": "External-limited"}, sort_keys=True, separators=(",", ":")))
    return 1
```

Remove `--reservation`; it is an internal authority primitive. Add `verify.native-verified-loop.small` that prints a fixed non-execution message and exits 1.

- [ ] **Step 4: Verify GREEN.**

```bash
uv run python -m unittest -v tests.test_native_verified_loop_verification
make test.native-verified-loop.provider-free
make verify.native-verified-loop.small
```

Expected: tests/provider-free target PASS; the guard exits 1 without a host call.

- [ ] **Step 5: Commit.**

```bash
git add tools/verify_native_verified_loop.py tests/test_native_verified_loop_verification.py Makefile
git commit -m "feat: add native small verification preflight"
```

### Task 3: Close truthful status and repository checks

**Files:**
- Modify: `docs/status/PRIME-PARITY-LEDGER.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/climb/session-state.json`
- Modify: `docs/status/JOURNAL.md`
- Modify: `tests/test_prime_climb.py`

**Interfaces:**
- Records that the preset is implemented but no operator resolver/host is configured.
- Keeps Native `Verified-loop` Missing and bounded features External-limited.

- [ ] **Step 1: Write a failing state test.**

```python
def test_native_verified_loop_small_preset_remains_external_limited(self) -> None:
    state = json.loads((ROOT / "docs/status/climb/session-state.json").read_text())
    self.assertEqual(state["next_action"], "phase-3.2-native-small-verification-host")
    self.assertNotIn("Native Verified-loop", _passed_ledger_claims())
```

- [ ] **Step 2: Verify RED.**

```bash
uv run python -m unittest -v tests.test_prime_climb.TestPrimeClimb.test_native_verified_loop_small_preset_remains_external_limited
```

Expected: FAIL because the successor is not recorded.

- [ ] **Step 3: Record the boundary.**

Set successor `phase-3.2-native-small-verification-host`; do not modify the generated historical H-038 tree. State that the absent host means no real run and no promotion.

- [ ] **Step 4: Verify closure.**

```bash
make test.native-controller-core.provider-free
make test.native-verified-loop.provider-free
make check
make promotion-check
git diff --check
git status --short --branch
```

Expected: executable checks PASS, promotion reports zero provider operations, and bounded status remains `External-limited`.

- [ ] **Step 5: Commit and journal.**

```bash
git add docs/status/PRIME-PARITY-LEDGER.md docs/status/RESUME-NEXT-SESSION.md docs/status/CURRENT-STATE.md docs/status/climb/session-state.json tests/test_prime_climb.py
git commit -m "docs: record native small verification boundary"
```

Append one ≤20-word `JOURNAL.md` line with the commit hash, then rewrite the live RESUME checkpoint because the recovery successor changed.

## Self-review

- Tasks cover user-simple action, operator-owned finite controls, no-call failures, single-use reservations, redaction, and truthful evidence state.
- No framework component imports provider configuration or reads credentials.
- The plan does not execute a real provider; a later operator/application host integration remains required.
