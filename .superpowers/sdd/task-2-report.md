# Task 2 Report: Extract the domain-neutral Pi RPC session

## Scope

Implemented the common Asterion Pi JSONL-RPC process/session lifecycle and
rebound the existing DCI `PiRpcClient` facade to that transport. The shared
module owns only literal process invocation, JSONL framing, prompt response
matching, immutable event publication, deadlines, cancellation, output caps,
and bounded cleanup. DCI command construction, Node/provider configuration,
context-profile interpretation, observation configuration, Pathlight entry
validation, prompt recovery, and session-entry interpretation remain in the
DCI package.

No Prime Agent source, SDK, checkout, or source lock is imported, inspected,
loaded, launched, or required by the common transport. The common transport
does not read `.env`, ambient credentials, or provider settings.

## Files changed

- `src/asterion/runtimes/pi_rpc.py` (created): immutable `PiRpcConfig`,
  `PiRpcEvent`, and `PiRpcResult`; reusable `PiRpcSession` process and JSONL
  transport; async one-prompt `run()` lifecycle.
- `tests/test_pi_session.py` (created): lifecycle, immutability, sequence,
  literal argv, malformed JSON, EOF, response mismatch, ACK/terminal,
  stdout/final-text/stderr caps, deadline, cancellation, and bounded cleanup.
- `src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py`: DCI facade
  now creates and delegates process I/O and cleanup to `PiRpcSession`; all
  DCI-specific interpretation stays local.
- `tests/test_dci_pi_rpc_proxy.py`: asserts the exact DCI command and copied
  child environment are bound into the common session.
- `tests/test_dci_pi_rpc_recovery.py`: asserts existing recovery JSON frames
  flow byte-for-byte through the common transport seam.

## TDD RED evidence

Exact command:

```text
uv run python -m unittest -v tests.test_pi_session
```

Output:

```text
test_pi_session (unittest.loader._FailedTest.test_pi_session) ... ERROR
ModuleNotFoundError: No module named 'asterion.runtimes.pi_rpc'
Ran 1 test in 0.000s
FAILED (errors=1)
```

Reason: the new focused suite imported the specified common transport API
before that module existed.

The DCI delegation seam was also observed RED before rebinding:

```text
AttributeError: ... dci.implementation.runtime.pi_rpc does not have the
attribute 'PiRpcSession'
RuntimeError: RPC client is not running
Ran 2 tests ... FAILED (errors=2)
```

A self-review regression for stderr overflow was observed RED before the
post-drain error gate was added:

```text
test_stderr_cap_fails_closed_even_when_stdout_settles ... FAIL
AssertionError: RuntimeError not raised
Ran 1 test ... FAILED (failures=1)
```

## GREEN verification

Exact combined command from the brief:

```text
uv run python -m unittest -v tests.test_pi_session tests.test_dci_pi_rpc_proxy tests.test_dci_pi_rpc_recovery tests.test_dci_pi_rpc_observation
```

Output summary:

```text
Ran 32 tests in 1.067s
OK
```

Additional checks:

```text
uv run ruff check src/asterion/runtimes/pi_rpc.py src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py tests/test_pi_session.py tests/test_dci_pi_rpc_proxy.py tests/test_dci_pi_rpc_recovery.py
All checks passed!

uv run python -m py_compile src/asterion/runtimes/pi_rpc.py src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py tests/test_pi_session.py tests/test_dci_pi_rpc_proxy.py tests/test_dci_pi_rpc_recovery.py
PASS

git diff --check -- src/asterion/runtimes/pi_rpc.py src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py tests/test_pi_session.py tests/test_dci_pi_rpc_proxy.py tests/test_dci_pi_rpc_recovery.py
PASS
```

## Self-review

- Dependency direction is preserved: DCI imports the domain-neutral runtime;
  the runtime imports no capability, application, DCI, Prime, provider, or
  Pathlight module.
- The child environment is copied and frozen at configuration construction;
  event payloads are recursively frozen; results expose tuples and bytes.
- Prompt response IDs must match exactly, sequences are contiguous from one,
  and success requires an ACK followed by `agent_settled`.
- Malformed/non-object JSON, premature EOF, mismatched responses, output-cap
  excess, deadline, and cancellation fail closed.
- Cancellation emits a literal abort frame where possible. Cleanup closes
  stdin, waits briefly, terminates, kills if necessary, joins drain threads,
  and reports an unresolved cleanup timeout.
- DCI retains its existing command ordering, copied proxy/private observation
  environment, sorted unique inherited-FD union, `get_state`/`get_entries`
  validation, max-turn behavior, recovery prompts, and streaming/tool output.
- DCI stderr remains available after stop through a retained byte snapshot.
- Only the five assigned implementation/test files are staged for the task
  commit; unrelated dirty and untracked workspace state is untouched.

## Concerns

No known concern within the requested boundary. The exact focused suite was
run; the repository-wide `make test`/`make check` were intentionally not run
because the brief requested the four-module combined suite and the workspace
contains unrelated concurrent changes.

## Review-fix follow-up

### Scope

Resolved all four review findings without expanding beyond the five owned
implementation/test files:

1. Added one common `drive_prompt` lifecycle and `PiRpcPromptControl` for
   response matching, deadline accounting, cancellation polling, abort
   emission, and bounded settled-state waits. Both `PiRpcSession.run()` and
   the DCI facade now consume it. DCI retains only streaming, max-turn,
   recovery, provider-error, and settled-state interpretation.
2. Replaced session-global drain state with per-launch `_ProcessState` captured
   by each reader. Cleanup now starts a distinct process group, escalates
   terminate/kill to that group, explicitly closes pipe descriptors to unblock
   readers, verifies both joins, retains unresolved process/thread state, and
   rejects reuse until cleanup succeeds. The DCI facade likewise retains a
   transport whose cleanup failed.
3. Restricted immutable event payloads to recursively frozen, finite,
   JSON-compatible values. Mutable/opaque leaves, non-string keys, cycles, and
   non-finite floats fail closed.
4. Added direct aggregate stdout-byte and total event-count limit tests.

### RED evidence

The first review regression command covered lifecycle delegation, stuck-reader
cleanup, immutable leaves, and both missing direct cap tests:

```text
uv run python -m unittest -v \
  tests.test_pi_session.PiRpcSessionTests.test_events_reject_non_json_mutable_leaves \
  tests.test_pi_session.PiRpcSessionTests.test_aggregate_stdout_byte_cap_fails_closed \
  tests.test_pi_session.PiRpcSessionTests.test_event_count_cap_fails_closed \
  tests.test_pi_session.PiRpcSessionTests.test_unresolved_reader_cleanup_is_reported_and_blocks_state_reuse \
  tests.test_dci_pi_rpc_recovery.DciPiRpcRecoveryTests.test_prompt_lifecycle_is_driven_only_by_common_transport
```

Observed output:

```text
mutable bytearray/set/object: FAIL (ValueError not raised)
unresolved reader cleanup: FAIL (RuntimeError not raised)
DCI lifecycle delegation: FAIL (AssertionError: direct send)
aggregate stdout byte cap: PASS on first execution
event count cap: PASS on first execution
Ran 5 tests ... FAILED (failures=5)
```

The last two were coverage-only findings: their production guards already
existed. A mutation check raised both guards above the fake workload and
proved the new tests produce RED when either protection is absent:

```text
test_aggregate_stdout_byte_cap_fails_closed ... FAIL
test_event_count_cap_fails_closed ... FAIL
Ran 2 tests in 0.065s
FAILED (failures=2)
EXPECTED MUTATION RED
```

Facade-level cleanup retention also went RED before its fix:

```text
test_failed_common_cleanup_keeps_transport_for_a_bounded_retry ... FAIL
AssertionError: None is not <MagicMock ...>
Ran 1 test ... FAILED (failures=1)
```

### GREEN evidence

Focused review regressions after implementation:

```text
test_events_reject_non_json_mutable_leaves ... ok
test_unresolved_reader_cleanup_is_reported_and_blocks_state_reuse ... ok
test_prompt_lifecycle_is_driven_only_by_common_transport ... ok
Ran 3 tests in 0.003s
OK

test_failed_common_cleanup_keeps_transport_for_a_bounded_retry ... ok
Ran 1 test in 0.002s
OK
```

Exact combined command, with resource leaks promoted to errors:

```text
uv run python -W error::ResourceWarning -m unittest -v tests.test_pi_session tests.test_dci_pi_rpc_proxy tests.test_dci_pi_rpc_recovery tests.test_dci_pi_rpc_observation
Ran 39 tests in 1.212s
OK
```

Review-fix static verification:

```text
uv run ruff check src/asterion/runtimes/pi_rpc.py src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py tests/test_pi_session.py tests/test_dci_pi_rpc_proxy.py tests/test_dci_pi_rpc_recovery.py
All checks passed!

uv run python -m py_compile src/asterion/runtimes/pi_rpc.py src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py tests/test_pi_session.py tests/test_dci_pi_rpc_proxy.py tests/test_dci_pi_rpc_recovery.py
PASS

git diff --check -- src/asterion/runtimes/pi_rpc.py src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py tests/test_pi_session.py tests/test_dci_pi_rpc_proxy.py tests/test_dci_pi_rpc_recovery.py
PASS
```

### Review-fix concerns

No known concern within the assigned boundary. The repository-wide suite was
not rerun; the exact combined transport/DCI suite and owned-file static checks
are the verified boundary.

## Second review-fix follow-up

### Scope

Resolved both second-review findings within the owned transport/facade surface:

1. Added `PiRpcPromptControl.read_event()` and `request()` so the DCI settled
   `get_state` exchange reuses the active prompt deadline, cancellation signal,
   bounded polling, abort state, and common request-ID stream. DCI continues to
   own only the `get_state` response shape and idle/compaction interpretation.
2. Kept the synchronous prompt driver for the DCI facade while marshaling the
   public async session callback onto the calling event-loop thread. Async task
   cancellation now signals and aborts the driver, waits for its bounded exit,
   consumes its terminal exception, and only then performs process cleanup and
   releases the session for reuse.

### RED evidence

The three focused second-review regressions initially failed:

```text
uv run python -W error::ResourceWarning -m unittest -v \
  tests.test_dci_pi_rpc_recovery.DciPiRpcRecoveryTests.test_settled_validation_uses_common_control_and_shared_request_ids \
  tests.test_pi_session.PiRpcSessionTests.test_async_callbacks_run_on_calling_loop_thread_and_context \
  tests.test_pi_session.PiRpcSessionTests.test_async_cancellation_waits_for_prompt_driver_to_quiesce

test_settled_validation_uses_common_control_and_shared_request_ids ... FAIL
test_async_callbacks_run_on_calling_loop_thread_and_context ... FAIL
test_async_cancellation_waits_for_prompt_driver_to_quiesce ... FAIL
Ran 3 tests in 0.465s
FAILED (failures=3)
```

The async failures showed a worker-thread callback identity instead of the
calling loop thread and `driver_exited == False` when cancellation returned.
The first version of the settled test patched the shared `time` module object
too broadly; after narrowing that patch to DCI's module binding, a guard
mutation restoring the reviewed nested call produced the intended RED:

```text
test_settled_validation_uses_common_control_and_shared_request_ids ... FAIL
AssertionError: nested DCI lifecycle
Ran 1 test in 0.088s
FAILED (failures=1)
```

### GREEN evidence

Focused second-review regressions after implementation:

```text
test_settled_validation_uses_common_control_and_shared_request_ids ... ok
test_async_callbacks_run_on_calling_loop_thread_and_context ... ok
test_async_cancellation_waits_for_prompt_driver_to_quiesce ... ok
Ran 3 tests in 0.534s
OK
```

Exact combined command, with resource leaks promoted to errors:

```text
uv run python -W error::ResourceWarning -m unittest -v tests.test_pi_session tests.test_dci_pi_rpc_proxy tests.test_dci_pi_rpc_recovery tests.test_dci_pi_rpc_observation
Ran 41 tests in 4.172s
OK
```

Second-review static verification:

```text
uv run ruff check src/asterion/runtimes/pi_rpc.py tests/test_pi_session.py src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py tests/test_dci_pi_rpc_proxy.py tests/test_dci_pi_rpc_recovery.py
All checks passed!

uv run python -m py_compile src/asterion/runtimes/pi_rpc.py src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py tests/test_pi_session.py tests/test_dci_pi_rpc_proxy.py tests/test_dci_pi_rpc_recovery.py
PASS

git diff --check -- src/asterion/runtimes/pi_rpc.py tests/test_pi_session.py src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py tests/test_dci_pi_rpc_proxy.py tests/test_dci_pi_rpc_recovery.py
PASS
```

### Self-review and concerns

- The common layer owns timing/cancellation and response-ID matching but has no
  DCI provider, observation, recovery, Pathlight, or state-shape knowledge.
- Public async callbacks execute on the event-loop thread with the caller's
  context, and cleanup/reuse is conditional on driver quiescence.
- The DCI synchronous facade and its recovery/streaming behavior remain intact
  in the exact combined suite.
- No known concern within the assigned boundary. Repository-wide checks were
  not rerun; the exact requested combined suite is the verified boundary.
