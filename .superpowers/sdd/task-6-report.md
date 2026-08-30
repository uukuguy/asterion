# Task 6 Report - Asynchronous Native Control Client

## Summary

Implemented Task 6 only: `NativeControlPlaneClient` and its focused client
tests. The client exposes the native controller through the public async
`ControlPlaneClient` shape plus `sync_authority_snapshot()`, with one
`asyncio.Lock` guarding controller state and no lock held across adapter awaits
or public event yields.

## Files

- Created `src/asterion/control/providers/native/client.py`
- Created `tests/test_native_control_client.py`

No prior native task files were edited.

## RED Evidence

Command:

```bash
uv run python -m unittest -v tests.test_native_control_client
```

Result: RED as required, exit 1, failed during import with:

```text
ModuleNotFoundError: No module named 'asterion.control.providers.native.client'
```

## GREEN Evidence

Focused client tests:

```bash
uv run python -m unittest -v tests.test_native_control_client
```

Result: PASS, exit 0, 13 tests, OK.

Required controller plus client brief command:

```bash
uv run python -m unittest -v tests.test_native_control_controller tests.test_native_control_client
```

Result: PASS, exit 0, 37 tests, OK.

Task 2-6 native suite:

```bash
uv run python -m unittest -v tests.test_native_control_model tests.test_native_control_store tests.test_native_control_capsule tests.test_native_control_controller tests.test_native_control_client
```

Result: PASS, exit 0, 122 tests, OK.

Static checks:

```bash
uv run ruff check src/asterion/control/providers/native/client.py tests/test_native_control_client.py
```

Result: PASS, exit 0, `All checks passed!`.

```bash
uv run pyright src/asterion/control/providers/native/client.py tests/test_native_control_client.py
```

Result: PASS, exit 0, `0 errors, 0 warnings, 0 informations`.

```bash
uv run python -m py_compile src/asterion/control/providers/native/client.py tests/test_native_control_client.py
```

Result: PASS, exit 0.

## Requirement Coverage

- Exact `ControlPlaneManifest`, `NativeController`, `ControlCommand`,
  `EventCursor`, and `RemainingBudget` types are checked before public effects.
- `NativeControlError` is fixed, context-free, and body-free at public
  boundaries.
- `send()` persists through the controller before returning; equal command
  retries are idempotent and conflicts fail closed through the controller.
- Authority snapshots are exact-type checked and equal retries are idempotent.
- `close()` delegates once through the controller and is idempotent after
  success; post-close sends, syncs, new iterators, and pre-created iterators all
  reject.
- Event iteration snapshots under the lock, yields outside it, observes host
  sends during yield, advances to quiescence, and avoids duplicate yields.
- Turn advancement is bounded by exact positive JS-safe
  `max_turns_per_poll`/`max_events_per_poll` values.
- Budget-limited turns commit without invoking the adapter.
- Normal turns begin under lock, await the adapter outside the lock, then
  reacquire and commit the exact pending result.
- Adapter exceptions and invalid/over-budget results commit exactly one
  recovery projection when the original turn is still pending.
- A concurrent `session.cancel` during adapter suspension acquires the lock,
  commits the terminal cancellation, fences the started turn, and causes the
  late adapter result to be discarded without a result, recovery, or second
  terminal.
- Different pending-turn mismatch fails closed as transport uncertainty.
- Tests use deterministic barriers/events and timeouts for concurrency races.

## Scope Notes

No provider, network, model, credential, upload, application execution, or
H-038 promotion operation was performed.

## Fix Wave 1 - In-Flight Turn Ownership

### Blocker

A concurrent `events()` iterator could observe a pending turn while another
iterator was already awaiting the adapter for that exact request. Because the
client had no ownership claim around the adapter await, both iterators could
execute the same turn and race the durable commit/recovery boundary. `close()`
also closed controller resources immediately instead of waiting for the
in-flight adapter settlement.

### RED Evidence

Command:

```bash
uv run python -m unittest -v tests.test_native_control_client
```

Result: RED, exit 1. New regressions failed because concurrent iterators
re-executed a suspended turn, close completed before adapter settlement, and
iterator cancellation left the turn re-executable.

### Fix

- Added a client-owned `_in_flight_turn` claim protected by the existing
  `asyncio.Lock`.
- Concurrent iterators stop at quiescence when another iterator owns the
  pending request instead of invoking the adapter.
- All commit/fail/terminal-discard/cancellation paths clear the claim and
  notify waiters.
- Iterator task cancellation durably fences a still-pending turn via safe
  recovery and re-raises `asyncio.CancelledError` unconverted.
- `close()` marks closing under lock, rejects new public operations, waits for
  in-flight settlement with the lock released, then closes controller resources
  exactly once.

### GREEN Evidence

Focused client tests:

```bash
uv run python -m unittest -v tests.test_native_control_client
```

Result: PASS, exit 0, 18 tests, OK.

Task 2-6 native suite:

```bash
uv run python -m unittest -v tests.test_native_control_model tests.test_native_control_store tests.test_native_control_capsule tests.test_native_control_controller tests.test_native_control_client
```

Result: PASS, exit 0, 127 tests, OK.

Static checks:

```bash
uv run ruff check src/asterion/control/providers/native/client.py tests/test_native_control_client.py
uv run pyright src/asterion/control/providers/native/client.py tests/test_native_control_client.py
uv run python -m py_compile src/asterion/control/providers/native/client.py tests/test_native_control_client.py
```

Results: Ruff passed; Pyright reported `0 errors, 0 warnings, 0 informations`
plus its version notice; `py_compile` passed.

### Scope Notes

No provider, network, model, credential, upload, application execution, Prime,
DCI, H-038 promotion, JOURNAL, or tracked report operation was performed.

## Fix Wave 2 - Poison Uncertain In-Flight Settlement

### Blocker

After Fix Wave 1, an in-flight turn claim could still be cleared while the
same unfenced pending request remained in the controller if cancellation
recovery or ordinary adapter/result recovery could not durably write
`fail_turn()`. A later iterator could then re-execute the same uncertain turn.

### RED Evidence

Command:

```bash
uv run python -m unittest -v tests.test_native_control_client
```

Result: RED, exit 1. The new regressions failed because cancellation
recovery, adapter-exception recovery, and invalid-result recovery each allowed
the claim to clear healthy after injected `fail_turn()` failure, permitting a
later events poll to re-enter the same pending turn.

### Fix

- Added a permanent client-local poisoned/unavailable state.
- Public `send()`, `sync_authority_snapshot()`, `events()`, and iterator
  advances now reject with fixed `NativeControlError` once poisoned, with no
  controller effects.
- Claim clearing now atomically poisons under the existing client lock whenever
  the exact in-flight request is still the same unfenced pending turn.
- Cancellation recovery still preserves the original `asyncio.CancelledError`,
  but poisons before waking waiters if durable `fail_turn()` cannot be written.
- Ordinary adapter exception, invalid result, and budget-limited settlement
  uncertainty paths also poison before clearing the in-flight claim.
- `close()` remains available after poison, wakes from in-flight settlement,
  closes controller resources once, and remains idempotent.

### GREEN Evidence

Focused client tests:

```bash
uv run python -m unittest -v tests.test_native_control_client
```

Result: PASS, exit 0, 22 tests, OK.

Task 2-6 native suite:

```bash
uv run python -m unittest -v tests.test_native_control_model tests.test_native_control_store tests.test_native_control_capsule tests.test_native_control_controller tests.test_native_control_client
```

Result: PASS, exit 0, 131 tests, OK.

Static checks:

```bash
uv run ruff check src/asterion/control/providers/native/client.py tests/test_native_control_client.py
uv run pyright src/asterion/control/providers/native/client.py tests/test_native_control_client.py
uv run python -m py_compile src/asterion/control/providers/native/client.py tests/test_native_control_client.py
git diff --check
```

Results: Ruff passed; Pyright reported `0 errors, 0 warnings, 0 informations`
plus its version notice; `py_compile` passed; `git diff --check` passed.

### Scope Notes

Only `src/asterion/control/providers/native/client.py`,
`tests/test_native_control_client.py`, and this ignored Task 6 report were
changed for Fix Wave 2. Existing tracked `docs/status/JOURNAL.md` changes were
left untouched.

## Fix Wave 3 - Process-Control Adapter Abort Cleanup

### Blocker

The adapter execution wrapper still caught ordinary `Exception` paths only.
Exact process-control `BaseException` exits such as `KeyboardInterrupt`,
`SystemExit`, and `GeneratorExit`, plus custom hostile `BaseException`
subclasses, could bypass in-flight ownership settlement. That left the client
able to leak sentinel exception bodies or keep close waiters blocked on a stuck
claim.

### RED Evidence

Focused new regressions:

```bash
uv run python -m unittest -v tests.test_native_control_client.TestNativeControlClient.test_exact_process_control_from_adapter_is_sanitized_after_cleanup tests.test_native_control_client.TestNativeControlClient.test_custom_base_exception_from_adapter_is_normalized_and_poisoned tests.test_native_control_client.TestNativeControlClient.test_custom_base_exception_wakes_close_and_blocks_second_iterator tests.test_native_control_client.TestNativeControlClient.test_terminal_cancel_fences_base_exception_without_poisoning_client
```

Result: RED, exit 1. Exact built-ins leaked `SENTINEL_SECRET` args and custom
`BaseException` propagated through the public iterator path instead of being
normalized; in-flight cleanup was not guaranteed on these exits.

### Fix

- Added an adapter `BaseException` cleanup path after the existing
  `asyncio.CancelledError` and ordinary `Exception` handling.
- Non-cancellation adapter aborts now settle the in-flight claim under the
  existing client lock, notify waiters, and poison unless the exact turn was
  already terminal-fenced.
- The client does not call `fail_turn()` for arbitrary process-control aborts,
  avoiding swallowed process-control recovery writes.
- Exact `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit` propagate as
  fresh exact built-ins with empty args and cleared cause/context.
- Custom hostile `BaseException` subclasses normalize to fixed unchained
  `NativeControlError` without constructing or stringifying the hostile type.
- Terminal-cancel fencing during a suspended adapter abort still discards
  healthy without recovery or re-execution.

### GREEN Evidence

Focused new regressions:

```bash
uv run python -m unittest -v tests.test_native_control_client.TestNativeControlClient.test_exact_process_control_from_adapter_is_sanitized_after_cleanup tests.test_native_control_client.TestNativeControlClient.test_custom_base_exception_from_adapter_is_normalized_and_poisoned tests.test_native_control_client.TestNativeControlClient.test_custom_base_exception_wakes_close_and_blocks_second_iterator tests.test_native_control_client.TestNativeControlClient.test_terminal_cancel_fences_base_exception_without_poisoning_client
```

Result: PASS, exit 0, 4 tests, OK.

Focused client tests:

```bash
uv run python -m unittest -v tests.test_native_control_client
```

Result: PASS, exit 0, 26 tests, OK.

Task 2-6 native suite:

```bash
uv run python -m unittest -v tests.test_native_control_model tests.test_native_control_store tests.test_native_control_capsule tests.test_native_control_controller tests.test_native_control_client
```

Result: PASS, exit 0, 135 tests, OK.

Static checks:

```bash
uv run ruff check src/asterion/control/providers/native/client.py tests/test_native_control_client.py
uv run pyright src/asterion/control/providers/native/client.py tests/test_native_control_client.py
uv run python -m py_compile src/asterion/control/providers/native/client.py tests/test_native_control_client.py
git diff --check
```

Results: Ruff passed; Pyright reported `0 errors, 0 warnings, 0 informations`
plus its version notice; `py_compile` passed; `git diff --check` passed.

### Scope Notes

Only `src/asterion/control/providers/native/client.py`,
`tests/test_native_control_client.py`, and this tracked Task 6 report were
changed for Fix Wave 3. Existing tracked `docs/status/JOURNAL.md` changes were
left unstaged.
